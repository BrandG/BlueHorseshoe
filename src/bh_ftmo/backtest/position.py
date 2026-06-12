"""Pure position P&L helpers for bid/ask-aware backtest bookkeeping.

These functions keep the long/short sign conventions in one place so the engine
and equity tracker can reuse the same pricing logic consistently.
"""

from __future__ import annotations

import json
from pathlib import Path

from bh_ftmo.backtest.types import Position


JPY_STYLE_QUOTES = {"JPY", "HUF"}
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"


def _canonical_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    if raw.endswith(".SIM"):
        raw = raw[:-4]
    if raw.endswith("=X"):
        raw = raw[:-2]
    raw = raw.replace("/", "_")
    if "_" in raw:
        return raw
    if len(raw) == 6:
        return f"{raw[:3]}_{raw[3:]}"
    return raw


def _load_configured_pip_sizes() -> dict[str, float]:
    if not CONFIG_PATH.exists():
        return {}
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for item in payload.get("instruments", []):
        pip_size = item.get("pip_size")
        if pip_size is None:
            continue
        for key in ("oanda", "ftmo", "symbol"):
            value = item.get(key)
            if value:
                out[_canonical_symbol(str(value))] = float(pip_size)
    return out


CONFIGURED_PIP_SIZES = _load_configured_pip_sizes()



def _pip_size_for_symbol(symbol: str) -> float:
    """Return configured pip size, falling back to conventional FX inference."""

    canonical = _canonical_symbol(symbol)
    configured = CONFIGURED_PIP_SIZES.get(canonical)
    if configured is not None:
        return configured
    quote = canonical.split("_", 1)[1]
    return 0.01 if quote in JPY_STYLE_QUOTES else 0.0001



def pip_distance(
    entry_price: float,
    other_price: float,
    pip_size: float,
) -> float:
    """Return the signed pip distance between two prices."""

    return (other_price - entry_price) / pip_size



def realized_pnl_account_ccy(
    pos: Position,
    close_price: float,
    pip_value: float,
) -> float:
    """Return realized P&L in account currency for a closing price.

    The open and close prices are already side-of-spread prices, so no extra
    spread adjustment is applied here.
    """

    price_pips = pip_distance(pos.open_price, close_price, _pip_size_for_symbol(pos.symbol))
    direction_multiplier = 1.0 if pos.direction > 0 else -1.0
    return direction_multiplier * price_pips * pip_value * pos.lots



def floating_pnl_account_ccy(
    pos: Position,
    bid: float,
    ask: float,
    pip_value: float,
) -> float:
    """Return mark-to-market P&L using bid for longs and ask for shorts."""

    mark_price = bid if pos.direction > 0 else ask
    price_pips = pip_distance(pos.open_price, mark_price, _pip_size_for_symbol(pos.symbol))
    direction_multiplier = 1.0 if pos.direction > 0 else -1.0
    return direction_multiplier * price_pips * pip_value * pos.lots
