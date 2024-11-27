import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

class StockMidpointPredictor:
    def __init__(self, lookback_period=30):
        self.lookback_period = lookback_period
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.scaler = StandardScaler()
        
    def _calculate_technical_indicators(self, df):
        """Calculate various technical indicators."""
        df = df.copy()
        
        # Calculate midpoint
        df['midpoint'] = (df['high'] + df['low']) / 2
        
        # EMA indicators
        ema_20 = EMAIndicator(close=df['close'], window=20)
        ema_50 = EMAIndicator(close=df['close'], window=50)
        df['ema_20'] = ema_20.ema_indicator()
        df['ema_50'] = ema_50.ema_indicator()
        
        # RSI
        rsi = RSIIndicator(close=df['close'])
        df['rsi'] = rsi.rsi()
        
        # Bollinger Bands
        bb = BollingerBands(close=df['close'])
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        
        # Volatility
        df['daily_range'] = df['high'] - df['low']
        df['daily_returns'] = df['close'].pct_change()
        df['volatility'] = df['daily_returns'].rolling(window=20).std()
        
        # Volume indicators
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        return df
    
    def _create_features(self, df):
        """Create features for the model."""
        df = df.copy()
        
        # Calculate technical indicators first
        df = self._calculate_technical_indicators(df)
        
        # Create lagged features
        for i in range(1, self.lookback_period + 1):
            df[f'midpoint_lag_{i}'] = df['midpoint'].shift(i)
            df[f'volume_lag_{i}'] = df['volume'].shift(i)
            df[f'daily_range_lag_{i}'] = df['daily_range'].shift(i)
        
        # Select features for the model
        feature_columns = [col for col in df.columns if col not in ['date', 'midpoint']]
        features_df = df[feature_columns].copy()
        
        return df, features_df
    
    def train(self, df):
        """Train the model on historical data."""
        # Create features and get the processed dataframe
        processed_df, features_df = self._create_features(df)
        
        # Create target variable (next day's midpoint)
        target = processed_df['midpoint'].shift(-1)
        
        # Remove rows with NaN values (due to lagged features and shifted target)
        valid_indices = features_df.dropna().index
        features_df = features_df.loc[valid_indices]
        target = target.loc[valid_indices]
        
        # Remove the last row since we don't have the next day's target for it
        features_df = features_df.iloc[:-1]
        target = target.iloc[:-1]
        
        # Scale features
        X_scaled = self.scaler.fit_transform(features_df)
        
        # Train the model
        self.model.fit(X_scaled, target)
        
    def predict(self, df):
        """Predict the next day's midpoint."""
        # Create features
        processed_df, features_df = self._create_features(df)
        
        # Get the last complete row of features
        X = features_df.iloc[-1:].copy()
        
        # Scale features
        X_scaled = self.scaler.transform(X)
        
        # Make prediction
        prediction = self.model.predict(X_scaled)[0]
        
        return prediction
    
    def evaluate(self, df):
        """Evaluate the model's performance."""
        # Create features
        processed_df, features_df = self._create_features(df)
        target = processed_df['midpoint'].shift(-1)
        
        # Remove rows with NaN values
        valid_indices = features_df.dropna().index
        features_df = features_df.loc[valid_indices]
        target = target.loc[valid_indices]
        
        # Remove the last row since we don't have the next day's target for it
        features_df = features_df.iloc[:-1]
        target = target.iloc[:-1]
        
        # Scale features
        X_scaled = self.scaler.transform(features_df)
        
        # Make predictions
        y_pred = self.model.predict(X_scaled)
        
        # Calculate metrics
        mse = np.mean((target - y_pred) ** 2)
        rmse = np.sqrt(mse)
        mae = np.mean(np.abs(target - y_pred))
        
        return {
            'mse': mse,
            'rmse': rmse,
            'mae': mae,
            'predictions': y_pred,
            'actual': target
        }