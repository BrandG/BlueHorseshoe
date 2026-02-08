#!/bin/bash
# Monitor Phase 3B Testing Progress

LOG_FILE="/tmp/claude-0/-root-BlueHorseshoe/5952837e-749b-4aea-adcc-7f60542c2fe9/scratchpad/phase3b_testing.log"
CSV_FILE="/root/BlueHorseshoe/src/logs/backtest_log.csv"

echo "========================================"
echo "Phase 3B Testing Monitor"
echo "========================================"
echo ""

# Check if process is running
if ps -p 159838 > /dev/null 2>&1; then
    echo "Status: ✅ RUNNING"
    ELAPSED=$(ps -p 159838 -o etime=)
    echo "Elapsed time: $ELAPSED"
else
    echo "Status: ⚠️  COMPLETED or STOPPED"
fi

echo ""
echo "Last 15 lines of output:"
echo "----------------------------------------"
tail -15 "$LOG_FILE"

echo ""
echo "========================================"
echo "CSV Statistics:"
echo "----------------------------------------"
TRADE_COUNT=$(tail -n +2 "$CSV_FILE" | wc -l)
echo "Total trades logged: $TRADE_COUNT"

echo ""
echo "Commands:"
echo "  Full log: tail -f $LOG_FILE"
echo "  CSV: cat $CSV_FILE | tail -20"
echo "========================================"
