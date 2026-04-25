"""Three null-strategy baselines for the BH FTMO Phase 3 entry-edge gate.

Per decision 17B, the gate compares BH FTMO's pass-rate against the best
of these three baselines and requires a >=10pp margin. This module produces
the signal lists that drive each baseline through the engine; execution
(sizing, stops, fills, FTMO rules, weekend flatten) lives in the engine
and is identical across all four strategy types.

All three classes are picklable for ProcessPoolExecutor fan-out (P3-9).
Randomness is seeded via numpy.random.default_rng for reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import ClassVar, Sequence

import numpy as np
import pandas as pd

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.indicators.momentum import rsi


def _sorted_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a timestamp-sorted copy with a normalized timestamp column."""

    normalized = frame.copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"])
    return normalized.sort_values("timestamp").reset_index(drop=True)


def _signal(
    *,
    symbol: str,
    strategy: str,
    timestamp: object,
    direction: int,
    components: dict[str, float],
) -> Signal:
    """Build a threshold-passing baseline signal."""

    return Signal(
        symbol=symbol,
        strategy=strategy,
        timestamp=pd.Timestamp(timestamp).to_pydatetime(),
        direction=direction,
        score=1.0,
        components=components,
        above_threshold=True,
    )


def _bid_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    """Project bid-space OHLC columns into the indicator contract."""

    return frame.rename(
        columns={
            "open_bid": "open",
            "high_bid": "high",
            "low_bid": "low",
            "close_bid": "close",
        }
    )[["open", "high", "low", "close"]]


@dataclass(frozen=True)
class RandomEntryAtrExitStrategy:
    """Uniform-random entry baseline.

    For each 4h bar across the configured symbols, with probability
    ``signal_density``, emit a Signal with random direction (+1 or -1, 50/50).
    Engine handles ATR-based stop/target via its standard trade factory path.

    Deterministic given ``(seed, symbols, signal_density, bar set)``.
    """

    STRATEGY_NAME: ClassVar[str] = "random_baseline"

    seed: int
    symbols: tuple[str, ...]
    signal_density: float = 0.05

    def __init__(
        self,
        seed: int,
        symbols: Sequence[str],
        signal_density: float = 0.05,
    ) -> None:
        """Store a pickle-safe random baseline configuration."""

        if not 0.0 <= signal_density <= 1.0:
            raise ValueError("signal_density must be within [0.0, 1.0]")
        object.__setattr__(self, "seed", int(seed))
        object.__setattr__(self, "symbols", tuple(symbols))
        object.__setattr__(self, "signal_density", float(signal_density))

    def generate_signals(
        self,
        bars_4h: dict[str, pd.DataFrame],
    ) -> list[Signal]:
        """Generate uniform-random threshold-passing entry signals."""

        rng = np.random.default_rng(self.seed)
        directions = np.array([-1, 1], dtype=int)
        signals: list[Signal] = []
        for symbol in self.symbols:
            if symbol not in bars_4h:
                continue
            frame = _sorted_bars(bars_4h[symbol])
            for row in frame.itertuples(index=False):
                if rng.random() >= self.signal_density:
                    continue
                direction = int(rng.choice(directions))
                signals.append(
                    _signal(
                        symbol=symbol,
                        strategy=self.STRATEGY_NAME,
                        timestamp=row.timestamp,
                        direction=direction,
                        components={"random": 1.0},
                    )
                )
        return sorted(signals, key=lambda signal: (signal.timestamp, signal.symbol))


@dataclass(frozen=True)
class MondayInFridayOutStrategy:
    """Fixed-schedule time-in-market baseline.

    Emit one long signal per Monday on the configured symbol. The engine's
    weekend flatten logic performs the Friday exit; this strategy emits
    entries only.
    """

    STRATEGY_NAME: ClassVar[str] = "monday_friday"

    symbol: str = "EUR_USD"

    def generate_signals(
        self,
        bars_4h: dict[str, pd.DataFrame],
    ) -> list[Signal]:
        """Emit one long signal for each Monday, preferring the 00:00 UTC bar."""

        if self.symbol not in bars_4h:
            return []

        frame = _sorted_bars(bars_4h[self.symbol])
        monday_rows = frame[frame["timestamp"].dt.weekday == 0]
        if monday_rows.empty:
            return []

        signals: list[Signal] = []
        for _, weekly_rows in monday_rows.groupby(monday_rows["timestamp"].dt.normalize()):
            exact_match = weekly_rows[weekly_rows["timestamp"].dt.time == time(0, 0)]
            entry_row = exact_match.iloc[0] if not exact_match.empty else weekly_rows.iloc[0]
            signals.append(
                _signal(
                    symbol=self.symbol,
                    strategy=self.STRATEGY_NAME,
                    timestamp=entry_row["timestamp"],
                    direction=1,
                    components={"monday_in": 1.0},
                )
            )
        return signals


@dataclass(frozen=True)
class SimpleRsi14Strategy:
    """Simple RSI(14) oversold/overbought baseline on bid-space closes."""

    STRATEGY_NAME: ClassVar[str] = "rsi_14"

    symbols: tuple[str, ...]
    oversold: float = 30.0
    overbought: float = 70.0
    rsi_window: int = 14

    def __init__(
        self,
        symbols: Sequence[str],
        oversold: float = 30.0,
        overbought: float = 70.0,
        rsi_window: int = 14,
    ) -> None:
        """Store a pickle-safe RSI baseline configuration."""

        if rsi_window < 1:
            raise ValueError("rsi_window must be >= 1")
        if oversold >= overbought:
            raise ValueError("oversold must be below overbought")
        object.__setattr__(self, "symbols", tuple(symbols))
        object.__setattr__(self, "oversold", float(oversold))
        object.__setattr__(self, "overbought", float(overbought))
        object.__setattr__(self, "rsi_window", int(rsi_window))

    def generate_signals(
        self,
        bars_4h: dict[str, pd.DataFrame],
    ) -> list[Signal]:
        """Generate long/short signals when bid-space RSI crosses thresholds."""

        signals: list[Signal] = []
        for symbol in self.symbols:
            if symbol not in bars_4h:
                continue
            frame = _sorted_bars(bars_4h[symbol])
            rsi_series = rsi(_bid_ohlc(frame), period=self.rsi_window)
            for idx, row in enumerate(frame.itertuples(index=False)):
                if idx < self.rsi_window or pd.isna(rsi_series.iloc[idx]):
                    continue
                rsi_value = float(rsi_series.iloc[idx])
                if rsi_value < self.oversold:
                    signals.append(
                        _signal(
                            symbol=symbol,
                            strategy=self.STRATEGY_NAME,
                            timestamp=row.timestamp,
                            direction=1,
                            components={"rsi_oversold": 1.0},
                        )
                    )
                elif rsi_value > self.overbought:
                    signals.append(
                        _signal(
                            symbol=symbol,
                            strategy=self.STRATEGY_NAME,
                            timestamp=row.timestamp,
                            direction=-1,
                            components={"rsi_overbought": 1.0},
                        )
                    )
        return sorted(signals, key=lambda signal: (signal.timestamp, signal.symbol))
