"""Multi-strategy comparison harness for Phase 3 gate evaluation."""

from __future__ import annotations

# pylint: disable=too-many-arguments,too-many-positional-arguments

from typing import Optional

import pandas as pd

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.baselines import (
    MondayInFridayOutStrategy,
    RandomEntryAtrExitStrategy,
    SimpleRsi14Strategy,
)
from bh_ftmo.backtest.calendar_provider import CalendarProvider, NullCalendarProvider
from bh_ftmo.backtest.engine import StartConfig, run_n_randomized
from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.types import ChallengeResult, PairSpec


def run_strategy_cohort(
    strategy_name: str,
    signals: list[Signal],
    bars_4h: dict[str, pd.DataFrame],
    bars_1h: dict[str, pd.DataFrame],
    atr_by_symbol: dict[str, pd.Series],
    pair_specs: dict[str, PairSpec],
    ftmo_config: dict,
    sizing_config: dict,
    swap_rates_by_symbol: dict[str, SwapRates],
    calendar_provider: CalendarProvider,
    starts: list[StartConfig],
    *,
    max_workers: Optional[int] = None,
    risk_overlay_config: Optional[dict[str, dict]] = None,
) -> list[ChallengeResult]:
    """Run one strategy's signals over a shared randomized-start cohort."""

    del strategy_name
    return run_n_randomized(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr_by_symbol,
        pair_specs=pair_specs,
        ftmo_config=ftmo_config,
        sizing_config=sizing_config,
        swap_rates_by_symbol=swap_rates_by_symbol,
        calendar_provider=calendar_provider,
        starts=starts,
        max_workers=max_workers,
        risk_overlay_config=risk_overlay_config,
    )


def run_full_comparison(
    bars_4h: dict[str, pd.DataFrame],
    bars_1h: dict[str, pd.DataFrame],
    atr_by_symbol: dict[str, pd.Series],
    pair_specs: dict[str, PairSpec],
    ftmo_config: dict,
    sizing_config: dict,
    swap_rates_by_symbol: dict[str, SwapRates],
    bh_ftmo_signals: list[Signal],
    starts: list[StartConfig],
    *,
    rng_seed: int = 0,
    max_workers: Optional[int] = None,
    risk_overlay_config: Optional[dict[str, dict]] = None,
) -> dict[str, list[ChallengeResult]]:
    """Run BH FTMO plus the three locked baselines over identical starts."""

    symbols = tuple(sorted(bars_4h))
    if not symbols:
        raise ValueError('bars_4h must not be empty')

    monday_symbol = 'EUR_USD' if 'EUR_USD' in bars_4h else symbols[0]
    calendar_provider = NullCalendarProvider()
    strategy_inputs = {
        'bh_ftmo': bh_ftmo_signals,
        'random_baseline': RandomEntryAtrExitStrategy(seed=rng_seed, symbols=symbols).generate_signals(bars_4h),
        'monday_friday': MondayInFridayOutStrategy(symbol=monday_symbol).generate_signals(bars_4h),
        'rsi_14': SimpleRsi14Strategy(symbols=symbols).generate_signals(bars_4h),
    }
    return {
        strategy_name: run_strategy_cohort(
            strategy_name,
            signals,
            bars_4h,
            bars_1h,
            atr_by_symbol,
            pair_specs,
            ftmo_config,
            sizing_config,
            swap_rates_by_symbol,
            calendar_provider,
            starts,
            max_workers=max_workers,
            risk_overlay_config=risk_overlay_config if strategy_name == "bh_ftmo" else None,
        )
        for strategy_name, signals in strategy_inputs.items()
    }
