import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from Globals import get_symbol_list, graph

def hurst(ts):
    """
    Calculate the Hurst Exponent of a time series.

    The Hurst Exponent is used as a measure of the long-term memory of time series.
    Values range from 0 to 1. A value of 0.5 indicates a random walk, 
    a value less than 0.5 indicates mean reversion, and a value greater than 0.5 
    indicates long-term positive autocorrelation.

    Parameters:
    ts (array-like): The time series data.

    Returns:
    float: The Hurst Exponent of the time series.
    """
    if not isinstance(ts, (list, np.ndarray)):
        raise ValueError("Input time series must be a list or numpy array.")
    if len(ts) < 100:
        raise ValueError("Input time series must have at least 100 data points.")

    # Create the range of lag values
    LAG_MIN = 2
    LAG_MAX = 100
    lags = range(LAG_MIN, LAG_MAX)

    # Calculate the array of the variances of the lagged differences
    tau = [np.sqrt(np.std(ts[lag:] - ts[:-lag])) for lag in lags]

    # Use a linear fit to estimate the Hurst Exponent
    poly = np.polyfit(np.log(lags), np.log(tau), 1)

    # Return the Hurst exponent from the polyfit output
    return poly[0] * 2.0



def get_hurst_exponent(symbol, end_date, daterange):
    """
    Calculate the Hurst Exponent for a given symbol and plot the midpoints, highpoints, and lowpoints.

    Args:
        symbol (str): The symbol for which to calculate the Hurst Exponent.
        end_date (str): The end date for the data range.
        daterange (int): The range of dates to consider.

    Returns:
        float: The Hurst Exponent of the time series.

    Usage:
        get_hurst_exponent('A', '2024-10-23', 1000))
    """

    TWO_MONTHS = 40
    mid_values = get_symbol_list(symbol, 'midpoint', end_date, daterange)
    high_values = get_symbol_list(symbol, 'high', end_date, TWO_MONTHS)
    low_values = get_symbol_list(symbol, 'low', end_date, TWO_MONTHS)
    H = hurst(np.array(mid_values))

    graph_mid_values = mid_values[:TWO_MONTHS]
    if len(graph_mid_values) < 2:
        raise ValueError("Not enough data points to calculate final_mid_delta.")

    midpoint_mean = sum(graph_mid_values)/len(graph_mid_values)
    final_mid_delta = graph_mid_values[-2]+H

    graph(xLabel='date', yLabel='Value', title="Graph of midpoints",
          curves=[
              {'curve': graph_mid_values},
              {'curve': low_values, 'color': 'g'},
              {'curve': high_values, 'color': 'g'}
          ],
          lines=[
              {'y': midpoint_mean, 'color': 'r', 'linestyle': '-'}
          ],
          points=[
              {'x': TWO_MONTHS, 'y': final_mid_delta, 'color': 'b'},
              {'x': TWO_MONTHS, 'y': final_mid_delta * 1.005},
              {'x': TWO_MONTHS, 'y': final_mid_delta * 0.995}
          ]
    )
    return H
