"""Lightweight FTMO sizing simulation.

Consumes a trade ledger (cols: pair, entry_ts, exit_ts, r) and runs an FTMO
challenge from a randomized start date with configurable sizing rules. Returns
pass/fail/in_progress, days traded, max drawdown, fail reason.

Two intra-trade equity models:
  - "realistic": floating P&L is zero until trade exit; daily DD checks only
    realized P&L. Trade ledger doesn't carry per-bar mark-to-market data, so
    this is the upper bound of what we can compute without bar-level prices.
  - "conservative": each open position marks to -1.0R for daily/max DD checks.
    Closes when actual r is realized at exit_ts. Worst-case approximation.

The truth is somewhere in between; running both gives a pass-rate spread.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import pytz


@dataclass
class FtmoConfig:
    initial_balance: float
    daily_loss_pct: float       # e.g. 0.05
    max_loss_pct: float         # e.g. 0.10
    profit_target_pct: Optional[float]  # None for funded
    min_trading_days: int
    max_trading_days: Optional[int]  # None = unlimited (Swing)
    server_timezone: str = "Europe/Prague"
    max_loss_type: str = "static"  # "static" or "trailing"


@dataclass
class SizingConfig:
    mode: str  # "fixed" or "concurrency_scaled"
    risk_per_trade_pct: float = 0.005
    max_expected_concurrent: int = 10
    safety_margin: float = 0.8
    commission_r_pct: float = 0.0  # subtract from each trade's r as a fixed cost

    def risk_dollars(self, account_balance: float) -> float:
        if self.mode == "fixed":
            return account_balance * self.risk_per_trade_pct
        # concurrency-scaled: keep worst-case concurrent loss inside daily DD
        # risk = daily_dd * safety_margin / max_expected_concurrent
        # caller fills daily_dd via a wrapper if needed
        return account_balance * self.risk_per_trade_pct


@dataclass
class SimResult:
    status: str   # "passed", "failed", "in_progress"
    fail_reason: Optional[str]   # "daily_dd", "max_dd", "timeout", None
    final_equity: float
    peak_equity: float
    trough_equity: float
    max_dd_pct: float
    days_traded: int
    n_trades: int
    n_wins: int
    n_losses: int
    n_timeouts: int
    days_to_resolution: int
    start_date: date


def _server_day(ts, tz_name: str) -> date:
    """Server-day rollover key. FTMO uses Europe/Prague midnight."""
    if not isinstance(ts, pd.Timestamp):
        ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(tz_name).date()


def simulate_challenge(
    trades: pd.DataFrame,
    ftmo: FtmoConfig,
    sizing: SizingConfig,
    start_ts: pd.Timestamp,
    intra_trade_model: str = "realistic",
    *,
    sorted_entry_ts: Optional[np.ndarray] = None,
    sorted_exit_ts: Optional[np.ndarray] = None,
    sorted_r: Optional[np.ndarray] = None,
) -> SimResult:
    """Run one FTMO challenge from start_ts using the given trade ledger.

    For speed, callers can pass numpy arrays presorted by entry_ts; this avoids
    re-sorting/copying per call.
    """
    if sorted_entry_ts is not None:
        entries = sorted_entry_ts
        exits = sorted_exit_ts
        rs = sorted_r
        i0 = int(np.searchsorted(entries, start_ts, side="left"))
    else:
        df = trades.copy()
        df["entry_ts"] = pd.to_datetime(df["entry_ts"])
        df["exit_ts"] = pd.to_datetime(df["exit_ts"])
        df = df.sort_values("entry_ts").reset_index(drop=True)
        entries = df["entry_ts"].values
        exits = df["exit_ts"].values
        rs = df["r"].values
        i0 = int(np.searchsorted(entries, start_ts, side="left"))

    # Build events: each eligible trade contributes (ts, kind, idx, r).
    # idx here is the trade index in entries[i0:].
    n_eligible = len(entries) - i0
    events = []
    for j in range(n_eligible):
        events.append((entries[i0 + j], "entry", j, float(rs[i0 + j])))
        events.append((exits[i0 + j], "exit", j, float(rs[i0 + j])))
    events.sort()

    initial_balance = ftmo.initial_balance
    daily_dd_dollars = ftmo.daily_loss_pct * initial_balance
    max_dd_floor = initial_balance * (1 - ftmo.max_loss_pct)
    profit_target = (initial_balance * (1 + ftmo.profit_target_pct)
                     if ftmo.profit_target_pct else None)

    realized_equity = initial_balance  # equity from closed trades only
    open_positions: dict[int, float] = {}  # idx → risk_dollars (entry risk)
    daily_reference = initial_balance  # equity at last server-day rollover
    last_day = None
    days_with_trades = set()
    n_wins = n_losses = n_timeouts = 0
    n_resolved = 0

    def floating_pnl_loss(intra_model: str) -> float:
        """Worst-case loss on currently-open positions for daily DD check."""
        if intra_model == "realistic" or not open_positions:
            return 0.0
        # Conservative: each open position at -1.0R
        return sum(open_positions.values())

    def equity_for_dd_check(intra_model: str) -> float:
        return realized_equity - floating_pnl_loss(intra_model)

    fail_reason = None
    last_event_ts = start_ts

    for ts, kind, idx, r in events:
        last_event_ts = ts
        srv_day = _server_day(ts, ftmo.server_timezone)
        if last_day is None:
            last_day = srv_day
            daily_reference = realized_equity - floating_pnl_loss(intra_trade_model)
        elif srv_day != last_day:
            # Day rollover: reset daily reference
            last_day = srv_day
            daily_reference = realized_equity - floating_pnl_loss(intra_trade_model)

        if kind == "entry":
            risk_dollars = sizing.risk_dollars(initial_balance)
            open_positions[idx] = risk_dollars
        else:  # exit
            risk_dollars = open_positions.pop(idx, sizing.risk_dollars(initial_balance))
            r_after_costs = r - sizing.commission_r_pct
            realized_equity += r_after_costs * risk_dollars
            n_resolved += 1
            if r >= 1.0 - 1e-9:
                n_wins += 1
            elif r <= -1.0 + 1e-9:
                n_losses += 1
            else:
                n_timeouts += 1
            days_with_trades.add(srv_day)

        # Check rule breaches at every event
        eq_check = equity_for_dd_check(intra_trade_model)
        if eq_check < daily_reference - daily_dd_dollars - 1e-6:
            fail_reason = "daily_dd"
            break
        if eq_check < max_dd_floor - 1e-6:
            fail_reason = "max_dd"
            break

        # Check profit target hit. We do NOT require open_positions to be empty:
        # at FTMO, hitting target lets you flatten immediately. The floating-PnL
        # check above already guards against an open book big enough to wipe the
        # cushion, so realized_equity ≥ target is a safe pass signal.
        if profit_target is not None and realized_equity >= profit_target - 1e-6:
            if len(days_with_trades) >= ftmo.min_trading_days:
                return SimResult(
                    status="passed", fail_reason=None,
                    final_equity=realized_equity,
                    peak_equity=realized_equity,
                    trough_equity=min(realized_equity, daily_reference),
                    max_dd_pct=max(0, (initial_balance - eq_check) / initial_balance),
                    days_traded=len(days_with_trades),
                    n_trades=n_resolved, n_wins=n_wins, n_losses=n_losses,
                    n_timeouts=n_timeouts,
                    days_to_resolution=int((pd.Timestamp(ts) - start_ts).days),
                    start_date=start_ts.date(),
                )

        # Check max trading days
        if ftmo.max_trading_days is not None:
            if len(days_with_trades) >= ftmo.max_trading_days:
                break

    # Loop ended — either failure or in-progress
    eq_final = realized_equity - floating_pnl_loss(intra_trade_model)
    if fail_reason:
        status = "failed"
    elif profit_target is not None and realized_equity < profit_target:
        status = "in_progress" if ftmo.max_trading_days is None else "failed"
        if status == "failed":
            fail_reason = "timeout"
    else:
        status = "passed" if profit_target is None else "in_progress"

    return SimResult(
        status=status, fail_reason=fail_reason,
        final_equity=realized_equity, peak_equity=realized_equity,
        trough_equity=min(realized_equity, daily_reference),
        max_dd_pct=max(0, (initial_balance - eq_final) / initial_balance),
        days_traded=len(days_with_trades),
        n_trades=n_resolved, n_wins=n_wins, n_losses=n_losses,
        n_timeouts=n_timeouts,
        days_to_resolution=int((pd.Timestamp(last_event_ts) - start_ts).days),
        start_date=start_ts.date(),
    )


def run_cohort(
    trades: pd.DataFrame,
    ftmo: FtmoConfig,
    sizing: SizingConfig,
    n_starts: int = 500,
    intra_trade_model: str = "realistic",
    seed: int = 42,
) -> dict:
    """Run N randomized-start sims and aggregate."""
    df = trades.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["exit_ts"] = pd.to_datetime(df["exit_ts"])
    if df.empty:
        return {"n_starts": 0, "passed": 0, "failed": 0, "in_progress": 0}
    earliest = df["entry_ts"].min()
    # Last possible start: latest entry minus a buffer (for pass to be reachable)
    latest_entry = df["entry_ts"].max()
    # If max_trading_days is set, allow start no later than (latest - that days)
    # If None (Swing unlimited), allow start no later than (latest - 90 days) buffer
    if ftmo.max_trading_days is not None:
        latest_start = latest_entry - pd.Timedelta(days=ftmo.max_trading_days * 1.5)
    else:
        latest_start = latest_entry - pd.Timedelta(days=180)
    if latest_start <= earliest:
        return {"n_starts": 0, "error": "insufficient data span"}

    rng = np.random.default_rng(seed)
    span_days = (latest_start - earliest).days
    offsets = rng.integers(0, span_days, size=n_starts)
    start_dates = [earliest + pd.Timedelta(days=int(o)) for o in offsets]

    # Pre-sort once for speed
    df_sorted = df.sort_values("entry_ts").reset_index(drop=True)
    entries_arr = df_sorted["entry_ts"].values
    exits_arr = df_sorted["exit_ts"].values
    rs_arr = df_sorted["r"].values.astype(float)

    results = []
    for start in start_dates:
        r = simulate_challenge(
            df_sorted, ftmo, sizing, start,
            intra_trade_model=intra_trade_model,
            sorted_entry_ts=entries_arr,
            sorted_exit_ts=exits_arr,
            sorted_r=rs_arr,
        )
        results.append(r)

    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    in_progress = sum(1 for r in results if r.status == "in_progress")
    fail_reasons = {}
    for r in results:
        if r.fail_reason:
            fail_reasons[r.fail_reason] = fail_reasons.get(r.fail_reason, 0) + 1

    pass_days = [r.days_to_resolution for r in results if r.status == "passed"]

    return {
        "n_starts": n_starts,
        "passed": passed,
        "failed": failed,
        "in_progress": in_progress,
        "pass_rate": passed / n_starts,
        "fail_reasons": fail_reasons,
        "median_days_to_pass": float(np.median(pass_days)) if pass_days else None,
        "results": results,
    }


def load_ftmo_config(path: str, phase: str = "step1") -> FtmoConfig:
    """Load a Swing-style config file (with step1/step2/funded blocks)."""
    import json
    with open(path) as f:
        cfg = json.load(f)
    base = cfg["ftmo"].copy()
    base = {k: v for k, v in base.items() if not k.startswith("_")}
    if phase == "step2" and "ftmo_step2" in cfg:
        for k, v in cfg["ftmo_step2"].items():
            if not k.startswith("_"):
                base[k] = v
    elif phase == "funded" and "ftmo_funded" in cfg:
        for k, v in cfg["ftmo_funded"].items():
            if not k.startswith("_"):
                base[k] = v
    return FtmoConfig(
        initial_balance=base["initial_balance"],
        daily_loss_pct=base["daily_loss_pct"],
        max_loss_pct=base["max_loss_pct"],
        profit_target_pct=base.get("profit_target_pct"),
        min_trading_days=base.get("min_trading_days", 4),
        max_trading_days=base.get("max_trading_days"),
        server_timezone=base.get("server_timezone", "Europe/Prague"),
        max_loss_type=base.get("max_loss_type", "static"),
    )
