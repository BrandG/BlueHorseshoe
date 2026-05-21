"""simulate_flatten.py — Phase 2 of WEEKEND_FLATTEN_EQUITIES_v1.

Replays each trade in the baseline ledger with a Friday-flatten / Monday-reopen
rule applied. Two rules supported via --rule:

  uniform     : every Friday close inside (entry_date, exit_date) ends a
                segment; the following Monday open starts the next.
  asymmetric  : Friday close only ends a segment IF the position is in profit
                at that point (banks the win, skips the weekend gap). Losing
                positions hold through the weekend, no segment break.

Methodology (matches the forex precedent at
``research/v2_deploy_backtest/weekend_flatten_winners.py``):

  Total return = product over segments of (segment_end / segment_start)

Segment endpoints:
  - First segment starts at the original entry_price on entry_date.
  - Last segment ends at the original exit_price on exit_date.
  - Middle segments span (Monday open) to (next-Friday close).

Trades that do not span any weekend pass through unchanged. The output ledger
mirrors the baseline schema with two added columns (n_segments,
flatten_rule_applied) and an overridden ``blended_pnl_pct`` reflecting the
flatten-adjusted total return.

See docs/planning/WEEKEND_FLATTEN_EQUITIES_v1.md.

Usage:
  ./run.sh python research/weekend_flatten_equities_v1/simulate_flatten.py \\
      --rule uniform \\
      --input  research/weekend_flatten_equities_v1/baseline_ledger_weekly.csv \\
      --output research/weekend_flatten_equities_v1/uniform_flatten_ledger.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Iterable

import pandas as pd

from bluehorseshoe.core.config import REPO_ROOT, get_settings
from bluehorseshoe.data.duckdb_store import DuckDBStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Segment-walking simulator
# ---------------------------------------------------------------------------

def _walk_segments_uniform(bars: pd.DataFrame, entry_price: float,
                           exit_price: float) -> tuple[float, int]:
    """Uniform-flatten segments. ``bars`` must include the entry day's close
    and the exit day's close. Friday closes end segments; following Monday
    opens start the next.

    Returns (total_return_ratio, n_segments).
    """
    if bars.empty:
        return (exit_price / entry_price if entry_price else 1.0), 1

    bars = bars.sort_values("date").reset_index(drop=True)
    bars["weekday"] = bars["date"].dt.weekday  # 0=Mon..4=Fri

    # Build segment endpoints: (segment_start_price, segment_end_price)
    segments: list[tuple[float, float]] = []
    seg_start = entry_price
    seg_open_idx = 0  # 0 marks "before any bar" — start price is entry_price

    for i in range(len(bars)):
        wd = int(bars.at[i, "weekday"])
        # End-of-segment trigger: a Friday close that ISN'T the trade's exit bar.
        if wd == 4 and i < len(bars) - 1:
            seg_end = float(bars.at[i, "close"])
            segments.append((seg_start, seg_end))
            # Next segment starts at NEXT Monday's open (or whatever the next bar is)
            if i + 1 < len(bars):
                seg_start = float(bars.at[i + 1, "open"])
            seg_open_idx = i + 1

    # Final segment ends at the trade's actual exit price.
    segments.append((seg_start, exit_price))

    # Compound returns: total = product of (end/start)
    ratio = 1.0
    for s_start, s_end in segments:
        if s_start <= 0:
            continue
        ratio *= (s_end / s_start)
    return ratio, len(segments)


def _walk_segments_asymmetric(bars: pd.DataFrame, entry_price: float,
                              exit_price: float) -> tuple[float, int]:
    """Asymmetric "flatten winners only" — Friday close ends a segment ONLY
    if the position is currently in profit (cumulative compounded return > 1).
    Losing positions hold through; no segment break.

    Returns (total_return_ratio, n_segments).
    """
    if bars.empty:
        return (exit_price / entry_price if entry_price else 1.0), 1

    bars = bars.sort_values("date").reset_index(drop=True)
    bars["weekday"] = bars["date"].dt.weekday

    segments: list[tuple[float, float]] = []
    seg_start = entry_price
    cum_ratio_before_seg = 1.0  # Cumulative return ratio of all CLOSED segments

    for i in range(len(bars)):
        wd = int(bars.at[i, "weekday"])
        if wd == 4 and i < len(bars) - 1:
            seg_end = float(bars.at[i, "close"])
            # Check if THIS segment alone is in profit (seg_end > seg_start).
            # The "in profit" check for flatten-winners is about the live
            # position's MTM vs cost basis — equivalent to seg_end > seg_start
            # for the current segment.
            if seg_start > 0 and seg_end > seg_start:
                segments.append((seg_start, seg_end))
                cum_ratio_before_seg *= (seg_end / seg_start)
                if i + 1 < len(bars):
                    seg_start = float(bars.at[i + 1, "open"])
            # else: hold through — no segment break

    segments.append((seg_start, exit_price))

    ratio = 1.0
    for s_start, s_end in segments:
        if s_start <= 0:
            continue
        ratio *= (s_end / s_start)
    return ratio, len(segments)


SIMULATORS = {
    "uniform": _walk_segments_uniform,
    "asymmetric": _walk_segments_asymmetric,
}


# ---------------------------------------------------------------------------
# Driver: stream baseline ledger → flatten ledger
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rule", required=True, choices=sorted(SIMULATORS.keys()))
    parser.add_argument("--input", default=str(
        Path(REPO_ROOT) / "research" / "weekend_flatten_equities_v1"
        / "baseline_ledger_weekly.csv"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    store = DuckDBStore(settings.duckdb_path, read_only=True)
    simulator = SIMULATORS[args.rule]

    # Per-symbol cache of OHLCV (df sorted by date) so repeated lookups for the
    # same symbol are cheap.
    symbol_cache: dict[str, pd.DataFrame] = {}

    def _get_bars_for_window(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = symbol_cache.get(symbol)
        if df is None:
            data = store.load_symbol_dict(symbol)
            if not data or not data.get("days"):
                df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            else:
                df = pd.DataFrame(data["days"])
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
            symbol_cache[symbol] = df
        mask = (df["date"] >= pd.to_datetime(start_date)) & (df["date"] <= pd.to_datetime(end_date))
        return df[mask].reset_index(drop=True)

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    total_in = 0
    total_with_weekend = 0
    total_modified = 0
    total_unchanged = 0

    with in_path.open() as fin, out_path.open("w", newline="") as fout:
        reader = csv.DictReader(fin)
        out_cols = (reader.fieldnames or []) + ["n_segments", "flatten_rule_applied",
                                                "original_blended_pnl_pct"]
        writer = csv.DictWriter(fout, fieldnames=out_cols)
        writer.writeheader()

        for row in reader:
            total_in += 1
            spans = int(row.get("spans_weekends") or 0)
            try:
                entry_price = float(row.get("entry_price") or 0)
                # Take the trade's REALIZED exit (already in the baseline ledger
                # as the blended exit synthesized from t1/t2 fills).
                blended = float(row.get("blended_pnl_pct") or 0)
                original_exit = entry_price * (1 + blended / 100)
            except (TypeError, ValueError):
                # Malformed row — copy through with zero modification
                row["n_segments"] = 1
                row["flatten_rule_applied"] = "n/a"
                row["original_blended_pnl_pct"] = row.get("blended_pnl_pct", "")
                writer.writerow(row)
                continue

            if spans <= 0 or row.get("entry_date") in (None, "") or \
                    row.get("exit_date") in (None, ""):
                # No weekend spanned (or missing dates) — pass through unchanged
                row["n_segments"] = 1
                row["flatten_rule_applied"] = "passthrough"
                row["original_blended_pnl_pct"] = row.get("blended_pnl_pct", "")
                writer.writerow(row)
                total_unchanged += 1
                continue

            total_with_weekend += 1

            bars = _get_bars_for_window(row["symbol"], row["entry_date"], row["exit_date"])
            if bars.empty or entry_price <= 0:
                row["n_segments"] = 1
                row["flatten_rule_applied"] = "no_data"
                row["original_blended_pnl_pct"] = row.get("blended_pnl_pct", "")
                writer.writerow(row)
                continue

            new_ratio, n_segments = simulator(bars, entry_price, original_exit)
            new_blended_pct = (new_ratio - 1.0) * 100.0
            row["original_blended_pnl_pct"] = row.get("blended_pnl_pct", "")
            row["blended_pnl_pct"] = f"{new_blended_pct}"
            row["n_segments"] = n_segments
            row["flatten_rule_applied"] = args.rule
            writer.writerow(row)
            total_modified += 1

            if total_in % 1000 == 0:
                elapsed = time.time() - t0
                print(f"  [{total_in}] elapsed={elapsed:.1f}s  "
                      f"with_weekend={total_with_weekend}  modified={total_modified}",
                      flush=True)

    store.close()
    print(f"\nDone. Read {total_in} baseline trades:")
    print(f"  spans_weekends>0:  {total_with_weekend}")
    print(f"  modified by rule:  {total_modified}")
    print(f"  passthrough:       {total_unchanged}")
    print(f"  Output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
