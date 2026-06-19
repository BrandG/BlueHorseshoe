"""
Trade journal data models — normalized shapes for the full trade lifecycle.

Collections:
    trade_ideas     — What BlueHorseshoe intended to trade (top N candidates)
    trade_orders    — Orders submitted to the broker (per leg)
    trade_fills     — Actual executions (source of truth)
    trade_positions — Synthesized from fills, with T1/T2 legs
    trade_reviews   — Journal layer with plan-vs-actual metrics
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ── ID Helpers ────────────────────────────────────────────────────────

STRATEGY_DISPLAY_TO_INTERNAL = {
    "Baseline": "baseline",
    "MeanRev": "mean_reversion",
    "Connors": "connors",
    "RangeSupport": "range_support",   # so idea_id reads idea_<date>_<sym>_range_support
}


def normalize_strategy(strategy: str) -> str:
    """Convert display name ('Baseline', 'MeanRev') to internal name."""
    return STRATEGY_DISPLAY_TO_INTERNAL.get(strategy, strategy.lower().replace(" ", "_"))


def make_idea_id(date: str, symbol: str, strategy: str) -> str:
    """Stable deterministic ID for a trade idea."""
    return f"idea_{date}_{symbol}_{normalize_strategy(strategy)}"


def make_order_ref(idea_id: str, leg: str) -> str:
    """Stable order reference linking to idea + leg."""
    return f"order_{idea_id}_{leg}"


def make_position_id(idea_id: str) -> str:
    """Stable position ID derived from the originating idea."""
    return f"pos_{idea_id}"


def make_review_id(position_id: str) -> str:
    """Stable review ID derived from the position."""
    return f"review_{position_id}"


# ── Dataclasses ───────────────────────────────────────────────────────

@dataclass
class TradeIdea:
    """What BlueHorseshoe intended to trade — top N actionable candidates."""
    idea_id: str
    batch_date: str
    symbol: str
    strategy: str
    rank: int
    composite_score: float
    ml_win_probability: float
    signal_strength: str
    entry_price: float
    stop_loss: float
    take_profit_t1: float
    take_profit_t2: float
    risk_reward_ratio: float
    position_size_shares: int = 0
    position_size_dollars: float = 0.0
    components: Dict[str, float] = field(default_factory=dict)
    sentiment: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_doc(self) -> dict:
        """Convert to MongoDB document."""
        return {
            "idea_id": self.idea_id,
            "batch_date": self.batch_date,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "rank": self.rank,
            "composite_score": self.composite_score,
            "ml_win_probability": self.ml_win_probability,
            "signal_strength": self.signal_strength,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit_t1": self.take_profit_t1,
            "take_profit_t2": self.take_profit_t2,
            "risk_reward_ratio": self.risk_reward_ratio,
            "position_size_shares": self.position_size_shares,
            "position_size_dollars": self.position_size_dollars,
            "components": self.components,
            "sentiment": self.sentiment,
            "created_at": self.created_at,
        }


@dataclass
class TradeOrder:
    """An order submitted to the broker, one per leg (T1 or T2)."""
    order_ref: str
    idea_id: str
    symbol: str
    leg: str  # "T1" or "T2"
    broker_order_ids: List[int] = field(default_factory=list)
    quantity: int = 0
    limit_price: float = 0.0
    take_profit_price: float = 0.0
    stop_loss_price: float = 0.0
    status: str = "submitted"  # submitted, filled, cancelled, error
    error: Optional[str] = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_doc(self) -> dict:
        """Convert to MongoDB document."""
        return {
            "order_ref": self.order_ref,
            "idea_id": self.idea_id,
            "symbol": self.symbol,
            "leg": self.leg,
            "broker_order_ids": self.broker_order_ids,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "take_profit_price": self.take_profit_price,
            "stop_loss_price": self.stop_loss_price,
            "status": self.status,
            "error": self.error,
            "submitted_at": self.submitted_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TradeFill:
    """An actual execution from the broker — source of truth."""
    fill_id: str
    symbol: str
    side: str = "buy"  # buy or sell
    quantity: int = 0
    price: float = 0.0
    commission: float = 0.0
    exec_time: Optional[datetime] = None
    exec_id: str = ""
    order_ref: Optional[str] = None
    idea_id: Optional[str] = None
    source: str = "ibkr"  # ibkr, csv, manual
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_doc(self) -> dict:
        """Convert to MongoDB document."""
        return {
            "fill_id": self.fill_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "commission": self.commission,
            "exec_time": self.exec_time,
            "exec_id": self.exec_id,
            "order_ref": self.order_ref,
            "idea_id": self.idea_id,
            "source": self.source,
            "created_at": self.created_at,
        }


@dataclass
class PositionLeg:
    """One leg of a position (T1 or T2)."""
    leg: str  # "T1" or "T2"
    quantity: int = 0
    entry_fill_id: Optional[str] = None
    exit_fill_id: Optional[str] = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    close_reason: Optional[str] = None  # take_profit_t1, take_profit_t2, stop_loss, timeout, manual
    pnl: float = 0.0
    r_multiple: float = 0.0
    hold_days: int = 0

    def to_doc(self) -> dict:
        """Convert to MongoDB-embeddable dict."""
        return {
            "leg": self.leg,
            "quantity": self.quantity,
            "entry_fill_id": self.entry_fill_id,
            "exit_fill_id": self.exit_fill_id,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "close_reason": self.close_reason,
            "pnl": self.pnl,
            "r_multiple": self.r_multiple,
            "hold_days": self.hold_days,
        }


@dataclass
class TradePosition:
    """A position synthesized from fills, with T1/T2 legs."""
    position_id: str
    idea_id: str
    symbol: str
    strategy: str
    status: str = "open"  # open, closed
    planned_entry: float = 0.0
    planned_stop: float = 0.0
    planned_target_t1: float = 0.0
    planned_target_t2: float = 0.0
    actual_entry: float = 0.0
    legs: List[PositionLeg] = field(default_factory=list)
    total_quantity: int = 0
    total_pnl: float = 0.0
    total_commission: float = 0.0
    entry_slippage: float = 0.0
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_doc(self) -> dict:
        """Convert to MongoDB document."""
        return {
            "position_id": self.position_id,
            "idea_id": self.idea_id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "status": self.status,
            "planned_entry": self.planned_entry,
            "planned_stop": self.planned_stop,
            "planned_target_t1": self.planned_target_t1,
            "planned_target_t2": self.planned_target_t2,
            "actual_entry": self.actual_entry,
            "legs": [leg.to_doc() for leg in self.legs],
            "total_quantity": self.total_quantity,
            "total_pnl": self.total_pnl,
            "total_commission": self.total_commission,
            "entry_slippage": self.entry_slippage,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TradeReview:
    """Journal review — plan vs actual with metrics and discipline assessment."""
    review_id: str
    position_id: str
    idea_id: str
    symbol: str
    strategy: str
    batch_date: str
    # Plan vs Actual
    planned_entry: float = 0.0
    actual_entry: float = 0.0
    planned_stop: float = 0.0
    planned_target_t2: float = 0.0
    actual_exit_avg: float = 0.0
    # Metrics
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    r_multiple: float = 0.0
    entry_slippage_pct: float = 0.0
    hold_days: int = 0
    outcome: str = ""  # win, loss, breakeven
    # T1/T2 tracking
    t1_hit: bool = False
    t2_hit: bool = False
    stop_hit: bool = False
    # Discipline
    followed_plan: bool = True
    discipline_score: float = 1.0
    # User-editable
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    lessons_learned: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_doc(self) -> dict:
        """Convert to MongoDB document."""
        return {
            "review_id": self.review_id,
            "position_id": self.position_id,
            "idea_id": self.idea_id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "batch_date": self.batch_date,
            "planned_entry": self.planned_entry,
            "actual_entry": self.actual_entry,
            "planned_stop": self.planned_stop,
            "planned_target_t2": self.planned_target_t2,
            "actual_exit_avg": self.actual_exit_avg,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "r_multiple": self.r_multiple,
            "entry_slippage_pct": self.entry_slippage_pct,
            "hold_days": self.hold_days,
            "outcome": self.outcome,
            "t1_hit": self.t1_hit,
            "t2_hit": self.t2_hit,
            "stop_hit": self.stop_hit,
            "followed_plan": self.followed_plan,
            "discipline_score": self.discipline_score,
            "tags": self.tags,
            "notes": self.notes,
            "lessons_learned": self.lessons_learned,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
