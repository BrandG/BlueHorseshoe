"""compare_arms.py — Phase 3 of WEEKEND_FLATTEN_EQUITIES_v1.

Compares baseline vs uniform-flatten vs asymmetric-flatten ledgers. Computes
the metrics enumerated in the design doc:
  - Cum R, mean R/trade, mean R/day held (time-adjusted)
  - Median days held
  - Max single-trade loss (R), max drawdown (cum R)
  - 99th-percentile loss (R)
Stratified by:
  - Pooled (all trades, both strategies)
  - By strategy
  - By regime
  - By weekend-count bucket (0, 1, 2+)

Bootstrap-stability check (1000 resamples) on the sign of the cum-R delta
between baseline and each flatten rule.

Applies the ship/no-ship decision rule from the design doc.

R per trade is defined as ``blended_pnl_pct / RISK_PCT_PER_TRADE``, where
``RISK_PCT_PER_TRADE`` is the production MAX_RISK_PERCENT = 5%. This puts
returns in standard-R units across all comparisons.

Output:
  - Console table comparing the three arms
  - Markdown memo at WEEKEND_FLATTEN_EQUITIES_v1_RESULTS.md
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from bluehorseshoe.core.config import REPO_ROOT


# Production risk constant (analysis/constants.py:MAX_RISK_PERCENT)
RISK_PCT_PER_TRADE = 5.0


def to_r(pnl_pct: pd.Series) -> pd.Series:
    """Convert blended P&L percentage to R units (P&L / max risk per trade)."""
    return pnl_pct / RISK_PCT_PER_TRADE


def load_ledger(path: Path, arm_name: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["status"].isin(("split_full_profit", "split_partial_profit",
                                "stopped_out", "closed_profit", "closed_loss"))]
    df["arm"] = arm_name
    df["r"] = to_r(df["blended_pnl_pct"])
    df["days_held"] = df["days_held"].astype(int).clip(lower=1)  # avoid /0
    df["r_per_day"] = df["r"] / df["days_held"]
    return df


def summarize(df: pd.DataFrame) -> dict:
    """Per-arm summary metrics."""
    if df.empty:
        return {"trades": 0}
    cum_r = df["r"].sum()
    sorted_r = df["r"].sort_values().reset_index(drop=True)
    running_cum = sorted_r.cumsum()
    # Max drawdown of the cum-R curve (across the time-ordered ledger, not
    # sorted) — re-compute below using the original ledger order:
    r_in_order = df.sort_values(["entry_date", "trade_id"])["r"].reset_index(drop=True)
    cum_curve = r_in_order.cumsum()
    running_max = cum_curve.cummax()
    drawdown = cum_curve - running_max
    max_dd = drawdown.min() if not drawdown.empty else 0.0
    return {
        "trades":          int(len(df)),
        "mean_r":          float(df["r"].mean()),
        "cum_r":           float(cum_r),
        "mean_r_per_day":  float(df["r_per_day"].mean()),
        "median_days":     int(df["days_held"].median()),
        "max_loss_r":      float(df["r"].min()),
        "p99_loss_r":      float(df["r"].quantile(0.01)),
        "max_drawdown":    float(max_dd),
    }


def compare_arms_pooled(baseline: pd.DataFrame, uniform: pd.DataFrame,
                        asymmetric: pd.DataFrame) -> pd.DataFrame:
    """One row per arm with summary metrics."""
    rows = []
    for arm, df in [("baseline", baseline), ("uniform", uniform),
                    ("asymmetric", asymmetric)]:
        s = summarize(df)
        s["arm"] = arm
        rows.append(s)
    return pd.DataFrame(rows).set_index("arm")


def stratify(df: pd.DataFrame, by: str) -> pd.DataFrame:
    groups = df.groupby(by, dropna=False)
    rows = []
    for key, group in groups:
        s = summarize(group)
        s[by] = key
        rows.append(s)
    return pd.DataFrame(rows).set_index(by) if rows else pd.DataFrame()


def bootstrap_signflip(baseline: pd.DataFrame, alt: pd.DataFrame,
                       n_iter: int = 1000, rng_seed: int = 42) -> dict:
    """Resample with replacement; count fraction of resamples where cum-R
    delta (alt - baseline) flips sign vs the observed delta."""
    rng = np.random.default_rng(rng_seed)
    common = sorted(set(baseline["trade_id"]) & set(alt["trade_id"]))
    if not common:
        return {"flip_rate": float("nan"), "common_trades": 0}
    base_r = baseline.set_index("trade_id").loc[common, "r"].values
    alt_r = alt.set_index("trade_id").loc[common, "r"].values
    delta = alt_r - base_r
    observed_total = delta.sum()
    observed_sign = np.sign(observed_total)
    n = len(delta)
    flips = 0
    for _ in range(n_iter):
        idx = rng.integers(0, n, size=n)
        if np.sign(delta[idx].sum()) != observed_sign:
            flips += 1
    return {
        "flip_rate": float(flips) / n_iter,
        "common_trades": n,
        "observed_delta_cum_r": float(observed_total),
        "observed_sign": int(observed_sign),
    }


def ship_decision(baseline_pool: dict, alt_pool: dict, boot: dict,
                  strata_alt: pd.DataFrame, strata_base: pd.DataFrame) -> str:
    """Apply the design-doc decision rule. Returns a short string."""
    if not baseline_pool or not alt_pool:
        return "NO — missing baseline or alt summary"
    if boot.get("flip_rate", 1.0) > 0.05:
        return f"NO — bootstrap flip rate {boot['flip_rate']:.1%} > 5%"
    rpd_improves = alt_pool["mean_r_per_day"] > baseline_pool["mean_r_per_day"]
    dd_baseline = baseline_pool["max_drawdown"]
    dd_alt = alt_pool["max_drawdown"]
    cum_baseline = baseline_pool["cum_r"]
    cum_alt = alt_pool["cum_r"]
    cum_cost_ok = (cum_alt >= cum_baseline * 0.85) if cum_baseline > 0 else (cum_alt >= cum_baseline)
    # max_drawdown values are non-positive; "reduces by 25%" means alt's dd is
    # closer to zero by at least 25% of baseline's magnitude
    dd_improves_25 = (abs(dd_alt) <= abs(dd_baseline) * 0.75) and cum_cost_ok
    if not (rpd_improves or dd_improves_25):
        return "NO — neither (mean R/day improves) nor (DD reduces ≥25% with cum-R cost ≤15%)"
    # Regime-confinement check: is improvement confined to ≤1 regime?
    if not strata_alt.empty and not strata_base.empty:
        regimes = sorted(set(strata_alt.index) & set(strata_base.index))
        regimes_with_improvement = 0
        for reg in regimes:
            try:
                if strata_alt.loc[reg, "mean_r_per_day"] > strata_base.loc[reg, "mean_r_per_day"]:
                    regimes_with_improvement += 1
            except Exception:  # noqa: BLE001
                pass
        if regimes_with_improvement <= 1:
            return ("NO — improvement is confined to ≤1 regime; needs a "
                    "regime detector, not an always-on rule")
    return "SHIP — clears all gates"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    base_dir = Path(REPO_ROOT) / "research" / "weekend_flatten_equities_v1"
    parser.add_argument("--baseline", default=str(base_dir / "baseline_ledger_weekly.csv"))
    parser.add_argument("--uniform", default=str(base_dir / "uniform_flatten_ledger.csv"))
    parser.add_argument("--asymmetric", default=str(base_dir / "asymmetric_flatten_ledger.csv"))
    parser.add_argument("--output", default=str(base_dir / "WEEKEND_FLATTEN_EQUITIES_v1_RESULTS.md"))
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s")

    baseline = load_ledger(Path(args.baseline), "baseline")
    uniform = load_ledger(Path(args.uniform), "uniform")
    asymmetric = load_ledger(Path(args.asymmetric), "asymmetric")

    # ----- Pool comparison -----
    pooled = compare_arms_pooled(baseline, uniform, asymmetric)
    print("\n=== Pooled comparison (all trades) ===\n")
    print(pooled.to_string(float_format=lambda x: f"{x:.3f}"))

    # ----- Stratified by strategy -----
    print("\n=== By strategy — baseline vs uniform vs asymmetric (mean_r, cum_r, mean_r_per_day) ===")
    for arm_name, df in [("baseline", baseline), ("uniform", uniform), ("asymmetric", asymmetric)]:
        print(f"\n[{arm_name}]")
        print(stratify(df, "strategy")[["trades", "mean_r", "cum_r", "mean_r_per_day"]]
              .to_string(float_format=lambda x: f"{x:.3f}"))

    # ----- Stratified by regime -----
    print("\n=== By regime — uniform delta vs baseline (mean_r_per_day) ===")
    base_reg = stratify(baseline, "regime")
    uni_reg = stratify(uniform, "regime")
    asy_reg = stratify(asymmetric, "regime")
    if not base_reg.empty:
        delta = pd.DataFrame({
            "baseline": base_reg["mean_r_per_day"],
            "uniform":  uni_reg["mean_r_per_day"],
            "asymmetric": asy_reg["mean_r_per_day"],
        }).round(4)
        delta["uni_delta"]  = (delta["uniform"]    - delta["baseline"]).round(4)
        delta["asy_delta"]  = (delta["asymmetric"] - delta["baseline"]).round(4)
        print(delta.to_string())

    # ----- Stratified by weekend count -----
    print("\n=== By weekend-count bucket — baseline (mean_r) ===")
    wks_buckets = baseline.copy()
    wks_buckets["wk_bucket"] = pd.cut(wks_buckets["spans_weekends"],
                                       bins=[-0.1, 0.1, 1.1, 999], labels=["0", "1", "2+"])
    print(stratify(wks_buckets, "wk_bucket")[["trades", "mean_r", "cum_r"]]
          .to_string(float_format=lambda x: f"{x:.3f}"))

    # ----- Bootstrap stability -----
    print("\n=== Bootstrap sign-stability (1000 resamples) ===")
    uni_boot = bootstrap_signflip(baseline, uniform)
    asy_boot = bootstrap_signflip(baseline, asymmetric)
    print(f"uniform    delta cum-R = {uni_boot.get('observed_delta_cum_r', 0):.2f}  "
          f"flip rate = {uni_boot.get('flip_rate', float('nan')):.1%}")
    print(f"asymmetric delta cum-R = {asy_boot.get('observed_delta_cum_r', 0):.2f}  "
          f"flip rate = {asy_boot.get('flip_rate', float('nan')):.1%}")

    # ----- Ship decision -----
    print("\n=== Ship/no-ship decision ===")
    baseline_pool = summarize(baseline)
    uni_pool = summarize(uniform)
    asy_pool = summarize(asymmetric)
    uni_decision = ship_decision(baseline_pool, uni_pool, uni_boot, uni_reg, base_reg)
    asy_decision = ship_decision(baseline_pool, asy_pool, asy_boot, asy_reg, base_reg)
    print(f"uniform    : {uni_decision}")
    print(f"asymmetric : {asy_decision}")

    # ----- Write memo -----
    out = Path(args.output)
    with out.open("w") as f:
        f.write("# WEEKEND_FLATTEN_EQUITIES_v1 — Results\n\n")
        f.write(f"Baseline ledger: `{args.baseline}` ({len(baseline)} trades)\n")
        f.write(f"Uniform ledger:  `{args.uniform}` ({len(uniform)} trades)\n")
        f.write(f"Asymmetric ledger: `{args.asymmetric}` ({len(asymmetric)} trades)\n\n")
        f.write("## Pooled comparison\n\n")
        f.write("```\n")
        f.write(pooled.to_string(float_format=lambda x: f"{x:.3f}"))
        f.write("\n```\n\n")
        f.write("## Bootstrap sign-stability (1000 resamples)\n\n")
        f.write(f"- uniform    cum-R delta {uni_boot.get('observed_delta_cum_r', 0):.2f}  "
                f"flip rate {uni_boot.get('flip_rate', float('nan')):.1%}\n")
        f.write(f"- asymmetric cum-R delta {asy_boot.get('observed_delta_cum_r', 0):.2f}  "
                f"flip rate {asy_boot.get('flip_rate', float('nan')):.1%}\n\n")
        f.write("## Ship/no-ship\n\n")
        f.write(f"- uniform: **{uni_decision}**\n")
        f.write(f"- asymmetric: **{asy_decision}**\n")
    print(f"\nMemo written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
