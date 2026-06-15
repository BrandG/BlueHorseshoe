"""Delisting sweep — P0: read-only frozen-tail finder.

Identifies symbols whose most-recent N sessions are all untraded (volume 0) — the
data-provider signature of a delisted/halted name, where the last close is carried
forward on current-dated rows (e.g. THR/Thermon froze at $61.14 after its ~2026-05-29
acquisition). These bloat the active universe and feed the market-cap filter zombie
overviews.

P0 is REPORT-ONLY: it mutates nothing. It writes a candidate CSV and prints a
summary so the list can be eyeballed before later phases add AlphaVantage
LISTING_STATUS confirmation (P1) and soft-deactivation via ``symbols.active=False``
(P2). See docs/planning/DELISTING_SWEEP.md.

Usage:
    ./run.sh python src/bluehorseshoe/maintenance/delisting_sweep.py [--min-untraded N] [--out PATH]
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List

import duckdb
import pandas as pd

from bluehorseshoe.cli.context import create_cli_context
from bluehorseshoe.core.config import get_settings

# Census reported at every run so a threshold choice is grounded in current data.
CENSUS_THRESHOLDS = (1, 5, 10, 20)
DEFAULT_MIN_UNTRADED = 10

# Benchmarks / regime ETFs — never sweep these even if a feed glitch freezes them.
PROTECTED_SYMBOLS = {"SPY", "QQQ", "DIA", "IWM"}

logger = logging.getLogger(__name__)


def untraded_tail_census(con: duckdb.DuckDBPyConnection) -> Dict[int, int]:
    """Count symbols whose leading (most-recent) zero-volume run is >= each threshold."""
    sql = """
        WITH r AS (
            SELECT symbol, volume,
                   row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
            FROM ohlcv
        ),
        per AS (
            SELECT symbol,
                   COALESCE(min(rn) FILTER (WHERE volume > 0) - 1, count(*)) AS days_untraded
            FROM r GROUP BY symbol
        )
        SELECT
            count(*) FILTER (WHERE days_untraded >= 1)  AS n1,
            count(*) FILTER (WHERE days_untraded >= 5)  AS n5,
            count(*) FILTER (WHERE days_untraded >= 10) AS n10,
            count(*) FILTER (WHERE days_untraded >= 20) AS n20,
            count(*) AS total
        FROM per
    """
    row = con.execute(sql).fetchone()
    return {1: row[0], 5: row[1], 10: row[2], 20: row[3], 0: row[4]}


def find_untraded_tail_candidates(
    con: duckdb.DuckDBPyConnection, min_untraded: int
) -> pd.DataFrame:
    """Symbols with an untraded tail >= ``min_untraded`` sessions.

    ``days_untraded`` is the length of the leading zero-volume run (how many
    most-recent bars show no trading). A symbol that never traded at all reports
    ``days_untraded == total_rows``. Returns columns:
    symbol, days_untraded, last_date, last_traded_date, last_close, total_rows.
    """
    sql = """
        WITH r AS (
            SELECT symbol, date, close, volume,
                   row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
            FROM ohlcv
        )
        SELECT
            symbol,
            COALESCE(min(rn) FILTER (WHERE volume > 0) - 1, count(*)) AS days_untraded,
            max(date)                              AS last_date,
            max(date) FILTER (WHERE volume > 0)    AS last_traded_date,
            arg_max(close, date)                   AS last_close,
            count(*)                               AS total_rows
        FROM r
        GROUP BY symbol
        HAVING COALESCE(min(rn) FILTER (WHERE volume > 0) - 1, count(*)) >= ?
        ORDER BY days_untraded DESC, symbol
    """
    return con.execute(sql, [min_untraded]).fetchdf()


def annotate_with_mongo(df: pd.DataFrame, database) -> pd.DataFrame:
    """Add active flag, name, exchange, and zombie-overview marker from MongoDB.

    ``has_zombie_mcap`` flags candidates that still carry a MarketCapitalization in
    ``symbol_overviews`` — these are the ones currently passing the prediction
    market-cap filter despite being untradeable.
    """
    symbols: List[str] = df["symbol"].tolist()
    if not symbols:
        for col in ("active", "name", "exchange", "has_zombie_mcap", "protected"):
            df[col] = pd.Series(dtype=object)
        return df

    meta: Dict[str, Dict[str, Any]] = {
        d["symbol"]: d
        for d in database.symbols.find(
            {"symbol": {"$in": symbols}},
            {"symbol": 1, "active": 1, "name": 1, "exchange": 1, "_id": 0},
        )
    }
    mcap_symbols = {
        d["symbol"]
        for d in database.symbol_overviews.find(
            {
                "symbol": {"$in": symbols},
                "MarketCapitalization": {"$exists": True, "$nin": [None, "", "0", "None"]},
            },
            {"symbol": 1, "_id": 0},
        )
    }
    df["active"] = df["symbol"].map(lambda s: meta.get(s, {}).get("active"))
    df["name"] = df["symbol"].map(lambda s: meta.get(s, {}).get("name"))
    df["exchange"] = df["symbol"].map(lambda s: meta.get(s, {}).get("exchange"))
    df["has_zombie_mcap"] = df["symbol"].isin(mcap_symbols)
    df["protected"] = df["symbol"].isin(PROTECTED_SYMBOLS)
    return df


def _print_summary(census: Dict[int, int], df: pd.DataFrame, min_untraded: int, out_path: Path) -> None:
    total = census[0]
    print("\n=== Delisting sweep — P0 (read-only) ===")
    print(f"Universe (DuckDB symbols): {total}")
    print("Untraded-tail census (most-recent N sessions all volume 0):")
    for n in CENSUS_THRESHOLDS:
        print(f"  >= {n:>2} sessions: {census[n]:>5}")

    active_mask = df["active"].eq(True)  # True only; False/None (unknown) excluded
    active = df[active_mask]
    inactive = df[~active_mask]
    protected = df[df["protected"]]
    zombie = active[active["has_zombie_mcap"]]
    print(f"\nCandidates at N>={min_untraded}: {len(df)}")
    print(f"  already active=False (no-op for sweep): {len(inactive)}")
    print(f"  ACTIVE (sweep would target):            {len(active)}")
    print(f"    of which carry a zombie market-cap:   {len(zombie)}  (currently pass the mcap filter)")
    print(f"  protected (never swept):                {len(protected)}  {sorted(protected['symbol'].tolist())}")

    sample = active.head(15)
    if not sample.empty:
        print("\nSample (most-untraded first):")
        cols = ["symbol", "days_untraded", "last_traded_date", "last_close", "has_zombie_mcap", "exchange", "name"]
        print(sample[cols].to_string(index=False))
    print(f"\nFull candidate list ({len(df)} rows) written to: {out_path}")
    print("P0 mutated nothing. Next: P1 (AlphaVantage LISTING_STATUS confirmation).")


def run(min_untraded: int = DEFAULT_MIN_UNTRADED, out: str | None = None) -> pd.DataFrame:
    """Find untraded-tail candidates, annotate, write CSV, print summary. Read-only."""
    settings = get_settings()
    db_path = settings.duckdb_path
    if not Path(db_path).exists():
        raise FileNotFoundError(f"DuckDB store not found at {db_path}")

    out_path = Path(out) if out else Path(settings.logs_path) / "delisting_sweep_candidates.csv"

    con = duckdb.connect(db_path, read_only=True)
    try:
        census = untraded_tail_census(con)
        candidates = find_untraded_tail_candidates(con, min_untraded)
    finally:
        con.close()

    with create_cli_context() as ctx:
        candidates = annotate_with_mongo(candidates, ctx.db)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(out_path, index=False)
    _print_summary(census, candidates, min_untraded, out_path)
    return candidates


def main() -> None:
    """CLI entry point for the read-only delisting-sweep finder."""
    parser = argparse.ArgumentParser(description="Delisting sweep P0 — read-only frozen-tail finder.")
    parser.add_argument(
        "--min-untraded", type=int, default=DEFAULT_MIN_UNTRADED,
        help=f"Min consecutive untraded (zero-volume) most-recent sessions to flag (default {DEFAULT_MIN_UNTRADED}).",
    )
    parser.add_argument("--out", type=str, default=None, help="Output CSV path (default src/logs/delisting_sweep_candidates.csv).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    run(min_untraded=args.min_untraded, out=args.out)


if __name__ == "__main__":
    main()
