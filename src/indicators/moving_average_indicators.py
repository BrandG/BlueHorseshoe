"""
This module contains the MovingAverageIndicator class for calculating moving average crossovers.
Classes:
    MovingAverageIndicator: A class for calculating moving average crossovers using either simple moving averages (SMA) 
        or exponential moving averages (EMA).
Usage example:
    # Sample data
    data = pd.DataFrame({
        'close': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    })
    # Initialize the indicator
    indicator = MovingAverageIndicator(data)
    # Calculate crossovers
    score = indicator.calculate_crossovers(fast_period=3, slow_period=5, use_ema=True)
    print(score)
"""
import pandas as pd

class MovingAverageIndicator: # pylint: disable=too-few-public-methods
    """
    MovingAverageIndicator class for calculating moving average crossovers.
    Attributes:
        data (pd.DataFrame): DataFrame containing the price data with a 'close' column.
    Methods:
        __init__(data: pd.DataFrame):
            Initializes the MovingAverageIndicator with the provided data.
        calculate_crossovers(fast_period=50, slow_period=200, use_ema=True) -> int:
            Calculates MA/EMA crossovers and returns a score based on the crossover.
            - fast_period (int): Period for the fast moving average. Default is 50.
            - slow_period (int): Period for the slow moving average. Default is 200.
            - use_ema (bool): Whether to use EMA (True) or SMA (False). Default is True.
            - int: 1 if a bullish crossover occurs, -1 if a bearish crossover occurs, 0 otherwise.
    """

    def __init__(self, data: pd.DataFrame):
        self.data = data

    def calculate_crossovers(self, fast_period=50, slow_period=200, use_ema=True):
        """
        Calculates MA/EMA crossovers and adjusts a scoring system.
        
        Parameters:
        - data (pd.DataFrame): DataFrame with 'Close' column for prices.
        - fast_period (int): Period for the fast moving average.
        - slow_period (int): Period for the slow moving average.
        - use_ema (bool): Whether to use EMA (True) or SMA (False).
        
        Returns:
        - pd.DataFrame: DataFrame with 'Fast_MA', 'Slow_MA', and 'Score' columns.
        """
        data = self.data.copy()
        # Calculate the moving averages
        if use_ema:
            data['Fast_MA'] = data['close'].ewm(span=fast_period, adjust=False).mean()
            data['Slow_MA'] = data['close'].ewm(span=slow_period, adjust=False).mean()
        else:
            data['Fast_MA'] = data['close'].rolling(window=fast_period).mean()
            data['Slow_MA'] = data['close'].rolling(window=slow_period).mean()

        if data['Fast_MA'].iloc[-1] > data['Slow_MA'].iloc[-1] and data['Fast_MA'].iloc[-2] <= data['Slow_MA'].iloc[-2]:
            return 1
        if data['Fast_MA'].iloc[-1] < data['Slow_MA'].iloc[-1] and data['Fast_MA'].iloc[-2] >= data['Slow_MA'].iloc[-2]:
            return -1
        return 0
