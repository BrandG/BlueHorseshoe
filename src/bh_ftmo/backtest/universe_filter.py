"""Cost-survivability filter for FX backtest universes."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Mapping, Optional

import pandas as pd

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class UniverseFilterConfig:
    enabled: bool = False
    stop_pct: float = 0.005
    max_spread_to_stop_ratio: float = 0.05
    lookback_days: int = 30

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, object]]) -> "UniverseFilterConfig":
        if payload is None:
            return cls()
        return cls(
            enabled=bool(payload.get("enabled", cls.enabled)),
            stop_pct=float(payload.get("stop_pct", cls.stop_pct)),
            max_spread_to_stop_ratio=float(
                payload.get("max_spread_to_stop_ratio", cls.max_spread_to_stop_ratio)
            ),
            lookback_days=int(payload.get("lookback_days", cls.lookback_days)),
        )


def apply_universe_filter(
    bars_4h: dict[str, pd.DataFrame],
    config: UniverseFilterConfig,
) -> set[str]:
    """Return symbols whose median spread consumes no more than the configured stop share."""

    if not config.enabled:
        return set(bars_4h)
    if config.stop_pct <= 0:
        raise ValueError("universe filter stop_pct must be positive")
    if config.max_spread_to_stop_ratio < 0:
        raise ValueError("universe filter max_spread_to_stop_ratio must be non-negative")
    if config.lookback_days <= 0:
        raise ValueError("universe filter lookback_days must be positive")

    passing: set[str] = set()
    required_columns = {"timestamp", "close_bid", "close_ask"}
    for symbol, frame in bars_4h.items():
        if frame.empty:
            LOG.warning("universe filter dropped %s: empty bars", symbol)
            continue
        missing = required_columns - set(frame.columns)
        if missing:
            LOG.warning("universe filter dropped %s: missing columns %s", symbol, sorted(missing))
            continue

        window = _lookback_window(frame, config.lookback_days)
        if window.empty:
            LOG.warning("universe filter dropped %s: empty lookback window", symbol)
            continue

        bid = pd.to_numeric(window["close_bid"], errors="coerce")
        ask = pd.to_numeric(window["close_ask"], errors="coerce")
        mid = (bid + ask) / 2.0
        spread = ask - bid
        median_price = float(mid.median())
        median_spread = float(spread.median())
        if not pd.notna(median_price) or not pd.notna(median_spread) or median_price <= 0:
            LOG.warning("universe filter dropped %s: invalid median price/spread", symbol)
            continue

        ratio = median_spread / (config.stop_pct * median_price)
        if ratio <= config.max_spread_to_stop_ratio or math.isclose(
            ratio, config.max_spread_to_stop_ratio, rel_tol=1e-12, abs_tol=1e-12
        ):
            passing.add(symbol)

    return passing


def _lookback_window(frame: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    timestamps = pd.to_datetime(frame["timestamp"], errors="coerce")
    latest = timestamps.max()
    if pd.isna(latest):
        return frame.iloc[0:0]
    start = latest - pd.Timedelta(days=lookback_days)
    return frame.loc[timestamps >= start]
