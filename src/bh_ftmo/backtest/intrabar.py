"""Intrabar stop/target event extraction from 1h sub-bars.

The backtest runs on H4 bars but uses stored H1 bars to resolve stop and target
hits within each H4 candle. This module emits the candidate close events; final
portfolio ordering remains the event queue's responsibility.
"""

from __future__ import annotations

import pandas as pd

from bh_ftmo.backtest.types import ExitEvent, Position



def extract_events(
    position: Position,
    bar_4h: pd.Series,
    bars_1h: pd.DataFrame,
    pip_size: float,
) -> list[ExitEvent]:
    """Return stop/target events encountered while walking the four H1 sub-bars."""

    del bar_4h, pip_size
    events: list[ExitEvent] = []
    ordered = bars_1h.sort_values("timestamp")
    for _, row in ordered.iterrows():
        ts = row["timestamp"]
        if position.direction > 0:
            stop_hit = float(row["low_bid"]) <= position.stop
            target_hit = float(row["high_bid"]) >= position.target
        else:
            stop_hit = float(row["high_ask"]) >= position.stop
            target_hit = float(row["low_ask"]) <= position.target

        if stop_hit:
            events.append(
                ExitEvent(
                    ts=ts,
                    symbol=position.symbol,
                    kind="stop",
                    price=position.stop,
                    position_id=position.id,
                )
            )
        if target_hit:
            events.append(
                ExitEvent(
                    ts=ts,
                    symbol=position.symbol,
                    kind="target",
                    price=position.target,
                    position_id=position.id,
                )
            )
        if events:
            return events
    return []
