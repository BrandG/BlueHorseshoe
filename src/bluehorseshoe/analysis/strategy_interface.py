"""
Pluggable Strategy Interface for BlueHorseshoe.

Defines the TradingStrategy ABC and concrete implementations (BaselineStrategy,
MeanReversionStrategy). Each strategy encapsulates its identity, configuration,
dict-key names, and core scoring logic so that new strategies can be added
without touching downstream consumers.

Both concrete classes are stateless and picklable — they receive ``trader``
as a parameter to ``process()`` instead of storing it, which is critical for
ProcessPoolExecutor.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from bluehorseshoe.analysis.constants import (
    MIN_STOCK_PRICE,
    MAX_STOCK_PRICE,
    MIN_RR_RATIO_BASELINE,
    MIN_RR_RATIO_MEAN_REVERSION,
    REGIME_PROFILES,
    REQUIRE_WEEKLY_UPTREND,
    DEEP_OVERSOLD_Z_DISTRESS,
)
from bluehorseshoe.core.config import get_settings, weights_config


# ---------------------------------------------------------------------------
# Shared regime gate (contrarian sleeves)
# ---------------------------------------------------------------------------

def spy_is_nonbull(benchmark_df) -> Optional[bool]:
    """SPY-EMA regime gate matching the research harness, shared by the contrarian sleeves.

    nonbull = NOT(SPY close > EMA200 AND EMA50 > EMA200). Returns True (nonbull),
    False (bull), or None when it cannot be determined (missing/short SPY history) —
    callers fail closed on None.
    """
    import numpy as np
    import talib
    if benchmark_df is None or len(benchmark_df) < 200:
        return None
    close = benchmark_df['close'].to_numpy(dtype=float)
    ema50 = talib.EMA(close, 50)
    ema200 = talib.EMA(close, 200)
    if np.isnan(ema200[-1]) or np.isnan(ema50[-1]):
        return None
    bull = (close[-1] > ema200[-1]) and (ema50[-1] > ema200[-1])
    return not bull


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class StrategyResult:
    """Value object returned by ``TradingStrategy.process()``."""

    score: float
    components: Dict[str, float]
    setup: Dict[str, float]       # entry_price, stop_loss, take_profit, rr_ratio, …
    ml_prob: float
    stop_multiplier: float
    target_multiplier: float
    regime_status: str = "Neutral"


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class TradingStrategy(ABC):
    """
    Interface every trading strategy must implement.

    Subclasses are stateless value objects — safe to pickle and share across
    ``ProcessPoolExecutor`` workers.
    """

    # --- Identity -----------------------------------------------------------
    @property
    @abstractmethod
    def name(self) -> str:
        """Internal name used in MongoDB docs, ML model paths, etc."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable label for reports (e.g. 'Baseline', 'MeanRev')."""

    # --- Dict key names (backward compat) -----------------------------------
    @property
    @abstractmethod
    def score_key(self) -> str:
        """Key for the score in the result dict (e.g. 'baseline_score')."""

    @property
    @abstractmethod
    def setup_key(self) -> str:
        """Key for the setup dict (e.g. 'baseline_setup')."""

    @property
    @abstractmethod
    def ml_prob_key(self) -> str:
        """Key for ML win probability (e.g. 'baseline_ml_prob')."""

    @property
    @abstractmethod
    def components_key(self) -> str:
        """Key for score components (e.g. 'baseline_components')."""

    # --- Config -------------------------------------------------------------
    @property
    @abstractmethod
    def weight_prefix(self) -> str:
        """Prefix for weight categories ('' for baseline, 'mr_' for MR)."""

    @property
    @abstractmethod
    def default_stop_multiplier(self) -> float:
        """Default ATR multiplier for stop loss."""

    @property
    @abstractmethod
    def default_target_multiplier(self) -> float:
        """Default ATR multiplier for take profit."""

    @property
    @abstractmethod
    def min_rr_ratio(self) -> float:
        """Minimum risk/reward ratio to qualify."""

    # --- Regime-aware multipliers -------------------------------------------

    def get_regime_stop_multiplier(self, regime_status: Optional[str] = None) -> float:
        """Return ATR stop multiplier adjusted for market regime."""
        profile = REGIME_PROFILES.get(regime_status or "Neutral")
        if profile:
            return profile.get(f"stop_multiplier_{self.name}", self.default_stop_multiplier)
        return self.default_stop_multiplier

    def get_regime_target_multiplier(self, regime_status: Optional[str] = None) -> float:
        """Return ATR target multiplier adjusted for market regime."""
        profile = REGIME_PROFILES.get(regime_status or "Neutral")
        if profile:
            return profile.get(f"target_multiplier_{self.name}", self.default_target_multiplier)
        return self.default_target_multiplier

    def get_hold_days(self, regime_status: Optional[str] = None) -> int:
        """Hold horizon (bars) the hypothesis evaluator uses before time-exit.

        Defaults to the market-regime profile so Baseline/MeanReversion behave
        exactly as before. Strategies with a fixed validated horizon override this.
        """
        profile = REGIME_PROFILES.get(
            regime_status or "Neutral", REGIME_PROFILES.get("Neutral", {})
        )
        return profile.get("hold_days", 5)

    @property
    def entry_style(self) -> str:
        """Entry-fill model the hypothesis evaluator should apply.

        'limit_below'          — resting limit at/under entry, scanned from the
                                 signal bar (Baseline, MeanReversion; unchanged).
        'marketable_next_open' — marketable DAY limit above prior close, valid
                                 for the next session only (DeepOversold).
        """
        return "limit_below"

    @property
    def paper_tradeable(self) -> bool:
        """Whether PaperTrader may submit live bracket orders for this strategy.

        Default True. A 'tracking-only' sleeve sets this False: it still flows
        through scores → journal freeze → hypothesis evaluation (forward-R in
        journal_hypothetical_trades), but PaperTrader filters it out so it never
        competes for live broker slots. Use for lower-conviction signals being
        measured out-of-sample before any live deployment.
        """
        return True

    @property
    def edge_weight(self) -> float:
        """Validated per-trade edge in R units, used for cross-sleeve slot ranking.

        PaperTrader ranks candidates by ``score * edge_weight`` ("expected-R
        priority") so a higher-edge sleeve wins a slot even when a weaker sleeve
        produced a higher raw score (raw score only ranks WITHIN a sleeve, by its
        own axis — e.g. oversold depth). Default 0.0: an unvalidated sleeve has no
        claim on a slot and fills only leftover capacity after validated sleeves.
        A sleeve earns a positive weight only from a cost/liquidity-survived
        backtest. Re-measure (don't guess) when the firing rule changes.
        """
        return 0.0

    # --- Core methods -------------------------------------------------------

    @abstractmethod
    def process(self, trader: Any, df: pd.DataFrame, symbol: str,
                yesterday: dict, ctx: Any) -> Optional[StrategyResult]:
        """
        Score a single symbol using this strategy (main-process variant).

        Args:
            trader: ``SwingTrader`` instance (has ML models, DB connections).
            df: OHLCV DataFrame for the symbol.
            symbol: Ticker string.
            yesterday: Dict of the last row of ``df``.
            ctx: ``StrategyContext`` with benchmark data, market health, etc.

        Returns:
            ``StrategyResult`` or ``None`` if the symbol does not qualify.
        """

    @abstractmethod
    def process_worker(self, trader: Any, df: pd.DataFrame, symbol: str,
                       yesterday: dict, worker_state: dict,
                       overview: dict, sentiment: float) -> Optional[StrategyResult]:
        """
        Score a single symbol using this strategy (worker-process variant).

        Identical logic to ``process()`` but uses pre-loaded ML models from
        ``worker_state`` instead of DB-connected inference objects.
        """


# ---------------------------------------------------------------------------
# Baseline (Trend-Following)
# ---------------------------------------------------------------------------

class BaselineStrategy(TradingStrategy):
    """Trend-following strategy: rewards strength, momentum, and breakouts."""

    @property
    def name(self) -> str:
        return "baseline"

    @property
    def display_name(self) -> str:
        return "Baseline"

    @property
    def score_key(self) -> str:
        return "baseline_score"

    @property
    def setup_key(self) -> str:
        return "baseline_setup"

    @property
    def ml_prob_key(self) -> str:
        return "baseline_ml_prob"

    @property
    def components_key(self) -> str:
        return "baseline_components"

    @property
    def weight_prefix(self) -> str:
        return ""

    @property
    def default_stop_multiplier(self) -> float:
        return 2.0

    @property
    def default_target_multiplier(self) -> float:
        return 3.0

    @property
    def min_rr_ratio(self) -> float:
        return MIN_RR_RATIO_BASELINE

    @property
    def paper_tradeable(self) -> bool:
        # Tracking-only (2026-06-07). The trend/breakout scorer has no validated
        # entry edge: it anti-selects (top-10 picks worst) and its positive R is
        # beta + bracket geometry, not signal. It still flows through scores →
        # journal → hypothesis-engine forward-R, but must not compete with the
        # gauntlet-validated DeepOS / DeepOS+HA sleeves for live broker slots.
        return False

    # -- Main-process scoring ------------------------------------------------

    def process(self, trader, df, symbol, yesterday, ctx):
        """Direct extraction of ``SwingTrader._process_baseline()``."""
        # Regime / weekly uptrend check
        regime_status = (ctx.market_health or {}).get('status')
        should_enforce_weekly = REQUIRE_WEEKLY_UPTREND
        if regime_status == 'Bullish':
            should_enforce_weekly = False

        if should_enforce_weekly and not trader.is_weekly_uptrend(df):
            return None

        # Step 1: Calculate score
        score_components = trader.technical_analyzer.calculate_baseline_score(
            df,
            enabled_indicators=ctx.enabled_indicators,
            aggregation=ctx.aggregation,
        )
        technical_score = score_components.get("total", 0.0)

        # Step 2: Setup (stop / target / entry) — regime-adjusted multipliers
        ml_stop_multiplier = self.get_regime_stop_multiplier(regime_status)
        ml_target_multiplier = trader.profit_target_inference.predict_profit_target_multiplier(
            symbol, score_components,
            target_date=str(yesterday['date'])[:10],
            strategy=self.name,
        )
        setup = trader.calculate_baseline_setup(
            df,
            ml_stop_multiplier=ml_stop_multiplier,
            ml_target_multiplier=ml_target_multiplier,
            technical_score=technical_score,
        )

        if not setup['is_realistic']:
            return None
        entry_price = setup['entry_price']
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None
        if setup['rr_ratio'] < self.min_rr_ratio:
            return None

        # Relative Strength bonus
        rs_multiplier = weights_config.get_weights('momentum').get('RS_MULTIPLIER', 1.0)
        if ctx.benchmark_df is not None and rs_multiplier != 0.0:
            rs_ratio = trader.calculate_relative_strength(df, ctx.benchmark_df)
            if rs_ratio > 1.10:
                rs_bonus = 5.0
            elif rs_ratio > 1.0:
                rs_bonus = 2.0
            else:
                rs_bonus = -2.0
            rs_bonus *= rs_multiplier
            score_components["rs_index"] = rs_bonus
            score_components["total"] += rs_bonus

        # Score Acceleration bonus
        accel_multiplier = weights_config.get_weights('trend').get('SCORE_ACCEL_MULTIPLIER', 0.0)
        if accel_multiplier != 0.0 and hasattr(ctx, 'score_history'):
            from bluehorseshoe.analysis.strategy import SwingTrader  # avoid circular at module level
            history = ctx.score_history.get(symbol, [])
            accel_bonus = SwingTrader._calculate_score_acceleration(history) * accel_multiplier
            score_components["score_acceleration"] = accel_bonus
            score_components["total"] += accel_bonus

        # Intraday Context bonus (daily-bar proxy)
        from bluehorseshoe.analysis.intraday_context import compute_daily_context
        from bluehorseshoe.analysis.constants import INTRADAY_CONTEXT_WEIGHT
        ctx_result = compute_daily_context(df)
        ctx_bonus = ctx_result["context_score"] * INTRADAY_CONTEXT_WEIGHT
        score_components["intraday_context"] = ctx_bonus
        score_components["intraday_resistance"] = ctx_result["resistance"]
        score_components["total"] += ctx_bonus

        # ML Win Probability
        ml_prob = trader.ml_inference.predict_probability(
            symbol, score_components,
            target_date=str(yesterday['date'])[:10],
            strategy=self.name,
        )

        return StrategyResult(
            score=score_components.pop("total", 0.0),
            components=score_components,
            setup=setup,
            ml_prob=ml_prob,
            stop_multiplier=ml_stop_multiplier,
            target_multiplier=ml_target_multiplier,
            regime_status=regime_status or "Neutral",
        )

    # -- Worker-process scoring ----------------------------------------------

    def process_worker(self, trader, df, symbol, yesterday, worker_state,
                       overview, sentiment):
        """Direct extraction of ``_worker_process_baseline()``."""
        from bluehorseshoe.analysis.strategy import SwingTrader  # avoid circular

        benchmark_df = worker_state['benchmark_df']
        market_health = worker_state['market_health']
        enabled_indicators = worker_state['enabled_indicators']
        aggregation = worker_state['aggregation']

        # Weekly uptrend check
        regime_status = (market_health or {}).get('status')
        should_enforce_weekly = REQUIRE_WEEKLY_UPTREND
        if regime_status == 'Bullish':
            should_enforce_weekly = False
        if should_enforce_weekly and not trader.is_weekly_uptrend(df):
            return None

        # Step 1: Calculate technical score
        score_components = trader.technical_analyzer.calculate_baseline_score(
            df, enabled_indicators=enabled_indicators, aggregation=aggregation,
            motif_scores=worker_state.get('motif_scores'),
        )
        technical_score = score_components.get("total", 0.0)

        # Step 2: Setup — regime-adjusted multipliers
        ml_stop_multiplier = self.get_regime_stop_multiplier(regime_status)
        from bluehorseshoe.analysis.strategy import _worker_ml_predict_profit_target
        ml_target_multiplier = _worker_ml_predict_profit_target(
            score_components, overview, sentiment, strategy=self.name,
        )
        setup = trader.calculate_baseline_setup(
            df,
            ml_stop_multiplier=ml_stop_multiplier,
            ml_target_multiplier=ml_target_multiplier,
            technical_score=technical_score,
        )

        if not setup['is_realistic']:
            return None
        entry_price = setup['entry_price']
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None
        if setup['rr_ratio'] < self.min_rr_ratio:
            return None

        # Relative Strength bonus
        rs_multiplier = weights_config.get_weights('momentum').get('RS_MULTIPLIER', 1.0)
        if benchmark_df is not None and rs_multiplier != 0.0:
            rs_ratio = trader.calculate_relative_strength(df, benchmark_df)
            if rs_ratio > 1.10:
                rs_bonus = 5.0
            elif rs_ratio > 1.0:
                rs_bonus = 2.0
            else:
                rs_bonus = -2.0
            rs_bonus *= rs_multiplier
            score_components["rs_index"] = rs_bonus
            score_components["total"] += rs_bonus

        # Score Acceleration bonus
        accel_multiplier = weights_config.get_weights('trend').get('SCORE_ACCEL_MULTIPLIER', 0.0)
        if accel_multiplier != 0.0:
            score_history = worker_state.get('score_history', {})
            history = score_history.get(symbol, [])
            accel_bonus = SwingTrader._calculate_score_acceleration(history) * accel_multiplier
            score_components["score_acceleration"] = accel_bonus
            score_components["total"] += accel_bonus

        # Intraday Context bonus (daily-bar proxy)
        from bluehorseshoe.analysis.intraday_context import compute_daily_context
        from bluehorseshoe.analysis.constants import INTRADAY_CONTEXT_WEIGHT
        ctx_result = compute_daily_context(df)
        ctx_bonus = ctx_result["context_score"] * INTRADAY_CONTEXT_WEIGHT
        score_components["intraday_context"] = ctx_bonus
        score_components["intraday_resistance"] = ctx_result["resistance"]
        score_components["total"] += ctx_bonus

        # ML Win Probability (worker variant — no DB)
        from bluehorseshoe.analysis.strategy import _worker_ml_predict_probability
        ml_prob = _worker_ml_predict_probability(
            score_components, overview, sentiment, strategy=self.name,
        )

        return StrategyResult(
            score=score_components.pop("total", 0.0),
            components=score_components,
            setup=setup,
            ml_prob=ml_prob,
            stop_multiplier=ml_stop_multiplier,
            target_multiplier=ml_target_multiplier,
            regime_status=regime_status or "Neutral",
        )


# ---------------------------------------------------------------------------
# Mean Reversion (Dip-Buying)
# ---------------------------------------------------------------------------

class MeanReversionStrategy(TradingStrategy):
    """Mean-reversion strategy: rewards oversold conditions and reversal signals."""

    @property
    def name(self) -> str:
        return "mean_reversion"

    @property
    def display_name(self) -> str:
        return "MeanRev"

    @property
    def score_key(self) -> str:
        return "mr_score"

    @property
    def setup_key(self) -> str:
        return "mr_setup"

    @property
    def ml_prob_key(self) -> str:
        return "mr_ml_prob"

    @property
    def components_key(self) -> str:
        return "mr_components"

    @property
    def weight_prefix(self) -> str:
        return "mr_"

    @property
    def default_stop_multiplier(self) -> float:
        return 1.5

    @property
    def default_target_multiplier(self) -> float:
        return 2.0

    @property
    def min_rr_ratio(self) -> float:
        return MIN_RR_RATIO_MEAN_REVERSION

    @property
    def paper_tradeable(self) -> bool:
        # Tracking-only (2026-06-07). The MR scorer never cleared the honest
        # gauntlet; its validated descendant is DeepOversold (mechanical, ML-free,
        # +0.142R/trade after costs). Keep MR's forward-R in the hypothesis engine
        # but stop it from competing for live broker slots.
        return False

    # -- Main-process scoring ------------------------------------------------

    def process(self, trader, df, symbol, yesterday, ctx):
        """Direct extraction of ``SwingTrader._process_mr()``."""
        regime_status = (ctx.market_health or {}).get('status')

        score_components = trader.technical_analyzer.calculate_technical_score(
            df,
            strategy=self.name,
            enabled_indicators=ctx.enabled_indicators,
            aggregation=ctx.aggregation,
        )

        # Intraday Context bonus (daily-bar proxy)
        from bluehorseshoe.analysis.intraday_context import compute_daily_context
        from bluehorseshoe.analysis.constants import INTRADAY_CONTEXT_WEIGHT_MR
        ctx_result = compute_daily_context(df)
        ctx_bonus = ctx_result["context_score"] * INTRADAY_CONTEXT_WEIGHT_MR
        score_components["intraday_context"] = ctx_bonus
        score_components["intraday_resistance"] = ctx_result["resistance"]
        score_components["total"] += ctx_bonus

        ml_stop_multiplier = trader.stop_loss_inference.predict_stop_loss_multiplier(
            symbol, score_components,
            target_date=str(yesterday['date'])[:10],
        )

        ml_target_multiplier = trader.profit_target_inference.predict_profit_target_multiplier(
            symbol, score_components,
            target_date=str(yesterday['date'])[:10],
            strategy=self.name,
        )

        setup = trader.calculate_mean_reversion_setup(
            df,
            ml_stop_multiplier=ml_stop_multiplier,
            ml_target_multiplier=ml_target_multiplier,
        )
        if not setup['is_realistic']:
            return None
        entry_price = setup['entry_price']
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None
        if setup['rr_ratio'] < self.min_rr_ratio:
            return None

        ml_prob = trader.ml_inference.predict_probability(
            symbol, score_components,
            target_date=str(yesterday['date'])[:10],
            strategy=self.name,
        )

        return StrategyResult(
            score=score_components.pop("total", 0.0),
            components=score_components,
            setup=setup,
            ml_prob=ml_prob,
            stop_multiplier=ml_stop_multiplier,
            target_multiplier=ml_target_multiplier,
            regime_status=regime_status or "Neutral",
        )

    # -- Worker-process scoring ----------------------------------------------

    def process_worker(self, trader, df, symbol, yesterday, worker_state,
                       overview, sentiment):
        """Direct extraction of ``_worker_process_mr()``."""
        market_health = worker_state.get('market_health')
        regime_status = (market_health or {}).get('status')
        enabled_indicators = worker_state['enabled_indicators']
        aggregation = worker_state['aggregation']

        score_components = trader.technical_analyzer.calculate_technical_score(
            df, strategy=self.name,
            enabled_indicators=enabled_indicators, aggregation=aggregation,
            motif_scores=worker_state.get('motif_scores'),
        )

        # Intraday Context bonus (daily-bar proxy)
        from bluehorseshoe.analysis.intraday_context import compute_daily_context
        from bluehorseshoe.analysis.constants import INTRADAY_CONTEXT_WEIGHT_MR
        ctx_result = compute_daily_context(df)
        ctx_bonus = ctx_result["context_score"] * INTRADAY_CONTEXT_WEIGHT_MR
        score_components["intraday_context"] = ctx_bonus
        score_components["intraday_resistance"] = ctx_result["resistance"]
        score_components["total"] += ctx_bonus

        from bluehorseshoe.analysis.strategy import (
            _worker_ml_predict_stop_loss,
            _worker_ml_predict_profit_target,
            _worker_ml_predict_probability,
        )

        ml_stop_multiplier = _worker_ml_predict_stop_loss(
            score_components, overview, sentiment,
        )
        ml_target_multiplier = _worker_ml_predict_profit_target(
            score_components, overview, sentiment, strategy=self.name,
        )

        setup = trader.calculate_mean_reversion_setup(
            df,
            ml_stop_multiplier=ml_stop_multiplier,
            ml_target_multiplier=ml_target_multiplier,
        )
        if not setup['is_realistic']:
            return None
        entry_price = setup['entry_price']
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None
        if setup['rr_ratio'] < self.min_rr_ratio:
            return None

        ml_prob = _worker_ml_predict_probability(
            score_components, overview, sentiment, strategy=self.name,
        )

        return StrategyResult(
            score=score_components.pop("total", 0.0),
            components=score_components,
            setup=setup,
            ml_prob=ml_prob,
            stop_multiplier=ml_stop_multiplier,
            target_multiplier=ml_target_multiplier,
            regime_status=regime_status or "Neutral",
        )


# ---------------------------------------------------------------------------
# Deep Oversold (Persistent Dip) — validated entry edge, 2026-06-04
# ---------------------------------------------------------------------------

class DeepOversoldStrategy(TradingStrategy):
    """Buy persistent oversold dislocation in liquid names.

    The one entry signal to survive the honest gauntlet. Mechanical and ML-free
    on purpose: the validated +0.142R/trade backtest used a fixed 2:1 ATR bracket
    and *none* of the MR scorer's ML / intraday / motif machinery, so this strategy
    reproduces exactly that rule and nothing else.

    Fires when, on the signal bar:
      * RSI(14) has been below ``DEEP_OVERSOLD_RSI_THRESHOLD`` for at least
        ``DEEP_OVERSOLD_MIN_AGE`` *consecutive* bars (the edge is in persistence —
        forward return rises monotonically with oversold age), AND
      * 20-day average dollar-volume >= ``DEEP_OVERSOLD_MIN_DOLLAR_VOLUME`` (the
        edge is strongest in liquid names, absent in the thin <$1M tail), AND
      * price in [MIN_STOCK_PRICE, MAX_STOCK_PRICE] and the 1*ATR stop is within
        MAX_RISK_PERCENT (``is_realistic``).

    Score is ``BASE + (age - MIN_AGE) * STEP`` — slot-competitive with strong
    Baseline/MR scores and monotone in oversold depth, the validated ranking axis.
    """

    @property
    def name(self) -> str:
        return "deep_oversold"

    @property
    def display_name(self) -> str:
        return "DeepOS"

    @property
    def score_key(self) -> str:
        return "deep_os_score"

    @property
    def setup_key(self) -> str:
        return "deep_os_setup"

    @property
    def ml_prob_key(self) -> str:
        return "deep_os_ml_prob"

    @property
    def components_key(self) -> str:
        return "deep_os_components"

    @property
    def weight_prefix(self) -> str:
        return "deep_os_"

    @property
    def edge_weight(self) -> float:
        from bluehorseshoe.analysis.constants import DEEP_OVERSOLD_EDGE_R
        return DEEP_OVERSOLD_EDGE_R

    @property
    def default_stop_multiplier(self) -> float:
        from bluehorseshoe.analysis.constants import DEEP_OVERSOLD_STOP_MULT
        return DEEP_OVERSOLD_STOP_MULT

    @property
    def default_target_multiplier(self) -> float:
        from bluehorseshoe.analysis.constants import DEEP_OVERSOLD_TARGET_MULT
        return DEEP_OVERSOLD_TARGET_MULT

    @property
    def min_rr_ratio(self) -> float:
        from bluehorseshoe.analysis.constants import DEEP_OVERSOLD_MIN_RR
        return DEEP_OVERSOLD_MIN_RR

    def get_hold_days(self, regime_status=None) -> int:
        from bluehorseshoe.analysis.constants import DEEP_OVERSOLD_HOLD_DAYS
        return DEEP_OVERSOLD_HOLD_DAYS

    @property
    def entry_style(self) -> str:
        return "marketable_next_open"

    # -- Shared evaluation (no ML / overview / sentiment needed) -------------

    @staticmethod
    def _oversold_age(rsi, threshold: float) -> int:
        """Consecutive bars (ending at the last bar) with RSI below threshold."""
        age = 0
        for value in reversed(rsi):
            if value == value and value < threshold:  # value==value rejects NaN
                age += 1
            else:
                break
        return age

    def _bracket_result(self, df, regime_status, score, components):
        """Build the validated 2:1 ATR / entry-premium bracket + StrategyResult.

        Shared by the deep-oversold sleeves (oversold, +HA, and adx-down): all use the
        identical execution geometry — $-vol floor, entry = prior close * (1 + premium)
        as a DAY limit, stop/target anchored to entry for 2:1, hold-10, marketable
        next-open, ML-free prior — and differ ONLY in their firing gate and ``score``
        / ``components`` (computed by the caller). Returns ``None`` if the liquidity,
        price, ATR, realism, or R:R gate fails.
        """
        import numpy as np
        import talib
        from bluehorseshoe.analysis.constants import (
            DEEP_OVERSOLD_MIN_DOLLAR_VOLUME, DEEP_OVERSOLD_STOP_MULT,
            DEEP_OVERSOLD_TARGET_MULT, DEEP_OVERSOLD_PRIOR_WINRATE,
            DEEP_OVERSOLD_ENTRY_PREMIUM, MAX_RISK_PERCENT,
        )
        from bluehorseshoe.analysis.liquidity import trailing_dollar_volume
        close = df['close'].to_numpy(dtype=float)

        # 20-day average dollar volume (incl. signal bar) — liquidity floor is part of the edge.
        # Shared helper so the deep-oversold edge floor and the general report floor
        # (MIN_DOLLAR_VOLUME) measure liquidity identically.
        dollar_vol_20 = trailing_dollar_volume(close, df['volume'].to_numpy(dtype=float))
        if dollar_vol_20 < DEEP_OVERSOLD_MIN_DOLLAR_VOLUME:
            return None

        # Build the bracket directly: entry = prior close * (1 + premium), submitted as
        # a DAY limit; stop/target anchor to THAT entry so a fill at-or-below it keeps
        # the 2:1. ATR via talib(14) to match the research harness exactly.
        high = df['high'].to_numpy(dtype=float)
        low = df['low'].to_numpy(dtype=float)
        atr = talib.ATR(high, low, close, 14)[-1]
        if not atr > 0 or np.isnan(atr):
            return None
        last_close = float(close[-1])
        entry_price = last_close * (1 + DEEP_OVERSOLD_ENTRY_PREMIUM)
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None
        stop_loss = entry_price - DEEP_OVERSOLD_STOP_MULT * atr
        take_profit = entry_price + DEEP_OVERSOLD_TARGET_MULT * atr * 0.98  # 2% delta haircut
        risk = entry_price - stop_loss
        rr_ratio = (take_profit - entry_price) / risk if risk > 0 else 0.0
        risk_pct = risk / entry_price if entry_price > 0 else 1.0
        if risk_pct > MAX_RISK_PERCENT:        # 1*ATR stop too wide for this name
            return None
        if rr_ratio < self.min_rr_ratio:
            return None
        setup = {
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "rr_ratio": float(rr_ratio),
            "actual_close": last_close,
            "is_realistic": True,
        }
        components = {**components, "dollar_vol_M": round(dollar_vol_20 / 1e6, 1)}
        return StrategyResult(
            score=float(score),
            components=components,
            setup=setup,
            ml_prob=DEEP_OVERSOLD_PRIOR_WINRATE,
            stop_multiplier=DEEP_OVERSOLD_STOP_MULT,
            target_multiplier=DEEP_OVERSOLD_TARGET_MULT,
            regime_status=regime_status or "Neutral",
        )

    def _evaluate(self, trader, df, regime_status):
        import talib
        from bluehorseshoe.analysis.constants import (
            DEEP_OVERSOLD_RSI_THRESHOLD, DEEP_OVERSOLD_MIN_AGE,
            DEEP_OVERSOLD_BASE_SCORE, DEEP_OVERSOLD_AGE_STEP,
        )
        if df is None or len(df) < 40:
            return None
        close = df['close'].to_numpy(dtype=float)
        rsi = talib.RSI(close, 14)
        age = self._oversold_age(rsi, DEEP_OVERSOLD_RSI_THRESHOLD)
        if age < DEEP_OVERSOLD_MIN_AGE:
            return None
        score = DEEP_OVERSOLD_BASE_SCORE + (age - DEEP_OVERSOLD_MIN_AGE) * DEEP_OVERSOLD_AGE_STEP
        components = {"oversold_age": float(age), "rsi": float(rsi[-1])}
        return self._bracket_result(df, regime_status, score, components)

    def _solvency_ok(self, symbol: str, solvency: Optional[Dict[str, float]]) -> bool:
        """Keep unknown-Z names; drop only known distressed Altman-Z'' names."""
        z_score = (solvency or {}).get(symbol)
        return z_score is None or float(z_score) >= DEEP_OVERSOLD_Z_DISTRESS

    def process(self, trader, df, symbol, yesterday, ctx):
        config = getattr(trader, "config", None) or get_settings()
        if config.deep_oversold_nonbull_gate:
            if spy_is_nonbull(getattr(ctx, 'benchmark_df', None)) is not True:
                return None
        if config.deep_oversold_solvency_filter:
            if not self._solvency_ok(symbol, getattr(ctx, 'solvency', None)):
                return None
        regime_status = (ctx.market_health or {}).get('status')
        return self._evaluate(trader, df, regime_status)

    def process_worker(self, trader, df, symbol, yesterday, worker_state,
                       overview, sentiment):
        config = getattr(trader, "config", None) or get_settings()
        if config.deep_oversold_nonbull_gate:
            if spy_is_nonbull(worker_state.get('benchmark_df')) is not True:
                return None
        if config.deep_oversold_solvency_filter:
            if not self._solvency_ok(symbol, worker_state.get('solvency')):
                return None
        regime_status = (worker_state.get('market_health') or {}).get('status')
        return self._evaluate(trader, df, regime_status)


# ---------------------------------------------------------------------------
# Deep Oversold × Heiken-Ashi green (high-conviction contrarian tier) — locked 2026-06-06
# ---------------------------------------------------------------------------

class DeepOversoldHAStrategy(DeepOversoldStrategy):
    """DeepOversold + a Heiken-Ashi green confirmation, gated to nonbull regime.

    The high-conviction tier of the contrarian sleeve. Spec frozen in
    ``research/indicator_screen/HA_DEEP_OVERSOLD_LOCKED_v1.md``. Identical to
    :class:`DeepOversoldStrategy` in every mechanic — same RSI-age / $-vol floor /
    2:1 ATR bracket / hold-10 / marketable-next-open / scoring / ML-free prior —
    PLUS two research-validated gates layered on the *front*:

      * **Regime (mandatory):** SPY is nonbull, i.e. NOT(close > EMA200 AND
        EMA50 > EMA200) on SPY daily closes — the exact gate the gauntlet used.
        All-regime the HA overlay is a NET-NEGATIVE filter (−0.057R vs bare deep),
        so the gate is not optional; we fail closed if SPY history is unavailable.
      * **Heiken-Ashi green:** the current *true recursive* HA candle is bullish
        (``HA_close > HA_open``). NOTE: this deliberately does NOT use the
        production ``TechnicalAnalyzer.calculate_heiken_ashi`` (non-recursive open
        approximation) — the recursive open is what the research validated.

    Gauntlet (nonbull, realistic frictions): deep+HA-green +0.404R/trade vs bare
    deep +0.244R. Low-frequency, high-conviction (~68 nonbull trades/yr universe-wide).
    Shares DeepOversold's ``DEEP_OVERSOLD_MIN_AGE`` so it reads as a clean
    "DeepOS + 2 gates" overlay (a 1-bar difference from the research age convention,
    immaterial to the monotone-in-depth edge). Tracked by the hypothesis engine and
    eligible for live paper orders via the legacy slot pool.
    """

    _HA_WINDOW = 150  # recursive HA_open converges far faster; 150 bars is exact to float precision

    @property
    def name(self) -> str:
        return "deep_oversold_ha"

    @property
    def display_name(self) -> str:
        return "DeepOS+HA"

    @property
    def score_key(self) -> str:
        return "deep_os_ha_score"

    @property
    def setup_key(self) -> str:
        return "deep_os_ha_setup"

    @property
    def ml_prob_key(self) -> str:
        return "deep_os_ha_ml_prob"

    @property
    def components_key(self) -> str:
        return "deep_os_ha_components"

    @property
    def weight_prefix(self) -> str:
        return "deep_os_ha_"

    @property
    def edge_weight(self) -> float:
        # The high-conviction tier (~2.8x bare DeepOS); MUST override or it would
        # inherit DeepOversold's weight and tie with it under cross-sleeve ranking.
        from bluehorseshoe.analysis.constants import DEEP_OVERSOLD_HA_EDGE_R
        return DEEP_OVERSOLD_HA_EDGE_R

    # -- Gates ---------------------------------------------------------------

    @staticmethod
    def spy_is_nonbull(benchmark_df) -> Optional[bool]:
        """SPY-EMA regime gate (delegates to the shared module-level helper)."""
        return spy_is_nonbull(benchmark_df)

    @classmethod
    def heiken_ashi_last_is_green(cls, df) -> bool:
        """True-recursive Heiken-Ashi: is the latest candle bullish (HA_close>HA_open)?"""
        import numpy as np
        if df is None or len(df) < 2:
            return False
        tail = df.iloc[-cls._HA_WINDOW:] if len(df) > cls._HA_WINDOW else df
        o = tail['open'].to_numpy(dtype=float)
        h = tail['high'].to_numpy(dtype=float)
        low = tail['low'].to_numpy(dtype=float)
        c = tail['close'].to_numpy(dtype=float)
        ha_close = (o + h + low + c) / 4.0
        ha_open = np.empty(len(c))
        ha_open[0] = (o[0] + c[0]) / 2.0
        for t in range(1, len(c)):
            ha_open[t] = (ha_open[t - 1] + ha_close[t - 1]) / 2.0
        return bool(ha_close[-1] > ha_open[-1])

    def _gates_pass(self, df, benchmark_df) -> bool:
        # nonbull is mandatory; None (undeterminable) and False (bull) both fail closed
        if self.spy_is_nonbull(benchmark_df) is not True:
            return False
        return self.heiken_ashi_last_is_green(df)

    def _solvency_ok(self, symbol: str, solvency: Optional[Dict[str, float]]) -> bool:
        """HA is intentionally not filtered; its own gates subsume solvency."""
        return True

    # -- Scoring (delegate to DeepOversold once the gates pass) ----------------

    def process(self, trader, df, symbol, yesterday, ctx):
        if not self._gates_pass(df, getattr(ctx, 'benchmark_df', None)):
            return None
        regime_status = (ctx.market_health or {}).get('status')
        return self._evaluate(trader, df, regime_status)

    def process_worker(self, trader, df, symbol, yesterday, worker_state,
                       overview, sentiment):
        if not self._gates_pass(df, worker_state.get('benchmark_df')):
            return None
        regime_status = (worker_state.get('market_health') or {}).get('status')
        return self._evaluate(trader, df, regime_status)


# ---------------------------------------------------------------------------
# Deep Downtrend (adx_diDown contrarian) — TRACKING-ONLY sleeve, 2026-06-07
# ---------------------------------------------------------------------------

class DeepDownAdxStrategy(DeepOversoldStrategy):
    """Buy a strong, *deep* established downtrend in nonbull regimes (textbook ADX inverted).

    The one PSAR/ADX signal to survive the clean re-audit + incremental + cost gauntlet
    (research/indicator_screen/adx_didown_*.out). A strong directional downtrend
    (ADX(14) > threshold AND -DI > +DI), held for ``ADX_DOWN_MIN_RUN`` consecutive bars
    (enter DEEP — where the age gradient peaked), reverts on the same validated 2:1 ATR /
    hold-10 / marketable-next-open bracket as DeepOversold. Two front gates:
      * **Regime (mandatory):** SPY nonbull (all-regime the edge is ~flat, neg 2018).
      * **Deep downtrend run:** state run-length >= ADX_DOWN_MIN_RUN.

    TRACKING-ONLY (``paper_tradeable = False``): the edge is real but MODEST (gauntlet
    nonbull S4 +0.149R t7.8, but only ~+0.05R selection alpha over dip-beta, ≈half the HA
    confluence, and it overlaps the dislocation factor the HA/oversold sleeves already
    harvest). So it flows to the hypothesis engine for out-of-sample forward-R but does NOT
    compete for live broker slots. Promote to live only if the OOS record justifies it.
    """

    @property
    def name(self) -> str:
        return "adx_didown"

    @property
    def display_name(self) -> str:
        return "ADX-Down"

    @property
    def score_key(self) -> str:
        return "adx_didown_score"

    @property
    def setup_key(self) -> str:
        return "adx_didown_setup"

    @property
    def ml_prob_key(self) -> str:
        return "adx_didown_ml_prob"

    @property
    def components_key(self) -> str:
        return "adx_didown_components"

    @property
    def weight_prefix(self) -> str:
        return "adx_didown_"

    @property
    def paper_tradeable(self) -> bool:
        return False  # tracking-only: hypothesis-engine forward-R, no live orders

    @property
    def edge_weight(self) -> float:
        # Unused while tracking-only (filtered before allocation); kept accurate
        # so promotion to live ranks it correctly without a code change.
        from bluehorseshoe.analysis.constants import ADX_DOWN_EDGE_R
        return ADX_DOWN_EDGE_R

    @staticmethod
    def _downtrend_run(adx, pdi, mdi, threshold) -> int:
        """Consecutive bars (ending at the last bar) in a strong downtrend
        (ADX>threshold AND -DI>+DI). 0 if the last bar isn't one."""
        import numpy as np
        run = 0
        for a, p, m in zip(reversed(adx), reversed(pdi), reversed(mdi)):
            if a == a and p == p and m == m and a > threshold and m > p:  # x==x rejects NaN
                run += 1
            else:
                break
        return run

    def _evaluate(self, trader, df, regime_status):
        import talib
        from bluehorseshoe.analysis.constants import (
            ADX_DOWN_ADX_THRESHOLD, ADX_DOWN_MIN_RUN,
            ADX_DOWN_BASE_SCORE, ADX_DOWN_AGE_STEP,
        )
        if df is None or len(df) < 40:
            return None
        high = df['high'].to_numpy(dtype=float)
        low = df['low'].to_numpy(dtype=float)
        close = df['close'].to_numpy(dtype=float)
        adx = talib.ADX(high, low, close, 14)
        pdi = talib.PLUS_DI(high, low, close, 14)
        mdi = talib.MINUS_DI(high, low, close, 14)
        run = self._downtrend_run(adx, pdi, mdi, ADX_DOWN_ADX_THRESHOLD)
        if run < ADX_DOWN_MIN_RUN:
            return None
        score = ADX_DOWN_BASE_SCORE + (run - ADX_DOWN_MIN_RUN) * ADX_DOWN_AGE_STEP
        components = {
            "downtrend_run": float(run),
            "adx": float(adx[-1]),
            "minus_di": float(mdi[-1]),
        }
        return self._bracket_result(df, regime_status, score, components)

    def process(self, trader, df, symbol, yesterday, ctx):
        if spy_is_nonbull(getattr(ctx, 'benchmark_df', None)) is not True:
            return None
        regime_status = (ctx.market_health or {}).get('status')
        return self._evaluate(trader, df, regime_status)

    def process_worker(self, trader, df, symbol, yesterday, worker_state,
                       overview, sentiment):
        if spy_is_nonbull(worker_state.get('benchmark_df')) is not True:
            return None
        regime_status = (worker_state.get('market_health') or {}).get('status')
        return self._evaluate(trader, df, regime_status)


# ---------------------------------------------------------------------------
# Range-bound support sleeve (range_support) — LIVE paper, 2026-06-19
# ---------------------------------------------------------------------------

class RangeSupportStrategy(TradingStrategy):
    """Buy a pullback to a pure-support level in a range-bound liquid name.

    The validated result of ``research/support_resistance_v1/`` (HANDOFF.md). Detection logic
    lives in :mod:`bluehorseshoe.analysis.indicators.support_levels` (a numeric port of the
    research detector). Fires when, on the signal bar:

      * the name is range-bound: Kaufman efficiency ratio (window 100) <= RANGE_SUPPORT_ER_MAX, AND
      * 20-day average dollar-volume >= RANGE_SUPPORT_MIN_DOLLAR_VOLUME, price in [5, 500], AND
      * price is within 0.5*ATR ABOVE the nearest *pure-support* level (a reversal cluster of >=3
        touches that has only ever acted as support), after a pullback from above in the prior 10 bars.

    Bracket: entry at the signal close, stop 1*ATR below entry, and **NO take-profit** — the exit is
    the up-day ratchet + ~25-bar time cap, managed live by ``bh_swing`` (it reads the ``range_support``
    sleeve tag off ``trade_orders`` and applies the ratchet only to these positions). Raw score is flat
    (RANGE_SUPPORT_BASE_SCORE): proximity/strength ANTI-select in the research, so they are NOT a ranking
    axis; cross-sleeve slotting uses ``edge_weight`` (the conservative selection component, not gross R).
    """

    @property
    def name(self) -> str:
        return "range_support"

    @property
    def display_name(self) -> str:
        return "RangeSupport"

    @property
    def score_key(self) -> str:
        return "range_support_score"

    @property
    def setup_key(self) -> str:
        return "range_support_setup"

    @property
    def ml_prob_key(self) -> str:
        return "range_support_ml_prob"

    @property
    def components_key(self) -> str:
        return "range_support_components"

    @property
    def weight_prefix(self) -> str:
        return "range_support_"

    @property
    def default_stop_multiplier(self) -> float:
        from bluehorseshoe.analysis.constants import RANGE_SUPPORT_STOP_MULT
        return RANGE_SUPPORT_STOP_MULT

    @property
    def default_target_multiplier(self) -> float:
        return 0.0                      # no take-profit; exit via ratchet + time cap (bh_swing)

    @property
    def min_rr_ratio(self) -> float:
        return 0.0                      # no target -> R:R gate is not applicable

    @property
    def edge_weight(self) -> float:
        from bluehorseshoe.analysis.constants import RANGE_SUPPORT_EDGE_R
        return RANGE_SUPPORT_EDGE_R

    def get_hold_days(self, regime_status=None) -> int:
        from bluehorseshoe.analysis.constants import RANGE_SUPPORT_HOLD_DAYS
        return RANGE_SUPPORT_HOLD_DAYS

    @property
    def entry_style(self) -> str:
        return "limit_below"            # resting limit at/under the support-proximity entry

    @property
    def paper_tradeable(self) -> bool:
        return True

    def _evaluate(self, df, regime_status):
        import numpy as np
        from bluehorseshoe.analysis.constants import (
            RANGE_SUPPORT_ER_MAX, RANGE_SUPPORT_MIN_DOLLAR_VOLUME, RANGE_SUPPORT_STOP_MULT,
            RANGE_SUPPORT_BASE_SCORE, RANGE_SUPPORT_PRIOR_WINRATE, MAX_RISK_PERCENT,
        )
        from bluehorseshoe.analysis.liquidity import trailing_dollar_volume
        from bluehorseshoe.analysis.indicators import support_levels as sl

        if df is None or len(df) < sl.ER_WINDOW + 10:
            return None
        close = df['close'].to_numpy(dtype=float)
        high = df['high'].to_numpy(dtype=float)
        low = df['low'].to_numpy(dtype=float)

        # 1) range-bound gate (the universe the edge was measured on)
        if not sl.is_range_bound(close, er_max=RANGE_SUPPORT_ER_MAX):
            return None
        # 2) liquidity floor
        dollar_vol_20 = trailing_dollar_volume(close, df['volume'].to_numpy(dtype=float))
        if dollar_vol_20 < RANGE_SUPPORT_MIN_DOLLAR_VOLUME:
            return None
        # 3) pure-support proximity entry on the latest bar
        sig = sl.evaluate_support_entry(high, low, close)
        if sig is None:
            return None

        entry_price = sig["entry_price"]
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None
        atr = sig["atr"]
        stop_loss = entry_price - RANGE_SUPPORT_STOP_MULT * atr
        risk = entry_price - stop_loss
        if risk <= 0:
            return None
        if (risk / entry_price) > MAX_RISK_PERCENT:      # 1*ATR stop too wide for this name
            return None

        setup = {
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "take_profit": 0.0,                          # NO target -> PaperTrader submits stop-only
            "rr_ratio": 0.0,
            "actual_close": float(close[-1]),
            "is_realistic": True,
        }
        components = {
            "range_score": round(float(sl.range_score(close)), 3),
            "dist_atr": round(sig["dist_atr"], 3),
            "support_price": round(sig["support_price"], 2),
            "touches": float(sig["touches"]),
            "dollar_vol_M": round(dollar_vol_20 / 1e6, 1),
        }
        return StrategyResult(
            score=float(RANGE_SUPPORT_BASE_SCORE),
            components=components,
            setup=setup,
            ml_prob=RANGE_SUPPORT_PRIOR_WINRATE,
            stop_multiplier=RANGE_SUPPORT_STOP_MULT,
            target_multiplier=0.0,
            regime_status=regime_status or "Neutral",
        )

    def process(self, trader, df, symbol, yesterday, ctx):
        regime_status = (ctx.market_health or {}).get('status') if getattr(ctx, 'market_health', None) else None
        return self._evaluate(df, regime_status)

    def process_worker(self, trader, df, symbol, yesterday, worker_state, overview, sentiment):
        regime_status = (worker_state.get('market_health') or {}).get('status')
        return self._evaluate(df, regime_status)
