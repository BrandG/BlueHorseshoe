"""
models.py (v1.0)
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class Candidate:
    """
    Represents a single trading candidate with price data and scores.
    """
    symbol: str
    score: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    range: float
    body: float
    stability: float
    volatility: Optional[float] = None

    predicted_high: Optional[float] = None
    predicted_low: Optional[float] = None
    expected_upside: Optional[float] = None
    expected_downside: Optional[float] = None

    def to_dict(self):
        """Convert object to dictionary."""
        return self.__dict__


@dataclass
class DailyReport:
    """
    Represents the daily generated report containing market analysis and top picks.
    """
    report_date: str
    data_date: str
    strategy: str
    version: str
    universe_size: int
    top_candidates: List[Dict[str, Any]]
    selected: Dict[str, Any]

    def to_dict(self):
        """Convert object to dictionary."""
        return self.__dict__
