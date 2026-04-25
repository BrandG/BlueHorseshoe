"""Portfolio-level collection and deterministic ordering of exit events.

Intrabar events are extracted per position, but FTMO rule enforcement depends on
account-wide chronological ordering. This module produces the sorted event list
consumed by the future engine loop.
"""

from __future__ import annotations

import pandas as pd

from bh_ftmo.backtest import intrabar
from bh_ftmo.backtest.types import ExitEvent, Position

_KIND_PRIORITY = {
    "stop": 0,
    "target": 1,
    "swap": 2,
    "weekend_flatten": 3,
    "deadline": 4,
    "session_close": 5,
}



def collect_and_sort(
    open_positions: list[Position],
    bar_4h_by_symbol: dict[str, pd.Series],
    bars_1h_by_symbol: dict[str, pd.DataFrame],
    pip_sizes: dict[str, float],
) -> list[ExitEvent]:
    """Collect all candidate events for open positions and sort deterministically."""

    events: list[ExitEvent] = []
    for position in open_positions:
        events.extend(
            intrabar.extract_events(
                position,
                bar_4h=bar_4h_by_symbol[position.symbol],
                bars_1h=bars_1h_by_symbol[position.symbol],
                pip_size=pip_sizes[position.symbol],
            )
        )
    return sorted(events, key=lambda event: (event.ts, event.symbol, _KIND_PRIORITY.get(event.kind, 99)))
