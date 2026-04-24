"""BH FTMO analysis layer — strategies, signal generation, cluster filter."""

from bh_ftmo.analysis.signal_generator import (
    DEFAULT_STRENGTH_PAIRS,
    DXY_CONSTITUENTS,
    SignalContext,
    SignalGenerator,
)
from bh_ftmo.analysis.strategy import (
    BaselineStrategy,
    Signal,
    load_weights,
)

__all__ = [
    "BaselineStrategy",
    "Signal",
    "SignalContext",
    "SignalGenerator",
    "DEFAULT_STRENGTH_PAIRS",
    "DXY_CONSTITUENTS",
    "load_weights",
]
