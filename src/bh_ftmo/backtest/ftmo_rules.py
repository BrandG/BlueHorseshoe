"""FTMO rule enforcement: daily loss, max loss, target, and trading-day gates.

The rule engine is stateful within one challenge run, but it is not shared
across runs and contains no module-level mutable challenge state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from bh_ftmo.backtest.types import RuleBreach
from bh_ftmo.data.fx_time_utils import ftmo_day_boundary, ny_calendar_day

REQUIRED_FIELDS = frozenset(
    {
        "initial_balance",
        "account_currency",
        "phase",
        "profit_target_pct",
        "daily_loss_pct",
        "max_loss_pct",
        "max_loss_type",
        "min_trading_days",
        "max_trading_days",
        "server_timezone",
        "commission_per_lot_round_turn",
        "swap_model",
    }
)
_VALID_MAX_LOSS_TYPES = frozenset({"static", "trailing"})


class FtmoConfigUnverifiedError(Exception):
    """Raised when the FTMO config block is incomplete or still scaffolded."""


@dataclass
class ChallengeState:
    """Engine-internal mutable state for one challenge run."""

    reference_equity: float
    peak_equity: float
    trading_day_set: set[date]
    breached: Optional[RuleBreach]
    target_hit_at: Optional[datetime]
    last_reset_ts: Optional[datetime]
    challenge_start_ts: datetime
    challenge_start_equity: float



def _strip_metadata_keys(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if not key.startswith("_")}



def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return "PLACEHOLDER" in value
    return False



def load_ftmo_config(path: Path) -> dict[str, Any]:
    """Load and validate the FTMO config block from a JSON config file."""

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    ftmo = payload.get("ftmo")
    if not isinstance(ftmo, dict):
        raise FtmoConfigUnverifiedError("config is missing an ftmo object")

    cleaned = _strip_metadata_keys(ftmo)
    missing = sorted(REQUIRED_FIELDS - cleaned.keys())
    if missing:
        raise FtmoConfigUnverifiedError(f"ftmo config missing required fields: {', '.join(missing)}")

    placeholders = sorted(key for key, value in cleaned.items() if _contains_placeholder(value))
    if placeholders:
        raise FtmoConfigUnverifiedError(f"ftmo config still contains PLACEHOLDER values: {', '.join(placeholders)}")

    max_loss_type = cleaned.get("max_loss_type")
    if max_loss_type not in _VALID_MAX_LOSS_TYPES:
        raise FtmoConfigUnverifiedError("ftmo config max_loss_type must be one of {'static', 'trailing'}")

    return cleaned


class FtmoRuleEngine:
    """Stateful FTMO rule evaluator for a single challenge simulation."""

    def __init__(self, ftmo_config: dict[str, Any], start_equity: float, start_ts: datetime, server_tz: str):
        self._ftmo_config = dict(ftmo_config)
        self._server_tz = server_tz
        self._state = ChallengeState(
            reference_equity=float(start_equity),
            peak_equity=float(start_equity),
            trading_day_set=set(),
            breached=None,
            target_hit_at=None,
            last_reset_ts=self._boundary_at_or_before(start_ts),
            challenge_start_ts=start_ts,
            challenge_start_equity=float(start_equity),
        )
        self._last_seen_ts = start_ts

    @property
    def state(self) -> ChallengeState:
        return self._state

    def _boundary_at_or_before(self, ts: datetime) -> datetime:
        next_boundary = ftmo_day_boundary(ts, server_tz=self._server_tz)
        if next_boundary == ts:
            return ts
        server_zone = ZoneInfo(self._server_tz)
        local_ts = ts.replace(tzinfo=ZoneInfo("UTC")).astimezone(server_zone)
        boundary_local = local_ts.replace(hour=0, minute=0, second=0, microsecond=0)
        return boundary_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    def _max_loss_threshold(self) -> float:
        initial_balance = float(self._ftmo_config["initial_balance"])
        max_loss_pct = float(self._ftmo_config["max_loss_pct"])
        max_loss_type = self._ftmo_config["max_loss_type"]
        if max_loss_type == "static":
            return initial_balance * (1.0 - max_loss_pct)
        if max_loss_type == "trailing":
            return self._state.peak_equity * (1.0 - max_loss_pct)
        raise AssertionError("invalid ftmo_config['max_loss_type']; expected 'static' or 'trailing'")

    def _daily_loss_threshold(self) -> float:
        initial_balance = float(self._ftmo_config["initial_balance"])
        daily_loss_pct = float(self._ftmo_config["daily_loss_pct"])
        return self._state.reference_equity - (daily_loss_pct * initial_balance)

    def _target_threshold(self) -> float:
        initial_balance = float(self._ftmo_config["initial_balance"])
        profit_target_pct = float(self._ftmo_config["profit_target_pct"])
        return initial_balance * (1.0 + profit_target_pct)

    def is_session_reset_due(self, ts: datetime) -> bool:
        """Return True when ``ts`` has crossed into a new FTMO day."""

        self._last_seen_ts = ts
        if self._state.last_reset_ts is None:
            return True
        return self._boundary_at_or_before(ts) > self._state.last_reset_ts

    def on_session_reset(self, ts: datetime, equity_after_swap: float) -> None:
        """Capture the new daily-loss baseline after rollover swap is applied."""

        self._last_seen_ts = ts
        boundary = self._boundary_at_or_before(ts)
        if self._state.last_reset_ts == boundary:
            self._state.reference_equity = float(equity_after_swap)
            return
        self._state.reference_equity = float(equity_after_swap)
        self._state.last_reset_ts = boundary

    def on_trade_event(self, ts: datetime) -> None:
        """Mark the NY calendar day of an open or close as a trading day."""

        self._last_seen_ts = ts
        self._state.trading_day_set.add(ny_calendar_day(ts))

    def on_equity_update(self, ts: datetime, equity: float) -> Optional[RuleBreach]:
        """Evaluate hard rules in FTMO precedence order and record target hits."""

        self._last_seen_ts = ts
        if self._state.breached is not None:
            return self._state.breached

        self._state.peak_equity = max(self._state.peak_equity, float(equity))

        max_loss_threshold = self._max_loss_threshold()
        if equity < max_loss_threshold:
            self._state.breached = RuleBreach(
                rule="max_loss",
                timestamp=ts,
                equity_at_breach=float(equity),
                threshold=max_loss_threshold,
            )
            return self._state.breached

        daily_loss_threshold = self._daily_loss_threshold()
        if equity < daily_loss_threshold:
            self._state.breached = RuleBreach(
                rule="daily_loss",
                timestamp=ts,
                equity_at_breach=float(equity),
                threshold=daily_loss_threshold,
            )
            return self._state.breached

        if self._state.target_hit_at is None and equity >= self._target_threshold() - 1e-9:
            self._state.target_hit_at = ts
        return None

    def can_open_new(self, ts: datetime) -> tuple[bool, Optional[str]]:
        """Return whether the challenge is allowed to take a new entry."""

        self._last_seen_ts = ts
        if self._state.breached is not None:
            return False, "breached"
        if self.days_in_challenge(ts) > int(self._ftmo_config["max_trading_days"]):
            return False, "past_max_trading_days"
        if self._state.target_hit_at is not None and self.trading_days_count() >= int(self._ftmo_config["min_trading_days"]):
            return False, "target_already_passed"
        return True, None

    def is_passed(self) -> bool:
        """Return whether the challenge has met the pass conditions."""

        return (
            self._state.breached is None
            and self._state.target_hit_at is not None
            and self.trading_days_count() >= int(self._ftmo_config["min_trading_days"])
        )

    def is_pushed(self) -> bool:
        """Return whether the challenge expired without a pass or fail."""

        return (
            self._state.breached is None
            and self._state.target_hit_at is None
            and self.days_in_challenge(self._last_seen_ts) > int(self._ftmo_config["max_trading_days"])
        )

    def days_in_challenge(self, current_ts: datetime) -> int:
        """Return calendar days elapsed in the challenge window, inclusive."""

        return (current_ts.date() - self._state.challenge_start_ts.date()).days + 1

    def trading_days_count(self) -> int:
        """Return the number of distinct NY trading days with opens or closes."""

        return len(self._state.trading_day_set)
