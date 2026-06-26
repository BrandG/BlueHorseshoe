"""Tests for bud.briefing.compute_entry_stop_target geometry overrides.

Covers the per-strategy exit-geometry overrides validated by exit_geometry_v2:
- atr LONG → 2% TP / 0.5% SL (2026-06-26 deploy); atr SHORT stays baseline 1%/1%.
- bb/macd → 0.75% tight stop.
- everything else → global 1%/1%.
"""
import pandas as pd
import pytest

from bud.briefing import (
    Cell,
    compute_entry_stop_target,
    ATR_LONG_TP_PCT,
    ATR_LONG_SL_PCT,
    TP_PCT,
    STOP_PCT,
    TIGHT_STOP_PCT,
)


def _mid(last_low=1.0, last_high=2.0, last_close=1.5):
    """Two-bar H4 mid frame; the last bar drives the entry fill."""
    return pd.DataFrame(
        {
            "open": [1.0, 1.2],
            "high": [1.1, last_high],
            "low": [0.9, last_low],
            "close": [1.05, last_close],
        }
    )


def test_atr_long_limit_uses_wider_target_tighter_stop():
    # limit long fills at the trigger bar's low
    cell = Cell("atr", "EUR_NOK", "long", "limit", {})
    entry, stop, target = compute_entry_stop_target(cell, _mid(last_low=1.0))
    assert entry == pytest.approx(1.0)
    assert stop == pytest.approx(1.0 * (1 - ATR_LONG_SL_PCT))   # 0.5% below
    assert target == pytest.approx(1.0 * (1 + ATR_LONG_TP_PCT))  # 2% above
    # sanity: this is NOT the global 1%/1%
    assert ATR_LONG_TP_PCT == 0.020 and ATR_LONG_SL_PCT == 0.005


def test_atr_short_limit_stays_baseline():
    # atr short was a drift-rider — must remain at the global 1%/1% geometry
    cell = Cell("atr", "NZD_CHF", "short", "limit", {})
    entry, stop, target = compute_entry_stop_target(cell, _mid(last_high=2.0))
    assert entry == pytest.approx(2.0)  # limit short fills at the high
    assert stop == pytest.approx(2.0 * (1 + STOP_PCT))   # 1% above
    assert target == pytest.approx(2.0 * (1 - TP_PCT))   # 1% below


def test_bb_short_keeps_tight_stop_not_atr_override():
    # regression: the atr branch must not disturb the bb/macd tight-stop path
    cell = Cell("bb", "AUD_CAD", "short", "mid", {})
    entry, stop, target = compute_entry_stop_target(cell, _mid(last_close=1.5))
    assert entry == pytest.approx(1.5)  # mid fills at the close
    assert stop == pytest.approx(1.5 * (1 + TIGHT_STOP_PCT))  # 0.75%
    assert target == pytest.approx(1.5 * (1 - TP_PCT))        # 1%
