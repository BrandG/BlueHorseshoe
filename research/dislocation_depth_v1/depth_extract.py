"""P0 dislocation-depth extraction and ATR-confound diagnostics."""
# pylint: disable=duplicate-code,import-error,missing-function-docstring
# pylint: disable=too-many-arguments,too-many-locals,wrong-import-order
# pylint: disable=wrong-import-position
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
CONFLUENCE_DIR = ROOT / "research" / "confluence_v1"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(CONFLUENCE_DIR))

from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators import (  # noqa: E402
    atr,
    bollinger_bands,
    cci,
    ema,
    ohlc_mid,
    rsi,
    sma,
    stochastic,
)
from co_fire import DIR_MASKERS  # noqa: E402
from factor_grouping import choose_params, deployed_cells  # noqa: E402

EVALUATORS = ("bb", "rsi", "cci", "sma", "ema", "stoch")
DIRECTIONS = ("long", "short")
ATR_PERIOD = 14
ATR_PERCENTILE_WINDOW = 252
FIRES_PATH = OUT_DIR / "depth_fires.csv"
REPORT_PATH = OUT_DIR / "P0_DEPTH_DISTRIBUTION.md"
CO_FIRE_OUT = CONFLUENCE_DIR / "co_fire.out"


def _fresh_indices(mask: np.ndarray) -> np.ndarray:
    return np.flatnonzero(mask.astype(bool))


def _safe_div(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    out = np.full(len(numerator), np.nan, dtype=float)
    good = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0.0)
    out[good] = numerator[good] / denominator[good]
    return out


def _rolling_percentile(values: pd.Series, window: int) -> pd.Series:
    def rank_last(arr: np.ndarray) -> float:
        finite = arr[np.isfinite(arr)]
        if len(finite) == 0 or not np.isfinite(arr[-1]):
            return np.nan
        return float(np.mean(finite <= arr[-1]))

    return values.rolling(window, min_periods=window).apply(rank_last, raw=True)


def _entry_modes(cells: list[Any]) -> dict[str, str]:
    modes: dict[str, str] = {}
    for evaluator in EVALUATORS:
        found = sorted({cell.entry_mode for cell in cells if cell.strategy == evaluator})
        if len(found) != 1:
            raise RuntimeError(f"expected one entry_mode for {evaluator}, got {found}")
        modes[evaluator] = found[0]
    return modes


def _expected_solo_counts() -> dict[tuple[str, str], int]:
    if not CO_FIRE_OUT.exists():
        raise RuntimeError(f"missing reference solo-count file: {CO_FIRE_OUT}")
    expected: dict[tuple[str, str], int] = {}
    pattern = re.compile(r"^\s*(\w+)\s+long=\s*(\d+)\s+short=\s*(\d+)")
    for line in CO_FIRE_OUT.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        evaluator, long_count, short_count = match.groups()
        if evaluator in EVALUATORS:
            expected[(evaluator, "long")] = int(long_count)
            expected[(evaluator, "short")] = int(short_count)
    missing = [(name, direction) for name in EVALUATORS for direction in DIRECTIONS
               if (name, direction) not in expected]
    if missing:
        raise RuntimeError(f"missing reference solo counts: {missing}")
    return expected


def _osc_depths(
    mid: pd.DataFrame,
    params: dict[str, Any],
    indicator: Callable[[pd.DataFrame, dict[str, Any]], np.ndarray],
    *,
    signed: bool,
) -> dict[str, np.ndarray]:
    arr = indicator(mid, params)
    recovery = int(params["recovery"])
    base = np.roll(arr, recovery)
    base[:recovery] = np.nan
    threshold = float(params["threshold"])
    if signed:
        return {
            "long": (-threshold) - base,
            "short": base - threshold,
        }
    return {
        "long": threshold - base,
        "short": base - (100.0 - threshold),
    }


def _rsi_arr(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    return rsi(mid, period=params["period"]).to_numpy(dtype=float)


def _cci_arr(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    return cci(mid, period=params["period"]).to_numpy(dtype=float)


def _stoch_arr(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    frame = stochastic(mid, k_period=params["k_period"], d_period=params["d_period"])
    return frame["k"].to_numpy(dtype=float)


def _bb_depths(
    mid: pd.DataFrame,
    params: dict[str, Any],
    entry_atr: np.ndarray,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    bands = bollinger_bands(mid, period=params["period"], n_std=params["n_std"])
    close = mid["close"].to_numpy(dtype=float)
    lower = bands["lower"].to_numpy(dtype=float)
    upper = bands["upper"].to_numpy(dtype=float)
    width = upper - lower
    raw = {
        "long": lower - close,
        "short": close - upper,
    }
    band_width = {
        direction: _safe_div(depth, width)
        for direction, depth in raw.items()
    }
    atr_norm = {
        direction: _safe_div(depth, entry_atr)
        for direction, depth in raw.items()
    }
    return {"raw": raw, "atr_norm": atr_norm}, band_width


def _ma_depths(
    mid: pd.DataFrame,
    params: dict[str, Any],
    entry_atr: np.ndarray,
    ma_fn: Callable[..., pd.Series],
) -> dict[str, dict[str, np.ndarray]]:
    ma_arr = ma_fn(mid, period=params["period"]).to_numpy(dtype=float)
    close = mid["close"].to_numpy(dtype=float)
    k_atr = float(params["k"]) * entry_atr
    raw = {
        "long": (ma_arr - close) - k_atr,
        "short": (close - ma_arr) - k_atr,
    }
    atr_norm = {
        direction: _safe_div(depth, entry_atr)
        for direction, depth in raw.items()
    }
    return {"raw": raw, "atr_norm": atr_norm}


def _depth_arrays(
    evaluator: str,
    mid: pd.DataFrame,
    params: dict[str, Any],
    entry_atr: np.ndarray,
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, np.ndarray] | None]:
    if evaluator == "bb":
        return _bb_depths(mid, params, entry_atr)
    if evaluator == "sma":
        return _ma_depths(mid, params, entry_atr, sma), None
    if evaluator == "ema":
        return _ma_depths(mid, params, entry_atr, ema), None
    if evaluator == "rsi":
        depths = _osc_depths(mid, params, _rsi_arr, signed=False)
    elif evaluator == "cci":
        depths = _osc_depths(mid, params, _cci_arr, signed=True)
    elif evaluator == "stoch":
        depths = _osc_depths(mid, params, _stoch_arr, signed=False)
    else:
        raise ValueError(f"unsupported evaluator: {evaluator}")
    return {"raw": depths, "atr_norm": depths}, None


def _fire_rows(
    *,
    pair: str,
    evaluator: str,
    entry_mode: str,
    mid: pd.DataFrame,
    timestamps: pd.Series,
    params: dict[str, Any],
    entry_atr: pd.Series,
    atr_percentile: pd.Series,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    masks = DIR_MASKERS[evaluator](mid, params)
    depth_map, band_width_depth = _depth_arrays(
        evaluator,
        mid,
        params,
        entry_atr.to_numpy(dtype=float),
    )
    rows: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for direction, mask in zip(DIRECTIONS, masks):
        indices = _fresh_indices(mask)
        counts[direction] = int(len(indices))
        for idx in indices:
            band_value = np.nan
            if band_width_depth is not None:
                band_value = float(band_width_depth[direction][idx])
            rows.append({
                "pair": pair,
                "evaluator": evaluator,
                "direction": direction,
                "entry_mode": entry_mode,
                "ts": timestamps.iloc[idx],
                "raw_depth": float(depth_map["raw"][direction][idx]),
                "atr_norm_depth": float(depth_map["atr_norm"][direction][idx]),
                "band_width_depth": band_value,
                "entry_ATR": float(entry_atr.iloc[idx]),
                "ATR_percentile": float(atr_percentile.iloc[idx]),
            })
    return rows, counts


def _corr(left: pd.Series, right: pd.Series) -> float:
    clean = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 2:
        return float("nan")
    if clean.iloc[:, 0].std(ddof=0) == 0.0 or clean.iloc[:, 1].std(ddof=0) == 0.0:
        return float("nan")
    return float(clean.iloc[:, 0].corr(clean.iloc[:, 1]))


def _quantiles(series: pd.Series) -> dict[str, float]:
    quantiles = series.replace([np.inf, -np.inf], np.nan).dropna().quantile(
        [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0],
    )
    return {f"q{int(level * 100):02d}": float(value) for level, value in quantiles.items()}


def _distribution_lines(df: pd.DataFrame) -> list[str]:
    lines = [
        "## Depth Distribution",
        "",
        "| evaluator | direction | n | raw q10 | raw q50 | raw q90 | atr q10 | atr q50 | atr q90 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for (evaluator, direction), sub in df.groupby(["evaluator", "direction"], sort=True):
        raw = _quantiles(sub["raw_depth"])
        atr_q = _quantiles(sub["atr_norm_depth"])
        lines.append(
            f"| {evaluator} | {direction} | {len(sub):,} | "
            f"{raw['q10']:.6g} | {raw['q50']:.6g} | {raw['q90']:.6g} | "
            f"{atr_q['q10']:.6g} | {atr_q['q50']:.6g} | {atr_q['q90']:.6g} |"
        )
    return lines


def _confound_frame(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for evaluator, sub in df.groupby("evaluator", sort=True):
        per_pair = []
        for pair, pair_df in sub.groupby("pair", sort=True):
            raw_corr = _corr(pair_df["raw_depth"], pair_df["entry_ATR"])
            atr_corr = _corr(pair_df["atr_norm_depth"], pair_df["entry_ATR"])
            per_pair.append((pair, raw_corr, atr_corr))
        raw_vals = [value for _, value, _ in per_pair if np.isfinite(value)]
        atr_vals = [value for _, _, value in per_pair if np.isfinite(value)]
        rows.append({
            "evaluator": evaluator,
            "n": len(sub),
            "pooled_raw_corr": _corr(sub["raw_depth"], sub["entry_ATR"]),
            "pooled_atr_norm_corr": _corr(sub["atr_norm_depth"], sub["entry_ATR"]),
            "per_pair_raw_min": min(raw_vals) if raw_vals else np.nan,
            "per_pair_raw_max": max(raw_vals) if raw_vals else np.nan,
            "per_pair_atr_norm_min": min(atr_vals) if atr_vals else np.nan,
            "per_pair_atr_norm_max": max(atr_vals) if atr_vals else np.nan,
            "per_pair_finite_n": len(raw_vals),
        })
    return pd.DataFrame(rows)


def _confound_lines(confound: pd.DataFrame) -> list[str]:
    lines = [
        "## Volatility-Confound Diagnostic",
        "",
        "| evaluator | n | corr(raw, ATR) | corr(ATR-norm, ATR) | "
        "per-pair raw range | per-pair ATR-norm range |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in confound.sort_values("evaluator").itertuples(index=False):
        lines.append(
            f"| {row.evaluator} | {int(row.n):,} | {row.pooled_raw_corr:.3f} | "
            f"{row.pooled_atr_norm_corr:.3f} | "
            f"[{row.per_pair_raw_min:.3f}, {row.per_pair_raw_max:.3f}] | "
            f"[{row.per_pair_atr_norm_min:.3f}, {row.per_pair_atr_norm_max:.3f}] |"
        )
    return lines


def _verdict(confound: pd.DataFrame) -> str:
    price_based = confound[confound["evaluator"].isin(["bb", "sma", "ema"])]
    raw_abs = price_based["pooled_raw_corr"].abs().mean()
    norm_abs = price_based["pooled_atr_norm_corr"].abs().mean()
    if norm_abs < raw_abs * 0.5:
        return (
            "For price-domain dislocations, ATR-normalization materially reduces "
            f"the pooled depth/ATR linkage (mean |corr| {raw_abs:.3f} -> {norm_abs:.3f}). "
            "P1 should lean on `atr_norm_depth` for those cells."
        )
    return (
        "For price-domain dislocations, ATR-normalization does not fully remove "
        f"the depth/ATR linkage (mean |corr| {raw_abs:.3f} -> {norm_abs:.3f}). "
        "P1 should treat volatility control as mandatory, not optional."
    )


def _build_report(
    *,
    df: pd.DataFrame,
    confound: pd.DataFrame,
    choices: dict[str, Any],
    pairs: list[str],
    counts: dict[tuple[str, str], int],
) -> str:
    lines = [
        "# P0 Depth Distribution",
        "",
        "## Method",
        (
            f"Extracted fresh fires for {len(EVALUATORS)} dislocation-family evaluators "
            f"across {len(pairs)} deployed pairs using `co_fire.DIR_MASKERS`, "
            "`deployed_cells()`, and modal deployed params from `choose_params()`."
        ),
        (
            "Bars are closed H4 bars (`include_incomplete=False`). `entry_ATR` is ATR(14); "
            f"`ATR_percentile` is the rolling {ATR_PERCENTILE_WINDOW}-bar percentile rank. "
            "`ts` is the source H4 bar-open timestamp."
        ),
        (
            "For RSI, stochastic, and CCI, the plan defines depth in oscillator units; "
            "`atr_norm_depth` therefore equals the oscillator-unit depth for P0 reporting."
        ),
        "",
        "## Parameter Choices",
    ]
    for evaluator in EVALUATORS:
        lines.append(f"- {evaluator}: `{json.dumps(choices[evaluator].params, sort_keys=True)}`")
    lines.extend(["", "## Count Sanity"])
    for evaluator in EVALUATORS:
        long_count = counts[(evaluator, "long")]
        short_count = counts[(evaluator, "short")]
        lines.append(f"- {evaluator}: long={long_count:,}, short={short_count:,}")
    lines.extend([""])
    lines.extend(_distribution_lines(df))
    lines.extend([""])
    lines.extend(_confound_lines(confound))
    lines.extend(["", "## Verdict", _verdict(confound), ""])
    return "\n".join(lines)


def run() -> tuple[pd.DataFrame, str]:
    cells = deployed_cells()
    pairs = sorted({cell.pair for cell in cells})
    choices = choose_params(cells)
    modes = _entry_modes(cells)
    expected = _expected_solo_counts()

    all_rows: list[dict[str, object]] = []
    counts = {(evaluator, direction): 0 for evaluator in EVALUATORS for direction in DIRECTIONS}
    with FxStore(read_only=True) as store:
        for pair in pairs:
            raw = store.load(pair, granularity="H4", include_incomplete=False)
            if raw.empty:
                raise RuntimeError(f"no complete H4 bars for {pair}")
            mid = ohlc_mid(raw)
            entry_atr = atr(mid, period=ATR_PERIOD)
            atr_percentile = _rolling_percentile(entry_atr, ATR_PERCENTILE_WINDOW)
            for evaluator in EVALUATORS:
                rows, pair_counts = _fire_rows(
                    pair=pair,
                    evaluator=evaluator,
                    entry_mode=modes[evaluator],
                    mid=mid,
                    timestamps=raw["timestamp"],
                    params=choices[evaluator].params,
                    entry_atr=entry_atr,
                    atr_percentile=atr_percentile,
                )
                all_rows.extend(rows)
                for direction, count in pair_counts.items():
                    counts[(evaluator, direction)] += count

    mismatches = {
        key: {"actual": counts[key], "expected": expected[key]}
        for key in sorted(expected)
        if counts[key] != expected[key]
    }
    if mismatches:
        raise RuntimeError(f"solo fresh-fire count mismatch: {mismatches}")

    df = pd.DataFrame(all_rows).sort_values(["evaluator", "pair", "direction", "ts"])
    df.to_csv(FIRES_PATH, index=False)
    confound = _confound_frame(df)
    report = _build_report(
        df=df,
        confound=confound,
        choices=choices,
        pairs=pairs,
        counts=counts,
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    return df, report


def main() -> None:
    df, _ = run()
    print(f"wrote {len(df):,} fires -> {FIRES_PATH}")
    print(f"wrote report -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
