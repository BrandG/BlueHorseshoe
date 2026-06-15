"""Entry-location P4: does the high-ATR ∩ NY skip generalize beyond strong-4 long?

P1-P3 validated: skipping high-ATR ∩ NY entries recovers +17% of book R on the
strong-4 long-MR sleeve (per-trade, holdout-passed, broad across pairs). This tests
how wide that effect is — across the full-6 MR book and across SHORT direction.

Groups (all from depth_fires.csv = the 6 dislocation/MR cells, both directions):
  - strong4 long  (bb, rsi, ema, stoch)        — recap baseline
  - full6   long  (+ cci, sma)
  - strong4 short
  - full6   short

Trend/momentum families (macd, atr, ichimoku, candle) are NOT in any fire set — they
need a separate fire-generation pass and are out of scope here.

Per-trade lens only (no account framing). Mid entry, 1%/1%, MAX_HOLD=84, deduped one
entry per (pair, signal bar) within each sleeve+direction. NW Bartlett L=83.
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
from _lib import MAX_HOLD, STOP_PCT, TP_PCT, sim_long_mid, sim_short_mid  # noqa: E402

STRONG = ("bb", "rsi", "ema", "stoch")
FULL6 = ("bb", "rsi", "cci", "sma", "ema", "stoch")
NW_LAG = MAX_HOLD - 1
FIRES_PATH = DEPTH_DIR / "depth_fires.csv"
OUT_PATH = OUT_DIR / "GENERALIZE_P4.md"
GRID_CSV = OUT_DIR / "generalize_p4.csv"

GROUPS = [
    ("strong4 long", STRONG, "long"),
    ("full6 long", FULL6, "long"),
    ("strong4 short", STRONG, "short"),
    ("full6 short", FULL6, "short"),
]


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


def _simulate_all() -> pd.DataFrame:
    fires = pd.read_csv(FIRES_PATH, parse_dates=["ts"])
    fires = fires[fires["evaluator"].isin(FULL6)].copy()
    pairs = sorted(fires["pair"].unique())
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
            atr_vals = atr(mid, period=14).to_numpy(float)
            sess = [s.value if hasattr(s, "value") else str(s)
                    for s in session_label(ts_series)]
            for fire in fires[fires["pair"] == pair].itertuples(index=False):
                i = ts_index.get(pd.Timestamp(fire.ts))
                if i is None or not np.isfinite(atr_vals[i]):
                    continue
                direction = str(fire.direction)
                sim = sim_long_mid if direction == "long" else sim_short_mid
                r, _exit = sim(close, high, low, i, MAX_HOLD)
                if r is None:
                    continue
                rows.append({
                    "pair": pair, "evaluator": str(fire.evaluator), "direction": direction,
                    "ts": pd.Timestamp(fire.ts), "bucket": _atr_bucket(float(fire.ATR_percentile)),
                    "session": sess[i], "R": float(r),
                })
    return pd.DataFrame(rows)


def _summarize(name: str, sleeve: pd.DataFrame) -> dict[str, object]:
    book_R = float(sleeve["R"].sum())
    hn = sleeve[(sleeve["bucket"] == "high") & (sleeve["session"] == "ny")]
    r = hn["R"].to_numpy(float)
    n = len(r)
    mean = float(np.mean(r)) if n else np.nan
    se = _nw_se(r) if n else np.nan
    ci_hi = mean + 1.96 * se if np.isfinite(se) else np.nan
    ny_R = float(np.sum(r)) if n else 0.0
    # per-pair breadth within the corner
    pp = hn.groupby("pair")["R"].agg(["size", "mean", "sum"]) if n else pd.DataFrame()
    n_pairs = len(pp)
    n_neg = int((pp["mean"] < 0).sum()) if n_pairs else 0
    worst_share = float(pp["sum"].min() / ny_R) if n_pairs and ny_R != 0 else np.nan
    return {
        "group": name, "book_n": len(sleeve), "book_R": book_R,
        "highNY_n": n, "highNY_mean_R": mean, "highNY_ci_high": ci_hi,
        "sig_neg": bool(np.isfinite(ci_hi) and ci_hi < 0),
        "highNY_total_R": ny_R, "recovered_R": -ny_R,
        "recovered_pct": (-ny_R / book_R * 100.0) if book_R != 0 else np.nan,
        "pairs_neg": n_neg, "pairs_total": n_pairs, "worst_pair_share": worst_share,
    }


def _fmt(v: float, d: int = 4) -> str:
    return "nan" if not np.isfinite(v) else f"{v:+.{d}f}"


def main() -> None:
    trades = _simulate_all()
    rows = []
    for name, cells, direction in GROUPS:
        sleeve = trades[
            trades["evaluator"].isin(cells) & (trades["direction"] == direction)
        ].sort_values(["pair", "ts", "evaluator"]).drop_duplicates(["pair", "ts"])
        rows.append(_summarize(name, sleeve))
    grid = pd.DataFrame(rows)
    grid.to_csv(GRID_CSV, index=False)

    lines = [
        "# Entry-Location P4 — does high∩NY skip generalize?",
        "",
        "Per-trade R, mid entry, 1%/1%, MAX_HOLD=84, deduped per (pair, bar) within "
        "sleeve+direction. `sig_neg` = NW 95% upper bound < 0. `recovered_R` = R gained by "
        "skipping high∩NY = +(its losses). Trend families (macd/atr/ichimoku/candle) absent "
        "from the fire set → not tested.",
        "",
        "| group | book n | book R | high∩NY n | high∩NY mean_R | NW_CI_high | sig_neg | recovered R | % of book | pairs neg |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in grid.iterrows():
        lines.append(
            f"| {r['group']} | {int(r['book_n']):,} | {r['book_R']:+.1f} "
            f"| {int(r['highNY_n']):,} | {_fmt(r['highNY_mean_R'])} | {_fmt(r['highNY_ci_high'])} "
            f"| {'YES' if r['sig_neg'] else '·'} | {r['recovered_R']:+.1f} "
            f"| {_fmt(r['recovered_pct'], 1)}% | {int(r['pairs_neg'])}/{int(r['pairs_total'])} |"
        )
    lines += [
        "",
        "Reading: a group generalizes the rule if high∩NY mean_R < 0 (ideally sig_neg), "
        "the recovered R is a meaningful share of its book, and the loss is broad across "
        "pairs. A group where the whole book R is itself negative is a different problem "
        "(the sleeve doesn't make money) — the skip can't rescue it.",
        "", f"Artifacts: `{GRID_CSV.name}`.", "",
    ]
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("=== Entry-Location P4 (generalization) complete ===")
    print(f"report: {OUT_PATH}\n")
    for _, r in grid.iterrows():
        print(
            f"  {r['group']:<14} bookR={r['book_R']:+7.1f} (n={int(r['book_n']):,})  "
            f"high∩NY: n={int(r['highNY_n']):>5,} mean={_fmt(r['highNY_mean_R'])} "
            f"CIhi={_fmt(r['highNY_ci_high'])} {'SIGNEG' if r['sig_neg'] else '   .  '}  "
            f"recover={r['recovered_R']:+6.1f} ({_fmt(r['recovered_pct'],1)}%)  "
            f"pairsneg={int(r['pairs_neg'])}/{int(r['pairs_total'])}"
        )


if __name__ == "__main__":
    main()
