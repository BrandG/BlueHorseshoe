"""
Legacy trading strategy module.
"""
import pandas as pd

def calculate_technical_indicators(days_list):
    """
    Calculates technical indicators for a given list of days.
    """
    df = pd.DataFrame(days_list)
    # Ensure sorted by date
    df.sort_values('date', inplace=True)

    # Calculate RSI
    df['rsi'] = df.ta.rsi(length=14)

    # Calculate SMA
    df['sma_50'] = df.ta.sma(length=50)

    # Vectorized stability calculation
    df['body'] = (df['close'] - df['open']).abs()
    df['range'] = df['high'] - df['low']
    df['stability'] = df['body'] / df['range']

    return df
