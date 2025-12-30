import json
import os
import logging

WEIGHTS_FILE = '/workspaces/BlueHorseshoe/src/weights.json'

DEFAULT_WEIGHTS = {
    'trend': {
        'ADX_MULTIPLIER': 1.0,
        'STOCHASTIC_MULTIPLIER': 1.0,
        'ICHIMOKU_MULTIPLIER': 1.0,
        'PSAR_MULTIPLIER': 1.0,
        'HEIKEN_ASHI_MULTIPLIER': 1.0
    },
    'momentum': {
        'RSI_MULTIPLIER': 1.0,
        'ROC_MULTIPLIER': 1.0,
        'MACD_MULTIPLIER': 1.0,
        'MACD_SIGNAL_MULTIPLIER': 0.15,
        'BB_MULTIPLIER': 1.0
    },
    'volume': {
        'OBV_MULTIPLIER': 1.0,
        'CMF_MULTIPLIER': 1.0,
        'ATR_BAND_MULTIPLIER': 1.0,
        'ATR_SPIKE_MULTIPLIER': 1.0
    },
    'candlestick': {
        'RISE_FALL_3_METHODS_MULTIPLIER': 1.0,
        'THREE_WHITE_SOLDIERS_MULTIPLIER': 1.0,
        'MARUBOZU_MULTIPLIER': 1.0,
        'BELT_HOLD_MULTIPLIER': 1.0
    }
}

class ConfigManager:
    _instance = None
    _weights = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance.load_weights()
        return cls._instance

    def load_weights(self):
        if os.path.exists(WEIGHTS_FILE):
            try:
                with open(WEIGHTS_FILE, 'r') as f:
                    self._weights = json.load(f)
                logging.info("Weights loaded from %s", WEIGHTS_FILE)
            except Exception as e:
                logging.error("Error loading weights: %s. Using defaults.", e)
                self._weights = DEFAULT_WEIGHTS.copy()
        else:
            self._weights = DEFAULT_WEIGHTS.copy()
            self.save_weights()

    def save_weights(self):
        try:
            with open(WEIGHTS_FILE, 'w') as f:
                json.dump(self._weights, f, indent=4)
            logging.info("Weights saved to %s", WEIGHTS_FILE)
        except Exception as e:
            logging.error("Error saving weights: %s", e)

    def get_weights(self, category):
        return self._weights.get(category, DEFAULT_WEIGHTS.get(category, {}))

    def update_weights(self, category, new_weights):
        if category not in self._weights:
            self._weights[category] = {}
        self._weights[category].update(new_weights)
        self.save_weights()

weights_config = ConfigManager()
