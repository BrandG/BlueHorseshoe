"""
Configuration management for BlueHorseshoe, handling application settings and indicator weights.
"""
import json
import os
import logging
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# Derive repo root from this file's location:
#   config.py is at src/bluehorseshoe/core/config.py → parents[3] = repo root
REPO_ROOT = str(Path(__file__).resolve().parents[3])

WEIGHTS_FILE = os.environ.get('WEIGHTS_FILE', f'{REPO_ROOT}/src/weights.json')
WEIGHTS_V2_FULL_FILE = os.environ.get('WEIGHTS_V2_FULL_FILE', f'{REPO_ROOT}/src/weights_v2_full.json')
WEIGHTS_V3_FILE = os.environ.get('WEIGHTS_V3_FILE', f'{REPO_ROOT}/src/weights.json')

DEFAULT_WEIGHTS = {
    'trend': {
        'ADX_MULTIPLIER': 1.0,
        'STOCHASTIC_MULTIPLIER': 1.0,
        'ICHIMOKU_MULTIPLIER': 1.0,
        'PSAR_MULTIPLIER': 1.0,
        'HEIKEN_ASHI_MULTIPLIER': 1.0,
        'DONCHIAN_MULTIPLIER': 1.0,
        'SUPERTREND_MULTIPLIER': 1.0,
        'TTM_SQUEEZE_MULTIPLIER': 1.0,
        'AROON_MULTIPLIER': 1.0,
        'KELTNER_MULTIPLIER': 1.0
    },
    'momentum': {
        'RSI_MULTIPLIER': 1.0,
        'ROC_MULTIPLIER': 1.0,
        'MACD_MULTIPLIER': 1.0,
        'MACD_SIGNAL_MULTIPLIER': 0.15,
        'BB_MULTIPLIER': 1.0,
        'WILLIAMS_R_MULTIPLIER': 1.0,
        'CCI_MULTIPLIER': 1.0
    },
    'volume': {
        'OBV_MULTIPLIER': 1.0,
        'CMF_MULTIPLIER': 1.0,
        'ATR_BAND_MULTIPLIER': 1.0,
        'ATR_SPIKE_MULTIPLIER': 1.0,
        'MFI_MULTIPLIER': 1.0,
        'VWAP_MULTIPLIER': 1.0,
        'FORCE_INDEX_MULTIPLIER': 1.0,
        'AD_LINE_MULTIPLIER': 1.0
    },
    'candlestick': {
        'RISE_FALL_3_METHODS_MULTIPLIER': 1.0,
        'THREE_WHITE_SOLDIERS_MULTIPLIER': 1.0,
        'MARUBOZU_MULTIPLIER': 1.0,
        'BELT_HOLD_MULTIPLIER': 1.0
    },
    'mean_reversion': {
        'RSI_MULTIPLIER': 1.0,
        'BB_MULTIPLIER': 1.0,
        'MA_DIST_MULTIPLIER': 1.0,
        'CANDLESTICK_MULTIPLIER': 1.0
    },
    'price_action': {
        'GAP_MULTIPLIER': 1.0
    },
    'mr_trend': {
        'ADX_MULTIPLIER': 0.5,
        'STOCHASTIC_MULTIPLIER': 0.0,
        'ICHIMOKU_MULTIPLIER': 1.5,
        'PSAR_MULTIPLIER': 0.0,
        'HEIKEN_ASHI_MULTIPLIER': 0.0,
        'DONCHIAN_MULTIPLIER': 2.0,
        'SUPERTREND_MULTIPLIER': 1.5,
        'TTM_SQUEEZE_MULTIPLIER': 1.5,
        'AROON_MULTIPLIER': 1.0,
        'KELTNER_MULTIPLIER': 2.0,
        'SCORE_ACCEL_MULTIPLIER': 0.0,
    },
    'mr_momentum': {
        'RSI_MULTIPLIER': 0.0,
        'ROC_MULTIPLIER': 1.5,
        'MACD_MULTIPLIER': 1.0,
        'MACD_SIGNAL_MULTIPLIER': 0.15,
        'BB_MULTIPLIER': 0.0,
        'WILLIAMS_R_MULTIPLIER': 0.0,
        'CCI_MULTIPLIER': 0.0,
        'RS_MULTIPLIER': 0.0,
    },
    'mr_volume': {
        'OBV_MULTIPLIER': 0.0,
        'CMF_MULTIPLIER': 0.0,
        'ATR_BAND_MULTIPLIER': 0.0,
        'ATR_SPIKE_MULTIPLIER': 0.0,
        'MFI_MULTIPLIER': 0.0,
        'VWAP_MULTIPLIER': 1.5,
        'FORCE_INDEX_MULTIPLIER': 0.0,
        'AD_LINE_MULTIPLIER': 1.5,
    },
    'mr_candlestick': {
        'RISE_FALL_3_METHODS_MULTIPLIER': 0.0,
        'THREE_WHITE_SOLDIERS_MULTIPLIER': 0.0,
        'MARUBOZU_MULTIPLIER': 0.0,
        'BELT_HOLD_MULTIPLIER': 0.0,
    },
    'mr_price_action': {
        'GAP_MULTIPLIER': 0.0,
    },
    'mean_reversion_specific': {
        'RSI_DIVERGENCE_MULTIPLIER': 0.0,
        'ZSCORE_MULTIPLIER': 0.0,
        'CONNORS_RSI_MULTIPLIER': 0.0,
        'DV2_MULTIPLIER': 0.0,
        'SHORT_ROC_MULTIPLIER': 0.0,
    },
    'mr_mean_reversion_specific': {
        'RSI_DIVERGENCE_MULTIPLIER': 2.0,
        'ZSCORE_MULTIPLIER': 1.5,
        'CONNORS_RSI_MULTIPLIER': 1.5,
        'DV2_MULTIPLIER': 1.0,
        'SHORT_ROC_MULTIPLIER': 1.5,
    },
}

class Settings(BaseSettings):
    """
    Application-wide settings loaded from environment variables.
    Uses Pydantic BaseSettings for validation and .env file support.
    """
    # MongoDB
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "bluehorseshoe"

    # File Paths
    base_path: str = f"{REPO_ROOT}/src/historical_data"
    logs_path: str = f"{REPO_ROOT}/src/logs"
    graphs_path: str = f"{REPO_ROOT}/src/graphs"
    weights_path: str = f"{REPO_ROOT}/src/weights.json"

    # Alpha Vantage API
    alphavantage_key: str = ""
    alphavantage_cps: int = 2

    # Tiingo API
    tiingo_api_key: str = ""
    tiingo_cps: int = 5

    # IBKR Gateway
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 4004
    ibkr_client_id: int = 1

    # Paper Trading
    paper_trading_enabled: bool = False
    paper_total_investment: float = 10000.0
    paper_max_positions: int = 10
    # Reserved slots for the deep_oversold sleeve (of paper_max_positions).
    # 0 disables the reservation entirely → pure global top-N by score across all
    # paper_tradeable sleeves. Disabled 2026-06-07: with the live book now exactly
    # {deep_oversold, deep_oversold_ha} (both gauntlet-validated and on the same
    # score scale), there's no weaker tier to protect a floor from — let the
    # highest scores win the slots. Set >0 again to floor-reserve a sleeve.
    paper_slots_deep_oversold: int = 0
    # Conviction-weighted sizing (2026-06-07): split the pot proportional to each
    # sleeve's validated per-trade R (edge_weight) instead of flat-equal, so a
    # higher-edge fill gets more capital. The pot is unchanged (len(selected)*base),
    # so total deployment matches flat sizing — only the DISTRIBUTION tilts. Reduces
    # exactly to flat when the book is one sleeve. False = legacy flat sizing.
    paper_conviction_sizing: bool = True
    # Cap on any single position, as a multiple of the equal-weight slot (base =
    # total/max_positions). Bounds single-name concentration; 2.5 = up to 25% of
    # capital at default config. Excess above the cap is left undeployed.
    paper_max_position_mult: float = 2.5
    # Fractional shares (2026-06-07): deploy exact target dollars instead of flooring
    # to whole shares. Code is complete and correct, but DEFAULT IS FALSE because the
    # IBKR account currently REJECTS API fractional orders:
    #   Error 10243 "Fractional-sized order cannot be placed via API" (verified via
    #   src/verify_fractional_bracket.py on paper acct DUE616654, 2026-06-07).
    # With conviction sizing almost every order is fractional, so True here would make
    # the broker reject EVERY bracket → zero fills. Re-enable ONLY after enabling
    # fractional-share trading on the IBKR account AND re-running the verify script to
    # a PASS. Until then this stays False and we floor to whole shares (tiny leak).
    paper_fractional_shares: bool = False
    paper_fractional_precision: int = 4    # decimals to round fractional share qty
    paper_min_order_value: float = 1.0     # skip positions whose notional is below this ($)
    # Fill-anchored execution: false preserves the legacy all-at-once bracket
    # submission. True stages during -p and attaches exits after the real fill
    # via --execute-open.
    fill_anchored_execution: bool = False

    # Yahoo Finance
    yahoo_enabled: bool = True
    yahoo_cps: int = 1

    # Alpha Vantage data fetching (key already in Settings; this enables EOD use)
    alphavantage_data_enabled: bool = True

    # Provider pool
    provider_max_retries: int = 1

    # DuckDB
    duckdb_path: str = f"{REPO_ROOT}/data/ohlcv.duckdb"

    # Feature Flags
    holiday_mode: bool = False
    deep_oversold_nonbull_gate: bool = False
    deep_oversold_solvency_filter: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )

# Singleton instance for settings (lazy-loaded)
_settings_instance: Optional[Settings] = None

def get_settings() -> Settings:
    """
    Get or create the settings singleton instance.
    This allows environment variables to be loaded once and reused.
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance

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

    def load_regime_weights(self):
        """Loads and caches both V2-full and V3 weight dicts for regime-adaptive selection."""
        if not hasattr(self, '_regime_weights'):
            self._regime_weights = {}
        for label, path in [('v2', WEIGHTS_V2_FULL_FILE), ('v3', WEIGHTS_V3_FILE)]:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    self._regime_weights[label] = json.load(f)
                logging.info("Regime weights loaded: %s from %s", label, path)
            else:
                logging.warning("Regime weights file not found: %s", path)

    def select_weights_for_regime(self, score: int) -> str:
        """Picks V2 or V3 weights based on regime score and swaps self._weights.

        Rule: V3 for extreme regimes (score <= 2 or >= 9), V2 for favorable (3-8).

        Returns:
            Label string ('v2' or 'v3') indicating which weights were selected.
        """
        if not hasattr(self, '_regime_weights') or not self._regime_weights:
            self.load_regime_weights()

        if score <= 2 or score >= 9:
            label = 'v3'
        else:
            label = 'v2'

        if label in self._regime_weights:
            self._weights = self._regime_weights[label].copy()
            logging.info("Regime score %d → %s weights active", score, label.upper())
        else:
            logging.warning("Regime weights '%s' not cached, keeping current weights", label)

        return label

weights_config = ConfigManager()
