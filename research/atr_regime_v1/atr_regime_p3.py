"""ATR-regime P3 book-level deployable-value simulation."""
# pylint: disable=import-error,wrong-import-order,wrong-import-position
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-locals
# pylint: disable=too-many-statements,too-many-branches,duplicate-code
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

from _lib import MAX_HOLD, STOP_PCT, TP_PCT  # noqa: E402
from atr_regime_p1 import REGIME_LABEL, _fmt, _markdown_table  # noqa: E402
from atr_regime_p2b import (  # noqa: E402
    PRIMARY_DIRECTION,
    PRIMARY_SLEEVE,
    _attach_metric_values,
    _bucket_col,
    _build_sleeves,
    _load_fires_and_pairs,
    _metric_frame,
    _metric_frames,
    _simulate_all_bars_baseline,
    _simulate_all_depth_trades,
)
from bh_ftmo.data.fx_store import FxStore  # noqa: E402

SEED = 20260614
METRIC = "atr_pct_w252"
BUCKET_COL = _bucket_col(METRIC)
BOOK_PATH = OUT_DIR / "atr_regime_p3_book.csv"
REPORT_PATH = OUT_DIR / "ATR_REGIME_P3.md"
OUT_PATH = OUT_DIR / "atr_regime_p3.out"
HALVES = ("full", "h1", "h2")
CONDITIONERS: dict[str, dict[str, float]] = {
    "unconditioned": {
        "ATR_low_0_33": 1.0,
        "ATR_mid_33_67": 1.0,
        "ATR_high_67_100": 1.0,
    },
    "hard_gate_skip_high": {
        "ATR_low_0_33": 1.0,
        "ATR_mid_33_67": 1.0,
        "ATR_high_67_100": 0.0,
    },
    "size_down_high_0_5": {
        "ATR_low_0_33": 1.0,
        "ATR_mid_33_67": 1.0,
        "ATR_high_67_100": 0.5,
    },
    "size_down_high_0_0": {
        "ATR_low_0_33": 1.0,
        "ATR_mid_33_67": 1.0,
        "ATR_high_67_100": 0.0,
    },
    "size_up_low_1_5": {
        "ATR_low_0_33": 1.5,
        "ATR_mid_33_67": 1.0,
        "ATR_high_67_100": 1.0,
    },
    "size_up_low_1_5_down_high_0_5": {
        "ATR_low_0_33": 1.5,
        "ATR_mid_33_67": 1.0,
        "ATR_high_67_100": 0.5,
    },
}


def _half_labels(frame: pd.DataFrame) -> pd.Series:
    ordered = frame.sort_values(["ts", "pair", "bar_idx"]).reset_index()
    cut = len(ordered) // 2
    labels = pd.Series("h2", index=ordered["index"], dtype=object)
    labels.loc[ordered.iloc[:cut]["index"]] = "h1"
    return labels


def _book_frame(frame: pd.DataFrame, sample: str) -> pd.DataFrame:
    out = _metric_frame(frame, METRIC).copy()
    if out.empty:
        raise RuntimeError(f"{sample} produced no {METRIC} trades")
    out["sample"] = sample
    out["regime"] = out[BUCKET_COL].map(REGIME_LABEL)
    out["half"] = ""
    labels = _half_labels(out)
    out.loc[labels.index, "half"] = labels
    return out.sort_values(["ts", "pair", "bar_idx"]).reset_index(drop=True)


def _max_drawdown(values: pd.Series) -> float:
    if values.empty:
        return np.nan
    equity = values.cumsum()
    peak = equity.cummax()
    return float((peak - equity).max())


def _daily_sharpe_like(frame: pd.DataFrame) -> float:
    if frame.empty:
        return np.nan
    daily = frame.groupby(frame["ts"].dt.floor("D"), sort=True)["sized_R"].sum()
    std = float(daily.std(ddof=1))
    if not np.isfinite(std) or std == 0.0:
        return np.nan
    return float(daily.mean() / std)


def _period_years(frame: pd.DataFrame) -> float:
    if frame.empty:
        return np.nan
    span_days = (frame["ts"].max() - frame["ts"].min()).total_seconds() / 86400.0
    return max(span_days / 365.25, 1.0 / 365.25)


def _conditioned_frame(frame: pd.DataFrame, multipliers: dict[str, float]) -> pd.DataFrame:
    out = frame.copy()
    out["risk_multiplier"] = out[BUCKET_COL].map(multipliers).astype(float)
    out["active_trade"] = out["risk_multiplier"] > 0.0
    out["sized_R"] = out["R"] * out["risk_multiplier"]
    return out[out["active_trade"]].copy()


def _metrics_for(
    frame: pd.DataFrame,
    *,
    sample: str,
    half: str,
    conditioner: str,
    multipliers: dict[str, float],
) -> dict[str, object]:
    half_frame = frame if half == "full" else frame[frame["half"] == half]
    conditioned = _conditioned_frame(half_frame, multipliers)
    trades = len(conditioned)
    total_r = float(conditioned["sized_R"].sum()) if trades else 0.0
    max_dd = _max_drawdown(conditioned["sized_R"]) if trades else np.nan
    expectancy = total_r / trades if trades else np.nan
    throughput = trades / _period_years(half_frame) if not half_frame.empty else np.nan
    return_dd = total_r / max_dd if np.isfinite(max_dd) and max_dd > 0.0 else np.nan
    bucket_counts = conditioned[BUCKET_COL].value_counts().to_dict()
    return {
        "sample": sample,
        "half": half,
        "conditioner": conditioner,
        "low_mult": multipliers["ATR_low_0_33"],
        "mid_mult": multipliers["ATR_mid_33_67"],
        "high_mult": multipliers["ATR_high_67_100"],
        "total_R": total_r,
        "expectancy_R": expectancy,
        "trades": trades,
        "base_signals": len(half_frame),
        "throughput_trades_per_year": throughput,
        "maxDD_R": max_dd,
        "return_DD": return_dd,
        "daily_R_sharpe_like": _daily_sharpe_like(conditioned),
        "low_trades": int(bucket_counts.get("ATR_low_0_33", 0)),
        "mid_trades": int(bucket_counts.get("ATR_mid_33_67", 0)),
        "high_trades": int(bucket_counts.get("ATR_high_67_100", 0)),
    }


def _add_deltas(results: pd.DataFrame) -> pd.DataFrame:
    out = results.copy()
    delta_cols = [
        "delta_total_R",
        "delta_expectancy_R",
        "delta_throughput_trades_per_year",
        "delta_maxDD_reduction_R",
        "delta_return_DD",
        "throughput_cost_pct",
    ]
    for col in delta_cols:
        out[col] = np.nan
    for (sample, half), sub in out.groupby(["sample", "half"], sort=False):
        base = sub[sub["conditioner"] == "unconditioned"]
        if base.empty:
            continue
        base_row = base.iloc[0]
        mask = (out["sample"] == sample) & (out["half"] == half)
        out.loc[mask, "delta_total_R"] = out.loc[mask, "total_R"] - float(base_row.total_R)
        out.loc[mask, "delta_expectancy_R"] = (
            out.loc[mask, "expectancy_R"] - float(base_row.expectancy_R)
        )
        out.loc[mask, "delta_throughput_trades_per_year"] = (
            out.loc[mask, "throughput_trades_per_year"]
            - float(base_row.throughput_trades_per_year)
        )
        out.loc[mask, "delta_maxDD_reduction_R"] = (
            float(base_row.maxDD_R) - out.loc[mask, "maxDD_R"]
        )
        out.loc[mask, "delta_return_DD"] = out.loc[mask, "return_DD"] - float(base_row.return_DD)
        if int(base_row.trades) > 0:
            out.loc[mask, "throughput_cost_pct"] = 1.0 - out.loc[mask, "trades"] / float(
                base_row.trades,
            )
    return out


def _arbiter_rows(results: pd.DataFrame, mr_sample: str) -> pd.DataFrame:
    rows = []
    random_sample = "all_bars_random_long"
    for conditioner in CONDITIONERS:
        if conditioner == "unconditioned":
            continue
        mr = _select_metric(results, mr_sample, "full", conditioner)
        random = _select_metric(results, random_sample, "full", conditioner)
        rows.append({
            "conditioner": conditioner,
            "mr_delta_total_R": mr.delta_total_R,
            "random_delta_total_R": random.delta_total_R,
            "cell_alpha_delta_R": mr.delta_total_R - random.delta_total_R,
            "mr_delta_return_DD": mr.delta_return_DD,
            "random_delta_return_DD": random.delta_return_DD,
            "cell_alpha_delta_return_DD": mr.delta_return_DD - random.delta_return_DD,
            "mr_dd_reduction_R": mr.delta_maxDD_reduction_R,
            "random_dd_reduction_R": random.delta_maxDD_reduction_R,
            "cell_alpha_dd_reduction_R": (
                mr.delta_maxDD_reduction_R - random.delta_maxDD_reduction_R
            ),
            "mr_throughput_cost_pct": mr.throughput_cost_pct,
            "random_throughput_cost_pct": random.throughput_cost_pct,
        })
    return pd.DataFrame(rows)


def _select_metric(
    results: pd.DataFrame,
    sample: str,
    half: str,
    conditioner: str,
) -> pd.Series:
    sub = results[
        (results["sample"] == sample)
        & (results["half"] == half)
        & (results["conditioner"] == conditioner)
    ]
    if sub.empty:
        raise RuntimeError(f"missing metrics row: {sample} {half} {conditioner}")
    return sub.iloc[0]


def _fmt_pct(value: float) -> str:
    if not np.isfinite(value):
        return "nan"
    return f"{100.0 * value:.1f}%"


def _best_conditioner(results: pd.DataFrame, sample: str) -> str:
    candidates = results[
        (results["sample"] == sample)
        & (results["half"] == "full")
        & (results["conditioner"] != "unconditioned")
    ].copy()
    candidates = candidates[
        (candidates["delta_total_R"] >= 0.0)
        & (candidates["delta_maxDD_reduction_R"] >= 0.0)
        & (candidates["delta_return_DD"] >= 0.0)
    ].copy()
    if candidates.empty:
        return "unconditioned"
    candidates["score"] = (
        candidates["delta_return_DD"].fillna(-999.0)
        + 0.002 * candidates["delta_maxDD_reduction_R"].fillna(0.0)
        + 0.001 * candidates["delta_total_R"].fillna(0.0)
        - 4.0 * candidates["throughput_cost_pct"].fillna(0.0)
    )
    candidates = candidates.sort_values(
        ["score", "delta_return_DD", "delta_total_R"],
        ascending=False,
    )
    return str(candidates.iloc[0].conditioner)


def _schedule_for(conditioner: str) -> tuple[float, float, float]:
    multipliers = CONDITIONERS[conditioner]
    return (
        multipliers["ATR_low_0_33"],
        multipliers["ATR_mid_33_67"],
        multipliers["ATR_high_67_100"],
    )


def _deploy_call(results: pd.DataFrame, arbiter: pd.DataFrame, best: str) -> tuple[str, str]:
    if best == "unconditioned":
        return "do not deploy", "no conditioner improves the book-level trade-off"
    best_row = _select_metric(results, PRIMARY_SLEEVE, "full", best)
    arb_row = arbiter[arbiter["conditioner"] == best].iloc[0]
    improves_dd = bool(best_row.delta_maxDD_reduction_R > 0.0)
    preserves_book = bool(best_row.delta_total_R >= 0.0 or best_row.delta_return_DD > 0.0)
    throughput_ok = bool(best_row.throughput_cost_pct <= 0.35)
    alpha_return = bool(
        arb_row.cell_alpha_delta_R > 0.0 and arb_row.cell_alpha_delta_return_DD > 0.0
    )
    alpha_dd = bool(arb_row.cell_alpha_dd_reduction_R > 0.0)
    if improves_dd and preserves_book and throughput_ok:
        if alpha_return and alpha_dd:
            alpha_text = "cell alpha across return and drawdown"
        elif alpha_return:
            alpha_text = "MR-specific return/return-DD alpha plus generic vol-beta DD control"
        else:
            alpha_text = "generic vol-beta risk control"
        return "deploy", alpha_text
    return "do not deploy", "book-level trade-off is not strong enough"


def _report(results: pd.DataFrame, arbiter: pd.DataFrame, dedup_rows: pd.DataFrame) -> str:
    best = _best_conditioner(results, PRIMARY_SLEEVE)
    schedule = _schedule_for(best)
    call, alpha_text = _deploy_call(results, arbiter, best)
    base = _select_metric(results, PRIMARY_SLEEVE, "full", "unconditioned")
    best_row = _select_metric(results, PRIMARY_SLEEVE, "full", best)
    random_best = _select_metric(results, "all_bars_random_long", "full", best)
    full6_best = _select_metric(results, "long_mr_full6", "full", best)
    arb_row = arbiter[arbiter["conditioner"] == best].iloc[0]
    table_cols = [
        "conditioner",
        "total_R",
        "expectancy_R",
        "trades",
        "throughput_cost_pct",
        "maxDD_R",
        "return_DD",
        "delta_total_R",
        "delta_maxDD_reduction_R",
        "delta_return_DD",
    ]
    primary_full = results[
        (results["sample"] == PRIMARY_SLEEVE)
        & (results["half"] == "full")
    ].copy()
    primary_full["throughput_cost_pct"] = primary_full["throughput_cost_pct"].map(_fmt_pct)
    lines = [
        "# ATR Regime P3",
        "",
        "## Headline",
        (
            f"Deploy call: **{call}** the w252 ATR regime sizing schedule "
            f"low={schedule[0]:.1f}, mid={schedule[1]:.1f}, high={schedule[2]:.1f}."
        ),
        (
            f"Best deployable trade-off on `{PRIMARY_SLEEVE}` is `{best}`: "
            f"total R {_fmt(best_row.total_R)} vs unconditioned {_fmt(base.total_R)}, "
            f"maxDD {_fmt(best_row.maxDD_R)} vs {_fmt(base.maxDD_R)} "
            f"(DD reduction {_fmt(best_row.delta_maxDD_reduction_R)}), "
            f"return/DD {_fmt(best_row.return_DD)} vs {_fmt(base.return_DD)}, "
            f"throughput cost {_fmt_pct(float(best_row.throughput_cost_pct))}."
        ),
        (
            "Book-level alpha arbiter: the same conditioner on the all-bars random-long "
            f"book has delta return/DD {_fmt(random_best.delta_return_DD)} and DD "
            f"reduction {_fmt(random_best.delta_maxDD_reduction_R)}. MR minus random "
            f"alpha deltas are total R {_fmt(arb_row.cell_alpha_delta_R)}, "
            f"return/DD {_fmt(arb_row.cell_alpha_delta_return_DD)}, and DD reduction "
            f"{_fmt(arb_row.cell_alpha_dd_reduction_R)}. "
            f"Interpretation: **{alpha_text}**."
        ),
        "",
        "## Primary Book Full-Period Metrics",
    ]
    lines.extend(_markdown_table(primary_full, table_cols))
    lines.extend([
        "",
        "## Stability",
    ])
    stability = results[
        (results["sample"] == PRIMARY_SLEEVE)
        & (results["conditioner"].isin(["unconditioned", best]))
    ].copy()
    stability["throughput_cost_pct"] = stability["throughput_cost_pct"].map(_fmt_pct)
    lines.extend(_markdown_table(
        stability,
        ["conditioner", "half", "total_R", "trades", "maxDD_R", "return_DD", "delta_total_R"],
    ))
    lines.extend([
        "",
        "## Alpha Arbiter",
    ])
    arbiter_view = arbiter.copy()
    for col in ["mr_throughput_cost_pct", "random_throughput_cost_pct"]:
        arbiter_view[col] = arbiter_view[col].map(_fmt_pct)
    lines.extend(_markdown_table(
        arbiter_view,
        [
            "conditioner",
            "mr_delta_total_R",
            "random_delta_total_R",
            "cell_alpha_delta_R",
            "mr_delta_return_DD",
            "random_delta_return_DD",
            "cell_alpha_delta_return_DD",
            "mr_dd_reduction_R",
            "random_dd_reduction_R",
            "cell_alpha_dd_reduction_R",
            "mr_throughput_cost_pct",
        ],
    ))
    lines.extend([
        "",
        "## Full-6 Cross-Check",
        (
            f"`long_mr_full6` under `{best}`: total R {_fmt(full6_best.total_R)}, "
            f"delta R {_fmt(full6_best.delta_total_R)}, maxDD reduction "
            f"{_fmt(full6_best.delta_maxDD_reduction_R)}, return/DD delta "
            f"{_fmt(full6_best.delta_return_DD)}."
        ),
        "",
        "## Dedup And Method",
    ])
    lines.extend(_markdown_table(
        dedup_rows,
        ["sleeve", "direction", "sum_cell_trades", "deduped_trades", "dedup_drop"],
    ))
    lines.extend([
        "",
        (
            f"Method: causal/PIT `{METRIC}` ATR(14) rolling percentile; buckets are "
            "low 0-33, mid 33-67, high 67-100. Long-MR trades use deployed mid-entry "
            f"fires, 1%/1% R, MAX_HOLD={MAX_HOLD}, deduped one trade per "
            "`(pair, entry_bar)`. Random baseline is the all-bars long book over the "
            "same pairs and period. No sampling is used; numpy seed "
            f"{SEED} is fixed for reproducibility if sampling is added later."
        ),
        "",
        "## Artifacts",
        f"- `{BOOK_PATH.name}`: book metrics by sample, conditioner, and half.",
        f"- `{OUT_PATH.name}`: run summary.",
        "",
        "Production wiring is intentionally out of scope for P3.",
        "",
    ])
    return "\n".join(lines)


def run() -> tuple[pd.DataFrame, str]:
    np.random.seed(SEED)
    fires, pairs = _load_fires_and_pairs()
    start_ts = pd.Timestamp(fires["ts"].min())
    end_ts = pd.Timestamp(fires["ts"].max())
    with FxStore(read_only=True) as store:
        metric_frames = _metric_frames(store, pairs, start_ts, end_ts)
        random_book = _simulate_all_bars_baseline(metric_frames)
    all_trades, _drop_rows = _simulate_all_depth_trades(fires, pairs)
    all_trades = _attach_metric_values(all_trades, metric_frames)
    sleeve_trades, dedup_rows = _build_sleeves(all_trades)
    samples = {
        PRIMARY_SLEEVE: _book_frame(
            sleeve_trades[(PRIMARY_SLEEVE, PRIMARY_DIRECTION)],
            PRIMARY_SLEEVE,
        ),
        "long_mr_full6": _book_frame(sleeve_trades[("long_mr_full6", "long")], "long_mr_full6"),
        "all_bars_random_long": _book_frame(random_book, "all_bars_random_long"),
    }
    rows: list[dict[str, object]] = []
    for sample, frame in samples.items():
        for half in HALVES:
            for conditioner, multipliers in CONDITIONERS.items():
                rows.append(_metrics_for(
                    frame,
                    sample=sample,
                    half=half,
                    conditioner=conditioner,
                    multipliers=multipliers,
                ))
    results = _add_deltas(pd.DataFrame(rows))
    arbiter = _arbiter_rows(results, PRIMARY_SLEEVE)
    results.to_csv(BOOK_PATH, index=False)
    report = _report(results, arbiter, dedup_rows)
    REPORT_PATH.write_text(report, encoding="utf-8")
    best = _best_conditioner(results, PRIMARY_SLEEVE)
    call, alpha_text = _deploy_call(results, arbiter, best)
    best_row = _select_metric(results, PRIMARY_SLEEVE, "full", best)
    out_lines = [
        "ATR-regime P3 run complete",
        f"pairs={len(pairs)} period={start_ts}..{end_ts}",
        f"TP={TP_PCT:.4f} STOP={STOP_PCT:.4f} MAX_HOLD={MAX_HOLD}",
        f"metric={METRIC} seed={SEED} sampling_used=False",
        f"primary_sample={PRIMARY_SLEEVE}",
        f"best_conditioner={best}",
        f"deploy_call={call}",
        f"arbiter={alpha_text}",
        f"best_total_R={best_row.total_R:+.6f}",
        f"best_delta_total_R={best_row.delta_total_R:+.6f}",
        f"best_delta_maxDD_reduction_R={best_row.delta_maxDD_reduction_R:+.6f}",
        f"best_delta_return_DD={best_row.delta_return_DD:+.6f}",
        f"best_throughput_cost_pct={best_row.throughput_cost_pct:.6f}",
        f"csv={BOOK_PATH}",
        f"report={REPORT_PATH}",
    ]
    OUT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return results, report


def main() -> None:
    run()


if __name__ == "__main__":
    main()
