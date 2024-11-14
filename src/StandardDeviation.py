import logging
import math
from datetime import datetime, timedelta
import statistics
import matplotlib.pyplot as plt

from Globals import get_symbol_sublist
from Globals import graph
from Globals import stdevMultiplier
from Globals import ratioMultiplier
from historicalData import load_historical_data



def get_stdev(data):
    """
    Calculate the standard deviation of a list of numbers.

    Parameters:
    data (list of float): A list of numerical values.

    Returns:
    float: The standard deviation of the input list. Returns 0 if the list is empty.

    Example:
    >>> get_stdev([1, 2, 3, 4, 5])
    1.4142135623730951
    """
    n = len(data)
    if n == 0:
        return 0

    mean = 0
    variance = 0
    for i, x in enumerate(data):
        delta = x - mean
        mean += delta / (i + 1)
        variance += delta * (x - mean)
    variance /= (n - 1)
    stdev = math.sqrt(variance)
    return stdev



def drawStdev(midpoints):
    """
    Draws a graph of midpoints with standard deviation lines.

    Parameters:
    midpoints (list of float): A list of midpoint values.
    stdev (float): The standard deviation value.

    The function calculates the mean of the midpoints and plots a graph with:
    - The midpoints as a curve.
    - A red line representing the mean of the midpoints.
    - Two green lines representing the mean plus and minus the standard deviation.
    """
    stdev = get_stdev(midpoints)
    midpointMean = sum(midpoints)/len(midpoints)
    graph(xLabel="date", yLabel="Value", title="Graph of midpoints",
          curves=[{'curve':midpoints}],
          lines=[
              {'y':midpointMean, 'color':'r', 'linestyle':'-'},
              {'y':midpointMean+stdev, 'color':'g', 'linestyle':'-'},
              {'y':midpointMean-stdev, 'color':'g', 'linestyle':'-'},
              ])




def calculate_stability_score(price_data = None):
    """
    Calculate the stability score for a given symbol based on its price data.

    The stability score is determined by combining the standard deviation of the midpoints
    and the ratio of points within one standard deviation of the mean midpoint. A lower 
    standard deviation and a higher ratio of points within one standard deviation result 
    in a higher stability score.

    You might need to adjust the weights based on your specific needs

    Args:
        price_data (list): A list of price data points. Defaults to an empty list.

    Returns:
        float: The calculated stability score. Returns 0 if there is no data or if the 
               standard deviation is zero.

    Example:
        print(calculate_stability_score(load_historical_data_from_file('QGEN')['days'][:40]))
        print(calculate_stability_score(load_historical_data_from_file('IBM')['days'][:40]))
        print(calculate_stability_score(load_historical_data_from_file('A')['days'][:40]))

    """
    if not price_data:
        return 0
    
    midpoints = get_symbol_sublist('midpoint', historical_data=price_data)
    stdev = get_stdev(midpoints)

    if not midpoints or stdev == 0:  # Handle cases with no data or zero standard deviation
      return 0

    midpoint_mean = sum(midpoints) / len(midpoints)
    within_stdev_count = sum(1 for x in midpoints if abs(x - midpoint_mean) <= stdev)
    stdev_component = stdevMultiplier * stdev / (midpoint_mean + 1e-6)
    ratio_component = within_stdev_count * ratioMultiplier / len(midpoints)
    stability_score = 1 - (stdev_component * ratio_component)

    return stability_score




def get_workdays_last_month():
    """
    Calculate the workdays (Monday to Friday) for the last month.

    This function determines the workdays from today to 31 days ago, excluding weekends (Saturday and Sunday).

    Returns:
        list: A list of datetime objects representing the workdays in the last month, in chronological order.
    """
    today = datetime.today()
    one_month_ago = today - timedelta(days=31)

    workdays = []
    current_date = today
    while current_date > one_month_ago:
        if current_date.weekday() < 5:  # Weekday (0-4)
            workdays.append(current_date)
        current_date -= timedelta(days=1)
    return workdays[::-1]  # Reverse the list




def calculate_stability_scores_for_last_month(symbol, price_data=None):
    """
    Calculate the stability scores for the last month for a given symbol.

    This function calculates the stability scores for the last month based on the provided price data.
    If no price data is provided, it loads historical data from a file. It then calculates the stability
    score for each subset of the data and returns the mean stability score if valid scores are found.

    Args:
        symbol (str): The symbol for which to calculate the stability scores.
        price_data (list, optional): A list of price data dictionaries. Each dictionary should contain
                                     a 'midpoint' key. Defaults to None.

    Returns:
        float: The mean stability score for the last month if valid scores are found, rounded to three
               decimal places. Returns None if no valid scores are calculated.
    """
    scores = []
    if price_data is None:
        price_data = load_historical_data(symbol)['days'][:40]
    
    MIN_DATA_LENGTH = 20
    MIN_SCORE = 0
    MAX_SCORE = 100

    for i in range(0, MIN_DATA_LENGTH):
        data_subset = price_data[i:]

        is_all_midpoints_close = all(abs(element['midpoint'] - data_subset[0]['midpoint']) < 0.00001 for element in data_subset)
        is_data_subset_too_short = len(data_subset) < MIN_DATA_LENGTH
        if is_all_midpoints_close or is_data_subset_too_short:
            continue
        score = calculate_stability_score(data_subset)
        if MIN_SCORE < score < MAX_SCORE:
            scores.append(score)

    if scores:
        mean_score = round(sum(scores) / len(scores), 3)
        logging.info(f"Mean stability score for {symbol} over the last month: {mean_score}")
        return mean_score
    else:
        print(f"No valid scores for {symbol} calculated.")
        return None
    



def analyze_symbol_stability(symbols):
    """
    Analyzes the stability of a list of symbols based on their stability scores over the last month.

    This function calculates the stability scores for each symbol, sorts them in descending order,
    and prints the top 10 most stable symbols along with their stability scores. Additionally, it
    generates and displays a graph of the midpoints, highpoints, and lowpoints for the top symbols.

    Args:
        symbols (list): A list of symbols to analyze.

    Returns:
        None

    Raises:
        Exception: If there is an error in calculating the stability score for a symbol, it will be caught
                   and printed without interrupting the analysis of other symbols.

    Usage:
        analyze_symbol_stability([item['symbol'] for item in get_symbol_list_from_net()])

    Notes:
        - The function assumes the existence of the following helper functions:
            - calculate_stability_scores_for_last_month(symbol): Calculates the stability score for the given symbol.
            - load_historical_data_from_file(symbol): Loads historical data for the given symbol.
            - get_symbol_sublist(key, historical_data): Extracts a sublist of values from the historical data based on the key.
            - graph(xLabel, yLabel, title, curves, lines): Generates and displays a graph with the given parameters.
    """
    TOP_N = 10
    SLICE_LENGTH = 40

    symbol_stability = []
    for symbol in symbols:
        try:
            mean_score = calculate_stability_scores_for_last_month(symbol['symbol'])
            if mean_score is not None:
                symbol_stability.append((symbol['symbol'], mean_score))
        except Exception as e:
            print(f"Error analyzing symbol {symbol}: {e}")

    # Sort by stability score in descending order
    symbol_stability.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{TOP_N} Most Stable Symbols:")
    for i in range(min(TOP_N, len(symbol_stability))):
        print(f"{i+1}. {symbol_stability[i][0]}: {symbol_stability[i][1]}")
        price_data = load_historical_data(symbol_stability[i][0])['days'][:SLICE_LENGTH]

        midpoints = get_symbol_sublist('midpoint',historical_data=price_data)
        highpoints = get_symbol_sublist('high',historical_data=price_data)
        lowpoints = get_symbol_sublist('low',historical_data=price_data)
        if len(midpoints) <= 0:
            continue
        midpointMean = statistics.mean(midpoints)
        graph(xLabel="date", yLabel="Value", title="Graph of midpoints",
              curves=[{'curve':midpoints},{'curve':highpoints, 'color':'pink'},{'curve':lowpoints, 'color':'purple'}],
              lines=[ {'y':midpointMean, 'color':'r', 'linestyle':'-'}, ])
