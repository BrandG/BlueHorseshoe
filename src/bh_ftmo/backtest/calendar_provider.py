"""Economic-calendar blackout seam for the Phase 3 backtest engine.

Phase 3 ships only the protocol and a null implementation. A real provider can
be introduced later without changing the trade-admission API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol


class CalendarProvider(Protocol):
    """Minimal blackout interface consumed by trade admission logic."""

    def is_blackout(self, ts: datetime, currencies: set[str]) -> bool:
        """Return whether trading should be blocked at ``ts`` for ``currencies``."""

    def next_blackout_end(self, ts: datetime, currencies: set[str]) -> Optional[datetime]:
        """Return the end of the active blackout window, if any."""


class NullCalendarProvider:
    """Phase 3 default provider that never blocks trading."""

    def is_blackout(self, ts: datetime, currencies: set[str]) -> bool:
        """Return ``False`` because the null provider never blocks entries."""

        del ts, currencies
        return False

    def next_blackout_end(self, ts: datetime, currencies: set[str]) -> Optional[datetime]:
        """Return ``None`` because the null provider has no blackout windows."""

        del ts, currencies
