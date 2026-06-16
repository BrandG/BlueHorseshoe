"""Tests for bh_briefing_ftmo position-health assessment (pure logic)."""
import pytest

from bud.briefing_ftmo import _assess_position

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


def test_long_losing_but_supported_is_underwater():
    # Losing, but the entry cell still fires in our direction → UNDERWATER,
    # not CRITICAL (CRITICAL needs the signal gone or flipped).
    h = _assess_position(_long(), current=1.0980, inst=INST, fire_dirs={"long"})
    assert h["status"] == "UNDERWATER"
    assert h["pnl_usd"] < 0


def test_long_near_stop_while_supported():
    # Near stop but the cell still supports the position → NEAR STOP.
    h = _assess_position(_long(), current=1.0960, inst=INST, fire_dirs={"long"})
    assert h["status"] == "NEAR STOP"   # 10 of 50 pips room = 20% <= 25%


def test_long_past_stop():
    h = _assess_position(_long(), current=1.0945, inst=INST, fire_dirs=set())
    assert h["status"] == "AT/PAST STOP"


# ---- CRITICAL (get-out) status ----------------------------------------

def test_critical_on_opposite_fire_even_in_profit():
    # Opposite-direction cell fires → thesis inverted → CRITICAL, even in
    # profit. The signal column still reads FLIPPED independently.
    h = _assess_position(_long(), current=1.1030, inst=INST, fire_dirs={"short"})
    assert h["signal"] == "FLIPPED"
    assert h["status"] == "CRITICAL"


def test_signal_gone_and_underwater_with_room_is_underwater():
    # Entry setup no longer fires AND we're losing, but with room to the stop →
    # UNDERWATER, not CRITICAL. A held swing position almost never still fires
    # its H4 entry, so signal=="none" is the steady state and must not by itself
    # imply CRITICAL; only an opposite-direction fire (FLIPPED) or price risk
    # (NEAR STOP / AT-PAST STOP) escalates.
    h = _assess_position(_long(), current=1.0980, inst=INST, fire_dirs=set())
    assert h["signal"] == "none"
    assert h["pnl_usd"] < 0
    assert h["room_frac"] > 0.25
    assert h["status"] == "UNDERWATER"


def test_critical_outranks_near_stop():
    # Near the stop AND flipped → CRITICAL wins over NEAR STOP (precedence).
    h = _assess_position(_long(), current=1.0960, inst=INST, fire_dirs={"short"})
    assert h["status"] == "CRITICAL"


def test_signal_gone_but_in_profit_is_not_critical():
    # No signal but still in profit → not CRITICAL (CRITICAL needs underwater).
    h = _assess_position(_long(), current=1.1030, inst=INST, fire_dirs=set())
    assert h["signal"] == "none"
    assert h["status"] == "OK"


# ---- signal verdict ----------------------------------------------------

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


def test_short_losing_but_supported_is_underwater():
    h = _assess_position(_short(), current=1.1030, inst=INST, fire_dirs={"short"})
    assert h["pnl_pips"] == pytest.approx(-30.0)
    assert h["status"] == "UNDERWATER"


def test_short_flip_is_critical():
    h = _assess_position(_short(), current=1.0970, inst=INST, fire_dirs={"long"})
    assert h["signal"] == "FLIPPED"
    assert h["status"] == "CRITICAL"


# ---- missing data ------------------------------------------------------

def test_no_price_is_no_data():
    h = _assess_position(_long(), current=None, inst=INST, fire_dirs=set())
    assert h["status"] == "NO DATA"


def test_no_instrument_is_no_data():
    h = _assess_position(_long(), current=1.1030, inst=None, fire_dirs=set())
    assert h["status"] == "NO DATA"


# ---- price_source threading + live/H4 marking -------------------------------

import bud.briefing_ftmo as bf  # noqa: E402


def test_assess_position_records_price_source():
    live = _assess_position(_long(), current=1.1010, inst=INST, fire_dirs=set(),
                            price_source="live")
    assert live["price_source"] == "live"
    h4 = _assess_position(_long(), current=1.1010, inst=INST, fire_dirs=set(),
                          price_source="h4")
    assert h4["price_source"] == "h4"
    # No price at all -> source collapses to "none" regardless of the arg.
    none = _assess_position(_long(), current=None, inst=INST, fire_dirs=set(),
                            price_source="live")
    assert none["price_source"] == "none"


class _DummyStore:
    def __init__(self, *a, **k):
        pass

    def close(self):
        pass


def test_compute_health_marks_long_to_live_bid(monkeypatch):
    monkeypatch.setattr(bf, "FxStore", _DummyStore)
    monkeypatch.setattr(bf, "_live_prices",
                        lambda instrs: {"EUR_USD": {"bid": 1.1010, "ask": 1.1012}})
    out = bf.compute_position_health(
        [_long(entry=1.1000, stop=1.0950, lots=1.0)], [], {"EUR_USD.sim": INST, "EURUSD.sim": INST})
    h = out[0]
    assert h["price_source"] == "live"
    # long marks to bid 1.1010 -> +10 pips
    assert round(h["pnl_pips"], 1) == 10.0


def test_compute_health_marks_short_to_live_ask(monkeypatch):
    monkeypatch.setattr(bf, "FxStore", _DummyStore)
    monkeypatch.setattr(bf, "_live_prices",
                        lambda instrs: {"EUR_USD": {"bid": 1.0988, "ask": 1.0990}})
    out = bf.compute_position_health(
        [_short(entry=1.1000, stop=1.1050, lots=1.0)], [], {"EURUSD.sim": INST})
    h = out[0]
    assert h["price_source"] == "live"
    # short marks to ask 1.0990 -> +10 pips in its favour
    assert round(h["pnl_pips"], 1) == 10.0


def test_compute_health_falls_back_to_h4_when_no_live(monkeypatch):
    monkeypatch.setattr(bf, "FxStore", _DummyStore)
    monkeypatch.setattr(bf, "_live_prices", lambda instrs: {})
    monkeypatch.setattr(bf, "_latest_mid_close", lambda store, pair: 1.0990)
    out = bf.compute_position_health(
        [_long(entry=1.1000, stop=1.0950, lots=1.0)], [], {"EURUSD.sim": INST})
    h = out[0]
    assert h["price_source"] == "h4"
    assert round(h["pnl_pips"], 1) == -10.0
