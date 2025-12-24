"""
models.py (v1.0)
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import date


@dataclass
class Candidate:
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
        return self.__dict__


@dataclass
class DailyReport:
    report_date: str
    data_date: str
    strategy: str
    version: str
    universe_size: int
    top_candidates: List[Dict[str, Any]]
    selected: Dict[str, Any]

    def to_dict(self):
        return self.__dict__
