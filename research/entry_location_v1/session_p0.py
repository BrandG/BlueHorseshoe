"""Entry-location P0c: session as an entry conditioner, ATR-disentangled.

Question (BUD_ENTRY_LOCATION_RESEARCH.md §3.5, per-trade R lens):
  Does the forex session of the *trigger bar* (asia/london/overlap/ny) change a single
  trade's per-trade R -- and does any session edge survive inside ATR buckets, i.e. is
  session a genuinely separate axis from the volatility axis that already carries the
  signal? (entry-distance was NOT separate; D1-alignment was separate but sub-significant.)

Method:
  - Universe: long_mr_strong4 (bb, rsi, ema, stoch) long fires, deduped to one entry per
    (pair, signal bar). Mid entry only. TP/SL 1%/1%, MAX_HOLD=84.
  - Session label is `bh_ftmo.indicators.sessions.session_label` on the trigger-bar open
    timestamp -- a pure function of the clock, no look-ahead.
  - Cross-tab per-trade R by ATR bucket x session. NW SE (Bartlett, L=83) on each
    session-vs-rest contrast (pooled), per house standard.
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
from bh_ftmo.indicators.sessions import session_label  # noqa: E402
from _lib import MAX_HOLD, STOP_PCT, TP_PCT, sim_long_mid  # noqa: E402

STRONG_CELLS = ("bb", "rsi", "ema", "stoch")
NW_LAG = MAX_HOLD - 1
SESSION_ORDER = ("asia", "london", "overlap", "ny", "closed")
FIRES_PATH = DEPTH_DIR / "depth_fires.csv"
OUT_PATH = OUT_DIR / "SESSION_P0.md"
GRID_CSV = OUT_DIR / "session_p0_grid.csv"


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
            atr_vals = atr(mid, period=14).to_numpy(float)
            sess = [s.value if hasattr(s, "value") else str(s)
                    for s in session_label(ts_series)]
            for fire in fires[fires["pair"] == pair].itertuples(index=False):
                i = ts_index.get(pd.Timestamp(fire.ts))
                if i is None or not np.isfinite(atr_vals[i]):
                    continue
                r, _exit = sim_long_mid(close, high, low, i, MAX_HOLD)
                if r is None:
                    continue
                rows.append({
                    "pair": pair, "bucket": _atr_bucket(float(fire.ATR_percentile)),
                    "session": sess[i], "R": float(r),
                })
    return pd.DataFrame(rows)


def _fmt(v: float, d: int = 4) -> str:
    return "nan" if not np.isfinite(v) else f"{v:+.{d}f}"


def _sessions_present(trades: pd.DataFrame) -> list[str]:
    present = set(trades["session"].unique())
    return [s for s in SESSION_ORDER if s in present]


def _grid(trades: pd.DataFrame, sessions: list[str]) -> pd.DataFrame:
    out = []
    for bucket in ("low", "mid", "high", "ALL"):
        bsub = trades if bucket == "ALL" else trades[trades["bucket"] == bucket]
        row: dict[str, object] = {"bucket": bucket}
        for s in sessions:
            sR = bsub[bsub["session"] == s]["R"].to_numpy(float)
            row[f"n_{s}"] = len(sR)
            row[f"meanR_{s}"] = float(np.mean(sR)) if len(sR) else np.nan
        out.append(row)
    return pd.DataFrame(out)


def _sig_rows(trades: pd.DataFrame, sessions: list[str]) -> pd.DataFrame:
    """Pooled: each session's own NW CI, and session-vs-rest NW contrast."""
    out = []
    for s in sessions:
        a = trades[trades["session"] == s]["R"].to_numpy(float)
        rest = trades[trades["session"] != s]["R"].to_numpy(float)
        if len(a) < 2:
            continue
        mean_a, se_a = float(np.mean(a)), _nw_se(a)
        diff = mean_a - (float(np.mean(rest)) if len(rest) else np.nan)
        se_diff = float(np.sqrt(se_a ** 2 + (_nw_se(rest) ** 2 if len(rest) else 0.0)))
        out.append({
            "session": s, "n": len(a), "mean_R": mean_a, "nw_se": se_a,
            "own_ci_low": mean_a - 1.96 * se_a,
            "diff_vs_rest": diff, "diff_nw_ci_low": diff - 1.96 * se_diff,
        })
    return pd.DataFrame(out)


def main() -> None:
    trades = _simulate()
    sessions = _sessions_present(trades)
    grid = _grid(trades, sessions)
    sig = _sig_rows(trades, sessions)
    grid.to_csv(GRID_CSV, index=False)

    hdr = "| bucket | " + " | ".join(f"{s} (n)" for s in sessions) + " |"
    sep = "| --- | " + " | ".join("---" for _ in sessions) + " |"
    lines = [
        "# Entry-Location P0c — session, ATR-disentangled",
        "",
        "Universe: `long_mr_strong4` long, mid entry, TP/SL 1%/1%, MAX_HOLD=84, deduped "
        "one entry per (pair, signal bar). Session = trigger-bar NY-clock label. NW L=83.",
        "",
        "**Read:** (1) does any session's per-trade R clear its own NW bar / beat the "
        "rest? (2) does a session edge hold *inside* ATR buckets (orthogonal to vol)?",
        "",
        "## mean R by ATR bucket x session",
        "", hdr, sep,
    ]
    for _, row in grid.iterrows():
        cells = []
        for s in sessions:
            cells.append(f"{_fmt(row[f'meanR_{s}'])} ({int(row[f'n_{s}']):,})")
        lines.append(f"| {row['bucket']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Pooled significance (Newey-West)",
        "",
        "| session | n | mean_R | own_CI_low | diff_vs_rest | diff_CI_low |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in sig.iterrows():
        lines.append(
            f"| {r['session']} | {int(r['n']):,} | {_fmt(r['mean_R'])} "
            f"| {_fmt(r['own_ci_low'])} | {_fmt(r['diff_vs_rest'])} "
            f"| {_fmt(r['diff_nw_ci_low'])} |"
        )
    lines += [
        "",
        "`own_CI_low` > 0 means the session is individually profitable past the NW bar; "
        "`diff_CI_low` > 0 means it NW-beats the other sessions. A real session lever "
        "needs the edge to also persist inside the low/mid/high rows above.",
        "", f"Artifacts: `{GRID_CSV.name}`.", "",
    ]
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("=== Entry-Location P0c (session) complete ===")
    print(f"report: {OUT_PATH}")
    print(f"sessions present: {sessions}")
    for _, r in sig.iterrows():
        print(
            f"  {r['session']:>8}: mean_R={_fmt(r['mean_R'])} (n={int(r['n']):,})  "
            f"own_CI_low={_fmt(r['own_ci_low'])}  "
            f"vs_rest={_fmt(r['diff_vs_rest'])}  diff_CI_low={_fmt(r['diff_nw_ci_low'])}"
        )
    print("\nmean R by bucket x session:")
    for _, row in grid.iterrows():
        seq = "  ".join(f"{s}={_fmt(row[f'meanR_{s}'])}" for s in sessions)
        print(f"  {row['bucket']:>4}: {seq}")


if __name__ == "__main__":
    main()
