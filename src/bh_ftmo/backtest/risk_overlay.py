"""Opt-in intraday risk-management overlay for FTMO backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional

from bh_ftmo.backtest.types import Position


@dataclass(frozen=True)
class RiskOverlayConfig:
    """Configuration for one strategy's active risk overlay."""

    enabled: bool = False
    buffer_mult: float = 1.10
    soft_daily_limit: float = -0.04

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, object]]) -> "RiskOverlayConfig":
        if not payload:
            return cls()
        return cls(
            enabled=bool(payload.get("enabled", False)),
            buffer_mult=float(payload.get("buffer_mult", cls.buffer_mult)),
            soft_daily_limit=float(payload.get("soft_daily_limit", cls.soft_daily_limit)),
        )


class RiskOverlay:
    """Per-challenge active risk overlay.

    The overlay owns only its daily realized-P&L baseline and returns execution
    decisions to the engine. It does not mutate portfolio state.
    """

    def __init__(self, config: RiskOverlayConfig, ftmo_config: Mapping[str, object], *, start_equity: float):
        self.config = config
        self._daily_loss_pct = float(ftmo_config["daily_loss_pct"])
        self.day_start_equity = float(start_equity)
        self.daily_realized_pnl = 0.0

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def on_session_reset(self, ts: datetime, day_start_equity: float) -> None:
        del ts
        self.day_start_equity = float(day_start_equity)
        self.daily_realized_pnl = 0.0

    def on_position_closed(self, pnl: float) -> None:
        if not self.enabled:
            return
        self.daily_realized_pnl += float(pnl)

    def should_block_entry(self, open_positions: Mapping[int, Position], new_risk_dollars: float) -> bool:
        if not self.enabled:
            return False
        worst_open_risk = sum(float(position.risk_at_open_account_ccy) for position in open_positions.values())
        realized_loss_today = max(0.0, -self.daily_realized_pnl)
        buffer_remaining = (self.day_start_equity * self._daily_loss_pct) - realized_loss_today
        return (worst_open_risk + float(new_risk_dollars)) > (buffer_remaining * self.config.buffer_mult)

    def positions_to_liquidate(
        self,
        open_positions: Mapping[int, Position],
        mtm_per_position: Mapping[int, float],
        equity_low_now: float,
        low_pnl_per_position: Optional[Mapping[int, float]] = None,
    ) -> list[int]:
        """Return position ids to close, worst current MTM first, until soft-safe."""

        if not self.enabled or not open_positions:
            return []

        soft_limit_equity = self.day_start_equity * (1.0 + self.config.soft_daily_limit)
        if equity_low_now >= soft_limit_equity:
            return []

        remaining_ids = [position_id for position_id in open_positions if position_id in mtm_per_position]
        selected: list[int] = []
        simulated_equity_low = float(equity_low_now)
        low_pnl = low_pnl_per_position

        while simulated_equity_low < soft_limit_equity and remaining_ids:
            worst_id = min(remaining_ids, key=lambda position_id: float(mtm_per_position[position_id]))
            selected.append(worst_id)
            remaining_ids.remove(worst_id)
            if low_pnl is None:
                simulated_equity_low -= float(mtm_per_position[worst_id])
            else:
                simulated_equity_low += float(mtm_per_position[worst_id]) - float(
                    low_pnl.get(worst_id, mtm_per_position[worst_id])
                )

        return selected
