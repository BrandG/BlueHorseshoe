"""P1a strict-AND confluence expectancy sweep.

This is the narrowed raw-expectancy gate from CONFLUENCE_SWEEP_v1 §13. It
tests macd-crossed candidates plus redundancy controls, using P0 modal params
and direction-aware fresh fire masks. P1b rigor is intentionally out of scope.
"""
# pylint: disable=wrong-import-position,wrong-import-order,import-error
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-locals
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "research" / "v2_executable_regate" / "harness"))

from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators import ohlc_mid  # noqa: E402
from co_fire import DIR_MASKERS  # noqa: E402
from factor_grouping import EVALUATORS, choose_params, deployed_cells  # noqa: E402
from _lib import (  # noqa: E402
    MAX_HOLD,
    STOP_PCT,
    TP_PCT,
    sim_long_limit,
    sim_long_mid,
    sim_short_limit,
    sim_short_mid,
)

OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "p1a_results.csv"
REPORT_PATH = OUT_DIR / "CONFLUENCE_P1A.md"
OUT_PATH = OUT_DIR / "p1a_sweep.out"

EVAL_PAIRS = (
    ("macd", "stoch"),
    ("macd", "rsi"),
    ("macd", "cci"),
    ("bb", "ema"),
    ("stoch", "rsi"),
    ("stoch", "atr"),
)
CANDIDATES = frozenset({("macd", "stoch"), ("macd", "rsi"), ("macd", "cci")})
DIRECTIONS = ("long", "short")
ENTRY_MODES = ("mid", "limit")
CELLS = ("A_all", "B_all", "A_pure", "B_pure", "BOTH")
N_FLOOR = 40


@dataclass(frozen=True)
class TradeSample:
    """A realized R sample for one test cell."""

    values: tuple[float, ...]

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        if not self.values:
            return float("nan")
        return float(np.mean(self.values))

    @property
    def se(self) -> float:
        if len(self.values) <= 1:
            return float("nan")
        return float(np.std(self.values, ddof=1) / np.sqrt(len(self.values)))

    @property
    def ci_low(self) -> float:
        if self.n == 0:
            return float("nan")
        se = 0.0 if self.n == 1 else self.se
        return self.mean - 1.96 * se


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


def _simulate_cell(
    mid: pd.DataFrame,
    mask: np.ndarray,
    *,
    direction: str,
    entry_mode: str,
) -> TradeSample:
    close = mid["close"].to_numpy(float)
    high = mid["high"].to_numpy(float)
    low = mid["low"].to_numpy(float)
    sim = _simulator(direction, entry_mode)
    values = []
    for idx in np.flatnonzero(mask):
        r_value, _ = sim(close, high, low, int(idx), MAX_HOLD)
        if r_value is not None:
            values.append(float(r_value))
    return TradeSample(tuple(values))


def _cell_masks(mask_a: np.ndarray, mask_b: np.ndarray) -> dict[str, np.ndarray]:
    return {
        "A_all": mask_a,
        "B_all": mask_b,
        "A_pure": mask_a & ~mask_b,
        "B_pure": mask_b & ~mask_a,
        "BOTH": mask_a & mask_b,
    }


def _gate(samples: dict[str, TradeSample], *, n_floor: int = N_FLOOR) -> dict[str, object]:
    both = samples["BOTH"]
    component_best = max(samples["A_all"].mean, samples["B_all"].mean)
    positive_ci = bool(both.n >= n_floor and both.ci_low > 0.0)
    beats_components = bool(both.mean > component_best)
    return {
        "eligible": both.n >= n_floor,
        "positive_ci": positive_ci,
        "beats_components": beats_components,
        "passes": positive_ci and beats_components,
        "component_best": component_best,
    }


def _record_rows(
    rows: list[dict[str, object]],
    *,
    eval_pair: tuple[str, str],
    level: str,
    forex_pair: str,
    direction: str,
    entry_mode: str,
    samples: dict[str, TradeSample],
) -> None:
    gate = _gate(samples)
    for cell in CELLS:
        sample = samples[cell]
        rows.append({
            "evaluator_pair": f"{eval_pair[0]}+{eval_pair[1]}",
            "a": eval_pair[0],
            "b": eval_pair[1],
            "level": level,
            "forex_pair": forex_pair,
            "direction": direction,
            "entry_mode": entry_mode,
            "cell": cell,
            "n": sample.n,
            "mean_R": sample.mean,
            "SE": sample.se,
            "CI_low": sample.ci_low,
            "both_n": samples["BOTH"].n,
            "eligible": gate["eligible"],
            "positive_ci": gate["positive_ci"] if cell == "BOTH" else "",
            "beats_components": gate["beats_components"] if cell == "BOTH" else "",
            "passes_p1a": gate["passes"] if cell == "BOTH" else "",
            "component_best_mean_R": gate["component_best"] if cell == "BOTH" else "",
        })


def _pooled_samples(
    accumulator: dict[tuple[str, str, str, str], list[float]],
    eval_pair: tuple[str, str],
    direction: str,
    entry_mode: str,
) -> dict[str, TradeSample]:
    return {
        cell: TradeSample(tuple(accumulator[(f"{eval_pair[0]}+{eval_pair[1]}", direction, entry_mode, cell)]))
        for cell in CELLS
    }


def _format_float(value: float) -> str:
    if np.isnan(value):
        return "nan"
    return f"{value:.4f}"


def _gate_table(df: pd.DataFrame, *, level: str, candidates_only: bool = False) -> list[str]:
    both = df[(df["level"] == level) & (df["cell"] == "BOTH")].copy()
    if candidates_only:
        both = both[both["evaluator_pair"].isin({f"{a}+{b}" for a, b in CANDIDATES})]
    if level == "POOLED":
        sort_cols = ["evaluator_pair", "direction", "entry_mode"]
    else:
        sort_cols = ["evaluator_pair", "forex_pair", "direction", "entry_mode"]
    both = both.sort_values(sort_cols)
    lines = [
        "| evaluator_pair | scope | direction | entry | n | mean_R | CI_low | component_best | pass |",
        "|---|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for row in both.itertuples(index=False):
        scope = row.forex_pair if level == "PAIR" else "POOLED"
        lines.append(
            f"| {row.evaluator_pair} | {scope} | {row.direction} | {row.entry_mode} "
            f"| {int(row.n)} | {_format_float(row.mean_R)} | {_format_float(row.CI_low)} "
            f"| {_format_float(float(row.component_best_mean_R))} | {bool(row.passes_p1a)} |"
        )
    return lines


def _component_table(df: pd.DataFrame) -> list[str]:
    pooled = df[(df["level"] == "POOLED")].copy()
    pivot = pooled.pivot_table(
        index=["evaluator_pair", "direction", "entry_mode"],
        columns="cell",
        values="mean_R",
        aggfunc="first",
    ).reset_index()
    pivot = pivot.sort_values(["evaluator_pair", "direction", "entry_mode"])
    lines = [
        "| evaluator_pair | direction | entry | A_all | B_all | A_pure | B_pure | BOTH |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in pivot.itertuples(index=False):
        lines.append(
            f"| {row.evaluator_pair} | {row.direction} | {row.entry_mode} "
            f"| {_format_float(row.A_all)} | {_format_float(row.B_all)} "
            f"| {_format_float(row.A_pure)} | {_format_float(row.B_pure)} "
            f"| {_format_float(row.BOTH)} |"
        )
    return lines


def _verdict_lines(df: pd.DataFrame) -> list[str]:
    lines = []
    both = df[df["cell"] == "BOTH"].copy()
    survivors = both[both["passes_p1a"].astype(bool)]
    candidate_names = [f"{a}+{b}" for a, b in EVAL_PAIRS]
    for name in candidate_names:
        sub = survivors[survivors["evaluator_pair"] == name]
        kind = "candidate" if tuple(name.split("+")) in CANDIDATES else "control"
        if sub.empty:
            lines.append(f"- {name} ({kind}): no BOTH cell cleared both P1a gates.")
            continue
        scopes = []
        for row in sub.sort_values(["level", "forex_pair", "direction", "entry_mode"]).itertuples(index=False):
            scopes.append(f"{row.level}/{row.forex_pair}/{row.direction}/{row.entry_mode}")
        lines.append(f"- {name} ({kind}): SURVIVES P1a in {', '.join(scopes)}.")
    candidate_survivors = survivors[survivors["evaluator_pair"].isin({f"{a}+{b}" for a, b in CANDIDATES})]
    pooled_candidate_survivors = candidate_survivors[candidate_survivors["level"] == "POOLED"]
    lines.append("")
    if pooled_candidate_survivors.empty:
        lines.append("Primary pooled candidate verdict: no macd-crossed BOTH cell clears both P1a gates.")
    else:
        names = ", ".join(
            f"{row.evaluator_pair}/{row.direction}/{row.entry_mode}"
            for row in pooled_candidate_survivors.sort_values(
                ["evaluator_pair", "direction", "entry_mode"]
            ).itertuples(index=False)
        )
        lines.append(f"Primary pooled candidate verdict: SURVIVORS: {names}.")
    if candidate_survivors.empty:
        lines.append(
            "No candidate macd-crossed BOTH cell survived P1a. Recommendation: skip P1b "
            "and route next work to soft/voting confluence or relative-value."
        )
    else:
        lines.append("P1b candidate set from all raw P1a survivors, including eligible per-pair cells:")
        for row in candidate_survivors.sort_values(["level", "evaluator_pair", "forex_pair", "direction", "entry_mode"]).itertuples(index=False):
            lines.append(
                f"- {row.evaluator_pair} {row.level}/{row.forex_pair} "
                f"{row.direction} {row.entry_mode}: n={int(row.n)}, "
                f"mean_R={_format_float(row.mean_R)}, CI_low={_format_float(row.CI_low)}"
            )
    return lines


def _write_report(df: pd.DataFrame, pairs: list[str], choices: dict[str, object]) -> str:
    lines = [
        "# Confluence P1a",
        "",
        "## Method",
        (
            "Ran the narrowed strict-AND P1a sweep on the 17 deployed forex pairs from "
            "`factor_grouping.deployed_cells()`, using modal-deployed evaluator params from "
            "`factor_grouping.choose_params()` and direction-aware fresh fire masks from "
            "`co_fire.DIR_MASKERS`."
        ),
        "",
        (
            f"Simulation uses raw mid-price fills only: `sim_*_mid` and `sim_*_limit` from "
            f"`research/v2_executable_regate/harness/_lib.py`, with TP_PCT={TP_PCT:.2%}, "
            f"STOP_PCT={STOP_PCT:.2%}, and one fixed `MAX_HOLD={MAX_HOLD}` bars for every "
            "BOTH and control cell. Source: v2 ledger harness "
            "`research/v2_executable_regate/harness/_lib.py`; the seed regate scripts also "
            "document this as the deployed ledger geometry."
        ),
        "",
        f"Pairs: {', '.join(pairs)}.",
        "",
        "## Modal Params",
    ]
    for evaluator in EVALUATORS:
        if evaluator in choices:
            lines.append(f"- {evaluator}: `{choices[evaluator].params}` ({choices[evaluator].note})")
    lines.extend([
        "",
        "## Verdict",
        *_verdict_lines(df),
        "",
        "## Pooled BOTH Gates",
        *_gate_table(df, level="POOLED"),
        "",
        "## Pooled Attribution",
        *_component_table(df),
        "",
        "## Eligible Per-Pair BOTH Gates",
    ])
    pair_both = df[
        (df["level"] == "PAIR")
        & (df["cell"] == "BOTH")
        & (df["eligible"].astype(bool))
    ]
    if pair_both.empty:
        lines.append("No per-pair BOTH cells had realized n >= 40.")
    else:
        lines.extend(_gate_table(df[df["eligible"].astype(bool)], level="PAIR"))
    control = df[
        (df["level"] == "POOLED")
        & (df["evaluator_pair"] == "stoch+rsi")
        & (df["cell"] == "BOTH")
    ].sort_values(["direction", "entry_mode"])
    lines.extend(["", "## Control Sanity", ""])
    for row in control.itertuples(index=False):
        lift = float(row.mean_R) - float(row.component_best_mean_R)
        lines.append(
            f"- stoch+rsi {row.direction} {row.entry_mode}: BOTH mean_R="
            f"{_format_float(row.mean_R)}, best component="
            f"{_format_float(float(row.component_best_mean_R))}, lift={_format_float(lift)}."
        )
    lines.extend([
        "",
        "## Artifacts",
        f"- `{RESULTS_PATH.name}`: one row per evaluator-pair/level/pair/direction/entry/cell.",
        f"- `{OUT_PATH.name}`: console summary from the sweep run.",
    ])
    report = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report, encoding="utf-8")
    return report


def run() -> tuple[pd.DataFrame, str]:
    cells = deployed_cells()
    pairs = sorted({cell.pair for cell in cells})
    choices = choose_params(cells)

    missing = sorted({e for pair in EVAL_PAIRS for e in pair} - set(EVALUATORS))
    if missing:
        raise RuntimeError(f"unknown evaluators: {missing}")

    rows: list[dict[str, object]] = []
    pooled: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)

    with FxStore(read_only=True) as store:
        for forex_pair in pairs:
            mid = ohlc_mid(store.load(forex_pair, granularity="H4", include_incomplete=False))
            masks_by_eval = {}
            for evaluator in sorted({e for pair in EVAL_PAIRS for e in pair}):
                long_mask, short_mask = DIR_MASKERS[evaluator](mid, choices[evaluator].params)
                masks_by_eval[evaluator] = {
                    "long": long_mask.astype(bool),
                    "short": short_mask.astype(bool),
                }

            for eval_pair in EVAL_PAIRS:
                pair_name = f"{eval_pair[0]}+{eval_pair[1]}"
                for direction in DIRECTIONS:
                    cell_masks = _cell_masks(
                        masks_by_eval[eval_pair[0]][direction],
                        masks_by_eval[eval_pair[1]][direction],
                    )
                    for entry_mode in ENTRY_MODES:
                        samples = {
                            cell: _simulate_cell(
                                mid,
                                mask,
                                direction=direction,
                                entry_mode=entry_mode,
                            )
                            for cell, mask in cell_masks.items()
                        }
                        _record_rows(
                            rows,
                            eval_pair=eval_pair,
                            level="PAIR",
                            forex_pair=forex_pair,
                            direction=direction,
                            entry_mode=entry_mode,
                            samples=samples,
                        )
                        for cell, sample in samples.items():
                            pooled[(pair_name, direction, entry_mode, cell)].extend(sample.values)

    for eval_pair in EVAL_PAIRS:
        for direction in DIRECTIONS:
            for entry_mode in ENTRY_MODES:
                samples = _pooled_samples(pooled, eval_pair, direction, entry_mode)
                _record_rows(
                    rows,
                    eval_pair=eval_pair,
                    level="POOLED",
                    forex_pair="POOLED",
                    direction=direction,
                    entry_mode=entry_mode,
                    samples=samples,
                )

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_PATH, index=False)
    report = _write_report(df, pairs, choices)
    return df, report


def main() -> None:
    df, _ = run()
    both = df[(df["cell"] == "BOTH") & (df["level"] == "POOLED")].copy()
    passes = both[both["passes_p1a"].astype(bool)]
    lines = [
        "==== CONFLUENCE P1A STRICT-AND SWEEP ====",
        f"results -> {RESULTS_PATH}",
        f"report  -> {REPORT_PATH}",
        f"rows={len(df)} pooled_both_rows={len(both)} pooled_survivors={len(passes)}",
    ]
    if passes.empty:
        lines.append("pooled survivors: none")
    else:
        lines.append("pooled survivors:")
        for row in passes.sort_values(["evaluator_pair", "direction", "entry_mode"]).itertuples(index=False):
            lines.append(
                f"  {row.evaluator_pair} {row.direction} {row.entry_mode}: "
                f"n={int(row.n)} mean_R={_format_float(row.mean_R)} "
                f"CI_low={_format_float(row.CI_low)}"
            )
    console = "\n".join(lines)
    OUT_PATH.write_text(console + "\n", encoding="utf-8")
    print(console)


if __name__ == "__main__":
    main()
