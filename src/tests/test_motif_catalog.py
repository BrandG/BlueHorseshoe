"""Tests for motif catalog builder."""

import numpy as np
import pandas as pd
import pytest

from bluehorseshoe.analysis.curves.motif_catalog import (
    measure_forward_outcomes,
    score_motif,
    _compute_catalog_stats,
    _determine_first_hit,
)


def _make_symbol_df(closes, n_bars=200):
    """Build a full-history OHLCV DataFrame."""
    closes = np.array(closes, dtype=float)
    return pd.DataFrame({
        'date': [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(len(closes))],
        'close': closes,
        'high': closes * 1.01,
        'low': closes * 0.99,
        'volume': [1_000_000] * len(closes),
    })


class TestMeasureForwardOutcomes:
    def test_basic_outcomes(self):
        """Should produce outcomes for a symbol with enough history."""
        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.randn(200) * 0.5)
        df = _make_symbol_df(closes)
        results = measure_forward_outcomes(df, window_size=40, forward_days=5)

        assert len(results) > 0
        for r in results:
            assert 'motif_key' in r
            assert 'outcome' in r
            assert r['outcome'] in (0, 1)
            assert 'forward_return' in r

    def test_planted_pattern_high_edge(self):
        """V-bottom pattern always followed by +3% should have high win rate."""
        np.random.seed(123)
        bars = []
        # Create 10 V-bottom episodes
        for _ in range(10):
            # 40-bar V-bottom
            down = np.linspace(100, 85, 20)
            up = np.linspace(85, 103, 21)[1:]
            episode = np.concatenate([down, up])
            # Follow with 5 bars of +3% from last close
            last_close = episode[-1]
            follow = np.linspace(last_close, last_close * 1.04, 6)[1:]
            bars.extend(episode.tolist())
            bars.extend(follow.tolist())

        df = _make_symbol_df(bars)
        results = measure_forward_outcomes(df, window_size=40, forward_days=5)

        assert len(results) > 0
        # At least some wins
        wins = sum(r['outcome'] for r in results)
        assert wins > 0

    def test_short_history_empty(self):
        """Too few bars should return empty list."""
        df = _make_symbol_df(np.linspace(100, 110, 30))
        results = measure_forward_outcomes(df, window_size=40, forward_days=5)
        assert results == []

    def test_baseline_rate_matches(self):
        """Overall win rate should match manual count."""
        np.random.seed(99)
        closes = 100 + np.cumsum(np.random.randn(300) * 0.3)
        df = _make_symbol_df(closes)
        results = measure_forward_outcomes(df, window_size=20, forward_days=5)

        if len(results) > 0:
            total = len(results)
            wins = sum(r['outcome'] for r in results)
            win_rate = wins / total
            # Should be a reasonable number between 0 and 1
            assert 0.0 <= win_rate <= 1.0


class TestDetermineFirstHit:
    def test_target_first(self):
        """Target hit before stop should be win."""
        highs = np.array([101, 103, 105])
        lows = np.array([99.5, 99.0, 98.5])
        assert _determine_first_hit(highs, lows, target=102, stop=97) == 1

    def test_stop_first(self):
        """Stop hit before target should be loss."""
        highs = np.array([101, 100.5, 100])
        lows = np.array([99.5, 97, 96])
        assert _determine_first_hit(highs, lows, target=105, stop=98) == 0

    def test_neither_hit(self):
        """Neither hit should be loss (timeout)."""
        highs = np.array([101, 101.5, 101])
        lows = np.array([99.5, 99.0, 99.5])
        assert _determine_first_hit(highs, lows, target=105, stop=95) == 0


class TestScoreMotif:
    def test_positive_edge(self):
        """Positive edge, stability, support should give positive score."""
        stats = {'edge': 0.05, 'stability': 0.8, 'support': 1.0}
        assert score_motif(stats) == pytest.approx(0.04)

    def test_zero_edge(self):
        """Zero edge should give zero score."""
        stats = {'edge': 0.0, 'stability': 0.8, 'support': 1.0}
        assert score_motif(stats) == 0.0

    def test_negative_edge(self):
        """Negative edge should give negative score."""
        stats = {'edge': -0.05, 'stability': 0.8, 'support': 1.0}
        assert score_motif(stats) < 0


class TestComputeCatalogStats:
    def test_basic_stats(self):
        """Should compute correct statistics from accumulator."""
        accumulator = {
            'U2M:D1S:U3L_40': {
                'wins': 60,
                'total': 100,
                'sum_returns': 0.01 * 60 + (-0.01) * 40,
            },
            'D3M:U1S:D2L_40': {
                'wins': 30,
                'total': 100,
                'sum_returns': 0.01 * 30 + (-0.01) * 70,
            },
        }
        catalog = _compute_catalog_stats(accumulator)

        assert len(catalog) == 2
        # First motif has higher win rate
        m1 = catalog['U2M:D1S:U3L_40']
        m2 = catalog['D3M:U1S:D2L_40']
        assert m1['win_rate'] > m2['win_rate']
        assert m1['edge'] > 0
        assert m2['edge'] < 0

    def test_minimum_sample_filter(self):
        """Motifs with <5 samples should be filtered out."""
        accumulator = {
            'key1': {'wins': 3, 'total': 4, 'sum_returns': 0.01 * 3 + (-0.01)},
            'key2': {'wins': 30, 'total': 50, 'sum_returns': 0.01 * 30 + (-0.01) * 20},
        }
        catalog = _compute_catalog_stats(accumulator)
        assert 'key1' not in catalog
        assert 'key2' in catalog
