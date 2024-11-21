import logging
import statistics
import subprocess
import sys
import time
import warnings

from sklearn.exceptions import ConvergenceWarning

from Globals import get_symbol_list, get_symbol_sublist, graph
from StandardDeviation import analyze_symbol_stability
from historicalData import build_all_symbols_history, load_historical_data
from prediction import forecast_next_midpoint, get_gaussian_predictions
import os

sys.argv = ["-d"]

def start_mongo_server():
    try:
        subprocess.run(["mongod", "--dbpath", "/path/to/your/db"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to start MongoDB server: {e}")
        sys.exit(1)

def runDebugTest():
    print("Running debug test")

if __name__ == "__main__":
    logging.basicConfig(filename='blueHorseshoe.log', filemode='w', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger('pymongo').setLevel(logging.WARNING)
    
    # Suppress specific warnings
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-invertible starting MA parameters found. Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-stationary starting autoregressive parameters found. Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=ConvergenceWarning, message="Maximum Likelihood optimization failed to converge. Check mle_retvals")
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


    start_time = time.time()
    if "-u" in sys.argv:
        build_all_symbols_history()
        print("Historical data updated.")
    elif "-p" in sys.argv:
        results = get_gaussian_predictions()
        for result in results:
            print(f'{result["symbol"]} - forecasted = {result["forecasted"]} - uncertainty = {result["uncertainty"]} - actual = {result["actual"]} - validity = {result["validity"]} - valid_choice = {result["valid_choice"]}')
    elif "-d" in sys.argv:
        runDebugTest()
    
    end_time = time.time()
    print(f'Execution time: {end_time - start_time:.2f} seconds')
