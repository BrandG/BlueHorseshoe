import os
import time
import requests

SYMBOLS = [
    {'symbol': 'ACHC', 'entry': 11.91},
    {'symbol': 'ADBG', 'entry': 7.62},
    {'symbol': 'APPN', 'entry': 29.66},
    {'symbol': 'ASAN', 'entry': 11.51},
    {'symbol': 'COUR', 'entry': 6.48}
]

API_KEY = os.environ.get("ALPHAVANTAGE_KEY")

print(f"{'SYMBOL':<8} {'ENTRY':<10} {'CURRENT':<10} {'CHANGE %':<10}")
print("-" * 40)

for s in SYMBOLS:
    sym = s['symbol']
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={sym}&apikey={API_KEY}"
    try:
        r = requests.get(url)
        data = r.json()
        quote = data.get('Global Quote', {})
        price_str = quote.get('05. price')
        
        if price_str:
            price = float(price_str)
            change = ((price - s['entry']) / s['entry']) * 100
            print(f"{sym:<8} {s['entry']:<10.2f} {price:<10.2f} {change:<10.2f}%")
        else:
            print(f"{sym:<8} {s['entry']:<10.2f} {'N/A':<10} {'N/A':<10}")
            
    except Exception as e:
        print(f"{sym:<8} Error: {e}")
    
    time.sleep(1.1) # Respect rate limit
