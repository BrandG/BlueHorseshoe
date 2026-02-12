import logging
import datetime
import numpy as np
from celery import chain
from bluehorseshoe.api.celery_app import celery_app
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.data.historical_data import build_all_symbols_history, BackfillConfig
from bluehorseshoe.reporting.html_reporter import HTMLReporter
from bluehorseshoe.core.email_service import EmailService

logger = logging.getLogger(__name__)

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

@celery_app.task(bind=True)
def update_market_data_task(self):
    """
    Task to update recent historical data for all symbols.
    Creates a task-scoped container for dependency management.
    """
    logger.info(f"Task {self.request.id}: Starting market data update...")
    container = create_app_container()
    try:
        # Test database connection
        container.get_mongo_client().server_info()

        # Run update for recent data (compact mode)
        build_all_symbols_history(BackfillConfig(recent=True), database=container.get_database())
        logger.info("Market data update completed.")
        return "Data Updated"
    except Exception as e:
        logger.error(f"Market update failed: {e}", exc_info=True)
        raise e
    finally:
        container.close()

@celery_app.task(bind=True)
def predict_task(self, target_date: str = None, indicators: list = None, aggregation: str = "sum", previous_result=None):
    """
    Background task to run SwingTrader prediction.
    Accepts `previous_result` to allow chaining, though it ignores it.
    If target_date is None, defaults to latest available.
    Creates a task-scoped container for dependency management.
    """
    # If chained from update_task, previous_result might be "Data Updated"
    logger.info(f"Task {self.request.id}: Starting prediction for {target_date or 'latest'}")

    def progress_callback(current, total, percent):
        self.update_state(
            state='PROGRESS',
            meta={
                'current': current,
                'total': total,
                'percent': percent,
                'status': f'Processing symbols... {percent:.1f}%'
            }
        )

    container = create_app_container()
    try:
        # Test database connection
        container.get_mongo_client().server_info()

        # Create SwingTrader with injected dependencies
        trader = SwingTrader(
            database=container.get_database(),
            config=container.settings,
            report_writer=None  # No report writer for background tasks (uses stdout)
        )

        # Note: SwingTrader automatically handles target_date=None by finding latest
        report_data = trader.swing_predict(
            target_date=target_date,
            enabled_indicators=indicators,
            aggregation=aggregation,
            progress_callback=progress_callback
        )

        clean_data = convert_numpy(report_data)

        # Inject the date into the result if not present, for the reporter
        if target_date:
            clean_data['date'] = target_date
        elif not clean_data.get('date'):
             # Try to extract from regime or candidates if possible, or use today
             clean_data['date'] = str(datetime.date.today())

        logger.info(f"Task {self.request.id}: Prediction completed successfully.")
        return clean_data

    except Exception as e:
        logger.error(f"Prediction failed: {e}", exc_info=True)
        raise e
    finally:
        container.close()

@celery_app.task(bind=True)
def generate_report_task(self, report_data: dict):
    """
    Generates HTML report from prediction results.
    Creates a task-scoped container for dependency management.
    """
    logger.info(f"Task {self.request.id}: Generating HTML report...")
    container = create_app_container()
    try:
        reporter = HTMLReporter(database=container.get_database())

        # Extract data
        date = report_data.get('date', str(datetime.date.today()))
        regime = report_data.get('regime', {})
        candidates = report_data.get('candidates', [])
        charts = report_data.get('charts', [])

        # Calculate previous day's performance
        trader = SwingTrader(
            database=container.get_database(),
            config=container.settings,
            report_writer=None
        )
        prev_perf = trader.get_previous_performance(date)

        # Generate full interactive report
        html_content = reporter.generate_report(
            date=date,
            regime=regime,
            candidates=candidates,
            charts=charts,
            previous_performance=prev_perf
        )

        # Generate email-friendly report (no JavaScript, no charts)
        email_html = reporter.generate_email_report(
            date=date,
            regime=regime,
            candidates=candidates,
            previous_performance=prev_perf
        )

        # Save both versions
        full_path, email_path = reporter.save_both(html_content, email_html, f"report_{date}")

        logger.info(f"Full report generated: {full_path}")
        logger.info(f"Email-friendly report generated: {email_path}")
        return {"status": "Report Generated", "path": full_path, "email_path": email_path}
    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        raise e
    finally:
        container.close()

@celery_app.task(bind=True)
def send_email_task(self, report_info: dict):
    """
    Sends the generated report via email.
    """
    logger.info(f"Task {self.request.id}: Sending email report...")
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
        # We don't raise here to avoid failing the whole chain if just email fails
        return f"Email Error: {e}"

@celery_app.task
def run_daily_pipeline():
    """
    Orchestrator task that chains Update -> Predict -> Report -> Email.
    """
    # We leave target_date as None so it picks the latest data (which we just updated)
    # Use .si() (immutable) for predict_task so it doesn't receive "Data Updated" as an arg
    workflow = chain(
        update_market_data_task.s(),
        predict_task.si(target_date=None),
        generate_report_task.s(),
        send_email_task.s()
    )
    workflow.apply_async()
    logger.info("Daily pipeline triggered.")
