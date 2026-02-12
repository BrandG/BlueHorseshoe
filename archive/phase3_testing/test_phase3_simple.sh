#!/bin/bash
# Simple Phase 3 Testing - Uses prediction mode instead of backtests
# Tests indicators by generating predictions and analyzing scores

INDICATOR=$1
WEIGHT=$2

if [ -z "$INDICATOR" ] || [ -z "$WEIGHT" ]; then
    echo "Usage: ./test_phase3_simple.sh <INDICATOR> <WEIGHT>"
    echo "Example: ./test_phase3_simple.sh RS 1.0"
    echo ""
    echo "Available indicators: RS GAP VWAP TTM AROON KELTNER FORCE AD"
    exit 1
fi

echo "Testing $INDICATOR at ${WEIGHT}x weight..."

# Backup current config
cp src/weights.json src/weights.json.backup

# Create zero config with only test indicator enabled
case $INDICATOR in
    RS)
        CATEGORY="momentum"
        MULTIPLIER="RS_MULTIPLIER"
        ;;
    GAP)
        CATEGORY="price_action"
        MULTIPLIER="GAP_MULTIPLIER"
        ;;
    VWAP)
        CATEGORY="volume"
        MULTIPLIER="VWAP_MULTIPLIER"
        ;;
    TTM)
        CATEGORY="trend"
        MULTIPLIER="TTM_SQUEEZE_MULTIPLIER"
        ;;
    AROON)
        CATEGORY="trend"
        MULTIPLIER="AROON_MULTIPLIER"
        ;;
    KELTNER)
        CATEGORY="trend"
        MULTIPLIER="KELTNER_MULTIPLIER"
        ;;
    FORCE)
        CATEGORY="volume"
        MULTIPLIER="FORCE_INDEX_MULTIPLIER"
        ;;
    AD)
        CATEGORY="volume"
        MULTIPLIER="AD_LINE_MULTIPLIER"
        ;;
    *)
        echo "Unknown indicator: $INDICATOR"
        cp src/weights.json.backup src/weights.json
        exit 1
        ;;
esac

# Create test config (all zeros except test indicator)
cat > src/weights.json << EOF
{
  "trend": {
    "ADX_MULTIPLIER": 0.0,
    "STOCHASTIC_MULTIPLIER": 0.0,
    "ICHIMOKU_MULTIPLIER": 0.0,
    "PSAR_MULTIPLIER": 0.0,
    "HEIKEN_ASHI_MULTIPLIER": 0.0,
    "DONCHIAN_MULTIPLIER": 0.0,
    "SUPERTREND_MULTIPLIER": 0.0,
    "TTM_SQUEEZE_MULTIPLIER": 0.0,
    "AROON_MULTIPLIER": 0.0,
    "KELTNER_MULTIPLIER": 0.0
  },
  "momentum": {
    "RSI_MULTIPLIER": 0.0,
    "ROC_MULTIPLIER": 0.0,
    "MACD_MULTIPLIER": 0.0,
    "MACD_SIGNAL_MULTIPLIER": 0.0,
    "BB_MULTIPLIER": 0.0,
    "WILLIAMS_R_MULTIPLIER": 0.0,
    "CCI_MULTIPLIER": 0.0,
    "RS_MULTIPLIER": 0.0
  },
  "volume": {
    "OBV_MULTIPLIER": 0.0,
    "CMF_MULTIPLIER": 0.0,
    "ATR_BAND_MULTIPLIER": 0.0,
    "ATR_SPIKE_MULTIPLIER": 0.0,
    "MFI_MULTIPLIER": 0.0,
    "VWAP_MULTIPLIER": 0.0,
    "FORCE_INDEX_MULTIPLIER": 0.0,
    "AD_LINE_MULTIPLIER": 0.0
  },
  "candlestick": {
    "RISE_FALL_3_METHODS_MULTIPLIER": 0.0,
    "THREE_WHITE_SOLDIERS_MULTIPLIER": 0.0,
    "MARUBOZU_MULTIPLIER": 0.0,
    "BELT_HOLD_MULTIPLIER": 0.0
  },
  "mean_reversion": {
    "RSI_MULTIPLIER": 0.0,
    "BB_MULTIPLIER": 0.0,
    "MA_DIST_MULTIPLIER": 0.0,
    "CANDLESTICK_MULTIPLIER": 0.0
  },
  "price_action": {
    "GAP_MULTIPLIER": 0.0
  }
}
EOF

# Enable the test indicator
python3 << PYTHON_EOF
import json
with open('src/weights.json', 'r') as f:
    config = json.load(f)
config['$CATEGORY']['$MULTIPLIER'] = $WEIGHT
with open('src/weights.json', 'w') as f:
    json.dump(config, f, indent=2)
PYTHON_EOF

echo "Running prediction with $INDICATOR at ${WEIGHT}x..."
docker exec bluehorseshoe python src/main.py -p

echo ""
echo "✅ Test complete. Check results in:"
echo "   - src/graphs/report_*.html (latest report)"
echo "   - src/logs/report.txt (summary)"
echo ""
echo "Restoring original config..."
cp src/weights.json.backup src/weights.json
rm src/weights.json.backup

echo "Done!"
