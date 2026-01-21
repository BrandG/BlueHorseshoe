"""
Tests for ML overlay prediction logic.
"""
import os
import pytest
from unittest.mock import MagicMock
from bluehorseshoe.analysis.ml_overlay import MLInference

@pytest.fixture
def mock_database():
    """Create a mock database for testing."""
    mock_db = MagicMock()
    # Mock symbol_overviews collection
    mock_overviews_col = MagicMock()
    mock_overviews_col.find_one.return_value = {
        "Sector": "Technology",
        "Industry": "Software",
        "MarketCapitalization": "1000000000",
        "Beta": "1.2",
        "PERatio": "25"
    }
    # Mock symbol_news collection
    mock_news_col = MagicMock()
    mock_news_col.find_one.return_value = {"feed": []}

    mock_db.__getitem__.side_effect = lambda key: {
        "symbol_overviews": mock_overviews_col,
        "symbol_news": mock_news_col
    }.get(key, MagicMock())

    return mock_db

def test_ml_inference_loading(mock_database):
    """Verify that MLInference can load the model or handle missing model."""
    inference = MLInference(model_path="src/models/ml_overlay_v1.joblib", database=mock_database)
    assert "general" in inference.models

def test_predict_probability_fallback(mock_database):
    """Test prediction fallback when no model is present."""
    inference = MLInference(model_path="non_existent.joblib", database=mock_database)
    prob = inference.predict_probability("AAPL", {"trend": 1.0})
    assert prob == 0.0

@pytest.mark.skipif(not os.path.exists("src/models/ml_overlay_v1.joblib"), reason="Model file not found")
def test_predict_probability_real(mock_database):
    """Test prediction with the actual trained model."""
    inference = MLInference(model_path="src/models/ml_overlay_v1.joblib", database=mock_database)
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

def test_predict_probability_with_date(mock_database):
    """Test prediction with a specific date (triggers sentiment lookup)."""
    inference = MLInference(model_path="src/models/ml_overlay_v1.joblib", database=mock_database)
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
