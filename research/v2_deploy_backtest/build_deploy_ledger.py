"""Assemble the trade ledger for the 33-cell deployed v2 portfolio.

For each deployed strategy in `bh_ftmo_v2_paper.DEPLOYED_STRATEGIES`, find the
matching portfolio_trades CSV produced by the v2 research pipeline, attach
`strategy`, `entry_mode`, and `direction` columns (direction joined from
`bh_briefing.CELLS`), then concat + sort by entry_ts. Writes:

  research/v2_deploy_backtest/deploy_ledger.csv

This ledger is the input to the FTMO sizing sim (subtask 2) and the
direction-gate overlay (subtask 3).

Note: the existing per-strategy CSVs already only contain the cells that
survived v2 walk-forward gating, which equals the cells in bh_briefing.CELLS
for that strategy. No further per-cell subsetting is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from bh_briefing import CELLS  # noqa: E402
from bh_ftmo_v2_paper import DEPLOYED_STRATEGIES  # noqa: E402

V2_DIR = REPO / "research" / "_v2_rerun"
BB_DIR = REPO / "research" / "bb_execution_v1"
OUT = REPO / "research" / "v2_deploy_backtest" / "deploy_ledger.csv"

# Strategy + entry_mode -> source CSV. We pick the variant that matches
# what's actually deployed. D1-filter variants exist for most indicators
# but the deployed system does NOT apply the D1 filter — so we use the
# unfiltered ledger to mirror live behavior.
LEDGER_SOURCES: dict[tuple[str, str], Path] = {
    ("macd",     "limit"): V2_DIR / "macd"     / "portfolio_trades_limit.csv",
    ("atr",      "limit"): V2_DIR / "atr"      / "portfolio_trades_limit.csv",
    ("ichimoku", "limit"): V2_DIR / "ichimoku" / "portfolio_trades_limit.csv",
    ("stoch",    "mid"):   V2_DIR / "stoch"    / "portfolio_trades.csv",
    ("cci",      "mid"):   V2_DIR / "cci"      / "portfolio_trades.csv",
    ("ema",      "mid"):   V2_DIR / "ema"      / "portfolio_trades.csv",
    ("sma",      "mid"):   V2_DIR / "sma"      / "portfolio_trades.csv",
    ("rsi",      "mid"):   V2_DIR / "rsi"      / "portfolio_trades.csv",
    ("bb",       "mid"):   BB_DIR / "portfolio_trades.csv",
}


def cell_direction_lookup() -> dict[tuple[str, str], str]:
    """Map (strategy, pair) -> direction from the live cell list."""
    out: dict[tuple[str, str], str] = {}
    for c in CELLS:
        if c.strategy not in DEPLOYED_STRATEGIES:
            continue
        out[(c.strategy, c.pair)] = c.direction
    return out


def main() -> int:
    print(f"Deployed strategies: {sorted(DEPLOYED_STRATEGIES)}\n")

    direction_by_cell = cell_direction_lookup()

    parts: list[pd.DataFrame] = []
    missing: list[str] = []
    for (strat, mode), path in LEDGER_SOURCES.items():
        if strat not in DEPLOYED_STRATEGIES:
            continue
        if not path.exists():
            missing.append(f"{strat}/{mode}: {path}")
            continue
        df = pd.read_csv(path)
        df["strategy"] = strat
        df["entry_mode"] = mode
        df["direction"] = df["pair"].map(
            lambda p, s=strat: direction_by_cell.get((s, p))
        )
        unmapped = df["direction"].isna().sum()
        if unmapped > 0:
            print(f"  WARN {strat}/{mode}: {unmapped} trades with pairs not in CELLS")
        df = df.dropna(subset=["direction"])
        parts.append(df)
        n_pairs = df["pair"].nunique()
        print(f"  {strat:8s} {mode:5s}  n={len(df):5d}  pairs={n_pairs}  "
              f"mean_R={df['r'].mean():+.3f}  cum_R={df['r'].sum():+.1f}")

    if missing:
        print("\nMISSING ledgers:")
        for m in missing:
            print(f"  {m}")
        return 1

    ledger = pd.concat(parts, ignore_index=True)
    ledger["entry_ts"] = pd.to_datetime(ledger["entry_ts"])
    ledger["exit_ts"] = pd.to_datetime(ledger["exit_ts"])
    ledger = ledger.sort_values("entry_ts").reset_index(drop=True)

    cols = ["entry_ts", "exit_ts", "strategy", "pair", "direction", "entry_mode", "r"]
    ledger = ledger[cols]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(OUT, index=False)
    print(f"\nWrote {OUT}")

    print(f"\n=== Combined ledger ===")
    print(f"  total trades:    {len(ledger):,}")
    print(f"  date range:      {ledger['entry_ts'].min().date()} → {ledger['entry_ts'].max().date()}")
    print(f"  unique pairs:    {ledger['pair'].nunique()}")
    print(f"  mean_R:          {ledger['r'].mean():+.4f}")
    print(f"  cum_R:           {ledger['r'].sum():+.1f}")
    print(f"  long / short:    {(ledger['direction'] == 'long').sum()} / "
          f"{(ledger['direction'] == 'short').sum()}")
    print(f"  by strategy:")
    grp = ledger.groupby("strategy").agg(n=("r", "size"), mean_R=("r", "mean"),
                                          cum_R=("r", "sum"))
    for strat, row in grp.iterrows():
        print(f"    {strat:9s} n={int(row['n']):5d}  mean_R={row['mean_R']:+.3f}  cum_R={row['cum_R']:+.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
