"""Single-signal edge testing harness.

The production FTMO engine is great for survival simulation, but it's the
wrong tool for "does my candidate signal have positive R expectancy?" — that
question doesn't need cohorts, walk-forward folds, overlays, or DD limits.

This module gives you a thin, readable harness that:
  - takes a signal function (callable: bars -> Series of -1/0/+1)
  - opens a position at the signal bar's close, exits at first of stop/target/timeout
  - reports per-trade R distribution, win rate, profit factor, bootstrap CI

No challenge simulation, no overlay, no daily-loss cap, no equity tracking.
Just: "if I traded this signal, what's the per-trade outcome distribution?"

Usage:

    from bh_ftmo.research.test_signal import test_signal, print_result

    def my_sma_cross(bars):
        sma_fast = bars["close"].rolling(20).mean()
        sma_slow = bars["close"].rolling(50).mean()
        return ((sma_fast > sma_slow) & (sma_fast.shift(1) <= sma_slow.shift(1))).astype(int)

    result = test_signal(my_sma_cross, pairs=["EUR_USD", "GBP_USD"])
    print_result(result)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import pandas as pd

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import ohlc_mid


SignalFn = Callable[[pd.DataFrame], pd.Series]
"""Signal callable. Takes a bar DataFrame with at least columns
``timestamp, open, high, low, close``. Returns a Series of ints aligned to
the input rows: ``+1`` = enter long this bar, ``-1`` = enter short, ``0`` =
no signal."""


@dataclass
class TradeResult:
    pair: str
    entry_ts: datetime
    exit_ts: datetime
    direction: int
    entry_price: float
    exit_price: float
    outcome: str  # "win", "loss", "timeout"
    bars_held: int
    r: float


@dataclass
class SignalTestResult:
    n_trades: int
    n_wins: int
    n_losses: int
    n_timeouts: int
    win_rate: float
    avg_r: float
    median_r: float
    profit_factor: float
    median_bars_held: int
    avg_r_ci_95: tuple[float, float]
    trades: list[TradeResult] = field(default_factory=list)


def test_signal(
    signal_fn: SignalFn,
    pairs: list[str],
    *,
    stop_pct: float = 0.005,
    target_pct: float = 0.0075,
    max_hold_bars: int = 84,
    granularity: str = "H4",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    spread_pct: float = 0.0,
    rng_seed: int = 0,
    bootstrap_b: int = 1000,
) -> SignalTestResult:
    """Test a signal across pairs, return aggregate stats + raw trades.

    For each fired signal, open at the bar's close, exit at first of:
      - stop_pct adverse move (bar's low for longs, high for shorts)
      - target_pct favorable move
      - max_hold_bars elapsed (timeout — exit at that bar's close)

    R is computed as (P&L) / (entry - stop) so target = +(target/stop) R,
    stop = -1 R, timeout = whatever the close gives. Optional ``spread_pct``
    is subtracted from each trade's R as a flat cost approximation; for
    realistic per-pair spread/swap modeling, use the production engine.
    """
    if not pairs:
        raise ValueError("pairs must be non-empty")
    if stop_pct <= 0 or target_pct <= 0:
        raise ValueError("stop_pct and target_pct must be positive")

    store = FxStore()
    trades: list[TradeResult] = []

    for pair in pairs:
        raw = store.load(
            pair,
            granularity=granularity,
            start=start,
            end=end,
            include_incomplete=False,
        )
        if raw is None or raw.empty:
            continue

        # FxStore returns bid+ask; collapse to mid OHLC for signal generation
        # and trade simulation. (For tighter spread modeling, use the
        # production engine; this harness models spread as a flat ``spread_pct``.)
        bars = ohlc_mid(raw).copy()
        bars["timestamp"] = raw["timestamp"].values
        bars = bars.reset_index(drop=True)

        signals = signal_fn(bars)
        if not isinstance(signals, pd.Series):
            raise TypeError(f"signal_fn must return a pd.Series, got {type(signals)}")
        if len(signals) != len(bars):
            raise ValueError(
                f"signal_fn returned {len(signals)} signals for {len(bars)} bars"
            )

        signal_values = signals.fillna(0).astype(int).to_numpy()
        timestamps = bars["timestamp"].to_numpy()
        closes = bars["close"].to_numpy(dtype=float)
        highs = bars["high"].to_numpy(dtype=float)
        lows = bars["low"].to_numpy(dtype=float)
        n = len(bars)

        for i in range(n):
            direction = int(signal_values[i])
            if direction == 0:
                continue
            if i + max_hold_bars >= n:
                break

            entry_price = closes[i]
            entry_ts = timestamps[i]

            if direction > 0:
                stop_price = entry_price * (1 - stop_pct)
                target_price = entry_price * (1 + target_pct)
            else:
                stop_price = entry_price * (1 + stop_pct)
                target_price = entry_price * (1 - target_pct)

            outcome = "timeout"
            exit_idx = i + max_hold_bars
            exit_price = closes[exit_idx]
            exit_ts = timestamps[exit_idx]
            bars_held = max_hold_bars

            for j in range(1, max_hold_bars + 1):
                k = i + j
                if direction > 0:
                    if lows[k] <= stop_price:
                        outcome, exit_price = "loss", stop_price
                        exit_ts, bars_held = timestamps[k], j
                        break
                    if highs[k] >= target_price:
                        outcome, exit_price = "win", target_price
                        exit_ts, bars_held = timestamps[k], j
                        break
                else:
                    if highs[k] >= stop_price:
                        outcome, exit_price = "loss", stop_price
                        exit_ts, bars_held = timestamps[k], j
                        break
                    if lows[k] <= target_price:
                        outcome, exit_price = "win", target_price
                        exit_ts, bars_held = timestamps[k], j
                        break

            risk_distance = entry_price * stop_pct
            if direction > 0:
                pnl = exit_price - entry_price
            else:
                pnl = entry_price - exit_price
            r_value = pnl / risk_distance
            if spread_pct > 0:
                r_value -= spread_pct / stop_pct

            trades.append(
                TradeResult(
                    pair=pair,
                    entry_ts=pd.Timestamp(entry_ts).to_pydatetime(),
                    exit_ts=pd.Timestamp(exit_ts).to_pydatetime(),
                    direction=direction,
                    entry_price=float(entry_price),
                    exit_price=float(exit_price),
                    outcome=outcome,
                    bars_held=bars_held,
                    r=float(r_value),
                )
            )

    return _aggregate(trades, rng_seed=rng_seed, bootstrap_b=bootstrap_b)


def _aggregate(
    trades: list[TradeResult],
    *,
    rng_seed: int,
    bootstrap_b: int,
) -> SignalTestResult:
    n = len(trades)
    if n == 0:
        return SignalTestResult(
            n_trades=0, n_wins=0, n_losses=0, n_timeouts=0,
            win_rate=0.0, avg_r=0.0, median_r=0.0, profit_factor=0.0,
            median_bars_held=0, avg_r_ci_95=(0.0, 0.0), trades=[],
        )

    n_wins = sum(1 for t in trades if t.outcome == "win")
    n_losses = sum(1 for t in trades if t.outcome == "loss")
    n_timeouts = sum(1 for t in trades if t.outcome == "timeout")
    rs = np.array([t.r for t in trades], dtype=float)

    gross_wins = float(rs[rs > 0].sum())
    gross_losses = float(-rs[rs < 0].sum())
    profit_factor = (
        gross_wins / gross_losses if gross_losses > 0 else float("inf")
    )

    rng = np.random.default_rng(rng_seed)
    bootstrap_samples = rng.choice(rs, size=(bootstrap_b, n), replace=True).mean(axis=1)
    ci_low, ci_high = np.percentile(bootstrap_samples, [2.5, 97.5])

    return SignalTestResult(
        n_trades=n,
        n_wins=n_wins,
        n_losses=n_losses,
        n_timeouts=n_timeouts,
        win_rate=n_wins / n,
        avg_r=float(rs.mean()),
        median_r=float(np.median(rs)),
        profit_factor=profit_factor,
        median_bars_held=int(np.median([t.bars_held for t in trades])),
        avg_r_ci_95=(float(ci_low), float(ci_high)),
        trades=trades,
    )


def print_result(result: SignalTestResult) -> None:
    if result.n_trades == 0:
        print("No trades fired.")
        return
    print(f"Trades:           {result.n_trades}")
    print(f"  wins / losses / timeouts: {result.n_wins} / {result.n_losses} / {result.n_timeouts}")
    print(f"Win rate:         {result.win_rate:.1%}")
    print(f"Avg R:            {result.avg_r:+.4f}  (95% CI: {result.avg_r_ci_95[0]:+.4f} to {result.avg_r_ci_95[1]:+.4f})")
    print(f"Median R:         {result.median_r:+.4f}")
    print(f"Profit factor:    {result.profit_factor:.2f}")
    print(f"Median bars held: {result.median_bars_held}")
    verdict = (
        "POSITIVE EDGE (95% CI excludes zero)"
        if result.avg_r_ci_95[0] > 0
        else "NEGATIVE EDGE (95% CI excludes zero)"
        if result.avg_r_ci_95[1] < 0
        else "NO CLEAR EDGE (CI straddles zero)"
    )
    print(f"Verdict:          {verdict}")


# ---- Example signal: SMA cross ------------------------------------------


def sma_cross_long(bars: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    """Long when SMA(fast) crosses above SMA(slow). Example signal_fn."""
    sma_fast = bars["close"].rolling(fast).mean()
    sma_slow = bars["close"].rolling(slow).mean()
    crossed = (sma_fast > sma_slow) & (sma_fast.shift(1) <= sma_slow.shift(1))
    return crossed.astype(int)


if __name__ == "__main__":
    pairs = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "USD_CHF", "AUD_USD"]
    print(f"Testing SMA(20) crosses above SMA(50) on {pairs}, H4, last ~6 years...")
    result = test_signal(sma_cross_long, pairs=pairs)
    print_result(result)
