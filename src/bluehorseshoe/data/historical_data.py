import logging
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import requests
from pymongo.errors import ServerSelectionTimeoutError, PyMongoError
import talib as ta
from bluehorseshoe.core.config import get_settings
from bluehorseshoe.core.symbols import get_symbol_list
from bluehorseshoe.core.scores import ScoreManager
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.analysis.constants import MIN_STOCK_PRICE, MAX_STOCK_PRICE, MIN_VOLUME_THRESHOLD, MIN_MARKET_CAP
from bluehorseshoe.data.provider_pool import create_provider_pool_from_env


# Lazy-initialized provider pool singleton
_provider_pool = None


def _get_provider_pool():
    """Get or create the provider pool singleton."""
    global _provider_pool  # pylint: disable=global-statement
    if _provider_pool is None:
        _provider_pool = create_provider_pool_from_env()
    return _provider_pool


def load_historical_data_from_net(stock_symbol, recent=False):
    """
    Fetch historical stock data via the provider pool.
    Backward-compatible wrapper — tries providers in priority order.
    """
    pool = _get_provider_pool()
    return pool.fetch_single(stock_symbol, recent=recent)


def check_market_status(symbol='SPY'):
    """
    Verifies if the market data for a bellwether symbol is up-to-date.
    Returns True if the latest data point matches the expected trading day.
    """
    try:
        # Determine expected date (Today in NY, or last Friday if Weekend)
        try:
            now_ny = pd.Timestamp.now(tz='US/Eastern')
        except Exception:  # pylint: disable=broad-exception-caught
             # Fallback to local if TZ fails
            now_ny = pd.Timestamp.now()

        # If before 6 PM ET, expect data from the previous day
        if now_ny.hour < 18:
            now_ny -= pd.Timedelta(days=1)

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

    except Exception as e:  # pylint: disable=broad-exception-caught
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


def save_historical_data_to_mongo(symbol, data, db_instance, store=None):
    """
    Saves historical stock price data for a given symbol, performing an upsert operation.
    Also writes to DuckDB store when provided (dual-write).
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

    # Dual-write to DuckDB
    if store is not None and 'days' in data:
        try:
            df = pd.DataFrame(data['days'])
            store.save_symbol(symbol, df, full_name=data.get('full_name', symbol))
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.warning("DuckDB dual-write failed for %s: %s", symbol, e)

def get_backfill_checkpoint(database):
    """
    Returns the last successfully processed symbol from the checkpoint collection.

    Args:
        database: MongoDB database instance
    """
    try:
        checkpoint = database.loader_checkpoints.find_one({"_id": "full_backfill_checkpoint"})
        return checkpoint.get("last_symbol") if checkpoint else None
    except PyMongoError as e:
        logging.error("Failed to get checkpoint: %s", e)
        return None

def set_backfill_checkpoint(symbol, database):
    """
    Saves the last successfully processed symbol to the checkpoint collection.

    Args:
        symbol: Stock symbol to checkpoint
        database: MongoDB database instance
    """
    try:
        database.loader_checkpoints.update_one(
            {"_id": "full_backfill_checkpoint"},
            {"$set": {"last_symbol": symbol, "updated_at": pd.Timestamp.now().isoformat()}},
            upsert=True
        )
    except PyMongoError as e:
        logging.error("Failed to set checkpoint: %s", e)

def get_active_symbol_list(database):
    """
    Build the tradeable symbol universe using market cap from symbol_overviews.
    Returns symbols with MarketCapitalization >= MIN_MARKET_CAP.
    """
    pipeline = [
        {"$match": {
            "MarketCapitalization": {"$exists": True, "$nin": ["", "None", None, "0"]},
        }},
        {"$addFields": {"mcap_num": {"$toLong": "$MarketCapitalization"}}},
        {"$match": {"mcap_num": {"$gte": MIN_MARKET_CAP}}},
        {"$project": {"symbol": 1, "_id": 0}}
    ]
    results = database["symbol_overviews"].aggregate(pipeline)
    active = {doc["symbol"] for doc in results}

    logging.info("Active universe: %d symbols with market cap >= $%dM",
                 len(active), MIN_MARKET_CAP // 1_000_000)
    return active

@dataclass
class BackfillConfig:
    """Configuration for historical data backfill."""
    starting_at: str = ''
    save_to_file: bool = False
    recent: bool = False
    symbols: Optional[List] = None
    resume: bool = False
    limit: Optional[int] = None
    active_only: bool = False

def build_all_symbols_history(config: Optional[BackfillConfig] = None, database=None, store=None):
    """
    Builds historical data for all stock symbols and saves them to MongoDB.

    Args:
        config: BackfillConfig for controlling the backfill process
        database: MongoDB database instance. Required for checkpoint operations.
        store: Optional DuckDBStore for dual-write.
    """
    if config is None:
        config = BackfillConfig()

    if database is None:
        raise ValueError("database parameter is required for build_all_symbols_history")

    starting_at = config.starting_at
    if config.resume and not starting_at:
        starting_at = get_backfill_checkpoint(database)
        if starting_at:
            logging.info("Resuming backfill from symbol: %s", starting_at)

    symbol_list = config.symbols if config.symbols is not None else get_symbol_list(database=database)
    if symbol_list is None:
        logging.error("Symbol list is None.")
        return

    if config.active_only and config.symbols is None:
        active_symbols = get_active_symbol_list(database)
        total_before = len(symbol_list)
        symbol_list = [s for s in symbol_list if s['symbol'] in active_symbols]
        logging.info("Active-only mode: updating %d of %d total symbols", len(symbol_list), total_before)

    skip = bool(starting_at)
    total_symbols = len(symbol_list)

    # Build work list (apply skip/limit before submitting to pool)
    work_items = []
    for index, row in enumerate(symbol_list, start=1):
        symbol = row['symbol']
        if skip:
            if symbol == starting_at:
                skip = False
            continue
        work_items.append((row, index))
        if config.limit and len(work_items) >= config.limit:
            break

    if not work_items:
        logging.info("No symbols to process.")
        return

    # Build provider pool and partition symbols across providers
    pool = _get_provider_pool()
    symbols = [row['symbol'] for row, _ in work_items]
    assignments = pool.partition_symbols(symbols)
    work_map = {row['symbol']: (row, idx) for row, idx in work_items}

    logging.info("Multi-provider dispatch: %s",
                 ", ".join(f"{p.name}={len(assignments.get(p.name, []))} symbols"
                           for p in pool.providers))

    all_futures = {}
    executors = []

    for provider in pool.providers:
        provider_syms = assignments.get(provider.name, [])
        if not provider_syms:
            continue
        # Threads >= CPS so rate limiter is the bottleneck, not thread count
        workers = min(max(provider.config.cps + 1, 2), len(provider_syms))
        executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix=f"prov-{provider.name}"
        )
        executors.append(executor)
        for sym in provider_syms:
            row, idx = work_map[sym]
            future = executor.submit(
                process_symbol, row, idx, total_symbols,
                config.save_to_file, config.recent, database,
                provider=provider, fallback_providers=pool.providers,
                store=store
            )
            all_futures[future] = sym

    # Collect results
    completed = 0
    failed = 0
    for future in as_completed(all_futures):
        sym = all_futures[future]
        try:
            future.result()
            completed += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            failed += 1
            logging.error("Failed to process %s: %s", sym, e)

    for executor in executors:
        executor.shutdown(wait=False)

    # Checkpoint the last symbol in the work list
    if work_items:
        set_backfill_checkpoint(work_items[-1][0]['symbol'], database)

    logging.info("Done: %d completed, %d failed out of %d", completed, failed, len(work_items))



def process_symbol(row, index, total_symbols, save_to_file, recent, database,
                   provider=None, fallback_providers=None, store=None):
    """
    Processes a stock symbol by loading its historical data, validating it,
    calculating technical indicators, and saving the data to MongoDB and optionally to a file.

    Args:
        row: Symbol row with 'symbol' and 'name' keys
        index: Current symbol index
        total_symbols: Total number of symbols
        save_to_file: Whether to save data to file
        recent: Whether to fetch recent data only
        database: MongoDB database instance
        provider: Assigned DataProvider instance (optional, uses pool fallback if None)
        fallback_providers: List of all providers for fallback on failure
        store: Optional DuckDBStore for dual-write
    """
    symbol = row['symbol']
    name = row['name']
    percentage = round(index/total_symbols*100)

    # Load existing data from MongoDB to merge with or check for updates
    existing_data = {}
    try:
        existing_data = load_historical_data_from_mongo(symbol, database)
        if existing_data and 'days' in existing_data and existing_data['days']:
            last_stored_date = existing_data['days'][-1]['date']
            
            # OPTIMIZATION: Check if data is already up-to-date
            now_ny = pd.Timestamp.now(tz='US/Eastern')
            today = now_ny.date()
            if now_ny.hour < 18: # Before 6PM ET, expect previous day
                target_date = today - pd.Timedelta(days=1)
            else:
                target_date = today

            # Adjust for weekends
            if target_date.weekday() == 5: # Saturday -> Friday
                target_date -= pd.Timedelta(days=1)
            elif target_date.weekday() == 6: # Sunday -> Friday
                target_date -= pd.Timedelta(days=2)
                
            if str(target_date) <= last_stored_date:
                logging.info("Skipping %s: Data up to date (%s)", symbol, last_stored_date)
                return

    except Exception as e:
        logging.warning("Optimization check failed for %s: %s. Proceeding to fetch.", symbol, e)

    try:
        # Use assigned provider (with fallback) or legacy pool path
        if provider is not None:
            net_data = provider.fetch(symbol, recent=recent)
            if net_data is None and fallback_providers:
                for fp in fallback_providers:
                    if fp is not provider:
                        net_data = fp.fetch(symbol, recent=recent)
                        if net_data is not None:
                            break
        else:
            net_data = load_historical_data_from_net(stock_symbol=symbol, recent=recent)
        if not validate_net_data(net_data, symbol, name):
            return

        if net_data and 'days' in net_data:
            df_new = pd.DataFrame(net_data['days'])
        else:
            logging.error("No 'days' data found for %s.", symbol)
            return

        # MERGE LOGIC: Combine existing history with new data
        if existing_data and 'days' in existing_data:
            df_existing = pd.DataFrame(existing_data['days'])
            # Combine and drop duplicates based on date
            df = pd.concat([df_existing, df_new]).drop_duplicates(subset=['date'])
        else:
            df = df_new

        if 'date' not in df.columns:
            logging.error("Column 'date' not found in DataFrame for %s.", symbol)
            return

        df = df.sort_values(by='date').reset_index(drop=True)
        # Recalculate indicators on the FULL merged set to ensure continuity
        merged_days = get_technical_indicators(df)
        net_data['days'] = merged_days

        # Calculate and save score for the latest day
        try:
            # We need the full DF with indicators to calculate the score
            full_df = pd.DataFrame(merged_days)
            score_components = TechnicalAnalyzer.calculate_technical_score(full_df)
            total_score = score_components.pop("total", 0.0)
            last_date = merged_days[-1]['date']

            # Use injected score manager or fall back to one created from passed DB
            # We create a new ScoreManager instance here since we have the DB
            sm = ScoreManager(database=database)
            sm.save_scores([
                {
                    "symbol": symbol,
                    "date": last_date,
                    "score": total_score,
                    "strategy": "baseline",
                    "version": "1.1",
                    "metadata": {
                        "source": "update_process",
                        "components": score_components
                    }
                }
            ])
        except (PyMongoError, ValueError, KeyError) as e:
            logging.error("Failed to calculate/save score for %s: %s", symbol, e)

        if '_id' in net_data:
            del net_data['_id']

        logging.info('%d - %s (%d%%) - size: %d', index, symbol, percentage, len(net_data["days"]))
        print(f"Processed {symbol}: {len(net_data['days'])} days")
        save_historical_data_to_mongo(symbol, net_data, database, store=store)

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
    settings = get_settings()
    file_path = os.path.join(settings.base_path, f'StockPrice-{symbol}.json')
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
    df['roc_2'] = ta.ROC(df['close'], timeperiod=2).round(4) # type: ignore
    df['rsi_3'] = ta.RSI(df['close'], timeperiod=3).round(4) # type: ignore
    df['std_20'] = df['close'].rolling(20).std().round(4)
    df['dv2'] = (((df['close'] - df['low']) / (df['high'] - df['low'])).rolling(2).mean()).round(4)
    df['avg_volume_20'] = df['volume'].rolling(window=20).mean().round(4)
    return df.to_dict(orient='records')

def load_historical_data_from_file(symbol):
    """
    Loads historical stock price data from a JSON file for a given symbol.
    """
    settings = get_settings()
    file_path = os.path.join(settings.base_path, f'StockPrice-{symbol}.json')

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


def load_historical_data(symbol, database=None, score_manager_instance=None, store=None):
    """
    Loads historical stock price data for a given symbol from a file or the network.

    Args:
        symbol: Stock symbol to load
        database: MongoDB database instance. If None, creates temporary container for backward compatibility.
        score_manager_instance: ScoreManager instance. If None, uses global singleton for backward compatibility.
        store: Optional DuckDBStore. If provided, tries DuckDB first and passes to save for dual-write.

    Returns:
        Dictionary containing historical data with 'days' list
    """
    # Use injected database or fall back to container for backward compatibility
    if database is None:
        from bluehorseshoe.core.container import create_app_container
        container = create_app_container()
        db_instance = container.get_database()
    else:
        db_instance = database

    # DuckDB is the primary source; file and network are fallbacks.
    # MongoDB is no longer consulted for OHLCV reads.
    data = {}
    if store is not None:
        data = store.load_symbol_dict(symbol)
        if data:
            logging.debug("Loaded %s from DuckDB (%d days)", symbol, len(data.get('days', [])))
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
                save_historical_data_to_mongo(symbol, data, db_instance, store=store)

                # Also update score
                try:
                    full_df = pd.DataFrame(data['days'])
                    score_components = TechnicalAnalyzer.calculate_technical_score(full_df)
                    total_score = score_components.pop("total", 0.0)
                    last_date = data['days'][-1]['date']

                    # Use injected score manager or fall back to global singleton
                    sm = score_manager_instance if score_manager_instance is not None else ScoreManager(database=db_instance)
                    sm.save_scores([
                        {
                            "symbol": symbol,
                            "date": last_date,
                            "score": total_score,
                            "strategy": "baseline",
                            "version": "1.1",
                            "metadata": {
                                "source": "load_process",
                                "components": score_components
                            }
                        }
                    ])
                except (PyMongoError, ValueError, KeyError) as e:
                    logging.error("Failed to update score for %s during load: %s", symbol, e)

    return data