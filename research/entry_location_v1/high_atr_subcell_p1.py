"""Entry-location P1: is the high-ATR loss-corner a real, stable target?

The three P0 cuts agree the strong-4 long-MR book bleeds almost entirely in the
high-ATR bucket, and within it the worst sub-cells are NY session and counter-trend.
The deployed `size_down_high_0_5` is blunt -- it halves ALL high-ATR trades, including
ones that are fine. This asks whether a SURGICAL cut (size down only the bad corner,
keep full size on the rest of high-ATR) is justified:

  1. Is high-ATR ∩ NY (and ∩ counter-trend) negative in BOTH chronological halves?
  2. Does it clear the Newey-West bar (significantly negative: mean + 1.96*SE < 0)?
  3. Is the COMPLEMENT -- high-ATR minus that corner -- actually fine, i.e. is the blunt
     rule needlessly penalizing profitable high-ATR trades?

Universe/geometry identical to the P0 cuts: long_mr_strong4 long, mid entry, 1%/1%,
MAX_HOLD=84, deduped one entry per (pair, signal bar). D1 = PIT-live day-open vs trigger
close. Session = trigger-bar NY clock. NW Bartlett L=83. Halves = chronological median.
"""
# pylint: disable=import-error,wrong-import-position,wrong-import-order,too-many-locals
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
from bh_ftmo.indicators.sessions import session_label  # noqa: E402
from _lib import MAX_HOLD, STOP_PCT, TP_PCT, sim_long_mid  # noqa: E402

STRONG_CELLS = ("bb", "rsi", "ema", "stoch")
NW_LAG = MAX_HOLD - 1
FIRES_PATH = DEPTH_DIR / "depth_fires.csv"
OUT_PATH = OUT_DIR / "HIGH_ATR_SUBCELL_P1.md"
GRID_CSV = OUT_DIR / "high_atr_subcell_p1.csv"


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
            ts_series = pd.to_datetime(raw["timestamp"])
            ts_index = {ts: idx for idx, ts in enumerate(ts_series)}
            close = mid["close"].to_numpy(float)
            high = mid["high"].to_numpy(float)
            low = mid["low"].to_numpy(float)
            open_arr = mid["open"].to_numpy(float)
            atr_vals = atr(mid, period=14).to_numpy(float)
            day_open = _ny_day_open(raw, open_arr)
            sess = [s.value if hasattr(s, "value") else str(s)
                    for s in session_label(ts_series)]
            for fire in fires[fires["pair"] == pair].itertuples(index=False):
                i = ts_index.get(pd.Timestamp(fire.ts))
                if i is None or not np.isfinite(atr_vals[i]):
                    continue
                r, _exit = sim_long_mid(close, high, low, i, MAX_HOLD)
                if r is None:
                    continue
                d_open, d_close = day_open[i], close[i]
                align = ("with-trend" if d_close > d_open
                         else "counter-trend" if d_close < d_open else "flat")
                rows.append({
                    "ts": pd.Timestamp(fire.ts), "pair": pair,
                    "bucket": _atr_bucket(float(fire.ATR_percentile)),
                    "session": sess[i], "align": align, "R": float(r),
                })
    out = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    cut = len(out) // 2
    out["half"] = "h2"
    out.loc[: cut - 1, "half"] = "h1"
    return out


def _stat(sub: pd.DataFrame) -> dict[str, float]:
    r = sub["R"].to_numpy(float)
    if len(r) == 0:
        return {"n": 0, "mean_R": np.nan, "nw_se": np.nan, "ci_low": np.nan, "ci_high": np.nan}
    mean = float(np.mean(r))
    se = _nw_se(r)
    return {
        "n": len(r), "mean_R": mean, "nw_se": se,
        "ci_low": mean - 1.96 * se, "ci_high": mean + 1.96 * se,
    }


def _fmt(v: float, d: int = 4) -> str:
    return "nan" if not np.isfinite(v) else f"{v:+.{d}f}"


# sub-cells within the high-ATR bucket
def _subcells(high: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ny = high["session"] == "ny"
    ct = high["align"] == "counter-trend"
    return {
        "high (all)": high,
        "high ∩ NY": high[ny],
        "high ∩ not-NY": high[~ny],
        "high ∩ counter": high[ct],
        "high ∩ with-trend": high[high["align"] == "with-trend"],
        "high ∩ NY ∩ counter": high[ny & ct],
        "CUT set: high ∩ (NY or counter)": high[ny | ct],
        "KEEP set: high ∩ (not-NY & not-counter)": high[~ny & ~ct],
    }


def _rows(high: pd.DataFrame) -> pd.DataFrame:
    out = []
    for name, cells in _subcells(high).items():
        full = _stat(cells)
        h1 = _stat(cells[cells["half"] == "h1"])
        h2 = _stat(cells[cells["half"] == "h2"])
        sign_stable = (
            np.isfinite(h1["mean_R"]) and np.isfinite(h2["mean_R"])
            and np.sign(h1["mean_R"]) == np.sign(full["mean_R"])
            and np.sign(h2["mean_R"]) == np.sign(full["mean_R"])
        )
        out.append({
            "subcell": name, "n": full["n"],
            "mean_R": full["mean_R"], "nw_ci_low": full["ci_low"], "nw_ci_high": full["ci_high"],
            "sig_neg": bool(np.isfinite(full["ci_high"]) and full["ci_high"] < 0),
            "sig_pos": bool(np.isfinite(full["ci_low"]) and full["ci_low"] > 0),
            "h1_n": h1["n"], "h1_mean_R": h1["mean_R"],
            "h2_n": h2["n"], "h2_mean_R": h2["mean_R"],
            "sign_stable": sign_stable,
        })
    return pd.DataFrame(out)


def main() -> None:
    trades = _simulate()
    high = trades[trades["bucket"] == "high"].copy()
    grid = _rows(high)
    grid.to_csv(GRID_CSV, index=False)

    book_R = float(trades["R"].sum())
    high_R = float(high["R"].sum())
    cut_mask = (high["session"] == "ny") | (high["align"] == "counter-trend")
    cut_R = float(high[cut_mask]["R"].sum())
    keep_R = float(high[~cut_mask]["R"].sum())

    lines = [
        "# Entry-Location P1 — high-ATR loss-corner robustness",
        "",
        "Strong-4 long-MR, mid entry, 1%/1%, MAX_HOLD=84. NW Bartlett L=83. Halves = "
        "chronological median split of all fires. `sig_neg` = NW 95% upper bound < 0 "
        "(significantly money-losing); `sig_pos` = NW 95% lower bound > 0.",
        "",
        f"Book total R: {book_R:+.1f}  |  high-ATR total R: {high_R:+.1f}  "
        f"({100*high_R/book_R:+.0f}% of book) over {len(high):,} high-ATR trades.",
        "",
        "## Sub-cell stats within the high-ATR bucket",
        "",
        "| sub-cell | n | mean_R | NW_CI_low | NW_CI_high | sig_neg | h1 mean (n) | h2 mean (n) | sign-stable |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in grid.iterrows():
        lines.append(
            f"| {r['subcell']} | {int(r['n']):,} | {_fmt(r['mean_R'])} "
            f"| {_fmt(r['nw_ci_low'])} | {_fmt(r['nw_ci_high'])} | {'YES' if r['sig_neg'] else '·'} "
            f"| {_fmt(r['h1_mean_R'])} ({int(r['h1_n']):,}) "
            f"| {_fmt(r['h2_mean_R'])} ({int(r['h2_n']):,}) "
            f"| {'YES' if r['sign_stable'] else 'no'} |"
        )
    lines += [
        "",
        "## Blunt vs surgical (the deployment question)",
        "",
        f"- High-ATR total R = {high_R:+.1f}. The blunt `size_down_high_0_5` halves ALL of it.",
        f"- CUT set (high ∩ NY-or-counter): n={int(cut_mask.sum()):,}, total R = {cut_R:+.1f}.",
        f"- KEEP set (high ∩ neither): n={int((~cut_mask).sum()):,}, total R = {keep_R:+.1f}.",
        "",
        "If the KEEP set is solidly positive and the CUT set holds the loss in both halves, "
        "a surgical size-down (cut the corner, keep full size on the rest) dominates the "
        "blunt rule: same DD reduction, less throughput sacrificed.",
        "",
        f"Artifacts: `{GRID_CSV.name}`.", "",
    ]
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("=== Entry-Location P1 (high-ATR sub-cell robustness) complete ===")
    print(f"report: {OUT_PATH}")
    print(f"book R={book_R:+.1f}  high-ATR R={high_R:+.1f} ({100*high_R/book_R:+.0f}% of book)")
    print(f"CUT set R={cut_R:+.1f} (n={int(cut_mask.sum()):,})   "
          f"KEEP set R={keep_R:+.1f} (n={int((~cut_mask).sum()):,})\n")
    for _, r in grid.iterrows():
        print(
            f"  {r['subcell']:<42} n={int(r['n']):>6,}  mean={_fmt(r['mean_R'])}  "
            f"CI[{_fmt(r['nw_ci_low'])},{_fmt(r['nw_ci_high'])}]  "
            f"signeg={'Y' if r['sig_neg'] else '.'}  "
            f"h1={_fmt(r['h1_mean_R'])} h2={_fmt(r['h2_mean_R'])}  "
            f"stable={'Y' if r['sign_stable'] else '.'}"
        )


if __name__ == "__main__":
    main()
