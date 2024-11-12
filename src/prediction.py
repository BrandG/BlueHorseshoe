import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C
from statsmodels.tsa.arima.model import ARIMA
from Globals import get_symbol_sublist
from historicalData import load_historical_data
import logging

def forecast_next_midpoint(price_data=None, arima_order=(1, 1, 1)):
    """
    Forecasts the next midpoint for a given symbol using an ARIMA model.

    Args:
        price_data (list): A list of dictionaries containing price data.
        arima_order (tuple): The order of the ARIMA model. Default is (1, 1, 1).

    Returns:
        float: The forecasted next midpoint. Returns NaN if model fitting fails.
    """
    # Validate price_data
    if not isinstance(price_data, list) or not all(isinstance(item, dict) for item in price_data):
        return np.nan

    # Step 1: Calculate daily midpoints
    midpoints = get_symbol_sublist('midpoint', price_data)

    # Step 2: Fit ARIMA model
    try:
        model = ARIMA(midpoints, order=arima_order)
        model_fit = model.fit()

        # Step 3: Forecast the next midpoint
        forecast = model_fit.forecast(steps=1)
        next_midpoint = forecast[0]  # Extract the predicted value for the next day
    except Exception as e:
        logging.error(f"Error fitting ARIMA model: {e}")
        next_midpoint = np.nan  # Return NaN if model fitting fails

    return next_midpoint




def forecast_next_midpoint_gaussian(price_data = None, n_days=10):
    """
    Forecasts the next midpoint for a given symbol using a Gaussian Process model.

    Args:
        price_data (list): A list of dictionaries containing price data.
        n_days (int): The number of days to use for fitting the Gaussian Process model. Default is 10.

    Returns:
        tuple: The forecasted next midpoint and the standard deviation. Returns (0, 0) if there is insufficient data.
    """
    # Validate price_data
    if not isinstance(price_data, list) or not all(isinstance(item, dict) for item in price_data):
        raise ValueError("price_data must be a list of dictionaries")

    # Step 1: Calculate daily midpoints
    midpoints = get_symbol_sublist('midpoint', price_data)
    if len(midpoints) < n_days:
        logging.warning("Not enough data to fit the model")
        return 0, 0

    # Step 2: Normalize the midpoints
    mean_midpoints = np.mean(midpoints)
    std_midpoints = np.std(midpoints)
    normalized_midpoints = (midpoints - mean_midpoints) / (std_midpoints + 1e-6)

    # Prepare the training data
    X_train = np.arange(len(normalized_midpoints[-n_days:])).reshape(-1, 1)  # Last n_days as training points
    y_train = normalized_midpoints[-n_days:]

    # Step 3: Define the Gaussian Process model with updated kernel bounds
    kernel = C(1.0, (1e-4, 1e2)) * RBF(length_scale=1, length_scale_bounds=(1e-4, 1e1))
    gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=10, alpha=1e-2)

    # Step 4: Fit the model on the training data
    gp.fit(X_train, y_train)

    # Step 5: Make a prediction for the next day
    X_next = np.array([[len(midpoints)]])  # Next point in sequence
    normalized_y_pred, normalized_sigma = gp.predict(X_next, return_std=True)

    # Step 6: Convert back to the original scale
    y_pred = normalized_y_pred * std_midpoints + mean_midpoints
    sigma = normalized_sigma * std_midpoints

    return y_pred[0], sigma[0]  # Predicted midpoint and standard deviation




def get_gaussian_predictions():
    """
    Generates Gaussian Process predictions for the top ten stability scores.

    Returns:
        list: A list of dictionaries containing the prediction results for each symbol.
    """
    results = []
    symbol_list = get_top_ten_stability_scores()
    logging.info(f"Symbol list: {symbol_list}")
    for data in symbol_list:
        logging.info(f"Processing symbol: {data['symbol']['symbol']}")
        best_percent = 1.0
        symbol = data['symbol']['symbol']
        n_days = 54
        dateRange = 130
        symbol_file = load_historical_data(symbol)
        if symbol_file is None:
            continue
        price_data = symbol_file['days'][1:dateRange]
        if len(price_data) == 0:
            continue
        try:
            predicted_midpoint, uncertainty = forecast_next_midpoint_gaussian(symbol, price_data, n_days=n_days)
            compare_midpoint = (float(price_data[0]["high"]) + float(price_data[0]["low"])) / 2
            compare_percent = abs(compare_midpoint - predicted_midpoint) / compare_midpoint
            valid_choice = predicted_midpoint * 1.01 < float(price_data[0]["high"]) and predicted_midpoint * 0.999 > float(price_data[0]['low'])
            if compare_percent < best_percent:
                results.append({
                    'symbol': symbol,
                    'n_days': n_days,
                    'dateRange': dateRange,
                    'forecasted': predicted_midpoint,
                    'uncertainty': uncertainty,
                    'actual': compare_midpoint,
                    'validity': compare_percent,
                    'valid_choice': valid_choice
                })
                best_percent = compare_percent
        except Exception as e:
            logging.error(f"Error processing symbol {symbol}: {e}")
    logging.info(f"Results: {results}")
    return results


# if __name__ == "__main__":
#     for score in get_top_ten_stability_scores():
#         price_data = load_historical_data_from_file(score["symbol"]["symbol"])['days']
#         print(f'symbol = {score["symbol"]["symbol"]}')
#         predicted_midpoint = forecast_next_midpoint(score["symbol"]["symbol"],price_data)
#         print("Forecasted Midpoint for Next Day:", predicted_midpoint)
