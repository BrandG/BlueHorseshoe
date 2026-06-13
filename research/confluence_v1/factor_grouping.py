"""Phase 0 evaluator factor grouping for BUD H4 forex v2 cells.

This is a fire-mask correlation pass, not a backtest. It uses the deployed v2
cell universe, selects one deployed parameter set per evaluator, computes a
side-agnostic fire mask on each closed H4 bar for every deployed pair, and
clusters evaluators whose pooled fire-mask correlation exceeds a tunable
threshold.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bud.auto_trader import deploy_predicate
from bud.briefing import CELLS, Cell, _EVALUATORS, ranked_cells
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import (
    atr,
    bollinger_bands,
    cci,
    ema,
    ichimoku,
    is_bullish_engulfing,
    macd,
    ohlc_mid,
    rsi,
    sma,
    stochastic,
)

# pylint: disable=too-many-locals,too-many-arguments

OUT_DIR = Path(__file__).resolve().parent
MATRIX_PATH = OUT_DIR / "factor_grouping.csv"
PAIR_RANGE_PATH = OUT_DIR / "factor_grouping_pair_ranges.csv"
OUT_PATH = OUT_DIR / "factor_grouping.out"
REPORT_PATH = OUT_DIR / "P0_FACTOR_GROUPING.md"

THRESHOLD = 0.50
EVALUATORS = tuple(_EVALUATORS.keys())
DISLOCATION_FAMILY = frozenset({"bb", "cci", "ema", "rsi", "sma", "stoch"})


@dataclass(frozen=True)
class ParamChoice:
    """Selected parameter set and provenance for one evaluator."""

    params: dict[str, Any]
    count: int
    total: int
    note: str


def _params_key(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def deployed_cells() -> list[Cell]:
    """Return cells selected by the live deploy predicate."""

    return [cell for cell in ranked_cells() if deploy_predicate(cell)]


def choose_params(cells: list[Cell]) -> dict[str, ParamChoice]:
    """Pick the modal deployed params for each evaluator.

    Several evaluators have tied deployed parameter sets. In ties, the existing
    ranked-cell order is used as the deterministic tiebreaker so the chosen set
    comes from the strongest currently deployed cell among the tied modes.
    """
    by_strategy: dict[str, list[Cell]] = defaultdict(list)
    fallback_cells = ranked_cells(CELLS)
    rank_pos = {id(cell): pos for pos, cell in enumerate(fallback_cells)}
    for cell in cells:
        by_strategy[cell.strategy].append(cell)

    choices: dict[str, ParamChoice] = {}
    for strategy in EVALUATORS:
        source = "deploy_predicate"
        strategy_cells = by_strategy[strategy]
        if not strategy_cells:
            strategy_cells = [cell for cell in fallback_cells if cell.strategy == strategy]
            source = "briefing.CELLS fallback"
        if not strategy_cells:
            raise RuntimeError(f"no cells available for evaluator params: {strategy}")
        counts = Counter(_params_key(cell.params) for cell in strategy_cells)
        best_count = max(counts.values())
        tied = {key for key, count in counts.items() if count == best_count}
        selected = min(
            (cell for cell in strategy_cells if _params_key(cell.params) in tied),
            key=lambda cell: rank_pos[id(cell)],
        )
        total_sets = len(counts)
        if source != "deploy_predicate":
            note = (
                "single briefing.CELLS param set; evaluator is in _EVALUATORS but "
                "not selected by deploy_predicate"
            )
        elif total_sets == 1:
            note = "only deployed param set"
        elif len(tied) == 1:
            note = f"modal deployed param set ({best_count}/{len(strategy_cells)} cells)"
        else:
            note = (
                f"tied modal deployed param set ({best_count}/{len(strategy_cells)} cells); "
                "ranked-cell order broke tie"
            )
        choices[strategy] = ParamChoice(
            params=dict(selected.params),
            count=best_count,
            total=total_sets,
            note=note,
        )
    return choices


def _fresh_mask(cond: np.ndarray) -> np.ndarray:
    cond = np.nan_to_num(cond.astype(bool), nan=False)
    out = np.zeros(len(cond), dtype=bool)
    if len(cond) > 1:
        out[1:] = cond[1:] & ~cond[:-1]
    return out


def _osc_recovery_mask(
    arr: np.ndarray,
    *,
    threshold: float,
    recovery: int,
    signed: bool,
) -> np.ndarray:
    n = len(arr)
    long_cond = np.zeros(n, dtype=bool)
    short_cond = np.zeros(n, dtype=bool)
    if n < recovery + 2:
        return long_cond

    if signed:
        long_base, short_base = -threshold, threshold
    else:
        long_base, short_base = threshold, 100.0 - threshold

    finite = np.isfinite(arr)
    for idx in range(recovery, n):
        if not finite[idx] or not finite[idx - recovery]:
            continue
        long_consec = all(arr[idx - i] > arr[idx - i - 1] for i in range(recovery))
        short_consec = all(arr[idx - i] < arr[idx - i - 1] for i in range(recovery))
        long_cond[idx] = long_consec and arr[idx - recovery] < long_base
        short_cond[idx] = short_consec and arr[idx - recovery] > short_base
    return _fresh_mask(long_cond) | _fresh_mask(short_cond)


def _stoch_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    stoch = stochastic(mid, k_period=params["k_period"], d_period=params["d_period"])
    return _osc_recovery_mask(
        stoch["k"].to_numpy(dtype=float),
        threshold=float(params["threshold"]),
        recovery=int(params["recovery"]),
        signed=False,
    )


def _rsi_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    return _osc_recovery_mask(
        rsi(mid, period=params["period"]).to_numpy(dtype=float),
        threshold=float(params["threshold"]),
        recovery=int(params["recovery"]),
        signed=False,
    )


def _cci_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    return _osc_recovery_mask(
        cci(mid, period=params["period"]).to_numpy(dtype=float),
        threshold=float(params["threshold"]),
        recovery=int(params["recovery"]),
        signed=True,
    )


def _bb_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    bands = bollinger_bands(mid, period=params["period"], n_std=params["n_std"])
    close = mid["close"].to_numpy(dtype=float)
    lower = bands["lower"].to_numpy(dtype=float)
    upper = bands["upper"].to_numpy(dtype=float)
    width = upper - lower
    depth = float(params["depth"])
    long_cond = close < (lower - depth * width)
    short_cond = close > (upper + depth * width)
    return _fresh_mask(long_cond) | _fresh_mask(short_cond)


def _macd_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    frame = macd(mid, fast=params["fast"], slow=params["slow"], signal=params["signal"])
    macd_arr = frame["macd"].to_numpy(dtype=float)
    signal_arr = frame["signal"].to_numpy(dtype=float)
    trigger = params["trigger"]
    if trigger == "signal_cross":
        long_cond = macd_arr > signal_arr
        short_cond = macd_arr < signal_arr
    elif trigger == "zero_cross":
        long_cond = macd_arr > 0.0
        short_cond = macd_arr < 0.0
    else:
        raise ValueError(f"unsupported MACD trigger: {trigger}")
    return _fresh_mask(long_cond) | _fresh_mask(short_cond)


def _ma_distance_mask(mid: pd.DataFrame, params: dict[str, Any], ma_fn) -> np.ndarray:
    ma_arr = ma_fn(mid, period=params["period"]).to_numpy(dtype=float)
    atr_arr = atr(mid, period=params["atr_period"]).to_numpy(dtype=float)
    close = mid["close"].to_numpy(dtype=float)
    band = float(params["k"]) * atr_arr
    long_cond = close < ma_arr - band
    short_cond = close > ma_arr + band
    return _fresh_mask(long_cond) | _fresh_mask(short_cond)


def _sma_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    return _ma_distance_mask(mid, params, sma)


def _ema_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    return _ma_distance_mask(mid, params, ema)


def _atr_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    open_arr = mid["open"].to_numpy(dtype=float)
    high = mid["high"].to_numpy(dtype=float)
    low = mid["low"].to_numpy(dtype=float)
    close = mid["close"].to_numpy(dtype=float)
    trigger = params["trigger"]
    k = float(params["k"])

    if trigger == "close_breakout":
        atr_arr = atr(mid, period=params["atr_period"]).to_numpy(dtype=float)
        long_cond = close > np.roll(close, 1) + k * np.roll(atr_arr, 1)
        short_cond = close < np.roll(close, 1) - k * np.roll(atr_arr, 1)
        long_cond[0] = False
        short_cond[0] = False
        return _fresh_mask(long_cond) | _fresh_mask(short_cond)

    if trigger != "range_expansion":
        raise ValueError(f"unsupported ATR trigger: {trigger}")
    lookback = int(params.get("range_lookback", 14))
    rng = high - low
    mean_rng = pd.Series(rng).rolling(lookback, min_periods=lookback).mean().to_numpy()
    prior_mean = np.roll(mean_rng, 1)
    prior_mean[0] = np.nan
    big_bar = rng > k * prior_mean
    long_cond = big_bar & (close > open_arr)
    short_cond = big_bar & (close < open_arr)
    return _fresh_mask(long_cond) | _fresh_mask(short_cond)


def _ichimoku_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    frame = ichimoku(
        mid,
        tenkan_period=params["tenkan"],
        kijun_period=params["kijun"],
        senkou_b_period=params["senkou_b"],
        displacement=params["displacement"],
    )
    if params["trigger"] != "tk_cross":
        raise ValueError(f"unsupported Ichimoku trigger: {params['trigger']}")
    tenkan = frame["tenkan"].to_numpy(dtype=float)
    kijun = frame["kijun"].to_numpy(dtype=float)
    long_cond = tenkan > kijun
    short_cond = tenkan < kijun
    return _fresh_mask(long_cond) | _fresh_mask(short_cond)


def _candle_mask(mid: pd.DataFrame, params: dict[str, Any]) -> np.ndarray:
    if params["pattern"] != "bull_engulf":
        raise ValueError(f"unsupported candle pattern: {params['pattern']}")
    kwargs = {"min_body_frac": 0.5} if bool(params.get("strict", False)) else {}
    return is_bullish_engulfing(mid, **kwargs).to_numpy(dtype=bool)


MASKERS = {
    "atr": _atr_mask,
    "bb": _bb_mask,
    "candle": _candle_mask,
    "cci": _cci_mask,
    "ema": _ema_mask,
    "ichimoku": _ichimoku_mask,
    "macd": _macd_mask,
    "rsi": _rsi_mask,
    "sma": _sma_mask,
    "stoch": _stoch_mask,
}


def _corr(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) != len(y):
        raise ValueError("correlation arrays must have matching length")
    if len(x) < 2 or np.std(x) == 0.0 or np.std(y) == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def compute_masks(
    pairs: list[str],
    choices: dict[str, ParamChoice],
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, int]]:
    """Load complete H4 bars and compute evaluator masks for each pair."""

    masks_by_pair: dict[str, dict[str, np.ndarray]] = {}
    rows_by_pair: dict[str, int] = {}
    with FxStore(read_only=True) as store:
        for pair in pairs:
            raw = store.load(pair, granularity="H4", include_incomplete=False)
            if raw.empty:
                raise RuntimeError(f"no complete H4 bars for {pair}")
            mid = ohlc_mid(raw)
            rows_by_pair[pair] = len(mid)
            masks_by_pair[pair] = {
                name: MASKERS[name](mid, choices[name].params).astype(bool)
                for name in EVALUATORS
            }
    return masks_by_pair, rows_by_pair


def pooled_matrix(
    masks_by_pair: dict[str, dict[str, np.ndarray]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return pooled evaluator correlations and per-pair correlation ranges."""

    matrix = pd.DataFrame(np.eye(len(EVALUATORS)), index=EVALUATORS, columns=EVALUATORS)
    ranges = []
    for left, right in combinations(EVALUATORS, 2):
        pooled_left = np.concatenate([masks[left].astype(float) for masks in masks_by_pair.values()])
        pooled_right = np.concatenate([masks[right].astype(float) for masks in masks_by_pair.values()])
        pooled = _corr(pooled_left, pooled_right)
        matrix.loc[left, right] = pooled
        matrix.loc[right, left] = pooled

        per_pair = {
            pair: _corr(masks[left].astype(float), masks[right].astype(float))
            for pair, masks in masks_by_pair.items()
        }
        vals = [val for val in per_pair.values() if np.isfinite(val)]
        ranges.append({
            "left": left,
            "right": right,
            "pooled_corr": pooled,
            "per_pair_min": min(vals) if vals else np.nan,
            "per_pair_max": max(vals) if vals else np.nan,
            "per_pair_finite_n": len(vals),
        })
    return matrix, pd.DataFrame(ranges)


def clusters_from_matrix(matrix: pd.DataFrame, threshold: float) -> list[list[str]]:
    """Build connected components from correlations above ``threshold``."""

    parent = {name: name for name in matrix.index}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_left] = root_right

    for left, right in combinations(matrix.index, 2):
        value = matrix.loc[left, right]
        if pd.notna(value) and abs(float(value)) >= threshold:
            union(left, right)

    clusters: dict[str, list[str]] = defaultdict(list)
    for name in matrix.index:
        clusters[find(name)].append(name)
    return sorted((sorted(members) for members in clusters.values()), key=lambda x: (-len(x), x))


def _cluster_id(name: str, clusters: list[list[str]]) -> str:
    for idx, members in enumerate(clusters, start=1):
        if name in members:
            return f"C{idx}"
    raise KeyError(name)


def _format_pairs(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"- {left} + {right}" for left, right in pairs)


def build_report(
    *,
    cells: list[Cell],
    pairs: list[str],
    rows_by_pair: dict[str, int],
    choices: dict[str, ParamChoice],
    matrix: pd.DataFrame,
    ranges: pd.DataFrame,
    clusters: list[list[str]],
) -> str:
    """Build the markdown P0 result report."""

    all_pairs = list(combinations(EVALUATORS, 2))
    cross_cluster = [
        pair for pair in all_pairs
        if _cluster_id(pair[0], clusters) != _cluster_id(pair[1], clusters)
    ]
    redundant = [pair for pair in all_pairs if pair not in cross_cluster]

    stoch_corrs = matrix.loc["stoch"].drop("stoch").astype(float)
    stoch_neighbor = stoch_corrs.abs().sort_values(ascending=False).index[0]
    stoch_value = matrix.loc["stoch", stoch_neighbor]
    stoch_family_ok = stoch_neighbor in DISLOCATION_FAMILY

    lines = [
        "# P0 Factor Grouping",
        "",
        "## Objective",
        (
            "Determine which deployed v2 evaluator families are orthogonal on H4 forex "
            "before any P1 confluence sweep."
        ),
        "",
        "## Method",
        (
            f"Used {len(cells)} deployed cells across {len(pairs)} deployed pairs. "
            "For each evaluator, selected one deployed parameter set by modal frequency; "
            "ties use existing ranked-cell order as the deterministic tiebreaker. "
            "Fire masks are side-agnostic (`long OR short`) and evaluated on closed H4 "
            "bars only, matching the trigger-bar convention in `evaluate_cell`."
        ),
        "",
        "## Parameter Choices",
    ]
    for name in EVALUATORS:
        choice = choices[name]
        lines.append(
            f"- {name}: `{json.dumps(choice.params, sort_keys=True)}` "
            f"({choice.note}; {choice.total} deployed param set(s))"
        )

    lines.extend([
        "",
        "## Data Coverage",
    ])
    for pair in pairs:
        lines.append(f"- {pair}: {rows_by_pair[pair]:,} closed H4 bars")

    lines.extend([
        "",
        "## Cluster Map",
        f"Threshold: `abs(correlation) >= {THRESHOLD:.2f}`. Full matrix: `{MATRIX_PATH.name}`.",
    ])
    for idx, members in enumerate(clusters, start=1):
        tag = "redundant group" if len(members) > 1 else "standalone"
        lines.append(f"- C{idx} ({tag}): {', '.join(members)}")

    verdict = (
        f"{len(cross_cluster)} orthogonal cross-cluster evaluator pairs found; "
        "P1 is worth running only for those cross-cluster pairs."
        if cross_cluster
        else "All evaluators collapsed into one factor; confluence is likely dead before P1."
    )
    lines.extend([
        "",
        "## Verdict",
        verdict,
        (
            f"Evaluated all {len(all_pairs)} evaluator pairs. "
            f"{len(redundant)} are redundant-by-design at the current threshold."
        ),
        "",
        "## Cross-Cluster Shortlist For P1",
        _format_pairs(cross_cluster) if cross_cluster else "- None",
        "",
        "## Redundant By Design",
        _format_pairs(redundant) if redundant else "- None",
        "",
        "## Sanity Check",
        (
            f"Stoch nearest neighbor: `{stoch_neighbor}` "
            f"(corr={stoch_value:.3f}). "
            f"Dislocation-family check: {'passed' if stoch_family_ok else 'failed'}."
        ),
        "",
        "## Per-Pair Range Note",
        (
            f"Wrote `{PAIR_RANGE_PATH.name}` with pooled correlation plus per-pair min/max "
            "for every evaluator pair so the pooled average does not hide heterogeneity."
        ),
    ])

    top = ranges.assign(abs_corr=ranges["pooled_corr"].abs()).sort_values(
        "abs_corr", ascending=False,
    ).head(12)
    lines.extend(["", "## Top Absolute Correlations"])
    for row in top.itertuples(index=False):
        lines.append(
            f"- {row.left} + {row.right}: pooled={row.pooled_corr:.3f}, "
            f"per-pair range=[{row.per_pair_min:.3f}, {row.per_pair_max:.3f}]"
        )
    lines.append("")
    return "\n".join(lines)


def build_console_output(
    *,
    cells: list[Cell],
    pairs: list[str],
    matrix: pd.DataFrame,
    ranges: pd.DataFrame,
    clusters: list[list[str]],
) -> str:
    """Build stdout text and the captured ``.out`` body."""

    all_pairs = list(combinations(EVALUATORS, 2))
    cross_cluster = [
        pair for pair in all_pairs
        if _cluster_id(pair[0], clusters) != _cluster_id(pair[1], clusters)
    ]
    stoch_corrs = matrix.loc["stoch"].drop("stoch").astype(float)
    stoch_neighbor = stoch_corrs.abs().sort_values(ascending=False).index[0]
    stoch_value = matrix.loc["stoch", stoch_neighbor]

    lines = [
        "==== P0 FACTOR GROUPING ====",
        f"deployed cells: {len(cells)}",
        f"deployed pairs: {len(pairs)}",
        f"evaluator pairs evaluated: {len(all_pairs)}",
        f"threshold: abs(corr)>={THRESHOLD:.2f}",
        "",
        "clusters:",
    ]
    for idx, members in enumerate(clusters, start=1):
        lines.append(f"  C{idx}: {', '.join(members)}")
    lines.extend([
        "",
        f"cross-cluster shortlist: {len(cross_cluster)} evaluator pairs",
        f"redundant-by-design: {len(all_pairs) - len(cross_cluster)} evaluator pairs",
        f"stoch nearest neighbor: {stoch_neighbor} (corr={stoch_value:.3f})",
        "",
        "top absolute correlations:",
    ])
    top = ranges.assign(abs_corr=ranges["pooled_corr"].abs()).sort_values(
        "abs_corr", ascending=False,
    ).head(12)
    for row in top.itertuples(index=False):
        lines.append(
            f"  {row.left:9s} {row.right:9s} pooled={row.pooled_corr: .3f} "
            f"range=[{row.per_pair_min: .3f}, {row.per_pair_max: .3f}]"
        )
    lines.extend([
        "",
        f"saved matrix -> {MATRIX_PATH}",
        f"saved per-pair ranges -> {PAIR_RANGE_PATH}",
        f"saved report -> {REPORT_PATH}",
    ])
    return "\n".join(lines)


def main() -> None:
    """Run the factor grouping analysis and write all P0 artifacts."""

    cells = deployed_cells()
    pairs = sorted({cell.pair for cell in cells})
    choices = choose_params(cells)
    masks_by_pair, rows_by_pair = compute_masks(pairs, choices)
    matrix, ranges = pooled_matrix(masks_by_pair)
    clusters = clusters_from_matrix(matrix, THRESHOLD)

    matrix.round(6).to_csv(MATRIX_PATH)
    ranges.round(6).to_csv(PAIR_RANGE_PATH, index=False)
    report = build_report(
        cells=cells,
        pairs=pairs,
        rows_by_pair=rows_by_pair,
        choices=choices,
        matrix=matrix,
        ranges=ranges,
        clusters=clusters,
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    console = build_console_output(
        cells=cells,
        pairs=pairs,
        matrix=matrix,
        ranges=ranges,
        clusters=clusters,
    )
    OUT_PATH.write_text(console + "\n", encoding="utf-8")
    print(console)


if __name__ == "__main__":
    main()
