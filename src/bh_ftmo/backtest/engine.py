"""BH FTMO Phase 3 backtest engine: portfolio simulation with FTMO rules."""

from __future__ import annotations

# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches,too-many-statements,cell-var-from-loop

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.calendar_provider import CalendarProvider
from bh_ftmo.backtest.commission import commission_at_open
from bh_ftmo.backtest.equity import EquityCurve, equity
from bh_ftmo.backtest.event_queue import apply_in_order, collect_and_sort
from bh_ftmo.backtest.ftmo_rules import FtmoRuleEngine
from bh_ftmo.data.fx_time_utils import ftmo_day_boundary
from bh_ftmo.backtest.pip_value import quote_to_account_rate
from bh_ftmo.backtest.risk_exits import DeadlineState, deadline_check, weekend_flatten_events
from bh_ftmo.backtest.swap import SwapRates, apply_swap_to_positions
from bh_ftmo.backtest.trade_factory import can_open, derive_position
from bh_ftmo.backtest.types import ChallengeResult, ExitEvent, PairSpec, Position, RuleBreach, Trade

_VALID_MAX_LOSS_TYPES = frozenset({"static", "trailing"})


@dataclass(frozen=True)
class StartConfig:
    """One randomized challenge start configuration."""

    start_ts: datetime
    end_ts: datetime
    rng_seed: int



def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if "timestamp" in frame.columns:
        normalized = frame.copy()
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"])
        normalized = normalized.set_index("timestamp", drop=False)
    else:
        normalized = frame.copy()
        normalized.index = pd.to_datetime(normalized.index)
        normalized["timestamp"] = normalized.index
    normalized = normalized.sort_index()
    normalized.index.name = None
    return normalized



def _require_row(frame: pd.DataFrame, ts: datetime) -> pd.Series:
    row = frame.loc[ts]
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row



def _slice_1h_window(frame: pd.DataFrame, bar_ts: datetime) -> pd.DataFrame:
    end_ts = bar_ts + timedelta(hours=4)
    return frame.loc[(frame.index > bar_ts) & (frame.index <= end_ts)]



def _snapshot_from_rows(bar_row: pd.Series, one_hour_rows: pd.DataFrame, ts: datetime, bar_ts: datetime) -> tuple[float, float]:
    if ts == bar_ts:
        return float(bar_row["open_bid"]), float(bar_row["open_ask"])
    if ts == bar_ts + timedelta(hours=4):
        return float(bar_row["close_bid"]), float(bar_row["close_ask"])
    if ts in one_hour_rows.index:
        row = _require_row(one_hour_rows, ts)
        return float(row["close_bid"]), float(row["close_ask"])
    earlier = one_hour_rows.loc[one_hour_rows.index <= ts]
    if not earlier.empty:
        row = earlier.iloc[-1]
        return float(row["close_bid"]), float(row["close_ask"])
    return float(bar_row["open_bid"]), float(bar_row["open_ask"])



def _rates_snapshot_at(
    bars_4h: dict[str, pd.DataFrame],
    bars_1h: dict[str, pd.DataFrame],
    symbols: set[str],
    ts: datetime,
    bar_ts: datetime,
) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for symbol in symbols:
        if bar_ts not in bars_4h[symbol].index:
            continue
        bar_row = _require_row(bars_4h[symbol], bar_ts)
        one_hour_rows = _slice_1h_window(bars_1h[symbol], bar_ts)
        bid, ask = _snapshot_from_rows(bar_row, one_hour_rows, ts, bar_ts)
        snapshot[symbol] = 0.5 * (bid + ask)
    return snapshot



def _bid_ask_snapshot_at(
    bars_4h: dict[str, pd.DataFrame],
    bars_1h: dict[str, pd.DataFrame],
    symbols: set[str],
    ts: datetime,
    bar_ts: datetime,
) -> tuple[dict[str, float], dict[str, float]]:
    bids: dict[str, float] = {}
    asks: dict[str, float] = {}
    for symbol in symbols:
        bar_row = _require_row(bars_4h[symbol], bar_ts)
        one_hour_rows = _slice_1h_window(bars_1h[symbol], bar_ts)
        bid, ask = _snapshot_from_rows(bar_row, one_hour_rows, ts, bar_ts)
        bids[symbol] = bid
        asks[symbol] = ask
    return bids, asks



def _replace_trade_details(trade: Trade, swap_total: float, components: dict[str, float]) -> Trade:
    return replace(
        trade,
        pnl_account_ccy=trade.pnl_account_ccy + swap_total,
        swap_account_ccy=swap_total,
        components=dict(components),
    )



def _flush_open_positions(
    open_positions: dict[int, Position],
    ts: datetime,
    bar_ts: datetime,
    bars_4h: dict[str, pd.DataFrame],
    bars_1h: dict[str, pd.DataFrame],
    pair_specs: dict[str, PairSpec],
    ftmo_config: dict,
    cash: float,
    swap_totals_by_position: dict[int, float],
    components_by_position: dict[int, dict[str, float]],
) -> tuple[dict[int, Position], float, list[Trade]]:
    if not open_positions:
        return {}, cash, []

    symbols = {position.symbol for position in open_positions.values()}
    rates_universe = set(bars_4h.keys())
    bids, asks = _bid_ask_snapshot_at(bars_4h, bars_1h, symbols, ts, bar_ts)
    rates_at_ts = _rates_snapshot_at(bars_4h, bars_1h, rates_universe, ts, bar_ts)

    def pip_value_at(event_ts: datetime, symbol: str) -> float:
        del event_ts
        rate = quote_to_account_rate(symbol, ftmo_config["account_currency"], rates_at_ts)
        return pair_specs[symbol].pip_size * pair_specs[symbol].contract_size * rate

    events = [
        ExitEvent(
            ts=ts,
            symbol=position.symbol,
            kind="session_close",
            price=bids[position.symbol] if position.direction > 0 else asks[position.symbol],
            position_id=position.id,
        )
        for position in open_positions.values()
    ]

    class _NoOpRuleEngine:
        def on_trade_event(self, event_ts: datetime) -> None:
            """Ignore trade-event callbacks during breach flushes."""

            del event_ts

        def on_equity_update(self, event_ts: datetime, equity_value: float) -> None:
            """Ignore equity callbacks during breach flushes."""

            del event_ts, equity_value

    _, cash_after, raw_trades, _ = apply_in_order(
        events=sorted(events, key=lambda event: (event.ts, event.symbol)),
        open_positions=open_positions,
        cash=cash,
        pip_specs=pair_specs,
        pip_values_at=pip_value_at,
        commission_per_lot_round_turn=float(ftmo_config["commission_per_lot_round_turn"]),
        equity_curve=EquityCurve(),
        rule_engine=_NoOpRuleEngine(),
        bid_at=bids,
        ask_at=asks,
    )

    flushed: list[Trade] = []
    for trade in raw_trades:
        position_id = next(
            position_id
            for position_id, position in open_positions.items()
            if position.symbol == trade.symbol and position.open_ts == trade.open_ts
        )
        flushed.append(
            replace(
                _replace_trade_details(
                    trade,
                    swap_totals_by_position.get(position_id, 0.0),
                    components_by_position.get(position_id, {}),
                ),
                exit_reason="ftmo_breach",
            )
        )
        swap_totals_by_position.pop(position_id, None)
        components_by_position.pop(position_id, None)
    return {}, cash_after, flushed



def _append_future_skips(signals: list[Signal], after_ts: datetime, reason: str, skipped: list[tuple[Signal, str]]) -> None:
    for signal in signals:
        if signal.above_threshold and signal.timestamp > after_ts:
            skipped.append((signal, reason))



def run_challenge(
    bars_4h: dict[str, pd.DataFrame],
    bars_1h: dict[str, pd.DataFrame],
    signals: list[Signal],
    atr_by_symbol: dict[str, pd.Series],
    pair_specs: dict[str, PairSpec],
    ftmo_config: dict,
    sizing_config: dict,
    swap_rates_by_symbol: dict[str, SwapRates],
    calendar_provider: CalendarProvider,
    start_ts: datetime,
    start_equity: float,
    rng_seed: int,
    deadline: Optional[date] = None,
) -> ChallengeResult:
    """Run one pure FTMO challenge simulation over preloaded market data."""

    assert ftmo_config.get("max_loss_type") in _VALID_MAX_LOSS_TYPES, (
        "invalid ftmo_config['max_loss_type']; expected 'static' or 'trailing'"
    )

    bars_4h_norm = {symbol: _normalize_bars(frame) for symbol, frame in bars_4h.items()}
    bars_1h_norm = {symbol: _normalize_bars(frame) for symbol, frame in bars_1h.items()}
    rates_universe = set(bars_4h_norm.keys())
    signals_sorted = sorted(signals, key=lambda signal: (signal.timestamp, signal.symbol, signal.strategy))
    signals_by_ts: dict[datetime, list[Signal]] = {}
    for signal in signals_sorted:
        signals_by_ts.setdefault(signal.timestamp, []).append(signal)

    timeline = sorted({ts for frame in bars_4h_norm.values() for ts in frame.index if ts >= start_ts})
    challenge_deadline_ts = start_ts + timedelta(days=int(ftmo_config["max_trading_days"]))

    rule_engine = FtmoRuleEngine(ftmo_config, start_equity=start_equity, start_ts=start_ts, server_tz=ftmo_config["server_timezone"])
    equity_curve = EquityCurve()
    daily_samples: dict[datetime, float] = {}
    open_positions: dict[int, Position] = {}
    swap_totals_by_position: dict[int, float] = {}
    components_by_position: dict[int, dict[str, float]] = {}
    trades: list[Trade] = []
    breaches: list[RuleBreach] = []
    skipped_signals: list[tuple[Signal, str]] = []
    cash = float(start_equity)
    next_position_id = 1
    outcome = "in_progress"
    failed_by: Optional[str] = None
    actual_end_ts = start_ts

    for bar_ts in timeline:
        if bar_ts > challenge_deadline_ts:
            outcome = "passed" if rule_engine.is_passed() else "push"
            actual_end_ts = bar_ts
            break

        symbols_now = {symbol for symbol, frame in bars_4h_norm.items() if bar_ts in frame.index}
        if not symbols_now:
            continue

        actual_end_ts = bar_ts
        open_symbols = {position.symbol for position in open_positions.values()}
        open_symbols_with_data = {
            symbol for symbol in open_symbols if bar_ts in bars_4h_norm[symbol].index
        }
        open_positions_with_data = [
            position for position in open_positions.values() if position.symbol in open_symbols_with_data
        ]
        observed_symbols = symbols_now | open_symbols_with_data
        bid_at_bar, ask_at_bar = _bid_ask_snapshot_at(bars_4h_norm, bars_1h_norm, observed_symbols, bar_ts, bar_ts)
        rates_at_bar = _rates_snapshot_at(bars_4h_norm, bars_1h_norm, rates_universe, bar_ts, bar_ts)

        def pip_value_at(event_ts: datetime, symbol: str) -> float:
            del event_ts
            rate = quote_to_account_rate(symbol, ftmo_config["account_currency"], rates_at_bar)
            return pair_specs[symbol].pip_size * pair_specs[symbol].contract_size * rate

        bar_close_ts = bar_ts + timedelta(hours=4)
        reset_ts = ftmo_day_boundary(bar_ts, server_tz=ftmo_config["server_timezone"])
        if bar_ts <= reset_ts <= bar_close_ts and rule_engine.is_session_reset_due(reset_ts):
            reset_symbols = symbols_now | open_symbols_with_data
            bid_at_reset, ask_at_reset = _bid_ask_snapshot_at(bars_4h_norm, bars_1h_norm, reset_symbols, reset_ts, bar_ts)
            rates_at_reset = _rates_snapshot_at(bars_4h_norm, bars_1h_norm, rates_universe, reset_ts, bar_ts)

            def pip_value_at_reset(event_ts: datetime, symbol: str) -> float:
                del event_ts
                rate = quote_to_account_rate(symbol, ftmo_config["account_currency"], rates_at_reset)
                return pair_specs[symbol].pip_size * pair_specs[symbol].contract_size * rate

            if open_positions:
                swap_cashflows = apply_swap_to_positions(list(open_positions.values()), swap_rates_by_symbol, rollover_date=reset_ts.date())
                total_swap = sum(swap_cashflows.values())
                cash += total_swap
                for position_id, cashflow in swap_cashflows.items():
                    swap_totals_by_position[position_id] = swap_totals_by_position.get(position_id, 0.0) + cashflow
            current_equity = equity(
                cash,
                open_positions_with_data,
                bid_at_reset,
                ask_at_reset,
                {
                    position.symbol: pip_value_at_reset(reset_ts, position.symbol)
                    for position in open_positions_with_data
                },
            )
            rule_engine.on_session_reset(reset_ts, current_equity)
            equity_curve.record(reset_ts, current_equity)
            daily_samples[reset_ts] = current_equity
            breach = rule_engine.on_equity_update(reset_ts, current_equity)
            if breach is not None:
                breaches.append(breach)
                failed_by = breach.rule
                flushed_positions, cash, flushed_trades = _flush_open_positions(
                    open_positions,
                    breach.timestamp,
                    bar_ts,
                    bars_4h_norm,
                    bars_1h_norm,
                    pair_specs,
                    ftmo_config,
                    cash,
                    swap_totals_by_position,
                    components_by_position,
                )
                open_positions = flushed_positions
                trades.extend(flushed_trades)
                outcome = "failed"
                _append_future_skips(signals_sorted, breach.timestamp, "rule_blocked", skipped_signals)
                actual_end_ts = breach.timestamp
                break

        deadline_state = deadline_check(bar_ts, deadline, sizing_config)
        forced_events = weekend_flatten_events(
            open_positions_with_data,
            bar_ts,
            bid_at_bar,
            ask_at_bar,
            sizing_config,
        )
        if deadline_state == DeadlineState.HARD_FLATTEN and open_positions:
            forced_events.extend(
                ExitEvent(
                    ts=bar_ts,
                    symbol=position.symbol,
                    kind="deadline",
                    price=bid_at_bar[position.symbol] if position.direction > 0 else ask_at_bar[position.symbol],
                    position_id=position.id,
                )
                for position in open_positions_with_data
            )

        if forced_events:
            event_symbols = open_symbols_with_data | {event.symbol for event in forced_events}
            bid_snapshot, ask_snapshot = _bid_ask_snapshot_at(bars_4h_norm, bars_1h_norm, event_symbols, bar_ts, bar_ts)
            raw_open_positions, cash, new_trades, breach = apply_in_order(
                events=sorted(forced_events, key=lambda event: (event.ts, event.symbol, event.kind)),
                open_positions=open_positions,
                cash=cash,
                pip_specs=pair_specs,
                pip_values_at=pip_value_at,
                commission_per_lot_round_turn=float(ftmo_config["commission_per_lot_round_turn"]),
                equity_curve=equity_curve,
                rule_engine=rule_engine,
                bid_at=bid_snapshot,
                ask_at=ask_snapshot,
            )
            for trade in new_trades:
                position_id = next(
                    pos_id
                    for pos_id, position in open_positions.items()
                    if position.symbol == trade.symbol and position.open_ts == trade.open_ts
                )
                trades.append(
                    _replace_trade_details(
                        trade,
                        swap_totals_by_position.pop(position_id, 0.0),
                        components_by_position.pop(position_id, {}),
                    )
                )
            open_positions = raw_open_positions
            if breach is not None:
                breaches.append(breach)
                failed_by = breach.rule
                flushed_positions, cash, flushed_trades = _flush_open_positions(
                    open_positions,
                    breach.timestamp,
                    bar_ts,
                    bars_4h_norm,
                    bars_1h_norm,
                    pair_specs,
                    ftmo_config,
                    cash,
                    swap_totals_by_position,
                    components_by_position,
                )
                open_positions = flushed_positions
                trades.extend(flushed_trades)
                outcome = "failed"
                _append_future_skips(signals_sorted, breach.timestamp, "rule_blocked", skipped_signals)
                actual_end_ts = breach.timestamp
                break

        if open_positions:
            open_symbols = {position.symbol for position in open_positions.values()}
            open_symbols_with_data = {
                symbol for symbol in open_symbols if bar_ts in bars_4h_norm[symbol].index
            }
            open_positions_with_data = [
                position for position in open_positions.values() if position.symbol in open_symbols_with_data
            ]
            bar_rows = {symbol: _require_row(bars_4h_norm[symbol], bar_ts) for symbol in open_symbols_with_data}
            one_hour_windows = {
                symbol: _slice_1h_window(bars_1h_norm[symbol], bar_ts)
                for symbol in open_symbols_with_data
            }
            events = collect_and_sort(
                open_positions_with_data,
                bar_4h_by_symbol=bar_rows,
                bars_1h_by_symbol=one_hour_windows,
                pip_sizes={symbol: pair_specs[symbol].pip_size for symbol in open_symbols_with_data},
            )
            for event in events:
                event_symbols = open_symbols_with_data | {event.symbol}
                bid_snapshot, ask_snapshot = _bid_ask_snapshot_at(
                    bars_4h_norm,
                    bars_1h_norm,
                    event_symbols,
                    event.ts,
                    bar_ts,
                )
                raw_open_positions, cash, new_trades, breach = apply_in_order(
                    events=[event],
                    open_positions=open_positions,
                    cash=cash,
                    pip_specs=pair_specs,
                    pip_values_at=pip_value_at,
                    commission_per_lot_round_turn=float(ftmo_config["commission_per_lot_round_turn"]),
                    equity_curve=equity_curve,
                    rule_engine=rule_engine,
                    bid_at=bid_snapshot,
                    ask_at=ask_snapshot,
                )
                for trade in new_trades:
                    position_id = next(
                        pos_id
                        for pos_id, position in open_positions.items()
                        if position.symbol == trade.symbol and position.open_ts == trade.open_ts
                    )
                    trades.append(
                        _replace_trade_details(
                            trade,
                            swap_totals_by_position.pop(position_id, 0.0),
                            components_by_position.pop(position_id, {}),
                        )
                    )
                open_positions = raw_open_positions
                if breach is not None:
                    breaches.append(breach)
                    failed_by = breach.rule
                    flushed_positions, cash, flushed_trades = _flush_open_positions(
                        open_positions,
                        breach.timestamp,
                        bar_ts,
                        bars_4h_norm,
                        bars_1h_norm,
                        pair_specs,
                        ftmo_config,
                        cash,
                        swap_totals_by_position,
                        components_by_position,
                    )
                    open_positions = flushed_positions
                    trades.extend(flushed_trades)
                    outcome = "failed"
                    _append_future_skips(signals_sorted, breach.timestamp, "rule_blocked", skipped_signals)
                    actual_end_ts = breach.timestamp
                    break
            if outcome == "failed":
                break

        bar_close_ts = bar_ts + timedelta(hours=4)
        open_symbols = {position.symbol for position in open_positions.values()}
        open_symbols_with_data = {
            symbol for symbol in open_symbols if bar_ts in bars_4h_norm[symbol].index
        }
        open_positions_with_data = [
            position for position in open_positions.values() if position.symbol in open_symbols_with_data
        ]
        close_symbols = (
            {symbol for symbol, frame in bars_4h_norm.items() if bar_ts in frame.index}
            | open_symbols_with_data
        )
        bid_at_close, ask_at_close = _bid_ask_snapshot_at(
            bars_4h_norm,
            bars_1h_norm,
            close_symbols,
            bar_close_ts,
            bar_ts,
        )
        rates_at_close = _rates_snapshot_at(bars_4h_norm, bars_1h_norm, rates_universe, bar_close_ts, bar_ts)
        close_pip_values = {
            symbol: (
                pair_specs[symbol].pip_size
                * pair_specs[symbol].contract_size
                * quote_to_account_rate(symbol, ftmo_config["account_currency"], rates_at_close)
            )
            for symbol in open_symbols_with_data
        }
        current_equity = equity(cash, open_positions_with_data, bid_at_close, ask_at_close, close_pip_values)
        equity_curve.record(bar_close_ts, current_equity)
        breach = rule_engine.on_equity_update(bar_close_ts, current_equity)
        if breach is not None:
            breaches.append(breach)
            failed_by = breach.rule
            flushed_positions, cash, flushed_trades = _flush_open_positions(
                open_positions,
                breach.timestamp,
                bar_ts,
                bars_4h_norm,
                bars_1h_norm,
                pair_specs,
                ftmo_config,
                cash,
                swap_totals_by_position,
                components_by_position,
            )
            open_positions = flushed_positions
            trades.extend(flushed_trades)
            outcome = "failed"
            _append_future_skips(signals_sorted, breach.timestamp, "rule_blocked", skipped_signals)
            actual_end_ts = breach.timestamp
            break

        if deadline_state not in {DeadlineState.NO_NEW_ENTRIES, DeadlineState.HARD_FLATTEN}:
            entry_gate_reason: Optional[str] = None
            can_open_entries, entry_gate_reason = rule_engine.can_open_new(bar_ts)
        else:
            can_open_entries = False
            entry_gate_reason = "deadline_blocked"

        for signal in signals_by_ts.get(bar_ts, []):
            if not signal.above_threshold:
                continue
            if not can_open_entries:
                skipped_signals.append((signal, entry_gate_reason or "rule_blocked"))
                continue
            if signal.symbol not in bars_4h_norm:
                skipped_signals.append((signal, "missing_4h_data"))
                continue
            symbol_timeline = bars_4h_norm[signal.symbol].index
            next_candidates = symbol_timeline[symbol_timeline > bar_ts]
            if len(next_candidates) == 0:
                skipped_signals.append((signal, "missing_next_bar"))
                continue
            next_candidate = next_candidates[0]
            next_bar_ts = next_candidate.to_pydatetime() if hasattr(next_candidate, "to_pydatetime") else next_candidate
            next_bar = _require_row(bars_4h_norm[signal.symbol], next_bar_ts)
            one_hour_available = not _slice_1h_window(bars_1h_norm[signal.symbol], next_bar_ts).empty
            allowed, reason = can_open(
                signal,
                list(open_positions.values()),
                sizing_config,
                calendar_provider,
                one_hour_available,
                bar_ts,
            )
            if not allowed:
                skipped_signals.append((signal, reason or "admission_blocked"))
                continue
            rate_snapshot = _rates_snapshot_at(
                bars_4h_norm,
                bars_1h_norm,
                rates_universe,
                next_bar_ts,
                next_bar_ts,
            )
            quote_rate = quote_to_account_rate(
                signal.symbol,
                ftmo_config["account_currency"],
                rate_snapshot,
            )
            atr_series = atr_by_symbol[signal.symbol]
            atr_value = float(atr_series.loc[bar_ts])
            position = derive_position(
                signal,
                next_bar=next_bar,
                atr_14=atr_value,
                pair_spec=pair_specs[signal.symbol],
                sizing_config=sizing_config,
                account_currency=ftmo_config["account_currency"],
                current_equity=current_equity,
                quote_to_account=quote_rate,
                next_position_id=next_position_id,
            )
            if position is None:
                skipped_signals.append((signal, "invalid_position"))
                continue
            open_positions[position.id] = position
            swap_totals_by_position[position.id] = 0.0
            components_by_position[position.id] = dict(signal.components)
            next_position_id += 1
            cash -= commission_at_open(
                position.lots,
                float(ftmo_config["commission_per_lot_round_turn"]),
            )
            rule_engine.on_trade_event(position.open_ts)

    else:
        if rule_engine.is_passed():
            outcome = "passed"
        elif timeline and actual_end_ts >= challenge_deadline_ts:
            outcome = "push"
        else:
            outcome = "in_progress"

    if outcome == "in_progress" and rule_engine.is_passed():
        outcome = "passed"
    elif outcome == "in_progress" and actual_end_ts >= challenge_deadline_ts:
        outcome = "push"

    final_bar_ts = actual_end_ts if actual_end_ts in timeline or not timeline else timeline[-1]
    final_open_symbols_with_data = {
        position.symbol
        for position in open_positions.values()
        if final_bar_ts in bars_4h_norm[position.symbol].index
    }
    final_open_positions_with_data = [
        position for position in open_positions.values() if position.symbol in final_open_symbols_with_data
    ]
    final_symbols = final_open_symbols_with_data | {
        symbol for symbol in bars_4h_norm if final_bar_ts in bars_4h_norm[symbol].index
    }
    if final_symbols:
        final_bid, final_ask = _bid_ask_snapshot_at(
            bars_4h_norm,
            bars_1h_norm,
            final_symbols,
            actual_end_ts,
            final_bar_ts,
        )
        final_rates = _rates_snapshot_at(
            bars_4h_norm,
            bars_1h_norm,
            rates_universe,
            actual_end_ts,
            final_bar_ts,
        )
        final_pip_values = {
            symbol: (
                pair_specs[symbol].pip_size
                * pair_specs[symbol].contract_size
                * quote_to_account_rate(symbol, ftmo_config["account_currency"], final_rates)
            )
            for symbol in final_open_symbols_with_data
        }
        final_equity = equity(cash, final_open_positions_with_data, final_bid, final_ask, final_pip_values)
    else:
        final_equity = cash

    equity_curve_full = equity_curve.resample_1h()
    equity_curve_daily = pd.Series(
        [value for _, value in sorted(daily_samples.items())],
        index=pd.DatetimeIndex([ts for ts, _ in sorted(daily_samples.items())]),
        dtype=float,
    )

    return ChallengeResult(
        start_ts=start_ts,
        end_ts=actual_end_ts,
        outcome=outcome,
        failed_by=failed_by,
        target_hit_at=rule_engine.state.target_hit_at,
        trading_days=rule_engine.trading_days_count(),
        final_equity_account_ccy=float(final_equity),
        trades=tuple(trades),
        breaches=tuple(breaches),
        equity_curve=equity_curve_full,
        equity_curve_daily=equity_curve_daily,
        skipped_signals=tuple(skipped_signals),
        rng_seed=rng_seed,
    )



def _run_single_start(args: tuple) -> ChallengeResult:
    (
        bars_4h,
        bars_1h,
        signals,
        atr_by_symbol,
        pair_specs,
        ftmo_config,
        sizing_config,
        swap_rates_by_symbol,
        calendar_provider,
        start_config,
    ) = args
    normalized_4h = {symbol: _normalize_bars(frame) for symbol, frame in bars_4h.items()}
    normalized_1h = {symbol: _normalize_bars(frame) for symbol, frame in bars_1h.items()}
    clipped_4h = {symbol: frame.loc[frame.index <= start_config.end_ts].copy() for symbol, frame in normalized_4h.items()}
    clipped_1h = {symbol: frame.loc[frame.index <= start_config.end_ts].copy() for symbol, frame in normalized_1h.items()}
    clipped_signals = [signal for signal in signals if start_config.start_ts <= signal.timestamp <= start_config.end_ts]
    return run_challenge(
        bars_4h=clipped_4h,
        bars_1h=clipped_1h,
        signals=clipped_signals,
        atr_by_symbol=atr_by_symbol,
        pair_specs=pair_specs,
        ftmo_config=ftmo_config,
        sizing_config=sizing_config,
        swap_rates_by_symbol=swap_rates_by_symbol,
        calendar_provider=calendar_provider,
        start_ts=start_config.start_ts,
        start_equity=float(ftmo_config["initial_balance"]),
        rng_seed=start_config.rng_seed,
    )



def run_n_randomized(
    bars_4h: dict[str, pd.DataFrame],
    bars_1h: dict[str, pd.DataFrame],
    signals: list[Signal],
    atr_by_symbol: dict[str, pd.Series],
    pair_specs: dict[str, PairSpec],
    ftmo_config: dict,
    sizing_config: dict,
    swap_rates_by_symbol: dict,
    calendar_provider: CalendarProvider,
    starts: list[StartConfig],
    *,
    max_workers: Optional[int] = None,
) -> list[ChallengeResult]:
    """Run multiple start configurations in a process pool without shared state."""

    if max_workers == 1:
        return [
            _run_single_start(
                (
                    bars_4h,
                    bars_1h,
                    signals,
                    atr_by_symbol,
                    pair_specs,
                    ftmo_config,
                    sizing_config,
                    swap_rates_by_symbol,
                    calendar_provider,
                    start_config,
                )
            )
            for start_config in starts
        ]

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        return list(
            executor.map(
                _run_single_start,
                [
                    (
                        bars_4h,
                        bars_1h,
                        signals,
                        atr_by_symbol,
                        pair_specs,
                        ftmo_config,
                        sizing_config,
                        swap_rates_by_symbol,
                        calendar_provider,
                        start_config,
                    )
                    for start_config in starts
                ],
            )
        )
