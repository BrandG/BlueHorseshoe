"""Render the micro-futures cost-cushion chart for the opening-range fade (Variant B).

Cushion = (round-trip $ that kills the edge) / (assumed real round-trip $). >1 means the edge
survives that cost scenario; the dashed line at 1.0 is break-even. Bars grouped by instrument,
one per period (P1 recent, P2 untouched OOS), at the *conservative* cost scenario (honest worst case).

    ./run.sh python research/opening_range_fade_v1/chart_futures.py   # writes + emails the PNG
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import config as C
import data as D
from futures import summarize

OUT = os.path.join(C.STUDY_DIR, "figures", "futures_cushion.png")
SCEN = "conservative"   # the honest worst case


def main():
    p1 = summarize(D.build_setups(C.SYMBOLS_HOLDOUT, day_min="2025-06"))
    p2 = summarize(D.build_setups(C.SYMBOLS_HOLDOUT, day_max="2025-06"))
    order = ["SPY", "QQQ", "IWM"]
    futs = [p1[s]["fut"] for s in order]
    c1 = [p1[s]["scen"][SCEN]["cushion"] for s in order]
    c2 = [p2[s]["scen"][SCEN]["cushion"] for s in order]
    e1 = [p1[s]["scen"][SCEN]["exp"] for s in order]
    e2 = [p2[s]["scen"][SCEN]["exp"] for s in order]

    x = range(len(order)); w = 0.38
    fig, ax = plt.subplots(figsize=(9, 5.5))
    b1 = ax.bar([i - w/2 for i in x], c1, w, label="P1 2025-06..2026-06 (recent)", color="#2b8cbe")
    b2 = ax.bar([i + w/2 for i in x], c2, w, label="P2 2024-01..2025-05 (untouched OOS)", color="#a6bddb")
    ax.axhline(1.0, ls="--", lw=1.4, color="#d7301f", label="break-even (cushion = 1x)")

    for bars, exps in ((b1, e1), (b2, e2)):
        for rect, ex in zip(bars, exps):
            ax.annotate(f"{rect.get_height():.1f}x\n+${ex:.1f}/tr",
                        (rect.get_x() + rect.get_width()/2, rect.get_height()),
                        ha="center", va="bottom", fontsize=8.5)

    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{f}\n(↔{s})" for f, s in zip(futs, order)])
    ax.set_ylabel("cost cushion  (break-even RT $  /  real RT $)")
    ax.set_title("Opening-range fade (Variant B) on micro futures — conservative-cost cushion\n"
                 "edge clears costs in both periods; MNQ strongest, M2K thinnest",
                 fontsize=11)
    ax.set_ylim(0, max(c1 + c2) * 1.18)
    ax.legend(fontsize=8.5, loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=130)
    print("wrote", OUT)
    return OUT


if __name__ == "__main__":
    main()
