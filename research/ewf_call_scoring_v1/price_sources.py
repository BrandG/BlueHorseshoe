"""Price series access for EWF call scoring.

- Equities: daily bars read straight from data/ohlcv.duckdb (read-only).
- OANDA instruments: H1 MID candles fetched once per instrument into
  data/oanda_cache/{instrument}_H1.parquet via the project's OandaClient.
  The production FxStore is never written; this study keeps its own cache so
  a re-run is free and the pull is confined to run_research.sh's memory scope.

Bars are returned as the dict-of-arrays shape scoring.py expects:
{ts, open, high, low, close, date} sorted by ts, GMT-naive timestamps.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

CACHE = HERE / "data" / "oanda_cache"
DUCKDB_PATH = REPO / "data" / "ohlcv.duckdb"


def _to_bars(df: pd.DataFrame) -> dict:
    df = df.sort_values("ts").reset_index(drop=True)
    return {
        "ts": df["ts"].values.astype("datetime64[ns]"),
        "open": df["open"].to_numpy(float),
        "high": df["high"].to_numpy(float),
        "low": df["low"].to_numpy(float),
        "close": df["close"].to_numpy(float),
        "date": df["ts"].values.astype("datetime64[D]"),
    }


class PriceLib:
    def __init__(self):
        self._con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        self._equity_cache: dict[str, dict | None] = {}
        self._oanda_cache: dict[str, dict | None] = {}
        self.equity_symbols: set[str] = {
            s for (s,) in self._con.execute("select distinct symbol from ohlcv").fetchall()
        }

    def close(self):
        self._con.close()

    def equity_bars(self, symbol: str) -> dict | None:
        if symbol not in self._equity_cache:
            df = self._con.execute(
                "select date as ts, open, high, low, close from ohlcv "
                "where symbol = ? order by date", [symbol]
            ).df()
            df["ts"] = pd.to_datetime(df["ts"])
            self._equity_cache[symbol] = _to_bars(df) if len(df) > 25 else None
        return self._equity_cache[symbol]

    def oanda_bars(self, instrument: str) -> dict | None:
        if instrument not in self._oanda_cache:
            p = CACHE / f"{instrument}_H1.parquet"
            if not p.exists():
                self._oanda_cache[instrument] = None
            else:
                df = pd.read_parquet(p)
                self._oanda_cache[instrument] = _to_bars(df) if len(df) > 25 else None
        return self._oanda_cache[instrument]


# ---------------------------------------------------------------------------
# one-time OANDA H1 cache pull (run before scoring; resumable per instrument)
# ---------------------------------------------------------------------------

def fetch_oanda_cache(instruments: list[str], start: str, end: str) -> None:
    """Fetch H1 mid candles for each instrument into the study cache.

    Skips instruments already cached. The v20 candles endpoint serves ALL
    instruments (incl. CFDs) even when the account instrument list omits them,
    so availability is decided by trying the endpoint — a hard OANDA error
    writes an {instrument}_UNAVAILABLE marker so the funnel reports it as
    no-price-data rather than silently retrying every run.

    Pagination is done here (not iter_candles_paginated): OANDA returns short
    pages mid-history, which that helper treats as end-of-data. We only stop
    on an empty page, a non-advancing cursor, or reaching `end`.
    """
    from bh_ftmo.data.oanda_client import OandaClient, OandaConfig, OandaError

    CACHE.mkdir(parents=True, exist_ok=True)
    client = OandaClient(OandaConfig.from_env())
    try:
        for inst in instruments:
            out = CACHE / f"{inst}_H1.parquet"
            marker = CACHE / f"{inst}_UNAVAILABLE"
            if out.exists() or marker.exists():
                continue
            rows, cursor, first = [], start, True
            try:
                while True:
                    page = client.get_candles(
                        inst, granularity="H1", count=5000, from_time=cursor,
                        price="M", include_first=first,
                    )
                    if not page:
                        break
                    for c in page:
                        if c.get("complete", True):
                            m = c["mid"]
                            rows.append((c["time"], float(m["o"]), float(m["h"]),
                                         float(m["l"]), float(m["c"])))
                    last = page[-1]["time"]
                    if last >= end or last == cursor:
                        break
                    cursor, first = last, False
            except OandaError as e:
                if rows:
                    print(f"[fetch] {inst}: partial then FAILED {e} — not cached", flush=True)
                else:
                    marker.touch()
                    print(f"[fetch] {inst}: unavailable ({str(e)[:80]})", flush=True)
                continue
            if not rows:
                marker.touch()
                print(f"[fetch] {inst}: no candles returned", flush=True)
                continue
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
            df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
            df = df.drop_duplicates("ts").sort_values("ts")
            df = df[df.ts < pd.Timestamp(end).tz_localize(None)]
            df.to_parquet(out, index=False)
            print(f"[fetch] {inst}: {len(df)} H1 bars "
                  f"({df.ts.min()} .. {df.ts.max()})", flush=True)
    finally:
        client.close()
