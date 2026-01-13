
import pandas as pd
import logging
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.analysis.indicators.momentum_indicators import MomentumIndicator

def debug_macd(symbol):
    """
    Debugs the MACD calculation for a given symbol.
    """
    data = load_historical_data(symbol)
    if not data or 'days' not in data:
        print(f"No data for {symbol}")
        return

    df = pd.DataFrame(data['days'])
    print(f"Data for {symbol}: {len(df)} rows")
    print(f"Columns: {df.columns.tolist()}")

    indicator = MomentumIndicator(df)
    score = indicator.get_score(enabled_sub_indicators=['macd'])
    print(f"MACD Score for {symbol}: {score.buy}")

    last_row = df.iloc[-1]
    if 'macd_line' in last_row:
        print(f"Last MACD Line: {last_row['macd_line']}, Signal: {last_row['macd_signal']}")
    else:
        print("MACD columns MISSING in dataframe!")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    debug_macd("AAPL") # Use a standard symbol
