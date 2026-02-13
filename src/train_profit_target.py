"""
Script to train the ML profit target prediction model.
"""
import logging
import sys
# pylint: disable=wrong-import-position
from bluehorseshoe.analysis.ml_profit_target import ProfitTargetTrainer
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
        trainer = ProfitTargetTrainer(database=container.get_database())
        # Train all three models (v1, baseline, mean_reversion)
        trainer.retrain_all(limit=limit, before_date=before_date)
    finally:
        container.close()
