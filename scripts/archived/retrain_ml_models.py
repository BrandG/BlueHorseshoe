#!/usr/bin/env python3
"""
Retrain ML models with Phase 1 optimized weights.

This script retrains both the Win Probability and Stop Loss models
using historical graded trades scored with Phase 1 optimal weights.
"""

import logging
import sys
from pymongo import MongoClient

# Add src to path
sys.path.insert(0, '/workspaces/BlueHorseshoe/src')

from bluehorseshoe.analysis.ml_overlay import MLOverlayTrainer
from bluehorseshoe.analysis.ml_stop_loss import StopLossTrainer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def check_training_data(database):
    """Check how much training data we have available."""
    scores_collection = database['trade_scores']

    # Count total scored trades
    total_scores = scores_collection.count_documents({})

    # Count trades with entry prices (graded trades)
    graded_trades = scores_collection.count_documents({
        "metadata.entry_price": {"$exists": True}
    })

    # Count by strategy
    baseline_trades = scores_collection.count_documents({
        "metadata.entry_price": {"$exists": True},
        "strategy": "baseline"
    })

    mean_reversion_trades = scores_collection.count_documents({
        "metadata.entry_price": {"$exists": True},
        "strategy": "mean_reversion"
    })

    logging.info("=" * 80)
    logging.info("TRAINING DATA AVAILABILITY")
    logging.info("=" * 80)
    logging.info(f"Total scored trades: {total_scores:,}")
    logging.info(f"Graded trades (with outcomes): {graded_trades:,}")
    logging.info(f"  - Baseline strategy: {baseline_trades:,}")
    logging.info(f"  - Mean Reversion strategy: {mean_reversion_trades:,}")
    logging.info("=" * 80)

    return graded_trades

def retrain_win_probability_models(database, limit=10000):
    """Retrain the Win Probability ML models."""
    logging.info("\n" + "=" * 80)
    logging.info("RETRAINING WIN PROBABILITY MODELS")
    logging.info("=" * 80)

    trainer = MLOverlayTrainer(database=database)

    # Retrain all models (general, baseline, mean_reversion)
    # Use before_date to prevent look-ahead bias (use data before 2026-01-27)
    before_date = "2026-01-27"

    logging.info(f"\nTraining with limit={limit}, before_date={before_date}")
    trainer.retrain_all(limit=limit, before_date=before_date)

    logging.info("\n✅ Win Probability models retrained successfully!")

def retrain_stop_loss_model(database, limit=10000):
    """Retrain the Stop Loss ML model."""
    logging.info("\n" + "=" * 80)
    logging.info("RETRAINING STOP LOSS MODEL")
    logging.info("=" * 80)

    trainer = StopLossTrainer(database=database)

    # Use before_date to prevent look-ahead bias
    before_date = "2026-01-27"

    logging.info(f"\nTraining with limit={limit}, before_date={before_date}")
    trainer.train(limit=limit, before_date=before_date)

    logging.info("\n✅ Stop Loss model retrained successfully!")

def main():
    """Main retraining workflow."""
    logging.info("=" * 80)
    logging.info("ML MODEL RETRAINING - Phase 1 Optimized Weights")
    logging.info("=" * 80)

    # Connect to MongoDB
    client = MongoClient('mongodb://mongo:27017')
    database = client['bluehorseshoe']

    # Check available training data
    graded_trades = check_training_data(database)

    if graded_trades < 100:
        logging.error("\n❌ Insufficient training data!")
        logging.error(f"Found {graded_trades} graded trades, need at least 100")
        logging.error("Run more backtests first to generate training data:")
        logging.error("  docker exec bluehorseshoe python src/main.py -t 2026-01-20 --end 2026-01-27")
        return

    # Determine training limit based on available data
    training_limit = min(10000, graded_trades)
    logging.info(f"\nUsing {training_limit:,} samples for training")

    # Retrain both models
    try:
        retrain_win_probability_models(database, limit=training_limit)
        retrain_stop_loss_model(database, limit=training_limit)

        logging.info("\n" + "=" * 80)
        logging.info("✅ ALL MODELS RETRAINED SUCCESSFULLY!")
        logging.info("=" * 80)
        logging.info("\nNew models saved to:")
        logging.info("  - src/models/ml_overlay_v1.joblib (general)")
        logging.info("  - src/models/ml_overlay_baseline.joblib")
        logging.info("  - src/models/ml_overlay_mean_reversion.joblib")
        logging.info("  - src/models/ml_stop_loss_v1.joblib")
        logging.info("\nThese models will be used in the next prediction run.")

    except Exception as e:
        logging.error(f"\n❌ Error during retraining: {e}", exc_info=True)
        raise
    finally:
        client.close()

if __name__ == "__main__":
    main()
