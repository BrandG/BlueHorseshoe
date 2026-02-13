"""
Verification script for profit target ML model implementation.

This script verifies:
1. Grading engine returns mfe_atr for recent trades
2. Training pipeline works with sample data
3. Model can be trained without errors
"""
import logging
import sys
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.analysis.grading_engine import GradingEngine
from bluehorseshoe.analysis.ml_profit_target import ProfitTargetTrainer

def verify_grading_mfe(database):
    """Verify that grading engine calculates mfe_atr."""
    print("\n" + "="*80)
    print("STEP 1: Verifying grading engine returns mfe_atr")
    print("="*80)

    engine = GradingEngine(hold_days=10, database=database)

    # Get a few recent scores to grade
    query = {"metadata.entry_price": {"$exists": True}}
    results = engine.run_grading(query=query, limit=50, database=database)

    if not results:
        print("❌ No graded trades found")
        return False

    # Filter for successful grades (not errors)
    valid_results = [r for r in results if r.get('status') in ['success', 'failure']]
    print(f"Found {len(results)} total results, {len(valid_results)} valid trades")

    if not valid_results:
        print("❌ No valid graded trades found")
        statuses = {}
        for r in results:
            status = r.get('status', 'unknown')
            statuses[status] = statuses.get(status, 0) + 1
        print(f"   Status breakdown: {statuses}")
        print("\n   This is expected if:")
        print("   - Recent predictions don't have future data yet")
        print("   - Historical price data is missing")
        print("\n   To fix: Run older predictions or wait for future data")
        print("   Suggestion: Try training on older scores with --before-date parameter")
        return False

    # Check if mfe_atr is present
    mfe_found = False
    for result in valid_results:
        if 'mfe_atr' in result:
            mfe_found = True
            print(f"✅ Found mfe_atr in trade: {result['symbol']} on {result['date']}")
            print(f"   Status: {result['status']}, PnL: {result.get('pnl', 0):.2f}%")
            print(f"   MFE: {result['mfe_atr']:.2f} ATR, MAE: {result.get('mae_atr', 0):.2f} ATR")
            break

    if not mfe_found:
        print("❌ mfe_atr not found in graded trades")
        print(f"   Sample result keys: {list(valid_results[0].keys())}")
        return False

    print(f"✅ Grading engine correctly returns mfe_atr ({len(valid_results)} valid trades graded)")
    return True

def verify_training_pipeline(database):
    """Verify that training pipeline works with sample data."""
    print("\n" + "="*80)
    print("STEP 2: Verifying training pipeline with sample data")
    print("="*80)

    trainer = ProfitTargetTrainer(
        model_path="src/models/ml_profit_target_test.joblib",
        database=database
    )

    # Try to prepare training data
    print("Fetching sample training data (limit=500)...")
    try:
        df = trainer.prepare_training_data(limit=500)
    except Exception as e:
        print(f"❌ Error preparing training data: {e}")
        import traceback
        traceback.print_exc()
        return False

    if df.empty:
        print("❌ No training data prepared")
        print("   This might be because:")
        print("   - No scored trades exist in the database")
        print("   - Historical price data is missing")
        print("   - No trades had positive MFE (mfe_atr > 0)")
        return False

    print(f"✅ Prepared {len(df)} training samples")
    print(f"   Columns: {list(df.columns)[:10]}...")
    print(f"   TARGET (mfe_atr) range: {df['TARGET'].min():.2f} - {df['TARGET'].max():.2f}")

    # Check for required columns
    required_cols = ['TARGET', 'symbol', 'date', 'strategy']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        print(f"❌ Missing required columns: {missing}")
        return False

    print("✅ Training data preparation successful")
    return True

def verify_model_training(database):
    """Verify that model can be trained without errors."""
    print("\n" + "="*80)
    print("STEP 3: Training test model")
    print("="*80)

    trainer = ProfitTargetTrainer(
        model_path="src/models/ml_profit_target_test.joblib",
        database=database
    )

    try:
        print("Training test model with 500 samples...")
        trainer.train(limit=500, output_path="src/models/ml_profit_target_test.joblib")
        print("✅ Model training completed successfully")
        return True
    except Exception as e:
        print(f"❌ Model training failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all verification steps."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    print("\n" + "="*80)
    print("ML PROFIT TARGET MODEL VERIFICATION")
    print("="*80)

    container = create_app_container()
    try:
        database = container.get_database()

        # Run verification steps
        step1 = verify_grading_mfe(database)
        step2 = verify_training_pipeline(database)
        step3 = verify_model_training(database)

        # Summary
        print("\n" + "="*80)
        print("VERIFICATION SUMMARY")
        print("="*80)
        print(f"Step 1 - Grading MFE:        {'✅ PASSED' if step1 else '❌ FAILED'}")
        print(f"Step 2 - Training Pipeline:  {'✅ PASSED' if step2 else '❌ FAILED'}")
        print(f"Step 3 - Model Training:     {'✅ PASSED' if step3 else '❌ FAILED'}")
        print("="*80)

        if all([step1, step2, step3]):
            print("✅ All verification steps passed!")
            print("\nNext steps:")
            print("1. Train production models: docker exec bluehorseshoe python src/train_profit_target.py 10000")
            print("2. Test integration: docker exec bluehorseshoe python src/main.py -p --limit 10")
            print("3. Backtest validation: docker exec bluehorseshoe python src/main.py -t 2026-01-15 --end 2026-02-01")
            return 0
        else:
            print("❌ Some verification steps failed. Please review the errors above.")
            return 1

    except Exception as e:
        print(f"\n❌ Fatal error during verification: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        container.close()

if __name__ == "__main__":
    sys.exit(main())
