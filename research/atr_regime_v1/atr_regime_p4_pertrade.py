"""ATR-regime P4 per-trade re-cut: win rate + average R, calm vs choppy.

No FTMO +10% target, no challenge-pass race — judge the volatility conditioner
purely on the trades themselves, in R, split by ATR regime (calm = low/mid ATR,
choppy = high ATR). Headline metric is win rate, alongside average R and the
loss tail that drives account blow-ups.
"""
# pylint: disable=import-error,wrong-import-position,duplicate-code
# pylint: disable=missing-function-docstring

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT_DIR))

from atr_regime_p1 import REGIME_LABEL, REGIME_ORDER  # noqa: E402
from atr_regime_p4_ftmo import _sample_frames  # noqa: E402

CSV_PATH = OUT_DIR / "atr_regime_p4_pertrade.csv"
REPORT_PATH = OUT_DIR / "ATR_REGIME_P4_PERTRADE.md"
OUT_PATH = OUT_DIR / "atr_regime_p4_pertrade.out"

CALM = REGIME_ORDER[:2]   # low + mid ATR
CHOPPY = REGIME_ORDER[2]  # high ATR


def _stats(r_values: pd.Series) -> dict[str, float]:
    arr = r_values.to_numpy(dtype=float)
    n = int(arr.size)
    wins = int((arr > 0).sum())
    return {
        "trades": n,
        "win_rate": wins / n if n else float("nan"),
        "avg_R": float(arr.mean()) if n else float("nan"),
        "median_R": float(np.median(arr)) if n else float("nan"),
        "worst_R": float(arr.min()) if n else float("nan"),
        "p05_R": float(np.percentile(arr, 5)) if n else float("nan"),
        "total_R": float(arr.sum()) if n else float("nan"),
    }


def _grouped(frame: pd.DataFrame, sample: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    groups = {
        "calm (low+mid ATR)": frame[frame["regime"].isin(CALM)]["R"],
        "choppy (high ATR)": frame[frame["regime"] == CHOPPY]["R"],
        "all": frame["R"],
    }
    for bucket in REGIME_ORDER:
        groups[REGIME_LABEL[bucket]] = frame[frame["regime"] == bucket]["R"]
    for label, series in groups.items():
        row = {"sample": sample, "regime_group": label}
        row.update(_stats(series))
        rows.append(row)
    return rows


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _table(df: pd.DataFrame, sample: str) -> str:
    sub = df[df["sample"] == sample]
    order = ["calm (low+mid ATR)", "choppy (high ATR)", "all", "low", "mid", "high"]
    sub = sub.set_index("regime_group").loc[order].reset_index()
    header = "| regime | trades | win_rate | avg_R | median_R | worst_R | p05_R | total_R |"
    divider = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, divider]
    for row in sub.itertuples(index=False):
        lines.append(
            f"| {row.regime_group} | {int(row.trades)} | {_fmt_pct(row.win_rate)} | "
            f"{row.avg_R:.3f} | {row.median_R:.3f} | {row.worst_R:.2f} | "
            f"{row.p05_R:.2f} | {row.total_R:.1f} |"
        )
    return "\n".join(lines)


def _loss_share_high(frame: pd.DataFrame) -> float:
    losses = frame[frame["R"] < 0]
    total_loss = losses["R"].sum()
    if total_loss == 0:
        return float("nan")
    high_loss = losses[losses["regime"] == CHOPPY]["R"].sum()
    return float(high_loss / total_loss)


def _report(df: pd.DataFrame, samples: dict[str, pd.DataFrame]) -> str:
    parts = ["# ATR Regime P4 — Per-Trade Re-cut (win rate + R, calm vs choppy)", ""]
    parts.append(
        "Judges the volatility conditioner on the trades themselves — no +10% FTMO target, "
        "no challenge-pass race. Calm = low+mid ATR (the pair's vol in the bottom two-thirds "
        "of its own recent ~6 weeks, w252 percentile); choppy = high ATR (top third)."
    )
    parts.append("")
    for sample in ("long_mr_strong4", "long_mr_full6"):
        frame = samples[sample]
        share = _loss_share_high(frame)
        high_n = int((frame["regime"] == CHOPPY).sum())
        parts.append(f"## {sample}")
        parts.append(_table(df, sample))
        parts.append("")
        parts.append(
            f"Choppy trades are {high_n / len(frame) * 100:.0f}% of the book but account for "
            f"{share * 100:.0f}% of total losing-trade R. Down-sizing or skipping them is the "
            "conditioner's mechanism."
        )
        parts.append("")
    return "\n".join(parts)


def main() -> None:
    samples = _sample_frames()
    rows: list[dict[str, object]] = []
    for sample, frame in samples.items():
        rows.extend(_grouped(frame, sample))
    df = pd.DataFrame(rows)
    df.to_csv(CSV_PATH, index=False)
    report = _report(df, samples)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")

    summary_lines = ["ATR-regime P4 per-trade re-cut complete", f"csv={CSV_PATH}", f"report={REPORT_PATH}"]
    for sample in ("long_mr_strong4", "long_mr_full6"):
        sub = df[df["sample"] == sample].set_index("regime_group")
        calm = sub.loc["calm (low+mid ATR)"]
        choppy = sub.loc["choppy (high ATR)"]
        summary_lines.append(
            f"{sample}: calm win={calm.win_rate * 100:.1f}% avgR={calm.avg_R:.3f} | "
            f"choppy win={choppy.win_rate * 100:.1f}% avgR={choppy.avg_R:.3f}"
        )
    text = "\n".join(summary_lines)
    OUT_PATH.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
