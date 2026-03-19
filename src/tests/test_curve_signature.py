"""Tests for curve signature extraction module."""

import numpy as np
import pandas as pd
import pytest

from bluehorseshoe.analysis.curves.segmenter import (
    segment_price_series,
    Segment,
    Segmentation,
    TurningPoint,
)
from bluehorseshoe.analysis.curves.signature import (
    CurveSignature,
    extract_signature,
    signatures_similar,
    _bucket,
    _segment_descriptors,
)


def _make_df(closes, high_offset=2.0, low_offset=2.0):
    """Build a minimal OHLCV DataFrame from close prices."""
    closes = np.array(closes, dtype=float)
    return pd.DataFrame({
        'date': [f"2025-01-{i+1:02d}" for i in range(len(closes))],
        'close': closes,
        'high': closes + high_offset,
        'low': closes - low_offset,
        'volume': [1_000_000] * len(closes),
    })


class TestBucketing:
    def test_magnitude_buckets(self):
        from bluehorseshoe.analysis.curves.signature import _MAG_THRESHOLDS
        assert _bucket(0.3, _MAG_THRESHOLDS) == 0   # tiny
        assert _bucket(1.0, _MAG_THRESHOLDS) == 1   # small
        assert _bucket(2.0, _MAG_THRESHOLDS) == 2   # medium
        assert _bucket(4.0, _MAG_THRESHOLDS) == 3   # large
        assert _bucket(6.0, _MAG_THRESHOLDS) == 4   # huge

    def test_duration_buckets(self):
        from bluehorseshoe.analysis.curves.signature import _DUR_THRESHOLDS
        assert _bucket(3, _DUR_THRESHOLDS) == 0   # short
        assert _bucket(7, _DUR_THRESHOLDS) == 1   # medium
        assert _bucket(15, _DUR_THRESHOLDS) == 2  # long


class TestExtractSignature:
    def test_v_bottom_motif_key(self):
        """V-bottom should produce a key starting with D*:U*."""
        down = np.linspace(100, 80, 20)
        up = np.linspace(80, 100, 21)[1:]
        closes = np.concatenate([down, up])
        df = _make_df(closes)
        seg = segment_price_series(df, window_size=40, epsilon=0.5)
        sig = extract_signature(seg)

        assert isinstance(sig, CurveSignature)
        assert len(sig.vector) == 17

        # The key should contain D (down) and U (up) tokens
        tokens = sig.motif_key.split(':')
        assert len(tokens) == 3
        # Last two should show down then up pattern
        has_down = any(t.startswith('D') for t in tokens)
        has_up = any(t.startswith('U') for t in tokens)
        assert has_down and has_up

    def test_normalization_invariance(self):
        """Same shape at different price scales should produce identical motif_key."""
        base = np.concatenate([
            np.linspace(100, 85, 15),
            np.linspace(85, 100, 10),
            np.linspace(100, 90, 15)
        ])
        scaled = base * 3

        df1 = _make_df(base)
        df2 = _make_df(scaled, high_offset=6.0, low_offset=6.0)

        seg1 = segment_price_series(df1, window_size=40, epsilon=1.0)
        seg2 = segment_price_series(df2, window_size=40, epsilon=1.0)

        sig1 = extract_signature(seg1)
        sig2 = extract_signature(seg2)

        assert sig1.motif_key == sig2.motif_key

    def test_padding_short_history(self):
        """1-segment input should produce valid 17-dim vector with padding."""
        closes = np.linspace(100, 110, 20)
        df = _make_df(closes)
        seg = segment_price_series(df, window_size=20, epsilon=1.0)

        # Should have 1 segment (straight line)
        assert len(seg.segments) <= 2

        sig = extract_signature(seg)
        assert len(sig.vector) == 17
        assert sig.segment_count == len(seg.segments)
        # Motif key should have 3 tokens (padded)
        assert len(sig.motif_key.split(':')) == 3

    def test_vector_dimensions(self):
        """Vector should always be 17 dimensions."""
        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.randn(40))
        df = _make_df(closes)
        seg = segment_price_series(df, window_size=40, epsilon=1.0)
        sig = extract_signature(seg)
        assert len(sig.vector) == 17

    def test_global_features(self):
        """total_range and net_direction should be last two vector elements."""
        closes = np.concatenate([
            np.linspace(100, 80, 20),
            np.linspace(80, 100, 21)[1:]
        ])
        df = _make_df(closes)
        seg = segment_price_series(df, window_size=40, epsilon=0.5)
        sig = extract_signature(seg)

        total_range = sig.vector[15]
        net_direction = sig.vector[16]

        assert total_range > 0
        # V-shape has small net displacement but large total path
        assert 0.0 <= net_direction <= 1.0

    def test_empty_segmentation(self):
        """Empty segmentation should produce padded signature."""
        seg = Segmentation(
            symbol="TEST", window_size=40,
            segments=[], turning_points=[],
            atr_mean=1.0, start_date="", end_date=""
        )
        sig = extract_signature(seg)
        assert len(sig.vector) == 17
        assert sig.segment_count == 0


class TestSignaturesSimilar:
    def test_identical_signatures(self):
        """Identical signatures should be similar."""
        closes = np.linspace(100, 120, 40)
        df = _make_df(closes)
        seg = segment_price_series(df, window_size=40, epsilon=1.0)
        sig = extract_signature(seg)
        assert signatures_similar(sig, sig, max_hamming=0)

    def test_different_signatures(self):
        """Very different shapes should not be similar."""
        # Strong uptrend
        df1 = _make_df(np.linspace(100, 150, 40))
        seg1 = segment_price_series(df1, window_size=40, epsilon=1.0)
        sig1 = extract_signature(seg1)

        # V-bottom
        down = np.linspace(100, 70, 20)
        up = np.linspace(70, 100, 21)[1:]
        df2 = _make_df(np.concatenate([down, up]))
        seg2 = segment_price_series(df2, window_size=40, epsilon=0.5)
        sig2 = extract_signature(seg2)

        # Should differ in many dimensions
        hamming = sum(1 for i in range(15) if sig1.vector[i] != sig2.vector[i])
        assert hamming > 3
        assert not signatures_similar(sig1, sig2, max_hamming=3)
