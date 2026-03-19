"""
Curve/Motif indicator.

Scores price series based on historical motif pattern analysis. Extracts
the current price curve's signature and looks up its forward-outcome edge
from the pre-built motif catalog.
"""

from typing import Dict, Optional

from bluehorseshoe.analysis.curves.segmenter import segment_price_series
from bluehorseshoe.analysis.curves.signature import extract_signature
from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore
from bluehorseshoe.core.config import weights_config


class CurveIndicator(Indicator):
    """Indicator based on curve/motif pattern matching."""

    required_cols = ['close', 'high', 'low']

    def __init__(self, data, weight_category: str = None, motif_scores: Optional[Dict[str, float]] = None):
        self.weights = weights_config.get_weights(weight_category or 'curve')
        self.motif_scores = motif_scores or {}
        self._curve_details = {}  # populated by get_score for ML features
        super().__init__(data)

    def calculate_motif_score(self, window_size: int = 40) -> float:
        """
        Calculate motif score for a given window size.

        Returns the catalog composite score for the current shape,
        or 0.0 if no matching motif or catalog is empty.
        """
        if len(self.days) < window_size:
            return 0.0

        try:
            seg = segment_price_series(self.days, window_size=window_size)
            sig = extract_signature(seg)
        except Exception:  # pylint: disable=broad-except
            return 0.0

        key = f"{sig.motif_key}_{window_size}"
        score = self.motif_scores.get(key, 0.0)

        # Store details for ML feature extraction
        self._curve_details[f'curve_motif_score_{window_size}'] = score
        self._curve_details[f'curve_net_direction_{window_size}'] = sig.vector[16] if len(sig.vector) > 16 else 0.0
        self._curve_details[f'curve_total_range_{window_size}'] = sig.vector[15] if len(sig.vector) > 15 else 0.0

        return score

    def get_score(self, enabled_sub_indicators=None, aggregation: str = "sum") -> IndicatorScore:  # pylint: disable=unused-argument
        """Calculate combined curve indicator score across window sizes."""
        if len(self.days) < 20:
            return IndicatorScore(0.0, 0.0)

        buy_score = 0.0
        multiplier = self.weights.get('MOTIF_SCORE_MULTIPLIER', 1.0)
        if multiplier == 0.0:
            # Still compute for ML features even when weight is 0
            for window in (20, 40):
                self.calculate_motif_score(window)
            return IndicatorScore(0.0, 0.0)

        for window in (20, 40):
            score = self.calculate_motif_score(window)
            buy_score += score * multiplier

        return IndicatorScore(buy_score, 0.0)

    def get_curve_details(self) -> Dict[str, float]:
        """Return curve feature details for ML feature building."""
        return self._curve_details.copy()

    def graph(self):
        pass
