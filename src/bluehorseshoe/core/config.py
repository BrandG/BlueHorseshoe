"""
Configuration management for BlueHorseshoe, handling weights for various technical indicators.
"""
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
    },
    'mean_reversion': {
        'RSI_MULTIPLIER': 0.0,
        'BB_MULTIPLIER': 1.0,
        'MA_DIST_MULTIPLIER': 1.0,
        'CANDLESTICK_MULTIPLIER': 1.0
    }
}

class ConfigManager:
    """
    Singleton class to manage application configuration and weights.
    """
    _instance = None
    _weights = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance.load_weights()
        return cls._instance

    def load_weights(self):
        """Loads weights from the JSON file or uses defaults if loading fails."""
        if os.path.exists(WEIGHTS_FILE):
            try:
                with open(WEIGHTS_FILE, 'r', encoding='utf-8') as f:
                    self._weights = json.load(f)
                logging.info("Weights loaded from %s", WEIGHTS_FILE)
            except (json.JSONDecodeError, OSError) as e:
                logging.error("Error loading weights: %s. Using defaults.", e)
                self._weights = DEFAULT_WEIGHTS.copy()
        else:
            self._weights = DEFAULT_WEIGHTS.copy()
            self.save_weights()

    def save_weights(self):
        """Saves current weights to the JSON file."""
        try:
            with open(WEIGHTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._weights, f, indent=4)
            logging.info("Weights saved to %s", WEIGHTS_FILE)
        except OSError as e:
            logging.error("Error saving weights: %s", e)

    def get_weights(self, category):
        """Returns the weights for a specific indicator category."""
        return self._weights.get(category, DEFAULT_WEIGHTS.get(category, {}))

    def update_weights(self, category, new_weights):
        """Updates and persists weights for a specific category."""
        if category not in self._weights:
            self._weights[category] = {}
        self._weights[category].update(new_weights)
        self.save_weights()

weights_config = ConfigManager()
