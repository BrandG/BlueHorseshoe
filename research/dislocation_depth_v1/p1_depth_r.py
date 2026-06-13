"""P1 dislocation-depth R curves and monotonicity verdict."""
# pylint: disable=import-error,wrong-import-order,wrong-import-position
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-locals
# pylint: disable=too-many-statements,too-many-branches,duplicate-code
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

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
from bh_ftmo.indicators import ohlc_mid  # noqa: E402
from factor_grouping import choose_params, deployed_cells  # noqa: E402
from _lib import (  # noqa: E402
    MAX_HOLD,
    STOP_PCT,
    TP_PCT,
    sim_long_limit,
    sim_long_mid,
    sim_short_limit,
    sim_short_mid,
)

EVALUATORS = ("bb", "rsi", "cci", "sma", "ema", "stoch")
DIRECTIONS = ("long", "short")
PRICE_DOMAIN = frozenset({"bb", "ema", "sma"})
OSCILLATOR_DOMAIN = frozenset({"rsi", "cci", "stoch"})
QUINTILES = ("Q1_shallow", "Q2", "Q3", "Q4", "Q5_deep")
ATR_BUCKETS = (
    ("ATR_missing", -np.inf, 0.0),
    ("ATR_low_0_33", 0.0, 1.0 / 3.0),
    ("ATR_mid_33_67", 1.0 / 3.0, 2.0 / 3.0),
    ("ATR_high_67_100", 2.0 / 3.0, np.inf),
)
FIXED_BUCKETS = {
    "bb": (0.0, 0.10, 0.25, 0.50, 1.00, np.inf),
    "ema": (0.0, 0.10, 0.25, 0.50, 1.00, np.inf),
    "sma": (0.0, 0.10, 0.25, 0.50, 1.00, np.inf),
    "rsi": (0.0, 2.5, 5.0, 10.0, 15.0, np.inf),
    "cci": (0.0, 25.0, 50.0, 100.0, 150.0, np.inf),
    "stoch": (0.0, 5.0, 10.0, 15.0, 20.0, np.inf),
}

FIRES_PATH = OUT_DIR / "depth_fires.csv"
CURVES_PATH = OUT_DIR / "depth_r_curves.csv"
REPORT_PATH = OUT_DIR / "P1_DEPTH_R.md"
OUT_PATH = OUT_DIR / "p1_depth_r.out"


def _fmt(value: float, digits: int = 3) -> str:
    if not np.isfinite(value):
        return "nan"
    return f"{value:+.{digits}f}"


def _entry_modes(cells: list[object]) -> dict[str, str]:
    modes: dict[str, str] = {}
    for evaluator in EVALUATORS:
        found = sorted({cell.entry_mode for cell in cells if cell.strategy == evaluator})
        if len(found) != 1:
            raise RuntimeError(f"expected one entry_mode for {evaluator}, got {found}")
        modes[evaluator] = found[0]
    return modes


def _depth_column(evaluator: str) -> str:
    if evaluator in PRICE_DOMAIN:
        return "atr_norm_depth"
    if evaluator in OSCILLATOR_DOMAIN:
        return "raw_depth"
    raise ValueError(f"unsupported evaluator: {evaluator}")


def _simulator(direction: str, entry_mode: str) -> Callable:
    if direction == "long" and entry_mode == "mid":
        return sim_long_mid
    if direction == "short" and entry_mode == "mid":
        return sim_short_mid
    if direction == "long" and entry_mode == "limit":
        return sim_long_limit
    if direction == "short" and entry_mode == "limit":
        return sim_short_limit
    raise ValueError(f"unsupported simulator: {direction=} {entry_mode=}")


def _stat(values: pd.Series) -> dict[str, float | int]:
    arr = values.to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return {"n": 0, "mean_R": np.nan, "SE": np.nan, "CI_low": np.nan}
    mean = float(arr.mean())
    if len(arr) == 1:
        se = 0.0
    else:
        se = float(arr.std(ddof=1) / np.sqrt(len(arr)))
    return {"n": int(len(arr)), "mean_R": mean, "SE": se, "CI_low": mean - 1.96 * se}


def _spearman(left: list[float], right: list[float]) -> float:
    data = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(data) < 2:
        return float("nan")
    if data["left"].nunique() < 2 or data["right"].nunique() < 2:
        return float("nan")
    return float(data["left"].rank().corr(data["right"].rank()))


def _ols_slope(x_values: pd.Series, y_values: pd.Series) -> float:
    data = pd.DataFrame({"x": x_values, "y": y_values}).replace(
        [np.inf, -np.inf],
        np.nan,
    ).dropna()
    if len(data) < 2 or data["x"].std(ddof=0) == 0.0:
        return float("nan")
    x_arr = data["x"].to_numpy(dtype=float)
    y_arr = data["y"].to_numpy(dtype=float)
    return float(np.cov(x_arr, y_arr, ddof=0)[0, 1] / np.var(x_arr))


def _fixed_labels(evaluator: str) -> list[str]:
    edges = FIXED_BUCKETS[evaluator]
    labels = []
    for low, high in zip(edges[:-1], edges[1:]):
        if np.isinf(high):
            labels.append(f">={low:g}")
        else:
            labels.append(f"{low:g}_{high:g}")
    return labels


def _assign_buckets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["quintile_bucket"] = ""
    out["fixed_bucket"] = ""
    for (evaluator, _direction), idx in out.groupby(["evaluator", "direction"]).groups.items():
        sub = out.loc[idx]
        ranked = sub["depth"].rank(method="first")
        out.loc[idx, "quintile_bucket"] = pd.qcut(
            ranked,
            q=len(QUINTILES),
            labels=QUINTILES,
        ).astype(str)
        labels = _fixed_labels(evaluator)
        out.loc[idx, "fixed_bucket"] = pd.cut(
            sub["depth"],
            bins=FIXED_BUCKETS[evaluator],
            labels=labels,
            include_lowest=True,
            right=False,
        ).astype(str)
    return out


def _atr_bucket(value: float) -> str:
    if not np.isfinite(value):
        return "ATR_missing"
    for label, low, high in ATR_BUCKETS[1:]:
        if low <= value < high:
            return label
    return "ATR_missing"


def _curve_rows_for_group(
    sub: pd.DataFrame,
    *,
    level: str,
    forex_pair: str,
    bucket_type: str,
    bucket_col: str,
    ordered_buckets: tuple[str, ...] | list[str],
) -> list[dict[str, object]]:
    rows = []
    for bucket in ordered_buckets:
        bucket_sub = sub[sub[bucket_col] == bucket]
        stats = _stat(bucket_sub["R"])
        rows.append({
            "evaluator": sub["evaluator"].iloc[0],
            "level": level,
            "pair_or_pooled": forex_pair,
            "direction": sub["direction"].iloc[0],
            "bucket_type": bucket_type,
            "bucket": bucket,
            **stats,
        })
    return rows


def _build_curves(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    group_cols = ["evaluator", "direction"]
    for _, sub in df.groupby(group_cols, sort=True):
        rows.extend(_curve_rows_for_group(
            sub,
            level="POOLED",
            forex_pair="POOLED",
            bucket_type="quintile",
            bucket_col="quintile_bucket",
            ordered_buckets=QUINTILES,
        ))
        rows.extend(_curve_rows_for_group(
            sub,
            level="POOLED",
            forex_pair="POOLED",
            bucket_type="fixed",
            bucket_col="fixed_bucket",
            ordered_buckets=_fixed_labels(str(sub["evaluator"].iloc[0])),
        ))
    for (_, _, pair), sub in df.groupby(["evaluator", "direction", "pair"], sort=True):
        rows.extend(_curve_rows_for_group(
            sub,
            level="PAIR",
            forex_pair=pair,
            bucket_type="quintile",
            bucket_col="quintile_bucket",
            ordered_buckets=QUINTILES,
        ))
        rows.extend(_curve_rows_for_group(
            sub,
            level="PAIR",
            forex_pair=pair,
            bucket_type="fixed",
            bucket_col="fixed_bucket",
            ordered_buckets=_fixed_labels(str(sub["evaluator"].iloc[0])),
        ))
    curves = pd.DataFrame(rows)
    sort_cols = ["evaluator", "level", "pair_or_pooled", "direction", "bucket_type", "bucket"]
    return curves.sort_values(sort_cols)


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
        entry_mode = str(fire.entry_mode)
        ts = pd.Timestamp(fire.ts)
        bar_idx = index_by_ts.get(ts)
        if bar_idx is None:
            dropped[(evaluator, direction)] += 1
            continue
        sim = _simulator(direction, entry_mode)
        r_value, exit_idx = sim(close, high, low, int(bar_idx), MAX_HOLD)
        if r_value is None:
            dropped[(evaluator, direction)] += 1
            continue
        depth = getattr(fire, _depth_column(evaluator))
        rows.append({
            "pair": pair,
            "evaluator": evaluator,
            "direction": direction,
            "entry_mode": entry_mode,
            "ts": ts,
            "bar_idx": int(bar_idx),
            "exit_idx": int(exit_idx),
            "R": float(r_value),
            "depth": float(depth),
            "raw_depth": float(fire.raw_depth),
            "atr_norm_depth": float(fire.atr_norm_depth),
            "entry_ATR": float(fire.entry_ATR),
            "ATR_percentile": float(fire.ATR_percentile),
        })
    return rows, dropped


def _simulate_trades(fires: pd.DataFrame, pairs: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    dropped: dict[tuple[str, str], int] = defaultdict(int)
    with FxStore(read_only=True) as store:
        for pair in pairs:
            pair_rows, pair_dropped = _load_pair_trades(store, fires, pair)
            rows.extend(pair_rows)
            for key, count in pair_dropped.items():
                dropped[key] += count
    trades = pd.DataFrame(rows)
    if trades.empty:
        raise RuntimeError("no realized trades after simulation")
    trades = trades.replace([np.inf, -np.inf], np.nan).dropna(subset=["depth", "R"])
    trades["atr_bucket"] = trades["ATR_percentile"].map(_atr_bucket)
    trades = _assign_buckets(trades)

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


def _baseline_stats(trades: pd.DataFrame) -> dict[tuple[str, str], dict[str, float | int]]:
    out = {}
    for (evaluator, direction), sub in trades.groupby(["evaluator", "direction"], sort=True):
        out[(evaluator, direction)] = _stat(sub["R"])
    return out


def _monotonic_rows(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    baselines = _baseline_stats(trades)
    for (evaluator, direction), sub in trades.groupby(["evaluator", "direction"], sort=True):
        means = [
            float(sub[sub["quintile_bucket"] == bucket]["R"].mean())
            for bucket in QUINTILES
        ]
        deepest = _stat(sub[sub["quintile_bucket"] == "Q5_deep"]["R"])
        shallow = _stat(sub[sub["quintile_bucket"] == "Q1_shallow"]["R"])
        baseline = baselines[(evaluator, direction)]
        rows.append({
            "evaluator": evaluator,
            "direction": direction,
            "n": int(baseline["n"]),
            "baseline_mean_R": float(baseline["mean_R"]),
            "spearman_quintile_mean_R": _spearman([1, 2, 3, 4, 5], means),
            "ols_slope_R_on_depth": _ols_slope(sub["depth"], sub["R"]),
            "shallow_mean_R": float(shallow["mean_R"]),
            "deepest_n": int(deepest["n"]),
            "deepest_mean_R": float(deepest["mean_R"]),
            "deepest_CI_low": float(deepest["CI_low"]),
            "deepest_lift_vs_baseline": (
                float(deepest["mean_R"]) - float(baseline["mean_R"])
            ),
            "deepest_lift_vs_shallow": (
                float(deepest["mean_R"]) - float(shallow["mean_R"])
            ),
        })
    return pd.DataFrame(rows)


def _atr_tables(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    atr_rows = []
    two_way_rows = []
    flags = []
    for (evaluator, direction), sub in trades.groupby(["evaluator", "direction"], sort=True):
        for bucket, bucket_sub in sub.groupby("atr_bucket", sort=True):
            stats = _stat(bucket_sub["R"])
            atr_rows.append({
                "evaluator": evaluator,
                "direction": direction,
                "atr_bucket": bucket,
                **stats,
            })
        positive_strata = 0
        comparable_strata = 0
        for atr_bucket in [label for label, _, _ in ATR_BUCKETS]:
            atr_sub = sub[sub["atr_bucket"] == atr_bucket]
            q1 = atr_sub[atr_sub["quintile_bucket"] == "Q1_shallow"]
            q5 = atr_sub[atr_sub["quintile_bucket"] == "Q5_deep"]
            if len(q1) > 0 and len(q5) > 0:
                comparable_strata += 1
                if float(q5["R"].mean()) > float(q1["R"].mean()):
                    positive_strata += 1
            for quintile in QUINTILES:
                bucket_sub = atr_sub[atr_sub["quintile_bucket"] == quintile]
                stats = _stat(bucket_sub["R"])
                two_way_rows.append({
                    "evaluator": evaluator,
                    "direction": direction,
                    "atr_bucket": atr_bucket,
                    "depth_quintile": quintile,
                    **stats,
                })
        flags.append({
            "evaluator": evaluator,
            "direction": direction,
            "positive_strata": positive_strata,
            "comparable_strata": comparable_strata,
            "vanishes_within_atr": comparable_strata > 0 and positive_strata == 0,
        })
    return pd.DataFrame(atr_rows), pd.DataFrame(two_way_rows), pd.DataFrame(flags)


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
    trades: pd.DataFrame,
    curves: pd.DataFrame,
    drops: pd.DataFrame,
    choices: dict[str, object],
    modes: dict[str, str],
) -> str:
    monotonic = _monotonic_rows(trades)
    atr_stats, two_way, atr_flags = _atr_tables(trades)
    survivors = []
    lines = [
        "# P1 Depth R",
        "",
        "## Method",
        (
            f"Simulated P0 fires with `_lib.py` mid/limit simulators at TP={TP_PCT:.0%}, "
            f"SL={STOP_PCT:.0%}, and fixed `MAX_HOLD={MAX_HOLD}` H4 bars. "
            "`MAX_HOLD` is imported from the v2 harness and matches "
            "`research/confluence_v1/p1a_sweep.py`."
        ),
        (
            "Depth metric: `atr_norm_depth` for price-domain cells "
            "(bb/ema/sma), raw oscillator-unit depth for rsi/cci/stoch. "
            "All six deployed dislocation cells use mean-reversion `mid` entry mode."
        ),
        (
            "Fixed buckets are evaluator-specific: price-domain ATR units "
            "[0,0.10,0.25,0.50,1.00,inf), RSI [0,2.5,5,10,15,inf), "
            "CCI [0,25,50,100,150,inf), stoch [0,5,10,15,20,inf)."
        ),
        "",
        "## Deployed Cells",
    ]
    for evaluator in EVALUATORS:
        choice = choices[evaluator]
        lines.append(
            f"- {evaluator}: entry_mode={modes[evaluator]}, "
            f"params=`{json.dumps(choice.params, sort_keys=True)}`"
        )
    lines.extend(["", "## Fire Count / Drop Sanity"])
    drop_table = drops.copy()
    lines.extend(_markdown_table(
        drop_table,
        ["evaluator", "direction", "fires", "realized", "dropped", "sim_dropped"],
    ))
    lines.extend(["", "## Kill-Or-Advance Verdict"])
    for row in monotonic.sort_values(["evaluator", "direction"]).itertuples(index=False):
        flag = atr_flags[
            (atr_flags["evaluator"] == row.evaluator)
            & (atr_flags["direction"] == row.direction)
        ].iloc[0]
        monotone = row.spearman_quintile_mean_R > 0 and row.deepest_lift_vs_shallow > 0
        clears = row.deepest_CI_low > 0 and row.deepest_lift_vs_baseline > 0
        survived = bool(monotone and clears)
        if survived:
            survivors.append((row.evaluator, row.direction))
        vanish_text = (
            "gradient vanishes within ATR strata"
            if bool(flag.vanishes_within_atr)
            else (
                f"ATR strata positive in {int(flag.positive_strata)}/"
                f"{int(flag.comparable_strata)} comparable buckets"
            )
        )
        lines.append(
            f"- {row.evaluator} {row.direction}: "
            f"baseline={_fmt(row.baseline_mean_R)}, Q1={_fmt(row.shallow_mean_R)}, "
            f"Q5={_fmt(row.deepest_mean_R)} (CI_low={_fmt(row.deepest_CI_low)}), "
            f"Q5-baseline={_fmt(row.deepest_lift_vs_baseline)}, "
            f"Q5-Q1={_fmt(row.deepest_lift_vs_shallow)}, "
            f"Spearman={_fmt(row.spearman_quintile_mean_R)}, "
            f"slope={_fmt(row.ols_slope_R_on_depth, 5)}. "
            f"Monotone={'YES' if monotone else 'NO'}; "
            f"deepest clears={'YES' if clears else 'NO'}; {vanish_text}."
        )
    lines.extend(["", "## P2 Candidate Set"])
    if survivors:
        for evaluator, direction in survivors:
            lines.append(f"- {evaluator} {direction}")
    else:
        lines.append(
            "- None. No cell-direction passes both monotonicity and deepest-bucket "
            "positive-lift gates; route to relative-value / door #2 per the design doc."
        )
    lines.extend(["", "## ATR-Percentile Sanity"])
    atr_summary = atr_stats.sort_values(["evaluator", "direction", "atr_bucket"])
    atr_summary = atr_summary.rename(columns={"mean_R": "mean_R_by_ATR"})
    lines.extend(_markdown_table(
        atr_summary,
        ["evaluator", "direction", "atr_bucket", "n", "mean_R_by_ATR", "CI_low"],
    ))
    lines.extend(["", "## Depth x ATR Mean R"])
    for (evaluator, direction), sub in two_way.groupby(["evaluator", "direction"], sort=True):
        lines.extend(["", f"### {evaluator} {direction}"])
        pivot = sub.pivot(index="atr_bucket", columns="depth_quintile", values="mean_R")
        pivot = pivot.reindex([label for label, _, _ in ATR_BUCKETS], columns=QUINTILES)
        table = pivot.reset_index()
        lines.extend(_markdown_table(table, ["atr_bucket", *QUINTILES]))
    lines.extend([
        "",
        "## Artifacts",
        f"- `{CURVES_PATH.name}`: {len(curves):,} bucket rows, pooled and per-pair.",
        f"- `{OUT_PATH.name}`: run summary and headline survivor list.",
        "",
    ])
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

    trades, drops = _simulate_trades(fires, pairs)
    curves = _build_curves(trades)
    curves.to_csv(CURVES_PATH, index=False)
    report = _build_report(trades, curves, drops, choices, modes)
    REPORT_PATH.write_text(report, encoding="utf-8")

    monotonic = _monotonic_rows(trades)
    survivors = monotonic[
        (monotonic["spearman_quintile_mean_R"] > 0.0)
        & (monotonic["deepest_lift_vs_shallow"] > 0.0)
        & (monotonic["deepest_CI_low"] > 0.0)
        & (monotonic["deepest_lift_vs_baseline"] > 0.0)
    ]
    out_lines = [
        "P1 depth-R run complete",
        f"pairs={len(pairs)} trades={len(trades):,} curves={len(curves):,}",
        f"MAX_HOLD={MAX_HOLD} TP={TP_PCT:.4f} STOP={STOP_PCT:.4f}",
        "survivors="
        + (
            ", ".join(
                f"{row.evaluator}:{row.direction}"
                for row in survivors.sort_values(["evaluator", "direction"]).itertuples()
            )
            if not survivors.empty
            else "NONE"
        ),
    ]
    OUT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return curves, report


def main() -> None:
    run()


if __name__ == "__main__":
    main()
