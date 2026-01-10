
import os
import csv
import io
import requests

ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_KEY", "JFRQJ8YWSX8UK50X")
LISTING_STATUS_URL = "https://www.alphavantage.co/query?function=LISTING_STATUS&apikey={key}"

def debug_symbols():
    url = LISTING_STATUS_URL.format(key=ALPHAVANTAGE_KEY)
    print(f"Fetching from {url}...")
    response = requests.get(url)
    response.raise_for_status()
    
    csv_file = io.StringIO(response.text)
    reader = csv.DictReader(csv_file)
    rows = list(reader)
    
    exchanges = set()
    asset_types = set()
    
    spy_row = None
    
    for row in rows:
        exchanges.add(row.get("exchange"))
        asset_types.add(row.get("assetType"))
        if row.get("symbol") == "SPY":
            spy_row = row
            
    print("Unique Exchanges:", exchanges)
    print("Unique Asset Types:", asset_types)
    print("SPY Row:", spy_row)

if __name__ == "__main__":
    debug_symbols()
