"""DuckDB store for BH FTMO 4h + 1h forex bars.

Schema per plan decision 4A + 8A: ``ohlcv_4h`` and ``ohlcv_1h`` share an identical
schema with operational metadata (``provider``, ``ingested_at``, ``is_complete``).
Separate from the equity ``ohlcv.duckdb`` store per plan decision 4.

Timestamps are **tz-naive UTC** throughout (``FX_TIME_SPEC.md`` section 1). Callers
pass ``datetime`` objects; the store does no timezone conversion.

Usage:
    store = FxStore()  # uses default path data/fx_4h.duckdb
    rows = store.save_candles("EUR_USD", oanda_candles, granularity="H4")
    df = store.load("EUR_USD", granularity="H4", start=datetime(2020, 1, 1))
    store.close()
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]

Granularity = Literal["H1", "H4"]
_ALLOWED_GRANULARITIES: tuple[Granularity, ...] = ("H1", "H4")

log = logging.getLogger("bh_ftmo.data.fx_store")


def _default_db_path() -> Path:
    override = os.environ.get("BH_FTMO_FX_DB")
    if override:
        return Path(override)
    return REPO_ROOT / "data" / "fx_4h.duckdb"


_TABLE_NAMES: dict[str, str] = {"H4": "ohlcv_4h", "H1": "ohlcv_1h"}


def _table_for(granularity: Granularity) -> str:
    if granularity not in _ALLOWED_GRANULARITIES:
        raise ValueError(f"granularity must be one of {_ALLOWED_GRANULARITIES}, got {granularity!r}")
    return _TABLE_NAMES[granularity]


_TABLE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("symbol", "VARCHAR NOT NULL"),
    ("timestamp", "TIMESTAMP NOT NULL"),
    ("open_bid", "DOUBLE"),
    ("high_bid", "DOUBLE"),
    ("low_bid", "DOUBLE"),
    ("close_bid", "DOUBLE"),
    ("open_ask", "DOUBLE"),
    ("high_ask", "DOUBLE"),
    ("low_ask", "DOUBLE"),
    ("close_ask", "DOUBLE"),
    ("tick_volume", "BIGINT"),
    ("provider", "VARCHAR NOT NULL"),
    ("ingested_at", "TIMESTAMP NOT NULL"),
    ("is_complete", "BOOLEAN NOT NULL"),
)

_ROW_COLUMNS: tuple[str, ...] = tuple(name for name, _ in _TABLE_COLUMNS)


@dataclass(frozen=True)
class Coverage:
    symbol: str
    min_timestamp: Optional[datetime]
    max_timestamp: Optional[datetime]
    row_count: int


def _parse_rfc3339(ts: str) -> datetime:
    """Parse OANDA timestamps like ``2020-01-01T22:00:00.000000000Z`` to tz-naive UTC."""
    # Strip trailing 'Z' and any sub-millisecond precision datetime can't handle
    s = ts.rstrip("Z")
    # Reduce fractional-second precision to microseconds (datetime max)
    if "." in s:
        head, frac = s.split(".", 1)
        frac = frac[:6].ljust(6, "0")
        s = f"{head}.{frac}"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _coerce_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def candle_to_row(
    candle: dict[str, Any],
    *,
    symbol: str,
    provider: str = "oanda",
    ingested_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Convert one OANDA v20 BA-format candle into a store row dict.

    Raises ``ValueError`` if required bid/ask fields are missing.
    """
    try:
        bid = candle["bid"]
        ask = candle["ask"]
    except KeyError as exc:
        raise ValueError(f"candle missing bid/ask (requires price='BA'): {exc}") from exc
    ts = _parse_rfc3339(candle["time"])
    ingested = ingested_at or datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    return {
        "symbol": symbol,
        "timestamp": ts,
        "open_bid": float(bid["o"]),
        "high_bid": float(bid["h"]),
        "low_bid": float(bid["l"]),
        "close_bid": float(bid["c"]),
        "open_ask": float(ask["o"]),
        "high_ask": float(ask["h"]),
        "low_ask": float(ask["l"]),
        "close_ask": float(ask["c"]),
        "tick_volume": int(candle.get("volume", 0) or 0),
        "provider": provider,
        "ingested_at": _coerce_naive_utc(ingested),
        "is_complete": bool(candle.get("complete", True)),
    }


class FxStore:
    """Embedded DuckDB store for 4h + 1h forex OHLCV bars."""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        *,
        read_only: bool = False,
    ) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_db_path()
        if not read_only:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._read_only = read_only
        self._con = duckdb.connect(str(self._db_path), read_only=read_only)
        self._lock = threading.RLock()
        if not read_only:
            self._init_schema()

    # ---- schema ---------------------------------------------------------

    def _init_schema(self) -> None:
        cols_sql = ", ".join(f"{name} {dtype}" for name, dtype in _TABLE_COLUMNS)
        for gran in _ALLOWED_GRANULARITIES:
            table = _table_for(gran)
            self._con.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ({cols_sql}, PRIMARY KEY (symbol, timestamp))"
            )

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ---- write ----------------------------------------------------------

    def save_candles(
        self,
        symbol: str,
        candles: list[dict[str, Any]],
        *,
        granularity: Granularity,
        provider: str = "oanda",
        include_incomplete: bool = False,
        ingested_at: Optional[datetime] = None,
    ) -> int:
        """Parse OANDA candles into rows and upsert. Returns number written.

        Incomplete bars (``complete == False``) are skipped unless ``include_incomplete``.
        """
        if self._read_only:
            raise RuntimeError("cannot write to a read-only FxStore")
        _table_for(granularity)  # validate early
        if not candles:
            return 0
        rows: list[dict[str, Any]] = []
        for c in candles:
            if not include_incomplete and not bool(c.get("complete", True)):
                continue
            rows.append(candle_to_row(c, symbol=symbol, provider=provider, ingested_at=ingested_at))
        return self.save_rows(rows, granularity=granularity)

    def save_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        granularity: Granularity,
    ) -> int:
        if self._read_only:
            raise RuntimeError("cannot write to a read-only FxStore")
        table = _table_for(granularity)
        if not rows:
            return 0

        # Normalize timestamp + ingested_at types, dedupe (symbol, timestamp)
        # within the batch (last-write-wins to match upsert semantics).
        by_key: dict[tuple[str, datetime], dict[str, Any]] = {}
        for r in rows:
            r = dict(r)
            r["timestamp"] = _coerce_naive_utc(r["timestamp"])
            r["ingested_at"] = _coerce_naive_utc(r["ingested_at"])
            by_key[(r["symbol"], r["timestamp"])] = r
        normalized: list[dict[str, Any]] = list(by_key.values())

        df = pd.DataFrame(normalized, columns=list(_ROW_COLUMNS))  # noqa: F841 — used by DuckDB
        cols = ", ".join(_ROW_COLUMNS)

        with self._lock:
            # Build (symbol, timestamp) pair list for targeted delete
            keys = [(r["symbol"], r["timestamp"]) for r in normalized]
            keys_df = pd.DataFrame(keys, columns=["symbol", "timestamp"])  # noqa: F841
            self._con.execute(
                f"DELETE FROM {table} WHERE (symbol, timestamp) IN "
                f"(SELECT symbol, timestamp FROM keys_df)"
            )
            self._con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM df")
        return len(normalized)

    # ---- read -----------------------------------------------------------

    def load(
        self,
        symbol: str,
        *,
        granularity: Granularity,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        include_incomplete: bool = True,
    ) -> pd.DataFrame:
        table = _table_for(granularity)
        clauses = ["symbol = ?"]
        params: list[Any] = [symbol]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(_coerce_naive_utc(start))
        if end is not None:
            clauses.append("timestamp < ?")
            params.append(_coerce_naive_utc(end))
        if not include_incomplete:
            clauses.append("is_complete = TRUE")
        where = " AND ".join(clauses)
        cols = ", ".join(c for c in _ROW_COLUMNS if c != "symbol")
        with self._lock:
            df = self._con.execute(
                f"SELECT {cols} FROM {table} WHERE {where} ORDER BY timestamp",
                params,
            ).fetchdf()
        return df

    def latest_timestamp(
        self,
        symbol: str,
        *,
        granularity: Granularity,
        only_complete: bool = True,
    ) -> Optional[datetime]:
        """Return max timestamp for ``symbol`` in table, or ``None`` if empty."""
        table = _table_for(granularity)
        clauses = ["symbol = ?"]
        params: list[Any] = [symbol]
        if only_complete:
            clauses.append("is_complete = TRUE")
        where = " AND ".join(clauses)
        with self._lock:
            row = self._con.execute(
                f"SELECT MAX(timestamp) FROM {table} WHERE {where}", params
            ).fetchone()
        if not row or row[0] is None:
            return None
        val = row[0]
        if isinstance(val, pd.Timestamp):
            val = val.to_pydatetime()
        if val.tzinfo is not None:
            val = val.astimezone(timezone.utc).replace(tzinfo=None)
        return val

    def coverage(self, *, granularity: Granularity) -> dict[str, Coverage]:
        table = _table_for(granularity)
        with self._lock:
            df = self._con.execute(
                f"""
                SELECT symbol, MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts, COUNT(*) AS row_count
                FROM {table}
                GROUP BY symbol
                ORDER BY symbol
                """
            ).fetchdf()
        out: dict[str, Coverage] = {}
        for _, row in df.iterrows():
            out[str(row["symbol"])] = Coverage(
                symbol=str(row["symbol"]),
                min_timestamp=row["min_ts"].to_pydatetime() if pd.notna(row["min_ts"]) else None,
                max_timestamp=row["max_ts"].to_pydatetime() if pd.notna(row["max_ts"]) else None,
                row_count=int(row["row_count"]),
            )
        return out

    def symbols(self, *, granularity: Granularity) -> list[str]:
        table = _table_for(granularity)
        with self._lock:
            rows = self._con.execute(
                f"SELECT DISTINCT symbol FROM {table} ORDER BY symbol"
            ).fetchall()
        return [r[0] for r in rows]

    def row_count(self, *, granularity: Granularity, symbol: Optional[str] = None) -> int:
        table = _table_for(granularity)
        with self._lock:
            if symbol is not None:
                row = self._con.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE symbol = ?", [symbol]
                ).fetchone()
            else:
                row = self._con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0

    # ---- lifecycle ------------------------------------------------------

    def close(self) -> None:
        con = getattr(self, "_con", None)
        if con is not None:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
            self._con = None

    def __enter__(self) -> "FxStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
