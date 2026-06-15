"""Entry-location P0b: D1-alignment as an entry conditioner, ATR-disentangled.

Question (per BUD_ENTRY_LOCATION_RESEARCH.md §3.4, per-trade R lens):
  Bud's inline diagnostic claims with-trend fires carry ~3.3x the per-trade R. Is that
  real on the strong-4 long-MR book, and does it add R *after* conditioning on ATR
  regime -- i.e. is D1-alignment genuinely orthogonal to the volatility axis that
  already carries the signal (entry-distance was NOT, see DISENTANGLE_P0.md)?

Method:
  - Universe: long_mr_strong4 (bb, rsi, ema, stoch) long fires, deduped to one entry
    per (pair, signal bar). Mid entry only (entry-depth lever is closed). TP/SL 1%/1%,
    MAX_HOLD=84 -- identical geometry to the deployed sim.
  - D1 alignment, PIT-faithful to the LIVE briefing semantics: at trigger bar i, the
    daily candle is open = first bar of i's NY date, close = close[i] (the running
    daily close at trigger time). d1_dir = sign(close[i] - day_open). All trades are
    long, so with-trend = D1 up, counter-trend = D1 down, flat = doji. This mirrors
    `bud.briefing.d1_alignment` without the full-day-close look-ahead a naive backtest
    would introduce.
  - Cross-tab per-trade R by ATR bucket x D1 alignment. Newey-West SE (L = hold-1 = 83,
    Bartlett) on the with-trend - counter-trend contrast, per house standard.
"""
# pylint: disable=import-error,wrong-import-position,wrong-import-order
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
HARNESS_DIR = ROOT / "research" / "v2_executable_regate" / "harness"
DEPTH_DIR = ROOT / "research" / "dislocation_depth_v1"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HARNESS_DIR))

from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators import atr, ohlc_mid  # noqa: E402
from _lib import MAX_HOLD, STOP_PCT, TP_PCT, sim_long_mid  # noqa: E402

STRONG_CELLS = ("bb", "rsi", "ema", "stoch")
NW_LAG = MAX_HOLD - 1
FIRES_PATH = DEPTH_DIR / "depth_fires.csv"
OUT_PATH = OUT_DIR / "D1_ALIGN_P0.md"
GRID_CSV = OUT_DIR / "d1_align_p0_grid.csv"
ALIGN_ORDER = ("with-trend", "flat", "counter-trend")


def _atr_bucket(value: float) -> str:
    if not np.isfinite(value):
        return "missing"
    if value < 1.0 / 3.0:
        return "low"
    if value < 2.0 / 3.0:
        return "mid"
    return "high"


def _nw_se(values: np.ndarray, lag: int = NW_LAG) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n < 2:
        return float("nan")
    c = arr - arr.mean()
    var = float(c @ c) / n
    use = min(lag, n - 1)
    for L in range(1, use + 1):
        w = 1.0 - L / (use + 1.0)
        var += 2.0 * w * float(c[L:] @ c[:-L]) / n
    return float(np.sqrt(max(var, 0.0) / n))


def _ny_day_open(raw: pd.DataFrame, open_arr: np.ndarray) -> np.ndarray:
    """Per-bar 'open of this bar's NY calendar day' (vectorized, PIT-safe)."""
    ts = pd.to_datetime(raw["timestamp"])
    ts = ts.dt.tz_localize("UTC") if ts.dt.tz is None else ts.dt.tz_convert("UTC")
    ny_date = ts.dt.tz_convert("America/New_York").dt.date
    return pd.Series(open_arr).groupby(pd.Series(ny_date).values).transform("first").to_numpy(float)


def _load_fires() -> tuple[pd.DataFrame, list[str]]:
    fires = pd.read_csv(FIRES_PATH, parse_dates=["ts"])
    fires = fires[
        fires["evaluator"].isin(STRONG_CELLS) & (fires["direction"] == "long")
    ].copy()
    fires = fires.sort_values(["pair", "ts", "evaluator"]).drop_duplicates(["pair", "ts"])
    return fires, sorted(fires["pair"].unique())


def _simulate() -> pd.DataFrame:
    fires, pairs = _load_fires()
    rows: list[dict[str, object]] = []
    with FxStore(read_only=True) as store:
        for pair in pairs:
            raw = store.load(pair, granularity="H4", include_incomplete=False)
            if raw.empty:
                continue
            mid = ohlc_mid(raw)
            ts_index = {ts: idx for idx, ts in enumerate(pd.to_datetime(raw["timestamp"]))}
            close = mid["close"].to_numpy(float)
            high = mid["high"].to_numpy(float)
            low = mid["low"].to_numpy(float)
            open_arr = mid["open"].to_numpy(float)
            atr_vals = atr(mid, period=14).to_numpy(float)
            day_open = _ny_day_open(raw, open_arr)
            for fire in fires[fires["pair"] == pair].itertuples(index=False):
                i = ts_index.get(pd.Timestamp(fire.ts))
                if i is None or not np.isfinite(atr_vals[i]):
                    continue
                r, _exit = sim_long_mid(close, high, low, i, MAX_HOLD)
                if r is None:
                    continue
                d_open, d_close = day_open[i], close[i]
                if d_close > d_open:        # all fires are long
                    align = "with-trend"
                elif d_close < d_open:
                    align = "counter-trend"
                else:
                    align = "flat"
                rows.append({
                    "pair": pair, "bucket": _atr_bucket(float(fire.ATR_percentile)),
                    "align": align, "R": float(r),
                })
    return pd.DataFrame(rows)


def _cell(sub: pd.DataFrame) -> dict[str, float]:
    r = sub["R"].to_numpy(float)
    return {"n": len(r), "mean_R": float(np.mean(r)) if len(r) else np.nan}


def _diff(wt: pd.DataFrame, ct: pd.DataFrame) -> tuple[float, float, float]:
    a, b = wt["R"].to_numpy(float), ct["R"].to_numpy(float)
    if len(a) < 2 or len(b) < 2:
        return np.nan, np.nan, np.nan
    diff = float(np.mean(a) - np.mean(b))
    se = float(np.sqrt(_nw_se(a) ** 2 + _nw_se(b) ** 2))
    return diff, se, diff - 1.96 * se


def _fmt(v: float, d: int = 4) -> str:
    return "nan" if not np.isfinite(v) else f"{v:+.{d}f}"


def _grid(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for bucket in ("low", "mid", "high", "ALL"):
        bsub = trades if bucket == "ALL" else trades[trades["bucket"] == bucket]
        cells = {a: _cell(bsub[bsub["align"] == a]) for a in ALIGN_ORDER}
        diff, se, ci_low = _diff(
            bsub[bsub["align"] == "with-trend"], bsub[bsub["align"] == "counter-trend"]
        )
        row: dict[str, object] = {"bucket": bucket}
        for a in ALIGN_ORDER:
            row[f"n_{a}"] = cells[a]["n"]
            row[f"meanR_{a}"] = cells[a]["mean_R"]
        row["wt_minus_ct"] = diff
        row["nw_se"] = se
        row["nw_ci_low"] = ci_low
        out.append(row)
    return pd.DataFrame(out)


def main() -> None:
    trades = _simulate()
    grid = _grid(trades)
    grid.to_csv(GRID_CSV, index=False)

    lines = [
        "# Entry-Location P0b — D1-alignment, ATR-disentangled",
        "",
        "Universe: `long_mr_strong4` (bb, rsi, ema, stoch) long, mid entry, TP/SL 1%/1%, "
        "MAX_HOLD=84, deduped one entry per (pair, signal bar). D1 alignment uses the "
        "PIT-live definition (day-open vs trigger-bar close). NW SE: Bartlett L=83.",
        "",
        "**Read:** (1) is with-trend > counter-trend for these MR longs, and NW-significant? "
        "(2) does the with-trend lift survive *inside* each ATR bucket — i.e. is D1 a "
        "separate axis from volatility, unlike entry-distance?",
        "",
        "## mean R by ATR bucket x D1 alignment",
        "",
        "| bucket | with-trend (n) | flat (n) | counter-trend (n) | wt−ct | NW_SE | NW_CI_low |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, row in grid.iterrows():
        lines.append(
            f"| {row['bucket']} "
            f"| {_fmt(row['meanR_with-trend'])} ({int(row['n_with-trend']):,}) "
            f"| {_fmt(row['meanR_flat'])} ({int(row['n_flat']):,}) "
            f"| {_fmt(row['meanR_counter-trend'])} ({int(row['n_counter-trend']):,}) "
            f"| {_fmt(row['wt_minus_ct'])} | {_fmt(row['nw_se'])} | {_fmt(row['nw_ci_low'])} |"
        )
    lines += [
        "",
        "`wt−ct` > 0 means with-trend beats counter-trend; NW_CI_low > 0 means the gap "
        "clears the Newey-West 95% bar. If the gap holds inside low/mid/high (not just "
        "ALL), D1 is orthogonal to the ATR axis and is a real second entry-location lever.",
        "",
        f"Artifacts: `{GRID_CSV.name}`.", "",
    ]
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("=== Entry-Location P0b (D1) complete ===")
    print(f"report: {OUT_PATH}")
    for _, row in grid.iterrows():
        print(
            f"  {row['bucket']:>4}: with={_fmt(row['meanR_with-trend'])} "
            f"(n={int(row['n_with-trend']):,})  "
            f"counter={_fmt(row['meanR_counter-trend'])} "
            f"(n={int(row['n_counter-trend']):,})  "
            f"wt-ct={_fmt(row['wt_minus_ct'])}  NW_CI_low={_fmt(row['nw_ci_low'])}"
        )


if __name__ == "__main__":
    main()
