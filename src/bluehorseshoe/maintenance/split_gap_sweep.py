"""Split-gap sweep — read-only unadjusted-corporate-action finder.

Identifies single-bar price discontinuities whose signature is an *unadjusted split /
ratio change* rather than a real market move: the whole OHLC bar is rescaled by a near-
constant multiple while volume stays continuous. The data-provider applied a corporate-
action factor going forward but never back-adjusted the history (or vice-versa), leaving
a ~Nx step partway through the series.

Worked example (why this matters): AZN stepped from a 83.83 close on 2025-10-16 to 165.91
on 2025-10-17 — open/high/low/close all x~1.97 on *lower* volume. AstraZeneca did not
double in a day; the pre-step history is simply un-rescaled. That step sat inside the
252-bar window feeding ``RangeSupportStrategy`` and silently corrupted ATR / the Kaufman
efficiency-ratio gate, surfacing a bogus "support" entry to a human in the daily report.
The range-bound gate only caught it *reactively* (the step spiked ER); a flat-but-rescaled
series would sail straight through. This sweep is the deterministic catch.

Discriminator (why it does not fire on real moves):
  * magnitude   — close moves by >= ``factor-min`` (default 1.5x, i.e. +50% / -33%), AND
  * uniformity  — open/high/low/close each scale by ~the *same* factor (relative spread of
                  the four ratios <= ``uniform-max``). A real earnings/news shock gaps the
                  open one amount and travels a wide, uneven intraday range; a pure rescale
                  moves all four fields in lockstep.
``vol_ratio`` (jump-bar volume / trailing-20 average) is reported as confidence context: a
real move that big spikes volume, an adjustment artifact does not.

REPORT-ONLY: mutates nothing. Writes a candidate CSV and prints a summary so the list can
be eyeballed before remediation (per-symbol re-backfill, or a quarantine flag). Companion
to delisting_sweep.py; same conventions. See docs/planning/DELISTING_SWEEP.md neighbourhood.

Usage:
    ./run.sh python src/bluehorseshoe/maintenance/split_gap_sweep.py \
        [--factor-min 1.5] [--uniform-max 0.08] [--min-prev-close 1.0] \
        [--since YYYY-MM-DD] [--symbols AZN,FOO] [--out PATH]
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, NamedTuple

import duckdb
import pandas as pd

from bluehorseshoe.cli.context import create_cli_context
from bluehorseshoe.core.config import get_settings
from bluehorseshoe.maintenance.delisting_sweep import KNOWN_TEST_SYMBOLS, is_test_ticker

# A move must clear this multiple (up or down) to be a split candidate at all.
DEFAULT_FACTOR_MIN = 1.5          # >= +50% or <= -33% in a single bar
# The four OHLC ratios must agree to within this *relative* spread to look like a rescale.
DEFAULT_UNIFORM_MAX = 0.08        # (max_ratio - min_ratio) / mean_ratio
# A real corporate action lands on a tidy ratio (2:1, 1:10, 3:2...). Reject steps whose
# close ratio is not within this relative distance of any such factor — that filters out
# pump-and-dump spikes and bad-data teleports (huge ratios that match no real split).
DEFAULT_MAX_FACTOR_ERR = 0.12
# Skip sub-dollar names: penny-stock tick noise produces meaningless ratios.
DEFAULT_MIN_PREV_CLOSE = 1.0

# Common corporate-action factors we snap to, to label the suspected action.
# Covers ordinary splits, 3:2 / ADR-ratio changes, and distressed reverse splits to 1:20.
NICE_FACTORS = (
    0.05, 1 / 15, 1 / 12, 0.1, 0.125, 1 / 6, 0.2, 0.25, 1 / 3, 0.5, 2 / 3, 0.75,
    1.5, 4 / 3, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0,
)

# Benchmarks / regime ETFs — surface but never auto-act on these.
PROTECTED_SYMBOLS = {"SPY", "QQQ", "DIA", "IWM"}

logger = logging.getLogger(__name__)


class Criteria(NamedTuple):
    """Detection thresholds, bundled so they thread cleanly through the sweep."""
    factor_min: float = DEFAULT_FACTOR_MIN
    uniform_max: float = DEFAULT_UNIFORM_MAX
    max_factor_err: float = DEFAULT_MAX_FACTOR_ERR
    min_prev_close: float = DEFAULT_MIN_PREV_CLOSE


def find_split_gaps(
    con: duckdb.DuckDBPyConnection,
    crit: Criteria,
    since: str | None = None,
    symbols: List[str] | None = None,
) -> pd.DataFrame:
    """Single-bar transitions that look like an unadjusted split/ratio rescale.

    A candidate bar has (a) a close that moved by >= ``factor_min`` (up or down) vs the
    prior bar, and (b) open/high/low/close that each scaled by ~the same factor
    (relative spread of the four ratios <= ``uniform_max``). Returns one row per
    suspected step with the ratios, the OHLC spread, and the volume context.
    """
    filters = ["pc IS NOT NULL", "pc >= ?", "po > 0", "ph > 0", "pl > 0", "close > 0"]
    params: List[Any] = [crit.min_prev_close]
    if KNOWN_TEST_SYMBOLS:  # exchange test issues (Z*ZZT family) — never real listings
        placeholders = ",".join(["?"] * len(KNOWN_TEST_SYMBOLS))
        filters.append(f"symbol NOT IN ({placeholders})")
        params.extend(sorted(KNOWN_TEST_SYMBOLS))
    if since:
        filters.append("date >= ?")
        params.append(since)
    if symbols:
        placeholders = ",".join(["?"] * len(symbols))
        filters.append(f"symbol IN ({placeholders})")
        params.extend(symbols)
    where = " AND ".join(filters)
    # factor_min applies to the magnitude (max of move and its inverse); uniform_max to spread.
    params.extend([crit.factor_min, crit.uniform_max])

    sql = f"""
        WITH base AS (
            SELECT symbol, date, open, high, low, close, volume,
                   lag(open)  OVER w AS po,
                   lag(high)  OVER w AS ph,
                   lag(low)   OVER w AS pl,
                   lag(close) OVER w AS pc,
                   avg(volume) OVER (
                       PARTITION BY symbol ORDER BY date
                       ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                   ) AS vol_avg20
            FROM ohlcv
            WINDOW w AS (PARTITION BY symbol ORDER BY date)
        ),
        r AS (
            SELECT symbol, date, pc AS prev_close, close, volume, vol_avg20,
                   close / pc AS cr,
                   open  / po AS o_r,
                   high  / ph AS h_r,
                   low   / pl AS l_r
            FROM base
            WHERE {where}
        )
        SELECT symbol, date, prev_close, close,
               cr AS close_ratio, o_r AS open_ratio, h_r AS high_ratio, l_r AS low_ratio,
               (greatest(cr, o_r, h_r, l_r) - least(cr, o_r, h_r, l_r))
                   / ((cr + o_r + h_r + l_r) / 4.0) AS ohlc_spread_rel,
               volume / nullif(vol_avg20, 0) AS vol_ratio
        FROM r
        WHERE greatest(cr, 1.0 / cr) >= ?
          AND (greatest(cr, o_r, h_r, l_r) - least(cr, o_r, h_r, l_r))
                  / ((cr + o_r + h_r + l_r) / 4.0) <= ?
        ORDER BY symbol, date
    """
    return con.execute(sql, params).fetchdf()


def _nearest_nice_factor(ratio: float) -> tuple[float, float]:
    """Closest common corporate-action factor and the relative error to it."""
    best = min(NICE_FACTORS, key=lambda f: abs(f - ratio))
    return best, abs(best - ratio) / best


def annotate(df: pd.DataFrame, database) -> pd.DataFrame:
    """Label suspected action + snap to a nice factor; add Mongo name/exchange/active."""
    if df.empty:
        for col in ("suspected", "nearest_factor", "factor_err", "vol_quiet",
                    "name", "exchange", "active", "protected"):
            df[col] = pd.Series(dtype=object)
        return df

    factors = df["close_ratio"].map(_nearest_nice_factor)
    df["nearest_factor"] = [round(f, 4) for f, _ in factors]
    df["factor_err"] = [round(e, 4) for _, e in factors]
    df["suspected"] = df["close_ratio"].map(
        lambda r: "unadjusted_split" if r > 1 else "unadjusted_reverse_split"
    )
    # A genuine move of this size spikes volume; an adjustment artifact does not.
    df["vol_quiet"] = df["vol_ratio"].map(lambda v: bool(pd.notna(v) and v < 2.0))

    symbols = sorted(set(df["symbol"]))
    meta: Dict[str, Dict[str, Any]] = {
        d["symbol"]: d
        for d in database.symbols.find(
            {"symbol": {"$in": symbols}},
            {"symbol": 1, "active": 1, "name": 1, "exchange": 1, "_id": 0},
        )
    }
    df["name"] = df["symbol"].map(lambda s: meta.get(s, {}).get("name"))
    df["exchange"] = df["symbol"].map(lambda s: meta.get(s, {}).get("exchange"))
    df["active"] = df["symbol"].map(lambda s: meta.get(s, {}).get("active"))
    df["protected"] = df["symbol"].isin(PROTECTED_SYMBOLS)
    return df


def _print_summary(df: pd.DataFrame, crit: Criteria, since: str | None,
                   symbols: List[str] | None, out_path: Path) -> None:
    print("\n=== Split-gap sweep (read-only) ===")
    print(f"Criteria: |close move| >= {crit.factor_min}x, OHLC relative spread <= {crit.uniform_max}"
          f", factor_err <= {crit.max_factor_err}, prev_close >= {crit.min_prev_close}"
          + (f", since {since}" if since else "")
          + (f", symbols={','.join(symbols)}" if symbols else ""))

    if df.empty:
        print("No suspected unadjusted corporate-action steps found.")
        print(f"\nMutated nothing. Empty candidate list written to: {out_path}")
        return

    n_sym = df["symbol"].nunique()
    active = df[df["active"].eq(True)]
    quiet = df[df["vol_quiet"]]
    print(f"Suspected steps: {len(df)} across {n_sym} symbols")
    print(f"  high-confidence (volume did NOT spike, vol_ratio<2): {len(quiet)}")
    print(f"  on currently-active symbols:                         {active['symbol'].nunique()} symbols")

    show = df.copy()
    show = show.sort_values(["vol_quiet", "close_ratio"], ascending=[False, False]).head(20)
    cols = ["symbol", "date", "prev_close", "close", "close_ratio", "nearest_factor",
            "factor_err", "ohlc_spread_rel", "vol_ratio", "vol_quiet", "suspected"]
    fmt = show[cols].copy()
    for c in ("prev_close", "close"):
        fmt[c] = fmt[c].map(lambda x: f"{x:.2f}")
    for c in ("close_ratio", "ohlc_spread_rel", "vol_ratio"):
        fmt[c] = fmt[c].map(lambda x: f"{x:.4f}" if pd.notna(x) else "n/a")
    print("\nSample (volume-quiet first, then biggest factor):")
    print(fmt.to_string(index=False))
    print(f"\nFull candidate list ({len(df)} rows) written to: {out_path}")
    print("Mutated nothing. Remediation per symbol: re-backfill with adjusted history "
          "(./run.sh python src/main.py -b --symbols SYM), or quarantine until fixed.")


def run(
    crit: Criteria = Criteria(),
    since: str | None = None,
    symbols: List[str] | None = None,
    out: str | None = None,
) -> pd.DataFrame:
    """Find suspected unadjusted split/ratio steps, annotate, write CSV, print. Read-only."""
    settings = get_settings()
    db_path = settings.duckdb_path
    if not Path(db_path).exists():
        raise FileNotFoundError(f"DuckDB store not found at {db_path}")

    out_path = Path(out) if out else Path(settings.logs_path) / "split_gap_candidates.csv"

    con = duckdb.connect(db_path, read_only=True)
    try:
        candidates = find_split_gaps(con, crit, since, symbols)
    finally:
        con.close()

    with create_cli_context() as ctx:
        candidates = annotate(candidates, ctx.db)

    # Keep only steps near a real corporate-action ratio, and drop name-based test issues
    # (the Z*ZZT symbols are already excluded in SQL; this catches "TEST STOCK" by name).
    if not candidates.empty:
        near = candidates["factor_err"] <= crit.max_factor_err
        not_test = ~candidates.apply(
            lambda r: is_test_ticker(r["symbol"], r["name"] if isinstance(r["name"], str) else None),
            axis=1,
        )
        candidates = candidates[near & not_test].reset_index(drop=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(out_path, index=False)
    _print_summary(candidates, crit, since, symbols, out_path)
    return candidates


def main() -> None:
    """CLI entry point for the read-only split-gap finder."""
    parser = argparse.ArgumentParser(description="Split-gap sweep — read-only unadjusted-corporate-action finder.")
    parser.add_argument("--factor-min", type=float, default=DEFAULT_FACTOR_MIN,
                        help=f"Min single-bar close multiple, up or down (default {DEFAULT_FACTOR_MIN}).")
    parser.add_argument("--uniform-max", type=float, default=DEFAULT_UNIFORM_MAX,
                        help=f"Max relative spread of the 4 OHLC ratios (default {DEFAULT_UNIFORM_MAX}).")
    parser.add_argument("--max-factor-err", type=float, default=DEFAULT_MAX_FACTOR_ERR,
                        help=f"Max relative distance of close ratio from a real split factor (default {DEFAULT_MAX_FACTOR_ERR}).")
    parser.add_argument("--min-prev-close", type=float, default=DEFAULT_MIN_PREV_CLOSE,
                        help=f"Skip steps where prior close < this (penny noise; default {DEFAULT_MIN_PREV_CLOSE}).")
    parser.add_argument("--since", type=str, default=None, help="Only scan bars on/after this date (YYYY-MM-DD).")
    parser.add_argument("--symbols", type=str, default=None, help="Comma-separated symbol allow-list (default: whole universe).")
    parser.add_argument("--out", type=str, default=None, help="Output CSV path (default src/logs/split_gap_candidates.csv).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    crit = Criteria(factor_min=args.factor_min, uniform_max=args.uniform_max,
                    max_factor_err=args.max_factor_err, min_prev_close=args.min_prev_close)
    run(crit=crit, since=args.since, symbols=syms, out=args.out)


if __name__ == "__main__":
    main()
