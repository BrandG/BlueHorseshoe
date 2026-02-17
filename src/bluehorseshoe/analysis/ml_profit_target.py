"""
Module for ML-based profit target prediction.
"""
import os
from typing import Dict
from datetime import datetime
import logging
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import joblib

from bluehorseshoe.analysis.grading_engine import GradingEngine
from bluehorseshoe.analysis.ml_utils import extract_features


class ProfitTargetTrainer:
    """
    Trains a regression model to predict the optimal ATR-based profit target multiplier.
    """

    def __init__(self, model_path: str = "src/models/ml_profit_target_v1.joblib", database=None):
        """
        Initialize profit target trainer.

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

    def prepare_training_data(self, limit: int = 10000, before_date: str = None, strategy: str = None) -> pd.DataFrame:
        """
        Extracts features and labels (mfe_atr) from graded trades.
        """
        logging.info("Gathering graded trades for Profit Target training, strategy=%s, before=%s...", strategy, before_date)
        query = {"metadata.entry_price": {"$exists": True}}
        if strategy:
            query["strategy"] = strategy
        if before_date:
            query["date"] = {"$lt": before_date}

        results = self.grading_engine.run_grading(query=query, limit=limit, database=self.database)
        df_graded = pd.DataFrame(results)

        if df_graded.empty:
            logging.error("No graded trades found to train on.")
            return pd.DataFrame()

        # Filter for successful/failed trades with positive MFE
        df_graded = df_graded[df_graded['status'].isin(['success', 'failure'])]
        df_graded = df_graded[df_graded['mfe_atr'] > 0]

        features = []
        for _, row in df_graded.iterrows():
            # Extract unified features
            feat = extract_features(row['symbol'], row.get('components', {}), row['date'], database=self.database)
            if not feat:
                continue

            # Label (Target): MFE in ATR units
            feat.update({
                'TARGET': float(row.get('mfe_atr', 0.0)),
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
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred) # pylint: disable=invalid-name
        logging.info("Profit Target Regression - MSE: %.4f, MAE: %.4f, R2: %.4f", mse, mae, r2)

        # Feature Importance
        importances = pd.DataFrame({
            'feature': X_test.columns,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)
        logging.info("Top Features for Profit Target:\n" + importances.head(10).to_string())

    def train(self, limit: int = 10000, output_path: str = None, before_date: str = None, strategy: str = None):
        """
        Trains the Random Forest Regressor for profit target prediction.
        """
        if output_path is None:
            output_path = self.model_path

        df = self.prepare_training_data(limit=limit, before_date=before_date, strategy=strategy)
        if df.empty:
            return

        df = self._handle_categorical_data(df)

        # Drop non-feature columns
        X = df.drop(columns=['TARGET', 'symbol', 'date', 'strategy']) # pylint: disable=invalid-name
        y = df['TARGET']
        X = X.fillna(0)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42) # pylint: disable=invalid-name,unbalanced-tuple-unpacking
        logging.info("Training Profit Target Regressor on %d samples, testing on %d samples...", len(X_train), len(X_test))

        # Train Model
        model = RandomForestRegressor(n_estimators=150, max_depth=12, min_samples_leaf=5, min_samples_split=2, random_state=42)
        model.fit(X_train, y_train)

        self._evaluate_model(model, X_test, y_test)

        # Save model and encoders
        output = {
            'model': model,
            'encoders': self.label_encoders,
            'features': X.columns.tolist()
        }
        joblib.dump(output, output_path)
        logging.info("Profit Target Model saved to %s", output_path)

    def retrain_all(self, limit: int = 10000, before_date: str = None):
        """
        Retrains all models (General, Baseline, Mean Reversion).
        """
        logging.info("Starting automated retraining of all Profit Target models (limit=%s, before=%s)...", limit, before_date)

        # 1. General Model
        self.train(limit=limit, output_path="src/models/ml_profit_target_v1.joblib", before_date=before_date)

        # 2. Strategy-Specific Models
        self.train(limit=limit, strategy="baseline", output_path="src/models/ml_profit_target_baseline.joblib", before_date=before_date)

        self.train(limit=limit, strategy="mean_reversion", output_path="src/models/ml_profit_target_mean_reversion.joblib", before_date=before_date)

        logging.info("Automated Profit Target retraining complete.")


class ProfitTargetInference:
    """
    Predicts optimal ATR multiplier for profit targets.
    """
    # pylint: disable=too-few-public-methods
    def __init__(self, database=None):
        """
        Initialize profit target inference.

        Args:
            database: MongoDB database instance. Required for feature extraction.
        """
        self.database = database
        self.models = {}
        self.encoders = {}
        self.features = {}
        self._load_models()

    def _load_models(self):
        """Load all profit target models (general + strategy-specific)."""
        model_paths = {
            'general': 'src/models/ml_profit_target_v1.joblib',
            'baseline': 'src/models/ml_profit_target_baseline.joblib',
            'mean_reversion': 'src/models/ml_profit_target_mean_reversion.joblib',
        }
        for key, path in model_paths.items():
            if os.path.exists(path):
                try:
                    data = joblib.load(path)
                    self.models[key] = data['model']
                    self.encoders[key] = data.get('encoders', {})
                    self.features[key] = data.get('features', [])
                    logging.info("Profit Target model (%s) loaded from %s", key, path)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logging.warning("Failed to load Profit Target model %s: %s", path, e)

    def _encode_features(self, feat: Dict, encoders: Dict) -> Dict:
        """Helper to encode categorical features for inference."""
        for col in ['Sector', 'Industry']:
            le = encoders.get(col)
            val = str(feat.get(col, 'Unknown'))
            if le:
                try:
                    feat[col] = le.transform([val])[0]
                except ValueError:
                    feat[col] = 0
            else:
                feat[col] = 0
        return feat

    def _prepare_inference_df(self, feat: Dict, feature_list: list) -> pd.DataFrame:
        """Aligns feature dict with model training features and returns DataFrame."""
        df = pd.DataFrame([feat])
        for f in feature_list: # pylint: disable=invalid-name
            if f not in df.columns:
                df[f] = 0.0
        return df[feature_list].fillna(0)

    def predict_profit_target_multiplier(self, symbol: str, components: Dict[str, float],
                                          target_date: str = None, strategy: str = "general") -> float:
        """
        Predicts the recommended ATR multiplier for the profit target.

        Args:
            symbol: Stock symbol.
            components: Technical indicator scores.
            target_date: Target date for prediction.
            strategy: Strategy name for model selection.

        Returns:
            Recommended ATR multiplier for profit target.
        """
        if self.database is None:
            raise ValueError("database parameter is required for predict_profit_target_multiplier")

        # Fallback defaults per strategy
        fallback = 3.0 if strategy == "baseline" else 2.0

        # Select model: strategy-specific, fallback to general
        model_key = strategy if strategy in self.models else "general"
        model = self.models.get(model_key)

        if model is None:
            return fallback

        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")

        feat = extract_features(symbol, components, target_date, database=self.database)
        feat = self._encode_features(feat, self.encoders.get(model_key, {}))
        df_inf = self._prepare_inference_df(feat, self.features.get(model_key, []))

        predicted_mfe = float(model.predict(df_inf)[0])

        # Apply safety factor and clamp
        recommended_multiplier = predicted_mfe * 0.75
        recommended_multiplier = max(1.5, min(2.5, recommended_multiplier))
        return recommended_multiplier
