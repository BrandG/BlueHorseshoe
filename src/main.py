import logging
import sys
import time

from historicalData import build_all_symbols_history
from prediction import get_gaussian_predictions

if __name__ == "__main__":
    logging.basicConfig(filename='blueHorseshoe.log', filemode='w', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    start_time = time.time()
    if "-u" in sys.argv:
        build_all_symbols_history()
        print("Historical data updated.")
    elif "-p" in sys.argv:
        results = get_gaussian_predictions()
        for result in results:
            print(f'{result["symbol"]} - delta = {result["dailyDelta"]:.2%} - stability = {result["stability"]:.2%} - combinedScore = {result["combinedScore"]}')
    end_time = time.time()
    print(f'Execution time: {end_time - start_time:.2f} seconds')
