import logging
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report
import joblib
import os
from typing import Dict
from datetime import datetime

from bluehorseshoe.analysis.grading_engine import GradingEngine
from bluehorseshoe.analysis.ml_utils import extract_features

class MLOverlayTrainer:
    """
    Trains a Machine Learning model to act as a filter/overlay for technical signals.
    """

    def __init__(self, model_path: str = "src/models/ml_overlay_v1.joblib"):
        self.model_path = model_path
        self.grading_engine = GradingEngine(hold_days=10)
        self.label_encoders = {}

        # Ensure models directory exists
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

    def prepare_training_data(self, limit: int = 10000, strategy: str = None, before_date: str = None) -> pd.DataFrame:
        """
        Extracts features and labels from graded trades and fundamental data.
        """
        logging.info(f"Gathering graded trades for strategy={strategy}, before={before_date}...")
        # Get graded results (Success/Failure)
        query = {"metadata.entry_price": {"$exists": True}}
        if strategy:
            query["strategy"] = strategy

        if before_date:
            query["date"] = {"$lt": before_date}

        results = self.grading_engine.run_grading(query=query, limit=limit)
        df_graded = pd.DataFrame(results)

        if df_graded.empty:
            logging.error("No graded trades found to train on.")
            return pd.DataFrame()

        # Filter for successful/failed trades only
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

            # 3. Label (Target)
            feat['TARGET'] = 1 if row['status'] == 'success' else 0
            feat['symbol'] = symbol
            feat['date'] = row['date']
            feat['strategy'] = row.get('strategy', 'unknown')

            features.append(feat)

        return pd.DataFrame(features)

    def train(self, limit: int = 10000, strategy: str = None, output_path: str = None, before_date: str = None):
        """
        Trains the Random Forest model.
        """
        if output_path is None:
            output_path = self.model_path

        df = self.prepare_training_data(limit=limit, strategy=strategy, before_date=before_date)
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

        # Fill NaNs
        X = X.fillna(0)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        logging.info(f"Training on {len(X_train)} samples, testing on {len(X_test)} samples...")

        # Train Model
        model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
        model.fit(X_train, y_train)

        # Evaluate
        y_pred = model.predict(X_test)
        logging.info("\n" + classification_report(y_test, y_pred))

        # Calculate Feature Importance
        importances = pd.DataFrame({
            'feature': X.columns,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)

        logging.info("Top Features:\n" + importances.head(10).to_string())

        # Save model and encoders
        output = {
            'model': model,
            'encoders': self.label_encoders,
            'features': X.columns.tolist()
        }
        joblib.dump(output, output_path)
        logging.info(f"Model saved to {output_path}")

    def retrain_all(self, limit: int = 10000, before_date: str = None):
        """
        Retrains all models (General, Baseline, Mean Reversion).
        """
        logging.info(f"Starting automated retraining of all models (limit={limit}, before={before_date})...")

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
            logging.info(f"ML Overlay model ({key}) loaded from {path}")
        else:
            if key == "general":
                logging.warning(f"ML Overlay model not found at {path}")

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

        # Encode categorical
        encoders = self.encoders.get(model_key, {})
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

        # Create DataFrame aligned with training features
        df = pd.DataFrame([feat])

        # Ensure all training features are present
        model_features = self.features.get(model_key, [])
        for f in model_features:
            if f not in df.columns:
                df[f] = 0.0

        # Reorder columns to match training
        df = df[model_features]
        df = df.fillna(0)

        # Predict probability of class 1 (Success)
        probs = model.predict_proba(df)[0]
        return float(probs[1])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    trainer = MLOverlayTrainer()
    trainer.train(limit=5000)