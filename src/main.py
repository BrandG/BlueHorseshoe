import logging
import statistics
import sys
import time

from Globals import get_symbol_list, get_symbol_sublist, graph
from StandardDeviation import analyze_symbol_stability
from historicalData import build_all_symbols_history, load_historical_data
from prediction import forecast_next_midpoint, get_gaussian_predictions
import os

if __name__ == "__main__":
    logging.basicConfig(filename='blueHorseshoe.log', filemode='w', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger('pymongo').setLevel(logging.WARNING)
    
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


    start_time = time.time()
    if "-u" in sys.argv:
        build_all_symbols_history()
        print("Historical data updated.")
    elif "-p" in sys.argv:
        results = get_gaussian_predictions()
        for result in results:
            print(f'{result["symbol"]} - forecasted = {result["forecasted"]} - uncertainty = {result["uncertainty"]} - actual = {result["actual"]} - validity = {result["validity"]} - valid_choice = {result["valid_choice"]}')

    # Temp code to test general stability of symbols and predictions
    symbols = get_symbol_list()
    sorted_symbols = analyze_symbol_stability(symbols)

    for index in range(10):
        symbol_name = sorted_symbols[index][0]
        price_data = load_historical_data(symbol_name)['days'][:20]
        next_midpoint = forecast_next_midpoint(price_data[1:])
        print(f'{symbol_name} - next midpoint: {next_midpoint}')

        x_values = [data['date'] for data in price_data][::-1]
        print(f'{symbol_name} - x_values: {x_values}')
        midpoints = get_symbol_sublist('midpoint',historical_data=price_data)
        highpoints = get_symbol_sublist('high',historical_data=price_data)
        lowpoints = get_symbol_sublist('low',historical_data=price_data)
        if len(midpoints) <= 0:
            continue
        midpointMean = statistics.mean(midpoints)
        graph(xLabel="date", yLabel="Value", title=f'{index}_{symbol_name} midpoints', x_values=x_values,
            curves=[{'curve':midpoints},{'curve':highpoints, 'color':'pink'},{'curve':lowpoints, 'color':'purple'}],
            lines=[ {'y':midpointMean, 'color':'r', 'linestyle':'-'}, ],
            points=[{'x':20, 'y':next_midpoint, 'color':'g', 'marker':'x'}])
    
    end_time = time.time()
    print(f'Execution time: {end_time - start_time:.2f} seconds')
