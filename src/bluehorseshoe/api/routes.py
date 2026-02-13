import os
import glob
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, HTMLResponse
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

@router.get("/reports", response_class=HTMLResponse)
async def list_reports(config: Settings = Depends(get_config)):
    """
    List all available report dates as a styled HTML page with links.
    """
    pattern = os.path.join(config.logs_path, "report_*.html")
    files = glob.glob(pattern)

    # Extract dates and file info
    reports = []
    for f in files:
        basename = os.path.basename(f)
        # Handle both regular and email reports
        if basename.startswith("report_") and basename.endswith(".html"):
            date_part = basename.replace("report_", "").replace(".html", "").replace("_email", "")
            is_email = "_email" in basename
            file_size = os.path.getsize(f)
            modified_time = os.path.getmtime(f)

            reports.append({
                'date': date_part,
                'is_email': is_email,
                'size': file_size,
                'modified': modified_time,
                'filename': basename
            })

    # Sort by date (most recent first)
    reports.sort(key=lambda x: x['date'], reverse=True)

    # Generate HTML
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BlueHorseshoe Trading Reports</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}

            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
                color: #333;
                min-height: 100vh;
                padding: 20px;
            }}

            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 12px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                overflow: hidden;
            }}

            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 40px;
                text-align: center;
            }}

            .header h1 {{
                font-size: 2.5rem;
                font-weight: 700;
                margin-bottom: 10px;
            }}

            .header p {{
                font-size: 1.1rem;
                opacity: 0.9;
            }}

            .stats {{
                display: flex;
                justify-content: space-around;
                padding: 30px;
                background: #f8f9fa;
                border-bottom: 1px solid #e9ecef;
            }}

            .stat {{
                text-align: center;
            }}

            .stat-value {{
                font-size: 2rem;
                font-weight: 700;
                color: #667eea;
            }}

            .stat-label {{
                font-size: 0.9rem;
                color: #6c757d;
                margin-top: 5px;
            }}

            .reports-list {{
                padding: 40px;
            }}

            .report-card {{
                background: white;
                border: 1px solid #e9ecef;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 15px;
                transition: all 0.3s ease;
            }}

            .report-card:hover {{
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                transform: translateY(-2px);
            }}

            .report-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
            }}

            .report-date {{
                font-size: 1.3rem;
                font-weight: 600;
                color: #2c3e50;
            }}

            .report-badge {{
                background: #667eea;
                color: white;
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 0.8rem;
                font-weight: 600;
            }}

            .report-meta {{
                display: flex;
                gap: 20px;
                margin-bottom: 15px;
                font-size: 0.9rem;
                color: #6c757d;
            }}

            .report-meta span {{
                display: flex;
                align-items: center;
                gap: 5px;
            }}

            .report-links {{
                display: flex;
                gap: 10px;
            }}

            .btn {{
                display: inline-block;
                padding: 10px 20px;
                border-radius: 6px;
                text-decoration: none;
                font-weight: 600;
                transition: all 0.3s ease;
                border: none;
                cursor: pointer;
            }}

            .btn-primary {{
                background: #667eea;
                color: white;
            }}

            .btn-primary:hover {{
                background: #5568d3;
                transform: translateY(-1px);
            }}

            .btn-secondary {{
                background: #6c757d;
                color: white;
            }}

            .btn-secondary:hover {{
                background: #5a6268;
                transform: translateY(-1px);
            }}

            .empty-state {{
                text-align: center;
                padding: 60px 20px;
                color: #6c757d;
            }}

            .empty-state h2 {{
                font-size: 1.5rem;
                margin-bottom: 10px;
            }}

            @media (max-width: 768px) {{
                .header h1 {{
                    font-size: 1.8rem;
                }}

                .stats {{
                    flex-direction: column;
                    gap: 20px;
                }}

                .report-header {{
                    flex-direction: column;
                    align-items: flex-start;
                    gap: 10px;
                }}

                .report-links {{
                    flex-direction: column;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📈 BlueHorseshoe Trading Reports</h1>
                <p>ML-Enhanced Swing Trading Analysis</p>
            </div>

            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{len(set(r['date'] for r in reports))}</div>
                    <div class="stat-label">Unique Dates</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{len(reports)}</div>
                    <div class="stat-label">Total Reports</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{reports[0]['date'] if reports else 'N/A'}</div>
                    <div class="stat-label">Latest Report</div>
                </div>
            </div>

            <div class="reports-list">
    """

    if not reports:
        html += """
                <div class="empty-state">
                    <h2>No reports found</h2>
                    <p>Run predictions to generate your first report</p>
                </div>
        """
    else:
        # Group by date
        dates_seen = set()
        for report in reports:
            date = report['date']

            # Skip if we already showed this date
            if date in dates_seen:
                continue
            dates_seen.add(date)

            # Find both regular and email versions
            regular = next((r for r in reports if r['date'] == date and not r['is_email']), None)
            email = next((r for r in reports if r['date'] == date and r['is_email']), None)

            # Format date nicely
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
                formatted_date = dt.strftime("%B %d, %Y")
                day_of_week = dt.strftime("%A")
            except:
                formatted_date = date
                day_of_week = ""

            html += f"""
                <div class="report-card">
                    <div class="report-header">
                        <div class="report-date">{formatted_date}</div>
                        <div class="report-badge">{day_of_week}</div>
                    </div>
            """

            if regular:
                size_kb = regular['size'] / 1024
                modified = datetime.fromtimestamp(regular['modified']).strftime("%I:%M %p")
                html += f"""
                    <div class="report-meta">
                        <span>📄 {size_kb:.1f} KB</span>
                        <span>🕒 Updated {modified}</span>
                    </div>
                """

            html += """
                    <div class="report-links">
            """

            if regular:
                html += f"""
                        <a href="/api/v1/reports/{date}" class="btn btn-primary" target="_blank">
                            📊 View Full Report
                        </a>
                """

            if email:
                html += f"""
                        <a href="/api/v1/reports/{date}/email" class="btn btn-secondary" target="_blank">
                            📧 Email Version
                        </a>
                """

            html += """
                    </div>
                </div>
            """

    html += """
            </div>
        </div>
    </body>
    </html>
    """

    return html

@router.get("/reports/{date}")
async def get_report(date: str, config: Settings = Depends(get_config)):
    """
    Retrieve a specific HTML report by date (YYYY-MM-DD).
    """
    file_path = os.path.join(config.logs_path, f"report_{date}.html")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Report for {date} not found")

    return FileResponse(file_path, media_type="text/html")

@router.get("/reports/{date}/email")
async def get_email_report(date: str, config: Settings = Depends(get_config)):
    """
    Retrieve the email version of a report by date (YYYY-MM-DD).
    """
    file_path = os.path.join(config.logs_path, f"report_{date}_email.html")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Email report for {date} not found")

    return FileResponse(file_path, media_type="text/html")

@router.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "ok", "service": "bluehorseshoe-api"}