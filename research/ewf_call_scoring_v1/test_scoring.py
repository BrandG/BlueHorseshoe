"""Synthetic-bar tests for scoring.py — every outcome class, both call types.

Run:  ./run.sh pytest research/ewf_call_scoring_v1/test_scoring.py -v
"""
import numpy as np
import pandas as pd
import pytest

import scoring


def mk_bars(rows):
    """rows: list of (ts_str, o, h, l, c)."""
    ts = np.array([np.datetime64(r[0]) for r in rows], dtype="datetime64[ns]")
    return {
        "ts": ts,
        "open": np.array([r[1] for r in rows], float),
        "high": np.array([r[2] for r in rows], float),
        "low": np.array([r[3] for r in rows], float),
        "close": np.array([r[4] for r in rows], float),
        "date": ts.astype("datetime64[D]"),
    }


DAILY = mk_bars([
    ("2020-01-02", 100, 101, 99, 100),
    ("2020-01-03", 100, 102, 98, 101),
    ("2020-01-06", 101, 104, 100, 103),
    ("2020-01-07", 103, 106, 102, 105),
    ("2020-01-08", 105, 108, 104, 107),
    ("2020-01-09", 107, 110, 106, 109),
])


# --- walk_bracket -----------------------------------------------------------

def test_long_win():
    r = scoring.walk_bracket(DAILY, 0, 5, ref=100, target=105, stop=97, side=1)
    assert r["outcome"] == "win"
    assert r["R"] == pytest.approx(5 / 3)


def test_long_loss():
    r = scoring.walk_bracket(DAILY, 0, 5, ref=100, target=120, stop=98.5, side=1)
    assert r["outcome"] == "loss" and r["R"] == -1.0


def test_ambiguous_same_bar():
    # bar 1 spans 98..102: both target 101.5 and stop 98.5 inside it
    r = scoring.walk_bracket(DAILY, 1, 5, ref=100, target=101.5, stop=98.5, side=1)
    assert r["outcome"] == "ambiguous" and r["R"] == -1.0
    assert np.isnan(r["R_drop_ambiguous"])


def test_timeout_fractional_r():
    # target 115 never touched (max high 110), stop 97 never touched (min low 98)
    r = scoring.walk_bracket(DAILY, 0, 5, ref=100, target=115, stop=97, side=1)
    assert r["outcome"] == "timeout"
    assert r["R"] == pytest.approx((109 - 100) / 3)  # window-end close vs risk
    assert -1.0 <= r["R"] <= (115 - 100) / 3


def test_short_win_and_loss():
    bars = mk_bars([
        ("2020-01-02", 100, 101, 96, 97),
        ("2020-01-03", 97, 99, 94, 95),
    ])
    win = scoring.walk_bracket(bars, 0, 1, ref=100, target=96.5, stop=102, side=-1)
    assert win["outcome"] == "win" and win["R"] == pytest.approx(3.5 / 2)
    loss = scoring.walk_bracket(bars, 0, 1, ref=100, target=90, stop=100.5, side=-1)
    assert loss["outcome"] == "loss"


# --- windows / reference bars ------------------------------------------------

def test_window_end_trading_days():
    assert scoring.window_end(DAILY, 0, 3) == 2      # 3 distinct dates from idx 0
    assert scoring.window_end(DAILY, 0, 100) == 5    # capped at series end


def test_ref_bar_equity_premarket_vs_intraday():
    pre = pd.Timestamp("2020-01-03 08:00")           # 03:00 NY < 09:30 -> same-day open
    assert scoring.ref_bar_equity(DAILY, pre) == 1
    intra = pd.Timestamp("2020-01-03 15:00")         # 10:00 NY -> next trading day
    assert scoring.ref_bar_equity(DAILY, intra) == 2
    assert scoring.ref_bar_equity(DAILY, pd.Timestamp("2021-01-01")) is None


def test_ref_bar_h1_strictly_after():
    h1 = mk_bars([("2020-01-02T10:00", 1, 1, 1, 1), ("2020-01-02T11:00", 1, 1, 1, 1)])
    assert scoring.ref_bar_h1(h1, pd.Timestamp("2020-01-02 10:00")) == 1
    assert scoring.ref_bar_h1(h1, pd.Timestamp("2020-01-02 09:59")) == 0


def test_resolve_date_extreme():
    lvl = scoring.resolve_invalidation({"type": "date_extreme", "date": "2020-01-06", "side": "high"}, DAILY)
    assert lvl == 104.0
    assert scoring.resolve_invalidation({"type": "date_extreme", "date": "2020-02-01", "side": "low"}, DAILY) is None
    assert scoring.resolve_invalidation(97.5, DAILY) == 97.5


# --- Type A ------------------------------------------------------------------

def test_type_a_sanity_gates():
    assert scoring.score_type_a(DAILY, 0, 100, "long", [95], 97)["unscoreable"] == "levels-inconsistent"
    assert scoring.score_type_a(DAILY, 0, 100, "long", [105], 103)["unscoreable"] == "levels-inconsistent"
    assert scoring.score_type_a(DAILY, 0, 100, "long", [105], 99.999)["unscoreable"] == "levels-inconsistent"


def test_type_a_primary_is_nearest_target():
    res = scoring.score_type_a(DAILY, 0, 100, "long", [109.5, 104], 97)
    assert res["outcome_30"] == "win"
    assert res["R_30"] == pytest.approx(4 / 3)          # nearest target 104
    assert res["R_30_far"] == pytest.approx(9.5 / 3)    # farthest 109.5 also wins here


# --- Type B ------------------------------------------------------------------

TYPE_B = mk_bars([
    ("2020-01-02", 110, 111, 108, 109),   # above the zone, drifting down
    ("2020-01-03", 109, 109, 104, 105),   # touches zone edge 105 -> fill
    ("2020-01-06", 105, 112, 104.5, 111), # +1R (109) hit before pivot (101)
    ("2020-01-07", 111, 113, 110, 112),
])


def test_type_b_fill_then_1r_win():
    res = scoring.score_type_b(TYPE_B, 0, 110, "long", [101.5, 105], 101, [])
    assert res["entry_edge"] == 105 and res["risk"] == 4
    assert res["outcome_30"] == "win" and res["R_30"] == pytest.approx(1.0)
    assert res["outcome_30_2r"] == "win" and res["R_30_2r"] == pytest.approx(2.0)


def test_type_b_no_fill():
    bars = mk_bars([("2020-01-02", 110, 112, 109, 111), ("2020-01-03", 111, 113, 110, 112)])
    res = scoring.score_type_b(bars, 0, 110, "long", [101.5, 105], 101, [])
    assert res["outcome_30"] == "no_fill" and np.isnan(res["R_30"])


def test_type_b_pivot_must_be_beyond_edge():
    # long reaction but pivot ABOVE entry edge -> geometry invalid
    res = scoring.score_type_b(TYPE_B, 0, 110, "long", [101.5, 105], 106, [])
    assert res["unscoreable"] == "levels-inconsistent"


def test_type_b_pivot_inside_zone_ok():
    # Palladium case: pivot inside the zone but on the stop side of the entry edge
    res = scoring.score_type_b(TYPE_B, 0, 110, "long", [101.5, 105], 103.5, [])
    assert "unscoreable" not in res and res["risk"] == pytest.approx(1.5)


# --- nulls ------------------------------------------------------------------

def test_trend_direction_and_random_determinism():
    up = mk_bars([(f"2020-01-{d:02d}", 100 + d, 101 + d, 99 + d, 100 + d) for d in range(1, 26)])
    assert scoring.trend_direction(up, 24, n_td=20) == "long"
    assert scoring.random_direction(12345) == scoring.random_direction(12345)
    flips = {scoring.random_direction(i) for i in range(50)}
    assert flips == {"long", "short"}


# --- forward-window sufficiency ---------------------------------------------
# A call must not be scored over a window the data cannot cover. Silent truncation
# turns "we have no data" into a confident timeout R. (SEK_JPY shipped 40 bars.)

def test_forward_trading_days_counts_distinct_dates():
    assert scoring.forward_trading_days(DAILY, 0) == 6
    assert scoring.forward_trading_days(DAILY, 4) == 2
    assert scoring.forward_trading_days(DAILY, 5) == 1


def test_window_end_truncates_silently_hence_the_guard():
    """window_end() itself clamps to the series end — this documents WHY callers must
    check forward_trading_days() first rather than trusting the returned index."""
    assert scoring.window_end(DAILY, 4, 30) == 5      # asked 30td, got 2 days of bars
    assert scoring.forward_trading_days(DAILY, 4) < 30
