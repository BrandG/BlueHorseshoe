"""
Tests for analyze_sentiment_impact.py

Covers:
- Trade simulation (win, loss, timeout, no-entry, no-data, same-bar scenarios)
- Sentiment bucketing logic
- Bucket statistics computation
"""

import pandas as pd
import pytest

from analyze_sentiment_impact import (
    simulate_trade,
    bucket_sentiment,
    compute_bucket_stats,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_ohlcv(rows):
    """Build a DataFrame from (date, open, high, low, close) tuples."""
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df


# ── simulate_trade tests ─────────────────────────────────────────────────

class TestSimulateTrade:

    def test_win_hits_target(self):
        """Price reaches take-profit → WIN."""
        ohlcv = _make_ohlcv([
            ("2026-01-02", 100, 105, 99, 102),  # entry at 100, dips to 99
            ("2026-01-03", 101, 110, 100, 108),  # hits target 107
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=95, take_profit=107,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=5,
        )
        assert outcome == "WIN"
        assert pnl == pytest.approx(7.0, abs=0.01)
        assert days == 1

    def test_loss_hits_stop(self):
        """Price hits stop-loss → LOSS."""
        ohlcv = _make_ohlcv([
            ("2026-01-02", 100, 101, 99, 100),   # entry at 100
            ("2026-01-03", 99, 99, 93, 94),       # hits stop 95
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=95, take_profit=110,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=5,
        )
        assert outcome == "LOSS"
        assert pnl == pytest.approx(-5.0, abs=0.01)
        assert days == 1

    def test_timeout_positive(self):
        """Hold period expires with positive P&L → WIN (mark-to-market)."""
        ohlcv = _make_ohlcv([
            ("2026-01-02", 100, 101, 99, 100),   # entry
            ("2026-01-03", 100, 103, 99, 102),    # no hit
            ("2026-01-04", 102, 104, 101, 103),   # no hit
            ("2026-01-05", 103, 105, 102, 104),   # hold_days=3 expires
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=90, take_profit=115,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=3,
        )
        assert outcome == "WIN"
        assert pnl > 0
        assert days == 3

    def test_timeout_negative(self):
        """Hold period expires with negative P&L → TIMEOUT."""
        ohlcv = _make_ohlcv([
            ("2026-01-02", 100, 101, 99, 100),   # entry
            ("2026-01-03", 100, 100, 97, 98),     # dip but no stop
            ("2026-01-04", 98, 99, 96, 97),       # dip but no stop
            ("2026-01-05", 97, 98, 96, 97),       # hold_days=3 expires
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=90, take_profit=115,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=3,
        )
        assert outcome == "TIMEOUT"
        assert pnl < 0
        assert days == 3

    def test_no_entry(self):
        """Price never dips to entry → NO_ENTRY."""
        ohlcv = _make_ohlcv([
            ("2026-01-02", 105, 110, 103, 108),  # low=103 > entry=100
            ("2026-01-03", 108, 112, 106, 110),
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=95, take_profit=115,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=5,
        )
        assert outcome == "NO_ENTRY"
        assert pnl == 0.0

    def test_no_data(self):
        """Empty future data → NO_DATA."""
        ohlcv = _make_ohlcv([
            ("2025-12-30", 100, 101, 99, 100),
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=95, take_profit=110,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=5,
        )
        assert outcome == "NO_DATA"

    def test_same_bar_stop(self):
        """Entry and stop on same bar → LOSS with 0 days held."""
        ohlcv = _make_ohlcv([
            ("2026-01-02", 100, 101, 90, 92),  # low=90 < stop=95, also low < entry
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=95, take_profit=115,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=5,
        )
        assert outcome == "LOSS"
        assert days == 0

    def test_same_bar_target(self):
        """Entry and target on same bar → WIN with 0 days held."""
        ohlcv = _make_ohlcv([
            ("2026-01-02", 100, 115, 99, 112),  # high=115 >= target, low=99 <= entry
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=90, take_profit=110,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=5,
        )
        assert outcome == "WIN"
        assert pnl == pytest.approx(10.0, abs=0.01)
        assert days == 0

    def test_gap_down_entry(self):
        """Open gaps below entry → fills at open."""
        ohlcv = _make_ohlcv([
            ("2026-01-02", 97, 108, 96, 106),  # open=97 < entry=100, high hits target
        ])
        outcome, pnl, days = simulate_trade(
            entry_price=100, stop_loss=90, take_profit=105,
            ohlcv_df=ohlcv, entry_date="2026-01-01", hold_days=5,
        )
        assert outcome == "WIN"
        # Filled at 97 (open), target at 105 → pnl = (105/97-1)*100
        assert pnl == pytest.approx(((105 / 97) - 1) * 100, abs=0.01)


# ── bucket_sentiment tests ──────────────────────────────────────────────

class TestBucketSentiment:

    def test_zero_is_neutral(self):
        assert bucket_sentiment(0.0) == "Neutral (N/A)"

    def test_strongly_bearish(self):
        assert bucket_sentiment(-0.30) == "Strongly Bearish"
        assert bucket_sentiment(-0.16) == "Strongly Bearish"

    def test_mildly_bearish(self):
        assert bucket_sentiment(-0.10) == "Mildly Bearish"
        assert bucket_sentiment(-0.01) == "Mildly Bearish"

    def test_mildly_bullish(self):
        assert bucket_sentiment(0.05) == "Mildly Bullish"
        assert bucket_sentiment(0.14) == "Mildly Bullish"

    def test_strongly_bullish(self):
        assert bucket_sentiment(0.15) == "Strongly Bullish"
        assert bucket_sentiment(0.50) == "Strongly Bullish"

    def test_boundary_minus_015(self):
        """Exactly -0.15 is the start of Mildly Bearish bucket."""
        assert bucket_sentiment(-0.15) == "Mildly Bearish"
        assert bucket_sentiment(-0.1501) == "Strongly Bearish"

    def test_boundary_plus_015(self):
        """Exactly +0.15 → Strongly Bullish."""
        assert bucket_sentiment(0.15) == "Strongly Bullish"


# ── compute_bucket_stats tests ───────────────────────────────────────────

class TestComputeBucketStats:

    def test_empty_list(self):
        result = compute_bucket_stats([])
        assert result["n"] == 0
        assert result["win_rate"] == 0.0

    def test_all_wins(self):
        records = [
            {"outcome": "WIN", "pnl": 5.0},
            {"outcome": "WIN", "pnl": 3.0},
        ]
        result = compute_bucket_stats(records)
        assert result["n"] == 2
        assert result["win_rate"] == 100.0
        assert result["avg_pnl"] == pytest.approx(4.0)
        assert result["median_pnl"] == pytest.approx(4.0)

    def test_all_losses(self):
        records = [
            {"outcome": "LOSS", "pnl": -3.0},
            {"outcome": "LOSS", "pnl": -5.0},
        ]
        result = compute_bucket_stats(records)
        assert result["n"] == 2
        assert result["win_rate"] == 0.0
        assert result["avg_pnl"] == pytest.approx(-4.0)

    def test_mixed(self):
        records = [
            {"outcome": "WIN", "pnl": 10.0},
            {"outcome": "LOSS", "pnl": -5.0},
            {"outcome": "TIMEOUT", "pnl": -1.0},
            {"outcome": "WIN", "pnl": 3.0},
        ]
        result = compute_bucket_stats(records)
        assert result["n"] == 4
        assert result["win_rate"] == pytest.approx(50.0)
        assert result["avg_pnl"] == pytest.approx(1.75)
