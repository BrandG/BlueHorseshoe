#!/bin/bash
echo "Starting Full Rebuild and Training Sequence..."
export PYTHONPATH=$PYTHONPATH:/workspaces/BlueHorseshoe/src

echo "1. Rebuilding Scores (Jan 2025)..."
python src/rebuild_scores.py 2025-01-01 2025-01-31 > src/logs/rebuild_jan2025_full.log 2>&1
echo "Score Rebuild Complete."

echo "2. Running Grading..."
# Increased limit to ensure all Jan scores are processed if needed, though run_grading defaults might handle it.
python src/run_grading.py --save --limit 100000 > src/logs/grading_jan2025.log 2>&1
echo "Grading Complete."

echo "3. Training ML Overlay..."
python src/train_ml_overlay.py > src/logs/train_ml_overlay.log 2>&1
echo "ML Overlay Training Complete."

echo "4. Training Stop Loss Model..."
python src/train_stop_loss.py > src/logs/train_stop_loss.log 2>&1
echo "Stop Loss Training Complete."

echo "All tasks finished."
