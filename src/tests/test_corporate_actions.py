"""Tests for the corporate-action detectors (merger-pin price signature + news scan).

Motivating case: KW/Kennedy-Wilson, bought at $10.93 into a $10.90 cash
take-private — pinned price, frozen position, merger headlines in the feed.
"""
from datetime import datetime

import numpy as np
import pandas as pd

from bluehorseshoe.analysis.liquidity import is_merger_pinned
from bluehorseshoe.analysis.corporate_actions import (
    CorporateActionFlag,
    assess_corporate_action,
    scan_news_for_merger,
)


def _frame(closes, highs=None, lows=None):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "close": closes,
            "high": closes if highs is None else np.asarray(highs, dtype=float),
            "low": closes if lows is None else np.asarray(lows, dtype=float),
            "volume": np.full(closes.size, 1e6),
        }
    )


# --- Layer B: is_merger_pinned ------------------------------------------------

def test_pinned_series_is_flagged():
    """Normal volatility for ~250 days, then dead-flat near a deal price."""
    rng = np.random.default_rng(0)
    base = 11.0 + np.cumsum(rng.normal(0.0, 0.22, 250))  # ~2% daily moves
    base = np.clip(base, 5.0, None)
    flat = 10.90 + rng.normal(0.0, 0.01, 18)  # 18 > window so the gap is out of window
    assert is_merger_pinned(_frame(np.concatenate([base, flat]))) is True


def test_perpetually_quiet_series_is_not_flagged():
    """Always-quiet name: tight band but NO vol collapse vs its own baseline."""
    rng = np.random.default_rng(1)
    quiet = 10.90 + rng.normal(0.0, 0.01, 268)
    assert is_merger_pinned(_frame(quiet)) is False


def test_normal_volatile_series_is_not_flagged():
    rng = np.random.default_rng(2)
    vol = 50.0 + np.cumsum(rng.normal(0.0, 1.0, 268))
    vol = np.clip(vol, 5.0, None)
    assert is_merger_pinned(_frame(vol)) is False


def test_insufficient_data_fails_open():
    assert is_merger_pinned(_frame([10.9, 10.9, 10.9])) is False
    assert is_merger_pinned(pd.DataFrame()) is False
    assert is_merger_pinned(pd.DataFrame({"volume": [1, 2, 3]})) is False


# --- Layer C: scan_news_for_merger -------------------------------------------

NOW = datetime(2026, 6, 16, 12, 0, 0)


def _news(title, summary="", when="20260610T120000", relevance="0.9", ticker="KW"):
    return {
        "title": title,
        "summary": summary,
        "time_published": when,
        "ticker_sentiment": [{"ticker": ticker, "relevance_score": relevance}],
    }


def test_news_title_keyword_is_a_hit():
    feed = [_news("Kennedy Wilson to be acquired in all-cash take-private deal")]
    res = scan_news_for_merger(feed, "KW", now=NOW)
    assert res["hit"] is True
    assert res["latest"] == "2026-06-10"
    assert len(res["headlines"]) == 1


def test_summary_only_match_requires_relevance():
    low = [_news("Markets wrap", summary="...per share in cash...", relevance="0.05")]
    high = [_news("Markets wrap", summary="...per share in cash...", relevance="0.9")]
    assert scan_news_for_merger(low, "KW", now=NOW)["hit"] is False
    assert scan_news_for_merger(high, "KW", now=NOW)["hit"] is True


def test_old_news_outside_lookback_is_excluded():
    feed = [_news("Acme to be acquired", when="20240101T120000")]
    assert scan_news_for_merger(feed, "ACME", now=NOW, lookback_days=270)["hit"] is False


def test_unrelated_news_is_not_a_hit():
    feed = [
        _news("Company beats earnings estimates"),
        _news("Analyst raises price target"),
    ]
    assert scan_news_for_merger(feed, "KW", now=NOW)["hit"] is False


def test_empty_feed_is_safe():
    assert scan_news_for_merger([], "KW", now=NOW)["hit"] is False


# --- Orchestrator: assess_corporate_action -----------------------------------

def test_assess_price_only_no_database():
    rng = np.random.default_rng(0)
    base = 11.0 + np.cumsum(rng.normal(0.0, 0.22, 250))
    base = np.clip(base, 5.0, None)
    flat = 10.90 + rng.normal(0.0, 0.01, 18)
    flag = assess_corporate_action("KW", _frame(np.concatenate([base, flat])), database=None)
    assert isinstance(flag, CorporateActionFlag)
    assert flag.pinned is True
    assert flag.news_merger is False
    assert flag.flagged is True
    payload = flag.to_dict()
    assert payload["flagged"] is True and "pinned" in payload["reason"]


def test_flag_not_set_when_clean():
    rng = np.random.default_rng(2)
    vol = 50.0 + np.cumsum(rng.normal(0.0, 1.0, 268))
    vol = np.clip(vol, 5.0, None)
    flag = assess_corporate_action("AAA", _frame(vol), database=None)
    assert flag.flagged is False
    assert flag.reason == "none"
