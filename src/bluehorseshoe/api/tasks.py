import logging
import datetime
import numpy as np
import uuid
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.data.historical_data import build_all_symbols_history, BackfillConfig
from bluehorseshoe.reporting.html_reporter import HTMLReporter
from bluehorseshoe.core.email_service import EmailService

logger = logging.getLogger(__name__)

# In-memory task status store
task_store: dict[str, dict] = {}


def new_task_id() -> str:
    """Generate a new task ID and initialize its status."""
    tid = str(uuid.uuid4())
    task_store[tid] = {"status": "PENDING"}
    return tid


def convert_numpy(obj):
    """
    Recursively convert numpy types to native Python types for JSON serialization.
    """
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy(i) for i in obj]
    return obj


def update_market_data_task(task_id: str | None = None):
    """
    Update recent historical data for all symbols.
    Creates a task-scoped container for dependency management.
    """
    logger.info(f"Task {task_id}: Starting market data update...")
    if task_id:
        task_store[task_id] = {"status": "PROGRESS", "step": "update_market_data"}
    container = create_app_container()
    try:
        container.get_mongo_client().server_info()
        build_all_symbols_history(BackfillConfig(recent=True), database=container.get_database(), store=container.get_historical_store())
        logger.info("Market data update completed.")
        return "Data Updated"
    except Exception as e:
        logger.error(f"Market update failed: {e}", exc_info=True)
        raise
    finally:
        container.close()


def predict_task(target_date: str = None, indicators: list = None, aggregation: str = "sum", task_id: str | None = None):
    """
    Run SwingTrader prediction.
    If target_date is None, defaults to latest available.
    Creates a task-scoped container for dependency management.
    """
    logger.info(f"Task {task_id}: Starting prediction for {target_date or 'latest'}")
    if task_id:
        task_store[task_id] = {"status": "PROGRESS", "step": "predict"}

    def progress_callback(current, total, percent):
        if task_id:
            task_store[task_id] = {
                "status": "PROGRESS",
                "step": "predict",
                "progress": {
                    "current": current,
                    "total": total,
                    "percent": percent,
                    "status": f"Processing symbols... {percent:.1f}%",
                },
            }

    container = create_app_container()
    try:
        container.get_mongo_client().server_info()
        trader = SwingTrader(
            database=container.get_database(),
            config=container.settings,
            report_writer=None,
        )
        report_data = trader.swing_predict(
            target_date=target_date,
            enabled_indicators=indicators,
            aggregation=aggregation,
            progress_callback=progress_callback,
        )
        clean_data = convert_numpy(report_data)
        if target_date:
            clean_data["date"] = target_date
        elif not clean_data.get("date"):
            clean_data["date"] = str(datetime.date.today())
        logger.info(f"Task {task_id}: Prediction completed successfully.")
        return clean_data
    except Exception as e:
        logger.error(f"Prediction failed: {e}", exc_info=True)
        raise
    finally:
        container.close()


def generate_report_task(report_data: dict, task_id: str | None = None):
    """
    Generate HTML report from prediction results.
    Creates a task-scoped container for dependency management.
    """
    logger.info(f"Task {task_id}: Generating HTML report...")
    if task_id:
        task_store[task_id] = {"status": "PROGRESS", "step": "generate_report"}
    container = create_app_container()
    try:
        reporter = HTMLReporter(database=container.get_database())
        date = report_data.get("date", str(datetime.date.today()))
        regime = report_data.get("regime", {})
        candidates = report_data.get("candidates", [])
        charts = report_data.get("charts", [])

        trader = SwingTrader(
            database=container.get_database(),
            config=container.settings,
            report_writer=None,
        )
        prev_perf = trader.get_previous_performance(date)
        html_content = reporter.generate_report(
            date=date, regime=regime, candidates=candidates,
            charts=charts, previous_performance=prev_perf,
        )
        email_html = reporter.generate_email_report(
            date=date, regime=regime, candidates=candidates,
            previous_performance=prev_perf,
        )
        full_path, email_path = reporter.save_both(html_content, email_html, f"report_{date}")
        logger.info(f"Full report generated: {full_path}")
        logger.info(f"Email-friendly report generated: {email_path}")
        return {"status": "Report Generated", "path": full_path, "email_path": email_path}
    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        raise
    finally:
        container.close()


def send_email_task(report_info: dict, task_id: str | None = None):
    """
    Send the generated report via email.
    """
    logger.info(f"Task {task_id}: Sending email report...")
    if task_id:
        task_store[task_id] = {"status": "PROGRESS", "step": "send_email"}
    try:
        report_path = report_info.get("path")
        if not report_path:
            logger.warning("No report path provided to email task.")
            return "No Report Path"
        email_service = EmailService()
        success = email_service.send_report(report_path)
        if success:
            logger.info("Email sent successfully.")
            return "Email Sent"
        else:
            logger.warning("Email sending failed (check logs).")
            return "Email Failed"
    except Exception as e:
        logger.error(f"Email task failed: {e}", exc_info=True)
        return f"Email Error: {e}"


def run_daily_pipeline(task_id: str | None = None):
    """
    Sequential pipeline: Update -> Predict -> Report -> Email.
    """
    logger.info("Daily pipeline triggered.")
    try:
        update_market_data_task(task_id=task_id)
        report_data = predict_task(target_date=None, task_id=task_id)
        report_info = generate_report_task(report_data, task_id=task_id)
        send_email_task(report_info, task_id=task_id)
        if task_id:
            task_store[task_id] = {"status": "SUCCESS", "result": "Pipeline complete"}
        logger.info("Daily pipeline completed successfully.")
    except Exception as e:
        logger.error(f"Daily pipeline failed: {e}", exc_info=True)
        if task_id:
            task_store[task_id] = {"status": "FAILURE", "error": str(e)}
