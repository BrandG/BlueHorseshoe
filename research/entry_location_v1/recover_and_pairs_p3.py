"""Entry-location P3: per-trade payoff of skipping high∩NY + per-pair concentration.

Pure per-trade lens (no FTMO/account framing). Two questions:
  1. How much total R does skipping high-ATR ∩ NY recover for the strong-4 long-MR book?
     (= the per-trade losses we stop taking.)
  2. Is that loss broad across pairs, or one or two names? A corner driven by a single
     JPY pair is fragile; a corner spread across most pairs is a real property.

Universe/geometry identical to P0-P2 (imported `_simulate`): strong-4 long, mid entry,
1%/1%, MAX_HOLD=84, deduped one entry per (pair, signal bar).
"""
# pylint: disable=import-error,wrong-import-position,wrong-import-order
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT_DIR))

from high_atr_subcell_p1 import _simulate  # noqa: E402

OUT_PATH = OUT_DIR / "RECOVER_AND_PAIRS_P3.md"
GRID_CSV = OUT_DIR / "recover_and_pairs_p3.csv"


def _fmt(v: float, d: int = 4) -> str:
    return "nan" if not np.isfinite(v) else f"{v:+.{d}f}"


def main() -> None:
    trades = _simulate()
    book_R = float(trades["R"].sum())
    high_ny = trades[(trades["bucket"] == "high") & (trades["session"] == "ny")]
    ny_R = float(high_ny["R"].sum())
    recovered = -ny_R                       # losses we stop taking
    book_after = book_R - ny_R              # book with high∩NY skipped

    # per-pair breakdown of the high∩NY corner
    rows = []
    for pair, sub in high_ny.groupby("pair"):
        r = sub["R"].to_numpy(float)
        rows.append({
            "pair": pair, "n": len(r),
            "mean_R": float(np.mean(r)), "total_R": float(np.sum(r)),
        })
    per_pair = pd.DataFrame(rows).sort_values("total_R").reset_index(drop=True)
    per_pair.to_csv(GRID_CSV, index=False)

    n_pairs = len(per_pair)
    n_neg = int((per_pair["total_R"] < 0).sum())
    n_neg_mean = int((per_pair["mean_R"] < 0).sum())
    worst = per_pair.iloc[0]
    worst3_share = float(per_pair.head(3)["total_R"].sum() / ny_R) if ny_R != 0 else np.nan
    worst1_share = float(worst["total_R"] / ny_R) if ny_R != 0 else np.nan

    lines = [
        "# Entry-Location P3 — per-trade payoff + per-pair concentration of high∩NY",
        "",
        "Strong-4 long-MR, mid entry, 1%/1%, MAX_HOLD=84. Pure per-trade R; no account framing.",
        "",
        "## Payoff of skipping high∩NY",
        "",
        f"- Book total R (take everything): **{book_R:+.1f}**",
        f"- high∩NY total R (the corner): **{ny_R:+.1f}** over {len(high_ny):,} trades",
        f"- Book total R if high∩NY skipped: **{book_after:+.1f}**  "
        f"(recovers {recovered:+.1f} R, {100*recovered/book_R:+.0f}% of book)",
        "",
        "## Per-pair concentration of the high∩NY loss",
        "",
        f"- {n_pairs} pairs fire in this corner; {n_neg}/{n_pairs} have negative total R, "
        f"{n_neg_mean}/{n_pairs} have negative mean R.",
        f"- Worst single pair = {worst['pair']} ({worst['total_R']:+.1f} R, "
        f"{100*worst1_share:.0f}% of the corner loss).",
        f"- Worst 3 pairs = {100*worst3_share:.0f}% of the corner loss.",
        "",
        "| pair | n | mean_R | total_R |",
        "| --- | --- | --- | --- |",
    ]
    for _, r in per_pair.iterrows():
        lines.append(
            f"| {r['pair']} | {int(r['n']):,} | {_fmt(r['mean_R'])} | {r['total_R']:+.1f} |"
        )
    broad = n_neg_mean >= 0.6 * n_pairs and worst1_share < 0.5
    lines += [
        "",
        f"**Concentration verdict:** {'BROAD' if broad else 'CONCENTRATED'} — "
        + ("most pairs lose in this corner and no single pair dominates; the corner is a "
           "real cross-book property." if broad else
           "the loss leans on a few pairs; treat the corner as fragile until confirmed."),
        "", f"Artifacts: `{GRID_CSV.name}`.", "",
    ]
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("=== Entry-Location P3 (payoff + per-pair) complete ===")
    print(f"report: {OUT_PATH}")
    print(f"book R={book_R:+.1f}  high∩NY R={ny_R:+.1f} (n={len(high_ny):,})  "
          f"-> book if skipped={book_after:+.1f} (recovers {recovered:+.1f}, "
          f"{100*recovered/book_R:+.0f}% of book)")
    print(f"per-pair: {n_neg_mean}/{n_pairs} pairs negative mean R; "
          f"worst pair {worst['pair']}={worst['total_R']:+.1f} ({100*worst1_share:.0f}% of loss); "
          f"worst-3={100*worst3_share:.0f}%")
    print(f"verdict: {'BROAD (real cross-book property)' if broad else 'CONCENTRATED (fragile)'}\n")
    for _, r in per_pair.iterrows():
        print(f"  {r['pair']:<10} n={int(r['n']):>4}  mean={_fmt(r['mean_R'])}  tot={r['total_R']:+.1f}")


if __name__ == "__main__":
    main()
