"""
Module for ML-based stop loss prediction.
"""
import logging
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_squared_error, r2_score
import joblib
import os
from typing import Dict
from datetime import datetime

from bluehorseshoe.analysis.grading_engine import GradingEngine
from bluehorseshoe.analysis.ml_utils import extract_features

class StopLossTrainer:
    """
    Trains a regression model to predict the optimal ATR-based stop loss distance.
    """

    def __init__(self, model_path: str = "src/models/ml_stop_loss_v1.joblib"):
        self.model_path = model_path
        self.grading_engine = GradingEngine(hold_days=10)
        self.label_encoders = {}

        # Ensure models directory exists
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

    def prepare_training_data(self, limit: int = 10000, before_date: str = None) -> pd.DataFrame:
        """
        Extracts features and labels (mae_atr) from graded trades.
        """
        logging.info("Gathering graded trades for Stop Loss training, before=%s...", before_date)
        query = {"metadata.entry_price": {"$exists": True}}
        if before_date:
            query["date"] = {"$lt": before_date}

        results = self.grading_engine.run_grading(query=query, limit=limit)
        df_graded = pd.DataFrame(results)

        if df_graded.empty:
            logging.error("No graded trades found to train on.")
            return pd.DataFrame()

        # We want to train on both successes and failures to see how deep they go
        df_graded = df_graded[df_graded['status'].isin(['success', 'failure'])]

        features = []
        for _, row in df_graded.iterrows():
            symbol = row['symbol']

            # Technical Components
            components = row.get('components', {})
            if not components:
                continue

            # Extract unified features
            feat = extract_features(symbol, components, row['date'])

            # 3. Label (Target): MAE in ATR units
            feat['TARGET'] = float(row.get('mae_atr', 0.0))

            # Meta
            feat['symbol'] = symbol
            feat['date'] = row['date']
            feat['strategy'] = row.get('strategy', 'unknown')

            features.append(feat)

        return pd.DataFrame(features)

    def train(self, limit: int = 10000, output_path: str = None, before_date: str = None):
        """
        Trains the Random Forest Regressor.
        """
        if output_path is None:
            output_path = self.model_path

        df = self.prepare_training_data(limit=limit, before_date=before_date)
        if df.empty:
            return

        # Handle Categorical Data
        categorical_cols = ['Sector', 'Industry']
        for col in categorical_cols:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))
            self.label_encoders[col] = le

        # Drop non-feature columns
        X = df.drop(columns=['TARGET', 'symbol', 'date', 'strategy'])
        y = df['TARGET']

        X = X.fillna(0)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        logging.info("Training Regressor on %d samples, testing on %d samples...", len(X_train), len(X_test))

        # Train Model
        model = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42)
        model.fit(X_train, y_train)

        # Evaluate
        y_pred = model.predict(X_test)
        mse = mean_squared_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        logging.info("Regression Performance - MSE: %.4f, R2: %.4f", mse, r2)

        # Feature Importance
        importances = pd.DataFrame({
            'feature': X.columns,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)

        logging.info("Top Features for Stop Loss:\n" + importances.head(10).to_string())

        # Save model and encoders
        output = {
            'model': model,
            'encoders': self.label_encoders,
            'features': X.columns.tolist()
        }
        joblib.dump(output, output_path)
        logging.info("Stop Loss Model saved to %s", output_path)

class StopLossInference:
    """
    Predicts optimal ATR multiplier for a stop loss.
    """
    def __init__(self, model_path: str = "src/models/ml_stop_loss_v1.joblib"):
        self.model_path = model_path
        self.model = None
        self.encoders = {}
        self.features = []
        self._load_model()

    def _load_model(self):
        if os.path.exists(self.model_path):
            data = joblib.load(self.model_path)
            self.model = data['model']
            self.encoders = data['encoders']
            self.features = data['features']
            logging.info("Stop Loss Model loaded from %s", self.model_path)

    def predict_stop_loss_multiplier(self, symbol: str, components: Dict[str, float], target_date: str = None) -> float:
        """
        Predicts the recommended ATR multiplier for the stop loss.
        """
        if self.model is None:
            return 2.0  # Default fallback

        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")

        feat = extract_features(symbol, components, target_date)

        for col in ['Sector', 'Industry']:
            le = self.encoders.get(col)
            val = str(feat.get(col, 'Unknown'))
            if le:
                try:
                    feat[col] = le.transform([val])[0]
                except ValueError:
                    feat[col] = 0
            else:
                feat[col] = 0

        df = pd.DataFrame([feat])
        for f in self.features:
            if f not in df.columns:
                df[f] = 0.0

        df = df[self.features]
        df = df.fillna(0)

        predicted_mae = float(self.model.predict(df)[0])

        # We recommend a stop loss slightly beyond the predicted MAE
        # e.g., predicted_mae + 0.5 ATR, with a minimum of 1.5 ATR
        recommended_multiplier = max(1.5, predicted_mae + 0.5)
        return recommended_multiplier
