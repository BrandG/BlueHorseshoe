import logging
import sys
import time

from Globals import get_symbol_list
from StandardDeviation import analyze_symbol_stability
from historicalData import build_all_symbols_history
from prediction import get_gaussian_predictions
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

    symbols = get_symbol_list()
    analyze_symbol_stability(symbols)
    
    end_time = time.time()
    print(f'Execution time: {end_time - start_time:.2f} seconds')
