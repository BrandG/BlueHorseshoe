"""Simulate live safety gates on the deploy ledger to produce a 'gated' ledger.

Walks the deploy ledger chronologically (event-driven) and applies the same
skip rules the live paper trader applies at order-placement time:

  - skip_already_open: at most one open position per pair
  - skip_per_run_cap:  at most MAX_NEW_ORDERS_PER_RUN new orders per H4 cron tick
  - skip_direction:    |n_long - n_short| capped at MAX_NET_DIRECTION_IMBALANCE

Margin gate is NOT modeled — would require per-pair margin rates and intra-bar
NAV tracking. Direction + already-open checks dominate the throttling anyway.

Outputs:
  research/v2_deploy_backtest/gated_ledger.csv
  research/v2_deploy_backtest/gate_overlay_summary.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from bh_ftmo.trading.safety import (  # noqa: E402
    MAX_NET_DIRECTION_IMBALANCE,
)

LEDGER_IN = REPO / "research" / "v2_deploy_backtest" / "deploy_ledger.csv"
LEDGER_OUT = REPO / "research" / "v2_deploy_backtest" / "gated_ledger.csv"
SUMMARY_OUT = REPO / "research" / "v2_deploy_backtest" / "gate_overlay_summary.json"

# Mirror v2_paper's MAX_NEW_ORDERS_PER_RUN; can't import directly because the
# trader also imports OandaTrader/FxStore (network deps).
MAX_NEW_ORDERS_PER_RUN = 5


def simulate(ledger: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Walk the ledger chronologically applying gates. Return (kept, summary)."""
    # Build sorted event list: each trade contributes (entry_ts, "entry", idx) and
    # (exit_ts, "exit", idx). Process entries before exits at the same timestamp
    # so a same-ts close-and-open pair behaves like the live system: gate sees
    # the open position when checking the new entry. Tiebreak: exits AFTER entries.
    # Use floor('4h') (unit-agnostic) for the H4 bucket key.
    entry_buckets = ledger["entry_ts"].dt.floor("4h").astype("int64").to_numpy()
    entry_ns = ledger["entry_ts"].astype("datetime64[ns]").astype("int64").to_numpy()
    exit_ns = ledger["exit_ts"].astype("datetime64[ns]").astype("int64").to_numpy()

    events: list[tuple[int, int, int]] = []  # (ts_ns, kind_code, trade_idx)
    # kind_code: 0=entry, 1=exit; sorting gives entries first at ties.
    for i in range(len(ledger)):
        events.append((int(entry_ns[i]), 0, i))
        events.append((int(exit_ns[i]), 1, i))
    events.sort()

    open_pairs: set[str] = set()              # pairs with an open position
    open_idxs: dict[int, str] = {}             # trade_idx -> direction (for cleanup)
    n_long = 0
    n_short = 0
    bucket_count: dict[int, int] = defaultdict(int)
    kept: list[int] = []
    skips = Counter()

    pairs = ledger["pair"].to_numpy()
    dirs = ledger["direction"].to_numpy()

    for ts_ns, kind, idx in events:
        if kind == 1:  # exit
            if idx in open_idxs:
                d = open_idxs.pop(idx)
                open_pairs.discard(pairs[idx])
                if d == "long":
                    n_long -= 1
                else:
                    n_short -= 1
            continue

        # entry
        pair = pairs[idx]
        direction = dirs[idx]

        if pair in open_pairs:
            skips["skip_already_open"] += 1
            continue

        bucket = int(entry_buckets[idx])
        if bucket_count[bucket] >= MAX_NEW_ORDERS_PER_RUN:
            skips["skip_per_run_cap"] += 1
            continue

        if direction == "long":
            new_imbalance = (n_long + 1) - n_short
            if new_imbalance > MAX_NET_DIRECTION_IMBALANCE:
                skips["skip_direction_imbalance_long"] += 1
                continue
        else:
            new_imbalance = (n_short + 1) - n_long
            if new_imbalance > MAX_NET_DIRECTION_IMBALANCE:
                skips["skip_direction_imbalance_short"] += 1
                continue

        # Pass — accept the trade
        open_pairs.add(pair)
        open_idxs[idx] = direction
        if direction == "long":
            n_long += 1
        else:
            n_short += 1
        bucket_count[bucket] += 1
        kept.append(idx)

    kept_df = ledger.iloc[kept].reset_index(drop=True)

    # Per-strategy retention: how many of each strategy survived the gate?
    strat_in = ledger.groupby("strategy").size().to_dict()
    strat_out = kept_df.groupby("strategy").size().to_dict()
    retention = {
        s: {
            "in": int(strat_in.get(s, 0)),
            "out": int(strat_out.get(s, 0)),
            "retain_pct": (100.0 * strat_out.get(s, 0) / strat_in.get(s, 1))
                          if strat_in.get(s, 0) else 0.0,
        }
        for s in sorted(strat_in)
    }

    summary = {
        "n_in": int(len(ledger)),
        "n_kept": int(len(kept)),
        "n_skipped": int(len(ledger) - len(kept)),
        "retention_pct": 100.0 * len(kept) / len(ledger),
        "skip_reasons": dict(skips),
        "by_strategy": retention,
        "kept_mean_r": float(kept_df["r"].mean()) if len(kept_df) else 0.0,
        "kept_cum_r": float(kept_df["r"].sum()) if len(kept_df) else 0.0,
        "kept_long": int((kept_df["direction"] == "long").sum()),
        "kept_short": int((kept_df["direction"] == "short").sum()),
    }
    return kept_df, summary


def main() -> int:
    if not LEDGER_IN.exists():
        print(f"ERROR: missing {LEDGER_IN} — run build_deploy_ledger.py first")
        return 1

    print(f"Loading {LEDGER_IN.name}...")
    ledger = pd.read_csv(LEDGER_IN)
    ledger["entry_ts"] = pd.to_datetime(ledger["entry_ts"])
    ledger["exit_ts"] = pd.to_datetime(ledger["exit_ts"])
    print(f"  {len(ledger):,} trades, {ledger['entry_ts'].min().date()} → {ledger['entry_ts'].max().date()}\n")

    print(f"Applying gates: max_orders_per_run={MAX_NEW_ORDERS_PER_RUN}, "
          f"direction_imbalance_cap={MAX_NET_DIRECTION_IMBALANCE}\n")
    kept, summary = simulate(ledger)

    print(f"=== Gate overlay ===")
    print(f"  trades in:    {summary['n_in']:,}")
    print(f"  trades kept:  {summary['n_kept']:,}  ({summary['retention_pct']:.1f}%)")
    print(f"  trades skipped: {summary['n_skipped']:,}")
    print(f"  skip reasons:")
    for r, n in summary["skip_reasons"].items():
        print(f"    {r:35s}  {n:6,d}")
    print()
    print(f"  kept stats:")
    print(f"    mean R/trade:  {summary['kept_mean_r']:+.4f}  (was {ledger['r'].mean():+.4f})")
    print(f"    cum R:         {summary['kept_cum_r']:+.1f}  (was {ledger['r'].sum():+.1f})")
    print(f"    long / short:  {summary['kept_long']} / {summary['kept_short']}  "
          f"(was {(ledger['direction'] == 'long').sum()} / "
          f"{(ledger['direction'] == 'short').sum()})")
    print()
    print(f"  per-strategy retention:")
    for s, info in summary["by_strategy"].items():
        print(f"    {s:9s}  in={info['in']:5d}  out={info['out']:5d}  "
              f"retained={info['retain_pct']:5.1f}%")

    LEDGER_OUT.parent.mkdir(parents=True, exist_ok=True)
    kept.to_csv(LEDGER_OUT, index=False)
    SUMMARY_OUT.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {LEDGER_OUT}")
    print(f"Wrote {SUMMARY_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
