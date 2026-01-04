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
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass
            
    logging.info(f"Starting ML Overlay training with limit={limit}...")
    trainer = MLOverlayTrainer()
    
    # 1. Train General Model
    logging.info("Training GENERAL model...")
    trainer.train(limit=limit, output_path="src/models/ml_overlay_v1.joblib")
    
    # 2. Train Strategy-Specific Models
    logging.info("Training BASELINE model...")
    trainer.train(limit=limit, strategy="baseline", output_path="src/models/ml_overlay_baseline.joblib")
    
    logging.info("Training MEAN REVERSION model...")
    trainer.train(limit=limit, strategy="mean_reversion", output_path="src/models/ml_overlay_mean_reversion.joblib")
    
    logging.info("Training process complete.")
