#!/bin/bash
# Run split-exit comparison one date at a time to stay within memory limits.
# Each date gets its own CSV in src/logs/split_comparison_<date>.csv
# Results are also appended to a combined log for easy review.

COMBINED_LOG="src/logs/split_comparison_combined.log"
DATES="2025-10-01 2025-10-15 2025-10-29 2025-11-12 2025-11-26 2025-12-10 2025-12-24 2026-01-07 2026-01-21 2026-02-04"
TOTAL=10
COUNT=0

echo "=== Split-Exit Comparison: $TOTAL dates ===" | tee "$COMBINED_LOG"
echo "Started: $(date)" | tee -a "$COMBINED_LOG"
echo "" | tee -a "$COMBINED_LOG"

for DATE in $DATES; do
    COUNT=$((COUNT + 1))
    echo "--- [$COUNT/$TOTAL] $DATE ---" | tee -a "$COMBINED_LOG"

    docker exec bluehorseshoe python src/compare_split_exit.py "$DATE" \
        --hold 10 --top 20 --workers 1 2>&1 | tee -a "$COMBINED_LOG"

    EXIT_CODE=${PIPESTATUS[0]}
    if [ $EXIT_CODE -ne 0 ]; then
        echo "FAILED: $DATE (exit code $EXIT_CODE)" | tee -a "$COMBINED_LOG"
        echo "Stopping. Completed $((COUNT - 1))/$TOTAL dates." | tee -a "$COMBINED_LOG"
        exit 1
    fi

    echo "DONE: $DATE" | tee -a "$COMBINED_LOG"
    echo "" | tee -a "$COMBINED_LOG"
done

echo "=== All $TOTAL dates completed ===" | tee -a "$COMBINED_LOG"
echo "Finished: $(date)" | tee -a "$COMBINED_LOG"
