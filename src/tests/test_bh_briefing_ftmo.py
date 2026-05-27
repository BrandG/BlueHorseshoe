"""Tests for bh_briefing_ftmo position-health assessment (pure logic)."""
import pytest

from bh_briefing_ftmo import _assess_position

INST = {"pip_size": 0.0001, "dollar_per_pip_per_lot": 10.0}


def _long(entry=1.1000, stop=1.0950, lots=1.0):
    return {"ftmo_symbol": "EURUSD.sim", "side": "buy",
            "entry": entry, "stop": stop, "lots": lots}


def _short(entry=1.1000, stop=1.1050, lots=1.0):
    return {"ftmo_symbol": "EURUSD.sim", "side": "sell",
            "entry": entry, "stop": stop, "lots": lots}


# ---- status flag (long; 50-pip risk) ----------------------------------

def test_long_in_profit_is_ok():
    h = _assess_position(_long(), current=1.1030, inst=INST, fire_dirs=set())
    assert h["status"] == "OK"
    assert h["pnl_pips"] == pytest.approx(30.0)
    assert h["pnl_usd"] == pytest.approx(300.0)   # +30 pips * $10/pip * 1 lot
    assert h["room_frac"] > 1.0        # above entry → more than full risk distance to stop


def test_long_losing_but_clear_is_underwater():
    h = _assess_position(_long(), current=1.0980, inst=INST, fire_dirs=set())
    assert h["status"] == "UNDERWATER"
    assert h["pnl_usd"] < 0


def test_long_near_stop():
    h = _assess_position(_long(), current=1.0960, inst=INST, fire_dirs=set())
    assert h["status"] == "NEAR STOP"   # 10 of 50 pips room = 20% <= 25%


def test_long_past_stop():
    h = _assess_position(_long(), current=1.0945, inst=INST, fire_dirs=set())
    assert h["status"] == "AT/PAST STOP"


# ---- signal verdict ----------------------------------------------------

def test_opposite_signal_flips_even_when_in_profit():
    h = _assess_position(_long(), current=1.1030, inst=INST, fire_dirs={"short"})
    assert h["signal"] == "FLIPPED"
    assert h["status"] == "FLIPPED"


def test_same_direction_signal_supports():
    h = _assess_position(_long(), current=1.1030, inst=INST, fire_dirs={"long"})
    assert h["signal"] == "supports"
    assert h["status"] == "OK"


def test_no_signal_is_none():
    h = _assess_position(_long(), current=1.1030, inst=INST, fire_dirs=set())
    assert h["signal"] == "none"


# ---- short-side sign correctness --------------------------------------

def test_short_in_profit_when_price_falls():
    # short from 1.1000, price drops to 1.0970 → +30 pips profit
    h = _assess_position(_short(), current=1.0970, inst=INST, fire_dirs=set())
    assert h["pnl_pips"] == pytest.approx(30.0)
    assert h["pnl_usd"] == pytest.approx(300.0)
    assert h["status"] == "OK"


def test_short_underwater_when_price_rises():
    h = _assess_position(_short(), current=1.1030, inst=INST, fire_dirs=set())
    assert h["pnl_pips"] == pytest.approx(-30.0)
    assert h["status"] == "UNDERWATER"


def test_short_flip_is_long_signal():
    h = _assess_position(_short(), current=1.0970, inst=INST, fire_dirs={"long"})
    assert h["signal"] == "FLIPPED"


# ---- missing data ------------------------------------------------------

def test_no_price_is_no_data():
    h = _assess_position(_long(), current=None, inst=INST, fire_dirs=set())
    assert h["status"] == "NO DATA"


def test_no_instrument_is_no_data():
    h = _assess_position(_long(), current=1.1030, inst=None, fire_dirs=set())
    assert h["status"] == "NO DATA"
