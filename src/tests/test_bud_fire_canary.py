"""Canary for the BUD fire path: a synthetic bar that MUST fire a known cell.

The briefing's liveness line answers "is 0 fires normal?" from history; this
test answers the complementary question deterministically and offline: "can the
evaluator fire *at all*?" A regression that silently breaks evaluate_cell (a bad
indicator import, a params rename, an off-by-one) would make every briefing read
"0 fires" forever and look exactly like a quiet market. This guards against that
without depending on live market data.

Target: a long Bollinger-Band cell with depth=0.0 — fires iff the final close
sits below the lower band and did not on the prior bar. We build a calm series
around 100 then plunge the last bar, which unambiguously pierces the band.
"""
import math

import pandas as pd

from bud.briefing import CELLS, Cell, evaluate_cell

BB_LONG_PARAMS = {"period": 50, "n_std": 2.0, "depth": 0.0}


def _mid(closes: list[float]) -> pd.DataFrame:
    """Minimal OHLC-mid frame (BB only reads close; OHLC kept equal for safety)."""
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes})


def _calm(n: int = 59) -> list[float]:
    # Gentle deterministic wave so the band has a small, non-degenerate width.
    return [100.0 + 0.2 * math.sin(i) for i in range(n)]


def test_evaluate_cell_fires_on_constructed_plunge():
    # Calm around 100, then the last bar plunges far through the lower band.
    cell = Cell(strategy="bb", pair="CHF_JPY", direction="long",
                entry_mode="mid", params=BB_LONG_PARAMS)
    closes = _calm(59) + [90.0]
    # evaluate_cell may return a numpy bool — assert truthiness, not identity.
    assert evaluate_cell(cell, _mid(closes))


def test_no_fire_on_calm_series():
    # Negative control: a calm series with no plunge must NOT fire — proves the
    # canary isn't trivially always-true.
    cell = Cell(strategy="bb", pair="CHF_JPY", direction="long",
                entry_mode="mid", params=BB_LONG_PARAMS)
    closes = _calm(60)
    assert not evaluate_cell(cell, _mid(closes))


def test_a_real_long_bb_cell_fires_on_the_plunge():
    # Faithful to production config: pull an actual long BB cell from CELLS and
    # confirm it fires on the same plunge. If the cell set ever drops all long
    # BB cells this skips rather than false-fails.
    real = next((c for c in CELLS if c.strategy == "bb" and c.direction == "long"),
                None)
    if real is None:
        import pytest
        pytest.skip("no long BB cell in current CELLS")
    closes = _calm(max(60, real.params["period"] + 10)) + [80.0]
    assert evaluate_cell(real, _mid(closes))
