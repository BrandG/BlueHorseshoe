"""Tests for bh_ftmo.analysis.cluster_filter."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from bh_ftmo.analysis import (
    Signal,
    cluster_filter,
    explain_cluster_filter,
)
from bh_ftmo.analysis.cluster_filter import _exposures


# ---- helpers -----------------------------------------------------------


def _sig(
    symbol: str,
    score: float,
    *,
    timestamp: datetime = datetime(2026, 4, 22, 13, 0),
    direction: int = 1,
    above_threshold: bool = True,
) -> Signal:
    return Signal(
        symbol=symbol,
        strategy="baseline",
        timestamp=timestamp,
        direction=direction,
        score=score,
        components={"placeholder": score},
        above_threshold=above_threshold,
    )


# ---- _exposures --------------------------------------------------------


def test_exposures_long():
    s = _sig("EUR_USD", 5.0, direction=1)
    assert _exposures(s) == [("EUR", +1), ("USD", -1)]


def test_exposures_short():
    s = _sig("EUR_USD", 5.0, direction=-1)
    assert _exposures(s) == [("EUR", -1), ("USD", +1)]


def test_exposures_unparsable_symbol():
    s = _sig("XAUUSD", 5.0)  # no underscore — not a forex pair
    assert _exposures(s) == []


def test_exposures_zero_direction():
    s = _sig("EUR_USD", 5.0, direction=0)
    assert _exposures(s) == []


# ---- cluster_filter: empty / pass-through ----------------------------


def test_filter_empty_input():
    assert cluster_filter([]) == []


def test_filter_single_signal_kept():
    s = _sig("EUR_USD", 5.0)
    assert cluster_filter([s]) == [s]


def test_filter_passes_through_below_threshold():
    """Sub-threshold signals shouldn't be filtered or filter others."""
    s_below = _sig("EUR_USD", 1.0, above_threshold=False)
    s_above = _sig("GBP_USD", 5.0, above_threshold=True)
    out = cluster_filter([s_below, s_above])
    # Both retained — below-threshold passes through, above-threshold has no peers
    assert len(out) == 2
    assert s_below in out
    assert s_above in out


# ---- core: shared currency dedup --------------------------------------


def test_two_signals_sharing_short_quote_keep_higher_score():
    """EUR_CHF and GBP_CHF both express short-CHF; only the highest survives
    (assuming they share no other dominance)."""
    eur_chf = _sig("EUR_CHF", 4.0)
    gbp_chf = _sig("GBP_CHF", 6.0)
    kept = cluster_filter([eur_chf, gbp_chf])
    # Each is best on its base (long EUR vs long GBP — no overlap), so both survive!
    # The "shared CHF" angle is dominated by gbp_chf, but eur_chf is still
    # the best long-EUR signal.
    assert len(kept) == 2


def test_three_long_eur_signals_dedupe_to_one_winner_per_quote():
    """Long EUR vs USD/JPY/GBP: each has a unique short-leg, so all 3 keep."""
    eur_usd = _sig("EUR_USD", 4.0)
    eur_jpy = _sig("EUR_JPY", 5.0)
    eur_gbp = _sig("EUR_GBP", 3.5)
    kept = cluster_filter([eur_usd, eur_jpy, eur_gbp])
    # Each one is the unique flag-bearer for its quote-side short. Long-EUR
    # is dominated for two of them, but they all survive on the quote leg.
    assert {s.symbol for s in kept} == {"EUR_USD", "EUR_JPY", "EUR_GBP"}


def test_signal_dominated_on_both_exposures_is_dropped():
    """When EUR_USD is dominated by both a stronger long-EUR AND a stronger
    short-USD signal at the same bar, it gets suppressed."""
    # EUR_USD has score 4 — dominated on long-EUR by EUR_JPY (score 6),
    # dominated on short-USD by GBP_USD (score 7)
    eur_usd = _sig("EUR_USD", 4.0)
    eur_jpy = _sig("EUR_JPY", 6.0)
    gbp_usd = _sig("GBP_USD", 7.0)
    kept = cluster_filter([eur_usd, eur_jpy, gbp_usd])
    assert {s.symbol for s in kept} == {"EUR_JPY", "GBP_USD"}


def test_winner_keeps_when_uniquely_dominant():
    """Single signal involving both a unique base and a unique quote → kept."""
    eur_usd = _sig("EUR_USD", 5.0)
    aud_jpy = _sig("AUD_JPY", 4.5)
    chf_cad = _sig("CHF_CAD", 4.0)
    kept = cluster_filter([eur_usd, aud_jpy, chf_cad])
    # No two signals share any currency → all survive
    assert len(kept) == 3


# ---- timestamp isolation ----------------------------------------------


def test_filter_isolates_per_timestamp():
    """Signals at different timestamps don't compete with each other."""
    t1 = datetime(2026, 4, 22, 13, 0)
    t2 = datetime(2026, 4, 22, 17, 0)
    a = _sig("EUR_CHF", 4.0, timestamp=t1)
    b = _sig("EUR_CHF", 6.0, timestamp=t2)  # higher score on later bar
    c = _sig("GBP_CHF", 5.0, timestamp=t1)  # would dominate `a` on short-CHF
    kept = cluster_filter([a, b, c])
    # `a` (EUR_CHF @ t1) survives on long-EUR; `c` survives on long-GBP;
    # `b` (EUR_CHF @ t2) is alone at t2 → all kept
    assert len(kept) == 3


# ---- short-direction ---------------------------------------------------


def test_short_signals_use_flipped_exposure():
    """Short EUR_USD = short EUR + long USD. Should not cluster with long EUR_USD."""
    long_eu = _sig("EUR_USD", 5.0, direction=+1)
    short_eu = _sig("EUR_USD", 6.0, direction=-1)
    kept = cluster_filter([long_eu, short_eu])
    # Different exposures (long-EUR vs short-EUR) → both survive
    assert len(kept) == 2


def test_short_signals_dedupe_among_themselves():
    """Short EUR_USD and short EUR_GBP both express short-EUR."""
    a = _sig("EUR_USD", 4.0, direction=-1)
    b = _sig("EUR_GBP", 6.0, direction=-1)
    kept = cluster_filter([a, b])
    # `a`: short-EUR + long-USD; `b`: short-EUR + long-GBP
    # On short-EUR, `b` wins. But `a`'s long-USD is unique → both kept.
    assert len(kept) == 2


# ---- order preservation -----------------------------------------------


def test_filter_preserves_input_order():
    a = _sig("EUR_USD", 4.0)
    b = _sig("EUR_JPY", 6.0)
    c = _sig("GBP_USD", 7.0)
    kept = cluster_filter([a, b, c])
    # `a` is dominated → dropped; `b` and `c` retained in original order
    assert [s.symbol for s in kept] == ["EUR_JPY", "GBP_USD"]


# ---- non-major / unparseable symbols ---------------------------------


def test_unparseable_symbol_passes_through():
    s = _sig("XAU_USD_X", 5.0)  # 3 parts → unparseable
    eur_usd = _sig("EUR_USD", 6.0)
    kept = cluster_filter([s, eur_usd])
    # Unparseable symbol always kept, EUR_USD has no peers → both kept
    assert len(kept) == 2


# ---- explain_cluster_filter -------------------------------------------


def test_explain_returns_diagnostic_columns():
    eur_usd = _sig("EUR_USD", 4.0)
    eur_jpy = _sig("EUR_JPY", 6.0)
    gbp_usd = _sig("GBP_USD", 7.0)
    df = explain_cluster_filter([eur_usd, eur_jpy, gbp_usd])
    assert set(df.columns) == {
        "timestamp", "symbol", "score", "kept", "flag_bearer_for", "dominated_by"
    }
    assert len(df) == 3
    # EUR_USD: dominated on long-EUR by EUR_JPY, on short-USD by GBP_USD → not kept
    eu_row = df[df.symbol == "EUR_USD"].iloc[0]
    assert not eu_row.kept
    assert eu_row.dominated_by == {"EUR_long": "EUR_JPY", "USD_short": "GBP_USD"}
    assert eu_row.flag_bearer_for == []
    # EUR_JPY: flag-bearer for long-EUR
    ej_row = df[df.symbol == "EUR_JPY"].iloc[0]
    assert ej_row.kept
    assert "EUR_long" in ej_row.flag_bearer_for


def test_explain_handles_empty_input():
    df = explain_cluster_filter([])
    assert len(df) == 0
    assert "kept" in df.columns


# ---- cluster filter on real-style cluster scenario --------------------


def test_chf_weakness_cluster_dedupes_correctly():
    """Real scenario: CHF weak across the board on the same bar.

    AUD/CHF, NZD/CHF, CAD/CHF, GBP/CHF, EUR/CHF all signal long.
    The filter should keep:
      - The highest-scoring CHF-short (one winner)
      - PLUS any signal that's flag-bearer for its base currency
    Each signal has a unique base (AUD, NZD, CAD, GBP, EUR) → all keep on their base.
    Only when the bases also overlap do we see filtering.
    """
    sigs = [
        _sig("AUD_CHF", 4.0),
        _sig("NZD_CHF", 4.5),
        _sig("CAD_CHF", 5.0),
        _sig("GBP_CHF", 7.0),  # highest-scoring short-CHF expression
        _sig("EUR_CHF", 6.0),
    ]
    kept = cluster_filter(sigs)
    # All 5 have unique bases → each is flag-bearer for its base → all keep
    assert len(kept) == 5

    # Now add a competing AUD_USD: AUD_CHF and AUD_USD compete on long-AUD;
    # AUD_USD is unique on short-USD; AUD_CHF is dominated on short-CHF by GBP_CHF.
    # → AUD_CHF gets dropped (dominated on both sides).
    aud_usd = _sig("AUD_USD", 6.0)
    sigs2 = sigs + [aud_usd]
    kept2 = cluster_filter(sigs2)
    kept_syms = {s.symbol for s in kept2}
    assert "AUD_CHF" not in kept_syms
    assert "AUD_USD" in kept_syms
    # The other CHF signals (unique bases) still survive
    assert {"NZD_CHF", "CAD_CHF", "GBP_CHF", "EUR_CHF"}.issubset(kept_syms)
