import os
import glob
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from pymongo.database import Database
from bluehorseshoe.core.dependencies import get_database, get_config
from bluehorseshoe.core.config import Settings
import logging

router = APIRouter()
logger = logging.getLogger("bluehorseshoe.api")

# Celery-dependent endpoints removed - use CLI instead:
# - docker exec bluehorseshoe python src/main.py -u  # Update data
# - docker exec bluehorseshoe python src/main.py -p  # Predict & report
# Or use the cron job at 02:00 UTC daily

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