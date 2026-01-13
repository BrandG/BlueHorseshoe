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
from pymongo.errors import ServerSelectionTimeoutError, PyMongoError
import talib as ta
from bluehorseshoe.core.globals import GlobalData, get_mongo_client
from bluehorseshoe.core.database import db
from bluehorseshoe.core.symbols import get_symbol_list
from bluehorseshoe.core.scores import score_manager
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer


# Rate Limit Configuration
CPS = int(os.environ.get("ALPHAVANTAGE_CPS", "2"))
ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_KEY", "JFRQJ8YWSX8UK50X")

@sleep_and_retry
@limits(calls=1, period=1.0/CPS)
def load_historical_data_from_net(stock_symbol, recent=False):
    """
    Fetch historical stock data from Alpha Vantage API.
    """
    symbol = {'name': stock_symbol}

    outputsize = 'full' if not recent else 'compact'
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&outputsize={outputsize}" + \
        f"&symbol={stock_symbol}&apikey={ALPHAVANTAGE_KEY}"

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


def check_market_status(symbol='SPY'):
    """
    Verifies if the market data for a bellwether symbol is up-to-date.
    Returns True if the latest data point matches the expected trading day.
    """
    try:
        # Determine expected date (Today in NY, or last Friday if Weekend)
        try:
            now_ny = pd.Timestamp.now(tz='US/Eastern')
        except Exception:
             # Fallback to local if TZ fails
            now_ny = pd.Timestamp.now()

        expected_date = now_ny.date()

        if now_ny.weekday() == 5: # Saturday
            expected_date -= pd.Timedelta(days=1)
        elif now_ny.weekday() == 6: # Sunday
            expected_date -= pd.Timedelta(days=2)

        net_data = load_historical_data_from_net(symbol, recent=True)
        if not net_data or 'days' not in net_data:
            return False

        dates = [d['date'] for d in net_data['days']]
        if not dates:
            return False

        last_market_date = max(dates) # String 'YYYY-MM-DD'

        if str(expected_date) <= last_market_date:
            logging.info("Bellwether check passed: %s data available for %s", last_market_date, symbol)
            return True

        logging.warning("Bellwether check failed: Expected %s, found %s for %s", expected_date, last_market_date, symbol)
        return False

    except Exception as e:
        logging.error("Market status check exception: %s", e)
        return False


def load_historical_data_from_mongo(symbol, db_instance):
    """
    Loads historical stock price data from MongoDB for a given symbol.
    """
    data = {}
    try:
        collection = db_instance['historical_prices']
        data = collection.find_one({"symbol": symbol})
        if data is None:
            data = {}
    except (ServerSelectionTimeoutError, OSError, PyMongoError) as e:
        logging.error("Error accessing MongoDB: %s", e)

    return data


def save_historical_data_to_mongo(symbol, data, db_instance):
    """
    Saves historical stock price data for a given symbol, performing an upsert operation.
    """
    # Create a copy to avoid modifying the original dict's _id if it exists
    save_data = data.copy()
    if '_id' in save_data:
        del save_data['_id']

    save_data['last_updated'] = pd.Timestamp.now().isoformat()

    collection = db_instance['historical_prices']
    collection.update_one({"symbol": symbol}, {"$set": save_data}, upsert=True)

    # Store just the last year of data in a separate collection
    recent_data = save_data.copy()
    if 'days' in recent_data:
        recent_data['days'] = save_data['days'][-240:]
    recent_collection = db_instance['historical_prices_recent']
    recent_collection.update_one(
        {"symbol": symbol}, {"$set": recent_data}, upsert=True)

def get_backfill_checkpoint():
    """Returns the last successfully processed symbol from the checkpoint collection."""
    try:
        database = db.get_db()
        checkpoint = database.loader_checkpoints.find_one({"_id": "full_backfill_checkpoint"})
        return checkpoint.get("last_symbol") if checkpoint else None
    except PyMongoError as e:
        logging.error("Failed to get checkpoint: %s", e)
        return None

def set_backfill_checkpoint(symbol):
    """Saves the last successfully processed symbol to the checkpoint collection."""
    try:
        database = db.get_db()
        database.loader_checkpoints.update_one(
            {"_id": "full_backfill_checkpoint"},
            {"$set": {"last_symbol": symbol, "updated_at": pd.Timestamp.now().isoformat()}},
            upsert=True
        )
    except PyMongoError as e:
        logging.error("Failed to set checkpoint: %s", e)

def build_all_symbols_history(starting_at='', save_to_file=False, recent=False, symbols=None, resume=False, limit=None):
    """
    Builds historical data for all stock symbols and saves them to MongoDB.
    """
    if resume and not starting_at:
        starting_at = get_backfill_checkpoint()
        if starting_at:
            logging.info("Resuming backfill from symbol: %s", starting_at)

    symbol_list = symbols if symbols is not None else get_symbol_list()
    if symbol_list is None:
        logging.error("Symbol list is None.")
        return

    skip = bool(starting_at)
    total_symbols = len(symbol_list)
    processed_count = 0

    for index, row in enumerate(symbol_list, start=1):
        symbol = row['symbol']
        if skip:
            if symbol == starting_at:
                skip = False
            continue

        process_symbol(row, index, total_symbols, save_to_file, recent)
        set_backfill_checkpoint(symbol)
        processed_count += 1

        if limit and processed_count >= limit:
            logging.info("Reached limit of %d symbols. Stopping.", limit)
            break



def process_symbol(row, index, total_symbols, save_to_file, recent):
    """
    Processes a stock symbol by loading its historical data, validating it,
    calculating technical indicators, and saving the data to MongoDB and optionally to a file.
    """
    symbol = row['symbol']
    name = row['name']
    percentage = round(index/total_symbols*100)

    try:
        net_data = load_historical_data_from_net(stock_symbol=symbol, recent=recent)
        if not validate_net_data(net_data, symbol, name):
            return

        if net_data and 'days' in net_data:
            df = pd.DataFrame(net_data['days'])
        else:
            logging.error("No 'days' data found for %s.", symbol)
            return
        if 'date' not in df.columns:
            logging.error("Column 'date' not found in DataFrame for %s.", symbol)
            return

        df = df.sort_values(by='date').reset_index(drop=True)
        net_data['days'] = get_technical_indicators(df)

        # Calculate and save score for the latest day
        try:
            # We need the full DF with indicators to calculate the score
            full_df = pd.DataFrame(net_data['days'])
            score_components = TechnicalAnalyzer.calculate_technical_score(full_df)
            total_score = score_components.pop("total", 0.0)
            last_date = net_data['days'][-1]['date']

            score_manager.save_scores([{
                "symbol": symbol,
                "date": last_date,
                "score": total_score,
                "strategy": "baseline",
                "version": "1.1",
                "metadata": {
                    "source": "update_process",
                    "components": score_components
                }
            }])
        except (PyMongoError, ValueError, KeyError) as e:
            logging.error("Failed to calculate/save score for %s: %s", symbol, e)

        if '_id' in net_data:
            del net_data['_id']

        logging.info('%d - %s (%d%%) - size: %d', index, symbol, percentage, len(net_data["days"]))
        print(f"Processed {symbol}: {len(net_data['days'])} days")
        save_historical_data_to_mongo(symbol, net_data, get_mongo_client())

        if save_to_file:
            save_data_to_file(symbol, net_data)
    except (requests.exceptions.RequestException, json.JSONDecodeError, OSError) as e:
        logging.error('%s error: %s', type(e).__name__, e)

def validate_net_data(net_data, symbol, name):
    """
    Validates the provided net data for a given symbol and name.
    """
    if net_data is None:
        logging.error("No data for %s", symbol)
        return False
    if 'full_name' in net_data and name:
        net_data['full_name'] = name
    else:
        logging.warning("No full name for net loaded data for %s. Using symbol as name.", symbol)
        net_data['full_name'] = symbol
    if not isinstance(net_data, dict) or 'days' not in net_data:
        logging.error("Invalid data format for %s.", symbol)
        return False
    return True

def save_data_to_file(symbol, net_data):
    """
    Save stock price data to a JSON file.
    """
    file_path = os.path.join(GlobalData.base_path, f'StockPrice-{symbol}.json')
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(json.dumps(net_data))
    logging.info("Saved data for %s to %s", symbol, file_path)

def get_technical_indicators(df):
    """
    Calculate various technical indicators for a given DataFrame containing historical stock data.
    """
    if 'midpoint' not in df.columns:
        if 'open' in df.columns:
            df['midpoint'] = round((df['open'] + df['close']) / 2, 4)
        else:
            df['midpoint'] = df['close']
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
    """
    file_path = os.path.join(GlobalData.base_path, f'StockPrice-{symbol}.json')

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
    """
    data = load_historical_data_from_mongo(symbol, get_mongo_client())
    if not data:
        data = load_historical_data_from_file(symbol)
    if not data:
        data = load_historical_data_from_net(symbol, recent=False)
    if data and 'days' in data:
        data['days'] = sorted(data['days'], key=lambda x: x['date'])

        days = data['days']
        if len(days) > 0:
            # Ensure 'midpoint' is present for all days (easy check)
            for day in days:
                if 'midpoint' not in day and 'open' in day and 'close' in day:
                    day['midpoint'] = round((day['open'] + day['close']) / 2, 4)
            # Check if complex technical indicators are missing (using proxies)
            # We check the last day to see if calculation is needed
            if len(days) >= 20 and ('ema_20' not in days[-1] or 'avg_volume_20' not in days[-1]):
                df = pd.DataFrame(days)
                data['days'] = get_technical_indicators(df)
                save_historical_data_to_mongo(symbol, data, get_mongo_client())

                # Also update score
                try:
                    full_df = pd.DataFrame(data['days'])
                    score_components = TechnicalAnalyzer.calculate_technical_score(full_df)
                    total_score = score_components.pop("total", 0.0)
                    last_date = data['days'][-1]['date']
                    score_manager.save_scores([{
                        "symbol": symbol,
                        "date": last_date,
                        "score": total_score,
                        "strategy": "baseline",
                        "version": "1.1",
                        "metadata": {
                            "source": "load_process",
                            "components": score_components
                        }
                    }])
                except (PyMongoError, ValueError, KeyError) as e:
                    logging.error("Failed to update score for %s during load: %s", symbol, e)

    return data
