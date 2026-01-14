from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class PredictionRequest(BaseModel):
    """
    Schema for prediction requests.
    """
    target_date: Optional[str] = Field(
        None, 
        description="The date to predict for (YYYY-MM-DD). Defaults to the latest market date."
    )
    indicators: Optional[List[str]] = Field(
        None, 
        description="List of specific indicators to enable (e.g., ['momentum:rsi', 'trend:ema'])."
    )
    aggregation: str = Field(
        "sum", 
        description="Method to aggregate scores ('sum' or 'product')."
    )

class Candidate(BaseModel):
    """
    Schema for a single trading candidate.
    """
    symbol: str
    score: float
    reason: List[str]
    setup: Optional[Dict[str, Any]] = None

class Regime(BaseModel):
    """
    Schema for market regime information.
    """
    status: str
    details: Optional[Dict[str, Any]] = None

class PredictionResponse(BaseModel):
    """
    Schema for the prediction response.
    """
    date: str
    regime: Regime
    candidates: List[Candidate]
    # We can add more fields here as needed (e.g., charts URL in the future)
