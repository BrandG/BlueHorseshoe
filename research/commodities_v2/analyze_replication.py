"""Build the FTMO commodity replication memo from regate outputs.

Research-only helper for the 12-instrument FTMO commodity extension. It reads
``regate_ftmo_full`` outputs, re-simulates the copper MA-distance neighborhood,
and writes ``REPLICATION.md`` plus two small supporting CSVs.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from run_commodities_v2 import (
    Cell,
    build_baseline_cells,
    ema,
    load_instruments,
    sma,
    summarize_with_baselines,
    _load_mid,
    _simulate_cell,
)
from bh_ftmo.data.fx_store import FxStore

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "research" / "commodities_v2"
REGATE_DIR = OUT_DIR / "regate_ftmo_full"
NEW_INSTRUMENTS = ["XPT_USD", "XPD_USD", "CORN_USD", "WHEAT_USD", "SOYBN_USD", "SUGAR_USD"]
MA_CELLS = ["ema50_dist_low", "sma50_dist_low"]
MA_PERIODS = [20, 50, 100, 200]
DIST_THRESHOLDS = [-0.005, -0.01, -0.02]
SPLITS = {
    "2016-2021": ("2016-01-01", "2021-01-01"),
    "2021-2026": ("2021-01-01", "2026-07-01"),
}


def _fmt(value: object, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    return f"{number:+.{digits}f}"


def _fmt_plain(value: object, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    return f"{number:.{digits}f}"


def _markdown_table(df: pd.DataFrame, columns: list[str], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines)


def _simulate_ma_neighborhood() -> tuple[pd.DataFrame, pd.DataFrame]:
    instruments = {item.symbol: item for item in load_instruments()}
    copper = instruments["XCU_USD"]
    store = FxStore(read_only=True)
    try:
        h4 = _load_mid(store, "XCU_USD", "H4")
    finally:
        store.close()

    cells: list[Cell] = []
    for entry_mode in ("market", "limit"):
        for ma_kind in ("sma", "ema"):
            for period in MA_PERIODS:
                for threshold in DIST_THRESHOLDS:
                    name = f"{ma_kind}{period}_dist_{threshold:.1%}"
                    if ma_kind == "sma":
                        signal_fn = lambda b, p=period, t=threshold: (b["close"] / sma(b, period=p) - 1.0) < t
                    else:
                        signal_fn = lambda b, p=period, t=threshold: (b["close"] / ema(b, period=p) - 1.0) < t
                    cells.append(Cell("mr_under_limit", name, "H4", entry_mode, 1, signal_fn))

    baseline_cells = [cell for cell in build_baseline_cells() if cell.timeframe == "H4" and cell.direction == 1]
    all_trades = []
    all_baselines = []
    for cell in cells:
        all_trades.extend(_simulate_cell(copper, h4, cell, None))
    for cell in baseline_cells:
        all_baselines.extend(_simulate_cell(copper, h4, cell, None))
    rows, _, _ = summarize_with_baselines(all_trades, all_baselines)
    neighborhood = pd.DataFrame(rows).sort_values(["entry_mode", "cell"])
    neighborhood.to_csv(OUT_DIR / "copper_ma_neighborhood.csv", index=False)

    split_rows = []
    h4_ts = pd.to_datetime(h4["timestamp"])
    for label, (start, end) in SPLITS.items():
        split_bars = h4[(h4_ts >= pd.Timestamp(start)) & (h4_ts < pd.Timestamp(end))].reset_index(drop=True)
        split_trades = []
        split_baselines = []
        for cell in cells:
            split_trades.extend(_simulate_cell(copper, split_bars, cell, None))
        for cell in baseline_cells:
            split_baselines.extend(_simulate_cell(copper, split_bars, cell, None))
        split_summary, _, _ = summarize_with_baselines(split_trades, split_baselines)
        for row in split_summary:
            row["split"] = label
            split_rows.append(row)
    split_df = pd.DataFrame(split_rows).sort_values(["cell", "entry_mode", "split"])
    split_df.to_csv(OUT_DIR / "copper_ma_split_half.csv", index=False)
    return neighborhood, split_df


def main() -> int:
    per_cell = pd.read_csv(REGATE_DIR / "per_cell_results.csv")
    baselines = pd.read_csv(REGATE_DIR / "baseline_results.csv")
    cost = pd.read_csv(REGATE_DIR / "cost_model.csv")
    sessions = pd.read_csv(REGATE_DIR / "session_profile.csv")
    validation = pd.read_csv(REGATE_DIR / "stored_validation.csv")
    neighborhood, split_df = _simulate_ma_neighborhood()

    ma = per_cell[
        (per_cell["cell"].isin(MA_CELLS))
        & (per_cell["timeframe"] == "H4")
        & (per_cell["direction"] == 1)
    ].copy()
    ma["ci"] = ma.apply(lambda r: f"[{_fmt(r['excess_ci_low'])}, {_fmt(r['excess_ci_high'])}]", axis=1)
    ma_table = ma.sort_values(["instrument", "cell", "entry_mode"])[
        ["instrument", "cell", "entry_mode", "n", "mean_r", "baseline_mean_r", "excess_r", "ci"]
    ].copy()
    for col in ["mean_r", "baseline_mean_r", "excess_r"]:
        ma_table[col] = ma_table[col].map(_fmt)

    survivors = per_cell[
        (per_cell["instrument"].isin(NEW_INSTRUMENTS))
        & (per_cell["mean_r"] > 0)
        & (per_cell["excess_ci_low"] > 0)
        & (per_cell["excess_r"] > 0)
    ].sort_values(["instrument", "excess_r"], ascending=[True, False]).copy()
    if not survivors.empty:
        survivors["ci"] = survivors.apply(lambda r: f"[{_fmt(r['excess_ci_low'])}, {_fmt(r['excess_ci_high'])}]", axis=1)
        for col in ["mean_r", "baseline_mean_r", "excess_r"]:
            survivors[col] = survivors[col].map(_fmt)

    baseline_new = baselines[baselines["instrument"].isin(NEW_INSTRUMENTS)].copy()
    baseline_new = baseline_new.sort_values(["instrument", "timeframe", "entry_mode", "direction"])
    for col in ["mean_r", "ci_low", "ci_high"]:
        baseline_new[col] = baseline_new[col].map(_fmt)
    baseline_new["ci"] = baseline_new.apply(lambda r: f"[{r['ci_low']}, {r['ci_high']}]", axis=1)

    best_neighborhood = neighborhood.sort_values("excess_r", ascending=False).head(12).copy()
    best_neighborhood["ma"] = best_neighborhood["cell"].str.extract(r"^(sma|ema)")
    best_neighborhood["period"] = best_neighborhood["cell"].str.extract(r"^(?:sma|ema)(\d+)").astype(int)
    best_neighborhood["threshold"] = best_neighborhood["cell"].str.extract(r"dist_(-?\d+\.\d%)")
    best_neighborhood["ci"] = best_neighborhood.apply(lambda r: f"[{_fmt(r['excess_ci_low'])}, {_fmt(r['excess_ci_high'])}]", axis=1)
    for col in ["mean_r", "baseline_mean_r", "excess_r"]:
        best_neighborhood[col] = best_neighborhood[col].map(_fmt)

    original_split = split_df[
        split_df["cell"].isin(["sma50_dist_-1.0%", "ema50_dist_-1.0%"])
    ].copy()
    original_split["ci"] = original_split.apply(lambda r: f"[{_fmt(r['excess_ci_low'])}, {_fmt(r['excess_ci_high'])}]", axis=1)
    for col in ["mean_r", "baseline_mean_r", "excess_r"]:
        original_split[col] = original_split[col].map(_fmt)

    session_new = sessions[sessions["instrument"].isin(NEW_INSTRUMENTS)].copy()
    validation_summary = validation.groupby(["instrument", "granularity", "issue_kind"], dropna=False)["issue_count"].sum().reset_index()
    cost_new = cost[cost["instrument"].isin(NEW_INSTRUMENTS)].copy()
    for col in ["median_h4_spread_r", "expected_swap_per_lot_day_abs"]:
        cost_new[col] = cost_new[col].map(_fmt_plain)

    lines = [
        "# FTMO Commodity Universe Replication",
        "",
        "Run date: 2026-06-13 UTC. Outputs: `research/commodities_v2/regate_ftmo_full/`.",
        "Geometry matches the regate harness: 1% stop / 1% target, 0.25x stop limit offset, 84 max hold bars, matched always-in baselines, and block-bootstrap excess CIs.",
        "",
        "## Verdict",
        "",
        "Copper MA-distance does not replicate across the new FTMO/OANDA commodity set. The original copper cells remain positive, but the strongest support is copper-local and weakens materially in the 2021-2026 half. I would not graduate it to tracking-only wiring yet; treat it as a research watch item pending a future out-of-sample update or a broader industrial-metals confirmation.",
        "",
        "The new six instruments do produce two CI-positive absolute-positive cells, but neither is MA-distance: wheat and sugar trigger on `atr_range_exp` H4 limit. That is not companion-shape evidence for copper, so the MA-distance family remains copper-local in this run.",
        "",
        "## MA-Distance Cross-Instrument Table",
        "",
        _markdown_table(ma_table, ["instrument", "cell", "entry_mode", "n", "mean_r", "baseline_mean_r", "excess_r", "ci"], ["instrument", "cell", "mode", "n", "mean R", "baseline", "excess", "excess CI"]),
        "",
        "Read: copper is still the cleanest original survivor. No new-instrument MA-distance row has both positive absolute R and CI-positive excess. Grains show a few positive but non-significant excess rows; PGMs are negative after their high spread costs.",
        "",
        "## Copper Parameter Neighborhood",
        "",
        "Top 12 XCU_USD H4 MA-distance neighborhood rows:",
        "",
        _markdown_table(best_neighborhood, ["ma", "period", "threshold", "entry_mode", "n", "mean_r", "baseline_mean_r", "excess_r", "ci"], ["MA", "period", "threshold", "mode", "n", "mean R", "baseline", "excess", "excess CI"]),
        "",
        "The edge is not a single exact spike at EMA50/-1%. Positive excess appears across several market-entry thresholds and periods, but CI-positive rows cluster most clearly around EMA50/SMA50 and market entry. Limit-entry absolute R is high because the matched limit baseline is also strong; excess is less stable there.",
        "",
        "## Copper Split-Half",
        "",
        _markdown_table(original_split, ["cell", "entry_mode", "split", "n", "mean_r", "baseline_mean_r", "excess_r", "ci"], ["cell", "mode", "split", "n", "mean R", "baseline", "excess", "excess CI"]),
        "",
        "The sign holds in both halves for the 50-period cells, and EMA50 limit barely clears a positive lower CI in 2021-2026. The broader issue is that most split-half lower CIs still cross zero and SMA50 weakens materially after 2021. This is a yellow flag against immediate graduation.",
        "",
        "## New-Six Full-Universe Survivors",
        "",
    ]
    if survivors.empty:
        lines.extend(["No new-six cells met positive absolute R plus CI-positive excess."])
    else:
        lines.append(_markdown_table(survivors, ["instrument", "family", "cell", "timeframe", "entry_mode", "direction", "n", "mean_r", "baseline_mean_r", "excess_r", "ci"], ["instrument", "family", "cell", "tf", "mode", "dir", "n", "mean R", "baseline", "excess", "excess CI"]))
    lines.extend([
        "",
        "## Always-In Baselines For New Instruments",
        "",
        _markdown_table(baseline_new, ["instrument", "timeframe", "entry_mode", "direction", "n", "mean_r", "ci"], ["instrument", "tf", "mode", "dir", "n", "mean R", "NW CI"]),
        "",
        "None of the new six is a gold-like runaway beta instrument. XPT/XPD baselines are strongly negative after their high spread costs. The ags' H4 limit baselines are near flat to mildly positive, while market baselines are materially negative after spread.",
        "",
        "## Session And Data Notes",
        "",
        "The onboarded OANDA candles validated cleanly during backfill, and the sweep's stored validator output is summarized below. The ags do not trade a metals/energy-style near-23h session, so NY-anchored commodity validation gaps on those instruments are calendar mismatch, not evidence of missing bars.",
        "",
        _markdown_table(validation_summary, ["instrument", "granularity", "issue_kind", "issue_count"], ["instrument", "granularity", "issue", "count"]),
        "",
        "Observed weekday-hour patterns for the six new instruments are in `regate_ftmo_full/session_profile.csv`; key point: XPT/XPD look like the metals session, CORN/WHEAT/SOYBN H1 trade mostly weekday 00-19/20 UTC, and SUGAR is shorter and irregular around 07-17 UTC plus sparse evening prints.",
        "",
        "Research cost metadata for the new six:",
        "",
        _markdown_table(cost_new, ["instrument", "ftmo", "oanda", "pip_size", "dollar_per_pip_per_lot", "median_h4_spread_r"], ["instrument", "FTMO", "OANDA", "pip", "$/pip/lot", "median H4 spread R"]),
        "",
        "Pip economics for PGMs and ags are placeholders for research only. The current sweep's R math is effectively pip-independent for spread and placeholder financing drag; verify FTMO contract economics before any wiring. FTMO-tradeable coffee, cocoa, cotton, and heating oil remain out of scope here because OANDA does not serve these candles.",
        "",
        "Harness caveats retained: `bars_per_day = 6` overstates ag H4 bar density, mildly understating hold-days/financing drag, and `max_hold_bars = 84` spans more calendar days on shorter-session instruments. These do not change spread costs or excess-vs-baseline comparisons.",
        "",
        "## Cell Design Decision",
        "",
        "Do not wire a tracking cell from this run. If a future review insists on tracking despite the limited replication, the only defensible research spec is H4 long MA-distance mean reversion on XCU_USD with EMA/SMA 50, close at least 1% below MA, market entry preferred for cleaner excess-vs-baseline behavior, 1% stop / 1% target, and 84-bar max hold. Wheat and sugar ATR-expansion limit cells should be treated as separate research leads, not companions for copper.",
        "",
        "Supporting CSVs: `copper_ma_neighborhood.csv` and `copper_ma_split_half.csv`.",
        "",
    ])
    (OUT_DIR / "REPLICATION.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
