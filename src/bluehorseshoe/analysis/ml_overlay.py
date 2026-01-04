import logging
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import os
from typing import List, Dict, Any

from bluehorseshoe.analysis.grading_engine import GradingEngine
from bluehorseshoe.core.database import db
from bluehorseshoe.core.symbols import get_overview_from_mongo

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

    def prepare_training_data(self, limit: int = 10000) -> pd.DataFrame:
        """
        Extracts features and labels from graded trades and fundamental data.
        """
        logging.info("Gathering graded trades...")
        # Get graded results (Success/Failure)
        results = self.grading_engine.run_grading(limit=limit)
        df_graded = pd.DataFrame(results)
        
        if df_graded.empty:
            logging.error("No graded trades found to train on.")
            return pd.DataFrame()

        # Filter for successful/failed trades only
        df_graded = df_graded[df_graded['status'].isin(['success', 'failure'])]
        
        features = []
        for _, row in df_graded.iterrows():
            symbol = row['symbol']
            
            # 1. Technical Features (from components)
            feat = row.get('components', {}).copy()
            if not feat:
                continue
                
            # 2. Fundamental Features (from overviews)
            overview = get_overview_from_mongo(symbol)
            
            def safe_float(val):
                try:
                    if val is None or str(val).lower() == 'none':
                        return 0.0
                    return float(val)
                except (ValueError, TypeError):
                    return 0.0

            if overview:
                feat['Sector'] = overview.get('Sector', 'Unknown')
                feat['Industry'] = overview.get('Industry', 'Unknown')
                feat['MarketCap'] = safe_float(overview.get('MarketCapitalization'))
                feat['Beta'] = safe_float(overview.get('Beta'))
                feat['PERatio'] = safe_float(overview.get('PERatio'))
            else:
                feat['Sector'] = 'Unknown'
                feat['Industry'] = 'Unknown'
                feat['MarketCap'] = 0.0
                feat['Beta'] = 0.0
                feat['PERatio'] = 0.0
                
            # 3. Label (Target)
            feat['TARGET'] = 1 if row['status'] == 'success' else 0
            feat['symbol'] = symbol
            feat['date'] = row['date']
            
            features.append(feat)
            
        return pd.DataFrame(features)

    def train(self, limit: int = 10000):
        """
        Trains the Random Forest model.
        """
        df = self.prepare_training_data(limit=limit)
        if df.empty:
            return

        # Handle Categorical Data
        categorical_cols = ['Sector', 'Industry']
        for col in categorical_cols:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))
            self.label_encoders[col] = le

        # Drop non-feature columns
        X = df.drop(columns=['TARGET', 'symbol', 'date'])
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
        joblib.dump(output, self.model_path)
        logging.info(f"Model saved to {self.model_path}")

class MLInference:
    """
    Handles loading the trained ML model and performing predictions.
    """
    def __init__(self, model_path: str = "src/models/ml_overlay_v1.joblib"):
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
            logging.info(f"ML Overlay model loaded from {self.model_path}")
        else:
            logging.warning(f"ML Overlay model not found at {self.model_path}")

    def predict_probability(self, symbol: str, components: Dict[str, float]) -> float:
        """
        Predicts the win probability for a given symbol and technical components.
        """
        if self.model is None:
            return 0.0

        # Build feature vector
        feat = components.copy()
        overview = get_overview_from_mongo(symbol)
        
        def safe_float(val):
            try:
                if val is None or str(val).lower() == 'none':
                    return 0.0
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        if overview:
            feat['Sector'] = overview.get('Sector', 'Unknown')
            feat['Industry'] = overview.get('Industry', 'Unknown')
            feat['MarketCap'] = safe_float(overview.get('MarketCapitalization'))
            feat['Beta'] = safe_float(overview.get('Beta'))
            feat['PERatio'] = safe_float(overview.get('PERatio'))
        else:
            feat['Sector'] = 'Unknown'
            feat['Industry'] = 'Unknown'
            feat['MarketCap'] = 0.0
            feat['Beta'] = 0.0
            feat['PERatio'] = 0.0

        # Encode categorical
        for col in ['Sector', 'Industry']:
            le = self.encoders.get(col)
            val = str(feat.get(col, 'Unknown'))
            if le:
                # Handle unseen labels by mapping them to the first label or a default if possible
                try:
                    feat[col] = le.transform([val])[0]
                except ValueError:
                    feat[col] = 0 # Default to first class if unseen
            else:
                feat[col] = 0

        # Create DataFrame aligned with training features
        df = pd.DataFrame([feat])
        
        # Ensure all training features are present, fill missing with 0
        for f in self.features:
            if f not in df.columns:
                df[f] = 0.0
        
        # Reorder columns to match training
        df = df[self.features]
        df = df.fillna(0)

        # Predict probability of class 1 (Success)
        probs = self.model.predict_proba(df)[0]
        return float(probs[1])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    trainer = MLOverlayTrainer()
    trainer.train(limit=5000)
