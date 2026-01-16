from fastapi import APIRouter, HTTPException
from celery.result import AsyncResult
from bluehorseshoe.api.models import PredictionRequest, TaskSubmission, TaskStatus
from bluehorseshoe.api.tasks import predict_task
from bluehorseshoe.core.globals import get_mongo_client
from bluehorseshoe.core.service import get_latest_market_date
import logging

router = APIRouter()
logger = logging.getLogger("bluehorseshoe.api")

@router.post("/predict", response_model=TaskSubmission, status_code=202)
async def predict_candidates(request: PredictionRequest):
    """
    Submit a prediction job to the background worker.
    Returns a task_id to poll for results.
    """
    target_date = request.target_date
    if not target_date:
        if get_mongo_client() is None:
             raise HTTPException(status_code=500, detail="Database connection failed")
        
        target_date = get_latest_market_date()
        if not target_date:
             raise HTTPException(status_code=404, detail="No market data available to determine latest date.")

    logger.info(f"Submitting prediction task for {target_date}")

    # Trigger Celery Task
    task = predict_task.delay(
        target_date=target_date,
        indicators=request.indicators,
        aggregation=request.aggregation
    )

    return TaskSubmission(
        task_id=task.id,
        status="PENDING",
        message=f"Prediction started for {target_date}"
    )

@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """
    Check the status of a background task.
    """
    task_result = AsyncResult(task_id)
    
    response = TaskStatus(
        task_id=task_id,
        status=task_result.status
    )

    if task_result.status == 'PROGRESS':
        response.progress = task_result.info
    elif task_result.successful():
        response.result = task_result.result
    elif task_result.failed():
        response.error = str(task_result.result)
    
    return response

@router.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "ok", "service": "bluehorseshoe-api"}