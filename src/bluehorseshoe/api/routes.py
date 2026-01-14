from fastapi import APIRouter, HTTPException
from bluehorseshoe.api.models import PredictionRequest, PredictionResponse, Candidate, Regime
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.globals import get_mongo_client
from bluehorseshoe.core.service import get_latest_market_date
import logging

router = APIRouter()
logger = logging.getLogger("bluehorseshoe.api")

@router.post("/predict", response_model=PredictionResponse)
async def predict_candidates(request: PredictionRequest):
    """
    Generate trading candidates for a specific date.
    """
    # Ensure DB connection
    if get_mongo_client() is None:
        raise HTTPException(status_code=500, detail="Database connection failed")

    target_date = request.target_date
    if not target_date:
        # Re-use the helper from main.py or implement a safe fallback
        # Ideally, this logic should be in a shared service, but importing from main is okay for now
        # given the project structure.
        target_date = get_latest_market_date()
        if not target_date:
             raise HTTPException(status_code=404, detail="No market data available to determine latest date.")

    logger.info(f"Received prediction request for {target_date}")

    try:
        # Initialize the trader
        trader = SwingTrader()
        
        # Run prediction
        # Note: SwingTrader.swing_predict returns a dict with 'regime', 'candidates', etc.
        report_data = trader.swing_predict(
            target_date=target_date,
            enabled_indicators=request.indicators,
            aggregation=request.aggregation
        )

        if not report_data:
             raise HTTPException(status_code=404, detail=f"No data found for date {target_date}")

        # Map response to Pydantic models
        candidates_data = report_data.get('candidates', [])
        mapped_candidates = []
        for c in candidates_data:
            # Handle potential variation in candidate structure
            # Assuming c is a dict or object with these attributes. 
            # If SwingTrader returns raw dicts, this works.
            mapped_candidates.append(Candidate(
                symbol=c.get('symbol'),
                score=c.get('score', 0.0),
                reason=c.get('reasons', []), # Note: Check if it's 'reasons' or 'reason' in SwingTrader
                setup=c.get('setup')
            ))

        regime_data = report_data.get('regime', {})
        regime = Regime(
            status=regime_data.get('status', 'Unknown'),
            details=regime_data
        )

        return PredictionResponse(
            date=target_date,
            regime=regime,
            candidates=mapped_candidates
        )

    except Exception as e:
        logger.error(f"Prediction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "ok", "service": "bluehorseshoe-api"}
