import json
import os
import glob
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from pymongo.database import Database
from bluehorseshoe.api.models import PredictionRequest, TaskSubmission, TaskStatus
from bluehorseshoe.api.tasks import (
    predict_task, run_daily_pipeline, task_store, new_task_id,
)
from bluehorseshoe.core.dependencies import get_database, get_config, get_ibkr_client, get_store
from bluehorseshoe.core.config import REPO_ROOT, Settings
from bluehorseshoe.core.service import get_latest_market_date
from bluehorseshoe.data.ibkr_client import IBKRClient
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


# ── Reports dashboard helpers ──────────────────────────────────────────

_REPORTS_CSS = """
:root {
    --surface: rgba(255, 255, 255, 0.04);
    --surface-hover: rgba(255, 255, 255, 0.07);
    --border: rgba(255, 255, 255, 0.07);
    --border-hover: rgba(255, 255, 255, 0.14);
    --text: #ddd8e8;
    --text-muted: #7d7494;
    --accent: #7c5cbf;
    --accent-blue: #4a7cff;
    --accent-teal: #00c9a7;
}

*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

html { scroll-behavior: smooth; }

body {
    font-family: 'Outfit', system-ui, sans-serif;
    background: linear-gradient(160deg, #1a0533 0%, #0d0e24 45%, #0a1628 100%);
    background-attachment: fixed;
    color: var(--text);
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

body::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
        radial-gradient(ellipse at 15% 50%, rgba(124, 92, 191, 0.1) 0%, transparent 50%),
        radial-gradient(ellipse at 85% 20%, rgba(74, 124, 255, 0.07) 0%, transparent 50%),
        radial-gradient(ellipse at 50% 90%, rgba(0, 201, 167, 0.04) 0%, transparent 40%);
    pointer-events: none;
    z-index: 0;
}

.container {
    max-width: 1100px;
    margin: 0 auto;
    padding: 3rem 1.5rem 4rem;
    position: relative;
    z-index: 1;
}

.header {
    text-align: center;
    margin-bottom: 2.5rem;
}

.header h1 {
    font-size: 1.75rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    background: linear-gradient(135deg, #b794f4 0%, #7c5cbf 40%, #4a7cff 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.subtitle {
    font-size: 0.8rem;
    color: var(--text-muted);
    font-weight: 300;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 0.4rem;
}

.accent-line {
    display: block;
    width: 48px;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent-blue));
    margin: 1.25rem auto 0;
    border-radius: 1px;
    animation: glow-pulse 3s ease-in-out infinite;
}

@keyframes glow-pulse {
    0%, 100% { box-shadow: 0 0 8px rgba(124, 92, 191, 0.3); }
    50% { box-shadow: 0 0 16px rgba(124, 92, 191, 0.6); }
}

.stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
    margin-bottom: 2rem;
}

.stat-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.25rem 1rem;
    text-align: center;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    transition: border-color 0.3s ease;
}

.stat-box:hover {
    border-color: var(--border-hover);
}

.stat-value {
    font-family: 'DM Mono', 'SF Mono', 'Cascadia Code', monospace;
    font-size: 1.4rem;
    font-weight: 500;
    background: linear-gradient(135deg, var(--accent), var(--accent-blue));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.3;
}

.stat-label {
    font-size: 0.7rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 0.3rem;
}

.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 0.75rem;
}

.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.4rem;
    transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1),
                box-shadow 0.3s ease,
                border-color 0.3s ease;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    animation: fadeUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.card:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 32px rgba(124, 92, 191, 0.12),
                0 0 0 1px rgba(124, 92, 191, 0.08);
    border-color: var(--border-hover);
}

.card-date {
    font-family: 'DM Mono', 'SF Mono', monospace;
    font-size: 1.1rem;
    font-weight: 500;
    margin-bottom: 0.5rem;
    letter-spacing: -0.01em;
}

.card-meta {
    font-size: 0.78rem;
    color: var(--text-muted);
    margin-bottom: 1rem;
    letter-spacing: 0.01em;
}

.card-actions {
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
}

.btn {
    display: inline-flex;
    align-items: center;
    padding: 0.4rem 0.85rem;
    border-radius: 7px;
    font-family: 'Outfit', system-ui, sans-serif;
    font-size: 0.78rem;
    font-weight: 500;
    text-decoration: none;
    transition: all 0.2s ease;
    cursor: pointer;
    border: none;
}

.btn-full {
    background: linear-gradient(135deg, var(--accent), var(--accent-blue));
    color: #fff;
}

.btn-full:hover {
    box-shadow: 0 4px 16px rgba(124, 92, 191, 0.35);
    filter: brightness(1.12);
}

.btn-email {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--border);
    color: var(--text);
}

.btn-email:hover {
    border-color: rgba(124, 92, 191, 0.4);
    background: rgba(124, 92, 191, 0.1);
}

.btn-arcade {
    background: linear-gradient(135deg, var(--accent-teal), #2d8cf0);
    color: #fff;
}

.btn-arcade:hover {
    box-shadow: 0 4px 16px rgba(0, 201, 167, 0.3);
    filter: brightness(1.12);
}

.empty {
    grid-column: 1 / -1;
    text-align: center;
    padding: 5rem 2rem;
}

.empty-icon {
    font-size: 2.5rem;
    opacity: 0.15;
    margin-bottom: 1rem;
}

.empty p {
    color: var(--text-muted);
    font-size: 0.95rem;
}

@keyframes fadeUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
}

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(124, 92, 191, 0.3); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(124, 92, 191, 0.5); }

@media (max-width: 700px) {
    .stats { grid-template-columns: 1fr; }
    .grid { grid-template-columns: 1fr; }
    .header h1 { font-size: 1.35rem; }
    .container { padding: 2rem 1rem 3rem; }
    .stat-box { padding: 1rem; }
    .stat-value { font-size: 1.2rem; }
}

@media (max-width: 400px) {
    .card-actions { flex-direction: column; }
    .btn { justify-content: center; }
}
"""


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _build_report_card(date: str, variants: dict, index: int) -> str:
    sizes = []
    mtimes = []
    for path in variants.values():
        try:
            stat = os.stat(path)
            sizes.append(stat.st_size)
            mtimes.append(stat.st_mtime)
        except OSError:
            pass

    total_size = sum(sizes) if sizes else 0
    latest_mtime = max(mtimes) if mtimes else 0
    modified_str = datetime.fromtimestamp(latest_mtime).strftime("%b %d, %Y %I:%M %p") if latest_mtime else "Unknown"
    size_str = _format_file_size(total_size)

    buttons = []
    if "full" in variants:
        buttons.append(
            f'<a href="/api/v1/reports/{date}" class="btn btn-full" target="_blank">Full Report</a>'
        )
    if "email" in variants:
        buttons.append(
            f'<a href="/api/v1/reports/{date}/email" class="btn btn-email" target="_blank">Email</a>'
        )
    if "arcade" in variants:
        buttons.append(
            f'<a href="/api/v1/arcade/{date}" class="btn btn-arcade" target="_blank">Arcade</a>'
        )

    buttons_html = "\n            ".join(buttons)
    delay = index * 0.06

    return f"""<div class="card" style="animation-delay: {delay:.2f}s">
        <div class="card-date">{date}</div>
        <div class="card-meta">{size_str} &middot; {modified_str}</div>
        <div class="card-actions">
            {buttons_html}
        </div>
    </div>"""


def _build_reports_page(cards_html: str, num_dates: int, total_files: int, latest_date: str) -> str:
    empty_state = '<div class="empty"><div class="empty-icon">\u03A9</div><p>No reports generated yet</p></div>'
    content = cards_html if cards_html else empty_state

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>\u03A9 BlueHorseshoe Reports</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>{_REPORTS_CSS}</style>
</head>
<body>
<div class="container">
    <header class="header">
        <h1>\u03A9 BlueHorseshoe Reports</h1>
        <p class="subtitle">Trading Signal Archive</p>
        <span class="accent-line"></span>
    </header>
    <div class="stats">
        <div class="stat-box">
            <div class="stat-value">{num_dates}</div>
            <div class="stat-label">Report Dates</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{total_files}</div>
            <div class="stat-label">Total Files</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{latest_date}</div>
            <div class="stat-label">Latest Report</div>
        </div>
    </div>
    <div class="grid">
        {content}
    </div>
</div>
</body>
</html>"""


# ── Routes ─────────────────────────────────────────────────────────────

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
    store=Depends(get_store),
):
    """
    Submit a prediction job to run in the background.
    Returns a task_id to poll for results.
    """
    target_date = request.target_date
    if not target_date:
        target_date = get_latest_market_date(store=store)
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


@router.get("/reports", response_class=HTMLResponse)
async def list_reports(config: Settings = Depends(get_config)):
    """
    Styled HTML dashboard listing all available reports with links to each variant.
    """
    dates_info: dict[str, dict[str, str]] = {}

    # Scan logs_path for full and email reports
    for f in glob.glob(os.path.join(config.logs_path, "report_*.html")):
        basename = os.path.basename(f)
        if "_email.html" in basename:
            date = basename.replace("report_", "").replace("_email.html", "")
            dates_info.setdefault(date, {})["email"] = f
        else:
            date = basename.replace("report_", "").replace(".html", "")
            dates_info.setdefault(date, {})["full"] = f

    # Scan logs_path for arcade reports
    for f in glob.glob(os.path.join(config.logs_path, "report_*_arcade.html")):
        date = os.path.basename(f).replace("report_", "").replace("_arcade.html", "")
        dates_info.setdefault(date, {})["arcade"] = f

    sorted_dates = sorted(dates_info.keys(), reverse=True)
    num_dates = len(sorted_dates)
    total_files = sum(len(v) for v in dates_info.values())
    latest_date = sorted_dates[0] if sorted_dates else "N/A"

    cards = []
    for i, date in enumerate(sorted_dates):
        cards.append(_build_report_card(date, dates_info[date], i))

    cards_html = "\n".join(cards)
    return HTMLResponse(_build_reports_page(cards_html, num_dates, total_files, latest_date))


@router.get("/reports/{date}/email")
async def get_email_report(date: str, config: Settings = Depends(get_config)):
    """
    Retrieve the email variant of an HTML report by date (YYYY-MM-DD).
    """
    file_path = os.path.join(config.logs_path, f"report_{date}_email.html")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Email report for {date} not found")
    return FileResponse(file_path, media_type="text/html")


@router.get("/reports/{date}")
async def get_report(date: str, config: Settings = Depends(get_config)):
    """
    Retrieve a specific HTML report by date (YYYY-MM-DD).
    """
    file_path = os.path.join(config.logs_path, f"report_{date}.html")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Report for {date} not found")
    return FileResponse(file_path, media_type="text/html")


@router.get("/arcade/{date}")
async def get_arcade_report(date: str, config: Settings = Depends(get_config)):
    """
    Retrieve the arcade-themed HTML report by date (YYYY-MM-DD).
    """
    file_path = os.path.join(config.logs_path, f"report_{date}_arcade.html")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Arcade report for {date} not found")
    return FileResponse(file_path, media_type="text/html")


@router.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "ok", "service": "bluehorseshoe-api"}


_PIPELINE_STATUS_FILE = os.path.join(REPO_ROOT, "src", "logs", "pipeline_status.json")


@router.get("/pipeline/status")
async def get_pipeline_status():
    """
    Return the current pipeline status from the status JSON file.
    """
    if not os.path.exists(_PIPELINE_STATUS_FILE):
        return {"message": "No pipeline run yet", "status": None}
    try:
        with open(_PIPELINE_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read pipeline status: {e}") from e


@router.get("/quote/{symbol}")
def get_quote(symbol: str, client: IBKRClient = Depends(get_ibkr_client)):
    """
    Get a real-time quote snapshot from IB Gateway.
    Returns 503 if gateway is not available.
    """
    quote = client.get_quote(symbol.upper())
    if quote.error:
        raise HTTPException(status_code=503, detail=quote.error)
    return {
        "symbol": quote.symbol,
        "bid": quote.bid,
        "ask": quote.ask,
        "last": quote.last,
        "volume": quote.volume,
        "high": quote.high,
        "low": quote.low,
        "open": quote.open,
        "close": quote.close,
        "timestamp": quote.timestamp.isoformat() if quote.timestamp else None,
    }
