"""Multi-pair signal generator — runs strategies across many pairs at once.

The generator's job is to:

1. Build the **shared context** once per run:
     - synthesized DXY series (from the six ICE constituent pairs)
     - currency strength frame (across as many majors-pairs as available)
2. Run every configured strategy across every pair, passing the shared
   context. Each strategy returns one :class:`Signal` per bar.
3. Return a flat ``list[Signal]`` (or a tidy DataFrame view via
   :meth:`SignalGenerator.to_dataframe`).

Context is **best-effort**: if the six ICE-DXY constituents aren't all
present in the input, DXY is ``None``; if fewer than four pairs are
present, strengths is ``None``. Strategies handle absent context gracefully
by simply not firing the corresponding rules.

Why a class and not a function: it keeps the strategy list and configurable
DXY/strength pair sets in one place, and lets future code attach per-run
caches if profiling shows that helps.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

import pandas as pd

from bh_ftmo.analysis.strategy import BaselineStrategy, Signal
from bh_ftmo.indicators import (
    DXY_WEIGHTS,
    currency_strength,
    synthesize_dxy,
)

# Default majors-pair universe used when computing currency strength.
# Includes USD-base/quote pairs plus the major crosses so every G8 currency
# appears in at least three pairs.
DEFAULT_STRENGTH_PAIRS: tuple[str, ...] = (
    "EUR_USD", "GBP_USD", "AUD_USD", "NZD_USD",
    "USD_JPY", "USD_CHF", "USD_CAD",
    "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD", "EUR_CAD",
    "GBP_JPY", "GBP_CHF", "GBP_CAD",
    "AUD_JPY", "AUD_NZD", "NZD_JPY",
    "CHF_JPY", "CAD_JPY",
)

DXY_CONSTITUENTS: tuple[str, ...] = tuple(DXY_WEIGHTS.keys())

MIN_STRENGTH_PAIRS: int = 4


def _timestamp_indexed_close(pair_df: pd.DataFrame) -> pd.DataFrame:
    """Return a 1-col DataFrame with mid close indexed by the pair's timestamps.

    Both :func:`synthesize_dxy` and :func:`currency_strength` use the input
    DataFrame's index to build their output index; we want timestamps so that
    downstream strategies can look up context values by ``.loc[ts]``.
    """
    if "close_bid" in pair_df.columns and "close_ask" in pair_df.columns:
        close = (pair_df["close_bid"] + pair_df["close_ask"]) / 2.0
    elif "close" in pair_df.columns:
        close = pair_df["close"]
    else:
        raise ValueError("pair_df needs 'close' or 'close_bid'+'close_ask'")
    return pd.DataFrame({"close": close.values}, index=pd.DatetimeIndex(pair_df["timestamp"]))


@dataclass(frozen=True)
class SignalContext:
    """Shared context for one generator run — exposed for diagnostics."""

    dxy: Optional[pd.Series]
    strengths: Optional[pd.DataFrame]
    dxy_pairs_used: tuple[str, ...]
    strength_pairs_used: tuple[str, ...]


class SignalGenerator:
    """Drive one or more strategies across a multi-pair universe."""

    def __init__(
        self,
        strategies: Optional[Sequence] = None,
        *,
        dxy_pairs: Sequence[str] = DXY_CONSTITUENTS,
        strength_pairs: Sequence[str] = DEFAULT_STRENGTH_PAIRS,
        strength_lookback: int = 14,
    ) -> None:
        self.strategies = list(strategies) if strategies is not None else [BaselineStrategy()]
        self.dxy_pairs = tuple(dxy_pairs)
        self.strength_pairs = tuple(strength_pairs)
        self.strength_lookback = strength_lookback

    # ---- context builders ------------------------------------------------

    def _build_dxy(self, pair_dfs: dict[str, pd.DataFrame]) -> tuple[Optional[pd.Series], tuple[str, ...]]:
        missing = [p for p in self.dxy_pairs if p not in pair_dfs]
        if missing:
            return None, ()
        inputs = {p: _timestamp_indexed_close(pair_dfs[p]) for p in self.dxy_pairs}
        return synthesize_dxy(inputs), self.dxy_pairs

    def _build_strengths(
        self, pair_dfs: dict[str, pd.DataFrame]
    ) -> tuple[Optional[pd.DataFrame], tuple[str, ...]]:
        present = tuple(p for p in self.strength_pairs if p in pair_dfs)
        if len(present) < MIN_STRENGTH_PAIRS:
            return None, ()
        inputs = {p: _timestamp_indexed_close(pair_dfs[p]) for p in present}
        return currency_strength(inputs, lookback=self.strength_lookback), present

    def build_context(self, pair_dfs: dict[str, pd.DataFrame]) -> SignalContext:
        dxy, dxy_pairs = self._build_dxy(pair_dfs)
        strengths, str_pairs = self._build_strengths(pair_dfs)
        return SignalContext(dxy=dxy, strengths=strengths, dxy_pairs_used=dxy_pairs, strength_pairs_used=str_pairs)

    # ---- generation ------------------------------------------------------

    def generate(
        self,
        pair_dfs: dict[str, pd.DataFrame],
        *,
        symbols: Optional[Iterable[str]] = None,
    ) -> list[Signal]:
        """Score every supplied pair under every configured strategy.

        ``symbols`` optionally restricts which pairs to actually score (the
        full ``pair_dfs`` dict is still used to build the shared context, so
        a single-pair scoring run can still benefit from DXY/strength built
        from the broader universe).
        """
        ctx = self.build_context(pair_dfs)
        targets = list(symbols) if symbols is not None else list(pair_dfs.keys())
        out: list[Signal] = []
        for sym in targets:
            df = pair_dfs.get(sym)
            if df is None or len(df) == 0:
                continue
            for strat in self.strategies:
                out.extend(
                    strat.score_pair(df, symbol=sym, dxy=ctx.dxy, strengths=ctx.strengths)
                )
        return out

    def generate_from_store(
        self,
        store,
        symbols: Sequence[str],
        *,
        granularity: str = "H4",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        context_symbols: Optional[Sequence[str]] = None,
    ) -> list[Signal]:
        """Convenience wrapper: load pairs from an :class:`FxStore` and generate.

        ``context_symbols`` lets you load extra pairs purely to enrich the
        DXY/strength context without scoring them. Defaults to the union of
        ``symbols``, ``self.dxy_pairs``, and ``self.strength_pairs``.
        """
        if context_symbols is None:
            context_symbols = sorted(set(symbols) | set(self.dxy_pairs) | set(self.strength_pairs))
        pair_dfs: dict[str, pd.DataFrame] = {}
        for sym in context_symbols:
            try:
                df = store.load(sym, granularity=granularity, start=start, end=end)
            except Exception:  # noqa: BLE001
                continue
            if len(df) > 0:
                pair_dfs[sym] = df
        return self.generate(pair_dfs, symbols=symbols)

    # ---- presentation ----------------------------------------------------

    @staticmethod
    def to_dataframe(signals: Sequence[Signal]) -> pd.DataFrame:
        """Flatten a sequence of :class:`Signal` into a tidy DataFrame.

        Columns: ``timestamp``, ``symbol``, ``strategy``, ``direction``,
        ``score``, ``above_threshold``, ``components`` (dict).
        """
        rows = [
            {
                "timestamp": s.timestamp,
                "symbol": s.symbol,
                "strategy": s.strategy,
                "direction": s.direction,
                "score": s.score,
                "above_threshold": s.above_threshold,
                "components": s.components,
            }
            for s in signals
        ]
        return pd.DataFrame(rows)
