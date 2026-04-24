"""Validation for OANDA candles (pre-ingestion) and stored FX bars (post-ingestion).

Two entry points:

- :func:`validate_candles` — sanity-check a list of OANDA v20 BA-format candles
  before ingestion. Catches: missing bid/ask, duplicate timestamps, out-of-order
  timestamps, OHLC invariant violations, inverted spreads.

- :func:`validate_stored` — audit what's already in an :class:`FxStore` over a
  date range. Uses :func:`fx_time_utils.classify_gaps` for gap classification
  and re-checks OHLC/spread invariants.

Returns a list of :class:`ValidationIssue`. An empty list means clean.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import pandas as pd

from bh_ftmo.data.fx_store import FxStore, Granularity, _parse_rfc3339
from bh_ftmo.data.fx_time_utils import BarGapKind, classify_gaps


class IssueKind(str, Enum):
    MISSING_BID_ASK = "missing_bid_ask"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    INVALID_OHLC = "invalid_ohlc"
    INVERTED_SPREAD = "inverted_spread"
    DATA_GAP = "data_gap"
    US_HOLIDAY_GAP = "us_holiday_gap"
    UK_HOLIDAY_GAP = "uk_holiday_gap"


@dataclass(frozen=True)
class ValidationIssue:
    kind: IssueKind
    symbol: str
    timestamp: Optional[datetime]
    detail: str


def _check_ohlc_sanity(
    symbol: str,
    timestamp: datetime,
    o: float,
    h: float,
    l: float,
    c: float,
    side: str,
) -> Optional[ValidationIssue]:
    """Return an issue if OHLC invariants are violated, else ``None``.

    Invariants: ``h >= max(o, l, c)`` and ``l <= min(o, h, c)``.
    """
    if h < max(o, l, c) or l > min(o, h, c):
        return ValidationIssue(
            kind=IssueKind.INVALID_OHLC,
            symbol=symbol,
            timestamp=timestamp,
            detail=f"{side}: o={o} h={h} l={l} c={c}",
        )
    return None


def _check_spread(
    symbol: str,
    timestamp: datetime,
    bid: dict,
    ask: dict,
) -> Optional[ValidationIssue]:
    """Return an issue if any ask OHLC is below the corresponding bid."""
    for key in ("o", "h", "l", "c"):
        if float(ask[key]) < float(bid[key]):
            return ValidationIssue(
                kind=IssueKind.INVERTED_SPREAD,
                symbol=symbol,
                timestamp=timestamp,
                detail=f"ask[{key}]={ask[key]} < bid[{key}]={bid[key]}",
            )
    return None


def validate_candles(
    candles: list[dict[str, Any]],
    *,
    symbol: str,
) -> list[ValidationIssue]:
    """Validate raw OANDA candles pre-ingestion.

    Does **not** check gaps — that requires a known date range and is handled
    by :func:`validate_stored` (or callers can run :func:`classify_gaps` directly).
    """
    issues: list[ValidationIssue] = []
    seen: set[datetime] = set()
    last_ts: Optional[datetime] = None

    for idx, candle in enumerate(candles):
        time_str = candle.get("time")
        if not time_str:
            issues.append(
                ValidationIssue(
                    kind=IssueKind.MISSING_BID_ASK,
                    symbol=symbol,
                    timestamp=None,
                    detail=f"candle[{idx}] missing 'time'",
                )
            )
            continue
        try:
            ts = _parse_rfc3339(time_str)
        except ValueError as exc:
            issues.append(
                ValidationIssue(
                    kind=IssueKind.MISSING_BID_ASK,
                    symbol=symbol,
                    timestamp=None,
                    detail=f"candle[{idx}] unparseable time {time_str!r}: {exc}",
                )
            )
            continue

        if ts in seen:
            issues.append(
                ValidationIssue(
                    kind=IssueKind.DUPLICATE,
                    symbol=symbol,
                    timestamp=ts,
                    detail=f"candle[{idx}] duplicates a prior timestamp",
                )
            )
        seen.add(ts)

        if last_ts is not None and ts < last_ts:
            issues.append(
                ValidationIssue(
                    kind=IssueKind.OUT_OF_ORDER,
                    symbol=symbol,
                    timestamp=ts,
                    detail=f"candle[{idx}] ts={ts} precedes prior ts={last_ts}",
                )
            )
        last_ts = ts

        bid = candle.get("bid")
        ask = candle.get("ask")
        if not bid or not ask:
            issues.append(
                ValidationIssue(
                    kind=IssueKind.MISSING_BID_ASK,
                    symbol=symbol,
                    timestamp=ts,
                    detail=f"candle[{idx}] missing bid or ask (requires price='BA')",
                )
            )
            continue

        try:
            bid_o = float(bid["o"]); bid_h = float(bid["h"])
            bid_l = float(bid["l"]); bid_c = float(bid["c"])
            ask_o = float(ask["o"]); ask_h = float(ask["h"])
            ask_l = float(ask["l"]); ask_c = float(ask["c"])
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(
                ValidationIssue(
                    kind=IssueKind.MISSING_BID_ASK,
                    symbol=symbol,
                    timestamp=ts,
                    detail=f"candle[{idx}] non-numeric OHLC: {exc}",
                )
            )
            continue

        issue = _check_ohlc_sanity(symbol, ts, bid_o, bid_h, bid_l, bid_c, side="bid")
        if issue:
            issues.append(issue)
        issue = _check_ohlc_sanity(symbol, ts, ask_o, ask_h, ask_l, ask_c, side="ask")
        if issue:
            issues.append(issue)

        spread_issue = _check_spread(symbol, ts, bid, ask)
        if spread_issue:
            issues.append(spread_issue)

    return issues


_GAP_KIND_TO_ISSUE: dict[BarGapKind, IssueKind] = {
    BarGapKind.DATA_GAP: IssueKind.DATA_GAP,
    BarGapKind.US_HOLIDAY: IssueKind.US_HOLIDAY_GAP,
    BarGapKind.UK_HOLIDAY: IssueKind.UK_HOLIDAY_GAP,
    # BarGapKind.WEEKEND is filtered by expected_* and shouldn't appear here.
}


def validate_stored(
    store: FxStore,
    *,
    symbol: str,
    granularity: Granularity,
    start: datetime,
    end: datetime,
    include_holiday_gaps: bool = False,
) -> list[ValidationIssue]:
    """Audit stored bars in ``[start, end)`` for gaps and invariant violations.

    Gaps are classified via :func:`fx_time_utils.classify_gaps`. Holiday-attributed
    gaps are informational only and excluded unless ``include_holiday_gaps=True``.
    Only ``DATA_GAP`` is actionable.
    """
    issues: list[ValidationIssue] = []
    df = store.load(symbol, granularity=granularity, start=start, end=end, include_incomplete=True)

    observed = [ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts for ts in df["timestamp"]] if len(df) else []
    gaps = classify_gaps(observed, start_utc=start, end_utc=end, granularity=granularity)
    for g in gaps:
        issue_kind = _GAP_KIND_TO_ISSUE.get(g.kind)
        if issue_kind is None:
            continue  # weekend (shouldn't happen) — skip
        if issue_kind != IssueKind.DATA_GAP and not include_holiday_gaps:
            continue
        issues.append(
            ValidationIssue(
                kind=issue_kind,
                symbol=symbol,
                timestamp=g.timestamp,
                detail=f"expected bar missing ({g.kind.value})",
            )
        )

    # Row-level invariants (defense in depth; FxStore writes are already validated)
    for row in df.itertuples(index=False):
        ts = row.timestamp.to_pydatetime() if isinstance(row.timestamp, pd.Timestamp) else row.timestamp
        issue = _check_ohlc_sanity(
            symbol, ts, row.open_bid, row.high_bid, row.low_bid, row.close_bid, side="bid"
        )
        if issue:
            issues.append(issue)
        issue = _check_ohlc_sanity(
            symbol, ts, row.open_ask, row.high_ask, row.low_ask, row.close_ask, side="ask"
        )
        if issue:
            issues.append(issue)
        for key, bid_v, ask_v in (
            ("o", row.open_bid, row.open_ask),
            ("h", row.high_bid, row.high_ask),
            ("l", row.low_bid, row.low_ask),
            ("c", row.close_bid, row.close_ask),
        ):
            if ask_v < bid_v:
                issues.append(
                    ValidationIssue(
                        kind=IssueKind.INVERTED_SPREAD,
                        symbol=symbol,
                        timestamp=ts,
                        detail=f"ask[{key}]={ask_v} < bid[{key}]={bid_v}",
                    )
                )
                break

    return issues


def summarize_issues(issues: list[ValidationIssue]) -> dict[IssueKind, int]:
    """Return ``{kind: count}`` for a quick log line."""
    counts: dict[IssueKind, int] = {}
    for i in issues:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    return counts
