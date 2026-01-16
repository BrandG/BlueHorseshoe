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

class TaskSubmission(BaseModel):
    """
    Response when a long-running task is submitted.
    """
    task_id: str
    status: str
    message: str

class TaskStatus(BaseModel):

    """

    Response for polling task status.

    """

    task_id: str

    status: str

    progress: Optional[Dict[str, Any]] = None

    result: Optional[Dict[str, Any]] = None

    error: Optional[str] = None
