from datetime import datetime
from keras._tf_keras.keras.layers import LSTM, Dense
from keras._tf_keras.keras.callbacks import EarlyStopping
from keras._tf_keras.keras.models import Sequential
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from torch import lstm
from sklearn.metrics import mean_squared_error
import matplotlib.pyplot as plt

from Globals import report


# Select features for scaling
features = ['open', 'close', 'high', 'low', 'volume', 'MA5', 'RSI14']

sequence_length = 10  # Number of past days to use for prediction


def create_sequences(data, seq_length):
    X = []
    y = []
    
    for i in range(len(data) - seq_length):
        X_seq = data.iloc[i:(i + seq_length)][features].values
        y_seq = data.iloc[i + seq_length]['midpoint']
        X.append(X_seq)
        y.append(y_seq)
    return np.array(X), np.array(y)

# Relative Strength Index (RSI)
def compute_RSI(data, time_window):
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

def get_nn_prediction(price_data):

    scaled_df = getFeatures(price_data)
    report(f'price_data size = {len(price_data)}')
    report(f'Original Price data - {price_data[:5]}\n\n')
    report(f'Scaled Price data - {scaled_df[:5]}')

    model = buildModel(scaled_df)

    next_midpoint = predictNextMidpoint(model, scaled_df)

    return next_midpoint

def getFeatures(price_data):
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

    df['RSI14'] = compute_RSI(df['close'], 14)

    report(f'Price data - {df[:5]}')

    # Drop NaN values resulting from indicators
    df.dropna(inplace=True)

    report(f'Price data - nans removed - {df[:5]}')

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

def buildModel(scaled_df):
    # Define the proportion of data to be used for training
    train_size = int(len(scaled_df) * 0.8)

    # Split the data
    train_df = scaled_df.iloc[:(len(scaled_df) - train_size)]
    test_df = scaled_df.iloc[(len(scaled_df) - train_size):]

    # Create sequences for training
    X_train, y_train = create_sequences(train_df, sequence_length)

    # Create sequences for testing
    X_test, y_test = create_sequences(test_df, sequence_length)

    # Build the LSTM model
    model = Sequential()
    model.add(LSTM(units=50, activation='relu', input_shape=(sequence_length, len(features))))
    model.add(Dense(1))  # Output layer

    model.compile(optimizer='adam', loss='mse')

    # Define early stopping to prevent overfitting
    early_stopping = EarlyStopping(monitor='val_loss', patience=10)

    # Train the model
    history = model.fit(
        X_train, y_train,
        validation_data=(X_test, y_test),
        epochs=100,
        batch_size=32,
        callbacks=[early_stopping],
        verbose=1
    )

    # Make predictions on the test set
    y_pred = model.predict(X_test)

    # Compare the predicted midpoints with the actual midpoints
    comparison_df = pd.DataFrame({'Actual': y_test, 'Predicted': y_pred.flatten()}, index=test_df.index[sequence_length:])

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

    print(f"Training sequences shape: {X_train.shape}")
    print(f"Testing sequences shape: {X_test.shape}")

    print(comparison_df.head())

    print(f"Mean Squared Error on Test Set: {mse}")
    print(f"Root Mean Squared Error on Test Set: {rmse}")

    return model

def predictNextMidpoint(model, scaled_df):
    # Get the last 'sequence_length' data points from the scaled_df
    last_sequence = scaled_df[features].iloc[-sequence_length:].values
    last_sequence = last_sequence.reshape((1, sequence_length, len(features)))

    # Predict the next midpoint
    next_midpoint = model.predict(last_sequence)
    print(f"The predicted next midpoint is: {next_midpoint[0][0]}")
    return next_midpoint[0][0]
