"""
Entry point for training the ML Overlay model.
"""
import logging
import sys
from bluehorseshoe.analysis.ml_overlay import MLOverlayTrainer

if __name__ == "__main__":
    # Configure logging to both file and console
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    
    # Console Handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    # File Handler
    fh = logging.FileHandler("src/logs/ml_training.log", mode='w')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    limit = 5000
    before_date = None
    
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass
            
    if len(sys.argv) > 2:
        before_date = sys.argv[2]
            
    logging.info(f"Starting ML Overlay training with limit={limit}, before={before_date}...")
    trainer = MLOverlayTrainer()
    
    trainer.retrain_all(limit=limit, before_date=before_date)
    
    logging.info("Training process complete.")
