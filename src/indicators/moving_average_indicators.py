import pandas as pd


class MovingAverageIndicator:

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
