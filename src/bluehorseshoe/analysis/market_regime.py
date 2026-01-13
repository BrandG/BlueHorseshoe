"""
Module for analyzing market regime and health.
"""
import logging
from typing import Dict, Any, Optional
import pandas as pd
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer

class MarketRegime:
    """
    Analyzes overall market health using major indices (SPY, QQQ).
    Used as a "Circuit Breaker" to reduce risk during downturns.
    """
    # pylint: disable=too-few-public-methods

    @staticmethod
    def get_market_health(target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Determines the current market regime.
        Returns:
            {
                'status': 'Bullish' | 'Neutral' | 'Bearish',
                'multiplier': 1.0 | 0.5 | 0.0,
                'details': { 'SPY': ..., 'QQQ': ... }
            }
        """
        indices = ['SPY', 'QQQ']
        health_data = {}
        bullish_count = 0

        for symbol in indices:
            data = load_historical_data(symbol)
            if not data or not data.get('days'):
                logging.warning("MarketRegime: No data for %s", symbol)
                health_data[symbol] = 'Unknown'
                continue

            df = pd.DataFrame(data['days'])
            if target_date:
                df['date'] = pd.to_datetime(df['date'])
                df = df[df['date'] <= pd.to_datetime(target_date)]
                if df.empty:
                    health_data[symbol] = 'Unknown'
                    continue

            last_row = df.iloc[-1]

            # Simple health check: Price > EMA 20 and Trend is not Downtrend
            ema20 = last_row.get('ema_20')
            close = last_row['close']
            trend = TechnicalAnalyzer.calculate_trend(df)

            is_bullish = False
            if ema20 and close > ema20 and "Downtrend" not in trend:
                is_bullish = True
                bullish_count += 1

            health_data[symbol] = {
                'bullish': is_bullish,
                'trend': trend,
                'close': close,
                'ema20': ema20
            }

        # Logic for overall status
        if bullish_count == 2:
            status = 'Bullish'
            multiplier = 1.0
        elif bullish_count == 1:
            status = 'Neutral'
            multiplier = 0.5
        else:
            status = 'Bearish'
            multiplier = 0.0 # or 0.25 depending on risk appetite

        return {
            'status': status,
            'multiplier': multiplier,
            'details': health_data
        }
