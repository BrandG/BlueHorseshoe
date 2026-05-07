"""Phase III: re-test rising_3bar at 1.0%/1.0% RR and shorter MAX_HOLD.

Rising_3bar = stoch K rises 3 bars from below 20 (long-only), validated at
1.5%/1.5% with MAX_HOLD = 14 × 6 bars per memory. The deployed v2 portfolio
is at 1.0%/1.0% with a 5d cap on limit cells. Phase III asks:
  - Does rising_3bar's edge survive at 1.0% RR?
  - Does it survive at 5d MAX_HOLD?
  - Does the combination (proposed v2-aligned config) work?

Generates four trade ledgers:
  - 1.5%/1.5% × 14d   (canonical baseline — reproduce known result)
  - 1.5%/1.5% × 5d    (effect of cap alone)
  - 1.0%/1.0% × 14d   (effect of RR alone)
  - 1.0%/1.0% × 5d    (proposed v2-aligned config)

Runs FTMO Step-1 sim on each and prints a side-by-side comparison.
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
from bh_ftmo.indicators import stochastic, ohlc_mid  # noqa: E402

OUT_DIR = REPO / "research" / "v2_deploy_backtest" / "phase3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 40-pair OANDA universe
PAIRS = [
    "EUR_USD", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD", "USD_SEK",
    "AUD_CHF", "AUD_NZD", "AUD_CAD", "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD",
    "EUR_CZK", "CAD_JPY", "CAD_CHF", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "GBP_AUD", "GBP_CAD", "GBP_CHF", "GBP_NZD", "CHF_JPY", "NZD_JPY", "AUD_JPY",
    "USD_SGD", "USD_PLN", "USD_CZK", "USD_HUF", "EUR_HUF", "EUR_PLN", "EUR_SEK",
    "NZD_CAD", "NZD_CHF", "EUR_NOK", "USD_ZAR", "USD_NOK",
]
GRANULARITY = "H4"
N_STARTS = 500


def find_rising3bar(k: np.ndarray) -> np.ndarray:
    """K rising 3 bars (strictly), with K[i-3] < 20 and K[i-1], K[i-2] valid.
    Mirrors src/bh_ftmo_paper.py::evaluate_trigger_on_last_bar shape.
    Returns indices of fires in the bar array.
    """
    n = len(k)
    if n < 4:
        return np.array([], dtype=int)
    rising = np.zeros(n, dtype=bool)
    rising[3:] = (k[3:] > k[2:-1]) & (k[2:-1] > k[1:-2])
    base = np.full(n, np.nan)
    base[3:] = k[:-3]
    cond = (~np.isnan(base) & ~np.isnan(k) & rising & (base < 20.0))
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def sim_long_spread(ca, hb, lb, cb, i, max_hold, tp_pct, stop_pct):
    """Spread-aware long sim — entry at ASK close, exits checked vs BID side.
    Returns (r, exit_idx) or (None, None) if not enough future data.
    """
    if i + max_hold >= len(ca):
        return None, None
    entry = ca[i]
    tp = entry * (1 + tp_pct)
    stop = entry * (1 - stop_pct)
    risk = entry - stop
    for j in range(1, max_hold + 1):
        k = i + j
        if lb[k] <= stop:
            return -1.0, k
        if hb[k] >= tp:
            return (tp - entry) / risk, k
    exit_p = cb[i + max_hold]
    return (exit_p - entry) / risk, i + max_hold


def collect_trades(pair: str, tp_pct: float, stop_pct: float, max_hold: int) -> list[dict]:
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    k = stochastic(mid, k_period=14)["k"].to_numpy()
    triggers = find_rising3bar(k)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy()
    hb = raw["high_bid"].to_numpy()
    lb = raw["low_bid"].to_numpy()
    cb = raw["close_bid"].to_numpy()
    trades = []
    for i in triggers:
        i = int(i)
        r, exit_idx = sim_long_spread(ca, hb, lb, cb, i, max_hold, tp_pct, stop_pct)
        if r is None:
            continue
        trades.append({
            "pair": pair,
            "entry_ts": pd.Timestamp(ts[i]),
            "exit_ts": pd.Timestamp(ts[exit_idx]),
            "r": r,
        })
    return trades


def stats(df: pd.DataFrame) -> dict:
    rs = df["r"].to_numpy()
    n = len(rs)
    wins = int((rs >= 1.0 - 1e-9).sum())
    losses = int((rs <= -1.0 + 1e-9).sum())
    wr = wins / max(wins + losses, 1)
    cum_r = np.cumsum(rs)
    running_max = np.maximum.accumulate(cum_r)
    max_dd = float((cum_r - running_max).min()) if n else 0.0
    dur = (pd.to_datetime(df["exit_ts"]) - pd.to_datetime(df["entry_ts"])).dt.total_seconds() / 86400 if n else pd.Series([0])
    return {
        "n": n, "wins": wins, "losses": losses, "wr": wr,
        "mean_r": float(rs.mean()) if n else 0.0,
        "cum_r": float(rs.sum()) if n else 0.0,
        "max_dd_r": max_dd,
        "dur_p50": float(np.percentile(dur, 50)) if n else 0.0,
        "dur_p75": float(np.percentile(dur, 75)) if n else 0.0,
    }


def main() -> int:
    configs = [
        ("1.5x14d", 0.015, 0.015, 14 * 6),  # baseline
        ("1.5x5d",  0.015, 0.015, 30),
        ("1.0x14d", 0.010, 0.010, 14 * 6),
        ("1.0x5d",  0.010, 0.010, 30),       # proposed
    ]
    ftmo = load_ftmo_config(str(REPO / "src" / "bh_ftmo_swing_config.json"), phase="step1")

    results = []
    for label, tp_pct, stop_pct, max_hold in configs:
        print(f"\n=== {label}  TP={tp_pct*100:.1f}%  STOP={stop_pct*100:.1f}%  MAX_HOLD={max_hold} bars ({max_hold/6:.0f}d) ===", flush=True)
        all_trades = []
        for pair in PAIRS:
            try:
                tr = collect_trades(pair, tp_pct, stop_pct, max_hold)
            except Exception as exc:
                print(f"  {pair}: error {exc}")
                continue
            all_trades.extend(tr)
        df = pd.DataFrame(all_trades).sort_values("entry_ts").reset_index(drop=True)
        s = stats(df)
        print(f"  trades={s['n']:>5d}  W/L={s['wins']}/{s['losses']}  WR={s['wr']*100:.1f}%  "
              f"mean_R={s['mean_r']:+.4f}  cum_R={s['cum_r']:+.1f}  "
              f"max_DD={s['max_dd_r']:.1f}R  dur p50/p75={s['dur_p50']:.1f}/{s['dur_p75']:.1f}d")
        out_path = OUT_DIR / f"rising3bar_{label.replace('.','p')}.csv"
        df.to_csv(out_path, index=False)

        # FTMO sim at deployed rising_3bar sizing (1%) for both intra-trade models
        sizing = SizingConfig(mode="fixed", risk_per_trade_pct=0.01)
        ftmo_results = {}
        for model in ("realistic", "conservative"):
            c = run_cohort(df, ftmo, sizing, n_starts=N_STARTS,
                           intra_trade_model=model, seed=42)
            results_list = c.pop("results", [])
            if results_list:
                d = [r.days_to_resolution for r in results_list if r.status == "passed"]
                c["pass_days_p50"] = float(np.median(d)) if d else None
            ftmo_results[model] = c
            med = c.get("pass_days_p50")
            med_str = f"{med:.0f}d" if med is not None else "n/a"
            print(f"  FTMO {model:12s}: pass={c['pass_rate']*100:5.1f}%  median={med_str}")
        results.append((label, s, ftmo_results))

    print()
    print("=== Summary table ===")
    print(f"{'config':10s}  {'trades':>7s}  {'WR':>6s}  {'meanR':>8s}  {'cumR':>9s}  "
          f"{'maxDD':>8s}  {'dur p50':>8s}  {'realistic':>10s}  {'cons':>6s}  {'medP':>6s}")
    print("-" * 100)
    for label, s, fr in results:
        med = fr["realistic"].get("pass_days_p50") or fr["realistic"].get("median_days_to_pass")
        med_str = f"{med:.0f}d" if med else "n/a"
        print(f"{label:10s}  {s['n']:>7d}  {s['wr']*100:>5.1f}%  {s['mean_r']:>+8.4f}  "
              f"{s['cum_r']:>+9.1f}  {s['max_dd_r']:>7.1f}R  {s['dur_p50']:>7.1f}d  "
              f"{fr['realistic']['pass_rate']*100:>9.1f}%  "
              f"{fr['conservative']['pass_rate']*100:>5.1f}%  {med_str:>6s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
