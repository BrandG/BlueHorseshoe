"""
Trade metrics calculator — P/L, R-multiple, win rate, expectancy, discipline.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from pymongo.database import Database

logger = logging.getLogger(__name__)


@dataclass
class PortfolioMetrics:
    """Aggregate metrics across all positions."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    avg_r_multiple: float = 0.0
    expectancy: float = 0.0
    avg_hold_days: float = 0.0
    avg_entry_slippage_pct: float = 0.0
    total_pnl: float = 0.0
    total_commission: float = 0.0
    net_pnl: float = 0.0


@dataclass
class StrategyMetrics(PortfolioMetrics):
    """Metrics for a single strategy."""
    strategy: str = ""


@dataclass
class DisciplineMetrics:
    """Execution discipline metrics."""
    ideas_generated: int = 0
    ideas_traded: int = 0
    execution_rate: float = 0.0
    avg_plan_adherence: float = 0.0


class TradeMetricsCalculator:
    """Calculates trade quality metrics from positions and ideas."""

    def __init__(self, database: Database):
        self._db = database
        self._positions = database["trade_positions"]
        self._ideas = database["trade_ideas"]

    def calculate_portfolio_metrics(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> PortfolioMetrics:
        """Calculate metrics across all closed positions in date range."""
        positions = self._query_closed_positions(since, until)
        return self._compute_metrics(positions)

    def calculate_strategy_metrics(
        self,
        strategy: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> StrategyMetrics:
        """Calculate metrics for a single strategy."""
        positions = self._query_closed_positions(since, until, strategy=strategy)
        base = self._compute_metrics(positions)
        return StrategyMetrics(
            strategy=strategy,
            **{k: getattr(base, k) for k in PortfolioMetrics.__dataclass_fields__},
        )

    def calculate_discipline_metrics(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> DisciplineMetrics:
        """Calculate discipline and execution metrics."""
        idea_query: Dict = {}
        pos_query: Dict = {"status": "closed"}

        if since:
            idea_query["batch_date"] = {"$gte": since}
            pos_query.setdefault("opened_at", {})["$gte"] = datetime.strptime(since, "%Y-%m-%d")
        if until:
            idea_query.setdefault("batch_date", {})["$lte"] = until
            pos_query.setdefault("opened_at", {})["$lte"] = datetime.strptime(until, "%Y-%m-%d")

        ideas_count = self._ideas.count_documents(idea_query)
        positions = list(self._positions.find(pos_query, {"_id": 0}))
        traded_count = len(positions)

        # Plan adherence: how close entry was to planned entry
        adherences = []
        for pos in positions:
            planned = pos.get("planned_entry", 0)
            actual = pos.get("actual_entry", 0)
            if planned > 0 and actual > 0:
                pct_off = abs(actual - planned) / planned
                adherence = max(0.0, 1.0 - pct_off * 10)  # 10% off → 0.0
                adherences.append(adherence)

        return DisciplineMetrics(
            ideas_generated=ideas_count,
            ideas_traded=traded_count,
            execution_rate=traded_count / ideas_count if ideas_count > 0 else 0.0,
            avg_plan_adherence=sum(adherences) / len(adherences) if adherences else 0.0,
        )

    @staticmethod
    def calculate_r_multiple(position: dict) -> float:
        """
        R = net_pnl / (risk per share * quantity).
        Risk per share = planned_entry - planned_stop.
        """
        planned_entry = position.get("planned_entry", 0)
        planned_stop = position.get("planned_stop", 0)
        total_pnl = position.get("total_pnl", 0)
        total_commission = position.get("total_commission", 0)
        total_qty = position.get("total_quantity", 0)

        risk_per_share = planned_entry - planned_stop
        if risk_per_share <= 0 or total_qty <= 0:
            return 0.0

        net_pnl = total_pnl - total_commission
        total_risk = risk_per_share * total_qty
        return round(net_pnl / total_risk, 2)

    @staticmethod
    def calculate_slippage(position: dict) -> float:
        """Slippage = (actual_entry - planned_entry) / planned_entry."""
        planned = position.get("planned_entry", 0)
        actual = position.get("actual_entry", 0)
        if planned <= 0:
            return 0.0
        return round((actual - planned) / planned, 6)

    def _query_closed_positions(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> List[dict]:
        query: Dict = {"status": "closed"}
        if strategy:
            query["strategy"] = strategy
        if since:
            query.setdefault("opened_at", {})["$gte"] = datetime.strptime(since, "%Y-%m-%d")
        if until:
            query.setdefault("opened_at", {})["$lte"] = datetime.strptime(until, "%Y-%m-%d")

        return list(self._positions.find(query, {"_id": 0}))

    def _compute_metrics(self, positions: List[dict]) -> PortfolioMetrics:
        """Compute metrics from a list of closed positions."""
        if not positions:
            return PortfolioMetrics()

        wins = []
        losses = []
        r_multiples = []
        hold_days_list = []
        slippages = []
        total_pnl = 0.0
        total_commission = 0.0

        for pos in positions:
            pnl = pos.get("total_pnl", 0)
            commission = pos.get("total_commission", 0)
            net = pnl - commission

            total_pnl += pnl
            total_commission += commission

            if net > 0.005:
                wins.append(net)
            elif net < -0.005:
                losses.append(net)

            r = self.calculate_r_multiple(pos)
            r_multiples.append(r)

            # Hold days from legs
            for leg in pos.get("legs", []):
                hd = leg.get("hold_days", 0)
                if hd > 0:
                    hold_days_list.append(hd)

            slippages.append(self.calculate_slippage(pos))

        n = len(positions)
        n_wins = len(wins)
        n_losses = len(losses)
        n_breakeven = n - n_wins - n_losses

        gross_wins = sum(wins) if wins else 0
        gross_losses = abs(sum(losses)) if losses else 0

        win_rate = n_wins / n if n > 0 else 0
        avg_win = gross_wins / n_wins if n_wins > 0 else 0
        avg_loss = gross_losses / n_losses if n_losses > 0 else 0
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf") if gross_wins > 0 else 0

        loss_rate = n_losses / n if n > 0 else 0
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

        return PortfolioMetrics(
            total_trades=n,
            wins=n_wins,
            losses=n_losses,
            breakeven=n_breakeven,
            win_rate=round(win_rate, 4),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else 999.99,
            avg_r_multiple=round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0,
            expectancy=round(expectancy, 2),
            avg_hold_days=round(sum(hold_days_list) / len(hold_days_list), 1) if hold_days_list else 0,
            avg_entry_slippage_pct=round(sum(slippages) / len(slippages) * 100, 4) if slippages else 0,
            total_pnl=round(total_pnl, 2),
            total_commission=round(total_commission, 2),
            net_pnl=round(total_pnl - total_commission, 2),
        )
