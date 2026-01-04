import pytest
import pandas as pd
import os
import joblib
from bluehorseshoe.analysis.ml_overlay import MLInference

def test_ml_inference_loading():
    """Verify that MLInference can load the model or handle missing model."""
    inference = MLInference(model_path="src/models/ml_overlay_v1.joblib")
    assert "general" in inference.models

def test_predict_probability_fallback():
    """Test prediction fallback when no model is present."""
    inference = MLInference(model_path="non_existent.joblib")
    prob = inference.predict_probability("AAPL", {"trend": 1.0})
    assert prob == 0.0

@pytest.mark.skipif(not os.path.exists("src/models/ml_overlay_v1.joblib"), reason="Model file not found")
def test_predict_probability_real():
    """Test prediction with the actual trained model."""
    inference = MLInference(model_path="src/models/ml_overlay_v1.joblib")
    components = {
        "trend": 1.0,
        "volume": 1.0,
        "limit": 1.0,
        "candlestick": 1.0,
        "moving_average": 1.0,
        "momentum": 1.0
    }
    prob = inference.predict_probability("AAPL", components)
    assert 0.0 <= prob <= 1.0

def test_predict_probability_with_date():
    """Test prediction with a specific date (triggers sentiment lookup)."""
    inference = MLInference(model_path="src/models/ml_overlay_v1.joblib")
    components = {
        "trend": 1.0,
        "volume": 1.0,
        "limit": 1.0,
        "candlestick": 1.0,
        "moving_average": 1.0,
        "momentum": 1.0
    }
    # Using a date from the past to ensure get_sentiment_score is called
    prob = inference.predict_probability("AAPL", components, target_date="2026-01-01")
    assert 0.0 <= prob <= 1.0
