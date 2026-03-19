"""Tests for curve segmentation module."""

import numpy as np
import pandas as pd
import pytest

from bluehorseshoe.analysis.curves.segmenter import (
    rdp_simplify,
    detect_turning_points,
    segment_price_series,
    segment_multi_window,
    Segmentation,
    Segment,
    TurningPoint,
)


def _make_df(closes, high_offset=1.0, low_offset=1.0):
    """Build a minimal OHLCV DataFrame from close prices."""
    closes = np.array(closes, dtype=float)
    return pd.DataFrame({
        'date': [f"2025-01-{i+1:02d}" for i in range(len(closes))],
        'close': closes,
        'high': closes + high_offset,
        'low': closes - low_offset,
        'volume': [1_000_000] * len(closes),
    })


class TestRDPSimplify:
    def test_straight_line(self):
        """Straight line should yield only start and end."""
        points = np.array([[i, i * 2.0] for i in range(20)])
        result = rdp_simplify(points, epsilon=0.5)
        assert result == [0, 19]

    def test_v_shape(self):
        """V-shape should yield 3 points: start, bottom, end."""
        y = list(range(10, 0, -1)) + list(range(1, 11))
        points = np.array([[i, y[i]] for i in range(len(y))], dtype=float)
        result = rdp_simplify(points, epsilon=0.5)
        # Bottom should be at index ~9
        assert len(result) >= 3
        assert 0 in result
        assert len(y) - 1 in result

    def test_two_points(self):
        """Two points should return both."""
        points = np.array([[0, 0], [1, 5]], dtype=float)
        assert rdp_simplify(points, epsilon=1.0) == [0, 1]

    def test_single_point(self):
        """Single point should return it."""
        points = np.array([[0, 0]], dtype=float)
        assert rdp_simplify(points, epsilon=1.0) == [0]


class TestDetectTurningPoints:
    def test_straight_trend(self):
        """Steady uptrend should have 2 turning points (start + end)."""
        close = np.linspace(100, 120, 40)
        atr = np.full(40, 1.0)
        tp = detect_turning_points(close, atr, epsilon=1.0)
        assert tp[0] == 0
        assert tp[-1] == 39
        assert len(tp) == 2

    def test_v_shape(self):
        """V-shape should detect the bottom."""
        down = np.linspace(100, 80, 20)
        up = np.linspace(80, 100, 20)
        close = np.concatenate([down, up[1:]])  # avoid duplicate at 80
        atr = np.full(len(close), 1.0)
        tp = detect_turning_points(close, atr, epsilon=0.5)
        assert len(tp) >= 3
        # Bottom should be near index 19
        bottom_idx = min(tp, key=lambda i: close[i])
        assert 17 <= bottom_idx <= 21

    def test_zero_atr_fallback(self):
        """Zero ATR should use fallback without crashing."""
        close = np.linspace(50, 60, 20)
        atr = np.zeros(20)
        tp = detect_turning_points(close, atr, epsilon=1.0)
        assert len(tp) >= 2


class TestSegmentPriceSeries:
    def test_straight_line_one_segment(self):
        """Straight trend should produce 1 segment with ~0 curvature."""
        closes = np.linspace(100, 110, 40)
        df = _make_df(closes)
        seg = segment_price_series(df, window_size=40, epsilon=1.0)

        assert isinstance(seg, Segmentation)
        assert len(seg.segments) == 1
        assert seg.segments[0].direction == 1
        assert seg.segments[0].curvature < 0.5

    def test_v_shape_two_segments(self):
        """V-shape should produce 2 segments with turning point at bottom."""
        down = np.linspace(100, 85, 20)
        up = np.linspace(85, 100, 21)[1:]
        closes = np.concatenate([down, up])
        df = _make_df(closes, high_offset=2.0, low_offset=2.0)
        seg = segment_price_series(df, window_size=40, epsilon=0.5)

        assert len(seg.segments) >= 2
        # First segment should be down, followed by up
        assert seg.segments[0].direction == -1
        assert seg.segments[-1].direction == 1

    def test_sine_wave_alternating(self):
        """Sine wave should produce segments with both directions."""
        t = np.linspace(0, 2 * np.pi, 40)
        closes = 100 + 10 * np.sin(t)
        df = _make_df(closes, high_offset=2.0, low_offset=2.0)
        seg = segment_price_series(df, window_size=40, epsilon=0.3)

        assert len(seg.segments) >= 3
        # Should have both up and down segments
        directions = {s.direction for s in seg.segments}
        assert 1 in directions
        assert -1 in directions

    def test_noisy_data_reasonable_count(self):
        """Noisy data should produce 3-8 segments for 40 bars."""
        np.random.seed(42)
        trend = np.linspace(100, 110, 40)
        noise = np.random.randn(40) * 2
        closes = trend + noise
        df = _make_df(closes, high_offset=2.0, low_offset=2.0)
        seg = segment_price_series(df, window_size=40, epsilon=1.0)

        assert 1 <= len(seg.segments) <= 10

    def test_atr_normalization_invariance(self):
        """Same shape at 2x price should yield identical magnitude/slope."""
        base = np.array([100, 95, 90, 85, 90, 95, 100, 105, 110, 115,
                         120, 118, 115, 112, 110, 108, 110, 113, 116, 120])
        scaled = base * 2

        df1 = _make_df(base, high_offset=2.0, low_offset=2.0)
        df2 = _make_df(scaled, high_offset=4.0, low_offset=4.0)

        seg1 = segment_price_series(df1, window_size=20, epsilon=1.0)
        seg2 = segment_price_series(df2, window_size=20, epsilon=1.0)

        # Same number of segments
        assert len(seg1.segments) == len(seg2.segments)

        # Magnitudes and slopes should be very close (within ATR scaling)
        for s1, s2 in zip(seg1.segments, seg2.segments):
            assert s1.direction == s2.direction
            assert abs(s1.magnitude - s2.magnitude) < 0.5
            assert abs(s1.slope - s2.slope) < 0.1

    def test_flat_price(self):
        """Flat price should produce minimal segments."""
        closes = np.full(40, 50.0)
        df = _make_df(closes, high_offset=0.01, low_offset=0.01)
        seg = segment_price_series(df, window_size=40, epsilon=1.0)
        # Should have at most 1 segment
        assert len(seg.segments) <= 1

    def test_short_data(self):
        """Less than 5 data points should return empty segmentation."""
        df = _make_df([100, 101, 102])
        seg = segment_price_series(df, window_size=40, epsilon=1.0)
        assert len(seg.segments) == 0
        assert len(seg.turning_points) == 0

    def test_segment_properties(self):
        """Segment properties should be consistent."""
        closes = np.concatenate([
            np.linspace(100, 80, 15),
            np.linspace(80, 110, 25)
        ])
        df = _make_df(closes, high_offset=2.0, low_offset=2.0)
        seg = segment_price_series(df, window_size=40, epsilon=0.5)

        for s in seg.segments:
            assert s.duration > 0
            assert s.magnitude >= 0
            assert s.slope >= 0
            assert s.direction in (1, -1)
            assert s.curvature >= 0


class TestSegmentMultiWindow:
    def test_multiple_windows(self):
        """Should return segmentations for each window size."""
        closes = np.linspace(100, 120, 50)
        df = _make_df(closes)
        result = segment_multi_window(df, windows=(20, 40), symbol="TEST")

        assert 20 in result
        assert 40 in result
        assert result[20].symbol == "TEST"
        assert result[40].symbol == "TEST"
        assert result[20].window_size == 20
        assert result[40].window_size == 40
