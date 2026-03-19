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
    def _calculate_breadth(target_date: Optional[str] = None, database=None) -> float:
        """
        Calculates market breadth: % of a sample of major stocks above their 50-day EMA.

        Args:
            target_date: Optional date to calculate breadth for
            database: MongoDB database instance. If None, uses global singleton.
        """
        majors = [
            'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'NVDA', 'BRK.B', 'JNJ', 'JPM',
            'V', 'PG', 'MA', 'HD', 'UNH', 'DIS', 'BAC', 'ADBE', 'CRM', 'XOM'
        ]
        above_ema = 0
        total = 0

        for symbol in majors:
            data = load_historical_data(symbol, database=database)
            if not data or not data.get('days'):
                continue
            df = pd.DataFrame(data['days'])
            if target_date:
                df['date'] = pd.to_datetime(df['date'])
                df = df[df['date'] <= pd.to_datetime(target_date)]
            if len(df) < 50:
                continue
            ema50 = df['close'].ewm(span=50).mean().iloc[-1]
            if df.iloc[-1]['close'] > ema50:
                above_ema += 1
            total += 1
        return (above_ema / total) if total > 0 else 0.5

    @staticmethod
    def _get_index_health(symbol: str, target_date: Optional[str] = None, database=None) -> tuple[int, Dict[str, Any]]:
        """
        Calculates the health score for a single index.

        Args:
            symbol: Index symbol (e.g., SPY, QQQ)
            target_date: Optional date to calculate health for
            database: MongoDB database instance. If None, uses global singleton.
        """
        data = load_historical_data(symbol, database=database)
        if not data or not data.get('days'):
            logging.warning("MarketRegime: No data for %s", symbol)
            return 0, {'status': 'Unknown'}

        df = pd.DataFrame(data['days'])
        if target_date:
            df['date'] = pd.to_datetime(df['date'])
            df = df[df['date'] <= pd.to_datetime(target_date)]
            if df.empty:
                return 0, {'status': 'Unknown'}

        if len(df) < 200:
            logging.warning("MarketRegime: Insufficient data for %s", symbol)
            return 0, {'status': 'Insufficient'}

        last_row = df.iloc[-1]
        close = last_row['close']
        ema20 = df['close'].ewm(span=20).mean().iloc[-1]
        ema50 = df['close'].ewm(span=50).mean().iloc[-1]
        ema200 = df['close'].ewm(span=200).mean().iloc[-1]
        trend = TechnicalAnalyzer.calculate_trend(df)

        symbol_score = 0
        if close > ema20:
            symbol_score += 1
        if close > ema50:
            symbol_score += 1
        if close > ema200:
            symbol_score += 1
        if "Downtrend" not in trend:
            symbol_score += 1

        details = {
            'score': symbol_score, 'trend': trend, 'close': close,
            'ema20': ema20, 'ema50': ema50, 'ema200': ema200
        }
        return symbol_score, details

    @staticmethod
    def _get_final_status(score: int) -> tuple[str, float]:
        """Determines the final market status and multiplier from the total score."""
        if score >= 8:
            return 'Bullish', 1.0
        if score >= 5:
            return 'Neutral', 0.5
        return 'Bearish', 0.0

    @staticmethod
    def get_market_health(target_date: Optional[str] = None, database=None) -> Dict[str, Any]:
        """
        Determines the current market regime using price action, EMAs, and Breadth.

        Args:
            target_date: Optional date to calculate health for
            database: MongoDB database instance. If None, uses global singleton.

        Returns:
            {
                'status': 'Bullish' | 'Neutral' | 'Bearish',
                'multiplier': 1.0 | 0.5 | 0.0,
                'details': { 'SPY': ..., 'QQQ': ..., 'breadth': ... }
            }
        """
        indices = ['SPY', 'QQQ']
        health_data = {}
        total_score = 0

        for symbol in indices:
            score, details = MarketRegime._get_index_health(symbol, target_date, database=database)
            total_score += score
            health_data[symbol] = details

        breadth = MarketRegime._calculate_breadth(target_date, database=database)
        if breadth > 0.6:
            total_score += 2
        elif breadth > 0.4:
            total_score += 1
        health_data['breadth'] = breadth

        # VIX contribution: low VIX = bullish, high = bearish
        from bluehorseshoe.data.vix import get_vix_snapshot
        vix = get_vix_snapshot(target_date) if target_date else None
        if vix:
            health_data['VIX'] = vix
            if vix['close'] <= 15:
                total_score += 2
            elif vix['close'] <= 20:
                total_score += 1
            elif vix['close'] > 30:
                total_score -= 1

        # AAII sentiment contribution (contrarian: bearish = bullish signal)
        from bluehorseshoe.data.aaii import get_aaii_snapshot  # pylint: disable=import-outside-toplevel
        aaii = get_aaii_snapshot(target_date) if target_date else None
        if aaii:
            health_data['AAII'] = aaii
            spread = aaii['bull_bear_spread']
            if spread <= -20:
                total_score += 2  # Extreme bearish → contrarian bullish
            elif spread <= -10:
                total_score += 1  # Bearish → contrarian mildly bullish
            elif spread >= 30:
                total_score -= 1  # Extreme bullish → contrarian bearish

        # CNN Fear & Greed contribution (high fear = contrarian bullish)
        from bluehorseshoe.data.cnn_fear_greed import get_cnn_snapshot  # pylint: disable=import-outside-toplevel
        cnn = get_cnn_snapshot(target_date) if target_date else None
        if cnn:
            health_data['CNN'] = cnn
            if cnn['score'] <= 25:
                total_score += 2   # Extreme Fear → contrarian bullish
            elif cnn['score'] <= 40:
                total_score += 1   # Fear → mildly bullish
            elif cnn['score'] >= 80:
                total_score -= 1   # Extreme Greed → contrarian bearish

        status, multiplier = MarketRegime._get_final_status(total_score)

        return {
            'status': status,
            'multiplier': multiplier,
            'score': total_score,
            'details': health_data
        }
