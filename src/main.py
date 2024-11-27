import logging
import statistics
import sys
import time
import warnings
import pandas as pd

from sklearn.exceptions import ConvergenceWarning

from globals import ReportSingleton, get_mongo_client
from StockMidpointPredictor import StockMidpointPredictor
from historical_data import build_all_symbols_history, load_historical_data
from prediction import forecast_next_midpoint
import os

from flatness import analyze_midpoints
from nnPrediction import get_nn_prediction

sys.argv = ["-d"]

def debugTest():

    price_data = load_historical_data('IBM')
    newData = [{'open':val['open'], 'high':val['high'], 'low':val['low'], 'close':val['close'], 'volume':val['volume'], 'date':val['date']} for val in price_data['days']][1:]
    data = pd.DataFrame(newData[::-1])

    # Initialize and train the model
    predictor = StockMidpointPredictor(lookback_period=30)
    predictor.train(data)

    # Get prediction for next day
    next_day_midpoint = predictor.predict(data)
    print(f"Next day's midpoint: {next_day_midpoint:.2f}")

    # Evaluate model performance
    metrics = predictor.evaluate(data)
    print(f"RMSE: {metrics}")

    # price_data = load_historical_data('IBM')
    # print(price_data['days'][0])
    # get_nn_prediction(price_data['days'][::-1])

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
    #     ReportSingleton().write(f'{index}. {'Chosen' if chosen else 'Not Chosen'} - {'Valid' if valid else 'Invalid'} - {symbol_name}: Next midpoint {next_midpoint:2} ({next_low:2},{next_high:2}) last ({last_low:2}, {last_high:2}).')

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
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-invertible starting MA parameters found. Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-stationary starting autoregressive parameters found. Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=ConvergenceWarning, message="Maximum Likelihood optimization failed to ")
    warnings.filterwarnings("ignore", category=ConvergenceWarning)

    # Clear the graphs directory
    graphs_dir = 'graphs'
    for filename in os.listdir(graphs_dir):
        file_path = os.path.join(graphs_dir, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                os.rmdir(file_path)
        except Exception as e:
            logging.error(f'Failed to delete {file_path}. Reason: {e}')


    if "-u" in sys.argv:
        build_all_symbols_history()
        print("Historical data updated.")
    elif "-p" in sys.argv:
        print('Predicting next midpoints...')
        # results = get_gaussian_predictions()
        # for result in results:
        #     print(f'{result["symbol"]} - forecasted = {result["forecasted"]} - uncertainty = {result["uncertainty"]} - actual = {result["actual"]} - validity = {result["validity"]} - valid_choice = {result["valid_choice"]}')
    elif "-d" in sys.argv:
        debugTest()

    ReportSingleton().close()
    end_time = time.time()
    print(f'Execution time: {end_time - start_time:.2f} seconds')
