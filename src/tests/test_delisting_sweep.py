"""Tests for the delisting-sweep P0 finder (DuckDB logic, read-only)."""
import duckdb
import pandas as pd
import pytest

from bluehorseshoe.maintenance.delisting_sweep import (
    untraded_tail_census,
    find_untraded_tail_candidates,
)


@pytest.fixture
def con():
    """In-memory ohlcv with three archetypes: live, frozen-tail, fully-dead."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE ohlcv (symbol VARCHAR, date DATE, close DOUBLE, volume DOUBLE)")
    rows = []
    # LIVE: 30 sessions, all traded
    for i in range(30):
        rows.append(("LIVE", f"2026-05-{i+1:02d}", 100.0, 500_000))
    # FROZEN: 20 real sessions then a 9-session zero-volume tail (THR-like)
    for i in range(20):
        rows.append(("FROZEN", f"2026-04-{i+1:02d}", 60.0, 400_000))
    for i in range(9):
        rows.append(("FROZEN", f"2026-05-{i+1:02d}", 61.14, 0))
    # DEAD: 15 sessions, never any volume
    for i in range(15):
        rows.append(("DEAD", f"2026-03-{i+1:02d}", 25.0, 0))
    c.executemany("INSERT INTO ohlcv VALUES (?, ?, ?, ?)", rows)
    return c


def test_census_counts_by_threshold(con):
    census = untraded_tail_census(con)
    assert census[0] == 3          # total symbols
    assert census[1] == 2          # FROZEN + DEAD have an untraded last bar
    assert census[5] == 2          # both have >=5 untraded tail
    assert census[10] == 1         # only DEAD (15) clears 10; FROZEN tail is 9
    assert census[20] == 0         # neither reaches 20


def test_candidates_at_n5_includes_frozen_and_dead(con):
    df = find_untraded_tail_candidates(con, min_untraded=5).set_index("symbol")
    assert set(df.index) == {"FROZEN", "DEAD"}
    assert "LIVE" not in df.index
    assert df.loc["FROZEN", "days_untraded"] == 9
    assert df.loc["DEAD", "days_untraded"] == 15          # never traded -> full length
    # last_traded_date is the most recent real bar (NULL/None for fully-dead)
    assert str(df.loc["FROZEN", "last_traded_date"]).startswith("2026-04-20")
    assert pd.isna(df.loc["DEAD", "last_traded_date"])


def test_candidates_at_n10_excludes_shorter_frozen_tail(con):
    df = find_untraded_tail_candidates(con, min_untraded=10)
    assert set(df["symbol"]) == {"DEAD"}   # FROZEN's 9-tail is below 10


def test_live_symbol_never_flagged(con):
    df = find_untraded_tail_candidates(con, min_untraded=1)
    assert "LIVE" not in set(df["symbol"])
