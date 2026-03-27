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
)
from bluehorseshoe.core.config import weights_config


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
