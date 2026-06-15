"""Entry-location P0: disentangle entry-distance (k*ATR pullback) from ATR-regime.

Question (per BUD_ENTRY_LOCATION_RESEARCH.md, sharpened to per-trade R):
  Does requiring a deeper limit entry (k*ATR below the signal close) add per-trade R
  *after* conditioning on the ATR-regime bucket -- or is the apparent entry-distance
  edge just the ATR-regime effect re-expressed on the same volatility axis?

Method:
  - Universe: long_mr_strong4 fires (bb, rsi, ema, stoch), deduped to one entry per
    (pair, signal bar).
  - For each fire, sweep limit depth k in K_GRID.  k=0 is the current Bud mid rule
    (immediate fill at signal close).  k>0 places a limit at close - k*entry_ATR,
    valid for `window` H4 bars; fills if a bar low touches it (mid-OHLC touch).
  - TP/SL/R geometry identical to the deployed sim (1%/1%, MAX_HOLD=84), anchored at
    the fill bar.  No look-ahead: limit price uses close[i] and entry_ATR, both known
    at signal-bar close i; fills use future lows only.
  - Cross-tab per-trade R by ATR bucket x k.  Two windows (1 bar = Bud-faithful,
    6 bars = the contrarian DAY-tif construction the entry-distance idea came from).

Caveat: mid-OHLC touch over-counts limit fills vs executable bid/ask touch
(~37%, per the v2 executable-ledger finding).  The bias is roughly common across
buckets, so the *within-bucket* k-gradient -- the disentangling signal -- is far less
sensitive to it than absolute fill rates.  Treat fill rates as optimistic.
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
K_GRID = (0.0, 0.10, 0.25, 0.50, 0.75, 1.00)
WINDOWS = (1, 6)
FIRES_PATH = DEPTH_DIR / "depth_fires.csv"
OUT_PATH = OUT_DIR / "DISENTANGLE_P0.md"
GRID_CSV = OUT_DIR / "disentangle_p0_grid.csv"


def _atr_bucket(value: float) -> str:
    if not np.isfinite(value):
        return "missing"
    if value < 1.0 / 3.0:
        return "low"
    if value < 2.0 / 3.0:
        return "mid"
    return "high"


def sim_long_limit_k(close, high, low, i, max_hold, limit_price, window):
    """Long limit at `limit_price` (<= close[i]), valid `window` bars after signal.
    Returns (r_value, filled: bool). Non-fill -> (nan, False)."""
    fill_idx = None
    for j in range(1, window + 1):
        k = i + j
        if k >= len(close):
            return np.nan, False
        if low[k] <= limit_price:
            fill_idx = k
            break
    if fill_idx is None:
        return np.nan, False
    if fill_idx + max_hold >= len(close):
        return np.nan, False
    entry = limit_price
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if low[k] <= stop:
            return -1.0, True
        if high[k] >= tp:
            return (tp - entry) / risk, True
    exit_p = close[fill_idx + max_hold]
    return (exit_p - entry) / risk, True


def _load_fires() -> tuple[pd.DataFrame, list[str]]:
    fires = pd.read_csv(FIRES_PATH, parse_dates=["ts"])
    fires = fires[
        fires["evaluator"].isin(STRONG_CELLS) & (fires["direction"] == "long")
    ].copy()
    # one entry per (pair, signal bar): strong-4 cells can co-fire the same bar
    fires = fires.sort_values(["pair", "ts", "evaluator"]).drop_duplicates(["pair", "ts"])
    pairs = sorted(fires["pair"].unique())
    return fires, pairs


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
            atr_vals = atr(mid, period=14).to_numpy(float)
            pf = fires[fires["pair"] == pair]
            for fire in pf.itertuples(index=False):
                i = ts_index.get(pd.Timestamp(fire.ts))
                if i is None or not np.isfinite(atr_vals[i]):
                    continue
                bucket = _atr_bucket(float(fire.ATR_percentile))
                a = float(atr_vals[i])
                for window in WINDOWS:
                    for k in K_GRID:
                        if k == 0.0:
                            r, exit_idx = sim_long_mid(close, high, low, i, MAX_HOLD)
                            filled = r is not None
                            r = np.nan if r is None else float(r)
                        else:
                            r, filled = sim_long_limit_k(
                                close, high, low, i, MAX_HOLD,
                                close[i] - k * a, window,
                            )
                        rows.append({
                            "pair": pair, "bucket": bucket, "k": k,
                            "window": window, "filled": bool(filled), "R": r,
                        })
    return pd.DataFrame(rows)


def _grid(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for window in WINDOWS:
        for bucket in ("low", "mid", "high", "ALL"):
            for k in K_GRID:
                sub = trades[(trades["window"] == window) & (trades["k"] == k)]
                if bucket != "ALL":
                    sub = sub[sub["bucket"] == bucket]
                n_fires = len(sub)
                fills = sub[sub["filled"]]
                n_fills = len(fills)
                r_fill = fills["R"].to_numpy(float)
                mean_fill = float(np.nanmean(r_fill)) if n_fills else np.nan
                total_fill = float(np.nansum(r_fill)) if n_fills else 0.0
                out.append({
                    "window": window, "bucket": bucket, "k": k,
                    "n_fires": n_fires, "n_fills": n_fills,
                    "fill_rate": n_fills / n_fires if n_fires else np.nan,
                    "mean_R_fill": mean_fill,
                    "mean_R_per_fire": total_fill / n_fires if n_fires else np.nan,
                    "total_R": total_fill,
                })
    return pd.DataFrame(out)


def _fmt(v: float, d: int = 4) -> str:
    return "nan" if not np.isfinite(v) else f"{v:+.{d}f}"


def _table(grid: pd.DataFrame, window: int, value: str) -> list[str]:
    g = grid[grid["window"] == window]
    ks = list(K_GRID)
    header = "| bucket | " + " | ".join(f"k={k:.2f}" for k in ks) + " |"
    sep = "| --- | " + " | ".join("---" for _ in ks) + " |"
    lines = [header, sep]
    for bucket in ("low", "mid", "high", "ALL"):
        cells = []
        for k in ks:
            row = g[(g["bucket"] == bucket) & (g["k"] == k)].iloc[0]
            v = row[value]
            cells.append(f"{v:.3f}" if value == "fill_rate" else _fmt(float(v)))
        lines.append(f"| {bucket} | " + " | ".join(cells) + " |")
    return lines


def main() -> None:
    trades = _simulate()
    grid = _grid(trades)
    grid.to_csv(GRID_CSV, index=False)

    lines = [
        "# Entry-Location P0 — entry-distance vs ATR-regime disentangle",
        "",
        "Universe: `long_mr_strong4` (bb, rsi, ema, stoch) long fires, deduped to one "
        "entry per (pair, signal bar). TP/SL 1%/1%, MAX_HOLD=84. k=0 is the current Bud "
        "mid rule; k>0 is a limit at `close - k*ATR(14)` valid `window` H4 bars.",
        "",
        "**The disentangling read:** if the k-gradient in the `ALL` row also appears "
        "*inside each ATR bucket row*, entry-distance is a real, separate lever. If the "
        "k-gradient flattens once you hold the bucket fixed, entry-distance was the "
        "ATR-regime effect re-expressed (note §3.2 collapses into §3.1).",
    ]
    for window in WINDOWS:
        lines += [
            "", f"## window = {window} H4 bar(s)" + (
                "  (Bud-faithful next-bar limit)" if window == 1
                else "  (contrarian DAY-tif analog)"
            ),
            "", "### mean R on fills", "",
        ]
        lines += _table(grid, window, "mean_R_fill")
        lines += ["", "### fill rate", ""]
        lines += _table(grid, window, "fill_rate")
        lines += [
            "", "### mean R per fire (non-fills counted as 0 — opportunity-cost view)", "",
        ]
        lines += _table(grid, window, "mean_R_per_fire")
    lines += [
        "", "## Caveat",
        "Mid-OHLC touch over-counts limit fills vs executable bid/ask (~37%). Fill rates "
        "are optimistic; the within-bucket k-gradient is the robust signal.",
        f"", f"Artifacts: `{GRID_CSV.name}`.", "",
    ]
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")

    # console summary: pooled vs within-bucket k-effect at window=6
    g6 = grid[grid["window"] == 6]
    def at(bucket, k):
        return float(g6[(g6["bucket"] == bucket) & (g6["k"] == k)].iloc[0]["mean_R_fill"])
    print("=== Entry-Location P0 complete ===")
    print(f"fires (deduped strong4 long): {grid[(grid.window==6)&(grid.k==0.0)&(grid.bucket=='ALL')].iloc[0]['n_fires']:.0f}")
    print(f"report: {OUT_PATH}")
    print("\nmean R on fills, window=6  (k=0.00 -> k=1.00):")
    for bucket in ("low", "mid", "high", "ALL"):
        seq = "  ".join(_fmt(at(bucket, k)) for k in K_GRID)
        print(f"  {bucket:>4}: {seq}")


if __name__ == "__main__":
    main()
