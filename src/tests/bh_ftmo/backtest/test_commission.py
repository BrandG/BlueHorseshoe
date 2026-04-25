"""Unit tests for commission helpers."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

import pytest

from bh_ftmo.backtest.commission import commission_at_close, commission_at_open



def test_commission_splits_round_turn_evenly():
    assert commission_at_open(2.0, 3.0) == pytest.approx(3.0)
    assert commission_at_close(2.0, 3.0) == pytest.approx(3.0)



def test_commission_halves_sum_to_full_round_turn():
    total = commission_at_open(1.25, 4.0) + commission_at_close(1.25, 4.0)
    assert total == pytest.approx(5.0)



def test_commission_zero_lots_is_zero():
    assert commission_at_open(0.0, 3.0) == 0.0
    assert commission_at_close(0.0, 3.0) == 0.0



def test_commission_rejects_negative_lots():
    with pytest.raises(ValueError, match="non-negative"):
        commission_at_open(-0.1, 3.0)
