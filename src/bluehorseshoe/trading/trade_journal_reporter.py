"""
Trade journal reporter — generates daily reviews and weekly summaries.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo.database import Database

from bluehorseshoe.trading.trade_metrics import (
    TradeMetricsCalculator,
    PortfolioMetrics,
    DisciplineMetrics,
)
from bluehorseshoe.trading.trade_models import make_review_id

logger = logging.getLogger(__name__)


class TradeJournalReporter:
    """Generates trade review documents and summary reports."""

    def __init__(self, database: Database):
        self._db = database
        self._reviews = database["trade_reviews"]
        self._positions = database["trade_positions"]
        self._ideas = database["trade_ideas"]
        self._metrics = TradeMetricsCalculator(database)
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            self._reviews.create_index(
                [("review_id", 1)], unique=True, name="ux_review_id"
            )
            self._reviews.create_index(
                [("batch_date", 1)], name="ix_review_batch_date"
            )
        except Exception as e:
            logger.warning("Failed to create trade_reviews indexes: %s", e)

    def generate_daily_review(self, target_date: str) -> Dict[str, Any]:
        """
        Create review documents for positions closed on target_date.

        Returns:
            {"reviews_created": N, "positions_reviewed": M, "summary": PortfolioMetrics}
        """
        # Find positions closed on this date
        try:
            date_start = datetime.strptime(target_date, "%Y-%m-%d")
            date_end = date_start + timedelta(days=1)
        except ValueError:
            logger.error("Invalid date format: %s", target_date)
            return {"reviews_created": 0, "positions_reviewed": 0, "summary": PortfolioMetrics()}

        positions = list(self._positions.find({
            "status": "closed",
            "closed_at": {"$gte": date_start, "$lt": date_end},
        }, {"_id": 0}))

        # Also check positions by batch_date via their linked ideas
        if not positions:
            idea_ids = self._ideas.distinct("idea_id", {"batch_date": target_date})
            if idea_ids:
                positions = list(self._positions.find({
                    "idea_id": {"$in": idea_ids},
                    "status": "closed",
                }, {"_id": 0}))

        reviews_created = 0
        for pos in positions:
            try:
                review = self._build_review_doc(pos, target_date)
                self._reviews.update_one(
                    {"review_id": review["review_id"]},
                    {"$set": review},
                    upsert=True,
                )
                reviews_created += 1
            except Exception as e:
                logger.error("Failed to create review for %s: %s",
                             pos.get("position_id", "?"), e)

        # Calculate summary metrics for the day
        summary = self._metrics.calculate_portfolio_metrics(
            since=target_date, until=target_date,
        )

        return {
            "reviews_created": reviews_created,
            "positions_reviewed": len(positions),
            "summary": summary,
        }

    def generate_weekly_summary(self, week_start: str) -> Dict[str, Any]:
        """
        Aggregate metrics for the trading week starting on week_start.

        Returns dict with period, portfolio metrics, per-strategy breakdown,
        discipline metrics, and top winners/losers.
        """
        try:
            start = datetime.strptime(week_start, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid date format: %s", week_start)
            return {}

        end = start + timedelta(days=5)  # Trading week
        end_str = end.strftime("%Y-%m-%d")

        portfolio = self._metrics.calculate_portfolio_metrics(
            since=week_start, until=end_str,
        )

        # Per-strategy breakdown
        strategies = ["baseline", "mean_reversion"]
        by_strategy = []
        for strat in strategies:
            sm = self._metrics.calculate_strategy_metrics(
                strat, since=week_start, until=end_str,
            )
            if sm.total_trades > 0:
                by_strategy.append(sm)

        discipline = self._metrics.calculate_discipline_metrics(
            since=week_start, until=end_str,
        )

        # Top winners/losers
        positions = list(self._positions.find({
            "status": "closed",
            "opened_at": {
                "$gte": start,
                "$lte": end,
            },
        }, {"_id": 0}).sort("total_pnl", -1))

        top_winners = positions[:3] if positions else []
        top_losers = sorted(positions, key=lambda x: x.get("total_pnl", 0))[:3] if positions else []

        return {
            "period": f"{week_start} to {end_str}",
            "portfolio": portfolio,
            "by_strategy": by_strategy,
            "discipline": discipline,
            "top_winners": [
                {"symbol": p.get("symbol"), "strategy": p.get("strategy"),
                 "pnl": p.get("total_pnl", 0)}
                for p in top_winners
            ],
            "top_losers": [
                {"symbol": p.get("symbol"), "strategy": p.get("strategy"),
                 "pnl": p.get("total_pnl", 0)}
                for p in top_losers
            ],
        }

    def _build_review_doc(self, position: dict, batch_date: str) -> dict:
        """Build a trade_reviews document from a closed position."""
        position_id = position.get("position_id", "")
        idea_id = position.get("idea_id", "")
        review_id = make_review_id(position_id)

        planned_entry = position.get("planned_entry", 0)
        actual_entry = position.get("actual_entry", 0)
        planned_stop = position.get("planned_stop", 0)
        planned_target_t2 = position.get("planned_target_t2", 0)

        # Calculate average exit from legs
        legs = position.get("legs", [])
        exit_prices = [leg["exit_price"] for leg in legs if leg.get("exit_price", 0) > 0]
        exit_quantities = [leg["quantity"] for leg in legs if leg.get("exit_price", 0) > 0]
        total_exit_qty = sum(exit_quantities) if exit_quantities else 0
        actual_exit_avg = (
            sum(p * q for p, q in zip(exit_prices, exit_quantities)) / total_exit_qty
            if total_exit_qty > 0 else 0
        )

        total_pnl = position.get("total_pnl", 0)
        total_commission = position.get("total_commission", 0)
        net_pnl = total_pnl - total_commission

        r_multiple = self._metrics.calculate_r_multiple(position)
        slippage = self._metrics.calculate_slippage(position)

        # Hold days (max across legs)
        hold_days = max((leg.get("hold_days", 0) for leg in legs), default=0)

        # Outcome
        if net_pnl > 0.005:
            outcome = "win"
        elif net_pnl < -0.005:
            outcome = "loss"
        else:
            outcome = "breakeven"

        # T1/T2/Stop tracking
        t1_hit = any(leg.get("close_reason") == "take_profit_t1" for leg in legs)
        t2_hit = any(leg.get("close_reason") == "take_profit_t2" for leg in legs)
        stop_hit = any(leg.get("close_reason") == "stop_loss" for leg in legs)

        # Discipline score
        discipline_score = 1.0
        if planned_entry > 0 and actual_entry > 0:
            entry_off = abs(actual_entry - planned_entry) / planned_entry
            if entry_off > 0.01:
                discipline_score -= min(0.3, entry_off * 10)

        followed_plan = discipline_score >= 0.8

        now = datetime.now(timezone.utc)
        return {
            "review_id": review_id,
            "position_id": position_id,
            "idea_id": idea_id,
            "symbol": position.get("symbol", ""),
            "strategy": position.get("strategy", ""),
            "batch_date": batch_date,
            "planned_entry": planned_entry,
            "actual_entry": actual_entry,
            "planned_stop": planned_stop,
            "planned_target_t2": planned_target_t2,
            "actual_exit_avg": round(actual_exit_avg, 4),
            "gross_pnl": round(total_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "r_multiple": r_multiple,
            "entry_slippage_pct": round(slippage * 100, 4),
            "hold_days": hold_days,
            "outcome": outcome,
            "t1_hit": t1_hit,
            "t2_hit": t2_hit,
            "stop_hit": stop_hit,
            "followed_plan": followed_plan,
            "discipline_score": round(discipline_score, 2),
            "tags": [],
            "notes": "",
            "lessons_learned": "",
            "created_at": now,
            "updated_at": now,
        }

    # ── Console output ─────────────────────────────────────────────────

    def print_daily_review(self, data: Dict[str, Any]) -> None:
        """Print formatted daily review to console."""
        summary = data.get("summary", PortfolioMetrics())
        print(f"\n{'='*60}")
        print(f"  DAILY TRADE REVIEW")
        print(f"{'='*60}")
        print(f"  Positions reviewed: {data.get('positions_reviewed', 0)}")
        print(f"  Reviews created:    {data.get('reviews_created', 0)}")

        if summary.total_trades > 0:
            print(f"\n  --- Performance ---")
            print(f"  Trades:     {summary.total_trades} ({summary.wins}W / {summary.losses}L / {summary.breakeven}BE)")
            print(f"  Win rate:   {summary.win_rate:.1%}")
            print(f"  Net P/L:    ${summary.net_pnl:+.2f}")
            print(f"  Avg R:      {summary.avg_r_multiple:+.2f}")
            print(f"  Expectancy: ${summary.expectancy:+.2f}")
        print(f"{'='*60}\n")

    def print_weekly_summary(self, data: Dict[str, Any]) -> None:
        """Print formatted weekly summary to console."""
        portfolio = data.get("portfolio", PortfolioMetrics())
        discipline = data.get("discipline", DisciplineMetrics())

        print(f"\n{'='*60}")
        print(f"  WEEKLY TRADE SUMMARY — {data.get('period', 'N/A')}")
        print(f"{'='*60}")

        print(f"\n  --- Portfolio ---")
        print(f"  Total trades: {portfolio.total_trades}")
        print(f"  Win rate:     {portfolio.win_rate:.1%}")
        print(f"  Net P/L:      ${portfolio.net_pnl:+.2f}")
        print(f"  Profit factor:{portfolio.profit_factor:.2f}")
        print(f"  Avg R:        {portfolio.avg_r_multiple:+.2f}")
        print(f"  Expectancy:   ${portfolio.expectancy:+.2f}")
        print(f"  Avg hold:     {portfolio.avg_hold_days:.1f} days")

        for sm in data.get("by_strategy", []):
            print(f"\n  --- {sm.strategy} ---")
            print(f"  Trades: {sm.total_trades} | Win: {sm.win_rate:.0%} | Net: ${sm.net_pnl:+.2f} | Avg R: {sm.avg_r_multiple:+.2f}")

        print(f"\n  --- Discipline ---")
        print(f"  Ideas generated: {discipline.ideas_generated}")
        print(f"  Ideas traded:    {discipline.ideas_traded}")
        print(f"  Execution rate:  {discipline.execution_rate:.1%}")
        print(f"  Plan adherence:  {discipline.avg_plan_adherence:.1%}")

        winners = data.get("top_winners", [])
        losers = data.get("top_losers", [])
        if winners:
            print(f"\n  --- Top Winners ---")
            for w in winners:
                if w.get("pnl", 0) > 0:
                    print(f"  {w['symbol']} ({w['strategy']}): ${w['pnl']:+.2f}")
        if losers:
            print(f"\n  --- Top Losers ---")
            for l in losers:
                if l.get("pnl", 0) < 0:
                    print(f"  {l['symbol']} ({l['strategy']}): ${l['pnl']:+.2f}")

        print(f"{'='*60}\n")
