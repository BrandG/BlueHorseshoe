"""
This module provides functions for swing trading analysis.

The module includes functions to calculate entry and exit points for trading based on historical price data and 
a temporary prediction function to identify top buy candidates.

Functions:
    get_entry_exit_points(price_data): Calculate entry and exit points for trading based on price data.
    swing_predict(): Temporary prediction function to identify top buy candidates.
"""
import numpy as np
import pandas as pd
from globals import ReportSingleton, get_symbol_name_list
from historical_data import load_historical_data

def calculate_trend(df, period=20):
    if len(df) < period:
        return "Insufficient data"

    # Linear regression of closing prices
    x = np.arange(period)
    y = df['close'].rolling(period).apply(lambda z: np.polyfit(np.arange(len(z)), z, 1)[0], raw=True)
    
    # Calculate R-squared value
    def calculate_r2(z):
        slope, intercept = np.polyfit(np.arange(len(z)), z, 1)
        y_pred = slope * np.arange(len(z)) + intercept
        ss_res = np.sum((z - y_pred) ** 2)
        ss_tot = np.sum((z - np.mean(z)) ** 2)
        return 1 - (ss_res / ss_tot)
    
    r2 = df['close'].rolling(period).apply(calculate_r2, raw=True)
    
    # Trend strength based on slope and R-squared
    slope = y.iloc[-1]
    r2_value = r2.iloc[-1]
    
    # Categorize trend
    trend = "No Clear Trend"
    if slope > 0 and r2_value > 0.7:
        trend = "Strong Uptrend"
    elif slope > 0 and r2_value > 0.3:
        trend = "Weak Uptrend"
    elif slope < 0 and r2_value > 0.7:
        trend = "Strong Downtrend"
    elif slope < 0 and r2_value > 0.3:
        trend = "Weak Downtrend"
    ReportSingleton().write(f'Trend: {trend} - Slope: {slope:.2f} - R2: {r2_value:.2f}')
    return trend

def calculate_entry_price(df):
    entry_price = df.iloc[-1]['close']
    trend = calculate_trend(df)
    if trend == "Strong Uptrend":
        entry_price *= 1.05
    elif trend == "Weak Uptrend":
        entry_price *= 1.01
    elif trend == "Strong Downtrend":
        entry_price *= 0.95
    elif trend == "Weak Downtrend":
        entry_price *= 0.99

    return entry_price

def calculate_technical_score(df):
    """
    Calculate the technical score for a given stock based on various technical indicators.
    The score is calculated based on the following criteria:
    - Trend Strength (0-3 points)
    - Price Action (0-3 points)
    - MACD Strength (0-2 points)
    - Volume (0-2 points)
    - RSI (0-2 points)
    - Rate of Change (0-2 points)
    - DMIs (0-1 points)
    - Bollinger Bands (0-3 points)
    The maximum possible score is 18.
    Parameters:
    df (pandas.DataFrame): A DataFrame containing the following columns:
        - 'avg_volume_20': Average volume over the last 20 days
        - 'adx': Average Directional Index
        - 'close': Closing price
        - 'ema_20': 20-day Exponential Moving Average
        - 'macd_line': MACD line value
        - 'macd_signal': MACD signal line value
        - 'volume': Current volume
        - 'rsi_14': 14-day Relative Strength Index
        - 'roc_5': 5-day Rate of Change
        - 'dmi_p': Positive Directional Movement Index
        - 'dmi_n': Negative Directional Movement Index
        - 'bb_lower': Lower Bollinger Band
        - 'bb_upper': Upper Bollinger Band
    Returns:
    int: The calculated technical score.
    """
    score = 0
    
    if df['avg_volume_20'] < 10000:
        return score
    
    # Trend Strength (0-3 points)
    if df['adx'] > 35:
        score += 3
    elif df['adx'] > 30:
        score += 2
    elif df['adx'] > 25:
        score += 1

    # Price Action (0-3 points)
    ema_margin = (df['close'] - df['ema_20']) / df['ema_20'] * 100
    if ema_margin > 3:
        score += 3
    elif ema_margin > 2:
        score += 2
    elif ema_margin > 1:
        score += 1
    
    # MACD Strength (0-2 points)
    macd_diff = df['macd_line'] - df['macd_signal']
    if macd_diff > 0 and df['macd_line'] > 0:
        score += 2 if macd_diff > df['macd_signal'] * 0.15 else 1

    # Volume (0-2 points)
    vol_ratio = df['volume'] / df['avg_volume_20']
    score += 2 if vol_ratio > 2 else 1 if vol_ratio > 1.5 else 0
    
    # RSI (0-2 points)
    if 45 < df['rsi_14'] < 65:
        score += 2
    elif 40 < df['rsi_14'] < 70:
        score += 1

    # Rate of Change (0-2 points)
    if df['roc_5'] > 2:
        score += 2
    elif df['roc_5'] > 1:
        score += 1
    
    # DMIs (0-1 points)
    score += 1 if df['dmi_p'] > df['dmi_n'] else 0

    # Bollinger Bands (0-3 points)
    bb_position = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    
    if 0.3 < bb_position < 0.7:  # Price in middle band - trend continuation
        score += 2
    elif 0.1 < bb_position < 0.3:  # Near lower band - potential bounce
        score += 3
    elif bb_position > 0.85:  # Near upper band - overbought
        score -= 1

    return score  # Max score: 18

def get_entry_exit_points(price_data):
    """
    Calculate entry and exit points for trading based on price data.

    This function analyzes the provided price data to determine potential entry and exit points for trading. 
    It calculates a score for the most recent day based on various indicators and sets the entry price, 
    stop loss, and take profit levels.

    Args:
        price_data (dict): A dictionary containing price data with the following structure:
            {
                'days': [
                    {
                        'close': float,
                        'ema_20': float,
                        'macd_line': float,
                        'macd_signal': float,
                        'adx': float,
                        'high': float,
                        'atr_14': float
                    },
                    ...
                ]
            }

    Returns:
        dict: The updated price data dictionary with added entry and exit points for the most recent day.
    """
    if len(price_data['days']) < 2 :
        return price_data
    
    yesterday = price_data['days'][-1]

    yesterday['score'] = calculate_technical_score(yesterday)

    yesterday['entry_price'] = calculate_entry_price(pd.DataFrame(price_data['days']))
    yesterday['stop_loss'] = yesterday['entry_price'] * 0.96
    yesterday['take_profit'] = yesterday['entry_price'] * 1.04

    return price_data

def swing_predict():
    """
    Temporary Prediction function

    Returns:
        None
    """
    symbols = get_symbol_name_list()
    results = []
    for _, symbol in enumerate(symbols):
        ReportSingleton().write(f'Processing {symbol}...')
        price_data = load_historical_data(symbol)
        if price_data is None:
            ReportSingleton().write(f"Failed to load historical data for {symbol}.")
            return
        price_data = get_entry_exit_points(price_data)
        yesterday = price_data['days'][-1]
        if 'entry_price' in yesterday and 'stop_loss' in yesterday and 'take_profit' in yesterday and 'score' in yesterday \
            and 50 > yesterday['entry_price'] > 5.0 :
            results.append({'symbol': symbol, 'entry_price': yesterday['entry_price'], 'stop_loss': yesterday['stop_loss'],
                            'take_profit': yesterday['take_profit'], 'score': yesterday['score']})
            # ReportSingleton().write(f'{yesterday["date"]} - {symbol} - Entry: {yesterday["entry_price"]} - Stop-Loss: {yesterday["stop_loss"]} - '
            # f'Take-Profit: {yesterday["take_profit"]}')
    sorted_days = sorted(results, key=lambda x: x.get('score', 0), reverse=True)
    ReportSingleton().write('Top 10 buy candidates:')
    for i in range(min(10, len(sorted_days))):
        ReportSingleton().write(f'{sorted_days[i]["symbol"]} - Entry: {sorted_days[i]["entry_price"]:.2f} -' \
                    f' Stop-Loss: {sorted_days[i]["stop_loss"]:.2f} - Take-Profit: {sorted_days[i]["take_profit"]:.2f} -' \
                    f' Score: {sorted_days[i]["score"]:.2f}')
