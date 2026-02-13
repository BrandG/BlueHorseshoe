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
    Trains a regression model to predict the optimal ATR-based profit target distance.
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

        Args:
            limit: Maximum number of trades to process
            before_date: Only include trades before this date
            strategy: Filter by strategy ('baseline', 'mean_reversion', or None for all)
        """
        logging.info("Gathering graded trades for Profit Target training, before=%s, strategy=%s...", before_date, strategy)
        query = {"metadata.entry_price": {"$exists": True}}
        if before_date:
            query["date"] = {"$lt": before_date}
        if strategy:
            query["strategy"] = strategy

        results = self.grading_engine.run_grading(query=query, limit=limit, database=self.database)
        df_graded = pd.DataFrame(results)

        if df_graded.empty:
            logging.error("No graded trades found to train on.")
            return pd.DataFrame()

        # Train on both successes and failures that had SOME upward movement
        df_graded = df_graded[df_graded['status'].isin(['success', 'failure'])]

        # Check if mfe_atr column exists
        if 'mfe_atr' not in df_graded.columns:
            logging.error("Column 'mfe_atr' not found in graded results. Available columns: %s", list(df_graded.columns))
            logging.error("This may indicate that no trades could be graded (no future data available).")
            return pd.DataFrame()

        # Filter: Only trades with mfe_atr > 0 (must have reached some gain)
        df_graded = df_graded[df_graded['mfe_atr'] > 0]

        logging.info("Found %d trades with positive MFE for training.", len(df_graded))

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
        logging.info("Regression Performance - MSE: %.4f, MAE: %.4f, R2: %.4f", mse, mae, r2)

        # Feature Importance
        importances = pd.DataFrame({
            'feature': X_test.columns,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)
        logging.info("Top Features for Profit Target:\n" + importances.head(10).to_string())

    def train(self, limit: int = 10000, output_path: str = None, before_date: str = None, strategy: str = None):
        """
        Trains the Random Forest Regressor for profit target prediction.

        Args:
            limit: Maximum number of trades to train on
            output_path: Path to save the model (defaults to self.model_path)
            before_date: Only include trades before this date
            strategy: Filter by strategy ('baseline', 'mean_reversion', or None for all)
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
        logging.info("Training Regressor on %d samples, testing on %d samples...", len(X_train), len(X_test))

        # Train Model - More estimators and depth than stop-loss due to higher variance
        model = RandomForestRegressor(
            n_estimators=150,
            max_depth=12,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42
        )
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
        Trains all three profit target models (v1, baseline, mean_reversion).

        Args:
            limit: Maximum number of trades to train on
            before_date: Only include trades before this date
        """
        # Train general model
        logging.info("Training general profit target model...")
        self.train(limit=limit, output_path="src/models/ml_profit_target_v1.joblib", before_date=before_date)

        # Train baseline-specific model
        logging.info("Training baseline profit target model...")
        self.train(
            limit=limit,
            output_path="src/models/ml_profit_target_baseline.joblib",
            before_date=before_date,
            strategy="baseline"
        )

        # Train mean reversion-specific model
        logging.info("Training mean reversion profit target model...")
        self.train(
            limit=limit,
            output_path="src/models/ml_profit_target_mean_reversion.joblib",
            before_date=before_date,
            strategy="mean_reversion"
        )

        logging.info("All profit target models trained successfully!")

class ProfitTargetInference:
    """
    Predicts optimal ATR multiplier for a profit target.
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
        """Load all three profit target models."""
        model_paths = {
            'v1': 'src/models/ml_profit_target_v1.joblib',
            'baseline': 'src/models/ml_profit_target_baseline.joblib',
            'mean_reversion': 'src/models/ml_profit_target_mean_reversion.joblib'
        }

        for key, path in model_paths.items():
            if os.path.exists(path):
                data = joblib.load(path)
                self.models[key] = data['model']
                self.encoders[key] = data['encoders']
                self.features[key] = data['features']
                logging.info("Profit Target Model '%s' loaded from %s", key, path)
            else:
                logging.warning("Profit Target Model '%s' not found at %s", key, path)

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

    def predict_profit_target_multiplier(
        self,
        symbol: str,
        components: Dict[str, float],
        target_date: str = None,
        strategy: str = "baseline"
    ) -> float:
        """
        Predicts the recommended ATR multiplier for the profit target.

        Args:
            symbol: Stock symbol.
            components: Technical indicator scores.
            target_date: Target date for prediction.
            strategy: Trading strategy ('baseline' or 'mean_reversion')

        Returns:
            Recommended ATR multiplier for profit target.
        """
        if self.database is None:
            raise ValueError("database parameter is required for predict_profit_target_multiplier")

        # Determine which model to use
        model_key = strategy if strategy in self.models else 'v1'

        if model_key not in self.models:
            # Default fallback
            return 3.0 if strategy == "baseline" else 2.0

        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")

        feat = extract_features(symbol, components, target_date, database=self.database)
        feat = self._encode_features(feat, self.encoders[model_key])
        df_inf = self._prepare_inference_df(feat, self.features[model_key])

        predicted_mfe = float(self.models[model_key].predict(df_inf)[0])

        # Safety factor: Use 75% of predicted peak to exit before reversal
        # This helps lock in gains before potential reversal
        recommended_multiplier = predicted_mfe * 0.75

        # Floor values to ensure minimum reasonable targets
        if strategy == "baseline":
            recommended_multiplier = max(2.5, recommended_multiplier)
        else:  # mean_reversion
            recommended_multiplier = max(1.5, recommended_multiplier)

        return recommended_multiplier
