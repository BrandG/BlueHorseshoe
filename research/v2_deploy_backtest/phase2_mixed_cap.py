"""Phase II: mixed-cap test (5d on limit cells, 14d on mid cells).

Hypothesis: limit cells take a small R hit from a 5d cap (-23 to -31%)
while mid cells take a brutal hit (-28 to -46%). Selectively applying 5d
only to the limit cells should capture most of the safety benefit
(+5.8pp conservative pass rate from path_b_results) without the full
-19% cum R cost.

Builds a mixed deploy ledger:
  - macd, atr, ichimoku (limit cells):  5d ledgers from 5day_ledgers/
  - bb, cci, ema, sma, rsi, stoch (mid): 14d canonical ledgers

Then runs gate overlay + FTMO sim and compares vs full-14d and full-5d.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "ftmo_sizing_sim"))
sys.path.insert(0, str(REPO / "src"))

from sim import SizingConfig, run_cohort, load_ftmo_config  # noqa: E402
from bh_briefing import CELLS  # noqa: E402
from bh_ftmo_v2_paper import DEPLOYED_STRATEGIES  # noqa: E402
from bh_ftmo.trading.safety import MAX_NET_DIRECTION_IMBALANCE  # noqa: E402

LEDGERS_5D = REPO / "research" / "v2_deploy_backtest" / "5day_ledgers"
V2 = REPO / "research" / "_v2_rerun"
BB14 = REPO / "research" / "bb_execution_v1" / "portfolio_trades.csv"
DEPLOY_MIX = REPO / "research" / "v2_deploy_backtest" / "deploy_ledger_mixed.csv"
GATED_MIX = REPO / "research" / "v2_deploy_backtest" / "gated_ledger_mixed.csv"
RESULTS_MIX = REPO / "research" / "v2_deploy_backtest" / "phase2_results.json"

DEPLOYED_SIZING = 0.005
N_STARTS = 500
MAX_NEW_ORDERS_PER_RUN = 5

# Apply 5d cap only to limit-entry strategies (the resilient ones).
SHORT_CAP_STRATEGIES = {"macd", "atr", "ichimoku"}

# Full source paths per strategy, indexed by entry mode.
SOURCES_14D = {
    ("macd", "limit"):    V2 / "macd" / "portfolio_trades_limit.csv",
    ("atr", "limit"):     V2 / "atr" / "portfolio_trades_limit.csv",
    ("ichimoku", "limit"): V2 / "ichimoku" / "portfolio_trades_limit.csv",
    ("stoch", "mid"):     V2 / "stoch" / "portfolio_trades.csv",
    ("cci", "mid"):       V2 / "cci" / "portfolio_trades.csv",
    ("ema", "mid"):       V2 / "ema" / "portfolio_trades.csv",
    ("sma", "mid"):       V2 / "sma" / "portfolio_trades.csv",
    ("rsi", "mid"):       V2 / "rsi" / "portfolio_trades.csv",
    ("bb", "mid"):        BB14,
}
ENTRY_MODE = {
    "macd": "limit", "atr": "limit", "ichimoku": "limit",
    "stoch": "mid", "cci": "mid", "bb": "mid",
    "ema": "mid", "sma": "mid", "rsi": "mid",
}


def build_mixed_ledger() -> pd.DataFrame:
    direction_by = {(c.strategy, c.pair): c.direction
                    for c in CELLS if c.strategy in DEPLOYED_STRATEGIES}
    parts = []
    for strat in sorted(DEPLOYED_STRATEGIES):
        em = ENTRY_MODE[strat]
        if strat in SHORT_CAP_STRATEGIES:
            path = LEDGERS_5D / f"{strat}_5d_{em}.csv"
            cap = "5d"
        else:
            path = SOURCES_14D[(strat, em)]
            cap = "14d"
        if not path.exists():
            print(f"  WARN: missing {path}")
            continue
        df = pd.read_csv(path)
        df["strategy"] = strat
        df["entry_mode"] = em
        df["cap"] = cap
        df["direction"] = df["pair"].map(lambda p, s=strat: direction_by.get((s, p)))
        df = df.dropna(subset=["direction"])
        parts.append(df)
        print(f"  {strat:9s} {em:5s} cap={cap:3s}  n={len(df):>5d}  mean_R={df['r'].mean():+.4f}")
    ledger = pd.concat(parts, ignore_index=True)
    ledger["entry_ts"] = pd.to_datetime(ledger["entry_ts"])
    ledger["exit_ts"] = pd.to_datetime(ledger["exit_ts"])
    ledger = ledger.sort_values("entry_ts").reset_index(drop=True)
    return ledger[["entry_ts", "exit_ts", "strategy", "pair", "direction", "entry_mode", "cap", "r"]]


def gate_overlay(ledger: pd.DataFrame):
    entry_buckets = ledger["entry_ts"].dt.floor("4h").astype("int64").to_numpy()
    entry_ns = ledger["entry_ts"].astype("datetime64[ns]").astype("int64").to_numpy()
    exit_ns = ledger["exit_ts"].astype("datetime64[ns]").astype("int64").to_numpy()
    events = []
    for i in range(len(ledger)):
        events.append((int(entry_ns[i]), 0, i))
        events.append((int(exit_ns[i]), 1, i))
    events.sort()
    open_pairs = set(); open_idxs = {}; n_long = n_short = 0
    bucket_count = defaultdict(int); kept = []; skips = Counter()
    pairs = ledger["pair"].to_numpy(); dirs = ledger["direction"].to_numpy()
    for ts_ns, kind, idx in events:
        if kind == 1:
            if idx in open_idxs:
                d = open_idxs.pop(idx); open_pairs.discard(pairs[idx])
                if d == "long": n_long -= 1
                else: n_short -= 1
            continue
        pair = pairs[idx]; direction = dirs[idx]
        if pair in open_pairs:
            skips["skip_already_open"] += 1; continue
        bucket = int(entry_buckets[idx])
        if bucket_count[bucket] >= MAX_NEW_ORDERS_PER_RUN:
            skips["skip_per_run_cap"] += 1; continue
        if direction == "long":
            if (n_long + 1) - n_short > MAX_NET_DIRECTION_IMBALANCE:
                skips["skip_direction_imbalance_long"] += 1; continue
        else:
            if (n_short + 1) - n_long > MAX_NET_DIRECTION_IMBALANCE:
                skips["skip_direction_imbalance_short"] += 1; continue
        open_pairs.add(pair); open_idxs[idx] = direction
        if direction == "long": n_long += 1
        else: n_short += 1
        bucket_count[bucket] += 1; kept.append(idx)
    return ledger.iloc[kept].reset_index(drop=True), {"in": len(ledger), "kept": len(kept), "skips": dict(skips)}


def run_ftmo(ledger, ftmo, sizing_pct):
    sizing = SizingConfig(mode="fixed", risk_per_trade_pct=sizing_pct)
    out = {}
    for model in ("realistic", "conservative"):
        c = run_cohort(ledger, ftmo, sizing, n_starts=N_STARTS,
                       intra_trade_model=model, seed=42)
        results = c.pop("results", [])
        if results:
            d = [r.days_to_resolution for r in results if r.status == "passed"]
            c["pass_days_p50"] = float(np.median(d)) if d else None
        out[model] = c
    return out


def main() -> int:
    print("=== Phase II: mixed cap (5d limit + 14d mid) ===")
    print()
    ledger = build_mixed_ledger()
    ledger.to_csv(DEPLOY_MIX, index=False)
    print(f"\n  total: {len(ledger):,} trades  mean_R={ledger['r'].mean():+.4f}  cum_R={ledger['r'].sum():+.1f}")
    print(f"  long/short: {(ledger['direction']=='long').sum()}/"
          f"{(ledger['direction']=='short').sum()}")

    print(f"\n=== Gate overlay ===")
    gated, gs = gate_overlay(ledger)
    gated.to_csv(GATED_MIX, index=False)
    print(f"  in={gs['in']:,}  kept={gs['kept']:,}  retention={gs['kept']/gs['in']*100:.1f}%")
    print(f"  skips: {gs['skips']}")
    print(f"  gated mean_R={gated['r'].mean():+.4f}  cum_R={gated['r'].sum():+.1f}")
    print(f"  gated long/short: {(gated['direction']=='long').sum()}/"
          f"{(gated['direction']=='short').sum()}")

    print(f"\n=== FTMO sim (sizing={DEPLOYED_SIZING*100:.2f}%) ===")
    ftmo = load_ftmo_config(str(REPO / "src" / "bh_ftmo_swing_config.json"), phase="step1")
    sim_mix = run_ftmo(gated, ftmo, DEPLOYED_SIZING)
    for model, c in sim_mix.items():
        med = c.get("pass_days_p50")
        med_str = f"{med:.0f}d" if med is not None else "n/a"
        print(f"  {model:12s}  pass={c['pass_rate']*100:5.1f}%  "
              f"failed={c['failed']}/{c['n_starts']}  median_pass={med_str}")

    # Three-way compare: 14d / 5d / mixed
    pre_results = REPO / "research" / "v2_deploy_backtest" / "sweep_gated_results.json"
    pb_results = REPO / "research" / "v2_deploy_backtest" / "path_b_results.json"
    if pre_results.exists() and pb_results.exists():
        cdata = json.loads(pre_results.read_text())
        c14_5pct = None
        for sizing, c in cdata.get("sizing_sweep", []):
            try:
                if abs(float(sizing) - DEPLOYED_SIZING) < 1e-9:
                    c14_5pct = c
                    break
            except (ValueError, TypeError):
                continue
        c5d = json.loads(pb_results.read_text()).get("sim_5d", {})
        gated14 = pd.read_csv(REPO / "research" / "v2_deploy_backtest" / "gated_ledger.csv")
        gated5 = pd.read_csv(REPO / "research" / "v2_deploy_backtest" / "gated_ledger_5d.csv")

        print()
        print("=== THREE-WAY COMPARISON (gated, 0.5% sizing) ===")
        print(f"{'metric':35s}  {'14d (canon)':>12s}  {'5d (uniform)':>13s}  {'MIXED':>10s}")
        print("-" * 80)
        print(f"  {'trade count':33s}  {len(gated14):>12,d}  {len(gated5):>13,d}  {len(gated):>10,d}")
        print(f"  {'mean R':33s}  {gated14['r'].mean():>+12.4f}  {gated5['r'].mean():>+13.4f}  {gated['r'].mean():>+10.4f}")
        print(f"  {'cum R':33s}  {gated14['r'].sum():>+12.1f}  {gated5['r'].sum():>+13.1f}  {gated['r'].sum():>+10.1f}")
        for model in ("realistic", "conservative"):
            c14 = c14_5pct.get(model, {}) if c14_5pct else {}
            c5 = c5d.get(model, {})
            cmx = sim_mix[model]
            p14 = c14.get('pass_rate', 0)*100
            p5 = c5.get('pass_rate', 0)*100
            pmx = cmx['pass_rate']*100
            print(f"  {f'pass rate ({model})':33s}  {p14:>11.1f}%  {p5:>12.1f}%  {pmx:>9.1f}%")
            m14 = c14.get('pass_days_p50') or c14.get('median_days_to_pass')
            m5 = c5.get('pass_days_p50') or c5.get('median_days_to_pass')
            mmx = cmx.get('pass_days_p50') or cmx.get('median_days_to_pass')
            if m14 and m5 and mmx:
                print(f"  {f'median pass days ({model})':33s}  {m14:>11.0f}d  {m5:>12.0f}d  {mmx:>9.0f}d")

    out = {
        "deployed_sizing": DEPLOYED_SIZING,
        "n_starts": N_STARTS,
        "short_cap_strategies": sorted(SHORT_CAP_STRATEGIES),
        "gate_summary": gs,
        "sim_mixed": sim_mix,
        "gated_mixed_stats": {
            "n": int(len(gated)),
            "mean_r": float(gated["r"].mean()) if len(gated) else 0.0,
            "cum_r": float(gated["r"].sum()) if len(gated) else 0.0,
        },
    }
    RESULTS_MIX.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {RESULTS_MIX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
