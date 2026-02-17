import os
import glob
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from pymongo.database import Database
from bluehorseshoe.api.models import PredictionRequest, TaskSubmission, TaskStatus
from bluehorseshoe.api.tasks import (
    predict_task, run_daily_pipeline, task_store, new_task_id,
)
from bluehorseshoe.core.dependencies import get_database, get_config
from bluehorseshoe.core.config import Settings
from bluehorseshoe.core.service import get_latest_market_date
import logging

router = APIRouter()
logger = logging.getLogger("bluehorseshoe.api")


def _run_predict_background(task_id: str, target_date: str, indicators: list, aggregation: str):
    """Wrapper to run predict_task and store final status."""
    try:
        result = predict_task(
            target_date=target_date,
            indicators=indicators,
            aggregation=aggregation,
            task_id=task_id,
        )
        task_store[task_id] = {"status": "SUCCESS", "result": result}
    except Exception as e:
        task_store[task_id] = {"status": "FAILURE", "error": str(e)}


def _run_pipeline_background(task_id: str):
    """Wrapper to run daily pipeline in background."""
    run_daily_pipeline(task_id=task_id)


@router.post("/pipeline/run", response_model=TaskSubmission, status_code=202)
async def trigger_daily_pipeline(background_tasks: BackgroundTasks):
    """
    Manually triggers the full daily pipeline (Update -> Predict -> Report -> Email).
    """
    logger.info("Manually triggering daily pipeline.")
    task_id = new_task_id()
    background_tasks.add_task(_run_pipeline_background, task_id)
    return TaskSubmission(
        task_id=task_id,
        status="PENDING",
        message="Daily pipeline triggered manually.",
    )


@router.post("/predict", response_model=TaskSubmission, status_code=202)
async def predict_candidates(
    request: PredictionRequest,
    background_tasks: BackgroundTasks,
    db: Database = Depends(get_database),
):
    """
    Submit a prediction job to run in the background.
    Returns a task_id to poll for results.
    """
    target_date = request.target_date
    if not target_date:
        target_date = get_latest_market_date(db)
        if not target_date:
            raise HTTPException(status_code=404, detail="No market data available to determine latest date.")

    logger.info(f"Submitting prediction task for {target_date}")
    task_id = new_task_id()
    background_tasks.add_task(
        _run_predict_background, task_id, target_date, request.indicators, request.aggregation,
    )
    return TaskSubmission(
        task_id=task_id,
        status="PENDING",
        message=f"Prediction started for {target_date}",
    )


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """
    Check the status of a background task.
    """
    info = task_store.get(task_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Task not found")

    response = TaskStatus(task_id=task_id, status=info["status"])
    if info["status"] == "PROGRESS":
        response.progress = info.get("progress")
    elif info["status"] == "SUCCESS":
        response.result = info.get("result")
    elif info["status"] == "FAILURE":
        response.error = info.get("error")
    return response


@router.get("/reports")
async def list_reports(config: Settings = Depends(get_config)):
    """
    List all available report dates.
    """
    pattern = os.path.join(config.logs_path, "report_*.html")
    files = glob.glob(pattern)
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
