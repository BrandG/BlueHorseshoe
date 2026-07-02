"""Bud entry-location gate: high-ATR ∩ NY skip for the strong-4 long-MR sleeve.

Single source of truth for the validated entry-location rule. Imported by both
``bud.briefing`` (annotate + recommend) and ``bud.auto_v2`` (Phase-1 dark: journal
``would_skip``; the hard skip is flag-gated for Phase 3).

The rule (validated per-trade — recovers +17% of the strong-4 long book by declining
trades that lose money per trade):

    skip ⟺ strategy ∈ {bb, rsi, ema, stoch} AND direction == long
           AND trigger-bar session == NY
           AND ATR(14) trailing-252 percentile ≥ 2/3   (the "high" volatility bucket)

Scope is deliberately narrow: the corner does NOT generalize to shorts (flat) or to the
full-6 extras cci/sma (diluted, not significant) — see research/entry_location_v1/ and
docs/planning/BUD_ENTRY_LOCATION_RESEARCH.md / BUD_HIGH_NY_SKIP_WIRING.md.

Fail-open: if the ATR percentile can't be computed (data gap / insufficient history),
``is_high_ny_skip`` returns False — a trade is never suppressed on uncertainty.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bh_ftmo.indicators import atr
from bh_ftmo.indicators.sessions import Session, session_label

STRONG4_LONG = frozenset({"bb", "rsi", "ema", "stoch"})
ATR_PERIOD = 14
ATR_PCT_WINDOW = 252
ATR_HIGH_PCT = 2.0 / 3.0                       # "high" bucket = 67th–100th percentile
MIN_BARS_REQUIRED = ATR_PCT_WINDOW + ATR_PERIOD  # 266; briefing/auto load 300 → satisfied
NY_SESSION = Session.NY.value                  # "ny"

# Entry-location: skip high-ATR ∩ NY entries on the strong-4 long-MR sleeve
# (research/entry_location_v1/: −0.07R/trade, holdout-passed, +17% of the strong-4
# long book). PHASE 1 = dark: journal `would_skip_high_atr_ny` but STILL PLACE the
# trade — confirms the flag fires at the expected rate with zero behavior change.
# Flip to True for Phase 3 (hard skip). The predicate lives in bud.entry_location.
HIGH_NY_SKIP_ENABLED = False


def atr_pct_w252(mid: pd.DataFrame) -> float:
    """Trailing-252 percentile rank of ATR(14)'s latest value (causal / point-in-time).

    Mirrors the research ``_rolling_percentile`` rank_last exactly: rank the last bar's
    ATR against the finite ATR values in the trailing 252-bar window. Returns ``nan`` if
    fewer than ``ATR_PCT_WINDOW`` finite ATR values are available (caller fails open).
    """
    a = atr(mid, period=ATR_PERIOD).to_numpy(dtype=float)
    if len(a) < ATR_PCT_WINDOW:
        return float("nan")
    window = a[-ATR_PCT_WINDOW:]
    last = window[-1]
    finite = window[np.isfinite(window)]
    if len(finite) < ATR_PCT_WINDOW or not np.isfinite(last):
        return float("nan")
    return float(np.mean(finite <= last))


def session_str(bar_ts: pd.Timestamp) -> str:
    """NY-clock forex session label (asia/london/overlap/ny/closed) for one bar open."""
    label = session_label(pd.Series([pd.Timestamp(bar_ts)])).iloc[0]
    return label.value if isinstance(label, Session) else str(label)


def is_high_ny_skip(
    strategy: str, direction: str, bar_ts: pd.Timestamp, mid: pd.DataFrame
) -> bool:
    """True iff this fire is a strong-4 long, high-ATR, NY-session entry (the skip corner)."""
    if strategy not in STRONG4_LONG or direction != "long":
        return False
    if session_str(bar_ts) != NY_SESSION:
        return False
    pct = atr_pct_w252(mid)
    return bool(np.isfinite(pct) and pct >= ATR_HIGH_PCT)
