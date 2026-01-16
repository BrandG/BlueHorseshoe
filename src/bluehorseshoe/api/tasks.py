import logging
import numpy as np
from bluehorseshoe.api.celery_app import celery_app
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.globals import get_mongo_client

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
def predict_task(self, target_date: str, indicators: list = None, aggregation: str = "sum"):
    """
    Background task to run SwingTrader prediction.
    """
    logger.info(f"Task {self.request.id}: Starting prediction for {target_date}")
    
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

    try:
        # Ensure DB connection in worker process
        if get_mongo_client() is None:
            raise RuntimeError("Could not connect to MongoDB in worker")

        trader = SwingTrader()
        report_data = trader.swing_predict(
            target_date=target_date,
            enabled_indicators=indicators,
            aggregation=aggregation,
            progress_callback=progress_callback
        )
        
        # Convert numpy types to ensure JSON serialization compatibility
        clean_data = convert_numpy(report_data)
        
        logger.info(f"Task {self.request.id}: Prediction completed successfully.")
        return clean_data

    except Exception as e:
        logger.error(f"Task {self.request.id} failed: {e}", exc_info=True)
        # Re-raise to mark task as failed in Celery
        raise e
