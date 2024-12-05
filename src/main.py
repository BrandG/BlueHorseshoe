"""
Main module for the BlueHorseshoe project.

This module handles the initialization, training, and prediction of stock midpoints using historical data.
It also provides functionality for debugging, updating historical data, and predicting next midpoints.

Modules:
    logging: Provides logging capabilities.
    statistics: Provides functions for mathematical statistics.
    sys: Provides access to some variables used or maintained by the interpreter.
    time: Provides time-related functions.
    warnings: Provides a way to handle warnings.
    pandas: Provides data structures and data analysis tools.
    sklearn.exceptions: Provides exceptions for scikit-learn.
    globals: Provides global variables and functions.
    StockMidpointPredictor: Provides the StockMidpointPredictor class for stock midpoint prediction.
    historical_data: Provides functions to build and load historical data.
    prediction: Provides functions to forecast the next midpoint.
    os: Provides a way of using operating system dependent functionality.
    flatness: Provides functions to analyze midpoints.
    nnPrediction: Provides functions to get neural network predictions.

Functions:
    debug_test(): Loads historical data for IBM, trains the StockMidpointPredictor model, and evaluates its performance.

    Loads historical data for IBM, trains the StockMidpointPredictor model, and evaluates its performance.

    This function performs the following steps:
    1. Loads historical data for IBM.
    2. Prepares the data for training.
    3. Initializes and trains the StockMidpointPredictor model.
    4. Predicts the next day's midpoint.
    5. Evaluates the model's performance and prints the RMSE.

    Returns:
        None

"""
import random
import logging
import sys
import time
import warnings
import os
import pandas as pd

from sklearn.exceptions import ConvergenceWarning

from claude_prediction import ClaudePrediction
from globals import ReportSingleton, get_mongo_client, get_symbol_name_list
from historical_data import build_all_symbols_history, load_historical_data

sys.argv = ["-d"]

def debug_test():
    """
    Debug function to test the StockMidpointPredictor model.

    This function performs the following steps:
    1. Loads historical price data for IBM.
    2. Prepares the data for model training.
    3. Initializes and trains the StockMidpointPredictor model with a lookback period of 30 days.
    4. Predicts the next day's midpoint price.
    5. Evaluates the model's performance using RMSE (Root Mean Square Error).

    The function also contains commented-out code for additional analysis and forecasting of stock symbols,
    including calculating flatness, average delta, and generating graphical representations of midpoints.

    Note: The commented-out code is not executed but provides a template for further analysis and reporting.

    Returns:
        None
    """

    symbols = get_symbol_name_list()
    price_data = load_historical_data(random.choice(symbols))
    if price_data is None:
        print("Failed to load historical data for IBM.")
        return
    price_data = price_data['days'][:240]
    clipped_price_data = price_data[::-1]
    # clipped_price_data = clipped_price_data[:-21]
    data = pd.DataFrame([{
        'open':val['open'],
        'high':val['high'],
        'low':val['low'],
        'close':val['close'],
        'volume':val['volume'],
        'date':val['date']}
        for val in clipped_price_data])
    cp = ClaudePrediction(data)
    results = {}
    results['mfi'] = cp.get_mfi()
    results['obv'] = cp.get_obv()
    results['vwap'] = cp.volume_weighted_average_price()
    results['rsi'] = cp.get_rsi()
    results['stochastic_oscillator'] = cp.get_stochastic_oscillator()
    results['macd'] = cp.get_macd()
    results['atr'] = cp.get_atr()
    results['bb'] = cp.get_bollinger_bands()
    results['stdev'] = cp.get_standard_deviation_volatility()
    results['emas'] = cp.get_ema_signals()
    results['ichimoku'] = cp.get_ichimoku_cloud()

    # print(f'MFI: {mfi_result}')
    # print(f'OBV: {obv_result}')
    # print(f'VWAP: {vwap_result}')
    # print(f'RSI: {rsi_result}')
    # print(f'Stochastic Oscillator: {stochastic_oscillator_result}')
    # print(f'MACD: {macd_result}')
    # print('     Volatility Indicators:')
    # print(f'ATR: {atr_result['volatility']}')
    # print(f'Bollinger Bands: {bb_result['volatility']}')
    # print(f'Standard Deviation Volatility: {stdev_result['volatility']}')
    # print('     Short-Term Trend Indicators:')
    # print(f'EMA Signals: {emas_result}')
    # print(f'Ichimoku Cloud: {ichimoku_result}')
    print(results)

    # //--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==
    # price_data = load_historical_data('IBM')
    # newData = [{
    #     'open':val['open'],
    #     'high':val['high'],
    #     'low':val['low'],
    #     'close':val['close'],
    #     'volume':val['volume'],
    #     'date':val['date']} for val in price_data['days']][1:]
    # data = pd.DataFrame(newData[::-1])

    # # Initialize and train the model
    # predictor = StockMidpointPredictor(lookback_period=30)
    # predictor.train(data)

    # # Get prediction for next day
    # next_day_midpoint = predictor.predict(data)
    # print(f"Next day's midpoint: {next_day_midpoint:.2f}")

    # # Evaluate model performance
    # metrics = predictor.evaluate(data)
    # print(f"RMSE: {metrics}")

    # //--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==
    # price_data = load_historical_data('IBM')
    # print(price_data['days'][0])
    # get_nn_prediction(price_data['days'][::-1])

    # //--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==
    # symbols = get_symbol_name_list()
    # results = []
    # for symbol in symbols:
    #     price_data = load_historical_data(symbol)
    #     midpoints = get_symbol_sublist('midpoint', historical_data=price_data['days'])
    #     avg_delta = sum(get_symbol_sublist('high_low_delta_percentage', historical_data=price_data['days']))/len(price_data['days'])
    #     flatness = analyze_midpoints(midpoints)
    #     results.append({'symbol':symbol,'flatness':flatness, 'avg_delta':avg_delta})
    # results.sort(key=lambda x: x['flatness'])
    # results = list(filter(lambda x: x['avg_delta'] > 0.01, results))
    # validCount = 0
    # invalidCount = 0
    # for index in range(10):
    #     result=results[index]
    #     symbol_name = result['symbol']
    #     price_data = load_historical_data(symbol_name)['days'][:20]
    #     next_midpoint = round(forecast_next_midpoint(price_data[1:],(1,1,4)), 2)

    # //--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==//--\\==
    #     last_high = round(price_data[0]['high'], 2)
    #     last_low = round(price_data[0]['low'], 2)

    #     next_high = round(next_midpoint+(0.005 * next_midpoint), 2)
    #     next_low = round(next_midpoint-(0.005 * next_midpoint), 2)
    #     chosen = (next_high - next_low)/((next_high+next_low)/2) > 0.01
    #     if not chosen:
    #         invalidCount += 1
    #     valid = next_high <= last_high and next_low >= last_low
    #     if valid:
    #         validCount += 1
    #     ReportSingleton().write(f'{index}. {'Chosen' if chosen else 'Not Chosen'} -
    #                             {'Valid' if valid else 'Invalid'} - {symbol_name}:
    #                             Next midpoint {next_midpoint:2} ({next_low:2},
    #                             {next_high:2}) last ({last_low:2}, {last_high:2}).')

    #     price_data = price_data[:-1]
    #     x_values = [data['date'] for data in price_data]
    #     midpoints = get_symbol_sublist('midpoint',historical_data=price_data)
    #     highpoints = get_symbol_sublist('high',historical_data=price_data)
    #     lowpoints = get_symbol_sublist('low',historical_data=price_data)
    #     if len(midpoints) <= 0:
    #         continue
    #     midpointMean = statistics.mean(midpoints)
    #     graph_data : GraphData = {'x_label':'date', 'y_label':'Value', 'title':f'{index}_{symbol_name} midpoints', 'x_values':x_values,
    #         'curves': [{'curve':midpoints},{'curve':highpoints, 'color':'pink'},{'curve':lowpoints, 'color':'purple'}],
    #         'lines': [ {'y':midpointMean, 'color':'r', 'linestyle':'-'}, ],
    #         'points': [{'x':19, 'y':next_midpoint, 'color':'g', 'marker':'x'},
    #                    {'x':19, 'y':next_high, 'color':'orange', 'marker':'x'},
    #                    {'x':19, 'y':next_low, 'color':'orange', 'marker':'x'},],
    #     }
    #     graph(graph_data)
    # ReportSingleton().write('f'Valid percentage: {validCount/(10-invalidCount)*100}%')

if __name__ == "__main__":
    start_time = time.time()

    logging.basicConfig(filename='blueHorseshoe.log', filemode='w', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger('pymongo').setLevel(logging.WARNING)

    if get_mongo_client() is None:
        sys.exit(1)

    # Suppress specific warnings
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-invertible starting MA parameters found. " +
                            "Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-stationary starting autoregressive parameters " +
                            "found. Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=ConvergenceWarning, message="Maximum Likelihood optimization failed to ")
    warnings.filterwarnings("ignore", category=ConvergenceWarning)

    # Clear the graphs directory
    GRAPHS_DIR = 'graphs'
    for filename in os.listdir(GRAPHS_DIR):
        file_path = os.path.join(GRAPHS_DIR, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                os.rmdir(file_path)
        except (OSError, IOError) as e:
            logging.error('Failed to delete %s. Reason: %s', file_path, e)


    if "-u" in sys.argv:
        build_all_symbols_history()
        print("Historical data updated.")
    elif "-p" in sys.argv:
        print('Predicting next midpoints...')
        # results = get_gaussian_predictions()
        # for result in results:
            # print(f'{result["symbol"]} - forecasted = ' +
            #       f'{result["forecasted"]} - uncertainty = ' +
            #       f'{result["uncertainty"]} - actual = ' +
            #       f'{result["actual"]} - validity = {result["validity"]} ' +
            #       f'- valid_choice = {result["valid_choice"]}')
    elif "-d" in sys.argv:
        debug_test()

    ReportSingleton().close()
    end_time = time.time()
    print(f'Execution time: {end_time - start_time:.2f} seconds')
