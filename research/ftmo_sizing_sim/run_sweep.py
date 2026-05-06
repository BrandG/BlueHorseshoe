"""Sweep FTMO challenge pass rate across portfolios × sizing % × intra-trade models.

Per-portfolio (each indicator/entry combo) and combined-portfolio sweeps.
Uses the D1-filtered trade ledgers for indicators where filter helps; uses
the unfiltered ledgers for indicators where filter is destructive.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/research/ftmo_sizing_sim")
sys.path.insert(0, "/root/BlueHorseshoe/src")

from sim import FtmoConfig, SizingConfig, run_cohort, load_ftmo_config


CONFIG_PATH = "/root/BlueHorseshoe/src/bh_ftmo_swing_config.json"
ROOT = Path("/root/BlueHorseshoe/research/_v2_rerun")


def existing(p: Path) -> Path | None:
    return p if p.exists() else None


# Per MULTITF_FILTER_v1.md deployment table:
# - filter ON (use _d1 ledger if present): stoch mid+limit, sma mid, ema mid,
#   rsi mid, cci mid+limit, macd limit, atr mid+limit
# - filter OFF (use original unfiltered ledger): sma limit, ema limit,
#   rsi limit (NULL under filter — keep unfiltered), ichimoku limit (NULL too)
PORTFOLIOS = [
    # filter-ON (D1-filtered)
    ("stoch mid (D1)",     ROOT / "stoch" / "portfolio_trades_d1.csv"),
    ("stoch limit (D1)",   ROOT / "stoch" / "portfolio_trades_d1_limit.csv"),
    ("sma mid (D1)",       ROOT / "sma" / "portfolio_trades_d1.csv"),
    ("ema mid (D1)",       ROOT / "ema" / "portfolio_trades_d1.csv"),
    ("rsi mid (D1)",       ROOT / "rsi" / "portfolio_trades_d1.csv"),
    ("cci mid (D1)",       ROOT / "cci" / "portfolio_trades_d1.csv"),
    ("cci limit (D1)",     ROOT / "cci" / "portfolio_trades_d1_limit.csv"),
    ("macd limit (D1)",    ROOT / "macd" / "portfolio_trades_d1_limit.csv"),
    ("atr mid (D1)",       ROOT / "atr" / "portfolio_trades_d1.csv"),
    ("atr limit (D1)",     ROOT / "atr" / "portfolio_trades_d1_limit.csv"),
    # filter-OFF (unfiltered baselines, kept where D1 filter is destructive)
    ("sma limit (unfilt)", ROOT / "sma" / "portfolio_trades_limit.csv"),
    ("ema limit (unfilt)", ROOT / "ema" / "portfolio_trades_limit.csv"),
    ("rsi limit (unfilt)", ROOT / "rsi" / "portfolio_trades_limit.csv"),
    ("ichimoku limit (unfilt)", ROOT / "ichimoku" / "portfolio_trades_limit.csv"),
]


SIZING_PCTS = [0.0025, 0.005, 0.0075, 0.01]   # 0.25% to 1.0%
INTRA_MODELS = ["realistic", "conservative"]


def load_combined(portfolios) -> pd.DataFrame:
    """Concatenate all portfolio ledgers into one combined trade list."""
    parts = []
    for label, path in portfolios:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df["source"] = label
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    return out.sort_values("entry_ts").reset_index(drop=True)


def main():
    ftmo = load_ftmo_config(CONFIG_PATH, phase="step1")
    print(f"FTMO config: balance={ftmo.initial_balance}, daily_dd={ftmo.daily_loss_pct*100:.0f}%, "
          f"max_dd={ftmo.max_loss_pct*100:.0f}%, target={ftmo.profit_target_pct*100:.0f}%, "
          f"max_days={ftmo.max_trading_days}", flush=True)

    print("\n" + "=" * 110)
    print("PER-PORTFOLIO PASS RATES (n=500 randomized starts each)")
    print("=" * 110)
    print(f"{'PORTFOLIO':<28} {'TRADES':<8} {'SIZE':<6} {'INTRA':<14} "
          f"{'PASS':<8} {'FAIL':<8} {'IN_PROG':<8} {'TOP_FAIL_REASON':<20}")
    print("-" * 110)
    rows = []
    for label, path in PORTFOLIOS:
        if not path.exists():
            print(f"{label:<28} (missing)")
            continue
        df = pd.read_csv(path)
        df["entry_ts"] = pd.to_datetime(df["entry_ts"])
        df["exit_ts"] = pd.to_datetime(df["exit_ts"])
        for sz in SIZING_PCTS:
            for intra in INTRA_MODELS:
                sizing = SizingConfig(mode="fixed", risk_per_trade_pct=sz)
                out = run_cohort(df, ftmo, sizing, n_starts=500, intra_trade_model=intra)
                top_reason = max(out.get("fail_reasons", {}).items(), key=lambda x: x[1],
                                 default=(None, 0))
                top_reason_str = (f"{top_reason[0]} ({top_reason[1]})"
                                  if top_reason[0] else "—")
                print(f"{label:<28} {len(df):<8} {sz*100:<5.2f}% {intra:<14} "
                      f"{out['passed']:<8} {out['failed']:<8} {out['in_progress']:<8} "
                      f"{top_reason_str:<20}", flush=True)
                rows.append({
                    "portfolio": label, "n_trades": len(df), "size_pct": sz,
                    "intra_model": intra, "n_starts": out["n_starts"],
                    "passed": out["passed"], "failed": out["failed"],
                    "in_progress": out["in_progress"],
                    "pass_rate": out.get("pass_rate", 0),
                    "median_days_to_pass": out.get("median_days_to_pass"),
                    "fail_reasons": str(out.get("fail_reasons", {})),
                })

    out_path = Path("/root/BlueHorseshoe/research/ftmo_sizing_sim/per_portfolio_results.csv")
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"\nPer-portfolio results → {out_path}")

    # Combined portfolio sweep
    print("\n" + "=" * 110)
    print("COMBINED PORTFOLIO PASS RATES")
    print("=" * 110)
    combined = load_combined(PORTFOLIOS)
    if combined.empty:
        print("(no portfolios loaded)")
        return
    print(f"Combined: {len(combined)} trades from "
          f"{combined['source'].nunique()} portfolios, "
          f"date range {combined['entry_ts'].min().date()} to {combined['entry_ts'].max().date()}",
          flush=True)
    print()
    print(f"{'SIZE':<8} {'INTRA':<14} {'PASS':<8} {'FAIL':<8} {'IN_PROG':<8} "
          f"{'MEDIAN_DAYS':<14} {'TOP_FAIL':<20}")
    print("-" * 110)
    crows = []
    for sz in SIZING_PCTS:
        for intra in INTRA_MODELS:
            sizing = SizingConfig(mode="fixed", risk_per_trade_pct=sz)
            out = run_cohort(combined, ftmo, sizing, n_starts=500, intra_trade_model=intra)
            top_reason = max(out.get("fail_reasons", {}).items(), key=lambda x: x[1],
                             default=(None, 0))
            top_reason_str = (f"{top_reason[0]} ({top_reason[1]})"
                              if top_reason[0] else "—")
            mdp = (f"{out['median_days_to_pass']:.0f}"
                   if out.get("median_days_to_pass") is not None else "—")
            print(f"{sz*100:<7.2f}% {intra:<14} {out['passed']:<8} {out['failed']:<8} "
                  f"{out['in_progress']:<8} {mdp:<14} {top_reason_str:<20}", flush=True)
            crows.append({
                "size_pct": sz, "intra_model": intra, "n_starts": out["n_starts"],
                "passed": out["passed"], "failed": out["failed"],
                "in_progress": out["in_progress"],
                "pass_rate": out.get("pass_rate", 0),
                "median_days_to_pass": out.get("median_days_to_pass"),
                "fail_reasons": str(out.get("fail_reasons", {})),
            })
    out_path = Path("/root/BlueHorseshoe/research/ftmo_sizing_sim/combined_results.csv")
    pd.DataFrame(crows).to_csv(out_path, index=False)
    print(f"\nCombined results → {out_path}")


if __name__ == "__main__":
    main()
