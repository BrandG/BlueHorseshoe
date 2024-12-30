"""
This module provides functions to load, save, and manage historical stock price data
from various sources including Alpha Vantage API, MongoDB, and JSON files.

Functions:
    load_historical_data_from_net(stock_symbol, recent=False):
        Fetches historical stock data from Alpha Vantage API.

    load_historical_data_from_mongo(symbol, db):

    load_historical_data_from_file(symbol):

    load_historical_data(symbol):

    save_historical_data_to_mongo(symbol, data, db):

    build_all_symbols_history(starting_at='', save_to_file=False):
"""
import logging
import os
import json
import pandas as pd
import requests
from ratelimit import limits, sleep_and_retry #pylint: disable=import-error

from pymongo.errors import ServerSelectionTimeoutError
import talib as ta
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
        logging.info(load_historical_data_from_net('QGEN', True))

    Raises:
        requests.exceptions.HTTPError: If the HTTP request returned an unsuccessful status code.
    """
    # Rate limiting is handled by the @limits decorator
    symbol = {'name': stock_symbol}

    outputsize = 'full' if not recent else 'compact'
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&outputsize={outputsize}" + \
        f"&symbol={stock_symbol}&apikey=JFRQJ8YWSX8UK50X"

    response = requests.get(url, timeout=10)
    response.raise_for_status()  # Raise an exception for bad status codes

    json_data = response.json()

    if 'Time Series (Daily)' in json_data:
        time_series = json_data['Time Series (Daily)']
        symbol['days'] = []

        for date, daily_record in time_series.items():
            daily_data = {
                'date': date,
                'open': round(float(daily_record['1. open']), 4),
                'high': round(float(daily_record['2. high']), 4),
                'low': round(float(daily_record['3. low']), 4),
                'close': round(float(daily_record['4. close']), 4),
                'volume': int(daily_record['5. volume']),
            }
            daily_data['midpoint'] = round(
                (daily_data['open'] + daily_data['close']) / 2, 4)

            symbol['days'].append(daily_data)
    else:
        logging.error("'Time Series (Daily)' key not found in response for %s. URL: %s. Response: %s", stock_symbol, url, json_data)
        return None

    return symbol


def load_historical_data_from_mongo(symbol, db):
    """
    Loads historical stock price data from MongoDB for a given symbol.

    Args:
        symbol (str): The stock symbol for which to load historical data.
        db (Database): The MongoDB database instance.

    Returns:
        dict: A dictionary containing the historical data if found, empty dictionary otherwise.
    """
    data = {}
    try:
        collection = db['recent_historical_data']
        data = collection.find_one({"symbol": symbol})
        if data is None:
            data = {}
    except (ServerSelectionTimeoutError, OSError) as e:
        logging.error("Error accessing MongoDB: %s", e)

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

    # Store just the last year of data in a separate collection
    data['days'] = data['days'][-240:]
    recent_collection = db['recent_historical_data']
    recent_collection.update_one(
        {"symbol": symbol}, {"$set": data}, upsert=True)

def build_all_symbols_history(starting_at='', save_to_file=False, recent=False):
    """
    Builds historical data for all stock symbols and saves them as JSON files.

    Args:
        starting_at (str, optional): The stock symbol to start processing from. 
            If not provided, processing starts from the beginning of the symbol 
            list.

    Returns:
        None

    This function retrieves a list of stock symbols from the network and iterates
        through each symbol to fetch its historical data. The data is then saved
        as a JSON file in a specified directory. If a starting symbol is provided,
        the function skips all symbols until it reaches the specified starting
        symbol.
    """

    symbol_list = get_symbol_list()
    index = 0

    skip = bool(starting_at)

    for row in symbol_list:
        index += 1
        percentage = round(index/len(symbol_list)*100)

        if skip:
            if row['symbol'] == starting_at:
                skip = False
            else:
                continue

        symbol = row['symbol']
        name = row['name']

        try:
            net_data = load_historical_data_from_net(stock_symbol=symbol, recent=recent)
            if net_data is None:
                logging.error("No data for %s", symbol)
                continue
            net_data['full_name'] = name

            if isinstance(net_data, dict) and 'days' in net_data:
                df = pd.DataFrame(net_data['days'])
            else:
                logging.error("Invalid data format for %s.", symbol)
                return
            df = df.sort_values(by='date').reset_index(drop=True)

            net_data['days'] = get_technical_indicators(df)
            if '_id' in net_data:
                del net_data['_id']
            logging.info('%d - %s (%d%%) - size: %d', index, symbol, percentage, len(net_data["days"]))
            save_historical_data_to_mongo(symbol, net_data, get_mongo_client())

            if save_to_file:
                # write out new_data_json to file
                file_path = os.path.join(
                    BASE_PATH, f'StockPrice-{symbol}.json')
                with open(f'{file_path}', 'w', encoding='utf-8') as file:
                    file.write(json.dumps(net_data))
                    logging.info("Saved data for %s to %s", symbol, file_path)
        except requests.exceptions.RequestException as e:
            logging.error('Network error: %s', e)
            continue
        except json.JSONDecodeError as e:
            logging.error('JSON decode error: %s', e)
            continue
        except OSError as e:
            logging.error('OS error: %s', e)
            continue

def get_technical_indicators(df):
    """
    Calculate various technical indicators for a given DataFrame containing historical stock data.

    Parameters:
    df (pandas.DataFrame): DataFrame containing historical stock data with columns 'close', 'high', 'low', and 'volume'.

    Returns:
    list[dict]: A list of dictionaries where each dictionary represents a row of the DataFrame with the calculated technical indicators.

    The following technical indicators are calculated:
    - ema_20: 20-period Exponential Moving Average of the 'close' price.
    - macd_line: MACD line (difference between 12-period and 26-period EMA of the 'close' price).
    - macd_signal: Signal line (9-period EMA of the MACD line).
    - macd_hist: MACD histogram (difference between MACD line and Signal line).
    - adx: Average Directional Index.
    - rsi_14: 14-period Relative Strength Index.
    - atr_14: 14-period Average True Range.
    - bb_upper: Upper Bollinger Band.
    - bb_middle: Middle Bollinger Band (20-period SMA).
    - bb_lower: Lower Bollinger Band.
    - stoch_k: Stochastic %K.
    - stoch_d: Stochastic %D.
    - obv: On-Balance Volume.
    - mfi: 14-period Money Flow Index.
    - cci: 14-period Commodity Channel Index.
    - willr: 14-period Williams %R.
    """
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean().round(4)
    df['macd_line'], df['macd_signal'], df['macd_hist'] = ta.MACD( # type: ignore
        df['close'], fastperiod=12, slowperiod=26, signalperiod=9)
    df['macd_line'] = df['macd_line'].round(4)
    df['macd_signal'] = df['macd_signal'].round(4)
    df['macd_hist'] = df['macd_hist'].round(4)
    df['adx'] = ta.ADX(df['high'], df['low'], df['close'], timeperiod=14).round(4) # type: ignore
    df['dmi_p'] = ta.PLUS_DI(df['high'],df['low'],df['close'],timeperiod=14).round(4) # type: ignore
    df['dmi_n'] = ta.MINUS_DI(df['high'],df['low'],df['close'],timeperiod=14).round(4) # type: ignore
    df['rsi_14'] = ta.RSI(df['close'], timeperiod=14).round(4) # type: ignore
    df['atr_14'] = ta.ATR(df['high'], df['low'], df['close'], timeperiod=14).round(4) # type: ignore
    df['bb_upper'], df['bb_middle'], df['bb_lower'] = ta.BBANDS( # type: ignore
        df['close'], timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    df['bb_upper'] = df['bb_upper'].round(4)
    df['bb_middle'] = df['bb_middle'].round(4)
    df['bb_lower'] = df['bb_lower'].round(4)
    df['stoch_k'], df['stoch_d'] = ta.STOCH( # type: ignore
        df['high'], df['low'], df['close'], fastk_period=5, slowk_period=3, slowk_matype=0, slowd_period=3, slowd_matype=0)
    df['stoch_k'] = df['stoch_k'].round(4)
    df['stoch_d'] = df['stoch_d'].round(4)
    df['obv'] = ta.OBV(df['close'], df['volume']).round(4) # type: ignore
    df['mfi'] = ta.MFI(df['high'], df['low'], df['close'], df['volume'], timeperiod=14).round(4) # type: ignore
    df['cci'] = ta.CCI(df['high'], df['low'], df['close'], timeperiod=14).round(4) # type: ignore
    df['willr'] = ta.WILLR(df['high'], df['low'], df['close'], timeperiod=14).round(4) # type: ignore
    df['roc_5'] = ta.ROC(df['close'], timeperiod=5).round(4) # type: ignore
    df['avg_volume_20'] = df['volume'].rolling(window=20).mean().round(4)
    return df.to_dict(orient='records')

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
        logging.warning("File not found: %s", file_path)
    except json.JSONDecodeError:
        logging.error("Error: Invalid JSON in %s.", file_path)
    except PermissionError:
        logging.warning("Permission denied: %s", file_path)
    return {}


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
    if data and 'days' in data:
        data['days'] = sorted(data['days'], key=lambda x: x['date'])

    if data is None:
        return None
    days = data['days']
    if 'avg_volume_20' not in days[0]:
        df = pd.DataFrame(days)
        df['avg_volume_20'] = df['volume'].rolling(window=20).mean().round(4)
        days = df.to_dict(orient='records')

    return data

# if __name__ == "__main__":
#     ReportSingleton().write('Running historicalData.py')
    # ReportSingleton().write(load_historical_data_from_net('AAPL'))
    # ReportSingleton().write(merge_data({'days': []}, {'name': 'AAPL', 'days': []}))
    # build_all_symbols_history()
    # ReportSingleton().write(load_historical_data('AAPL'))
