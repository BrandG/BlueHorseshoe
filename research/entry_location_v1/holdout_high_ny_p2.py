"""Entry-location P2: recent-24mo holdout check on the high-ATR ∩ NY loss corner.

P1 found high-ATR ∩ NY is a significantly-negative, both-interleaved-halves-stable
loss corner (~−186R, ≈ the entire high-ATR drag). The BUD validation standard
([[bud_validation_split_interleaved]]) requires a profit/loss claim to also hold on
the LAST-24-MONTH recent holdout, not just interleaved halves. This is that gate.

Holdout = 2024-06-15 .. now (last 24mo); train = everything before. The corner PASSES
the gate if high∩NY stays clearly negative in BOTH train and holdout, and the rest of
high-ATR (not-NY) stays ~flat/positive in both (so the blunt rule is over-cutting).

Universe/geometry identical to P0/P1 (imported `_simulate`): strong-4 long, mid entry,
1%/1%, MAX_HOLD=84, deduped one entry per (pair, signal bar). NW Bartlett L=83.
"""
# pylint: disable=import-error,wrong-import-position,wrong-import-order
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT_DIR))

from high_atr_subcell_p1 import _nw_se, _simulate  # noqa: E402

HOLDOUT_START = pd.Timestamp("2024-06-15")  # today is 2026-06-15 → last 24 months
OUT_PATH = OUT_DIR / "HOLDOUT_HIGH_NY_P2.md"
GRID_CSV = OUT_DIR / "holdout_high_ny_p2.csv"


def _stat(sub: pd.DataFrame) -> dict[str, float]:
    r = sub["R"].to_numpy(float)
    if len(r) == 0:
        return {"n": 0, "mean_R": np.nan, "ci_low": np.nan, "ci_high": np.nan, "total_R": 0.0}
    mean, se = float(np.mean(r)), _nw_se(r)
    return {
        "n": len(r), "mean_R": mean, "total_R": float(np.sum(r)),
        "ci_low": mean - 1.96 * se, "ci_high": mean + 1.96 * se,
    }


def _fmt(v: float, d: int = 4) -> str:
    return "nan" if not np.isfinite(v) else f"{v:+.{d}f}"


def main() -> None:
    trades = _simulate()
    # tz-align the holdout cut to the (possibly tz-aware) fire timestamps
    ts = trades["ts"]
    cut = HOLDOUT_START.tz_localize(ts.dt.tz) if ts.dt.tz is not None else HOLDOUT_START
    trades["split"] = np.where(trades["ts"] >= cut, "holdout", "train")
    high = trades[trades["bucket"] == "high"]
    ny = high[high["session"] == "ny"]
    not_ny = high[high["session"] != "ny"]

    cells = {
        "high ∩ NY": ny,
        "high ∩ not-NY": not_ny,
        "high (all)": high,
    }
    rows = []
    for name, frame in cells.items():
        for split in ("full", "train", "holdout"):
            sub = frame if split == "full" else frame[frame["split"] == split]
            s = _stat(sub)
            rows.append({"cell": name, "split": split, **s})
    grid = pd.DataFrame(rows)
    grid.to_csv(GRID_CSV, index=False)

    def g(cell, split):
        return grid[(grid["cell"] == cell) & (grid["split"] == split)].iloc[0]

    ny_tr, ny_ho = g("high ∩ NY", "train"), g("high ∩ NY", "holdout")
    rest_tr, rest_ho = g("high ∩ not-NY", "train"), g("high ∩ not-NY", "holdout")
    passes = bool(ny_tr["mean_R"] < 0 and ny_ho["mean_R"] < 0)
    rest_ok = bool(rest_tr["mean_R"] >= -0.005 and rest_ho["mean_R"] >= -0.005)

    lines = [
        "# Entry-Location P2 — high-ATR ∩ NY recent-holdout gate",
        "",
        f"Holdout = {HOLDOUT_START.date()} .. now (last 24 months); train = before. "
        "Strong-4 long-MR, mid entry, 1%/1%, MAX_HOLD=84. NW Bartlett L=83.",
        "",
        f"**Gate (high∩NY negative in BOTH train & holdout): "
        f"{'PASS' if passes else 'FAIL'}.**",
        f"Corollary (rest of high-ATR not a loser in either, so blunt rule over-cuts): "
        f"{'holds' if rest_ok else 'does NOT hold'}.",
        "",
        "| cell | split | n | mean_R | NW_CI_low | NW_CI_high | total_R |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in grid.iterrows():
        lines.append(
            f"| {r['cell']} | {r['split']} | {int(r['n']):,} | {_fmt(r['mean_R'])} "
            f"| {_fmt(r['ci_low'])} | {_fmt(r['ci_high'])} | {r['total_R']:+.1f} |"
        )
    lines += [
        "",
        f"high∩NY: train {_fmt(ny_tr['mean_R'])} (n={int(ny_tr['n']):,}), "
        f"holdout {_fmt(ny_ho['mean_R'])} (n={int(ny_ho['n']):,}).",
        f"rest of high-ATR: train {_fmt(rest_tr['mean_R'])}, holdout {_fmt(rest_ho['mean_R'])}.",
        "",
        f"Artifacts: `{GRID_CSV.name}`.", "",
    ]
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("=== Entry-Location P2 (high∩NY recent-holdout) complete ===")
    print(f"report: {OUT_PATH}")
    print(f"GATE high∩NY neg in train AND holdout: {'PASS' if passes else 'FAIL'}")
    print(f"rest-of-high-ATR not a loser either side: {'holds' if rest_ok else 'NO'}\n")
    for _, r in grid.iterrows():
        print(
            f"  {r['cell']:<16} {r['split']:>7}  n={int(r['n']):>6,}  "
            f"mean={_fmt(r['mean_R'])}  CI[{_fmt(r['ci_low'])},{_fmt(r['ci_high'])}]  "
            f"totR={r['total_R']:+.1f}"
        )


if __name__ == "__main__":
    main()
