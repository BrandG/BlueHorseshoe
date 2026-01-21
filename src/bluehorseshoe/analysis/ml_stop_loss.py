"""
Module for ML-based stop loss prediction.
"""
import os
from typing import Dict
from datetime import datetime
import logging
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_squared_error, r2_score
import joblib

from bluehorseshoe.analysis.grading_engine import GradingEngine
from bluehorseshoe.analysis.ml_utils import extract_features

class StopLossTrainer:
    """
    Trains a regression model to predict the optimal ATR-based stop loss distance.
    """

    def __init__(self, model_path: str = "src/models/ml_stop_loss_v1.joblib", database=None):
        """
        Initialize stop loss trainer.

        Args:
            model_path: Path to save/load the trained model
            database: MongoDB database instance. Required for grading engine operations.
        """
        self.model_path = model_path
        self.database = database
        self.grading_engine = GradingEngine(hold_days=10, database=database)
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

        results = self.grading_engine.run_grading(query=query, limit=limit, database=self.database)
        df_graded = pd.DataFrame(results)

        if df_graded.empty:
            logging.error("No graded trades found to train on.")
            return pd.DataFrame()

        # We want to train on both successes and failures to see how deep they go
        df_graded = df_graded[df_graded['status'].isin(['success', 'failure'])]

        features = []
        for _, row in df_graded.iterrows():
            # Extract unified features
            feat = extract_features(row['symbol'], row.get('components', {}), row['date'])
            if not feat:
                continue

            # 3. Label (Target): MAE in ATR units
            feat.update({
                'TARGET': float(row.get('mae_atr', 0.0)),
                'symbol': row['symbol'],
                'date': row['date'],
                'strategy': row.get('strategy', 'unknown')
            })
            features.append(feat)

        return pd.DataFrame(features)

    def _handle_categorical_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Encodes categorical columns and stores encoders."""
        categorical_cols = ['Sector', 'Industry']
        for col in categorical_cols:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))
            self.label_encoders[col] = le
        return df

    def _evaluate_model(self, model, X_test, y_test): # pylint: disable=invalid-name
        """Evaluates model performance and logs metrics."""
        y_pred = model.predict(X_test)
        mse = mean_squared_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred) # pylint: disable=invalid-name
        logging.info("Regression Performance - MSE: %.4f, R2: %.4f", mse, r2)

        # Feature Importance
        importances = pd.DataFrame({
            'feature': X_test.columns,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)
        logging.info("Top Features for Stop Loss:\n" + importances.head(10).to_string())

    def train(self, limit: int = 10000, output_path: str = None, before_date: str = None):
        """
        Trains the Random Forest Regressor.
        """
        if output_path is None:
            output_path = self.model_path

        df = self.prepare_training_data(limit=limit, before_date=before_date)
        if df.empty:
            return

        df = self._handle_categorical_data(df)

        # Drop non-feature columns
        X = df.drop(columns=['TARGET', 'symbol', 'date', 'strategy']) # pylint: disable=invalid-name
        y = df['TARGET']
        X = X.fillna(0)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42) # pylint: disable=invalid-name,unbalanced-tuple-unpacking
        logging.info("Training Regressor on %d samples, testing on %d samples...", len(X_train), len(X_test))

        # Train Model
        model = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42)
        model.fit(X_train, y_train)

        self._evaluate_model(model, X_test, y_test)

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
    # pylint: disable=too-few-public-methods
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

    def _encode_features(self, feat: Dict) -> Dict:
        """Helper to encode categorical features for inference."""
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
        return feat

    def _prepare_inference_df(self, feat: Dict) -> pd.DataFrame:
        """Aligns feature dict with model training features and returns DataFrame."""
        df = pd.DataFrame([feat])
        for f in self.features: # pylint: disable=invalid-name
            if f not in df.columns:
                df[f] = 0.0
        return df[self.features].fillna(0)

    def predict_stop_loss_multiplier(self, symbol: str, components: Dict[str, float], target_date: str = None) -> float:
        """
        Predicts the recommended ATR multiplier for the stop loss.
        """
        if self.model is None:
            return 2.0  # Default fallback

        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")

        feat = extract_features(symbol, components, target_date)
        feat = self._encode_features(feat)
        df_inf = self._prepare_inference_df(feat)

        predicted_mae = float(self.model.predict(df_inf)[0])

        # We recommend a stop loss slightly beyond the predicted MAE
        # e.g., predicted_mae + 0.5 ATR, with a minimum of 1.5 ATR
        recommended_multiplier = max(1.5, predicted_mae + 0.5)
        return recommended_multiplier
