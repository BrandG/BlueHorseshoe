import os
import time
import requests

SYMBOLS = [
    {'symbol': 'ACHC', 'entry': 11.91},
]

API_KEY = os.environ.get("ALPHAVANTAGE_KEY")

for s in SYMBOLS:
    sym = s['symbol']
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={sym}&apikey={API_KEY}"
    try:
        r = requests.get(url)
        data = r.json()
        print(data)
    except Exception as e:
        print(e)
