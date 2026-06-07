"""
Strategy Registry for BlueHorseshoe.

Central mapping from strategy names to ``TradingStrategy`` instances.
Eliminates ternary branches like::

    score_key = "baseline_score" if strategy == "baseline" else "mr_score"

with::

    keys = get_strategy_keys(strategy)
    score_key = keys['score_key']
"""

from typing import Dict, List

from bluehorseshoe.analysis.strategy_interface import (
    BaselineStrategy,
    DeepDownAdxStrategy,
    DeepOversoldStrategy,
    DeepOversoldHAStrategy,
    MeanReversionStrategy,
    TradingStrategy,
)

# ---------------------------------------------------------------------------
# Singleton instances (stateless, safe to share)
# ---------------------------------------------------------------------------

_BASELINE = BaselineStrategy()
_MEAN_REVERSION = MeanReversionStrategy()
_DEEP_OVERSOLD = DeepOversoldStrategy()
_DEEP_OVERSOLD_HA = DeepOversoldHAStrategy()
_ADX_DIDOWN = DeepDownAdxStrategy()

_REGISTRY: Dict[str, TradingStrategy] = {
    _BASELINE.name: _BASELINE,
    _MEAN_REVERSION.name: _MEAN_REVERSION,
    _DEEP_OVERSOLD.name: _DEEP_OVERSOLD,
    _DEEP_OVERSOLD_HA.name: _DEEP_OVERSOLD_HA,
    _ADX_DIDOWN.name: _ADX_DIDOWN,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_strategy(name: str) -> TradingStrategy:
    """Look up a strategy by its internal name (e.g. ``'baseline'``)."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown strategy '{name}'. "
            f"Available: {list(_REGISTRY.keys())}"
        ) from None


def get_all_strategies() -> List[TradingStrategy]:
    """Return all registered strategies in insertion order."""
    return list(_REGISTRY.values())


def get_strategy_keys(name: str) -> Dict[str, str]:
    """
    Convenience helper returning all dict keys for a strategy.

    Returns::

        {
            'score_key': 'baseline_score',
            'setup_key': 'baseline_setup',
            'ml_prob_key': 'baseline_ml_prob',
            'components_key': 'baseline_components',
        }
    """
    strat = get_strategy(name)
    return {
        'score_key': strat.score_key,
        'setup_key': strat.setup_key,
        'ml_prob_key': strat.ml_prob_key,
        'components_key': strat.components_key,
    }
