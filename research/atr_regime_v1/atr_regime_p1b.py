"""ATR-regime P1b book-level sleeve re-gate."""
# pylint: disable=import-error,wrong-import-order,wrong-import-position
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-locals
# pylint: disable=too-many-statements,too-many-branches,too-many-return-statements
# pylint: disable=too-many-positional-arguments
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
CONFLUENCE_DIR = ROOT / "research" / "confluence_v1"
HARNESS_DIR = ROOT / "research" / "v2_executable_regate" / "harness"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(CONFLUENCE_DIR))
sys.path.insert(0, str(HARNESS_DIR))

from factor_grouping import deployed_cells  # noqa: E402
from _lib import MAX_HOLD, STOP_PCT, TP_PCT  # noqa: E402
from atr_regime_p1 import (  # noqa: E402
    DIRECTIONS,
    EVALUATORS,
    FIRES_PATH,
    REGIME_LABEL,
    REGIME_ORDER,
    _attach_halves,
    _entry_modes,
    _fmt,
    _gate_for_subset,
    _markdown_table,
    _pair_robustness,
    _simulate_trades,
)

STRONG_CELLS = ("bb", "rsi", "ema", "stoch")
FULL_CELLS = ("bb", "rsi", "cci", "sma", "ema", "stoch")
SLEEVES = {
    "long_mr_strong4": STRONG_CELLS,
    "long_mr_full6": FULL_CELLS,
}
CURVES_PATH = OUT_DIR / "atr_regime_sleeve_curves.csv"
REPORT_PATH = OUT_DIR / "ATR_REGIME_P1B.md"
OUT_PATH = OUT_DIR / "atr_regime_p1b.out"


def _clean_lag(value: float) -> int:
    if not np.isfinite(value):
        return MAX_HOLD - 1
    return max(0, int(round(value)) - 1)


def _lag_label(lag: int, corrected_lag: int, mean_lag: int) -> str:
    if lag == corrected_lag:
        return "corrected_median_minus_1"
    if lag == mean_lag:
        return "mean_minus_1"
    if lag == MAX_HOLD - 1:
        return "max_hold_minus_1"
    return f"L_{lag}"


def _nw_se(values: pd.Series | np.ndarray, lag: int) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    n_obs = len(arr)
    if n_obs < 2:
        return float("nan")
    centered = arr - arr.mean()
    gamma0 = float(centered @ centered) / n_obs
    variance = gamma0
    use_lag = min(lag, n_obs - 1)
    for lag_idx in range(1, use_lag + 1):
        weight = 1.0 - lag_idx / (use_lag + 1.0)
        gamma_lag = float(centered[lag_idx:] @ centered[:-lag_idx]) / n_obs
        variance += 2.0 * weight * gamma_lag
    return float(np.sqrt(max(variance, 0.0) / n_obs))


def _stats_lag(values: pd.Series | np.ndarray, lag: int) -> dict[str, float | int]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return {"n": 0, "mean_R": np.nan, "NW_SE": np.nan, "NW_CI_low": np.nan}
    mean = float(arr.mean())
    se = _nw_se(arr, lag)
    ci_low = mean - 1.96 * se if np.isfinite(se) else np.nan
    return {"n": int(len(arr)), "mean_R": mean, "NW_SE": se, "NW_CI_low": ci_low}


def _diff_stats_lag(left: pd.Series, right: pd.Series, lag: int) -> dict[str, float | int]:
    left_stats = _stats_lag(left, lag)
    right_stats = _stats_lag(right, lag)
    diff = float(left_stats["mean_R"]) - float(right_stats["mean_R"])
    left_se = float(left_stats["NW_SE"])
    right_se = float(right_stats["NW_SE"])
    se = float(np.sqrt(left_se * left_se + right_se * right_se))
    ci_low = diff - 1.96 * se if np.isfinite(se) else np.nan
    return {
        "n": int(left_stats["n"]) + int(right_stats["n"]),
        "mean_R": diff,
        "NW_SE": se,
        "NW_CI_low": ci_low,
    }


def _quantile(values: pd.Series, quantile: float) -> float:
    arr = values.to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan")
    return float(np.quantile(arr, quantile))


def _hold_summary_rows(trades: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    groups = [("POOLED", "all", trades)]
    for direction in DIRECTIONS:
        groups.append(("POOLED", direction, trades[trades["direction"] == direction]))
    for evaluator in EVALUATORS:
        for direction in DIRECTIONS:
            sub = trades[
                (trades["evaluator"] == evaluator)
                & (trades["direction"] == direction)
            ]
            groups.append((evaluator, direction, sub))

    for cell, direction, sub in groups:
        hold = sub["realized_hold"]
        rows.append({
            "row_type": "realized_hold_summary",
            "sleeve": cell,
            "direction": direction,
            "regime_bucket": "realized_hold",
            "regime": "realized_hold",
            "half": "full",
            "L": "",
            "L_label": "",
            "n": int(hold.count()),
            "mean_R": float(hold.mean()) if not hold.empty else np.nan,
            "NW_SE": np.nan,
            "NW_CI_low": np.nan,
            "hold_median": float(hold.median()) if not hold.empty else np.nan,
            "hold_mean": float(hold.mean()) if not hold.empty else np.nan,
            "hold_q10": _quantile(hold, 0.10),
            "hold_q25": _quantile(hold, 0.25),
            "hold_q75": _quantile(hold, 0.75),
            "hold_q90": _quantile(hold, 0.90),
            "dedup_drop": np.nan,
        })
    return rows


def _half_labels(sub: pd.DataFrame) -> pd.Series:
    ordered = sub.sort_values(["ts", "pair"]).reset_index()
    cut = len(ordered) // 2
    labels = pd.Series("h2", index=ordered["index"], dtype=object)
    labels.loc[ordered.iloc[:cut]["index"]] = "h1"
    return labels


def _dedup_sleeve(
    trades: pd.DataFrame,
    cells: Iterable[str],
    direction: str,
) -> tuple[pd.DataFrame, int, int]:
    sub = trades[
        trades["evaluator"].isin(cells)
        & (trades["direction"] == direction)
        & trades["atr_bucket"].isin(REGIME_ORDER)
    ].copy()
    pre_count = len(sub)
    sort_cols = ["pair", "bar_idx", "direction", "evaluator", "ts"]
    dedup = sub.sort_values(sort_cols).drop_duplicates(["pair", "bar_idx", "direction"])
    dedup = dedup.sort_values(["ts", "pair"]).copy()
    dedup["half"] = ""
    labels = _half_labels(dedup)
    dedup.loc[labels.index, "half"] = labels
    return dedup, pre_count, pre_count - len(dedup)


def _curve_rows_for_sleeve(
    sleeve: str,
    direction: str,
    sub: pd.DataFrame,
    half: str,
    lag: int,
    lag_label: str,
    dedup_drop: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for bucket in REGIME_ORDER:
        stats = _stats_lag(sub.loc[sub["atr_bucket"] == bucket, "R"], lag)
        rows.append({
            "row_type": "sleeve_curve",
            "sleeve": sleeve,
            "direction": direction,
            "regime_bucket": bucket,
            "regime": REGIME_LABEL[bucket],
            "half": half,
            "L": lag,
            "L_label": lag_label,
            **stats,
            "hold_median": np.nan,
            "hold_mean": np.nan,
            "hold_q10": np.nan,
            "hold_q25": np.nan,
            "hold_q75": np.nan,
            "hold_q90": np.nan,
            "dedup_drop": dedup_drop,
        })
    low_mid = sub.loc[sub["atr_bucket"].isin(REGIME_ORDER[:2]), "R"]
    high = sub.loc[sub["atr_bucket"] == REGIME_ORDER[2], "R"]
    for bucket, stats in (
        ("ATR_low_mid_0_67", _stats_lag(low_mid, lag)),
        ("ATR_low_mid_minus_high", _diff_stats_lag(low_mid, high, lag)),
    ):
        rows.append({
            "row_type": "sleeve_curve",
            "sleeve": sleeve,
            "direction": direction,
            "regime_bucket": bucket,
            "regime": bucket.replace("ATR_", ""),
            "half": half,
            "L": lag,
            "L_label": lag_label,
            **stats,
            "hold_median": np.nan,
            "hold_mean": np.nan,
            "hold_q10": np.nan,
            "hold_q25": np.nan,
            "hold_q75": np.nan,
            "hold_q90": np.nan,
            "dedup_drop": dedup_drop,
        })
    return rows


def _build_sleeve_curves(
    sleeves: dict[tuple[str, str], pd.DataFrame],
    drops: dict[tuple[str, str], int],
    lags: list[int],
    corrected_lag: int,
    mean_lag: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (sleeve, direction), sleeve_trades in sleeves.items():
        for half in ("full", "h1", "h2"):
            sub = sleeve_trades if half == "full" else sleeve_trades[sleeve_trades["half"] == half]
            for lag in lags:
                rows.extend(_curve_rows_for_sleeve(
                    sleeve,
                    direction,
                    sub,
                    half,
                    lag,
                    _lag_label(lag, corrected_lag, mean_lag),
                    drops[(sleeve, direction)],
                ))
    return pd.DataFrame(rows)


def _sleeve_gate(sub: pd.DataFrame, lag: int, pairs: list[str]) -> dict[str, object]:
    low_mid = sub.loc[sub["atr_bucket"].isin(REGIME_ORDER[:2]), "R"]
    high = sub.loc[sub["atr_bucket"] == REGIME_ORDER[2], "R"]
    low_mid_stats = _stats_lag(low_mid, lag)
    diff = _diff_stats_lag(low_mid, high, lag)
    pair = _pair_robustness_lowmid(sub, pairs)
    return {
        "low_mid_mean": float(low_mid_stats["mean_R"]),
        "low_mid_nw_ci_low": float(low_mid_stats["NW_CI_low"]),
        "uplift": float(diff["mean_R"]),
        "uplift_nw_se": float(diff["NW_SE"]),
        "uplift_nw_ci_low": float(diff["NW_CI_low"]),
        "nw_positive": float(diff["NW_CI_low"]) > 0.0,
        "direction_positive": float(diff["mean_R"]) > 0.0,
        "low_mid_tradeable": float(low_mid_stats["NW_CI_low"]) > 0.0,
        **pair,
    }


def _pair_robustness_lowmid(sub: pd.DataFrame, pairs: list[str]) -> dict[str, float | int | bool]:
    positive = 0
    comparable = 0
    for pair in pairs:
        pair_sub = sub[sub["pair"] == pair]
        low_mid = pair_sub.loc[pair_sub["atr_bucket"].isin(REGIME_ORDER[:2]), "R"]
        high = pair_sub.loc[pair_sub["atr_bucket"] == REGIME_ORDER[2], "R"]
        if low_mid.empty or high.empty:
            continue
        comparable += 1
        if float(low_mid.mean()) > float(high.mean()):
            positive += 1
    return {
        "pair_positive": positive,
        "pair_comparable": comparable,
        "pair_total": len(pairs),
        "pair_fraction_17": positive / len(pairs) if pairs else np.nan,
        "pair_fraction_comparable": positive / comparable if comparable else np.nan,
        "pair_majority_17": positive > len(pairs) / 2.0,
    }


def _sleeve_summary(
    sleeves: dict[tuple[str, str], pd.DataFrame],
    lags: list[int],
    pairs: list[str],
) -> pd.DataFrame:
    rows = []
    for (sleeve, direction), sleeve_trades in sleeves.items():
        for lag in lags:
            full = _sleeve_gate(sleeve_trades, lag, pairs)
            h1 = _sleeve_gate(sleeve_trades[sleeve_trades["half"] == "h1"], lag, pairs)
            h2 = _sleeve_gate(sleeve_trades[sleeve_trades["half"] == "h2"], lag, pairs)
            rows.append({
                "sleeve": sleeve,
                "direction": direction,
                "L": lag,
                **{f"full_{key}": value for key, value in full.items()},
                **{f"h1_{key}": value for key, value in h1.items()},
                **{f"h2_{key}": value for key, value in h2.items()},
                "both_halves_direction_positive": bool(
                    h1["direction_positive"] and h2["direction_positive"]
                ),
                "full_gate": bool(full["nw_positive"] and full["pair_majority_17"]),
            })
    return pd.DataFrame(rows)


def _per_cell_recheck(trades: pd.DataFrame, pairs: list[str], lag: int) -> pd.DataFrame:
    rows = []
    for evaluator in EVALUATORS:
        for direction in DIRECTIONS:
            sub = trades[(trades["evaluator"] == evaluator) & (trades["direction"] == direction)]
            full = _gate_for_subset_lag(sub, lag)
            p1_lag = _gate_for_subset(sub)
            pair = _pair_robustness(sub, pairs)
            rows.append({
                "cell": evaluator,
                "direction": direction,
                "L": lag,
                **{f"corrected_{key}": value for key, value in full.items()},
                "p1_l83_diff_nw_ci_low": p1_lag["diff_nw_ci_low"],
                "p1_l83_low_mid_nw_ci_low": p1_lag["low_mid_nw_ci_low"],
                "ci_strengthened_vs_l83": (
                    full["diff_nw_ci_low"] > p1_lag["diff_nw_ci_low"]
                    and full["low_mid_nw_ci_low"] > p1_lag["low_mid_nw_ci_low"]
                ),
                **pair,
            })
    return pd.DataFrame(rows)


def _gate_for_subset_lag(sub: pd.DataFrame, lag: int) -> dict[str, float | bool | int]:
    low = sub.loc[sub["atr_bucket"] == REGIME_ORDER[0], "R"]
    mid = sub.loc[sub["atr_bucket"] == REGIME_ORDER[1], "R"]
    high = sub.loc[sub["atr_bucket"] == REGIME_ORDER[2], "R"]
    low_mid = sub.loc[sub["atr_bucket"].isin(REGIME_ORDER[:2]), "R"]
    low_stats = _stats_lag(low, lag)
    mid_stats = _stats_lag(mid, lag)
    high_stats = _stats_lag(high, lag)
    low_mid_stats = _stats_lag(low_mid, lag)
    diff_stats = _diff_stats_lag(low_mid, high, lag)
    low_gt_high = float(low_stats["mean_R"]) > float(high_stats["mean_R"])
    low_mid_positive = float(low_mid_stats["NW_CI_low"]) > 0.0
    diff_positive = float(diff_stats["NW_CI_low"]) > 0.0
    return {
        "n_low": int(low_stats["n"]),
        "n_mid": int(mid_stats["n"]),
        "n_high": int(high_stats["n"]),
        "low_mean": float(low_stats["mean_R"]),
        "mid_mean": float(mid_stats["mean_R"]),
        "high_mean": float(high_stats["mean_R"]),
        "low_mid_mean": float(low_mid_stats["mean_R"]),
        "low_mid_nw_ci_low": float(low_mid_stats["NW_CI_low"]),
        "low_mid_vs_high": float(diff_stats["mean_R"]),
        "diff_nw_se": float(diff_stats["NW_SE"]),
        "diff_nw_ci_low": float(diff_stats["NW_CI_low"]),
        "low_gt_high": low_gt_high,
        "mid_gt_high": float(mid_stats["mean_R"]) > float(high_stats["mean_R"]),
        "low_mid_positive": low_mid_positive,
        "diff_positive": diff_positive,
        "gate": low_mid_positive and diff_positive and low_gt_high,
    }


def _format_bool(value: object) -> str:
    return "YES" if bool(value) else "NO"


def _report(
    hold_rows: list[dict[str, object]],
    cell_recheck: pd.DataFrame,
    sleeve_summary: pd.DataFrame,
    dedup_rows: pd.DataFrame,
    corrected_lag: int,
    mean_lag: int,
    lags: list[int],
) -> str:
    hold_df = pd.DataFrame(hold_rows)
    pooled = hold_df[
        (hold_df["sleeve"] == "POOLED") & (hold_df["direction"] == "all")
    ].iloc[0]
    headline = sleeve_summary[
        (sleeve_summary["sleeve"] == "long_mr_strong4")
        & (sleeve_summary["direction"] == "long")
        & (sleeve_summary["L"] == corrected_lag)
    ].iloc[0]
    full6 = sleeve_summary[
        (sleeve_summary["sleeve"] == "long_mr_full6")
        & (sleeve_summary["direction"] == "long")
        & (sleeve_summary["L"] == corrected_lag)
    ].iloc[0]
    advance = bool(
        headline.full_nw_positive
        and headline.both_halves_direction_positive
        and headline.full_pair_majority_17
        and headline.full_low_mid_tradeable
    )
    lines = [
        "# ATR Regime P1b",
        "",
        "## Method",
        (
            f"Simulated `depth_fires.csv` with `_lib.py` mid-entry R machinery, "
            f"TP={TP_PCT:.0%}, SL={STOP_PCT:.0%}, and `MAX_HOLD={MAX_HOLD}` H4 bars."
        ),
        (
            "Realized hold is `exit_idx - entry_idx`. The corrected primary Newey-West "
            f"lag is `L = round(pooled median realized hold) - 1 = {corrected_lag}`. "
            f"Sensitivity lags are `{lags}`; mean-derived L is {mean_lag} and "
            f"`MAX_HOLD - 1` is {MAX_HOLD - 1}."
        ),
        (
            "Sleeves are book-level deduped at one trade per `(pair, entry_bar, direction)`. "
            "The primary gate is the strong-4 long sleeve full-sample NW-positive "
            "low/mid-minus-high uplift, direction positive in both halves, per-pair majority, "
            "and absolute low/mid +R."
        ),
        "",
        "## Headline",
        (
            f"Strong-4 long sleeve at corrected L={corrected_lag}: "
            f"low/mid={_fmt(headline.full_low_mid_mean)} "
            f"(NW_CI_low={_fmt(headline.full_low_mid_nw_ci_low)}), "
            f"low/mid-high={_fmt(headline.full_uplift)} "
            f"(NW_CI_low={_fmt(headline.full_uplift_nw_ci_low)}), "
            f"both-halves direction={_format_bool(headline.both_halves_direction_positive)}, "
            f"per-pair majority={headline.full_pair_positive}/{headline.full_pair_total}."
        ),
        (
            f"Full-6 long sleeve at corrected L={corrected_lag}: "
            f"low/mid={_fmt(full6.full_low_mid_mean)} "
            f"(NW_CI_low={_fmt(full6.full_low_mid_nw_ci_low)}), "
            f"low/mid-high={_fmt(full6.full_uplift)} "
            f"(NW_CI_low={_fmt(full6.full_uplift_nw_ci_low)}), "
            f"both-halves direction={_format_bool(full6.both_halves_direction_positive)}, "
            f"per-pair majority={full6.full_pair_positive}/{full6.full_pair_total}."
        ),
        (
            "Strong-4 half-level NW detail: "
            f"h1 uplift={_fmt(headline.h1_uplift)} "
            f"(NW_CI_low={_fmt(headline.h1_uplift_nw_ci_low)}, "
            f"NW-positive={_format_bool(headline.h1_nw_positive)}); "
            f"h2 uplift={_fmt(headline.h2_uplift)} "
            f"(NW_CI_low={_fmt(headline.h2_uplift_nw_ci_low)}, "
            f"NW-positive={_format_bool(headline.h2_nw_positive)})."
        ),
        (
            "Absolute tradeability at corrected L: "
            f"strong-4 low/mid +R={_format_bool(headline.full_low_mid_tradeable)}; "
            f"full-6 low/mid +R={_format_bool(full6.full_low_mid_tradeable)}."
        ),
    ]
    if advance:
        lines.append(
            "Verdict: the long-MR sleeve holds at book level with corrected L; advance to "
            "P2 for alpha-vs-beta regime baseline."
        )
    else:
        lines.append(
            "Verdict: the long-MR sleeve does not clear the corrected book-level gate; treat "
            "this as a genuine null and route to relative-value / door #2."
        )
    lines.append(
        "Plain call: if this sleeve holds, P2 is warranted; if it dies here with corrected L, "
        "there is no volatility-regime conditioner to deploy from P1."
    )
    lines.extend([
        "",
        "## Realized Hold",
        (
            f"Pooled all trades n={int(pooled.n)}, median={pooled.hold_median:.2f}, "
            f"mean={pooled.hold_mean:.2f}, q10={pooled.hold_q10:.2f}, "
            f"q25={pooled.hold_q25:.2f}, q75={pooled.hold_q75:.2f}, "
            f"q90={pooled.hold_q90:.2f}."
        ),
        "",
        "## Dedup Sanity",
    ])
    lines.extend(_markdown_table(
        dedup_rows,
        ["sleeve", "direction", "sum_cell_trades", "deduped_trades", "dedup_drop"],
    ))
    lines.extend(["", "## Per-Cell Corrected-L Recheck"])
    lines.append(
        "Corrected L does not uniformly strengthen the four long cells versus L=83; "
        "the book-level sleeve is the primary P1b gate."
    )
    strong_long = cell_recheck[
        cell_recheck["cell"].isin(STRONG_CELLS) & (cell_recheck["direction"] == "long")
    ].sort_values("cell")
    for row in strong_long.itertuples(index=False):
        lines.append(
            f"- {row.cell} long: corrected diff CI_low={_fmt(row.corrected_diff_nw_ci_low)} "
            f"vs P1 L83={_fmt(row.p1_l83_diff_nw_ci_low)}; corrected low/mid CI_low="
            f"{_fmt(row.corrected_low_mid_nw_ci_low)} vs P1 L83="
            f"{_fmt(row.p1_l83_low_mid_nw_ci_low)}; strengthened="
            f"{_format_bool(row.ci_strengthened_vs_l83)}."
        )
    lines.extend(["", "## L Sensitivity"])
    sens_cols = [
        "sleeve",
        "direction",
        "L",
        "full_low_mid_mean",
        "full_low_mid_nw_ci_low",
        "full_uplift",
        "full_uplift_nw_ci_low",
        "both_halves_direction_positive",
        "full_pair_positive",
        "full_pair_total",
    ]
    sens = sleeve_summary[
        sleeve_summary["sleeve"].isin(["long_mr_strong4", "long_mr_full6"])
        & (sleeve_summary["direction"] == "long")
    ].sort_values(["sleeve", "L"])
    lines.extend(_markdown_table(sens, sens_cols))
    lines.extend(["", "## Short Sleeve Completeness"])
    shorts = sleeve_summary[
        (sleeve_summary["direction"] == "short") & (sleeve_summary["L"] == corrected_lag)
    ].sort_values("sleeve")
    for row in shorts.itertuples(index=False):
        lines.append(
            f"- {row.sleeve} short: low/mid={_fmt(row.full_low_mid_mean)} "
            f"(NW_CI_low={_fmt(row.full_low_mid_nw_ci_low)}), low/mid-high="
            f"{_fmt(row.full_uplift)} (NW_CI_low={_fmt(row.full_uplift_nw_ci_low)}), "
            f"both-halves direction={_format_bool(row.both_halves_direction_positive)}, "
            f"pairs={row.full_pair_positive}/{row.full_pair_total}."
        )
    lines.extend(["", "## Artifacts"])
    lines.append(f"- `{CURVES_PATH.name}`: sleeve curves plus realized-hold rows.")
    lines.append(f"- `{OUT_PATH.name}`: run summary.")
    lines.append("")
    return "\n".join(lines)


def run() -> tuple[pd.DataFrame, str]:
    cells = deployed_cells()
    pairs = sorted({cell.pair for cell in cells})
    modes = _entry_modes(cells)
    fires = pd.read_csv(FIRES_PATH, parse_dates=["ts"])
    fires = fires[fires["evaluator"].isin(EVALUATORS)].copy()
    bad_modes = []
    for evaluator, mode in modes.items():
        actual = sorted(fires.loc[fires["evaluator"] == evaluator, "entry_mode"].unique())
        if actual != [mode]:
            bad_modes.append((evaluator, actual, mode))
    if bad_modes:
        raise RuntimeError(f"P0 fire entry modes do not match deployed modes: {bad_modes}")

    trades, drops, _source_check = _simulate_trades(fires, pairs)
    trades = trades.copy()
    trades["realized_hold"] = trades["exit_idx"] - trades["bar_idx"]
    trades = _attach_halves(trades)
    pooled_hold = trades["realized_hold"]
    corrected_lag = _clean_lag(float(pooled_hold.median()))
    mean_lag = _clean_lag(float(pooled_hold.mean()))
    lags = sorted({corrected_lag, mean_lag, MAX_HOLD - 1})

    sleeve_trades: dict[tuple[str, str], pd.DataFrame] = {}
    dedup_drops: dict[tuple[str, str], int] = {}
    dedup_rows = []
    for sleeve, sleeve_cells in SLEEVES.items():
        for direction in DIRECTIONS:
            deduped, pre_count, drop_count = _dedup_sleeve(trades, sleeve_cells, direction)
            sleeve_trades[(sleeve, direction)] = deduped
            dedup_drops[(sleeve, direction)] = drop_count
            dedup_rows.append({
                "sleeve": sleeve,
                "direction": direction,
                "sum_cell_trades": pre_count,
                "deduped_trades": len(deduped),
                "dedup_drop": drop_count,
            })
            if len(deduped) > pre_count:
                raise RuntimeError(f"dedup count exceeded source count for {sleeve} {direction}")

    curves = _build_sleeve_curves(
        sleeve_trades,
        dedup_drops,
        lags,
        corrected_lag,
        mean_lag,
    )
    hold_rows = _hold_summary_rows(trades)
    all_curves = pd.concat([curves, pd.DataFrame(hold_rows)], ignore_index=True)
    sleeve_summary = _sleeve_summary(sleeve_trades, lags, pairs)
    cell_recheck = _per_cell_recheck(trades, pairs, corrected_lag)
    dedup_df = pd.DataFrame(dedup_rows)
    report = _report(
        hold_rows,
        cell_recheck,
        sleeve_summary,
        dedup_df,
        corrected_lag,
        mean_lag,
        lags,
    )

    all_curves.to_csv(CURVES_PATH, index=False)
    REPORT_PATH.write_text(report, encoding="utf-8")
    headline = sleeve_summary[
        (sleeve_summary["sleeve"] == "long_mr_strong4")
        & (sleeve_summary["direction"] == "long")
        & (sleeve_summary["L"] == corrected_lag)
    ].iloc[0]
    out_lines = [
        "ATR-regime P1b run complete",
        f"pairs={len(pairs)} regime_trades={len(trades):,}",
        f"MAX_HOLD={MAX_HOLD} corrected_L={corrected_lag} mean_L={mean_lag} lags={lags}",
        f"TP={TP_PCT:.4f} STOP={STOP_PCT:.4f}",
        f"count_sanity_pass={bool(drops['matches_p1'].all())}",
        f"strong4_long_full_uplift={headline.full_uplift:+.6f}",
        f"strong4_long_full_uplift_nw_ci_low={headline.full_uplift_nw_ci_low:+.6f}",
        f"strong4_long_both_halves_direction={bool(headline.both_halves_direction_positive)}",
        f"strong4_long_pair_majority={bool(headline.full_pair_majority_17)}",
    ]
    OUT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    if not bool(drops["matches_p1"].all()):
        raise RuntimeError("realized trade counts do not match P1")
    return all_curves, report


def main() -> None:
    run()


if __name__ == "__main__":
    main()
