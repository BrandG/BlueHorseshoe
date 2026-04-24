"""Currency flag-bearer cluster filter for multi-pair signals.

When EUR, GBP, and AUD are all strong against CHF on the same H4 bar, three
pairs flag long: EUR_CHF, GBP_CHF, AUD_CHF. Taking all three is one bet on
CHF-weakness with three times the size — not three independent trades. FTMO
risk caps mean we want to keep only the **best expression** of each currency
exposure.

Logic
-----
Each long signal on ``BASE_QUOTE`` expresses two currency exposures:

  - Long the BASE  (positive correlation with BASE strengthening)
  - Short the QUOTE (positive correlation with QUOTE weakening)

For each ``(timestamp, currency, direction)`` triple across the input batch,
the highest-scoring signal expressing that exposure is the **flag-bearer**.

A signal **survives the filter** if it is the flag-bearer for at least ONE
of its two currency exposures. Concretely: EUR_USD survives even if EUR_JPY
beats it on long-EUR — as long as EUR_USD is the best short-USD signal at
that bar. Balanced: dedupes redundant bets without over-suppressing genuinely
independent setups.

Sub-threshold signals are pass-through; the filter only applies among
``above_threshold=True`` candidates. Short signals (direction == -1) flip
the exposure mapping (short-BASE / long-QUOTE).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import pandas as pd

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.indicators.strength import _split_pair


def _exposures(signal: Signal) -> list[tuple[str, int]]:
    """Return ``(currency, direction)`` exposures expressed by this signal.

    direction = +1 → long the currency, -1 → short the currency.
    Returns empty list if the symbol can't be parsed (e.g. metals, indices).
    """
    parts = _split_pair(signal.symbol)
    if parts is None:
        return []
    base, quote = parts
    if signal.direction == 1:
        return [(base, +1), (quote, -1)]
    if signal.direction == -1:
        return [(base, -1), (quote, +1)]
    return []


def _exposure_label(ccy: str, direction: int) -> str:
    return f"{ccy}_{'long' if direction == +1 else 'short'}"


def cluster_filter(
    signals: Iterable[Signal],
    *,
    only_above_threshold: bool = True,
) -> list[Signal]:
    """Apply the currency flag-bearer filter.

    Parameters
    ----------
    signals:
        Input signals. Order is preserved on output (suppressed entries are
        simply absent).
    only_above_threshold:
        When True (default), the filter only applies among signals where
        ``above_threshold`` is True. Sub-threshold signals pass through
        unchanged (they aren't trade candidates anyway).

    Returns
    -------
    list[Signal]
        Kept signals: every sub-threshold signal (if ``only_above_threshold``)
        plus the above-threshold signals that are flag-bearer for at least
        one of their currency exposures.
    """
    sigs = list(signals)
    if not sigs:
        return []

    # Partition: candidates (eligible for filtering) vs. pass-through
    if only_above_threshold:
        candidates = [s for s in sigs if s.above_threshold]
        passthrough_indices = {i for i, s in enumerate(sigs) if not s.above_threshold}
    else:
        candidates = list(sigs)
        passthrough_indices = set()

    # Build flag-bearer index: (timestamp, currency, direction) → best Signal
    best: dict[tuple[datetime, str, int], Signal] = {}
    for s in candidates:
        for ccy, dir_ in _exposures(s):
            key = (s.timestamp, ccy, dir_)
            cur = best.get(key)
            if cur is None or s.score > cur.score:
                best[key] = s

    # A candidate is kept if it IS the best for at least one of its exposures
    kept: list[Signal] = []
    for i, s in enumerate(sigs):
        if i in passthrough_indices:
            kept.append(s)
            continue
        if not s.above_threshold and only_above_threshold:
            kept.append(s)
            continue
        # Skip if symbol unparseable — non-major instruments fall through unfiltered
        exps = _exposures(s)
        if not exps:
            kept.append(s)
            continue
        is_flag_bearer = any(best[(s.timestamp, c, d)] is s for c, d in exps)
        if is_flag_bearer:
            kept.append(s)
    return kept


def explain_cluster_filter(
    signals: Iterable[Signal],
    *,
    only_above_threshold: bool = True,
) -> pd.DataFrame:
    """Return a per-candidate diagnostic DataFrame.

    Columns: ``timestamp``, ``symbol``, ``score``, ``kept``,
    ``flag_bearer_for`` (list of ``"CCY_long"`` / ``"CCY_short"`` labels),
    ``dominated_by`` (mapping of exposure → winning symbol when not flag-bearer).

    Useful for tuning thresholds and understanding why a particular signal
    was suppressed.
    """
    sigs = list(signals)
    if not sigs:
        return pd.DataFrame(
            columns=["timestamp", "symbol", "score", "kept", "flag_bearer_for", "dominated_by"]
        )

    if only_above_threshold:
        candidates = [s for s in sigs if s.above_threshold]
    else:
        candidates = list(sigs)

    best: dict[tuple[datetime, str, int], Signal] = {}
    for s in candidates:
        for ccy, dir_ in _exposures(s):
            key = (s.timestamp, ccy, dir_)
            cur = best.get(key)
            if cur is None or s.score > cur.score:
                best[key] = s

    rows = []
    for s in candidates:
        flag_for: list[str] = []
        dominated_by: dict[str, str] = {}
        for ccy, dir_ in _exposures(s):
            label = _exposure_label(ccy, dir_)
            winner = best[(s.timestamp, ccy, dir_)]
            if winner is s:
                flag_for.append(label)
            else:
                dominated_by[label] = winner.symbol
        rows.append(
            {
                "timestamp": s.timestamp,
                "symbol": s.symbol,
                "score": s.score,
                "kept": bool(flag_for) or not _exposures(s),
                "flag_bearer_for": flag_for,
                "dominated_by": dominated_by,
            }
        )
    return pd.DataFrame(rows)
