"""
Module for ML-based trade signal overlay.
"""
import os
from typing import Dict
from datetime import datetime
import logging
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report
import joblib

from bluehorseshoe.analysis.grading_engine import GradingEngine
from bluehorseshoe.analysis.ml_utils import extract_features

class MLOverlayTrainer:
    """
    Trains a Machine Learning model to act as a filter/overlay for technical signals.
    """

    def __init__(self, model_path: str = "src/models/ml_overlay_v1.joblib", database=None):
        """
        Initialize ML overlay trainer.

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

    def prepare_training_data(self, limit: int = 10000, strategy: str = None, before_date: str = None) -> pd.DataFrame:
        """
        Extracts features and labels from graded trades and fundamental data.
        """
        logging.info("Gathering graded trades for strategy=%s, before=%s...", strategy, before_date)
        # Get graded results (Success/Failure)
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

        # Filter for successful/failed trades only
        df_graded = df_graded[df_graded['status'].isin(['success', 'failure'])]

        features = []
        for _, row in df_graded.iterrows():
            # Extract unified features
            feat = extract_features(row['symbol'], row.get('components', {}), row['date'])
            if not feat:
                continue

            # 3. Label (Target)
            feat.update({
                'TARGET': 1 if row['status'] == 'success' else 0,
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
        logging.info("Classification Report:\n%s", classification_report(y_test, y_pred))

        # Calculate Feature Importance
        importances = pd.DataFrame({
            'feature': X_test.columns,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)
        logging.info("Top Features:\n%s", importances.head(10).to_string())

    def train(self, limit: int = 10000, strategy: str = None, output_path: str = None, before_date: str = None):
        """
        Trains the Random Forest model.
        """
        if output_path is None:
            output_path = self.model_path

        df = self.prepare_training_data(limit=limit, strategy=strategy, before_date=before_date)
        if df.empty:
            return

        df = self._handle_categorical_data(df)

        # Drop non-feature columns
        X = df.drop(columns=['TARGET', 'symbol', 'date', 'strategy']) # pylint: disable=invalid-name
        y = df['TARGET']
        X = X.fillna(0)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42) # pylint: disable=invalid-name,unbalanced-tuple-unpacking
        logging.info("Training on %d samples, testing on %d samples...", len(X_train), len(X_test))

        # Train Model
        model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
        model.fit(X_train, y_train)

        self._evaluate_model(model, X_test, y_test)

        # Save model and encoders
        output = {
            'model': model,
            'encoders': self.label_encoders,
            'features': X.columns.tolist()
        }
        joblib.dump(output, output_path)
        logging.info("Model saved to %s", output_path)

    def retrain_all(self, limit: int = 10000, before_date: str = None):
        """
        Retrains all models (General, Baseline, Mean Reversion).
        """
        logging.info("Starting automated retraining of all models (limit=%s, before=%s)...", limit, before_date)

        # 1. General Model
        self.train(limit=limit, output_path="src/models/ml_overlay_v1.joblib", before_date=before_date)

        # 2. Strategy-Specific Models
        self.train(limit=limit, strategy="baseline", output_path="src/models/ml_overlay_baseline.joblib", before_date=before_date)

        self.train(limit=limit, strategy="mean_reversion", output_path="src/models/ml_overlay_mean_reversion.joblib", before_date=before_date)

        logging.info("Automated retraining complete.")

class MLInference:
    """
    Handles loading the trained ML model and performing predictions.
    """
    # pylint: disable=too-few-public-methods
    def __init__(self, model_path: str = "src/models/ml_overlay_v1.joblib"):
        self.model_path = model_path
        self.models = {} # Cache for strategy-specific models
        self.encoders = {}
        self.features = {} # Cache for features per model
        self._load_model(model_path, "general")

    def _load_model(self, path: str, key: str):
        if os.path.exists(path):
            data = joblib.load(path)
            self.models[key] = data['model']
            self.encoders[key] = data['encoders']
            self.features[key] = data['features']
            logging.info("ML Overlay model (%s) loaded from %s", key, path)
        else:
            if key == "general":
                logging.warning("ML Overlay model not found at %s", path)

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

    def _prepare_inference_df(self, feat: Dict, model_key: str) -> pd.DataFrame:
        """Aligns feature dict with model training features and returns DataFrame."""
        df = pd.DataFrame([feat])
        model_features = self.features.get(model_key, [])
        for f in model_features: # pylint: disable=invalid-name
            if f not in df.columns:
                df[f] = 0.0
        return df[model_features].fillna(0)

    def predict_probability(self, symbol: str, components: Dict[str, float], target_date: str = None, strategy: str = "general") -> float:
        """
        Predicts the win probability for a given symbol and technical components.
        """
        # Try to load strategy-specific model if not already loaded
        if strategy != "general" and strategy not in self.models:
            strat_path = f"src/models/ml_overlay_{strategy}.joblib"
            self._load_model(strat_path, strategy)

        # Fallback to general model
        model_key = strategy if strategy in self.models else "general"
        model = self.models.get(model_key)

        if model is None:
            return 0.0

        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")

        # Build feature vector
        feat = extract_features(symbol, components, target_date)
        feat = self._encode_features(feat, self.encoders.get(model_key, {}))
        df_inf = self._prepare_inference_df(feat, model_key)

        # Predict probability of class 1 (Success)
        probs = model.predict_proba(df_inf)[0]
        return float(probs[1])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    trainer = MLOverlayTrainer()
    trainer.train(limit=5000)
