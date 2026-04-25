"""Equity calculations and canonical equity-curve sampling.

FTMO rule checks operate on mark-to-market equity rather than realized cash.
This module centralizes that arithmetic and provides the 1h forward-filled
series required by the Phase 3 metric contracts.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from bh_ftmo.backtest.position import floating_pnl_account_ccy
from bh_ftmo.backtest.types import Position



def equity(
    cash: float,
    positions: list[Position],
    bid_at: dict[str, float],
    ask_at: dict[str, float],
    pip_values: dict[str, float],
) -> float:
    """Return account equity as cash plus floating P&L across open positions."""

    return cash + sum(
        floating_pnl_account_ccy(
            pos,
            bid=bid_at[pos.symbol],
            ask=ask_at[pos.symbol],
            pip_value=pip_values[pos.symbol],
        )
        for pos in positions
    )


class EquityCurve:
    """Collect timestamped equity samples and resample them onto a 1h grid."""

    def __init__(self) -> None:
        self._samples: dict[datetime, float] = {}

    def record(self, ts: datetime, equity_value: float) -> None:
        """Store or overwrite the equity sample for one timestamp."""

        self._samples[ts] = equity_value

    def to_series(self) -> pd.Series:
        """Return the recorded samples as a timestamp-sorted pandas Series."""

        if not self._samples:
            return pd.Series(dtype=float)
        ordered = sorted(self._samples.items(), key=lambda item: item[0])
        index = pd.DatetimeIndex([item[0] for item in ordered])
        values = [item[1] for item in ordered]
        return pd.Series(values, index=index, dtype=float)

    def resample_1h(self) -> pd.Series:
        """Forward-fill the samples onto a regular 1h grid for canonical metrics."""

        series = self.to_series()
        if series.empty:
            return series
        grid = pd.date_range(series.index.min(), series.index.max(), freq="1h")
        return series.reindex(grid).ffill()
