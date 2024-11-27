import requests
import os
import json
from ratelimit import limits, sleep_and_retry

from globals import get_mongo_client, get_symbol_list, BASE_PATH

@sleep_and_retry
@limits(calls=60, period=60)  # 60 calls per 60 seconds
def load_historical_data_from_net(stock_symbol, recent=False):
    """
    Fetch historical stock data from Alpha Vantage API.

    This function retrieves daily historical stock data for a given stock symbol
    from the Alpha Vantage API. It can fetch either the full historical data or
    just the most recent data based on the `recent` parameter.

    Args:
        stock_symbol (str): The stock symbol to fetch data for.
        recent (bool, optional): If True, fetch only the most recent data. 
                                    If False, fetch the full historical data. 
                                    Defaults to False.

    Returns:
        dict: A dictionary containing the stock symbol and a list of daily records.
                Each daily record includes the date, open, high, low, close, volume,
                midpoint, high-low delta, open-close delta, high-low delta percentage,
                and close-open delta percentage.
                Returns None if the 'Time Series (Daily)' key is not found in the response.

    Usage:
        print(load_historical_data_from_net('QGEN', CONST_GRAB_RECENT_DATES))

    Raises:
        requests.exceptions.HTTPError: If the HTTP request returned an unsuccessful status code.
    """
    # Rate limiting is handled by the @limits decorator
    symbol = {'name': stock_symbol}

    outputsize = 'full' if not recent else 'compact'
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&outputsize={outputsize}&symbol={stock_symbol}&apikey=JFRQJ8YWSX8UK50X"

    response = requests.get(url)
    response.raise_for_status()  # Raise an exception for bad status codes

    json_data = response.json()

    if 'Time Series (Daily)' in json_data:
        time_series = json_data['Time Series (Daily)']
        symbol['days'] = []

        for date, daily_record in time_series.items():
            high = round(float(daily_record['2. high']), 4)
            low = round(float(daily_record['3. low']), 4)
            open_price = round(float(daily_record['1. open']), 4)  # Renamed to avoid conflict with built-in open
            close = round(float(daily_record['4. close']), 4)
            volume = int(daily_record['5. volume'])
            midpoint = round((open_price + close) / 2, 4)
            high_low_delta = round(abs(high - low), 4)
            open_close_delta = round(abs(open_price - close), 4)
            high_low_delta_percentage = round(abs((high - low) / (close if close != 0 else 1e-6)), 4)
            close_open_delta_percentage = round(abs(close - open_price) / (close if close != 0 else 1e-6), 4)

            symbol['days'].append({
                'date': date,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
                'midpoint': midpoint,
                'high_low_delta': high_low_delta,
                'open_close_delta': open_close_delta,
                'high_low_delta_percentage': high_low_delta_percentage,
                'close_open_delta_percentage': close_open_delta_percentage
            })
    else:
        print(f"'Time Series (Daily)' key not found in response for {stock_symbol}. URL: {url}. Response: {json_data}")
        return None

    return symbol

def load_historical_data_from_mongo(symbol, db):
    """
    Loads historical stock price data from MongoDB for a given symbol.

    Args:
        symbol (str): The stock symbol for which to load historical data.
        db (Database): The MongoDB database instance.

    Returns:
        dict: A dictionary containing the historical data if found, None otherwise.
        None: If no data is found for the given symbol.
    """
    collection = db['historical_data']
    data = collection.find_one({"symbol": symbol})
    return data

def save_historical_data_to_mongo(symbol, data, db):
    """
    Saves historical stock price data to MongoDB for a given symbol, performing an upsert operation.
    Saves historical stock price data to MongoDB for a given symbol.

    Args:
        symbol (str): The stock symbol for which to save historical data.
        data (dict): The historical data to save.
        db (Database): The MongoDB database instance.

    Returns:
        None
    """
    collection = db['historical_data']
    collection.update_one({"symbol": symbol}, {"$set": data}, upsert=True)

# def merge_data(historical_data, recent_data):
#     """
#     Merges recent stock data into historical stock data, ensuring no duplicate dates.

#     Args:
#         historical_data (dict): The historical stock data containing a list of days.
#         recent_data (dict): The recent stock data containing a list of days and a name.

#     Returns:
#         dict: The merged stock data with unique dates, sorted in descending order by date.
#     """
#     final_data = historical_data.copy()
#     existing_dates = {day['date'] for day in final_data['days']}  # Use a set for existing dates

#     # Merge the days with unique dates
#     new_days = [day for day in recent_data['days'] if day['date'] not in existing_dates]
#     final_data['days'].extend(new_days)

#     # Sort historical_data by date using heapq for efficiency
#     final_data['days'] = list(heapq.nlargest(len(final_data['days']), final_data['days'], key=lambda x: x['date']))
#     # Remove the data['metadata'] entry
#     if 'metadata' in final_data:
#         del final_data['metadata']

#     return final_data




def build_all_symbols_history(starting_at='', save_to_file=False):
    """
    Builds historical data for all stock symbols and saves them as JSON files.

    Args:
        starting_at (str, optional): The stock symbol to start processing from. If not provided, processing starts from the beginning of the symbol list.

    Returns:
        None

    This function retrieves a list of stock symbols from the network and iterates through each symbol to fetch its historical data. The data is then saved as a JSON file in a specified directory. If a starting symbol is provided, the function skips all symbols until it reaches the specified starting symbol.
    """
    symbol_list = get_symbol_list()
    index = 0

    skip = True if starting_at else False

    for row in symbol_list:
        index += 1
        percentage = round(index/len(symbol_list)*100)
        print(f'{index} - {row['symbol']} ({percentage}%)')

        if skip:
            if row['symbol'] == starting_at:
                skip = False
            else:
                continue

        symbol = row['symbol']
        name = row['name']

        try:
            net_data = load_historical_data_from_net(stock_symbol=symbol, recent=False)
            if net_data is None:
                print(f"No data for {symbol}")
                continue
            net_data['full_name'] = name

            save_historical_data_to_mongo(symbol, net_data, get_mongo_client())

            if save_to_file:
                new_data_json = json.dumps(net_data)
                # write out new_data_json to file
                file_path = os.path.join(BASE_PATH, f'StockPrice-{symbol}.json')
                with open(f'{file_path}', 'w', encoding='utf-8') as file:
                    file.write(new_data_json)
                    print(f"Saved data for {symbol} to {file_path}")
        except Exception as e:
            print(f"Error: {e}")
            continue


def load_historical_data_from_file(symbol):
    """
    Loads historical stock price data from a JSON file for a given symbol.

    Usage:
        print(load_historical_data_from_file('QGEN'))

    Args:
        symbol (str): The stock symbol for which to load historical data.

    Returns:
        dict: A dictionary containing the historical data if the file is found and successfully read.
        None: If the file is not found or an error occurs during reading.

    Raises:
        FileNotFoundError: If the file does not exist at the specified path.
    """
    file_path = os.path.join(BASE_PATH, f'StockPrice-{symbol}.json')

    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        print(f"File not found: {file_path}")
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {file_path}.")
    except PermissionError:
        print(f"Permission denied: {file_path}")
    except Exception as e:
        print(f"Error: {e}")
    return None

def load_historical_data(symbol):
    """
    Loads historical stock price data for a given symbol from a file or the network.

    Args:
        symbol (str): The stock symbol for which to load historical data.

    Returns:
        dict: A dictionary containing the historical data.
    """
    data = load_historical_data_from_mongo(symbol, get_mongo_client())
    if data is None:
        data = load_historical_data_from_file(symbol)
    if data is None:
        data = load_historical_data_from_net(symbol, recent=False)
    return data

# if __name__ == "__main__":
#     print('Running historicalData.py')
    # print(load_historical_data_from_net('AAPL'))
    # print(merge_data({'days': []}, {'name': 'AAPL', 'days': []}))
    # build_all_symbols_history()
    # print(load_historical_data('AAPL'))