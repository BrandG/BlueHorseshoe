"""ATR-regime P2b time-local metric robustness probe."""
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
    DIRECTIONS,
    EVALUATORS,
    FIRES_PATH,
    REGIME_ORDER,
    _attach_halves,
    _atr_bucket,
    _entry_modes,
    _load_pair_trades,
    _markdown_table,
    _rolling_percentile,
)
from atr_regime_p1b import SLEEVES, _diff_stats_lag, _stats_lag  # noqa: E402

LAG = 22
PRIMARY_SLEEVE = "long_mr_strong4"
PRIMARY_DIRECTION = "long"
RATIO_SMA_WINDOW = 50
RATIO_BUCKET_WINDOW = 252
METRICS_PATH = OUT_DIR / "atr_regime_p2b_metrics.csv"
REPORT_PATH = OUT_DIR / "ATR_REGIME_P2B.md"
OUT_PATH = OUT_DIR / "atr_regime_p2b.out"
METRICS = ("atr_pct_w252", "atr_ma_ratio", "atr_pct_w60", "atr_pct_w500")
ALT_METRICS = ("atr_ma_ratio", "atr_pct_w60", "atr_pct_w500")
PERCENTILE_WINDOWS = {
    "atr_pct_w252": 252,
    "atr_pct_w60": 60,
    "atr_pct_w500": 500,
}
METRIC_NOTES = {
    "atr_pct_w252": "ATR(14) rolling 252-bar percentile, recomputed from closed H4 midpoint bars.",
    "atr_ma_ratio": (
        "ATR(14) / SMA(ATR(14),50), bucketed by rolling 252-bar percentile of that ratio."
    ),
    "atr_pct_w60": "ATR(14) rolling 60-bar percentile, recomputed from closed H4 midpoint bars.",
    "atr_pct_w500": "ATR(14) rolling 500-bar percentile, recomputed from closed H4 midpoint bars.",
}


def _stats(values: pd.Series | np.ndarray) -> dict[str, float | int]:
    return _stats_lag(values, LAG)


def _diff_stats(left: pd.Series, right: pd.Series) -> dict[str, float | int]:
    return _diff_stats_lag(left, right, LAG)


def _ci_low(mean: float, se: float) -> float:
    return mean - 1.96 * se if np.isfinite(se) else np.nan


def _ci_high(mean: float, se: float) -> float:
    return mean + 1.96 * se if np.isfinite(se) else np.nan


def _bucket_col(metric: str) -> str:
    return f"{metric}_bucket"


def _metric_value_col(metric: str) -> str:
    if metric == "atr_ma_ratio":
        return "atr_ma_ratio"
    return metric


def _percentile_col(metric: str) -> str:
    if metric == "atr_ma_ratio":
        return "atr_ma_ratio_pct_w252"
    return metric


def _cluster_se_for_contrast(
    frame: pd.DataFrame,
    bucket_col: str,
    left_buckets: tuple[str, ...],
    right_buckets: tuple[str, ...],
) -> float:
    left_mask = frame[bucket_col].isin(left_buckets)
    right_mask = frame[bucket_col].isin(right_buckets)
    left = frame.loc[left_mask, "R"].to_numpy(float)
    right = frame.loc[right_mask, "R"].to_numpy(float)
    if len(left) < 2 or len(right) < 2:
        return float("nan")
    left_mean = float(np.mean(left))
    right_mean = float(np.mean(right))
    contrib = pd.Series(0.0, index=frame.index, dtype=float)
    contrib.loc[left_mask] = (frame.loc[left_mask, "R"] - left_mean) / len(left)
    contrib.loc[right_mask] = -(frame.loc[right_mask, "R"] - right_mean) / len(right)
    clustered = contrib.groupby(frame["ts"], sort=False).sum().to_numpy(float)
    n_clusters = len(clustered)
    if n_clusters < 2:
        return float("nan")
    scale = n_clusters / (n_clusters - 1.0)
    return float(np.sqrt(max(scale * float(clustered @ clustered), 0.0)))


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


def _cluster_se_for_excess(
    sleeve: pd.DataFrame,
    baseline: pd.DataFrame,
    bucket_col: str,
) -> float:
    sleeve_contrib = _influence_by_ts(
        sleeve,
        bucket_col,
        REGIME_ORDER[:2],
        REGIME_ORDER[2:],
        sign=1.0,
    )
    base_contrib = _influence_by_ts(
        baseline,
        bucket_col,
        REGIME_ORDER[:2],
        REGIME_ORDER[2:],
        sign=-1.0,
    )
    combined = sleeve_contrib.add(base_contrib, fill_value=0.0).to_numpy(float)
    n_clusters = len(combined)
    if n_clusters < 2:
        return float("nan")
    scale = n_clusters / (n_clusters - 1.0)
    return float(np.sqrt(max(scale * float(combined @ combined), 0.0)))


def _load_fires_and_pairs() -> tuple[pd.DataFrame, list[str]]:
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
    return fires, pairs


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
    })
    for metric, window in PERCENTILE_WINDOWS.items():
        frame[metric] = _rolling_percentile(atr_values, window).to_numpy(float)
    ratio_sma = atr_values.rolling(RATIO_SMA_WINDOW, min_periods=RATIO_SMA_WINDOW).mean()
    frame["atr_ma_ratio"] = (atr_values / ratio_sma).to_numpy(float)
    frame["atr_ma_ratio_pct_w252"] = _rolling_percentile(
        frame["atr_ma_ratio"],
        RATIO_BUCKET_WINDOW,
    ).to_numpy(float)
    for metric in METRICS:
        frame[_bucket_col(metric)] = frame[_percentile_col(metric)].map(_atr_bucket)
    metric_cols = [_percentile_col(metric) for metric in METRICS]
    frame["eligible_any_metric"] = (
        (frame["ts"] >= start_ts)
        & (frame["ts"] <= end_ts)
        & (frame["bar_idx"] + MAX_HOLD < len(frame))
        & frame[metric_cols].notna().any(axis=1)
    )
    return frame


def _metric_frames(
    store: FxStore,
    pairs: list[str],
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    return {
        pair: _pair_metric_frame(store, pair, start_ts, end_ts)
        for pair in pairs
    }


def _simulate_all_bars_baseline(metric_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    value_cols = ["entry_ATR", *(_metric_value_col(metric) for metric in METRICS)]
    bucket_cols = [_bucket_col(metric) for metric in METRICS]
    for pair, frame in metric_frames.items():
        close = frame["close"].to_numpy(float)
        high = frame["high"].to_numpy(float)
        low = frame["low"].to_numpy(float)
        for row in frame[frame["eligible_any_metric"]].itertuples(index=False):
            r_value, exit_idx = sim_long_mid(close, high, low, int(row.bar_idx), MAX_HOLD)
            if r_value is None:
                continue
            out: dict[str, object] = {
                "pair": pair,
                "ts": pd.Timestamp(row.ts),
                "bar_idx": int(row.bar_idx),
                "exit_idx": int(exit_idx),
                "direction": "long",
                "entry_mode": "mid",
                "R": float(r_value),
            }
            for col in value_cols:
                out[col] = float(getattr(row, col))
            for col in bucket_cols:
                out[col] = str(getattr(row, col))
            rows.append(out)
    baseline = pd.DataFrame(rows)
    if baseline.empty:
        raise RuntimeError("all-bars baseline produced no trades")
    return baseline


def _simulate_all_depth_trades(
    fires: pd.DataFrame,
    pairs: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    dropped: dict[tuple[str, str], int] = {}
    with FxStore(read_only=True) as store:
        for pair in pairs:
            pair_rows, pair_dropped = _load_pair_trades(store, fires, pair)
            rows.extend(pair_rows)
            for key, count in pair_dropped.items():
                dropped[key] = dropped.get(key, 0) + count
    trades = pd.DataFrame(rows)
    if trades.empty:
        raise RuntimeError("no realized trades after simulation")
    trades = trades.replace([np.inf, -np.inf], np.nan).dropna(subset=["R"])
    drop_rows = []
    fire_counts = fires.groupby(["evaluator", "direction"]).size().to_dict()
    trade_counts = trades.groupby(["evaluator", "direction"]).size().to_dict()
    for evaluator in EVALUATORS:
        for direction in DIRECTIONS:
            key = (evaluator, direction)
            drop_rows.append({
                "evaluator": evaluator,
                "direction": direction,
                "fires": int(fire_counts.get(key, 0)),
                "realized": int(trade_counts.get(key, 0)),
                "dropped": int(fire_counts.get(key, 0) - trade_counts.get(key, 0)),
                "sim_dropped": int(dropped.get(key, 0)),
            })
    return trades, pd.DataFrame(drop_rows)


def _attach_metric_values(
    trades: pd.DataFrame,
    metric_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    out = trades.copy()
    for col in ["entry_ATR", *(_metric_value_col(metric) for metric in METRICS)]:
        out[col] = np.nan
    for col in [_bucket_col(metric) for metric in METRICS]:
        out[col] = "ATR_missing"
    metric_cols = [
        "entry_ATR",
        *(_metric_value_col(metric) for metric in METRICS),
        *(_bucket_col(metric) for metric in METRICS),
    ]
    for pair, metric_frame in metric_frames.items():
        by_ts = metric_frame.set_index("ts")
        mask = out["pair"] == pair
        ts_values = out.loc[mask, "ts"]
        for col in metric_cols:
            out.loc[mask, col] = ts_values.map(by_ts[col])
    return out


def _build_sleeves(trades: pd.DataFrame) -> tuple[dict[tuple[str, str], pd.DataFrame], pd.DataFrame]:
    sleeve_trades: dict[tuple[str, str], pd.DataFrame] = {}
    dedup_rows = []
    for sleeve, sleeve_cells in SLEEVES.items():
        for direction in DIRECTIONS:
            deduped, pre_count, drop_count = _dedup_sleeve_for_metrics(
                trades,
                sleeve_cells,
                direction,
            )
            sleeve_trades[(sleeve, direction)] = deduped
            dedup_rows.append({
                "sleeve": sleeve,
                "direction": direction,
                "sum_cell_trades": pre_count,
                "deduped_trades": len(deduped),
                "dedup_drop": drop_count,
            })
    return sleeve_trades, pd.DataFrame(dedup_rows)


def _dedup_sleeve_for_metrics(
    trades: pd.DataFrame,
    cells: tuple[str, ...],
    direction: str,
) -> tuple[pd.DataFrame, int, int]:
    out = trades.copy()
    if "atr_bucket" not in out.columns:
        out["atr_bucket"] = out[_bucket_col("atr_pct_w252")]
    sub = out[
        out["evaluator"].isin(cells)
        & (out["direction"] == direction)
    ].copy()
    pre_count = len(sub)
    sort_cols = ["pair", "bar_idx", "direction", "evaluator", "ts"]
    dedup = sub.sort_values(sort_cols).drop_duplicates(["pair", "bar_idx", "direction"])
    dedup = dedup.sort_values(["ts", "pair"]).copy()
    dedup["half"] = ""
    labels = _half_labels(dedup)
    dedup.loc[labels.index, "half"] = labels
    return dedup, pre_count, pre_count - len(dedup)


def _half_labels(sub: pd.DataFrame) -> pd.Series:
    ordered = sub.sort_values(["ts", "pair"]).reset_index()
    cut = len(ordered) // 2
    labels = pd.Series("h2", index=ordered["index"], dtype=object)
    labels.loc[ordered.iloc[:cut]["index"]] = "h1"
    return labels


def _metric_frame(frame: pd.DataFrame, metric: str) -> pd.DataFrame:
    return frame[frame[_bucket_col(metric)].isin(REGIME_ORDER)].copy()


def _curve_row(
    *,
    sample: str,
    metric: str,
    sleeve: str,
    direction: str,
    row_metric: str,
    bucket: str,
    stats: dict[str, float | int],
    cluster_se: float = np.nan,
) -> dict[str, object]:
    mean_value = float(stats["mean_R"])
    return {
        "row_type": "curve",
        "sample": sample,
        "metric": metric,
        "sleeve": sleeve,
        "direction": direction,
        "bucket_or_diff": bucket,
        "stat": row_metric,
        "n": int(stats["n"]),
        "mean_R": mean_value,
        "NW_SE": float(stats["NW_SE"]),
        "NW_CI_low": float(stats["NW_CI_low"]),
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
        "pair_positive": np.nan,
        "pair_comparable": np.nan,
        "pair_total": np.nan,
        "note": "",
    }


def _curve_rows(
    frame: pd.DataFrame,
    *,
    sample: str,
    metric: str,
    sleeve: str,
    direction: str,
) -> list[dict[str, object]]:
    sub = _metric_frame(frame, metric)
    bucket_col = _bucket_col(metric)
    rows = []
    for bucket in REGIME_ORDER:
        stats = _stats(sub.loc[sub[bucket_col] == bucket, "R"])
        rows.append(_curve_row(
            sample=sample,
            metric=metric,
            sleeve=sleeve,
            direction=direction,
            row_metric="bucket_mean",
            bucket=bucket,
            stats=stats,
        ))
    low_mid = sub.loc[sub[bucket_col].isin(REGIME_ORDER[:2]), "R"]
    high = sub.loc[sub[bucket_col] == REGIME_ORDER[2], "R"]
    rows.append(_curve_row(
        sample=sample,
        metric=metric,
        sleeve=sleeve,
        direction=direction,
        row_metric="low_mid_mean",
        bucket="low_mid",
        stats=_stats(low_mid),
    ))
    diff_stats = _diff_stats(low_mid, high)
    rows.append(_curve_row(
        sample=sample,
        metric=metric,
        sleeve=sleeve,
        direction=direction,
        row_metric="low_mid_minus_high",
        bucket="low_mid_minus_high",
        stats=diff_stats,
        cluster_se=_cluster_se_for_contrast(sub, bucket_col, REGIME_ORDER[:2], REGIME_ORDER[2:]),
    ))
    return rows


def _metric_value(frame: pd.DataFrame, metric: str) -> tuple[float, float, int]:
    sub = _metric_frame(frame, metric)
    bucket_col = _bucket_col(metric)
    low_mid = sub.loc[sub[bucket_col].isin(REGIME_ORDER[:2]), "R"]
    high = sub.loc[sub[bucket_col] == REGIME_ORDER[2], "R"]
    stats = _diff_stats(low_mid, high)
    return float(stats["mean_R"]), float(stats["NW_SE"]), int(stats["n"])


def _excess_row(
    sleeve_frame: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    metric: str,
) -> dict[str, object]:
    sleeve_mean, sleeve_se, sleeve_n = _metric_value(sleeve_frame, metric)
    base_mean, base_se, base_n = _metric_value(baseline, metric)
    excess = sleeve_mean - base_mean
    nw_se = float(np.sqrt(sleeve_se * sleeve_se + base_se * base_se))
    cluster_se = _cluster_se_for_excess(
        _metric_frame(sleeve_frame, metric),
        _metric_frame(baseline, metric),
        _bucket_col(metric),
    )
    return {
        "row_type": "excess",
        "sample": "sleeve_minus_all_bars_long",
        "metric": metric,
        "sleeve": PRIMARY_SLEEVE,
        "direction": PRIMARY_DIRECTION,
        "bucket_or_diff": "low_mid_minus_high",
        "stat": "low_mid_minus_high",
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
        "pair_positive": np.nan,
        "pair_comparable": np.nan,
        "pair_total": np.nan,
        "note": "positive excess means sleeve uplift is above all-bars long baseline uplift",
    }


def _pair_majority(frame: pd.DataFrame, metric: str, pairs: list[str]) -> dict[str, int]:
    sub = _metric_frame(frame, metric)
    bucket_col = _bucket_col(metric)
    positive = 0
    comparable = 0
    for pair in pairs:
        pair_sub = sub[sub["pair"] == pair]
        low_mid = pair_sub.loc[pair_sub[bucket_col].isin(REGIME_ORDER[:2]), "R"]
        high = pair_sub.loc[pair_sub[bucket_col] == REGIME_ORDER[2], "R"]
        if low_mid.empty or high.empty:
            continue
        comparable += 1
        positive += int(float(low_mid.mean()) > float(high.mean()))
    return {"pair_positive": positive, "pair_comparable": comparable, "pair_total": len(pairs)}


def _pair_row(frame: pd.DataFrame, metric: str, pairs: list[str]) -> dict[str, object]:
    pair = _pair_majority(frame, metric, pairs)
    return {
        "row_type": "pair_majority",
        "sample": "deduped_sleeve",
        "metric": metric,
        "sleeve": PRIMARY_SLEEVE,
        "direction": PRIMARY_DIRECTION,
        "bucket_or_diff": "pair_low_mid_gt_high",
        "stat": "pair_low_mid_gt_high",
        "n": len(_metric_frame(frame, metric)),
        "mean_R": np.nan,
        "NW_SE": np.nan,
        "NW_CI_low": np.nan,
        "cluster_SE": np.nan,
        "cluster_CI_low": np.nan,
        "cluster_CI_high": np.nan,
        "baseline_n": np.nan,
        "sleeve_n": len(_metric_frame(frame, metric)),
        "excess_mean_R": np.nan,
        "excess_NW_SE": np.nan,
        "excess_NW_CI_low": np.nan,
        "excess_cluster_SE": np.nan,
        "excess_cluster_CI_low": np.nan,
        **pair,
        "note": f"{pair['pair_positive']}/{pair['pair_comparable']} comparable pairs low/mid > high",
    }


def _build_results(
    baseline: pd.DataFrame,
    sleeve: pd.DataFrame,
    pairs: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric in METRICS:
        rows.extend(_curve_rows(
            baseline,
            sample="all_bars_long",
            metric=metric,
            sleeve="all_bars_long",
            direction="long",
        ))
        rows.extend(_curve_rows(
            sleeve,
            sample="deduped_sleeve",
            metric=metric,
            sleeve=PRIMARY_SLEEVE,
            direction=PRIMARY_DIRECTION,
        ))
        rows.append(_excess_row(sleeve, baseline, metric=metric))
        rows.append(_pair_row(sleeve, metric, pairs))
    return pd.DataFrame(rows)


def _select_row(
    results: pd.DataFrame,
    row_type: str,
    sample: str,
    metric: str,
    stat: str,
) -> pd.Series:
    sub = results[
        (results["row_type"] == row_type)
        & (results["sample"] == sample)
        & (results["metric"] == metric)
        & (results["stat"] == stat)
    ]
    if sub.empty:
        raise RuntimeError(f"missing result row: {row_type} {sample} {metric} {stat}")
    return sub.iloc[0]


def _side_by_side(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in METRICS:
        uplift = _select_row(results, "curve", "deduped_sleeve", metric, "low_mid_minus_high")
        excess = _select_row(
            results,
            "excess",
            "sleeve_minus_all_bars_long",
            metric,
            "low_mid_minus_high",
        )
        pair = _select_row(results, "pair_majority", "deduped_sleeve", metric, "pair_low_mid_gt_high")
        rows.append({
            "metric": metric,
            "uplift": uplift.mean_R,
            "NW_CI_low": uplift.NW_CI_low,
            "cluster_CI_low": uplift.cluster_CI_low,
            "excess_vs_baseline": excess.excess_mean_R,
            "excess_NW_CI_low": excess.excess_NW_CI_low,
            "excess_cluster_CI_low": excess.excess_cluster_CI_low,
            "pair": f"{int(pair.pair_positive)}/{int(pair.pair_comparable)}",
            "n": int(uplift.n),
            "corroborates": bool(uplift.NW_CI_low > 0.0 and excess.excess_mean_R > 0.0),
        })
    return pd.DataFrame(rows)


def _verdict(summary: pd.DataFrame) -> tuple[str, bool, int]:
    alt_hits = int(summary[summary["metric"].isin(ALT_METRICS)]["corroborates"].sum())
    if alt_hits >= 2:
        return (
            "corroborated: the edge is recent-relative calm, not a 252-rank artifact",
            True,
            alt_hits,
        )
    return (
        "artifact: only the 252-bar rank survives; route to relative-value / door #2",
        False,
        alt_hits,
    )


def _fmt_n(value: object) -> str:
    if pd.isna(value):
        return "nan"
    return f"{int(value):,}"


def _report(results: pd.DataFrame, dedup_rows: pd.DataFrame) -> str:
    summary = _side_by_side(results)
    call, advance, alt_hits = _verdict(summary)
    lines = [
        "# ATR Regime P2b",
        "",
        "## Headline",
        f"Verdict: **{call}**.",
    ]
    if advance:
        lines.append(
            "Plain call: alternative time-local metrics corroborate the low>high sleeve "
            "gradient and positive alpha-vs-beta excess; advance to P3 for book-level "
            "sizing/throughput/DD."
        )
    else:
        lines.append(
            "Plain call: the alternative time-local metrics do not corroborate the "
            "252-bar percentile; treat it as construction-specific and route to "
            "relative-value / door #2."
        )
    lines.extend([
        "",
        "## Metric Robustness",
        (
            f"Corroboration rule: at least 2 of 3 alternative time-local metrics must have "
            f"NW-positive sleeve low/mid-high uplift and positive sleeve-vs-baseline excess. "
            f"Observed alt hits: {alt_hits}/3."
        ),
    ])
    lines.extend(_markdown_table(
        summary,
        [
            "metric",
            "uplift",
            "NW_CI_low",
            "cluster_CI_low",
            "excess_vs_baseline",
            "excess_NW_CI_low",
            "excess_cluster_CI_low",
            "pair",
            "n",
            "corroborates",
        ],
    ))
    lines.extend([
        "",
        "## PIT Check",
        "All metrics are recomputed from `FxStore(read_only=True)` complete H4 midpoint bars.",
        (
            "`ATR(14)` uses closed bars at the entry timestamp. Each percentile is "
            "`rolling(window, min_periods=window).apply(rank_last)`, where `rank_last` "
            "ranks `arr[-1]` inside the backward-looking window. There is no negative "
            "shift or forward window."
        ),
        (
            f"`atr_ma_ratio` uses `ATR(14) / SMA(ATR(14), {RATIO_SMA_WINDOW})` and is "
            f"bucketed by a rolling {RATIO_BUCKET_WINDOW}-bar percentile of that ratio. "
            "This keeps the ratio metric time-local while avoiding fixed cross-period "
            "level thresholds."
        ),
        "",
        "## Metric Definitions",
    ])
    for metric in METRICS:
        lines.append(f"- `{metric}`: {METRIC_NOTES[metric]}")
    primary_dedup = dedup_rows[
        (dedup_rows["sleeve"] == PRIMARY_SLEEVE)
        & (dedup_rows["direction"] == PRIMARY_DIRECTION)
    ].iloc[0]
    lines.extend([
        "",
        "## Dedup Sanity",
        (
            f"{PRIMARY_SLEEVE} {PRIMARY_DIRECTION}: sum_cell_trades="
            f"{_fmt_n(primary_dedup.sum_cell_trades)}, deduped_trades="
            f"{_fmt_n(primary_dedup.deduped_trades)}, dedup_drop="
            f"{_fmt_n(primary_dedup.dedup_drop)}."
        ),
        "",
        "## Artifacts",
        f"- `{METRICS_PATH.name}`: per-metric bucket, uplift, excess, and per-pair rows.",
        f"- `{OUT_PATH.name}`: run summary.",
        "",
    ])
    return "\n".join(lines)


def run() -> tuple[pd.DataFrame, str]:
    fires, pairs = _load_fires_and_pairs()
    start_ts = pd.Timestamp(fires["ts"].min())
    end_ts = pd.Timestamp(fires["ts"].max())
    with FxStore(read_only=True) as store:
        frames = _metric_frames(store, pairs, start_ts, end_ts)
        baseline = _simulate_all_bars_baseline(frames)

    trades, _drops = _simulate_all_depth_trades(fires, pairs)
    trades = trades.copy()
    trades["realized_hold"] = trades["exit_idx"] - trades["bar_idx"]
    trades = _attach_halves(trades)
    trades = _attach_metric_values(trades, frames)
    sleeve_trades, dedup_rows = _build_sleeves(trades)
    sleeve = sleeve_trades[(PRIMARY_SLEEVE, PRIMARY_DIRECTION)]
    results = _build_results(baseline, sleeve, pairs)
    results.to_csv(METRICS_PATH, index=False)
    report = _report(results, dedup_rows)
    REPORT_PATH.write_text(report, encoding="utf-8")

    summary = _side_by_side(results)
    call, advance, alt_hits = _verdict(summary)
    out_lines = [
        "ATR-regime P2b run complete",
        f"pairs={len(pairs)} period={start_ts}..{end_ts}",
        f"TP={TP_PCT:.4f} STOP={STOP_PCT:.4f} MAX_HOLD={MAX_HOLD}",
        f"NW_L={LAG}",
        f"all_bars_baseline_rows_any_metric={len(baseline):,}",
        f"{PRIMARY_SLEEVE}_{PRIMARY_DIRECTION}_deduped_rows={len(sleeve):,}",
        f"alt_metric_hits={alt_hits}/3",
        f"verdict={call}",
        f"advance_to_p3={advance}",
        "pit_check=all metrics use closed H4 bars at entry and backward-looking rolling windows",
    ]
    for row in summary.itertuples(index=False):
        out_lines.append(
            f"{row.metric}: uplift={row.uplift:+.6f} nw_ci_low={row.NW_CI_low:+.6f} "
            f"cluster_ci_low={row.cluster_CI_low:+.6f} "
            f"excess={row.excess_vs_baseline:+.6f} corroborates={row.corroborates}"
        )
    OUT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return results, report


def main() -> None:
    run()


if __name__ == "__main__":
    main()
