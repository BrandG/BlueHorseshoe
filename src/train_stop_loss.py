import logging
import sys
from bluehorseshoe.analysis.ml_stop_loss import StopLossTrainer

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    limit = 5000
    before_date = None

    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass

    if len(sys.argv) > 2:
        before_date = sys.argv[2]

    trainer = StopLossTrainer()
    trainer.train(limit=limit, before_date=before_date)
