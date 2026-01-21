import os
import glob
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from celery.result import AsyncResult
from pymongo.database import Database
from bluehorseshoe.api.models import PredictionRequest, TaskSubmission, TaskStatus
from bluehorseshoe.api.tasks import predict_task, run_daily_pipeline
from bluehorseshoe.core.dependencies import get_database, get_config
from bluehorseshoe.core.config import Settings
from bluehorseshoe.core.service import get_latest_market_date
import logging

router = APIRouter()
logger = logging.getLogger("bluehorseshoe.api")

@router.post("/pipeline/run", response_model=TaskSubmission, status_code=202)
async def trigger_daily_pipeline():
    """
    Manually triggers the full daily pipeline (Update -> Predict -> Report -> Email).
    """
    logger.info("Manually triggering daily pipeline.")
    task = run_daily_pipeline.delay()
    
    return TaskSubmission(
        task_id=task.id,
        status="PENDING",
        message="Daily pipeline triggered manually."
    )

@router.post("/predict", response_model=TaskSubmission, status_code=202)
async def predict_candidates(
    request: PredictionRequest,
    db: Database = Depends(get_database)
):
    """
    Submit a prediction job to the background worker.
    Returns a task_id to poll for results.
    """
    target_date = request.target_date
    if not target_date:
        # Use injected database to get latest market date
        target_date = get_latest_market_date(db)
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

@router.get("/reports")
async def list_reports(config: Settings = Depends(get_config)):
    """
    List all available report dates.
    """
    pattern = os.path.join(config.logs_path, "report_*.html")
    files = glob.glob(pattern)

    # Extract dates from filenames (e.g., report_2026-01-15.html -> 2026-01-15)
    reports = []
    for f in files:
        basename = os.path.basename(f)
        date_part = basename.replace("report_", "").replace(".html", "")
        reports.append(date_part)

    return sorted(reports, reverse=True)

@router.get("/reports/{date}")
async def get_report(date: str, config: Settings = Depends(get_config)):
    """
    Retrieve a specific HTML report by date (YYYY-MM-DD).
    """
    file_path = os.path.join(config.logs_path, f"report_{date}.html")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Report for {date} not found")

    return FileResponse(file_path, media_type="text/html")

@router.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "ok", "service": "bluehorseshoe-api"}