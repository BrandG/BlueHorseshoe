"""ATR-regime P2 alpha-vs-beta baseline and robustness checks."""
# pylint: disable=import-error,wrong-import-order,wrong-import-position
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-locals
# pylint: disable=too-many-statements,too-many-branches,too-many-return-statements
# pylint: disable=too-many-positional-arguments,protected-access,duplicate-code
from __future__ import annotations

import sys
from pathlib import Path

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

from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators import atr, ohlc_mid  # noqa: E402
from factor_grouping import deployed_cells  # noqa: E402
from _lib import MAX_HOLD, STOP_PCT, TP_PCT, sim_long_mid  # noqa: E402
from atr_regime_p1 import (  # noqa: E402
    ATR_PERCENTILE_WINDOW,
    DIRECTIONS,
    EVALUATORS,
    FIRES_PATH,
    REGIME_LABEL,
    REGIME_ORDER,
    _attach_halves,
    _atr_bucket,
    _entry_modes,
    _fmt,
    _markdown_table,
    _rolling_percentile,
    _simulate_trades,
)
from atr_regime_p1b import (  # noqa: E402
    SLEEVES,
    _clean_lag,
    _dedup_sleeve,
    _diff_stats_lag,
    _stats_lag,
)

LAG = 22
PRIMARY_SLEEVE = "long_mr_strong4"
PRIMARY_DIRECTION = "long"
BASELINE_PATH = OUT_DIR / "atr_regime_p2_baseline.csv"
REPORT_PATH = OUT_DIR / "ATR_REGIME_P2.md"
OUT_PATH = OUT_DIR / "atr_regime_p2.out"
LIMIT_LEDGER_PATH = ROOT / "research" / "v2_executable_regate" / "seed" / "ledger_tp05.csv"
METRIC_FORMULATIONS = ("atr_percentile", "absolute_atr", "atr_over_price")


def _stats(values: pd.Series | np.ndarray, lag: int = LAG) -> dict[str, float | int]:
    return _stats_lag(values, lag)


def _diff_stats(left: pd.Series, right: pd.Series, lag: int = LAG) -> dict[str, float | int]:
    return _diff_stats_lag(left, right, lag)


def _ci_low(mean: float, se: float) -> float:
    return mean - 1.96 * se if np.isfinite(se) else np.nan


def _ci_high(mean: float, se: float) -> float:
    return mean + 1.96 * se if np.isfinite(se) else np.nan


def _cluster_se_for_contrast(
    frame: pd.DataFrame,
    bucket_col: str,
    left_buckets: tuple[str, ...],
    right_buckets: tuple[str, ...],
    value_col: str = "R",
) -> float:
    left_mask = frame[bucket_col].isin(left_buckets)
    right_mask = frame[bucket_col].isin(right_buckets)
    left = frame.loc[left_mask, value_col].to_numpy(float)
    right = frame.loc[right_mask, value_col].to_numpy(float)
    if len(left) < 2 or len(right) < 2:
        return float("nan")
    left_mean = float(np.mean(left))
    right_mean = float(np.mean(right))
    left_n = len(left)
    right_n = len(right)
    contrib = pd.Series(0.0, index=frame.index, dtype=float)
    contrib.loc[left_mask] = (frame.loc[left_mask, value_col] - left_mean) / left_n
    contrib.loc[right_mask] = -(frame.loc[right_mask, value_col] - right_mean) / right_n
    clustered = contrib.groupby(frame["ts"], sort=False).sum().to_numpy(float)
    n_clusters = len(clustered)
    if n_clusters < 2:
        return float("nan")
    scale = n_clusters / (n_clusters - 1.0)
    return float(np.sqrt(max(scale * float(clustered @ clustered), 0.0)))


def _cluster_se_for_excess(
    sleeve: pd.DataFrame,
    baseline: pd.DataFrame,
    bucket_col: str,
    test: str,
) -> float:
    if test == "uplift":
        left_buckets = REGIME_ORDER[:2]
        right_buckets = REGIME_ORDER[2:]
    elif test == "low_mid":
        left_buckets = REGIME_ORDER[:2]
        right_buckets = ()
    else:
        raise ValueError(f"unsupported excess test: {test}")

    sleeve_contrib = _influence_by_ts(sleeve, bucket_col, left_buckets, right_buckets, sign=1.0)
    base_contrib = _influence_by_ts(baseline, bucket_col, left_buckets, right_buckets, sign=-1.0)
    combined = sleeve_contrib.add(base_contrib, fill_value=0.0).to_numpy(float)
    n_clusters = len(combined)
    if n_clusters < 2:
        return float("nan")
    scale = n_clusters / (n_clusters - 1.0)
    return float(np.sqrt(max(scale * float(combined @ combined), 0.0)))


def _influence_by_ts(
    frame: pd.DataFrame,
    bucket_col: str,
    left_buckets: tuple[str, ...],
    right_buckets: tuple[str, ...],
    *,
    sign: float,
) -> pd.Series:
    contrib = pd.Series(0.0, index=frame.index, dtype=float)
    for buckets, side_sign in ((left_buckets, 1.0), (right_buckets, -1.0)):
        if not buckets:
            continue
        mask = frame[bucket_col].isin(buckets)
        values = frame.loc[mask, "R"].to_numpy(float)
        if len(values) == 0:
            continue
        mean = float(np.mean(values))
        contrib.loc[mask] = sign * side_sign * (frame.loc[mask, "R"] - mean) / len(values)
    return contrib.groupby(frame["ts"], sort=False).sum()


def _tercile_bucket(value: float, low_cut: float, high_cut: float) -> str:
    if not np.isfinite(value) or not np.isfinite(low_cut) or not np.isfinite(high_cut):
        return "ATR_missing"
    if value <= low_cut:
        return REGIME_ORDER[0]
    if value <= high_cut:
        return REGIME_ORDER[1]
    return REGIME_ORDER[2]


def _quantile_cuts(values: pd.Series) -> tuple[float, float]:
    arr = values.to_numpy(float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan"), float("nan")
    return float(np.quantile(arr, 1.0 / 3.0)), float(np.quantile(arr, 2.0 / 3.0))


def _load_fires_and_pairs() -> tuple[pd.DataFrame, list[str], dict[str, str]]:
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
    return fires, pairs, modes


def _pair_metric_frame(
    store: FxStore,
    pair: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    raw = store.load(pair, granularity="H4", include_incomplete=False)
    if raw.empty:
        raise RuntimeError(f"no complete H4 bars for {pair}")
    mid = ohlc_mid(raw)
    timestamps = pd.to_datetime(raw["timestamp"])
    atr_values = atr(mid, period=14)
    frame = pd.DataFrame({
        "pair": pair,
        "ts": timestamps,
        "bar_idx": np.arange(len(timestamps), dtype=int),
        "close": mid["close"].to_numpy(float),
        "high": mid["high"].to_numpy(float),
        "low": mid["low"].to_numpy(float),
        "entry_ATR": atr_values.to_numpy(float),
        "ATR_percentile": _rolling_percentile(atr_values, ATR_PERCENTILE_WINDOW).to_numpy(float),
    })
    frame["atr_over_price"] = frame["entry_ATR"] / frame["close"]
    frame["eligible_entry"] = (
        (frame["ts"] >= start_ts)
        & (frame["ts"] <= end_ts)
        & frame["ATR_percentile"].notna()
        & frame["entry_ATR"].notna()
        & frame["atr_over_price"].notna()
        & (frame["bar_idx"] + MAX_HOLD < len(frame))
    )
    return frame


def _metric_cut_map(
    store: FxStore,
    pairs: list[str],
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> tuple[dict[str, pd.DataFrame], dict[tuple[str, str], tuple[float, float]]]:
    metric_frames: dict[str, pd.DataFrame] = {}
    cuts: dict[tuple[str, str], tuple[float, float]] = {}
    for pair in pairs:
        pair_frame = _pair_metric_frame(store, pair, start_ts, end_ts)
        metric_frames[pair] = pair_frame
        eligible = pair_frame[pair_frame["eligible_entry"]]
        cuts[(pair, "absolute_atr")] = _quantile_cuts(eligible["entry_ATR"])
        cuts[(pair, "atr_over_price")] = _quantile_cuts(eligible["atr_over_price"])
    return metric_frames, cuts


def _simulate_all_bars_baseline(metric_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for pair, frame in metric_frames.items():
        close = frame["close"].to_numpy(float)
        high = frame["high"].to_numpy(float)
        low = frame["low"].to_numpy(float)
        for row in frame[frame["eligible_entry"]].itertuples(index=False):
            r_value, exit_idx = sim_long_mid(close, high, low, int(row.bar_idx), MAX_HOLD)
            if r_value is None:
                continue
            rows.append({
                "pair": pair,
                "ts": pd.Timestamp(row.ts),
                "bar_idx": int(row.bar_idx),
                "exit_idx": int(exit_idx),
                "direction": "long",
                "entry_mode": "mid",
                "R": float(r_value),
                "entry_ATR": float(row.entry_ATR),
                "ATR_percentile": float(row.ATR_percentile),
                "atr_over_price": float(row.atr_over_price),
                "atr_bucket": _atr_bucket(float(row.ATR_percentile)),
            })
    baseline = pd.DataFrame(rows)
    if baseline.empty:
        raise RuntimeError("all-bars baseline produced no trades")
    return baseline[baseline["atr_bucket"].isin(REGIME_ORDER)].copy()


def _attach_metric_buckets(
    frame: pd.DataFrame,
    cuts: dict[tuple[str, str], tuple[float, float]],
) -> pd.DataFrame:
    out = frame.copy()
    for formulation in ("absolute_atr", "atr_over_price"):
        metric_col = "entry_ATR" if formulation == "absolute_atr" else "atr_over_price"
        bucket_col = f"{formulation}_bucket"
        buckets = []
        for row in out.itertuples(index=False):
            low_cut, high_cut = cuts[(str(row.pair), formulation)]
            buckets.append(_tercile_bucket(float(getattr(row, metric_col)), low_cut, high_cut))
        out[bucket_col] = buckets
    return out


def _attach_sleeve_metric_values(
    trades: pd.DataFrame,
    metric_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    out = trades.copy()
    out["atr_over_price"] = np.nan
    for pair, metric_frame in metric_frames.items():
        by_ts = metric_frame.set_index("ts")
        mask = out["pair"] == pair
        ts_values = out.loc[mask, "ts"]
        out.loc[mask, "atr_over_price"] = ts_values.map(by_ts["atr_over_price"])
    out = out.dropna(subset=["atr_over_price"]).copy()
    return out


def _build_sleeves(trades: pd.DataFrame) -> tuple[dict[tuple[str, str], pd.DataFrame], pd.DataFrame]:
    sleeve_trades: dict[tuple[str, str], pd.DataFrame] = {}
    dedup_rows = []
    for sleeve, sleeve_cells in SLEEVES.items():
        for direction in DIRECTIONS:
            deduped, pre_count, drop_count = _dedup_sleeve(trades, sleeve_cells, direction)
            sleeve_trades[(sleeve, direction)] = deduped
            dedup_rows.append({
                "sleeve": sleeve,
                "direction": direction,
                "sum_cell_trades": pre_count,
                "deduped_trades": len(deduped),
                "dedup_drop": drop_count,
            })
    return sleeve_trades, pd.DataFrame(dedup_rows)


def _bucket_col(formulation: str) -> str:
    if formulation == "atr_percentile":
        return "atr_bucket"
    return f"{formulation}_bucket"


def _curve_summary(
    frame: pd.DataFrame,
    *,
    sample: str,
    formulation: str,
    sleeve: str,
    direction: str,
) -> list[dict[str, object]]:
    bucket_col = _bucket_col(formulation)
    rows: list[dict[str, object]] = []
    for bucket in REGIME_ORDER:
        stats = _stats(frame.loc[frame[bucket_col] == bucket, "R"])
        rows.append({
            "row_type": "curve",
            "sample": sample,
            "formulation": formulation,
            "sleeve": sleeve,
            "direction": direction,
            "metric": "bucket_mean",
            "regime_bucket": bucket,
            "regime": REGIME_LABEL[bucket],
            "L": LAG,
            **stats,
            "cluster_SE": np.nan,
            "cluster_CI_low": np.nan,
            "cluster_CI_high": np.nan,
            "baseline_n": np.nan,
            "sleeve_n": np.nan,
            "excess_mean_R": np.nan,
            "excess_NW_SE": np.nan,
            "excess_NW_CI_low": np.nan,
            "excess_cluster_SE": np.nan,
            "excess_cluster_CI_low": np.nan,
            "note": "",
        })
    low_mid = frame.loc[frame[bucket_col].isin(REGIME_ORDER[:2]), "R"]
    high = frame.loc[frame[bucket_col] == REGIME_ORDER[2], "R"]
    for metric, stats in (
        ("low_mid_mean", _stats(low_mid)),
        ("low_mid_minus_high", _diff_stats(low_mid, high)),
    ):
        cluster_se = np.nan
        if metric == "low_mid_minus_high":
            cluster_se = _cluster_se_for_contrast(
                frame,
                bucket_col,
                REGIME_ORDER[:2],
                REGIME_ORDER[2:],
            )
        mean_value = float(stats["mean_R"])
        rows.append({
            "row_type": "curve",
            "sample": sample,
            "formulation": formulation,
            "sleeve": sleeve,
            "direction": direction,
            "metric": metric,
            "regime_bucket": metric,
            "regime": metric,
            "L": LAG,
            **stats,
            "cluster_SE": cluster_se,
            "cluster_CI_low": _ci_low(mean_value, cluster_se),
            "cluster_CI_high": _ci_high(mean_value, cluster_se),
            "baseline_n": np.nan,
            "sleeve_n": np.nan,
            "excess_mean_R": np.nan,
            "excess_NW_SE": np.nan,
            "excess_NW_CI_low": np.nan,
            "excess_cluster_SE": np.nan,
            "excess_cluster_CI_low": np.nan,
            "note": "",
        })
    return rows


def _metric_value(frame: pd.DataFrame, formulation: str, metric: str) -> tuple[float, float, int]:
    bucket_col = _bucket_col(formulation)
    low_mid = frame.loc[frame[bucket_col].isin(REGIME_ORDER[:2]), "R"]
    if metric == "low_mid_mean":
        stats = _stats(low_mid)
    elif metric == "low_mid_minus_high":
        high = frame.loc[frame[bucket_col] == REGIME_ORDER[2], "R"]
        stats = _diff_stats(low_mid, high)
    else:
        raise ValueError(f"unsupported metric: {metric}")
    return float(stats["mean_R"]), float(stats["NW_SE"]), int(stats["n"])


def _excess_row(
    sleeve_frame: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    formulation: str,
    sleeve: str,
    direction: str,
    metric: str,
) -> dict[str, object]:
    sleeve_mean, sleeve_se, sleeve_n = _metric_value(sleeve_frame, formulation, metric)
    base_mean, base_se, base_n = _metric_value(baseline, formulation, metric)
    excess = sleeve_mean - base_mean
    nw_se = float(np.sqrt(sleeve_se * sleeve_se + base_se * base_se))
    cluster_se = np.nan
    if metric == "low_mid_minus_high":
        cluster_se = _cluster_se_for_excess(
            sleeve_frame,
            baseline,
            _bucket_col(formulation),
            "uplift",
        )
    elif metric == "low_mid_mean":
        cluster_se = _cluster_se_for_excess(
            sleeve_frame,
            baseline,
            _bucket_col(formulation),
            "low_mid",
        )
    return {
        "row_type": "excess",
        "sample": "sleeve_minus_all_bars_long",
        "formulation": formulation,
        "sleeve": sleeve,
        "direction": direction,
        "metric": metric,
        "regime_bucket": metric,
        "regime": metric,
        "L": LAG,
        "n": sleeve_n,
        "mean_R": sleeve_mean,
        "NW_SE": sleeve_se,
        "NW_CI_low": _ci_low(sleeve_mean, sleeve_se),
        "cluster_SE": np.nan,
        "cluster_CI_low": np.nan,
        "cluster_CI_high": np.nan,
        "baseline_n": base_n,
        "sleeve_n": sleeve_n,
        "excess_mean_R": excess,
        "excess_NW_SE": nw_se,
        "excess_NW_CI_low": _ci_low(excess, nw_se),
        "excess_cluster_SE": cluster_se,
        "excess_cluster_CI_low": _ci_low(excess, cluster_se),
        "note": "positive excess means sleeve is above unconditional all-bars long baseline",
    }


def _book_generalization_rows(trades: pd.DataFrame, pairs: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for direction in DIRECTIONS:
        dedup = (
            trades[trades["direction"] == direction]
            .sort_values(["pair", "bar_idx", "direction", "evaluator", "ts"])
            .drop_duplicates(["pair", "bar_idx", "direction"])
        )
        rows.extend(_curve_summary(
            dedup,
            sample="dislocation_full6_book_descriptive",
            formulation="atr_percentile",
            sleeve="dislocation_full6_book",
            direction=direction,
        ))
        pair_pos = 0
        pair_comp = 0
        for pair in pairs:
            sub = dedup[dedup["pair"] == pair]
            low_mid = sub.loc[sub["atr_bucket"].isin(REGIME_ORDER[:2]), "R"]
            high = sub.loc[sub["atr_bucket"] == REGIME_ORDER[2], "R"]
            if low_mid.empty or high.empty:
                continue
            pair_comp += 1
            pair_pos += int(float(low_mid.mean()) > float(high.mean()))
        rows.append({
            "row_type": "book_generalization",
            "sample": "dislocation_full6_book_descriptive",
            "formulation": "atr_percentile",
            "sleeve": "dislocation_full6_book",
            "direction": direction,
            "metric": "pair_low_mid_gt_high",
            "regime_bucket": "pair_low_mid_gt_high",
            "regime": "pair_low_mid_gt_high",
            "L": LAG,
            "n": len(dedup),
            "mean_R": pair_pos,
            "NW_SE": np.nan,
            "NW_CI_low": np.nan,
            "cluster_SE": np.nan,
            "cluster_CI_low": np.nan,
            "cluster_CI_high": np.nan,
            "baseline_n": np.nan,
            "sleeve_n": len(dedup),
            "excess_mean_R": np.nan,
            "excess_NW_SE": np.nan,
            "excess_NW_CI_low": np.nan,
            "excess_cluster_SE": np.nan,
            "excess_cluster_CI_low": np.nan,
            "note": f"{pair_pos}/{pair_comp} comparable pairs low/mid > high",
        })
    note = "limit-cell ATR/macd/ichimoku P0/P1 fires with ATR fields not available"
    if LIMIT_LEDGER_PATH.exists():
        ledger_cols = pd.read_csv(LIMIT_LEDGER_PATH, nrows=0).columns.tolist()
        note = (
            f"{LIMIT_LEDGER_PATH.relative_to(ROOT)} exists but has columns "
            f"{ledger_cols}; no ATR bucket fields, so limit-cell regime gradient not computed"
        )
    rows.append({
        "row_type": "book_generalization",
        "sample": "full_deployed_v2_book",
        "formulation": "atr_percentile",
        "sleeve": "full_deployed_v2_book",
        "direction": "both",
        "metric": "limit_cells_status",
        "regime_bucket": "not_computed",
        "regime": "not_computed",
        "L": LAG,
        "n": 0,
        "mean_R": np.nan,
        "NW_SE": np.nan,
        "NW_CI_low": np.nan,
        "cluster_SE": np.nan,
        "cluster_CI_low": np.nan,
        "cluster_CI_high": np.nan,
        "baseline_n": np.nan,
        "sleeve_n": np.nan,
        "excess_mean_R": np.nan,
        "excess_NW_SE": np.nan,
        "excess_NW_CI_low": np.nan,
        "excess_cluster_SE": np.nan,
        "excess_cluster_CI_low": np.nan,
        "note": note,
    })
    return rows


def _build_results(
    trades: pd.DataFrame,
    baseline: pd.DataFrame,
    sleeve_trades: dict[tuple[str, str], pd.DataFrame],
    pairs: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for formulation in METRIC_FORMULATIONS:
        rows.extend(_curve_summary(
            baseline,
            sample="all_bars_long",
            formulation=formulation,
            sleeve="all_bars_long",
            direction="long",
        ))
        for (sleeve, direction), sleeve_frame in sleeve_trades.items():
            rows.extend(_curve_summary(
                sleeve_frame,
                sample="deduped_sleeve",
                formulation=formulation,
                sleeve=sleeve,
                direction=direction,
            ))
            if direction == "long":
                for metric in ("low_mid_minus_high", "low_mid_mean"):
                    rows.append(_excess_row(
                        sleeve_frame,
                        baseline,
                        formulation=formulation,
                        sleeve=sleeve,
                        direction=direction,
                        metric=metric,
                    ))
    rows.extend(_book_generalization_rows(trades, pairs))
    return pd.DataFrame(rows)


def _select_row(
    results: pd.DataFrame,
    row_type: str,
    sample: str,
    formulation: str,
    sleeve: str,
    direction: str,
    metric: str,
) -> pd.Series:
    sub = results[
        (results["row_type"] == row_type)
        & (results["sample"] == sample)
        & (results["formulation"] == formulation)
        & (results["sleeve"] == sleeve)
        & (results["direction"] == direction)
        & (results["metric"] == metric)
    ]
    if sub.empty:
        raise RuntimeError(f"missing result row: {row_type} {sample} {sleeve} {metric}")
    return sub.iloc[0]


def _fmt_n(value: object) -> str:
    if pd.isna(value):
        return "nan"
    return f"{int(value):,}"


def _alpha_call(results: pd.DataFrame) -> tuple[str, bool]:
    uplift = _select_row(
        results,
        "excess",
        "sleeve_minus_all_bars_long",
        "atr_percentile",
        PRIMARY_SLEEVE,
        PRIMARY_DIRECTION,
        "low_mid_minus_high",
    )
    low_mid = _select_row(
        results,
        "excess",
        "sleeve_minus_all_bars_long",
        "atr_percentile",
        PRIMARY_SLEEVE,
        PRIMARY_DIRECTION,
        "low_mid_mean",
    )
    alpha = bool(uplift.excess_NW_CI_low > 0.0 and low_mid.excess_NW_CI_low > 0.0)
    clustered = bool(uplift.excess_cluster_CI_low > 0.0 and low_mid.excess_cluster_CI_low > 0.0)
    variants = _metric_variant_summary(results)
    metric_robust = bool(variants["passes_nw"].all() and variants["passes_cluster"].all())
    if alpha and clustered and metric_robust:
        return "cell alpha above all-bars long baseline and robust across ATR metrics", True
    if alpha and clustered:
        return "percentile cell alpha, but not robust across ATR metric formulations", False
    if alpha:
        return "NW alpha, but date-clustered excess is not clean", False
    return "approximately generic long vol-beta, not cell alpha", False


def _metric_variant_summary(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for formulation in METRIC_FORMULATIONS:
        row = _select_row(
            results,
            "curve",
            "deduped_sleeve",
            formulation,
            PRIMARY_SLEEVE,
            PRIMARY_DIRECTION,
            "low_mid_minus_high",
        )
        rows.append({
            "formulation": formulation,
            "uplift": row.mean_R,
            "nw_ci_low": row.NW_CI_low,
            "cluster_ci_low": row.cluster_CI_low,
            "n": row.n,
            "passes_nw": row.NW_CI_low > 0.0,
            "passes_cluster": row.cluster_CI_low > 0.0,
        })
    return pd.DataFrame(rows)


def _report(results: pd.DataFrame, dedup_rows: pd.DataFrame) -> str:
    call, advance = _alpha_call(results)
    sleeve_uplift = _select_row(
        results,
        "curve",
        "deduped_sleeve",
        "atr_percentile",
        PRIMARY_SLEEVE,
        PRIMARY_DIRECTION,
        "low_mid_minus_high",
    )
    base_uplift = _select_row(
        results,
        "curve",
        "all_bars_long",
        "atr_percentile",
        "all_bars_long",
        "long",
        "low_mid_minus_high",
    )
    uplift_excess = _select_row(
        results,
        "excess",
        "sleeve_minus_all_bars_long",
        "atr_percentile",
        PRIMARY_SLEEVE,
        PRIMARY_DIRECTION,
        "low_mid_minus_high",
    )
    sleeve_low_mid = _select_row(
        results,
        "curve",
        "deduped_sleeve",
        "atr_percentile",
        PRIMARY_SLEEVE,
        PRIMARY_DIRECTION,
        "low_mid_mean",
    )
    base_low_mid = _select_row(
        results,
        "curve",
        "all_bars_long",
        "atr_percentile",
        "all_bars_long",
        "long",
        "low_mid_mean",
    )
    low_mid_excess = _select_row(
        results,
        "excess",
        "sleeve_minus_all_bars_long",
        "atr_percentile",
        PRIMARY_SLEEVE,
        PRIMARY_DIRECTION,
        "low_mid_mean",
    )
    short_row = _select_row(
        results,
        "curve",
        "deduped_sleeve",
        "atr_percentile",
        PRIMARY_SLEEVE,
        "short",
        "low_mid_minus_high",
    )
    variants = _metric_variant_summary(results)
    limit_status = _select_row(
        results,
        "book_generalization",
        "full_deployed_v2_book",
        "atr_percentile",
        "full_deployed_v2_book",
        "both",
        "limit_cells_status",
    )
    lines = [
        "# ATR Regime P2",
        "",
        "## Headline",
        f"Verdict: **{call}**.",
    ]
    if advance:
        lines.append(
            "Plain call: advance to P3 for book-level sizing/throughput/DD simulation."
        )
    else:
        lines.append(
            "Plain call: do not advance this to P3 as a robust conditioner yet; the "
            "percentile alpha clears the baseline, but robustness fails outside the "
            "percentile formulation."
        )
    lines.extend([
        "",
        "## Alpha vs Beta Baseline",
        (
            f"All-bars baseline count sanity: baseline n={_fmt_n(base_uplift.n)} versus "
            f"{PRIMARY_SLEEVE} {PRIMARY_DIRECTION} sleeve n={_fmt_n(sleeve_uplift.n)}."
        ),
        (
            f"Regime-gradient uplift: sleeve={_fmt(sleeve_uplift.mean_R)} "
            f"(NW_CI_low={_fmt(sleeve_uplift.NW_CI_low)}, "
            f"date-cluster_CI_low={_fmt(sleeve_uplift.cluster_CI_low)}) versus "
            f"all-bars={_fmt(base_uplift.mean_R)} "
            f"(NW_CI_low={_fmt(base_uplift.NW_CI_low)})."
        ),
        (
            f"Excess uplift (sleeve - baseline)={_fmt(uplift_excess.excess_mean_R)} "
            f"(NW_CI_low={_fmt(uplift_excess.excess_NW_CI_low)}, "
            f"date-cluster_CI_low={_fmt(uplift_excess.excess_cluster_CI_low)})."
        ),
        (
            f"Low/mid absolute R: sleeve={_fmt(sleeve_low_mid.mean_R)} "
            f"(NW_CI_low={_fmt(sleeve_low_mid.NW_CI_low)}) versus "
            f"all-bars={_fmt(base_low_mid.mean_R)} "
            f"(NW_CI_low={_fmt(base_low_mid.NW_CI_low)})."
        ),
        (
            f"Excess low/mid R (sleeve - baseline)={_fmt(low_mid_excess.excess_mean_R)} "
            f"(NW_CI_low={_fmt(low_mid_excess.excess_NW_CI_low)}, "
            f"date-cluster_CI_low={_fmt(low_mid_excess.excess_cluster_CI_low)})."
        ),
        "",
        "## Date-Clustered SE",
        (
            "Cluster unit is entry timestamp across pairs. The sleeve's own "
            f"low/mid-high CI_low moves from NW {_fmt(sleeve_uplift.NW_CI_low)} to "
            f"date-cluster {_fmt(sleeve_uplift.cluster_CI_low)}."
        ),
        "",
        "## Long/Short Confirmation",
        (
            f"{PRIMARY_SLEEVE} short uplift={_fmt(short_row.mean_R)} "
            f"(NW_CI_low={_fmt(short_row.NW_CI_low)}, "
            f"date-cluster_CI_low={_fmt(short_row.cluster_CI_low)})."
        ),
        "",
        "## ATR Metric Formulations",
    ])
    lines.extend(_markdown_table(
        variants,
        ["formulation", "uplift", "nw_ci_low", "cluster_ci_low", "n", "passes_nw", "passes_cluster"],
    ))
    lines.extend([
        "",
        "## Dedup Sanity",
    ])
    lines.extend(_markdown_table(
        dedup_rows,
        ["sleeve", "direction", "sum_cell_trades", "deduped_trades", "dedup_drop"],
    ))
    lines.extend([
        "",
        "## Light Generalization",
        (
            "Dislocation-family full-6 descriptive rows are included in the CSV. "
            f"Limit-cell status: {limit_status.note}."
        ),
        "",
        "## Artifacts",
        f"- `{BASELINE_PATH.name}`: sleeve, all-bars baseline, excess, robustness rows.",
        f"- `{OUT_PATH.name}`: run summary.",
        "",
    ])
    return "\n".join(lines)


def _count_bucket_sanity(frame: pd.DataFrame) -> dict[str, int]:
    out: dict[str, int] = {}
    for bucket in REGIME_ORDER:
        out[bucket] = int((frame["atr_bucket"] == bucket).sum())
    return out


def run() -> tuple[pd.DataFrame, str]:
    fires, pairs, _modes = _load_fires_and_pairs()
    start_ts = pd.Timestamp(fires["ts"].min())
    end_ts = pd.Timestamp(fires["ts"].max())
    with FxStore(read_only=True) as store:
        metric_frames, cuts = _metric_cut_map(store, pairs, start_ts, end_ts)
        baseline = _simulate_all_bars_baseline(metric_frames)

    trades, drops, _source_check = _simulate_trades(fires, pairs)
    if not bool(drops["matches_p1"].all()):
        raise RuntimeError("realized trade counts do not match P1")
    trades = trades.copy()
    trades["realized_hold"] = trades["exit_idx"] - trades["bar_idx"]
    trades = _attach_halves(trades)
    trades = _attach_sleeve_metric_values(trades, metric_frames)
    trades = _attach_metric_buckets(trades, cuts)
    baseline = _attach_metric_buckets(baseline, cuts)
    sleeve_trades, dedup_rows = _build_sleeves(trades)
    results = _build_results(trades, baseline, sleeve_trades, pairs)
    results.to_csv(BASELINE_PATH, index=False)
    report = _report(results, dedup_rows)
    REPORT_PATH.write_text(report, encoding="utf-8")

    primary = _select_row(
        results,
        "excess",
        "sleeve_minus_all_bars_long",
        "atr_percentile",
        PRIMARY_SLEEVE,
        PRIMARY_DIRECTION,
        "low_mid_minus_high",
    )
    low_mid = _select_row(
        results,
        "excess",
        "sleeve_minus_all_bars_long",
        "atr_percentile",
        PRIMARY_SLEEVE,
        PRIMARY_DIRECTION,
        "low_mid_mean",
    )
    baseline_counts = _count_bucket_sanity(baseline)
    corrected_lag = _clean_lag(float(trades["realized_hold"].median()))
    call, advance = _alpha_call(results)
    out_lines = [
        "ATR-regime P2 run complete",
        f"pairs={len(pairs)} period={start_ts}..{end_ts}",
        f"TP={TP_PCT:.4f} STOP={STOP_PCT:.4f} MAX_HOLD={MAX_HOLD}",
        f"NW_L={LAG} p1b_corrected_L_from_this_run={corrected_lag}",
        f"all_bars_baseline_trades={len(baseline):,}",
        "baseline_bucket_counts="
        + ",".join(f"{key}:{value}" for key, value in baseline_counts.items()),
        f"{PRIMARY_SLEEVE}_{PRIMARY_DIRECTION}_sleeve_trades="
        f"{int(dedup_rows[(dedup_rows['sleeve'] == PRIMARY_SLEEVE) & (dedup_rows['direction'] == PRIMARY_DIRECTION)]['deduped_trades'].iloc[0]):,}",
        f"excess_uplift={primary.excess_mean_R:+.6f}",
        f"excess_uplift_nw_ci_low={primary.excess_NW_CI_low:+.6f}",
        f"excess_uplift_cluster_ci_low={primary.excess_cluster_CI_low:+.6f}",
        f"excess_low_mid_R={low_mid.excess_mean_R:+.6f}",
        f"excess_low_mid_R_nw_ci_low={low_mid.excess_NW_CI_low:+.6f}",
        f"excess_low_mid_R_cluster_ci_low={low_mid.excess_cluster_CI_low:+.6f}",
        f"verdict={call}",
        f"advance_to_p3={advance}",
    ]
    OUT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return results, report


def main() -> None:
    run()


if __name__ == "__main__":
    main()
