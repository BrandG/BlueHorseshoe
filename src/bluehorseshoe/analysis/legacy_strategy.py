"""
Legacy trading strategy module.
"""
from typing import Dict, Any
import pandas as pd
import pandas_ta as ta

def calculate_technical_indicators(days_list):
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