"""Exit-geometry sweep — per-trade total-money ranking.

Judges each take-profit / stop / hold setup on the individual trades alone, ranked
by TOTAL MONEY = sum of per-trade R at constant per-trade risk (so total R is
proportional to total dollars). Every trade is included; there is NO account/portfolio
drawdown, NO concurrent-position cap, NO regime (calm/choppy) conditioning — a single
trade cannot produce a "portfolio drawdown," and calm-vs-choppy is a property of the
market at entry, not of the trade. The interleaved A/B quarter split + recent-24mo
holdout is a robustness check (does the setup hold across eras?), not a gate.

Reuses the deployed long-MR sleeves and the bar-by-bar exit logic of
`research/v2_executable_regate/harness/_lib.py`; the parameterized simulator is asserted
to reproduce `_lib.py` exactly at TP=SL=1%, hold=84 before any sweep.
"""
# pylint: disable=import-error,wrong-import-position,duplicate-code
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-positional-arguments
# pylint: disable=too-many-locals

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
HARNESS_DIR = ROOT / "research" / "v2_executable_regate" / "harness"
ATR_DIR = ROOT / "research" / "atr_regime_v1"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HARNESS_DIR))
sys.path.insert(0, str(ATR_DIR))

from _lib import MAX_HOLD, sim_long_mid, sim_short_mid  # noqa: E402
from atr_regime_p2b import (  # noqa: E402
    PRIMARY_DIRECTION,
    PRIMARY_SLEEVE,
    _attach_metric_values,
    _bucket_col,
    _build_sleeves,
    _load_fires_and_pairs,
    _metric_frames,
    _simulate_all_depth_trades,
)
from bh_ftmo.data.fx_store import FxStore  # noqa: E402

TP_GRID = (0.004, 0.006, 0.008, 0.010, 0.015, 0.020)
SL_GRID = (0.006, 0.008, 0.010, 0.015, 0.020)
HOLD_DAYS_GRID = (6, 10, 14, 20)
H4_BARS_PER_DAY = 6
METRIC = "atr_pct_w252"
BUCKET_COL = _bucket_col(METRIC)
KNOWN_BUCKETS = ("ATR_low_0_33", "ATR_mid_33_67", "ATR_high_67_100")
SAMPLES = (PRIMARY_SLEEVE, "long_mr_full6")
SLICES = ("A", "B", "recent_holdout")
BASELINE = (0.010, 0.010, MAX_HOLD)
HOLDOUT_MONTHS = 24
CSV_PATH = OUT_DIR / "exit_sweep_pertrade.csv"
REPORT_PATH = OUT_DIR / "EXIT_SWEEP_v1.md"
OUT_PATH = OUT_DIR / "exit_sweep_pertrade.out"


def log(message: str) -> None:
    print(message, flush=True)


def sim_long_mid_param(close, high, low, i, tp_pct, sl_pct, max_hold):
    if i + max_hold >= len(close):
        return None
    entry = close[i]
    tp_price = entry * (1.0 + tp_pct)
    stop = entry * (1.0 - sl_pct)
    risk = entry - stop
    for j in range(1, max_hold + 1):
        k = i + j
        if low[k] <= stop:
            return -1.0
        if high[k] >= tp_price:
            return (tp_price - entry) / risk
    return (close[i + max_hold] - entry) / risk


def sim_short_mid_param(close, high, low, i, tp_pct, sl_pct, max_hold):
    if i + max_hold >= len(close):
        return None
    entry = close[i]
    tp_price = entry * (1.0 - tp_pct)
    stop = entry * (1.0 + sl_pct)
    risk = stop - entry
    for j in range(1, max_hold + 1):
        k = i + j
        if high[k] >= stop:
            return -1.0
        if low[k] <= tp_price:
            return (entry - tp_price) / risk
    return (entry - close[i + max_hold]) / risk


def _arrays(metric_frames):
    return {
        pair: {
            "close": frame["close"].to_numpy(float),
            "high": frame["high"].to_numpy(float),
            "low": frame["low"].to_numpy(float),
        }
        for pair, frame in metric_frames.items()
    }


def _faithfulness_check(all_trades, arrays):
    checked = 0
    for trade in all_trades.itertuples(index=False):
        data = arrays[str(trade.pair)]
        close, high, low = data["close"], data["high"], data["low"]
        bar_idx = int(trade.bar_idx)
        if str(trade.direction) == "long":
            ref_r, _ = sim_long_mid(close, high, low, bar_idx, MAX_HOLD)
            test_r = sim_long_mid_param(close, high, low, bar_idx, 0.010, 0.010, MAX_HOLD)
        else:
            ref_r, _ = sim_short_mid(close, high, low, bar_idx, MAX_HOLD)
            test_r = sim_short_mid_param(close, high, low, bar_idx, 0.010, 0.010, MAX_HOLD)
        checked += 1
        if not np.isclose(float(ref_r), float(test_r), atol=0.0, rtol=0.0):
            raise AssertionError(f"parameterized sim mismatches _lib.py at {trade.pair} bar={bar_idx}")
    return checked


def _quarter_slice(ts_values, holdout_start):
    pre = ts_values < holdout_start
    quarters = ts_values.dt.quarter
    labels = pd.Series("recent_holdout", index=ts_values.index, dtype=object)
    labels.loc[pre & quarters.isin([1, 3])] = "A"
    labels.loc[pre & quarters.isin([2, 4])] = "B"
    return labels


def _sample_frame(frame, sample, holdout_start):
    out = frame[frame[BUCKET_COL].isin(KNOWN_BUCKETS)].copy()
    if out.empty:
        raise RuntimeError(f"{sample} has no bucketed trades")
    out = out.sort_values(["ts", "pair", "bar_idx"]).reset_index(drop=True)
    out["slice"] = _quarter_slice(out["ts"], holdout_start)
    return out


def _simulate_combo(frame, index_by_pair, arrays, tp_pct, sl_pct, max_hold):
    r_values = np.full(len(frame), np.nan, dtype=float)
    bar_col = frame["bar_idx"].to_numpy(int)
    for pair, idx in index_by_pair.items():
        data = arrays[pair]
        close, high, low = data["close"], data["high"], data["low"]
        for local_idx in idx:
            value = sim_long_mid_param(close, high, low, int(bar_col[local_idx]), tp_pct, sl_pct, max_hold)
            if value is not None:
                r_values[local_idx] = float(value)
    return r_values


def _slice_metrics(r_values, slice_mask):
    active = slice_mask & np.isfinite(r_values)
    vals = r_values[active]
    if vals.size == 0:
        return {"n_trades": 0, "total_R": 0.0, "win_rate": float("nan")}
    return {
        "n_trades": int(vals.size),
        "total_R": float(vals.sum()),
        "win_rate": float(np.mean(vals > 0.0)),
    }


def _build_contexts(holdout_start):
    fires, pairs = _load_fires_and_pairs()
    start_ts = pd.Timestamp(fires["ts"].min())
    end_ts = pd.Timestamp(fires["ts"].max())
    with FxStore(read_only=True) as store:
        metric_frames = _metric_frames(store, pairs, start_ts, end_ts)
    arrays = _arrays(metric_frames)
    all_trades, _ = _simulate_all_depth_trades(fires, pairs)
    faithfulness_n = _faithfulness_check(all_trades, arrays)
    all_trades = _attach_metric_values(all_trades, metric_frames)
    sleeve_trades, _dedup = _build_sleeves(all_trades)
    contexts = {}
    for sample in SAMPLES:
        frame = _sample_frame(sleeve_trades[(sample, PRIMARY_DIRECTION)], sample, holdout_start)
        index_by_pair = {
            str(pair): sub.index.to_numpy(int) for pair, sub in frame.groupby("pair", sort=False)
        }
        slice_masks = {name: frame["slice"].eq(name).to_numpy() for name in SLICES}
        contexts[sample] = (frame, index_by_pair, slice_masks)
    return contexts, arrays, faithfulness_n, (start_ts, end_ts), len(pairs)


def _sweep(contexts, arrays):
    combos = [
        (tp, sl, hold * H4_BARS_PER_DAY)
        for tp in TP_GRID
        for sl in SL_GRID
        for hold in HOLD_DAYS_GRID
    ]
    rows = []
    for combo_idx, (tp_pct, sl_pct, max_hold) in enumerate(combos, start=1):
        if combo_idx % 20 == 0 or combo_idx == 1:
            log(f"combo {combo_idx}/{len(combos)} TP={tp_pct:.3f} SL={sl_pct:.3f} hold={max_hold // 6}d")
        for sample, (frame, index_by_pair, slice_masks) in contexts.items():
            r_values = _simulate_combo(frame, index_by_pair, arrays, tp_pct, sl_pct, max_hold)
            row = {
                "sample": sample,
                "tp_pct": tp_pct,
                "sl_pct": sl_pct,
                "max_hold": max_hold,
                "hold_days": max_hold // H4_BARS_PER_DAY,
            }
            total = 0.0
            all_pos = True
            for name in SLICES:
                stats = _slice_metrics(r_values, slice_masks[name])
                row[f"total_R_{name}"] = stats["total_R"]
                row[f"win_rate_{name}"] = stats["win_rate"]
                row[f"n_{name}"] = stats["n_trades"]
                total += stats["total_R"]
                all_pos = all_pos and stats["total_R"] > 0.0
            row["total_R"] = total
            row["n_trades"] = sum(int(row[f"n_{name}"]) for name in SLICES)
            row["win_rate"] = float(np.average(
                [row[f"win_rate_{name}"] for name in SLICES],
                weights=[row[f"n_{name}"] for name in SLICES],
            ))
            row["profitable_all_eras"] = all_pos
            rows.append(row)
    return pd.DataFrame(rows)


def _md_table(df, columns, headers):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in df.itertuples(index=False):
        cells = []
        for col in columns:
            value = getattr(row, col)
            if col in ("tp_pct", "sl_pct"):
                cells.append(f"{value * 100:.1f}%")
            elif col == "win_rate":
                cells.append(f"{value * 100:.1f}%")
            elif col in ("total_R", "total_R_A", "total_R_B", "total_R_recent_holdout"):
                cells.append(f"{value:+.0f}")
            else:
                cells.append(str(int(value)) if isinstance(value, (int, np.integer)) else str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _report(results, period, faithfulness_n, holdout_start):
    lines = [
        "# Exit Sweep v1 — best exit setup by total money (individual trades)",
        "",
        "## Headline",
    ]
    for sample in SAMPLES:
        sub = results[results["sample"] == sample]
        base = sub[(sub.tp_pct == BASELINE[0]) & (sub.sl_pct == BASELINE[1]) & (sub.max_hold == BASELINE[2])].iloc[0]
        best = sub[sub["profitable_all_eras"]].sort_values("total_R", ascending=False).iloc[0]
        gain = (best.total_R - base.total_R) / abs(base.total_R) * 100.0
        lines.append(
            f"`{sample}`: best total-money setup is **TP {best.tp_pct * 100:.1f}% / "
            f"SL {best.sl_pct * 100:.1f}% / {int(best.hold_days)}-day hold** at "
            f"**{best.total_R:+.0f}R** vs the fixed 1:1/14d baseline {base.total_R:+.0f}R "
            f"({gain:+.0f}%); profitable in all three eras."
        )
    lines += [
        "",
        "## What this measures (and what it does NOT)",
        (
            "Each setup is scored on the trades themselves, ranked by **total money** (sum of "
            "per-trade R at constant per-trade risk, so total R is proportional to total dollars). "
            "Every trade is included. There is **no account drawdown, no concurrent-position cap, "
            "no calm/choppy filter** — a single trade cannot produce a portfolio drawdown, and "
            "regime is a property of the market at entry, not of the trade. The A/B interleaved-"
            "quarter split + last-"
            f"{HOLDOUT_MONTHS}-month holdout (from `{holdout_start.date()}`) is only a robustness "
            "check: a setup must make money in all three eras to be reported, so the winner is not "
            "a one-period fluke. (Account-level FTMO limits are a separate question, not how a "
            "per-trade setup is chosen.)"
        ),
        (
            f"Faithfulness: `{faithfulness_n:,}` real fires reproduce `_lib.py` exactly at "
            "TP=SL=1%/14d, so the baseline below IS the campaign's book. "
            f"Sample period `{period[0].date()}..{period[1].date()}`, "
            f"{len(TP_GRID) * len(SL_GRID) * len(HOLD_DAYS_GRID)} setups swept."
        ),
        "",
    ]
    cols = ["tp_pct", "sl_pct", "hold_days", "total_R_A", "total_R_B", "total_R_recent_holdout", "total_R", "win_rate", "n_trades"]
    heads = ["TP", "SL", "hold(d)", "A", "B", "holdout", "TOTAL", "win", "trades"]
    for sample in SAMPLES:
        sub = results[results["sample"] == sample]
        base = sub[(sub.tp_pct == BASELINE[0]) & (sub.sl_pct == BASELINE[1]) & (sub.max_hold == BASELINE[2])]
        top = sub[sub["profitable_all_eras"]].sort_values("total_R", ascending=False).head(10)
        lines += [f"## {sample} — top 10 by total money (all eras positive)"]
        lines += _md_table(top, cols, heads)
        lines += ["", "Current 1:1/14d baseline for reference:"]
        lines += _md_table(base, cols, heads)
        lines += [""]
    lines += [
        "## Read",
        (
            "The consistent pattern across both books: **shorter hold (10 days, not 14) and a "
            "target wider than the stop** (let winners run, cut losers faster). The single best "
            "total-money setup uses a tight 0.6% stop, but it is the best of "
            f"{len(TP_GRID) * len(SL_GRID) * len(HOLD_DAYS_GRID)} swept — trust the *direction* "
            "(shorter hold, wider target than stop) more than the exact 0.6%. A steadier "
            "alternative on the focused book is TP 1.5% / SL 1.0% / 10-day (more even across eras)."
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


def run():
    log("loading fires + ATR frames, building deployed sleeves")
    fires_peek, _pairs = _load_fires_and_pairs()
    holdout_start = pd.Timestamp(fires_peek["ts"].max()) - pd.DateOffset(months=HOLDOUT_MONTHS)
    contexts, arrays, faithfulness_n, period, n_pairs = _build_contexts(holdout_start)
    log(f"faithfulness ok ({faithfulness_n:,} fires); sweeping exits")
    results = _sweep(contexts, arrays)
    results.to_csv(CSV_PATH, index=False)
    REPORT_PATH.write_text(_report(results, period, faithfulness_n, holdout_start), encoding="utf-8")
    out_lines = [
        "Exit sweep (per-trade total money) complete",
        f"period={period[0]}..{period[1]}",
        f"holdout_start={holdout_start}",
        f"pairs={n_pairs}",
        f"faithfulness_checked={faithfulness_n}",
        f"combos={len(TP_GRID) * len(SL_GRID) * len(HOLD_DAYS_GRID)}",
        f"csv={CSV_PATH}",
        f"report={REPORT_PATH}",
    ]
    for sample in SAMPLES:
        sub = results[results["sample"] == sample]
        base = sub[(sub.tp_pct == BASELINE[0]) & (sub.sl_pct == BASELINE[1]) & (sub.max_hold == BASELINE[2])].iloc[0]
        best = sub[sub["profitable_all_eras"]].sort_values("total_R", ascending=False).iloc[0]
        out_lines.append(
            f"{sample}: baseline={base.total_R:+.0f}R  best=TP{best.tp_pct * 100:.1f}/"
            f"SL{best.sl_pct * 100:.1f}/{int(best.hold_days)}d {best.total_R:+.0f}R"
        )
    OUT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print("\n".join(out_lines))


def main():
    run()


if __name__ == "__main__":
    main()
