"""Tests for bud.diagnostics — fire-history liveness + funnel-trace render."""
from datetime import datetime, timedelta, UTC

import pandas as pd

from bud.diagnostics import (
    FunnelTrace, render_funnel_trace,
    record_fire_event, read_liveness, render_liveness,
)

NOW = datetime(2026, 6, 15, 0, 0, tzinfo=UTC)


def _bar(days_ago: float) -> pd.Timestamp:
    return pd.Timestamp(NOW - timedelta(days=days_ago)).tz_localize(None)


def test_liveness_no_history(tmp_path):
    lv = read_liveness(now_utc=NOW, path=tmp_path / "missing.csv")
    assert lv.history_exists is False
    assert "no fire history yet" in render_liveness(lv)


def test_record_then_read_counts_window(tmp_path):
    p = tmp_path / "fire.csv"
    record_fire_event(_bar(2), 34, 3, 1, now_utc=NOW, path=p)     # in window, fired
    record_fire_event(_bar(5), 34, 0, 0, now_utc=NOW, path=p)     # in window, quiet
    record_fire_event(_bar(40), 34, 9, 2, now_utc=NOW, path=p)    # outside 30d window
    lv = read_liveness(window_days=30, now_utc=NOW, path=p)
    assert lv.history_exists is True
    assert lv.bars_logged == 2          # 40d-ago bar excluded from window
    assert lv.fire_events == 3          # only the in-window fire counts
    assert lv.bars_with_fire == 1
    # last_fire scans the whole log, so the 2d-ago fire wins over the 40d one
    assert lv.last_fire_age_days == 2.0
    assert "last fire 2.0d ago" in render_liveness(lv)


def test_record_is_upsert_not_append(tmp_path):
    p = tmp_path / "fire.csv"
    record_fire_event(_bar(1), 34, 2, 1, now_utc=NOW, path=p)
    record_fire_event(_bar(1), 34, 5, 2, now_utc=NOW, path=p)   # same bar, re-run
    lv = read_liveness(now_utc=NOW, path=p)
    assert lv.bars_logged == 1           # not double-counted
    assert lv.fire_events == 5           # overwritten with the latest value


def test_funnel_trace_renders_every_stage():
    t = FunnelTrace(
        bar_ts=pd.Timestamp("2026-06-12 17:00"), cells_defined=34,
        pairs_total=17, pairs_loaded=16, starved_pairs=["USD_ZAR"],
        fires_raw=[{"pair": "EUR_USD", "direction": "long", "strategy": "bb"}],
        pos_skipped=[{"pair": "EUR_USD", "direction": "long",
                      "skip_reason": "position already open"}],
        accepted=[], slots_left=1, daily_room=200.0,
    )
    out = render_funnel_trace(t)
    assert "STARVED: ['USD_ZAR']" in out
    assert "cells fired on this bar  : 1" in out
    assert "position already open" in out
    assert "ACCEPTED ORDERS          : 0" in out
