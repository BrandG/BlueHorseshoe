import yfinance as yf
import time

SYMBOLS = [
    {'symbol': 'ACHC', 'entry': 11.91},
    {'symbol': 'ADBG', 'entry': 7.62},
    {'symbol': 'APPN', 'entry': 29.66},
    {'symbol': 'ASAN', 'entry': 11.51},
    {'symbol': 'COUR', 'entry': 6.48}
]

print(f"{'SYMBOL':<8} {'YEST CLOSE':<12} {'CURRENT':<10} {'CHANGE %':<10}")
print("-" * 45)

for s in SYMBOLS:
    sym = s['symbol']
    try:
        ticker = yf.Ticker(sym)
        # Fetch 1 min data for the last day to get most recent price
        df = ticker.history(period="1d", interval="1m")
        
        if not df.empty:
            price = df.iloc[-1]['Close']
            change = ((price - s['entry']) / s['entry']) * 100
            print(f"{sym:<8} {s['entry']:<12.2f} {price:<10.2f} {change:<10.2f}%")
        else:
            print(f"{sym:<8} {s['entry']:<12.2f} {'N/A':<10} {'N/A':<10}")
            
    except Exception as e:
        print(f"{sym:<8} Error: {e}")
