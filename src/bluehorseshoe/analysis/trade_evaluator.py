from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class TradeEvalConfig:
    """Configuration for trade evaluation."""

    hold_days: int = 5
    entry_buffer_pct: float = 0.001  # 0.1% below entry price


@dataclass
class TradeEvalState:
    """Mutable state tracking a single trade evaluation."""

    entry_price: float
    adjusted_entry: float
    take_profit: float
    stop_loss: float
    status: str = "pending"  # pending -> active -> terminal
    actual_entry: Optional[float] = None
    entry_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_date: Optional[str] = None
    entry_idx: int = -1
    mae_pct: float = 0.0
    mfe_pct: float = 0.0


def _date_str(value: object) -> str:
    """Convert a date-like value to YYYY-MM-DD string form."""
    return str(value)[:10]


def check_entry(row: dict, bar_idx: int, state: TradeEvalState, hold_days: int) -> None:
    """
    Check if price crosses below adjusted entry on this bar.

    Mutates state in-place, returns None.
    """
    if row["low"] <= state.adjusted_entry:
        state.status = "active"
        state.entry_idx = bar_idx
        state.entry_date = _date_str(row["date"])

        if row["open"] < state.adjusted_entry:
            state.actual_entry = row["open"]
        else:
            state.actual_entry = state.adjusted_entry

        if row["low"] <= state.stop_loss:
            state.status = "stopped_out"
            state.exit_price = row["open"] if row["open"] < state.stop_loss else state.stop_loss
            state.exit_date = _date_str(row["date"])
            return

        if row["high"] >= state.take_profit:
            state.status = "target_hit"
            state.exit_price = row["open"] if row["open"] > state.take_profit else state.take_profit
            state.exit_date = _date_str(row["date"])
            return

    elif bar_idx >= hold_days:
        state.status = "limit_expired"


def check_active_trade(row: dict, bar_idx: int, state: TradeEvalState, hold_days: int) -> None:
    """
    Check exit conditions for an active trade. Track MAE/MFE.

    Mutates state in-place, returns None.
    """
    if state.actual_entry is None:
        return

    state.mae_pct = min(state.mae_pct, (row["low"] - state.actual_entry) / state.actual_entry)
    state.mfe_pct = max(state.mfe_pct, (row["high"] - state.actual_entry) / state.actual_entry)

    if row["low"] <= state.stop_loss:
        state.status = "stopped_out"
        state.exit_price = row["open"] if row["open"] < state.stop_loss else state.stop_loss
        state.exit_date = _date_str(row["date"])
        return

    if row["high"] >= state.take_profit:
        state.status = "target_hit"
        state.exit_price = row["open"] if row["open"] > state.take_profit else state.take_profit
        state.exit_date = _date_str(row["date"])
        return

    if (bar_idx - state.entry_idx) >= hold_days:
        state.status = "time_exit"
        state.exit_price = row["close"]
        state.exit_date = _date_str(row["date"])


def evaluate_bars(
    bars_df: pd.DataFrame,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    config: TradeEvalConfig,
) -> dict:
    """
    Walk forward through OHLCV bars and evaluate a hypothetical trade.
    """
    adjusted_entry = entry_price * (1 - config.entry_buffer_pct)
    state = TradeEvalState(
        entry_price=entry_price,
        adjusted_entry=adjusted_entry,
        take_profit=take_profit,
        stop_loss=stop_loss,
    )

    terminal_statuses = {"target_hit", "stopped_out", "time_exit", "limit_expired"}

    for bar_idx, (_, row) in enumerate(bars_df.reset_index(drop=True).iterrows()):
        row_dict = row.to_dict()
        if state.status == "pending":
            check_entry(row_dict, bar_idx, state, config.hold_days)
        elif state.status == "active":
            check_active_trade(row_dict, bar_idx, state, config.hold_days)

        if state.status in terminal_statuses:
            break

    if state.status == "active" and not bars_df.empty:
        last_row = bars_df.reset_index(drop=True).iloc[-1]
        state.status = "time_exit"
        state.exit_price = float(last_row["close"])
        state.exit_date = _date_str(last_row["date"])

    outcome_map = {
        "target_hit": "WIN",
        "stopped_out": "LOSS",
        "time_exit": "TIMEOUT",
        "limit_expired": "NOT_ENTERED",
        "pending": "NOT_ENTERED",
    }
    exit_reason_map = {
        "target_hit": "target",
        "stopped_out": "stop",
        "time_exit": "time_exit",
    }

    pnl_pct = 0.0
    days_held = 0
    if state.actual_entry is not None and state.exit_price is not None:
        pnl_pct = (state.exit_price - state.actual_entry) / state.actual_entry
        if state.entry_idx >= 0:
            if state.status == "time_exit" and not bars_df.empty:
                exit_idx = len(bars_df.reset_index(drop=True)) - 1
            else:
                exit_idx = state.entry_idx
                for idx, (_, row) in enumerate(bars_df.reset_index(drop=True).iterrows()):
                    if _date_str(row["date"]) == state.exit_date:
                        exit_idx = idx
                        break
            days_held = max(0, exit_idx - state.entry_idx)

    return {
        "outcome": outcome_map.get(state.status, "NOT_ENTERED"),
        "actual_entry": state.actual_entry,
        "entry_date": state.entry_date,
        "exit_price": state.exit_price,
        "exit_date": state.exit_date,
        "exit_reason": exit_reason_map.get(state.status),
        "days_held": days_held,
        "pnl_pct": pnl_pct,
        "mae_pct": state.mae_pct if state.actual_entry is not None else 0.0,
        "mfe_pct": state.mfe_pct if state.actual_entry is not None else 0.0,
    }
