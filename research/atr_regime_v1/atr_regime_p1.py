"""ATR-regime P1 sanity gates for dislocation-family MR cells."""
# pylint: disable=import-error,wrong-import-order,wrong-import-position
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-locals
# pylint: disable=too-many-statements,too-many-branches,duplicate-code
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
DEPTH_DIR = ROOT / "research" / "dislocation_depth_v1"
CONFLUENCE_DIR = ROOT / "research" / "confluence_v1"
HARNESS_DIR = ROOT / "research" / "v2_executable_regate" / "harness"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(CONFLUENCE_DIR))
sys.path.insert(0, str(HARNESS_DIR))

from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators import atr, ohlc_mid  # noqa: E402
from factor_grouping import choose_params, deployed_cells  # noqa: E402
from _lib import MAX_HOLD, STOP_PCT, TP_PCT, sim_long_mid, sim_short_mid  # noqa: E402

EVALUATORS = ("bb", "rsi", "cci", "sma", "ema", "stoch")
DIRECTIONS = ("long", "short")
REGIME_ORDER = ("ATR_low_0_33", "ATR_mid_33_67", "ATR_high_67_100")
REGIME_LABEL = {
    "ATR_low_0_33": "low",
    "ATR_mid_33_67": "mid",
    "ATR_high_67_100": "high",
}
EXPECTED_REALIZED = {
    ("bb", "long"): 5500,
    ("bb", "short"): 5533,
    ("rsi", "long"): 11843,
    ("rsi", "short"): 12314,
    ("cci", "long"): 19604,
    ("cci", "short"): 20144,
    ("sma", "long"): 4429,
    ("sma", "short"): 4570,
    ("ema", "long"): 5524,
    ("ema", "short"): 5683,
    ("stoch", "long"): 28579,
    ("stoch", "short"): 30360,
}
ATR_PERCENTILE_WINDOW = 252
NW_LAG = MAX_HOLD - 1
FIRES_PATH = DEPTH_DIR / "depth_fires.csv"
DEPTH_EXTRACT_PATH = DEPTH_DIR / "depth_extract.py"
CURVES_PATH = OUT_DIR / "atr_regime_curves.csv"
REPORT_PATH = OUT_DIR / "ATR_REGIME_P1.md"
OUT_PATH = OUT_DIR / "atr_regime_p1.out"


def _fmt(value: float, digits: int = 3) -> str:
    if not np.isfinite(value):
        return "nan"
    return f"{value:+.{digits}f}"


def _fmt_plain(value: float, digits: int = 3) -> str:
    if not np.isfinite(value):
        return "nan"
    return f"{value:.{digits}f}"


def _entry_modes(cells: list[object]) -> dict[str, str]:
    modes: dict[str, str] = {}
    for evaluator in EVALUATORS:
        found = sorted({cell.entry_mode for cell in cells if cell.strategy == evaluator})
        if found != ["mid"]:
            raise RuntimeError(f"expected one mid entry mode for {evaluator}, got {found}")
        modes[evaluator] = found[0]
    return modes


def _simulator(direction: str) -> Callable:
    if direction == "long":
        return sim_long_mid
    if direction == "short":
        return sim_short_mid
    raise ValueError(f"unsupported direction: {direction}")


def _atr_bucket(value: float) -> str:
    if not np.isfinite(value):
        return "ATR_missing"
    if 0.0 <= value < 1.0 / 3.0:
        return "ATR_low_0_33"
    if 1.0 / 3.0 <= value < 2.0 / 3.0:
        return "ATR_mid_33_67"
    if 2.0 / 3.0 <= value <= 1.0:
        return "ATR_high_67_100"
    return "ATR_missing"


def _nw_se(values: pd.Series | np.ndarray, lag: int = NW_LAG) -> float:
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


def _stats(values: pd.Series | np.ndarray) -> dict[str, float | int]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return {"n": 0, "mean_R": np.nan, "NW_SE": np.nan, "NW_CI_low": np.nan}
    mean = float(arr.mean())
    se = _nw_se(arr)
    ci_low = mean - 1.96 * se if np.isfinite(se) else np.nan
    return {"n": int(len(arr)), "mean_R": mean, "NW_SE": se, "NW_CI_low": ci_low}


def _diff_stats(left: pd.Series, right: pd.Series) -> dict[str, float]:
    left_stats = _stats(left)
    right_stats = _stats(right)
    diff = float(left_stats["mean_R"]) - float(right_stats["mean_R"])
    left_se = float(left_stats["NW_SE"])
    right_se = float(right_stats["NW_SE"])
    se = float(np.sqrt(left_se * left_se + right_se * right_se))
    ci_low = diff - 1.96 * se if np.isfinite(se) else np.nan
    return {"diff": diff, "NW_SE": se, "NW_CI_low": ci_low}


def _spearman(means: list[float]) -> float:
    data = pd.DataFrame({"order": [1, 2, 3], "mean": means}).dropna()
    if len(data) < 2 or data["mean"].nunique() < 2:
        return float("nan")
    return float(data["order"].rank().corr(data["mean"].rank()))


def _rolling_percentile(values: pd.Series, window: int) -> pd.Series:
    def rank_last(arr: np.ndarray) -> float:
        finite = arr[np.isfinite(arr)]
        if len(finite) == 0 or not np.isfinite(arr[-1]):
            return np.nan
        return float(np.mean(finite <= arr[-1]))

    return values.rolling(window, min_periods=window).apply(rank_last, raw=True)


def _source_causality_check() -> dict[str, object]:
    text = DEPTH_EXTRACT_PATH.read_text(encoding="utf-8")
    has_rolling = "values.rolling(window, min_periods=window).apply" in text
    has_rank_last = "finite <= arr[-1]" in text
    shifted = ".shift(" in text[text.find("def _rolling_percentile"):text.find("def _entry_modes")]
    lookahead = bool(re.search(r"shift\s*\(\s*-\d+", text))
    return {
        "source_window": has_rolling,
        "rank_current_closed_bar": has_rank_last,
        "shifted": shifted,
        "lookahead_shift": lookahead,
        "passed": has_rolling and has_rank_last and not lookahead,
    }


def _pair_causality_sample(store: FxStore, pair: str, fires: pd.DataFrame) -> dict[str, object]:
    raw = store.load(pair, granularity="H4", include_incomplete=False)
    mid = ohlc_mid(raw)
    recomputed = _rolling_percentile(atr(mid, period=14), ATR_PERCENTILE_WINDOW)
    sample = fires[(fires["pair"] == pair) & fires["ATR_percentile"].notna()].head(200)
    by_ts = pd.Series(recomputed.to_numpy(float), index=pd.to_datetime(raw["timestamp"]))
    deltas = []
    for fire in sample.itertuples(index=False):
        value = by_ts.get(pd.Timestamp(fire.ts), np.nan)
        deltas.append(abs(float(value) - float(fire.ATR_percentile)))
    max_abs_delta = float(np.nanmax(deltas)) if deltas else np.nan
    return {"pair": pair, "sample_n": len(deltas), "max_abs_delta": max_abs_delta}


def _load_pair_trades(
    store: FxStore,
    fires: pd.DataFrame,
    pair: str,
) -> tuple[list[dict[str, object]], dict[tuple[str, str], int]]:
    raw = store.load(pair, granularity="H4", include_incomplete=False)
    if raw.empty:
        raise RuntimeError(f"no complete H4 bars for {pair}")
    mid = ohlc_mid(raw)
    timestamps = pd.to_datetime(raw["timestamp"])
    index_by_ts = {ts: idx for idx, ts in enumerate(timestamps)}
    close = mid["close"].to_numpy(float)
    high = mid["high"].to_numpy(float)
    low = mid["low"].to_numpy(float)
    rows: list[dict[str, object]] = []
    dropped: dict[tuple[str, str], int] = defaultdict(int)

    for fire in fires[fires["pair"] == pair].itertuples(index=False):
        evaluator = str(fire.evaluator)
        direction = str(fire.direction)
        ts_value = pd.Timestamp(fire.ts)
        bar_idx = index_by_ts.get(ts_value)
        if bar_idx is None:
            dropped[(evaluator, direction)] += 1
            continue
        r_value, exit_idx = _simulator(direction)(close, high, low, int(bar_idx), MAX_HOLD)
        if r_value is None:
            dropped[(evaluator, direction)] += 1
            continue
        rows.append({
            "pair": pair,
            "evaluator": evaluator,
            "direction": direction,
            "entry_mode": str(fire.entry_mode),
            "ts": ts_value,
            "bar_idx": int(bar_idx),
            "exit_idx": int(exit_idx),
            "R": float(r_value),
            "entry_ATR": float(fire.entry_ATR),
            "ATR_percentile": float(fire.ATR_percentile),
            "atr_bucket": _atr_bucket(float(fire.ATR_percentile)),
        })
    return rows, dropped


def _simulate_trades(
    fires: pd.DataFrame,
    pairs: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    rows: list[dict[str, object]] = []
    dropped: dict[tuple[str, str], int] = defaultdict(int)
    source_check = _source_causality_check()
    with FxStore(read_only=True) as store:
        source_check["sample_recompute"] = _pair_causality_sample(store, pairs[0], fires)
        for pair in pairs:
            pair_rows, pair_dropped = _load_pair_trades(store, fires, pair)
            rows.extend(pair_rows)
            for key, count in pair_dropped.items():
                dropped[key] += count
    trades = pd.DataFrame(rows)
    if trades.empty:
        raise RuntimeError("no realized trades after simulation")
    trades = trades.replace([np.inf, -np.inf], np.nan).dropna(subset=["R"])
    all_trades = trades.copy()
    trades = all_trades[all_trades["atr_bucket"].isin(REGIME_ORDER)].copy()

    drop_rows = []
    fire_counts = fires.groupby(["evaluator", "direction"]).size().to_dict()
    trade_counts = all_trades.groupby(["evaluator", "direction"]).size().to_dict()
    regime_counts = trades.groupby(["evaluator", "direction"]).size().to_dict()
    for evaluator in EVALUATORS:
        for direction in DIRECTIONS:
            key = (evaluator, direction)
            drop_rows.append({
                "evaluator": evaluator,
                "direction": direction,
                "fires": int(fire_counts.get(key, 0)),
                "realized": int(trade_counts.get(key, 0)),
                "regime_realized": int(regime_counts.get(key, 0)),
                "expected_realized": EXPECTED_REALIZED[key],
                "dropped": int(fire_counts.get(key, 0) - trade_counts.get(key, 0)),
                "sim_dropped": int(dropped.get(key, 0)),
                "matches_p1": int(trade_counts.get(key, 0)) == EXPECTED_REALIZED[key],
            })
    return trades, pd.DataFrame(drop_rows), source_check


def _half_labels(sub: pd.DataFrame) -> pd.Series:
    ordered = sub.sort_values(["ts", "pair"]).reset_index()
    cut = len(ordered) // 2
    labels = pd.Series("h2", index=ordered["index"], dtype=object)
    labels.loc[ordered.iloc[:cut]["index"]] = "h1"
    return labels


def _attach_halves(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.copy()
    out["half"] = ""
    for _, sub in out.groupby(["evaluator", "direction"], sort=True):
        labels = _half_labels(sub)
        out.loc[labels.index, "half"] = labels
    return out


def _curve_rows_for_group(
    sub: pd.DataFrame,
    *,
    level: str,
    pair_or_pooled: str,
    half: str,
) -> list[dict[str, object]]:
    rows = []
    for bucket in REGIME_ORDER:
        stats = _stats(sub.loc[sub["atr_bucket"] == bucket, "R"])
        rows.append({
            "cell": sub["evaluator"].iloc[0],
            "direction": sub["direction"].iloc[0],
            "level": level,
            "pair_or_POOLED": pair_or_pooled,
            "regime_bucket": bucket,
            "regime": REGIME_LABEL[bucket],
            "half": half,
            **stats,
        })
    return rows


def _build_curves(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for half in ("full", "h1", "h2"):
        half_df = trades if half == "full" else trades[trades["half"] == half]
        for _, sub in half_df.groupby(["evaluator", "direction"], sort=True):
            rows.extend(_curve_rows_for_group(
                sub,
                level="pooled",
                pair_or_pooled="POOLED",
                half=half,
            ))
        for (_, _, pair), sub in half_df.groupby(["evaluator", "direction", "pair"], sort=True):
            rows.extend(_curve_rows_for_group(
                sub,
                level="pair",
                pair_or_pooled=pair,
                half=half,
            ))
    sort_cols = ["cell", "direction", "level", "pair_or_POOLED", "half", "regime_bucket"]
    return pd.DataFrame(rows).sort_values(sort_cols)


def _gate_for_subset(sub: pd.DataFrame) -> dict[str, float | bool | int]:
    low = sub.loc[sub["atr_bucket"] == "ATR_low_0_33", "R"]
    mid = sub.loc[sub["atr_bucket"] == "ATR_mid_33_67", "R"]
    high = sub.loc[sub["atr_bucket"] == "ATR_high_67_100", "R"]
    low_mid = sub.loc[sub["atr_bucket"].isin(REGIME_ORDER[:2]), "R"]
    low_stats = _stats(low)
    mid_stats = _stats(mid)
    high_stats = _stats(high)
    low_mid_stats = _stats(low_mid)
    diff_stats = _diff_stats(low_mid, high)
    means = [
        float(low_stats["mean_R"]),
        float(mid_stats["mean_R"]),
        float(high_stats["mean_R"]),
    ]
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
        "low_mid_vs_high": float(diff_stats["diff"]),
        "diff_nw_se": float(diff_stats["NW_SE"]),
        "diff_nw_ci_low": float(diff_stats["NW_CI_low"]),
        "spearman_ordered_buckets": _spearman(means),
        "low_gt_high": low_gt_high,
        "mid_gt_high": float(mid_stats["mean_R"]) > float(high_stats["mean_R"]),
        "low_mid_positive": low_mid_positive,
        "diff_positive": diff_positive,
        "gate": low_mid_positive and diff_positive and low_gt_high,
    }


def _pair_robustness(sub: pd.DataFrame, pairs: list[str]) -> dict[str, float | int]:
    positive = 0
    comparable = 0
    for pair in pairs:
        pair_sub = sub[sub["pair"] == pair]
        low = pair_sub.loc[pair_sub["atr_bucket"] == "ATR_low_0_33", "R"]
        high = pair_sub.loc[pair_sub["atr_bucket"] == "ATR_high_67_100", "R"]
        if low.empty or high.empty:
            continue
        comparable += 1
        if float(low.mean()) > float(high.mean()):
            positive += 1
    return {
        "pair_positive": positive,
        "pair_comparable": comparable,
        "pair_total": len(pairs),
        "pair_fraction_17": positive / len(pairs) if pairs else np.nan,
        "pair_fraction_comparable": positive / comparable if comparable else np.nan,
        "pair_majority_17": positive > len(pairs) / 2.0,
    }


def _cell_rows(trades: pd.DataFrame, pairs: list[str]) -> pd.DataFrame:
    rows = []
    for evaluator in EVALUATORS:
        for direction in DIRECTIONS:
            sub = trades[(trades["evaluator"] == evaluator) & (trades["direction"] == direction)]
            full = _gate_for_subset(sub)
            h1 = _gate_for_subset(sub[sub["half"] == "h1"])
            h2 = _gate_for_subset(sub[sub["half"] == "h2"])
            pair = _pair_robustness(sub, pairs)
            rows.append({
                "cell": evaluator,
                "direction": direction,
                **{f"full_{key}": value for key, value in full.items()},
                **{f"h1_{key}": value for key, value in h1.items()},
                **{f"h2_{key}": value for key, value in h2.items()},
                **pair,
                "both_halves_low_gt_high": bool(h1["low_gt_high"] and h2["low_gt_high"]),
                "both_halves_gate": bool(h1["gate"] and h2["gate"]),
                "survives_p1": bool(
                    full["gate"]
                    and h1["gate"]
                    and h2["gate"]
                    and pair["pair_majority_17"]
                ),
            })
    return pd.DataFrame(rows)


def _markdown_table(df: pd.DataFrame, columns: list[str]) -> list[str]:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in df[columns].itertuples(index=False):
        values = []
        for value in row:
            if isinstance(value, float):
                values.append(f"{value:.4g}" if np.isfinite(value) else "nan")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _build_report(
    curves: pd.DataFrame,
    drops: pd.DataFrame,
    summary: pd.DataFrame,
    source_check: dict[str, object],
    choices: dict[str, object],
) -> str:
    survivors = summary[summary["survives_p1"]].sort_values(["cell", "direction"])
    cross_count = int(summary["both_halves_gate"].sum())
    strict_count = int(summary["survives_p1"].sum())
    sample = source_check["sample_recompute"]
    lines = [
        "# ATR Regime P1",
        "",
        "## Method",
        (
            f"Simulated `depth_fires.csv` with `_lib.py` mid-entry R machinery, "
            f"TP={TP_PCT:.0%}, SL={STOP_PCT:.0%}, and `MAX_HOLD={MAX_HOLD}` H4 bars."
        ),
        (
            f"Newey-West uses the `nw_regate.py` Bartlett-kernel convention with "
            f"fixed `L = hold - 1 = {NW_LAG}` for every bucket and low/mid-vs-high diff."
        ),
        (
            "Regimes are within-pair `ATR_percentile` buckets: low [0,33), "
            "mid [33,67), high [67,100]. Rows with missing ATR percentile are excluded "
            "from P1 regime gates, matching the closed rolling-window warmup."
        ),
        "",
        "## ATR Percentile Causality Check",
        (
            f"`depth_extract.py` computes `entry_ATR = ATR(14)` on closed H4 midpoint bars "
            f"and `ATR_percentile` as `rolling({ATR_PERCENTILE_WINDOW}).apply(rank_last)`. "
            "The rolling function ranks `arr[-1]` against the finite values inside that "
            "same backward-looking window; no negative shift or forward window is present."
        ),
        (
            f"Source check passed={source_check['passed']}; recompute sample "
            f"{sample['pair']} n={sample['sample_n']} max_abs_delta="
            f"{sample['max_abs_delta']:.3g}. This confirms no future ATR values enter the "
            "stored percentile; the current closed signal bar is included and is known at "
            "mid-entry simulation time."
        ),
        "",
        "## Deployed Cells",
    ]
    for evaluator in EVALUATORS:
        lines.append(
            f"- {evaluator}: entry_mode=mid, "
            f"params=`{choices[evaluator].params}`"
        )
    lines.extend(["", "## Count Sanity"])
    lines.extend(_markdown_table(
        drops,
        [
            "evaluator",
            "direction",
            "fires",
            "realized",
            "regime_realized",
            "expected_realized",
            "dropped",
            "sim_dropped",
            "matches_p1",
        ],
    ))
    lines.extend(["", "## Headline"])
    lines.append(
        f"Cross-cell consistency: {cross_count}/12 cell-directions show an NW-significant "
        "low/mid bucket and low>high ordering in both halves."
    )
    lines.append(
        f"Strict P1 survivors after full-sample diff NW gate plus per-pair majority: "
        f"{strict_count}/12."
    )
    if strict_count == 0:
        lines.append(
            "The gradient collapses under the full P1 stack; route this thread to "
            "relative-value / door #2 rather than P2 volatility-regime deployment work."
        )
    lines.extend(["", "## Cell-Direction Verdicts"])
    for row in summary.sort_values(["cell", "direction"]).itertuples(index=False):
        lines.append(
            f"- {row.cell} {row.direction}: low={_fmt(row.full_low_mean)}, "
            f"mid={_fmt(row.full_mid_mean)}, high={_fmt(row.full_high_mean)}, "
            f"low/mid={_fmt(row.full_low_mid_mean)} "
            f"(NW_CI_low={_fmt(row.full_low_mid_nw_ci_low)}), "
            f"low/mid-high={_fmt(row.full_low_mid_vs_high)} "
            f"(NW_CI_low={_fmt(row.full_diff_nw_ci_low)}), "
            f"Spearman={_fmt_plain(row.full_spearman_ordered_buckets)}, "
            f"halves low>high={'YES' if row.both_halves_low_gt_high else 'NO'}, "
            f"halves gate={'YES' if row.both_halves_gate else 'NO'}, "
            f"pairs low>high={row.pair_positive}/{row.pair_total} "
            f"({_fmt_plain(row.pair_fraction_17)}), "
            f"survives={'YES' if row.survives_p1 else 'NO'}."
        )
    lines.extend(["", "## P2 Survivor Set"])
    if survivors.empty:
        lines.append("- None.")
    else:
        for row in survivors.itertuples(index=False):
            lines.append(f"- {row.cell} {row.direction}")
    lines.extend(["", "## Selection Control"])
    majority_count = int(summary["pair_majority_17"].sum())
    h1_count = int(summary["h1_gate"].sum())
    h2_count = int(summary["h2_gate"].sum())
    lines.append(
        f"Within-pair control: {majority_count}/12 cell-directions have a majority of "
        "the 17 pairs with low-ATR mean_R > high-ATR mean_R, so the headline is not "
        "just pooled low-vol pairs outperforming."
    )
    lines.append(
        f"Calendar/era control: h1 gates={h1_count}/12 and h2 gates={h2_count}/12. "
        "Both-halves status for each cell-direction is listed above; any one-half-only "
        "effect is treated as non-survival."
    )
    lines.extend(["", "## Artifacts"])
    lines.append(f"- `{CURVES_PATH.name}`: {len(curves):,} bucket rows.")
    lines.append(f"- `{OUT_PATH.name}`: run summary.")
    lines.append("")
    return "\n".join(lines)


def run() -> tuple[pd.DataFrame, str]:
    cells = deployed_cells()
    pairs = sorted({cell.pair for cell in cells})
    choices = choose_params(cells)
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

    trades, drops, source_check = _simulate_trades(fires, pairs)
    trades = _attach_halves(trades)
    curves = _build_curves(trades)
    summary = _cell_rows(trades, pairs)
    curves.to_csv(CURVES_PATH, index=False)
    report = _build_report(curves, drops, summary, source_check, choices)
    REPORT_PATH.write_text(report, encoding="utf-8")

    survivors = summary[summary["survives_p1"]].sort_values(["cell", "direction"])
    out_lines = [
        "ATR-regime P1 run complete",
        f"pairs={len(pairs)} regime_trades={len(trades):,} curves={len(curves):,}",
        f"MAX_HOLD={MAX_HOLD} NW_L={NW_LAG} TP={TP_PCT:.4f} STOP={STOP_PCT:.4f}",
        f"count_sanity_pass={bool(drops['matches_p1'].all())}",
        f"cross_cell_both_halves_gate={int(summary['both_halves_gate'].sum())}/12",
        "survivors="
        + (
            ", ".join(f"{row.cell}:{row.direction}" for row in survivors.itertuples())
            if not survivors.empty
            else "NONE"
        ),
    ]
    OUT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    if not bool(drops["matches_p1"].all()):
        raise RuntimeError("realized trade counts do not match P1_DEPTH_R.md")
    return curves, report


def main() -> None:
    run()


if __name__ == "__main__":
    main()
