"""
Script to check the intraday status of active trades.
"""
import sys
import argparse

# Try importing yfinance; handle gracefully if missing
try:
    import yfinance as yf
except ImportError:
    print("Error: 'yfinance' is not installed. Please run 'pip install yfinance' inside the container.")
    sys.exit(1)

def _find_fill(df, entry_price):
    """Finds the first occurrence where the entry price was touched."""
    for idx, row in df.iterrows():
        if row['Low'] <= entry_price <= row['High']:
            return idx
    return None

def _evaluate_outcome(post_fill_df, entry_price, stop_loss, take_profit, current_price):
    """Determines if the trade hit stop loss or take profit."""
    outcome = "OPEN"
    pnl = (current_price - entry_price) / entry_price * 100

    for _, row in post_fill_df.iterrows():
        if row['Low'] <= stop_loss:
            return "STOPPED OUT 🛑", (stop_loss - entry_price) / entry_price * 100
        if row['High'] >= take_profit:
            return "TARGET HIT 🎯", (take_profit - entry_price) / entry_price * 100

    return outcome, pnl

def check_intraday(symbol: str, entry_price: float, stop_loss: float, take_profit: float):
    """
    Fetches the current day's data for the symbol and checks if levels were hit.
    """
    print(f"\n--- Intraday Check for {symbol} ---")
    print(f"Plan: Entry {entry_price:.2f} | Stop {stop_loss:.2f} | Target {take_profit:.2f}")

    ticker = yf.Ticker(symbol)
    df = ticker.history(period="1d", interval="5m")

    if df.empty:
        print("No intraday data returned. Market might be closed or symbol invalid.")
        return

    last_time = df.index[-1]
    current_price = df.iloc[-1]['Close']

    print(f"Data Date: {last_time.date()}")
    print(f"Last Update: {last_time.time()}")
    print(f"Session: Open {df.iloc[0]['Open']:.2f} | High {df['High'].max():.2f} | "
          f"Low {df['Low'].min():.2f} | Current {current_price:.2f}")

    fill_time = _find_fill(df, entry_price)

    if not fill_time:
        print("Status: ❌ NO FILL (Price did not touch entry level)")
        return

    print(f"Status: ✅ FILLED at approx {fill_time.time()}")

    # 2. After fill, did we hit Stop or Target?
    outcome, pnl = _evaluate_outcome(
        df.loc[fill_time:], entry_price, stop_loss, take_profit, current_price
    )

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
