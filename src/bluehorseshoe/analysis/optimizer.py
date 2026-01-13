"""
Module for optimizing trading strategy weights.
"""

import logging
from bluehorseshoe.analysis.grading_engine import GradingEngine
from bluehorseshoe.core.config import weights_config

class WeightOptimizer:
    """
    Analyzes trading performance and optimizes indicator weights.
    """
    # pylint: disable=too-few-public-methods
    def __init__(self, days_lookback: int = 30):
        self.engine = GradingEngine(hold_days=10)
        self.days_lookback = days_lookback

    def run_optimization(self):
        """
        Runs the weight optimization process.
        """
        logging.info("Starting weight optimization based on last %d days...", self.days_lookback)

        # 1. Fetch scores from the last 30 days
        # In a real scenario, we'd filter by date. Here we'll just take the last 5000 scores.
        results = self.engine.run_grading(limit=5000)
        if not results:
            logging.warning("No results to analyze for optimization.")
            return

        # 2. Summarize component performance
        summary = self.engine.summarize_components(results)
        if summary.empty:
            logging.warning("Component summary is empty. Optimization aborted.")
            return

        logging.info("Component Performance:\n%s", summary.to_string())

        # 3. Adjust weights
        # Logic:
        # - If Win Rate > 55%, increase weight by 10%
        # - If Win Rate < 45%, decrease weight by 10%
        # - Min weight 0.1, Max weight 5.0

        categories = {
            'trend': ['trend'],
            'momentum': ['momentum'],
            'volume': ['volume'],
            'candlestick': ['candlestick']
        }

        # We also have safety filters and oversold bonuses which are top-level components
        # We could optimize those too, but they are currently constants.

        for category, component_names in categories.items():
            current_weights = weights_config.get_weights(category)
            new_weights = current_weights.copy()

            # Find the average win rate for this category
            cat_summary = summary[summary['component'].isin(component_names)]
            if cat_summary.empty:
                continue

            avg_win_rate = cat_summary['win_rate'].mean()

            adjustment = 1.0
            if avg_win_rate > 55:
                adjustment = 1.1
                logging.info("Category %s performing well (WR: %.2f%%). Increasing weights.", category, avg_win_rate)
            elif avg_win_rate < 45:
                adjustment = 0.9
                logging.info("Category %s performing poorly (WR: %.2f%%). Decreasing weights.", category, avg_win_rate)
            else:
                logging.info("Category %s performing as expected (WR: %.2f%%). No change.", category, avg_win_rate)
                continue

            for m_name in new_weights:
                # Don't adjust MACD_SIGNAL_MULTIPLIER as it's a sub-multiplier relative to MACD
                if m_name == 'MACD_SIGNAL_MULTIPLIER':
                    continue

                new_val = new_weights[m_name] * adjustment
                new_weights[m_name] = max(0.1, min(5.0, round(new_val, 2)))

            weights_config.update_weights(category, new_weights)

        logging.info("Weight optimization complete.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    optimizer = WeightOptimizer()
    optimizer.run_optimization()
