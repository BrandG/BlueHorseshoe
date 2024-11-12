from Globals import combined_score_mul, adjusted_rolling_close_open_modifier, adjusted_weighted_price_stability_modifier, adjusted_modified_atr_modifier, calculate_ewma_delta, clip_data_to_dates, get_symbol_list, stability_score_modifier
from StandardDeviation import calculate_stability_score
from StockSelectionTools import get_MATR_stability, get_rolling_close_open_delta_percentage, get_weighted_price_stability
from historicalData import load_historical_data
import time
import sys
from historicalData import build_all_symbols_history
from prediction import get_gaussian_predictions



if __name__ == "__main__":
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

