"""SandboxStrategy - event-based 3-signal portfolio validated 2026-04-29.

Produces Signals for three rules:
  - stoch_oversold_cross (long, all pairs)
  - sma_cross_long (long, all pairs)
  - rsi_overbought_cross (short, restricted to configured validated pairs)

Pair restriction: rsi_overbought only fires on the pairs in
``sandbox_v1.short_pair_whitelist``. See SESSION_HANDOFF.md (April 28-29 2026)
for the validation methodology and walk-forward results.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from bh_ftmo.analysis.strategy import Signal, load_weights
from bh_ftmo.indicators import ohlc_mid, rsi, sma, stochastic


class SandboxStrategy:
    """Event-based sandbox_v1 scoring.

    A bar emits a binary score when any of the validated events fires:

      - ``stoch_oversold_cross_long``: Stochastic %K crosses up through 20
      - ``sma_cross_long``: SMA(20) crosses above SMA(50)
      - ``rsi_overbought_cross_short``: RSI(14) crosses down through 70,
        restricted to the validated short whitelist

    Long/short ties resolve to long, matching BaselineStrategy's convention.
    """

    name = "sandbox_v1"

    def __init__(
        self,
        weights: Optional[dict] = None,
        *,
        sma_fast: int = 20,
        sma_slow: int = 50,
        stoch_period: int = 14,
        stoch_threshold: float = 20.0,
        rsi_period: int = 14,
        rsi_threshold: float = 70.0,
    ) -> None:
        if weights is None:
            weights = load_weights()
        strat_cfg = weights.get(self.name)
        if strat_cfg is None:
            raise ValueError(f"weights file has no '{self.name}' strategy block")

        self._component_weights: dict[str, float] = dict(strat_cfg.get("components", {}))
        self.min_score_threshold: float = float(strat_cfg.get("min_score_threshold", 0.0))
        self.sma_fast = sma_fast
        self.sma_slow = sma_slow
        self.stoch_period = stoch_period
        self.stoch_threshold = float(stoch_threshold)
        self.rsi_period = rsi_period
        self.rsi_threshold = float(rsi_threshold)

        if "short_pair_whitelist" not in strat_cfg:
            raise ValueError(
                f"weights file '{self.name}' block has no short_pair_whitelist"
            )
        resolved_whitelist = strat_cfg["short_pair_whitelist"]
        self.short_pair_whitelist = frozenset(
            str(symbol).upper() for symbol in resolved_whitelist
        )

    @property
    def component_weights(self) -> dict[str, float]:
        return dict(self._component_weights)

    def score_pair(
        self,
        pair_df: pd.DataFrame,
        *,
        symbol: str,
        dxy: Optional[pd.Series] = None,
        strengths: Optional[pd.DataFrame] = None,
    ) -> list[Signal]:
        """Score every bar in ``pair_df``. ``dxy`` and ``strengths`` are unused."""
        if "timestamp" not in pair_df.columns:
            raise ValueError("pair_df must have a 'timestamp' column")
        if len(pair_df) == 0:
            return []

        ohlc = ohlc_mid(pair_df)
        timestamps = pair_df["timestamp"].to_list()

        sma_fast = sma(ohlc, period=self.sma_fast)
        sma_slow = sma(ohlc, period=self.sma_slow)
        stoch_k = stochastic(ohlc, k_period=self.stoch_period)["k"]
        rsi_series = rsi(ohlc, period=self.rsi_period)

        stoch_long = (stoch_k.shift(1) < self.stoch_threshold) & (
            stoch_k >= self.stoch_threshold
        )
        sma_long = (sma_fast.shift(1) <= sma_slow.shift(1)) & (sma_fast > sma_slow)
        rsi_short = (rsi_series.shift(1) > self.rsi_threshold) & (
            rsi_series <= self.rsi_threshold
        )

        symbol_key = symbol.upper()
        short_allowed = symbol_key in self.short_pair_whitelist
        w = self._component_weights

        signals: list[Signal] = []
        for i, ts in enumerate(timestamps):
            long_components: dict[str, float] = {}
            short_components: dict[str, float] = {}

            if bool(stoch_long.iloc[i]):
                long_components["stoch_oversold_cross_long"] = w.get(
                    "stoch_oversold_cross_long", 1.0
                )
            if bool(sma_long.iloc[i]):
                long_components["sma_cross_long"] = w.get("sma_cross_long", 1.0)
            if short_allowed and bool(rsi_short.iloc[i]):
                short_components["rsi_overbought_cross_short"] = w.get(
                    "rsi_overbought_cross_short", 1.0
                )

            if long_components:
                direction = +1
                components = long_components
                score = 1.0
            elif short_components:
                direction = -1
                components = short_components
                score = 1.0
            else:
                direction = 0
                components = {}
                score = 0.0

            signals.append(
                Signal(
                    symbol=symbol,
                    strategy=self.name,
                    timestamp=ts,
                    direction=direction,
                    score=score,
                    components=components,
                    above_threshold=score > 0,
                )
            )

        return signals
