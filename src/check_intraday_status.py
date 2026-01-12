"""
Script to check the intraday status of active trades.
"""
import sys
import os
import argparse
from datetime import datetime
import pandas as pd

# Try importing yfinance; handle gracefully if missing
try:
    import yfinance as yf
except ImportError:
    print("Error: 'yfinance' is not installed. Please run 'pip install yfinance' inside the container.")
    sys.exit(1)

def check_intraday(symbol: str, entry_price: float, stop_loss: float, take_profit: float):
    """
    Fetches the current day's data for the symbol and checks if levels were hit.
    """
    print(f"\n--- Intraday Check for {symbol} ---")
    print(f"Plan: Entry {entry_price:.2f} | Stop {stop_loss:.2f} | Target {take_profit:.2f}")

    # Fetch 1 day of intraday data (default interval is usually adequate, but we can be explicit)
    # yfinance '1d' period gives 1m/2m/5m/etc. depending on provider availability.
    # '1d' usually returns 1-minute or 5-minute bars if available, or daily if market closed.
    ticker = yf.Ticker(symbol)

    # Attempt to get intraday data
    # period="1d" often gets the most recent trading session
    df = ticker.history(period="1d", interval="5m")

    if df.empty:
        print("No intraday data returned. Market might be closed or symbol invalid.")
        return

    # Basic stats
    day_open = df.iloc[0]['Open']
    day_high = df['High'].max()
    day_low = df['Low'].min()
    current_price = df.iloc[-1]['Close']
    last_time = df.index[-1]

    print(f"Data Date: {last_time.date()}")
    print(f"Last Update: {last_time.time()}")
    print(f"Session: Open {day_open:.2f} | High {day_high:.2f} | Low {day_low:.2f} | Current {current_price:.2f}")

    # Analysis
    # 1. Did we trigger entry?
    # Assuming 'LIMIT' buy order at Entry Price.
    # If High >= Entry and Low <= Entry (and Open was not well below?), we likely filled.
    # Logic:
    #   - If we opened BELOW entry, and High >= Entry -> Filled.
    #   - If we opened ABOVE entry, and Low <= Entry -> Filled (Pullback).

    filled = False
    fill_time = None

    # Iterate to find first fill
    for idx, row in df.iterrows():
        if row['Low'] <= entry_price <= row['High']:
            filled = True
            fill_time = idx
            break

    if not filled:
        # Check if we opened below entry and stayed below (GAP DOWN scenario - technically filled if limit, but context dependent)
        # Assuming simple Pullback logic: We want to buy at X.
        # If price drops to X, we buy.
        print("Status: ❌ NO FILL (Price did not touch entry level)")
        return

    print(f"Status: ✅ FILLED at approx {fill_time.time()}")

    # 2. After fill, did we hit Stop or Target?
    # Scan from fill_time onwards
    post_fill_df = df.loc[fill_time:]

    outcome = "OPEN"
    pnl = (current_price - entry_price) / entry_price * 100

    for idx, row in post_fill_df.iterrows():
        if row['Low'] <= stop_loss:
            outcome = "STOPPED OUT 🛑"
            pnl = (stop_loss - entry_price) / entry_price * 100
            break
        if row['High'] >= take_profit:
            outcome = "TARGET HIT 🎯"
            pnl = (take_profit - entry_price) / entry_price * 100
            break

    print(f"Outcome: {outcome}")
    print(f"Unrealized PnL: {pnl:.2f}%")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check intraday status of a trade prediction.")
    parser.add_argument("symbol", type=str, help="Stock symbol (e.g., CSTM)")
    parser.add_argument("entry", type=float, help="Planned entry price")
    parser.add_argument("stop", type=float, help="Stop loss price")
    parser.add_argument("target", type=float, help="Take profit target")

    args = parser.parse_args()

    check_intraday(args.symbol, args.entry, args.stop, args.target)
