#!/usr/bin/env python
"""
Quick integration test to verify dynamic entry implementation.
"""
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.core.scores import ScoreManager


def test_dynamic_entry_metadata():
    """Test that dynamic entry metadata is being saved correctly."""
    container = create_app_container()
    try:
        score_manager = ScoreManager(database=container.get_database())

        # Get the latest scores
        scores = list(container.get_database().scores.find().sort('date', -1).limit(10))

        if not scores:
            print("No scores found in database. Run a prediction first.")
            return False

        print(f"Found {len(scores)} recent scores. Checking metadata...\n")

        success = True
        for score in scores[:5]:  # Check first 5
            symbol = score.get('symbol', 'N/A')
            strategy = score.get('strategy', 'N/A')
            score_value = score.get('score', 0)
            metadata = score.get('metadata', {})

            # Check for new fields
            atr_discount = metadata.get('atr_discount_used')
            signal_strength = metadata.get('signal_strength')

            print(f"Symbol: {symbol}")
            print(f"  Strategy: {strategy}")
            print(f"  Score: {score_value:.2f}")
            print(f"  ATR Discount: {atr_discount}")
            print(f"  Signal Strength: {signal_strength}")

            # Verify fields exist for baseline strategy
            if strategy == 'baseline':
                if atr_discount is None:
                    print(f"  ❌ ERROR: Missing atr_discount_used")
                    success = False
                else:
                    print(f"  ✓ atr_discount_used present: {atr_discount}")

                if signal_strength is None:
                    print(f"  ❌ ERROR: Missing signal_strength")
                    success = False
                else:
                    print(f"  ✓ signal_strength present: {signal_strength}")

                # Verify discount matches signal strength
                expected_discounts = {
                    'EXTREME': 0.05,
                    'HIGH': 0.10,
                    'MEDIUM': 0.20,
                    'LOW': 0.35,
                    'WEAK': 0.50
                }
                expected = expected_discounts.get(signal_strength, 0.20)
                if abs(atr_discount - expected) < 0.001:
                    print(f"  ✓ Discount matches signal strength")
                else:
                    print(f"  ❌ ERROR: Discount {atr_discount} doesn't match expected {expected} for {signal_strength}")
                    success = False

            print()

        return success
    finally:
        container.close()


if __name__ == '__main__':
    if test_dynamic_entry_metadata():
        print("✓ All checks passed!")
        exit(0)
    else:
        print("❌ Some checks failed!")
        exit(1)
