
"""
Utility functions for ML model management and performance tracking.
"""
from typing import Dict, Any
from bluehorseshoe.core.symbols import get_overview_from_mongo, get_sentiment_score

def safe_float(val: Any) -> float:
    """Safely converts a value to float, handling None and strings."""
    try:
        if val is None or str(val).lower() == 'none':
            return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0

def extract_features(symbol: str, components: Dict[str, float], target_date: str) -> Dict[str, Any]:
    """
    Extracts a consolidated feature dictionary for a given symbol and date.
    Combines technical components, fundamental data, and sentiment scores.
    """
    # 1. Start with Technical Features
    feat = components.copy()

    # 2. Fundamental Features (from overviews)
    overview = get_overview_from_mongo(symbol)

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

    # 3. News Sentiment Feature
    feat['SentimentScore'] = get_sentiment_score(symbol, target_date)

    return feat
