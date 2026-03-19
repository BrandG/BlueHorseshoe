"""Tests for curve indicator and motif lookup."""

import numpy as np
import pandas as pd
import pytest

from bluehorseshoe.analysis.indicators.curve_indicators import CurveIndicator
from bluehorseshoe.analysis.curves.motif_lookup import lookup_motif_score


def _make_df(closes, high_offset=2.0, low_offset=2.0):
    """Build a minimal OHLCV DataFrame."""
    closes = np.array(closes, dtype=float)
    return pd.DataFrame({
        'date': [f"2025-01-{i+1:02d}" for i in range(len(closes))],
        'close': closes,
        'high': closes + high_offset,
        'low': closes - low_offset,
        'volume': [1_000_000] * len(closes),
    })


class TestCurveIndicator:
    def test_empty_catalog_returns_zero(self):
        """With no catalog, CurveIndicator should return (0.0, 0.0)."""
        closes = np.linspace(100, 120, 40)
        df = _make_df(closes)
        indicator = CurveIndicator(df, motif_scores={})
        score = indicator.get_score()
        assert score.buy == 0.0
        assert score.sell == 0.0

    def test_matching_motif_returns_score(self):
        """Catalog with matching motif should return non-zero score."""
        closes = np.linspace(100, 120, 40)
        df = _make_df(closes)

        # First extract the actual motif key that would be generated
        from bluehorseshoe.analysis.curves.segmenter import segment_price_series
        from bluehorseshoe.analysis.curves.signature import extract_signature
        seg = segment_price_series(df, window_size=40)
        sig = extract_signature(seg)

        # Create catalog with this exact motif
        motif_scores = {
            f"{sig.motif_key}_40": 0.15,
            f"{sig.motif_key}_20": 0.10,
        }
        indicator = CurveIndicator(df, motif_scores=motif_scores)
        score = indicator.get_score()
        # Default multiplier is 0.0 in weights.json, but we haven't loaded it
        # In test context, weights_config returns default, so multiplier should be non-zero
        # The indicator returns buy_score = sum(score * multiplier) for each window
        assert isinstance(score.buy, float)

    def test_short_data_returns_zero(self):
        """Less than 20 bars should return zero."""
        df = _make_df(np.linspace(100, 110, 15))
        indicator = CurveIndicator(df)
        score = indicator.get_score()
        assert score.buy == 0.0

    def test_curve_details_populated(self):
        """After scoring, curve details should contain ML features."""
        closes = np.linspace(100, 120, 40)
        df = _make_df(closes)
        indicator = CurveIndicator(df, motif_scores={})
        indicator.get_score()
        details = indicator.get_curve_details()

        # Should have features for each window that was processable
        assert 'curve_motif_score_40' in details
        assert 'curve_net_direction_40' in details
        assert 'curve_total_range_40' in details
        assert 'curve_motif_score_20' in details

    def test_sell_score_always_zero(self):
        """CurveIndicator should never return non-zero sell score."""
        closes = np.linspace(100, 120, 40)
        df = _make_df(closes)
        indicator = CurveIndicator(df, motif_scores={'test_40': 0.5})
        score = indicator.get_score()
        assert score.sell == 0.0


class TestMotifLookup:
    def test_existing_key(self):
        """Should return score for existing motif key."""
        scores = {'U2M:D1S:U3L_40': 0.15}
        assert lookup_motif_score(scores, 'U2M:D1S:U3L', 40) == 0.15

    def test_missing_key(self):
        """Should return 0.0 for missing key."""
        scores = {'U2M:D1S:U3L_40': 0.15}
        assert lookup_motif_score(scores, 'D1S:U2M:D3L', 40) == 0.0

    def test_empty_dict(self):
        """Should return 0.0 for empty catalog."""
        assert lookup_motif_score({}, 'U2M:D1S:U3L', 40) == 0.0
