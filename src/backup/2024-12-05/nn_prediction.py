"""
This module provides functions for predicting the next midpoint price using a neural network model.
It includes functions for feature extraction, sequence creation, model building, and prediction.

Functions:
    create_sequences(data, seq_length):

    compute_rsi(data, time_window):

    get_features(price_data):

    get_nn_prediction(price_data):

    build_model(scaled_df):

    predict_next_midpoint(model, scaled_df):
        Predicts the next midpoint using the provided model and scaled dataframe.

"""

# # usage
# price_data = load_historical_data('IBM')
# print(price_data['days'][0])
# get_nn_prediction(price_data['days'][::-1])



from datetime import datetime
from keras._tf_keras.keras.layers import LSTM, Dense
from keras._tf_keras.keras.callbacks import EarlyStopping
from keras._tf_keras.keras.models import Sequential
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error
import matplotlib.pyplot as plt

from globals import ReportSingleton


# Select features for scaling
features = ['open', 'close', 'high', 'low', 'volume', 'MA5', 'RSI14']

SEQUENCE_LENGTH = 10  # Number of past days to use for prediction


def create_sequences(data, seq_length):
    """
    Generates sequences of features and corresponding target values from the input data.

    Args:
        data (pd.DataFrame): The input data containing features and target values.
        seq_length (int): The length of each sequence to be created.

    Returns:
        tuple: A tuple containing two numpy arrays:
            - X (np.ndarray): Array of sequences of features with shape (num_sequences, seq_length, num_features).
            - y (np.ndarray): Array of target values corresponding to each sequence with shape (num_sequences,).
    """
    x = []
    y = []

    for i in range(len(data) - seq_length):
        x_seq = data.iloc[i:(i + seq_length)][features].values
        y_seq = data.iloc[i + seq_length]['midpoint']
        x.append(x_seq)
        y.append(y_seq)
    return np.array(x), np.array(y)

# Relative Strength Index (RSI)
def compute_rsi(data, time_window):
    """
    Computes the Relative Strength Index (RSI) for a given dataset and time window.

    Parameters:
    data (pandas.Series): The input data series for which RSI is to be computed.
    time_window (int): The time window over which to compute the RSI.

    Returns:
    pandas.Series: A series representing the RSI values for the input data.
    """
    diff = data.diff(1).dropna()
    up_chg = 0 * diff
    down_chg = 0 * diff

    up_chg[diff > 0] = diff[ diff > 0 ]
    down_chg[diff < 0] = -diff[ diff < 0 ]

    up_chg_avg   = up_chg.rolling(window=time_window, min_periods=1).mean()
    down_chg_avg = down_chg.rolling(window=time_window, min_periods=1).mean()

    rs = up_chg_avg / down_chg_avg
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_features(price_data):
    """
    Processes the given price data to extract features for machine learning models.

    Args:
        price_data (list or dict): The raw price data containing 'date', 'high', 'low', and 'close' prices.

    Returns:
        pd.DataFrame: A DataFrame containing the scaled features and the target variable 'midpoint'.

    Features:
        - 'midpoint': The midpoint of 'high' and 'low' prices.
        - 'MA5': 5-day moving average of the 'close' prices.
        - 'RSI14': 14-day Relative Strength Index of the 'close' prices.

    Notes:
        - The 'date' column is converted to datetime and set as the index.
        - NaN values resulting from the calculation of indicators are dropped.
        - The features are scaled using MinMaxScaler.
    """
    # Convert to DataFrame
    df = pd.DataFrame(price_data)

    # Ensure 'Date' is a datetime type
    df['date'] = pd.to_datetime(df['date'])

    # Set 'Date' as the index
    df.set_index('date', inplace=True)

    # Calculate the midpoint
    df['midpoint'] = (df['high'] + df['low']) / 2

    # Moving Average (MA)
    df['MA5'] = df['close'].rolling(window=5).mean()

    df['RSI14'] = compute_rsi(df['close'], 14)

    ReportSingleton().write(f'Price data - {df[:5]}')

    # Drop NaN values resulting from indicators
    df.dropna(inplace=True)

    ReportSingleton().write(f'Price data - nans removed - {df[:5]}')

    # Initialize the scaler
    scaler = MinMaxScaler()

    # Fit and transform the data
    scaled_features = scaler.fit_transform(df[features])

    # Create a new DataFrame for the scaled features
    scaled_df = pd.DataFrame(scaled_features, index=df.index, columns=features)

    # Add the target variable 'Midpoint' (you may also scale it if needed)
    scaled_df['midpoint'] = df['midpoint'].values

    print(df.head())
    print(scaled_df.head())
    print(f"Original data shape: {df.shape}")

    return scaled_df

def get_nn_prediction(price_data):
    """
    Generates a neural network prediction for the next midpoint price based on the given price data.

    Args:
        price_data (pd.DataFrame): A DataFrame containing the price data to be used for prediction.

    Returns:
        float: The predicted next midpoint price.

    Notes:
        - The function scales the input price data using the get_features function.
        - It logs the size and a sample of the original and scaled price data using the ReportSingleton.
        - It builds a neural network model using the scaled data with the build_model function.
        - It predicts the next midpoint price using the predict_next_midpoint function.
    """
    scaled_df = get_features(price_data)
    ReportSingleton().write(f'price_data size = {len(price_data)}')
    ReportSingleton().write(f'Original Price data - {price_data[:5]}\n\n')
    ReportSingleton().write(f'Scaled Price data - {scaled_df[:5]}')

    model = build_model(scaled_df)

    next_midpoint = predict_next_midpoint(model, scaled_df)

    return next_midpoint

def build_model(scaled_df):
    """
    Builds and trains an LSTM model for time series prediction using the provided scaled DataFrame.

    Args:
        scaled_df (pd.DataFrame): The scaled DataFrame containing the time series data.

    Returns:
        model (keras.Sequential): The trained LSTM model.

    The function performs the following steps:
    1. Splits the data into training and testing sets.
    2. Creates sequences for training and testing.
    3. Builds an LSTM model with specified architecture.
    4. Compiles the model with Adam optimizer and mean squared error loss.
    5. Defines early stopping to prevent overfitting.
    6. Trains the model on the training data and validates on the testing data.
    7. Makes predictions on the test set.
    8. Compares the predicted values with the actual values.
    9. Calculates and prints the Mean Squared Error (MSE) and Root Mean Squared Error (RMSE) on the test set.
    10. Plots and saves the comparison graph of actual vs predicted values.

    Note:
        - The function assumes the existence of a `create_sequences` function to generate sequences from the DataFrame.
        - The `SEQUENCE_LENGTH` and `features` variables should be defined in the global scope.
        - The function uses `EarlyStopping` from `keras.callbacks` and `Sequential`, `LSTM`, `Dense` from `keras.models`.
        - The function uses `mean_squared_error` from `sklearn.metrics` and `pd`, `np`, `plt`, `datetime` from their respective libraries.
    """
    # Define the proportion of data to be used for training
    train_size = int(len(scaled_df) * 0.8)

    # Split the data
    train_df = scaled_df.iloc[:(len(scaled_df) - train_size)]
    test_df = scaled_df.iloc[(len(scaled_df) - train_size):]

    # Create sequences for training
    x_train, y_train = create_sequences(train_df, SEQUENCE_LENGTH)

    # Create sequences for testing
    x_test, y_test = create_sequences(test_df, SEQUENCE_LENGTH)

    # Build the LSTM model
    model = Sequential()
    model.add(LSTM(units=50, activation='relu', input_shape=(SEQUENCE_LENGTH, len(features))))
    model.add(Dense(1))  # Output layer

    model.compile(optimizer='adam', loss='mse')

    # Define early stopping to prevent overfitting
    early_stopping = EarlyStopping(monitor='val_loss', patience=10)

    # Train the model
    model.fit(
        x_train, y_train,
        validation_data=(x_test, y_test),
        epochs=100,
        batch_size=32,
        callbacks=[early_stopping],
        verbose='1'
    )

    # Make predictions on the test set
    y_pred = model.predict(x_train)

    # Compare the predicted midpoints with the actual midpoints
    comparison_df = pd.DataFrame({'Actual': y_test, 'Predicted': y_pred.flatten()}, index=test_df.index[SEQUENCE_LENGTH:])

    # Calculate Mean Squared Error
    mse = mean_squared_error(y_test, y_pred)

    # Optionally, calculate Root Mean Squared Error
    rmse = np.sqrt(mse)

    plt.figure(figsize=(12, 6))
    plt.plot(comparison_df['Actual'], label='Actual Midpoint')
    plt.plot(comparison_df['Predicted'], label='Predicted Midpoint')
    plt.title('Actual vs Predicted Midpoint')
    plt.xlabel('Date')
    plt.ylabel('Midpoint')
    plt.legend()
    current_time_ms = int(datetime.now().timestamp() * 1000)
    plt.savefig(f'graphs/dbug_{current_time_ms}.png')
    # plt.show()

    print(f"Training data shape: {train_df.shape}")
    print(f"Testing data shape: {test_df.shape}")

    print(f"Training sequences shape: {x_train.shape}")
    print(f"Testing sequences shape: {x_test.shape}")

    print(comparison_df.head())

    print(f"Mean Squared Error on Test Set: {mse}")
    print(f"Root Mean Squared Error on Test Set: {rmse}")

    return model

def predict_next_midpoint(model, scaled_df):
    """
    Predict the next midpoint using the provided model and scaled dataframe.

    Args:
        model (keras.Model): The trained model used for making predictions.
        scaled_df (pandas.DataFrame): The dataframe containing the scaled data.

    Returns:
        float: The predicted next midpoint value.
    """
    # Get the last 'SEQUENCE_LENGTH' data points from the scaled_df
    last_sequence = scaled_df[features].iloc[-SEQUENCE_LENGTH:].values
    last_sequence = last_sequence.reshape((1, SEQUENCE_LENGTH, len(features)))

    # Predict the next midpoint
    next_midpoint = model.predict(last_sequence)
    print(f"The predicted next midpoint is: {next_midpoint[0][0]}")
    return next_midpoint[0][0]
