"""
DuckDB-based storage backend for OHLCV time-series data.

Replaces MongoDB's nested document arrays with a flat, columnar table
optimised for analytical reads (bulk symbol loads, date-range filters,
universe snapshots).

Usage:
    store = DuckDBStore("/path/to/ohlcv.duckdb")
    store.save_symbol("AAPL", df, full_name="Apple Inc.")
    df = store.load_symbol("AAPL", start_date="2024-01-01")
    store.close()
"""
import logging
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


class DuckDBStore:
    """Embedded columnar store for OHLCV + indicator data."""

    def __init__(self, db_path: str = ":memory:"):
        self._db_path = db_path
        self._con = duckdb.connect(db_path)
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

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def save_symbol(self, symbol: str, df: pd.DataFrame, full_name: str = "") -> None:
        """
        Upsert OHLCV rows for *symbol* from *df*.

        Only core OHLCV columns (date, open, high, low, close, volume) are
        persisted.  Indicator columns in *df* are silently dropped — they are
        always recomputed from raw OHLCV during ingestion.
        """
        if df is None or df.empty:
            return

        df = df.copy()
        df["symbol"] = symbol

        # Keep only columns that exist in the schema
        keep = [c for c in df.columns if c in _CORE_COLUMNS]
        df = df[keep]

        df_cols = list(df.columns)
        cols_sql = ", ".join(f'"{c}"' for c in df_cols)

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

    def load_universe_snapshot(
        self,
        date: str,
        min_price: float = 1.0,
    ) -> List[Dict]:
        """
        Load one-day OHLCV bars for the entire universe, filtered by price.

        Returns a list of flat dicts suitable for DataFrame construction.
        """
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
        row = self._con.execute("SELECT MAX(date) FROM ohlcv").fetchone()
        return row[0] if row and row[0] else None

    def get_symbol_dates(self, symbol: str) -> List[str]:
        """Return sorted list of dates for a symbol."""
        rows = self._con.execute(
            "SELECT date FROM ohlcv WHERE symbol = ? ORDER BY date", [symbol]
        ).fetchall()
        return [r[0] for r in rows]

    def get_metadata(self, symbol: str) -> Optional[Dict]:
        """Return metadata dict for a symbol, or None."""
        row = self._con.execute(
            "SELECT symbol, full_name, last_updated FROM symbol_metadata WHERE symbol = ?",
            [symbol],
        ).fetchone()
        if row is None:
            return None
        return {"symbol": row[0], "full_name": row[1], "last_updated": row[2]}

    def symbol_count(self) -> int:
        """Return number of distinct symbols stored."""
        row = self._con.execute("SELECT COUNT(DISTINCT symbol) FROM ohlcv").fetchone()
        return row[0] if row else 0

    def row_count(self, symbol: Optional[str] = None) -> int:
        """Return total row count, optionally filtered by symbol."""
        if symbol:
            row = self._con.execute(
                "SELECT COUNT(*) FROM ohlcv WHERE symbol = ?", [symbol]
            ).fetchone()
        else:
            row = self._con.execute("SELECT COUNT(*) FROM ohlcv").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._con is not None:
            try:
                self._con.close()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            self._con = None

    def __del__(self):
        self.close()
