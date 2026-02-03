#!/usr/bin/env python
"""
Validate that dynamic discounts are being applied correctly.

This script generates predictions and verifies that different signal strengths
receive different ATR discounts as expected.
"""
import sys
from collections import defaultdict

from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
from bluehorseshoe.analysis.constants import SIGNAL_STRENGTH_THRESHOLDS, ENTRY_DISCOUNT_BY_SIGNAL
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.core.symbols import get_symbol_name_list


def main():
    """Main validation function."""
    test_date = '2026-01-27'  # Date with good signal distribution
    sample_size = 500

    print("="*70)
    print("DYNAMIC ENTRY DISCOUNT VALIDATION")
    print("="*70)
    print(f"\nTest Date: {test_date}")
    print(f"Sample Size: {sample_size} symbols\n")

    # Show current thresholds
    print("Current Thresholds:")
    for tier, threshold in SIGNAL_STRENGTH_THRESHOLDS.items():
        discount = ENTRY_DISCOUNT_BY_SIGNAL.get(tier, 0.20)
        print(f"  {tier}: Score >= {threshold}, Discount = {discount}")
    print()

    container = create_app_container()
    try:
        trader = SwingTrader(database=container.get_database())
        ctx = StrategyContext(target_date=test_date)

        # Get sample symbols
        all_symbols = get_symbol_name_list(database=container.get_database())
        import random
        random.seed(42)  # Reproducible
        sample_symbols = random.sample(all_symbols, min(sample_size, len(all_symbols)))

        print(f"Processing {len(sample_symbols)} symbols...")
        predictions = []

        for i, symbol in enumerate(sample_symbols):
            try:
                result = trader.process_symbol(symbol, ctx)
                if result:
                    predictions.append(result)
                if (i + 1) % 100 == 0:
                    print(f"  Progress: {i + 1}/{len(sample_symbols)}")
            except Exception:
                continue

        # Filter baseline predictions
        baseline_predictions = [
            p for p in predictions
            if p and p.get('baseline_score', 0) > 0
        ]

        print(f"\nFound {len(baseline_predictions)} baseline candidates\n")

        # Analyze discounts by tier
        by_tier = defaultdict(lambda: {
            'count': 0,
            'scores': [],
            'discounts': [],
            'examples': []
        })

        for pred in baseline_predictions:
            setup = pred.get('baseline_setup', {})
            score = pred.get('baseline_score', 0)
            symbol = pred.get('symbol', 'N/A')

            strength = setup.get('signal_strength', 'UNKNOWN')
            discount = setup.get('atr_discount_used', None)

            if discount is not None:
                by_tier[strength]['count'] += 1
                by_tier[strength]['scores'].append(score)
                by_tier[strength]['discounts'].append(discount)

                if len(by_tier[strength]['examples']) < 3:
                    by_tier[strength]['examples'].append({
                        'symbol': symbol,
                        'score': score,
                        'discount': discount,
                        'entry': setup.get('entry_price', 0)
                    })

        # Print results
        print("="*70)
        print("VALIDATION RESULTS")
        print("="*70)

        tier_order = ['EXTREME', 'HIGH', 'MEDIUM', 'LOW', 'WEAK', 'UNKNOWN']

        validation_passed = True

        for tier in tier_order:
            if tier not in by_tier or by_tier[tier]['count'] == 0:
                continue

            data = by_tier[tier]
            count = data['count']
            avg_score = sum(data['scores']) / len(data['scores'])
            unique_discounts = set(data['discounts'])
            expected_discount = ENTRY_DISCOUNT_BY_SIGNAL.get(tier, 0.20)

            print(f"\n{tier}:")
            print(f"  Count: {count}")
            print(f"  Avg Score: {avg_score:.1f}")
            print(f"  Expected Discount: {expected_discount}")
            print(f"  Actual Discounts: {unique_discounts}")

            # Validate
            if len(unique_discounts) == 1 and expected_discount in unique_discounts:
                print(f"  ✓ Validation PASSED - Discount matches expected value")
            else:
                print(f"  ✗ Validation FAILED - Discount mismatch!")
                validation_passed = False

            # Show examples
            if data['examples']:
                print(f"  Examples:")
                for ex in data['examples'][:3]:
                    print(f"    {ex['symbol']}: Score={ex['score']:.1f}, Discount={ex['discount']}, Entry=${ex['entry']:.2f}")

        # Summary
        print(f"\n{'='*70}")
        if validation_passed:
            print("✓ ALL VALIDATIONS PASSED")
            print("Dynamic entry discounts are working correctly!")
        else:
            print("✗ SOME VALIDATIONS FAILED")
            print("Dynamic entry discounts may not be working as expected.")
        print("="*70)

        # Show distribution summary
        total = sum(d['count'] for d in by_tier.values())
        print(f"\nSignal Distribution:")
        for tier in tier_order:
            if tier in by_tier:
                count = by_tier[tier]['count']
                pct = (count / total * 100) if total > 0 else 0
                print(f"  {tier}: {count} ({pct:.1f}%)")

        return 0 if validation_passed else 1

    finally:
        container.close()


if __name__ == '__main__':
    sys.exit(main())
