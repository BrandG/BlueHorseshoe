"""
DuckDB-based storage backend for OHLCV time-series data.

Replaces MongoDB's nested document arrays with a flat, columnar table
optimised for analytical reads (bulk symbol loads, date-range filters,
universe snapshots).

Usage:
    store = DuckDBStore("/path/to/ohlcv.duckdb")
    store_ro = DuckDBStore("/path/to/ohlcv.duckdb", read_only=True)
    store.save_symbol("AAPL", df, full_name="Apple Inc.")
    df = store.load_symbol("AAPL", start_date="2024-01-01")
    store.close()
"""
import logging
from pathlib import Path
import threading
from typing import Dict, List, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# Core OHLCV columns — the only columns stored in DuckDB.
# Indicator columns (RSI, MACD, etc.) are NOT persisted because they are
# always recomputed from raw OHLCV during ingestion via get_technical_indicators().
_SCHEMA_COLUMNS = [
    ("symbol", "VARCHAR NOT NULL"),
    ("date", "VARCHAR NOT NULL"),
    ("open", "DOUBLE"),
    ("high", "DOUBLE"),
    ("low", "DOUBLE"),
    ("close", "DOUBLE"),
    ("volume", "DOUBLE"),
]

# Set of column names accepted by save_symbol() — anything else is dropped.
_CORE_COLUMNS = {"symbol", "date", "open", "high", "low", "close", "volume"}

_FUNDAMENTALS_COLUMNS = [
    ("symbol", "VARCHAR NOT NULL"),
    ("fiscalDateEnding", "DATE NOT NULL"),
    ("reportedDate", "DATE NOT NULL"),
    ("altman_z", "DOUBLE"),
    ("fscore", "INTEGER"),
    ("n_avail", "INTEGER"),
    ("ni_ttm", "DOUBLE"),
    ("ocf_ttm", "DOUBLE"),
    ("rev_ttm", "DOUBLE"),
    ("ebit_ttm", "DOUBLE"),
    ("total_assets", "DOUBLE"),
    ("total_liabilities", "DOUBLE"),
    ("total_debt", "DOUBLE"),
    ("current_assets", "DOUBLE"),
    ("current_liabilities", "DOUBLE"),
    ("retained_earnings", "DOUBLE"),
    ("shares_out", "DOUBLE"),
]

_FUNDAMENTALS_COLUMN_NAMES = [name for name, _ in _FUNDAMENTALS_COLUMNS]


class DuckDBStore:
    """Embedded columnar store for OHLCV + indicator data."""

    def __init__(self, db_path: str = ":memory:", read_only: bool = False):
        self._db_path = db_path
        self._read_only = read_only
        self._con = duckdb.connect(db_path, read_only=read_only)
        self._lock = threading.RLock()
        if not read_only:
            self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        cols_sql = ", ".join(f"{name} {dtype}" for name, dtype in _SCHEMA_COLUMNS)
        # No primary key — DuckDB's columnar zone maps handle our WHERE-based
        # queries efficiently, and the ART index for a PK on 28M+ rows costs
        # ~1.6 GB (3x the actual data).  Uniqueness is enforced by the
        # DELETE-before-INSERT pattern in save_symbol().
        self._con.execute(f"""
            CREATE TABLE IF NOT EXISTS ohlcv ({cols_sql})
        """)

        self._con.execute("""
            CREATE TABLE IF NOT EXISTS symbol_metadata (
                symbol       VARCHAR PRIMARY KEY,
                full_name    VARCHAR,
                last_updated VARCHAR
            )
        """)

        fund_cols_sql = ", ".join(f'"{name}" {dtype}' for name, dtype in _FUNDAMENTALS_COLUMNS)
        self._con.execute(f"""
            CREATE TABLE IF NOT EXISTS fundamentals ({fund_cols_sql})
        """)

    @staticmethod
    def _with_altman_z(df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy with book-only Altman-Z'' computed from PIT statement fields."""
        out = df.copy()
        wc = out["current_assets"] - out["current_liabilities"]
        ta = out["total_assets"]
        tl = out["total_liabilities"]
        equity_book = ta - tl
        out["altman_z"] = (
            6.56 * (wc / ta)
            + 3.26 * (out["retained_earnings"] / ta)
            + 6.72 * (out["ebit_ttm"] / ta)
            + 1.05 * (equity_book / tl)
        )
        return out

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def save_symbol(self, symbol: str, df: pd.DataFrame, full_name: str = "") -> None:
        """
        Upsert OHLCV rows for *symbol* from *df*.

        Only core OHLCV columns (date, open, high, low, close, volume) are
        persisted.  Indicator columns in *df* are silently dropped — they are
        always recomputed from raw OHLCV during ingestion.

        Thread-safe: serialized via _lock since the DuckDB Python
        connection object is not thread-safe.
        """
        if self._read_only:
            raise RuntimeError("Cannot write to a read-only DuckDBStore")

        if df is None or df.empty:
            return

        df = df.copy()
        df["symbol"] = symbol

        # Keep only columns that exist in the schema
        keep = [c for c in df.columns if c in _CORE_COLUMNS]
        df = df[keep]

        df_cols = list(df.columns)
        cols_sql = ", ".join(f'"{c}"' for c in df_cols)

        with self._lock:
            # Delete existing rows for this symbol+date combo, then insert
            # (DuckDB INSERT OR REPLACE requires matching all columns)
            self._con.execute(
                "DELETE FROM ohlcv WHERE symbol = ? AND date IN (SELECT date FROM df)",
                [symbol],
            )
            self._con.execute(f"INSERT INTO ohlcv ({cols_sql}) SELECT {cols_sql} FROM df")

            # Update metadata
            ts = pd.Timestamp.now().isoformat()
            self._con.execute("""
                INSERT OR REPLACE INTO symbol_metadata (symbol, full_name, last_updated)
                VALUES (?, ?, ?)
            """, [symbol, full_name or symbol, ts])

    def save_fundamentals(self, df: pd.DataFrame) -> None:
        """Upsert PIT fundamentals rows keyed by symbol + fiscalDateEnding."""
        if self._read_only:
            raise RuntimeError("Cannot write to a read-only DuckDBStore")
        if df is None or df.empty:
            return

        df = self._with_altman_z(df) if "altman_z" not in df.columns else df.copy()
        df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"]).dt.date
        df["reportedDate"] = pd.to_datetime(df["reportedDate"]).dt.date

        for col in _FUNDAMENTALS_COLUMN_NAMES:
            if col not in df.columns:
                df[col] = None
        df = df[_FUNDAMENTALS_COLUMN_NAMES]
        cols_sql = ", ".join(f'"{c}"' for c in _FUNDAMENTALS_COLUMN_NAMES)

        with self._lock:
            self._con.execute("""
                DELETE FROM fundamentals
                WHERE (symbol, fiscalDateEnding) IN (
                    SELECT symbol, fiscalDateEnding FROM df
                )
            """)
            self._con.execute(f"""
                INSERT INTO fundamentals ({cols_sql})
                SELECT {cols_sql} FROM df
            """)

    def seed_fundamentals_from_parquet(self, parquet_path: str = "data/fundamentals.parquet") -> int:
        """Load the validated research fundamentals parquet into DuckDB."""
        path = Path(parquet_path)
        if not path.exists():
            raise FileNotFoundError(f"Fundamentals parquet not found: {parquet_path}")
        df = pd.read_parquet(path)
        before = self.fundamentals_row_count()
        self.save_fundamentals(df)
        after = self.fundamentals_row_count()
        return after - before

    # ------------------------------------------------------------------
    # Read — single symbol
    # ------------------------------------------------------------------
    def load_symbol(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Load OHLCV data for a single symbol.

        Returns a DataFrame sorted by date, or ``None`` if no rows match.
        """
        clauses = ["symbol = ?"]
        params: list = [symbol]

        if start_date:
            clauses.append("date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("date <= ?")
            params.append(end_date)

        where = " AND ".join(clauses)
        with self._lock:
            df = self._con.execute(
                f"SELECT * FROM ohlcv WHERE {where} ORDER BY date", params
            ).fetchdf()

        if df.empty:
            return None

        # Drop the symbol column — callers already know the symbol
        df = df.drop(columns=["symbol"], errors="ignore")
        return df

    def load_symbol_dict(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Returns ``{'days': [row_dicts], 'full_name': ...}`` dict format.
        """
        df = self.load_symbol(symbol, start_date=start_date, end_date=end_date)
        if df is None:
            return {}

        # Replace NaN with None for JSON-safe dicts, matching MongoDB behaviour
        days = df.where(df.notna(), None).to_dict(orient="records")

        meta = self.get_metadata(symbol)
        full_name = meta.get("full_name", symbol) if meta else symbol

        return {"days": days, "full_name": full_name, "symbol": symbol}

    # ------------------------------------------------------------------
    # Read — bulk
    # ------------------------------------------------------------------
    def load_symbols_bulk(
        self,
        symbols: List[str],
        start_date: Optional[str] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Load OHLCV data for multiple symbols in a single scan.

        Returns a dict mapping symbol → DataFrame.
        """
        if not symbols:
            return {}

        placeholders = ", ".join(["?"] * len(symbols))
        params: list = list(symbols)

        where = f"symbol IN ({placeholders})"
        if start_date:
            where += " AND date > ?"
            params.append(start_date)

        with self._lock:
            df = self._con.execute(
                f"SELECT * FROM ohlcv WHERE {where} ORDER BY symbol, date", params
            ).fetchdf()

        if df.empty:
            return {}

        result: Dict[str, pd.DataFrame] = {}
        for sym, group in df.groupby("symbol"):
            grp = group.drop(columns=["symbol"]).reset_index(drop=True)
            result[str(sym)] = grp
        return result

    def load_solvency_asof(self, date: str) -> Dict[str, float]:
        """
        Load latest Altman-Z'' by symbol with reportedDate <= date.

        This is point-in-time safe: rows reported after the as-of date are never
        returned.

        Fail-safe: a read-only store opened on a DB that predates the fundamentals
        table (``_init_schema`` is skipped for read-only connections) has no such
        table. Rather than crash ``-p`` (the loader runs regardless of the solvency
        flag), return ``{}`` — "no fundamentals known" → every candidate is kept,
        matching the unknown-Z policy.
        """
        with self._lock:
            table_exists = self._con.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'fundamentals' LIMIT 1"
            ).fetchone()
            if not table_exists:
                return {}
            df = self._con.execute("""
                SELECT symbol, altman_z
                FROM (
                    SELECT
                        symbol,
                        altman_z,
                        reportedDate,
                        ROW_NUMBER() OVER (
                            PARTITION BY symbol
                            ORDER BY reportedDate DESC, fiscalDateEnding DESC
                        ) AS rn
                    FROM fundamentals
                    WHERE reportedDate <= CAST(? AS DATE)
                      AND altman_z IS NOT NULL
                )
                WHERE rn = 1
            """, [date]).fetchdf()
        if df.empty:
            return {}
        return {str(row["symbol"]): float(row["altman_z"]) for _, row in df.iterrows()}

    def get_latest_fundamental_reported_dates(self) -> Dict[str, str]:
        """Return latest fundamentals reportedDate by symbol."""
        with self._lock:
            df = self._con.execute("""
                SELECT symbol, MAX(reportedDate) AS reportedDate
                FROM fundamentals
                GROUP BY symbol
            """).fetchdf()
        if df.empty:
            return {}
        return {
            str(row["symbol"]): str(row["reportedDate"])[:10]
            for _, row in df.iterrows()
            if pd.notna(row["reportedDate"])
        }

    def load_universe_snapshot(
        self,
        date: str,
        min_price: float = 1.0,
    ) -> List[Dict]:
        """
        Load one-day OHLCV bars for the entire universe, filtered by price.

        Returns a list of flat dicts suitable for DataFrame construction.
        """
        with self._lock:
            df = self._con.execute("""
                SELECT symbol, date, open, high, low, close, volume
                FROM ohlcv
                WHERE date = ? AND close >= ?
                ORDER BY symbol
            """, [date, min_price]).fetchdf()

        if df.empty:
            return []
        return df.to_dict(orient="records")

    # ------------------------------------------------------------------
    # Metadata / utility
    # ------------------------------------------------------------------
    def get_latest_date(self) -> Optional[str]:
        """Return the most recent date across all symbols."""
        with self._lock:
            row = self._con.execute("SELECT MAX(date) FROM ohlcv").fetchone()
        return row[0] if row and row[0] else None

    def get_symbol_dates(self, symbol: str) -> List[str]:
        """Return sorted list of dates for a symbol."""
        with self._lock:
            rows = self._con.execute(
                "SELECT date FROM ohlcv WHERE symbol = ? ORDER BY date", [symbol]
            ).fetchall()
        return [r[0] for r in rows]

    def get_symbol_coverage(self) -> Dict[str, Dict]:
        """Return {symbol: {"min_date": str, "max_date": str, "row_count": int}} for all symbols."""
        with self._lock:
            df = self._con.execute("""
                SELECT symbol, MIN(date) AS min_date, MAX(date) AS max_date, COUNT(*) AS row_count
                FROM ohlcv
                GROUP BY symbol
            """).fetchdf()
        if df.empty:
            return {}
        result: Dict[str, Dict] = {}
        for _, row in df.iterrows():
            result[row["symbol"]] = {
                "min_date": row["min_date"],
                "max_date": row["max_date"],
                "row_count": int(row["row_count"]),
            }
        return result

    def get_metadata(self, symbol: str) -> Optional[Dict]:
        """Return metadata dict for a symbol, or None."""
        with self._lock:
            row = self._con.execute(
                "SELECT symbol, full_name, last_updated FROM symbol_metadata WHERE symbol = ?",
                [symbol],
            ).fetchone()
        if row is None:
            return None
        return {"symbol": row[0], "full_name": row[1], "last_updated": row[2]}

    def symbol_count(self) -> int:
        """Return number of distinct symbols stored."""
        with self._lock:
            row = self._con.execute("SELECT COUNT(DISTINCT symbol) FROM ohlcv").fetchone()
        return row[0] if row else 0

    def row_count(self, symbol: Optional[str] = None) -> int:
        """Return total row count, optionally filtered by symbol."""
        with self._lock:
            if symbol:
                row = self._con.execute(
                    "SELECT COUNT(*) FROM ohlcv WHERE symbol = ?", [symbol]
                ).fetchone()
            else:
                row = self._con.execute("SELECT COUNT(*) FROM ohlcv").fetchone()
        return row[0] if row else 0

    def fundamentals_row_count(self, symbol: Optional[str] = None) -> int:
        """Return fundamentals row count, optionally filtered by symbol."""
        with self._lock:
            if symbol:
                row = self._con.execute(
                    "SELECT COUNT(*) FROM fundamentals WHERE symbol = ?", [symbol]
                ).fetchone()
            else:
                row = self._con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Close the DuckDB connection."""
        con = getattr(self, "_con", None)
        if con is not None:
            try:
                con.close()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            self._con = None

    def __del__(self):
        self.close()
