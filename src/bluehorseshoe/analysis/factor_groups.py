"""Orthogonal factor groups for the GORDON factor briefing.

Locked 2026-06-04 from the double-demeaned (market-removed) cross-sectional
correlation structure of 31 signals (research/indicator_screen/signal_corr.csv,
clustered in factor_grouping.py). Participation ratio = 3.72 effective factors;
PC1 = 50% of variance.

The point of this module is to STOP scoring by summing weighted indicator triggers
(which anti-selects, because ~24 of 31 signals are one redundant no-edge factor and
a sum weights it 24x). Instead the report presents candidates per ORTHOGONAL factor,
each with an honestly-earned confidence badge, and the human picks across factors
(real diversification) rather than down one.

Key structural findings baked in here:
  * There is no standalone "trend" factor — trend-direction signals (psar, di_spread,
    sma_cross, macd, ema_slope) collapse INTO the dominant price-position cluster,
    which is exactly why they anti-predict.
  * ADX clusters with VOLATILITY (bb_width, atr_pct), not with direction.
  * The dominant factor's RAW LEVEL is anti-predictive; its only validated
    edge-bearing transform is oversold DEPTH/PERSISTENCE (the DeepOS edge). So that
    column is ranked by depth, NOT by oscillator level.

Status semantics (the badge):
  VALIDATED — positive, sign-stable-both-halves, post-cost edge through the gauntlet.
  AVOID     — measured anti-predictive (negative edge); shown as context, never a buy.
  UNTESTED  — not yet run through the gauntlet; no ranking dimension validated.
"""
from dataclasses import dataclass, field
from typing import List, Optional


VALIDATED = "validated"
AVOID = "avoid"
UNTESTED = "untested"


@dataclass(frozen=True)
class FactorGroup:
    key: str
    label: str                      # column header in the briefing
    members: List[str]              # signal names from signal_corr.csv that load on this factor
    status: str                     # VALIDATED | AVOID | UNTESTED
    edge_summary: str               # human-readable confidence/edge badge text
    ranking_dimension: Optional[str]  # the VALIDATED within-factor rank key, or None
    strategy: Optional[str]         # registered strategy.name that populates this column, if any
    note: str = ""                  # the honest caveat / how to read this factor


# ---------------------------------------------------------------------------
# The locked groups (order = display order, strongest/known first)
# ---------------------------------------------------------------------------

FACTOR_GROUPS: List[FactorGroup] = [
    FactorGroup(
        key="dislocation",
        label="Dislocation (mean-reversion)",
        # The dominant ~50%-variance factor. Raw level anti-predicts; we read it
        # through its one validated transform: oversold depth/persistence.
        members=[
            "rsi", "willr", "stochk", "cci", "mfi", "bb_pctb", "zscore",
            "keltner_pos", "donch_pos", "vwap_dist", "dist_sma50", "dist_sma200",
            "ich_kijun", "aroonosc", "macd_hist", "roc3", "roc10",
            # trend-direction signals structurally live here too (no-edge):
            "di_spread", "psar_dist", "sma_cross", "ema_slope",
        ],
        status=VALIDATED,
        edge_summary="+0.142R/trade · t6.2 · 9/11 yrs · post-cost",
        ranking_dimension="oversold_age",   # depth/persistence, NOT oscillator level
        strategy="deep_oversold",
        note=("Dominant factor (~50% variance). Its RAW level / momentum / "
              "trend-direction reading is anti-predictive — that is the no-edge "
              "core. The only validated edge is the DEEP, PERSISTENT dislocation "
              "transform (RSI<30 sustained ≥3 bars, liquid). Ranked by oversold "
              "depth, never by oscillator level."),
    ),
    FactorGroup(
        key="volatility",
        label="Volatility",
        members=["atr_pct", "bb_width", "adx"],
        status=AVOID,
        edge_summary="ADX dead/anti (0/11 yrs); level untested",
        ranking_dimension=None,
        strategy=None,
        note=("ADX clusters here, not with direction. As a long entry ADX is "
              "anti-predictive (gradient falls with trend persistence). Raw "
              "volatility level not yet screened for an edge-bearing transform."),
    ),
    FactorGroup(
        key="volume_flow",
        label="Volume / flow",
        members=["rvol", "obv_slope", "force_idx", "ad_slope"],
        status=UNTESTED,
        edge_summary="not yet screened",
        ranking_dimension=None,
        strategy=None,
        note=("rvol is structurally its own factor; obv/force/ad are domain-volume "
              "but co-move with price. No within-factor edge transform validated yet."),
    ),
    FactorGroup(
        key="gap_event",
        label="Gap / event",
        members=["gap"],
        status=AVOID,
        edge_summary="gap_up failed under bracket exec (−0.04R)",
        ranking_dimension=None,
        strategy=None,
        note=("gap_up looked good close-to-close but reverts into the stop under "
              "bracket execution. Shown as context, not a buy."),
    ),
    FactorGroup(
        key="candlestick",
        label="Candlestick",
        members=["engulf", "hammer"],
        status=UNTESTED,
        edge_summary="not yet screened",
        ranking_dimension=None,
        strategy=None,
        note="Bar-geometry events; no edge-bearing transform validated yet.",
    ),
]

_BY_KEY = {g.key: g for g in FACTOR_GROUPS}
_BY_STRATEGY = {g.strategy: g for g in FACTOR_GROUPS if g.strategy}


def get_factor_groups() -> List[FactorGroup]:
    """All locked factor groups, in display order."""
    return list(FACTOR_GROUPS)


def group_for_strategy(strategy_name: str) -> Optional[FactorGroup]:
    """The factor group a registered strategy populates, or None."""
    return _BY_STRATEGY.get(strategy_name)


def get_group(key: str) -> Optional[FactorGroup]:
    return _BY_KEY.get(key)
