"""
Script to train the ML stop loss prediction model.
"""
import logging
import sys
# pylint: disable=wrong-import-position
from bluehorseshoe.analysis.ml_stop_loss import StopLossTrainer
from bluehorseshoe.core.container import create_app_container

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

    container = create_app_container()
    try:
        trainer = StopLossTrainer(database=container.get_database())
        trainer.train(limit=limit, before_date=before_date)
    finally:
        container.close()