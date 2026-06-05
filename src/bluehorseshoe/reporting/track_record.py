"""Signal Track Record — aggregates matured hypothetical-trade outcomes.

Reads `journal_hypothetical_trades` (populated by the hypothesis engine) and
rolls recent matured signals up into the metrics the daily report surfaces:
entry rate, win rate, average P&L, alpha vs SPY, and profit factor — at two
rank-depth tiers and split by strategy.

Pure data layer: returns plain dicts so `html_reporter` can render the same
numbers into the standard, email, and arcade reports without re-querying.

Field notes (verified against the collection):
- `rank` is **per-strategy** — rank<=10 selects the top 10 baseline *and* the
  top 10 mean-reversion picks (the depth actually traded).
- `outcome` ∈ {WIN, LOSS, TIMEOUT, NOT_ENTERED}; NOT_ENTERED never opened a
  position (price didn't reach the adjusted entry) and is excluded from
  performance, but counts toward entry rate.
- `pnl_pct` / `alpha_pct` are fractions (-0.0211 == -2.11%).

Only matured batches are ever present here (the engine evaluates a batch in
one shot once it matures), so the recency window can't be polluted by
half-finished batches — only by genuinely older eras, which the lookback
window excludes.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# A rolling window keeps the report on *recent* behavior and structurally
# excludes the 2022 score-backfill replay era (and the Feb-2026 crash regime).
DEFAULT_LOOKBACK_DAYS = 60
DEFAULT_TIERS = (10, 50)
TOP_MOVERS = 5

_ENTERED = ("WIN", "LOSS", "TIMEOUT")


def _window_start(as_of_date: str, lookback_days: int) -> str:
    day = _dt.date.fromisoformat(as_of_date[:10])
    return (day - _dt.timedelta(days=lookback_days)).isoformat()


def _mean(rows: List[dict], key: str) -> float:
    return (sum((r.get(key) or 0) for r in rows) / len(rows)) if rows else 0.0


def _metrics(rows: List[dict]) -> Dict[str, Any]:
    """Performance summary for one group of signals."""
    total = len(rows)
    entered = [r for r in rows if r.get("outcome") in _ENTERED]
    n_ent = len(entered)
    wins = [r for r in entered if (r.get("pnl_pct") or 0) > 0]
    gross_win = sum((r.get("pnl_pct") or 0) for r in wins)
    gross_loss = sum((r.get("pnl_pct") or 0) for r in entered if (r.get("pnl_pct") or 0) < 0)

    if gross_loss < 0:
        profit_factor: Optional[float] = gross_win / abs(gross_loss)
    elif gross_win > 0:
        profit_factor = None  # no losers — render as ∞
    else:
        profit_factor = 0.0

    return {
        "total": total,
        "entered": n_ent,
        "not_entered": total - n_ent,
        "entry_rate": (n_ent / total) if total else 0.0,
        "wins": len(wins),
        "win_rate": (len(wins) / n_ent) if n_ent else 0.0,
        "target_hits": sum(1 for r in entered if r.get("outcome") == "WIN"),
        "stops": sum(1 for r in entered if r.get("outcome") == "LOSS"),
        "timeouts": sum(1 for r in entered if r.get("outcome") == "TIMEOUT"),
        "avg_pnl_pct": _mean(entered, "pnl_pct") * 100,
        "avg_alpha_pct": _mean(entered, "alpha_pct") * 100,
        "profit_factor": profit_factor,
        "avg_days_held": _mean(entered, "days_held"),
    }


def compute_track_record(
    database,
    as_of_date: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    tiers=DEFAULT_TIERS,
) -> Optional[Dict[str, Any]]:
    """Roll recent matured signals into report-ready track-record metrics.

    Returns None when there's no database or no matured signals in the window
    (callers render an "accumulating" placeholder rather than an empty table).
    """
    if database is None:
        return None

    tiers = tuple(sorted(set(tiers)))
    start = _window_start(as_of_date, lookback_days)
    max_tier = max(tiers)

    try:
        rows = list(database["journal_hypothetical_trades"].find(
            {"batch_date": {"$gte": start, "$lte": as_of_date}, "rank": {"$lte": max_tier}},
            {"_id": 0, "batch_date": 1, "symbol": 1, "strategy": 1, "rank": 1,
             "outcome": 1, "pnl_pct": 1, "alpha_pct": 1, "days_held": 1, "composite_score": 1},
        ))
    except Exception as exc:  # never let a report die on a journal query
        logger.warning("Track record query failed (%s); section will be skipped.", exc)
        return None

    if not rows:
        return None

    batch_dates = sorted({r["batch_date"] for r in rows})
    result: Dict[str, Any] = {
        "window": {
            "start": start,
            "end": as_of_date,
            "lookback_days": lookback_days,
            "n_batches": len(batch_dates),
            "first_batch": batch_dates[0],
            "last_batch": batch_dates[-1],
        },
        "tiers": {},
    }

    for n in tiers:
        tier_rows = [r for r in rows if (r.get("rank") or 10**9) <= n]
        result["tiers"][n] = {
            "overall": _metrics(tier_rows),
            "baseline": _metrics([r for r in tier_rows if r.get("strategy") == "baseline"]),
            "mean_reversion": _metrics([r for r in tier_rows if r.get("strategy") == "mean_reversion"]),
        }

    # Best/worst entered trades from the tightest (most decision-relevant) tier.
    tight = tiers[0]
    entered_tight = [
        r for r in rows
        if (r.get("rank") or 10**9) <= tight and r.get("outcome") in _ENTERED
    ]
    by_pnl = sorted(entered_tight, key=lambda r: (r.get("pnl_pct") or 0))
    result["tight_tier"] = tight
    result["top_losers"] = by_pnl[:TOP_MOVERS]
    result["top_winners"] = list(reversed(by_pnl[-TOP_MOVERS:]))
    return result
