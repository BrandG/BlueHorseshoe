"""Asymmetric weekend rule: at every weekend boundary, if a trade is in profit
force-close it; if it's at a loss, let it ride.

Approximates the rule by walking each weekend-spanning trade through bar-level
prices from FxStore. For each Friday 20:00-UTC bar (last H4 bar of the trading
week, closes at Sat 00:00 UTC), we compute the trade's unrealized R using
that bar's CLOSE_BID (for longs) or CLOSE_ASK (for shorts) — the spread-aware
exit price. If R > 0 at the boundary, the trade is exited there. Otherwise it
keeps walking until it hits TP, SL, the next weekend (loop continues), or
ultimately its original exit_ts.

This is a quick directional approximation. Doesn't re-run the gate overlay
(slight inaccuracy on what other trades land), but the headline numbers
(cum R, mean R, FTMO pass) tell us whether the rule is workable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "ftmo_sizing_sim"))
sys.path.insert(0, str(REPO / "src"))

from sim import SizingConfig, run_cohort, load_ftmo_config  # noqa: E402
from bh_ftmo.data.fx_store import FxStore  # noqa: E402

GATED = REPO / "research" / "v2_deploy_backtest" / "gated_ledger.csv"
OUT = REPO / "research" / "v2_deploy_backtest" / "gated_ledger_weekend_flatten_winners.csv"

TP_PCT = 0.01
STOP_PCT = 0.01


def find_weekend_close_bars(ts_array: np.ndarray) -> np.ndarray:
    """Boolean mask: True for bars opening Friday 20:00 UTC (last weekday bar)."""
    s = pd.DatetimeIndex(ts_array)
    return ((s.weekday == 4) & (s.hour == 20)).to_numpy()


def replay_trade_with_flatten(entry_ts, exit_ts, original_r, direction,
                              ts, ca, cb, hb, lb, ha, la):
    """Walk bars from entry to exit. At each Friday-20-bar, if in profit, exit.
    Returns (new_r, new_exit_ts).
    """
    # Find entry index in ts (must match exactly)
    entry_idx = np.searchsorted(ts, np.datetime64(entry_ts))
    if entry_idx >= len(ts) or ts[entry_idx] != np.datetime64(entry_ts):
        return original_r, exit_ts  # bar not found, keep original
    exit_idx = np.searchsorted(ts, np.datetime64(exit_ts))

    # Entry price (spread-aware)
    if direction == "long":
        entry = float(ca[entry_idx])
        tp = entry * (1 + TP_PCT)
        stop = entry * (1 - STOP_PCT)
        risk = entry - stop
    else:
        entry = float(cb[entry_idx])
        tp = entry * (1 - TP_PCT)
        stop = entry * (1 + STOP_PCT)
        risk = stop - entry

    # Walk forward; at every Friday 17:00 or 21:00 bar (last bar before weekend
    # close on OANDA H4 — bars open at hours 1,5,9,13,17,21 UTC, weekend gap
    # falls between Friday's last bar and Sunday's first bar).
    for j in range(entry_idx + 1, min(exit_idx + 1, len(ts))):
        bar_ts = pd.Timestamp(ts[j]).to_pydatetime()
        is_last_friday_bar = (bar_ts.weekday() == 4 and bar_ts.hour in (17, 21))
        if is_last_friday_bar:
            # Compute current R at this bar's close (spread-aware)
            if direction == "long":
                current_exit_price = float(cb[j])  # exit on bid
                current_r = (current_exit_price - entry) / risk
            else:
                current_exit_price = float(ca[j])  # exit on ask
                current_r = (entry - current_exit_price) / risk
            if current_r > 0:
                return current_r, pd.Timestamp(ts[j])
            # else: in loss, keep riding
    # Never closed by rule — keep original outcome
    return original_r, exit_ts


def main() -> int:
    print(f"Loading {GATED.name}...")
    df = pd.read_csv(GATED)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["exit_ts"]  = pd.to_datetime(df["exit_ts"])
    print(f"  {len(df):,} trades, {df['entry_ts'].min().date()} → {df['entry_ts'].max().date()}")

    # Preload FxStore for each unique pair (much faster than per-trade load)
    store = FxStore()
    pair_data = {}
    for pair in sorted(df["pair"].unique()):
        raw = store.load(pair, granularity="H4", include_incomplete=False)
        if raw is None or raw.empty:
            print(f"  WARN: no data for {pair}")
            continue
        pair_data[pair] = {
            "ts": raw["timestamp"].to_numpy(),
            "ca": raw["close_ask"].to_numpy(dtype=float),
            "cb": raw["close_bid"].to_numpy(dtype=float),
            "hb": raw["high_bid"].to_numpy(dtype=float),
            "lb": raw["low_bid"].to_numpy(dtype=float),
            "ha": raw["high_ask"].to_numpy(dtype=float),
            "la": raw["low_ask"].to_numpy(dtype=float),
        }
    store.close()
    print(f"  loaded bar data for {len(pair_data)} pairs")

    new_rs = []
    new_exits = []
    n_modified = 0
    n_winners_locked = 0
    for _, row in df.iterrows():
        pd_ = pair_data.get(row["pair"])
        if pd_ is None:
            new_rs.append(row["r"])
            new_exits.append(row["exit_ts"])
            continue
        new_r, new_exit = replay_trade_with_flatten(
            row["entry_ts"], row["exit_ts"], float(row["r"]), row["direction"],
            pd_["ts"], pd_["ca"], pd_["cb"], pd_["hb"], pd_["lb"], pd_["ha"], pd_["la"],
        )
        new_rs.append(new_r)
        new_exits.append(new_exit)
        if abs(new_r - row["r"]) > 1e-6 or new_exit != row["exit_ts"]:
            n_modified += 1
            if new_r > 0 and new_r < row["r"] + 1e-6:
                n_winners_locked += 1

    df_new = df.copy()
    df_new["r"] = new_rs
    df_new["exit_ts"] = new_exits

    print(f"\n  trades modified by rule: {n_modified:,}")
    print(f"  winners locked in early: {n_winners_locked:,}")

    # Stats comparison
    print("\n=== Original vs flatten-winners ===")
    print(f"{'metric':30s}  {'orig':>14s}   {'new':>14s}   {'Δ':>10s}")
    print("-" * 75)
    print(f"  {'trade count':28s}  {len(df):>14,d}   {len(df_new):>14,d}   {0:>+10d}")
    o_mean, n_mean = df['r'].mean(), df_new['r'].mean()
    o_cum, n_cum = df['r'].sum(), df_new['r'].sum()
    print(f"  {'mean R':28s}  {o_mean:>+14.4f}   {n_mean:>+14.4f}   {(n_mean-o_mean)/abs(o_mean)*100:>+9.1f}%")
    print(f"  {'cum R':28s}  {o_cum:>+14.1f}   {n_cum:>+14.1f}   {(n_cum-o_cum)/abs(o_cum)*100:>+9.1f}%")

    o_wins = int((df['r'] >= 1.0 - 1e-9).sum())
    n_wins = int((df_new['r'] >= 1.0 - 1e-9).sum())
    o_losses = int((df['r'] <= -1.0 + 1e-9).sum())
    n_losses = int((df_new['r'] <= -1.0 + 1e-9).sum())
    print(f"  {'wins (R>=1)':28s}  {o_wins:>14d}   {n_wins:>14d}   "
          f"{n_wins-o_wins:>+10d}")
    print(f"  {'losses (R<=-1)':28s}  {o_losses:>14d}   {n_losses:>14d}   "
          f"{n_losses-o_losses:>+10d}")
    timeouts_o = len(df) - o_wins - o_losses
    timeouts_n = len(df_new) - n_wins - n_losses
    print(f"  {'partial exits/timeouts':28s}  {timeouts_o:>14d}   {timeouts_n:>14d}   "
          f"{timeouts_n-timeouts_o:>+10d}")

    # Save and run FTMO sim
    df_new.to_csv(OUT, index=False)
    print(f"\nWrote {OUT}")

    print("\n=== FTMO Step 1 sim (sizing 0.5%, n_starts=500) ===")
    ftmo = load_ftmo_config(str(REPO / "src" / "bh_ftmo_swing_config.json"), phase="step1")
    sizing = SizingConfig(mode="fixed", risk_per_trade_pct=0.005)
    for label, ledger in (("ORIG  ", df), ("FLATTEN", df_new)):
        for model in ("realistic", "conservative"):
            c = run_cohort(ledger, ftmo, sizing, n_starts=500,
                           intra_trade_model=model, seed=42)
            results = c.pop("results", [])
            med = None
            if results:
                d = [r.days_to_resolution for r in results if r.status == "passed"]
                med = float(np.median(d)) if d else None
            med_str = f"{med:.0f}d" if med is not None else "n/a"
            print(f"  {label} {model:12s}: pass={c['pass_rate']*100:5.1f}%  "
                  f"failed={c['failed']}/{c['n_starts']}  median_pass={med_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
