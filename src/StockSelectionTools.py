from Globals import calculate_ewma_delta, clip_data_to_dates, const_date_range, get_symbol_list, get_symbol_sublist
from Globals import adjusted_rolling_close_open_modifier, adjusted_weighted_price_stability_modifier, adjusted_modified_atr_modifier, combined_score_mul, stability_score_modifier
from StandardDeviation import calculate_stability_score
from historicalData import load_historical_data


def get_rolling_close_open_delta_percentage(price_data=None, daterange=const_date_range, window_size=5):
    """
    Calculate the rolling average of the close-open delta percentage over a specified window size.
    This can help filter for stocks with stable price behavior while retaining tradable daily ranges.
    Ranges from 0..1 where 0 is smallest change, and 1 is greatest change

    Args:
        price_data (list, optional): A list of price data dictionaries. Each dictionary should contain
                                     'close_open_delta_percentage' key. Defaults to None.
        daterange (int, optional): The number of days to consider from the price data. Defaults to const_date_range.
        window_size (int, optional): The size of the rolling window to calculate the average. Defaults to 5.

    Returns:
        float: The rolling average of the close-open delta percentage. Returns 0.0 if input is invalid or
               if there are not enough data points to calculate the rolling average.

    Usage:
        print(get_rolling_close_open_delta_percentage(price_data = load_historical_data_from_file('QGEN')['days']))
    """
    if price_data is None or not isinstance(price_data, list) or len(price_data) < daterange:
        return 0.0  # Return 0.0 for invalid input

    deltas = get_symbol_sublist('close_open_delta_percentage', historical_data=price_data[:daterange])

    if len(deltas) < window_size:
        return 0.0  # Return 0.0 if there are not enough deltas for the window size

    rolling_delta = []
    window_sum = sum(deltas[:window_size - 1])
    for i in range(window_size - 1, len(deltas)):
        window_sum += deltas[i]
        rolling_delta.append(window_sum / window_size)
        window_sum -= deltas[i - window_size + 1]

    return sum(rolling_delta[:window_size]) / window_size





def get_weighted_price_stability(price_data, volume_window_size=const_date_range):
    """
    Calculate the weighted price stability of a stock based on its price data and volume.

    This function computes the weighted price stability by considering the absolute 
    percentage change between the open and close prices, weighted by the relative volume 
    over a specified window size.

    The Weighted Price Stability calculation multiplies each day's close-open delta by the 
    relative volume, giving greater importance to high-volume days. This weighting allows 
    us to focus on price stability under conditions of higher liquidity, as those are 
    typically more meaningful for consistent trading behavior.
    
    Args:
        price_data (list): A list of dictionaries containing 'open', 'close', and 'volume' keys.
        volume_window_size (int): The size of the window to calculate the rolling average volume.

    Returns:
        float: The weighted price stability score. Returns 0.0 if input data is invalid or insufficient.

    usage:
        print(get_weighted_price_stability(price_data = load_historical_data_from_file('QGEN')['days']))
    """
    if not price_data or not isinstance(price_data, list):
        return 0.0  # Return 0.0 for invalid input

    deltas = []
    volumes = []

    for price_obj in price_data[:volume_window_size]:
        if not isinstance(price_obj, dict) or 'open' not in price_obj or 'close' not in price_obj or 'volume' not in price_obj:
            continue  # Skip if 'open', 'close', or 'volume' are missing
        try:
            open_price = float(price_obj['open'])
            close_price = float(price_obj['close'])
            volumes.append(float(price_obj['volume']))
            deltas.append(abs((close_price - open_price) / close_price))
        except (ValueError, TypeError):
            # Handle cases where open, close, or volume are not valid numbers
            continue

    if len(volumes) < volume_window_size:
        return 0.0  # Return 0.0 if there are not enough volumes for the window size

    rolling_average_volume = []
    window_sum = sum(volumes[:volume_window_size - 1])
    for i in range(volume_window_size - 1, len(volumes)):
        window_sum += volumes[i]
        rolling_average_volume.append(window_sum / volume_window_size)
        window_sum -= volumes[i - volume_window_size + 1]

    relative_volume = []
    for i in range(volume_window_size - 1, len(volumes)):
        if rolling_average_volume[i - (volume_window_size - 1)] == 0:
            relative_volume.append(0)
        else:
            relative_volume.append(volumes[i] / rolling_average_volume[i - (volume_window_size - 1)])

    weighted_data = []
    for i in range(volume_window_size - 1, len(deltas)):
        weighted_value = deltas[i] * relative_volume[i - (volume_window_size - 1)]
        weighted_data.append(weighted_value)

    # Final weighted stability score
    return sum(weighted_data) / len(weighted_data) if weighted_data else 0.0




def get_MATR_stability(price_data=None, daterange=const_date_range):
    """
    Calculate the Modified Average True Range (MATR) stability for a given set of price data.

    The Modified Average True Range (ATR) is an adaptation of the traditional Average True Range 
    (ATR), a widely used indicator in technical analysis for measuring market volatility. The 
    traditional ATR calculates the average range between the high and low prices over a specified 
    period, incorporating gaps by considering the previous close as well. The Modified ATR makes 
    adjustments to this calculation to tailor it for specific trading strategies or to smooth out 
    anomalies in volatility.

    This version is the EMA modification (exponential moving average). It should prioritize recent 
    price changes over older data. Maybe we try one of the others like Relative ATR 
    (percentage-based. Good for comparing to other stocks), or Volume weighted. 🤷

    Note: I did make some changes to make it return a stability percentage.

    Parameters:
    price_data (list of dict): A list of dictionaries containing price information with keys 'high', 'low', and 'close'.
    daterange (int): The number of days to consider for the calculation.

    Returns:
    float: The MATR stability value. Returns 0.0 if the input data is invalid or insufficient.

    The function performs the following steps:
    1. Validates the input price data.
    2. Calculates the true range for each day within the daterange.
    3. Computes the Modified Average True Range (MATR) using an exponential moving average (EMA).

    Usage:
    print(get_MATR_stability(price_data=load_historical_data_from_file('QGEN')['days']))

    Note:
    - If price_data is None, not a list, or has fewer elements than daterange, the function returns 0.0.
    - If any price data dictionary is missing 'high', 'low', or 'close' keys, that entry is skipped.
    - If there are not enough valid true range values, the function returns 0.0.
    """
    if price_data is None or not isinstance(price_data, list) or len(price_data) < daterange:
        return 0.0  # Return 0.0 for invalid input

    true_range = []
    for i in range(1, min(len(price_data), daterange)):
        price_obj = price_data[i]
        yesterday_price_obj = price_data[i - 1]
        if not isinstance(price_obj, dict) or 'high' not in price_obj or 'low' not in price_obj or 'close' not in price_obj:
            continue  # Skip if 'high', 'low', or 'close' are missing
        try:
            high_price = float(price_obj['high'])
            low_price = float(price_obj['low'])
            close_price = float(price_obj['close'])
            yesterday_close_price = float(yesterday_price_obj['close'])
            mean_val = (close_price + yesterday_close_price) / 2
            tr1 = (high_price - low_price) / mean_val
            tr2 = abs(high_price - yesterday_close_price) / mean_val
            tr3 = abs(low_price - yesterday_close_price) / mean_val
            true_range.append(max(tr1, tr2, tr3))
        except (ValueError, TypeError) as e:
            # Handle cases where high, low, or close are not valid numbers
            print(f'Error processing price data: {e}')
            continue

    if len(true_range) < daterange:
        return 0.0  # Return 0.0 if there are not enough true range values

    modified_atr = [sum(true_range[:daterange]) / daterange]

    alpha = 2 / (daterange + 1)
    for i in range(daterange, len(true_range)):
        ema_value = (true_range[i] * alpha) + (modified_atr[-1] * (1 - alpha))
        modified_atr.append(ema_value)

    return sum(modified_atr[:daterange]) / daterange
    

    
def get_stability_score(historical_data):
    adjusted_rolling_close_open_delta = get_rolling_close_open_delta_percentage(historical_data) * adjusted_rolling_close_open_modifier
    adjusted_weighted_price_stability = get_weighted_price_stability(historical_data) * adjusted_weighted_price_stability_modifier
    adjusted_modified_atr = get_MATR_stability(historical_data) * adjusted_modified_atr_modifier
    stability_score = calculate_stability_score(historical_data) * stability_score_modifier

    return (adjusted_rolling_close_open_delta + \
                            adjusted_weighted_price_stability + \
                            adjusted_modified_atr + \
                            stability_score) / 4


def get_top_ten_stability_scores():
    results=[]
    for symbol in get_symbol_list():
        price_data = load_historical_data(symbol['symbol'])
        if price_data is None:
            print(f'No data found for {symbol["symbol"]}')
            continue
        price_data = clip_data_to_dates(price_data["days"], '2024-10-15',40)
        stability_score = get_stability_score(price_data)
        delta = calculate_ewma_delta(price_data)

        results.append({'symbol':symbol,
                        'dailyDelta':delta,
                        'stability':stability_score,
                        'combinedScore': delta * combined_score_mul[0] + stability_score * combined_score_mul[1]})

    # Filter out the bad data
    results = [result for result in results if result['stability'] < 100.0 and result['dailyDelta'] > 0.012 and result['symbol']['name'] != '']

    # Sort by stabiility and delta
    results.sort(key=lambda x:(x['combinedScore']), reverse=False)
    print(f'Returning top 10 stability scores {results[:10]}')

    return results[:10]
