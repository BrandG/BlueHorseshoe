"""Path B fast variant: regenerate macd-limit + stoch-mid trade ledgers
with MAX_HOLD = 30 (5 days), without redoing the parameter sweep.

We monkeypatch MAX_HOLD on the imported run_*_v2 modules and reuse their
collect_trades() functions — same triggers, same cell selection, just shorter
hold cap. This skips ~95% of the original script runtime (the 2400-cell
walk-forward sweep).

Output:
  research/v2_deploy_backtest/5day_ledgers/macd_5d_limit.csv
  research/v2_deploy_backtest/5day_ledgers/stoch_5d_mid.csv

Compares each new ledger against its 14d counterpart for: trade count, mean R,
cum R, WR, duration distribution.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "_v2_rerun"))
sys.path.insert(0, str(REPO / "src"))

import run_macd_v2  # noqa: E402
import run_stoch_v2  # noqa: E402
from _lib import survivor_gate_walkforward, select_production_cells  # noqa: E402

OUT_DIR = REPO / "research" / "v2_deploy_backtest" / "5day_ledgers"
NEW_MAX_HOLD = 30
OLD_MAX_HOLD = 14 * 6


def regen(module, spread_csv: Path, cell_columns: list[str], entry_mode: str,
          collect_args_from_row) -> pd.DataFrame:
    """Read spread CSV, gate, select cells, regenerate trades with monkeypatched MAX_HOLD."""
    spread_df = pd.read_csv(spread_csv)
    robust = survivor_gate_walkforward(spread_df)
    print(f"  spread-robust cells: {len(robust)}/{len(spread_df)}")
    if robust.empty:
        return pd.DataFrame()

    selected = select_production_cells(robust, cell_columns)
    print(f"  selected production cells: {len(selected)}")

    # Monkeypatch MAX_HOLD on the module
    module.MAX_HOLD = NEW_MAX_HOLD
    print(f"  regenerating trades with MAX_HOLD={NEW_MAX_HOLD} bars ({NEW_MAX_HOLD/6:.0f}d)...")

    trades = []
    for s in selected:
        tr = module.collect_trades(*collect_args_from_row(s), entry_mode=entry_mode)
        trades.extend(tr)
    df_t = pd.DataFrame(trades).sort_values("entry_ts").reset_index(drop=True) if trades else pd.DataFrame()

    # Restore module
    module.MAX_HOLD = OLD_MAX_HOLD
    return df_t


def stats(label: str, df: pd.DataFrame) -> None:
    if df.empty:
        print(f"  {label}: empty")
        return
    rs = df["r"].to_numpy()
    n = len(rs)
    wins = int((rs >= 1.0 - 1e-9).sum())
    losses = int((rs <= -1.0 + 1e-9).sum())
    timeouts = n - wins - losses
    wr = wins / max(wins + losses, 1)
    dur = (pd.to_datetime(df["exit_ts"]) - pd.to_datetime(df["entry_ts"])).dt.total_seconds() / 86400
    print(f"  {label:18s} n={n:>5d}  W/L/T={wins}/{losses}/{timeouts}  "
          f"WR={wr*100:.1f}%  mean_R={rs.mean():+.4f}  cum_R={rs.sum():+8.1f}  "
          f"dur p50/p75={np.percentile(dur,50):.1f}/{np.percentile(dur,75):.1f}d")


def compare(label: str, orig_csv: Path, new_df: pd.DataFrame, out_csv: Path) -> None:
    orig = pd.read_csv(orig_csv)
    orig["entry_ts"] = pd.to_datetime(orig["entry_ts"])
    orig["exit_ts"] = pd.to_datetime(orig["exit_ts"])
    print(f"\n=== {label} comparison ===")
    stats("ORIG (14d)", orig)
    stats("NEW (5d) ", new_df)

    if new_df.empty:
        return
    rd = new_df["r"]
    od = orig["r"]
    print(f"  Δ count:  {len(new_df)-len(orig):+d}  ({(len(new_df)/len(orig)-1)*100:+.1f}%)")
    print(f"  Δ mean_R: {rd.mean()-od.mean():+.4f}  ({(rd.mean()-od.mean())/abs(od.mean())*100:+.1f}%)")
    print(f"  Δ cum_R:  {rd.sum()-od.sum():+.1f}  ({(rd.sum()-od.sum())/abs(od.sum())*100:+.1f}%)")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    new_df[["pair", "entry_ts", "exit_ts", "r"]].to_csv(out_csv, index=False)
    print(f"  wrote {out_csv}")


def main() -> int:
    print(f"Path B fast variant: macd-limit + stoch-mid with MAX_HOLD = {NEW_MAX_HOLD} bars (5d)")
    print()

    print("=== MACD limit ===")
    macd_new = regen(
        run_macd_v2,
        REPO / "research" / "_v2_rerun" / "macd" / "walkforward_spread_limit.csv",
        ["pair", "fast", "slow", "signal", "trigger", "direction"],
        "limit",
        lambda s: (s["pair"], int(s["fast"]), int(s["slow"]),
                   int(s["signal"]), s["trigger"], s["direction"]),
    )
    compare("MACD limit",
            REPO / "research" / "_v2_rerun" / "macd" / "portfolio_trades_limit.csv",
            macd_new,
            OUT_DIR / "macd_5d_limit.csv")

    print()
    print("=== STOCH mid ===")
    stoch_new = regen(
        run_stoch_v2,
        REPO / "research" / "_v2_rerun" / "stoch" / "walkforward_spread.csv",
        ["pair", "k_period", "d_period", "threshold", "recovery", "direction"],
        "mid",
        lambda s: (s["pair"], int(s["k_period"]), int(s["d_period"]),
                   int(s["threshold"]), int(s["recovery"]), s["direction"]),
    )
    compare("STOCH mid",
            REPO / "research" / "_v2_rerun" / "stoch" / "portfolio_trades.csv",
            stoch_new,
            OUT_DIR / "stoch_5d_mid.csv")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
