# import numpy as np
# from Globals import get_symbol_sublist

# from historicalData import load_historical_data

# def calculate_hurst_exponent(symbol):
#     """
#     Calculate the Hurst exponent for a given symbol over a specified date range.

#     Parameters:
#     symbol (str): The symbol for which to calculate the Hurst exponent.

#     Returns:
#     float: The Hurst exponent.
#     """
#     mid_values = get_symbol_sublist('midpoint', load_historical_data(symbol))
#     ts = np.array(mid_values)

#     if len(ts) < 100:
#         raise ValueError("Input time series must have at least 100 data points.")

#     # Create the range of lag values
#     LAG_MIN = 2
#     LAG_MAX = 100
#     lags = range(LAG_MIN, LAG_MAX)
#     log_lags = np.log(lags)

#     # Calculate the array of the variances of the lagged differences
#     differences = [np.subtract(ts[lag:], ts[:-lag]) for lag in lags]
#     # Perform a linear fit on the log-log plot of lags vs. tau
#     log_tau = np.log(np.sqrt([np.std(diff) for diff in differences]))
#     fit_coefficients = np.polyfit(log_lags, log_tau, 1)

#     # The Hurst exponent is calculated as twice the slope of the log-log plot of the variances of the lagged differences (fit_coefficients[0])
#     # The Hurst exponent is twice the slope of the log-log plot of the variances of the lagged differences
#     hurst_exponent = fit_coefficients[0] * 2.0

#     return hurst_exponent
