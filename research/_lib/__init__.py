"""Shared reference harness for BlueHorseshoe research.

Import the pieces you need, but VALIDATE per study — this is a starting scaffold that
encodes the agreed standard (see research/README.md), not a blessed black box. The
canary in every run is `matched_random_benchmark`: if random doesn't read ~0.000R,
the machinery is non-neutral and no cell can be trusted until it does.
"""

from .harness import (
    bracket_trade,
    atr_pct,
    passes_liquidity,
    clustered_se,
    newey_west_se,
    summarize_R,
    matched_random_benchmark,
)

__all__ = [
    "bracket_trade",
    "atr_pct",
    "passes_liquidity",
    "clustered_se",
    "newey_west_se",
    "summarize_R",
    "matched_random_benchmark",
]
