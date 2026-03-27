"""
Quick V2 vs V3 weight comparison script.
Scores a set of symbols with both weight profiles and compares results.
"""
import sys
import json
import os
from pathlib import Path
sys.path.insert(0, 'src')

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)

import pandas as pd
import numpy as np
from pymongo import MongoClient

# Target date for comparison
TARGET_DATE = "2025-10-01"

# We'll test 100 liquid symbols with known data
TEST_SYMBOLS = [
    'AAPL','MSFT','NVDA','AMD','AMZN','GOOGL','META','TSLA','NFLX','AVGO',
    'ARM','ANET','CRM','ORCL','ADBE','INTC','QCOM','TXN','MU','LRCX',
    'ALLE','AN','AOS','AMT','ADC','AI','AGNC','ABR','AER','COKE',
    'KT','TRNO','DOO','VNO','ROG','BLDR','KLIC','MKC','STAG','PSX',
    'STZ','VLO','LKQ','WPC','PAG','LXP','MTRN','ALV','ACM','APH',
    'JPM','BAC','GS','MS','WFC','C','BLK','SCHW','AXP','USB',
    'UNH','JNJ','PFE','ABBV','MRK','LLY','TMO','ABT','DHR','BMY',
    'XOM','CVX','COP','SLB','EOG','PXD','MPC','OXY','HAL','DVN',
    'HD','LOW','TGT','WMT','COST','NKE','SBUX','MCD','DIS','CMCSA',
    'NEE','DUK','SO','AEP','D','EXC','SRE','WEC','ES','ED',
]


def load_symbol_data(db, symbol, target_date, store=None):
    """Load and prepare data for a symbol up to target date."""
    if store is None:
        return None
    df = store.load_symbol(symbol)
    if df is None or df.empty:
        return None
    df['date'] = pd.to_datetime(df['date'])
    df = df[df['date'] <= target_date]
    if len(df) < 60:
        return None
    df = df[df['date'] <= target_date]

    if len(df) < 60:
        return None

    # Ensure required columns exist
    required = ['open', 'high', 'low', 'close', 'volume']
    for col in required:
        if col not in df.columns:
            return None

    return df


def score_with_weights(df, weights_file=None):
    """Score a symbol's data using TechnicalAnalyzer with specified weights."""
    # Temporarily override weights if needed
    if weights_file:
        os.environ['WEIGHTS_FILE'] = weights_file

    # Must reimport to pick up new weights
    # Instead, we'll directly manipulate the config singleton
    from bluehorseshoe.core.config import weights_config
    if weights_file:
        with open(weights_file) as f:
            new_weights = json.load(f)
        weights_config._weights = new_weights

    from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer

    baseline = TechnicalAnalyzer.calculate_baseline_score(df)
    mr = TechnicalAnalyzer.calculate_mean_reversion_score(df)

    return baseline.get('total', 0.0), mr.get('total', 0.0)


def main():
    client = MongoClient('mongodb://mongo:27017')
    db = client['bluehorseshoe']

    from bluehorseshoe.core.config import weights_config

    # Load V3 weights (current default)
    v3_path = f'{_REPO_ROOT}/src/weights.json'
    v2_path = f'{_REPO_ROOT}/src/weights_v2.json'

    results = []

    for symbol in TEST_SYMBOLS:
        df = load_symbol_data(db, symbol, TARGET_DATE)
        if df is None:
            continue

        # Score with V3 weights
        with open(v3_path) as f:
            weights_config._weights = json.load(f)
        from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
        v3_baseline = TechnicalAnalyzer.calculate_baseline_score(df)
        v3_mr = TechnicalAnalyzer.calculate_mean_reversion_score(df)

        # Score with V2 weights
        with open(v2_path) as f:
            weights_config._weights = json.load(f)
        v2_baseline = TechnicalAnalyzer.calculate_baseline_score(df)
        v2_mr = TechnicalAnalyzer.calculate_mean_reversion_score(df)

        results.append({
            'symbol': symbol,
            'v3_baseline': v3_baseline.get('total', 0.0),
            'v2_baseline': v2_baseline.get('total', 0.0),
            'v3_mr': v3_mr.get('total', 0.0),
            'v2_mr': v2_mr.get('total', 0.0),
        })

    # Restore V3 weights
    with open(v3_path) as f:
        weights_config._weights = json.load(f)

    # Analysis
    df_results = pd.DataFrame(results)
    print(f"\n{'='*80}")
    print(f"V2 vs V3 Weight Comparison — {TARGET_DATE}")
    print(f"{'='*80}")
    print(f"Symbols scored: {len(df_results)}")

    # Baseline comparison
    print(f"\n--- BASELINE STRATEGY ---")
    print(f"{'Metric':<30} {'V2':>10} {'V3':>10} {'Delta':>10}")
    print(f"{'-'*60}")

    v2_bl_mean = df_results['v2_baseline'].mean()
    v3_bl_mean = df_results['v3_baseline'].mean()
    print(f"{'Mean score':<30} {v2_bl_mean:>10.2f} {v3_bl_mean:>10.2f} {v3_bl_mean - v2_bl_mean:>+10.2f}")

    v2_bl_pos = (df_results['v2_baseline'] > 0).sum()
    v3_bl_pos = (df_results['v3_baseline'] > 0).sum()
    print(f"{'Positive scores':<30} {v2_bl_pos:>10d} {v3_bl_pos:>10d} {v3_bl_pos - v2_bl_pos:>+10d}")

    # Top 10 comparison
    print(f"\nTop 10 — V3 Baseline:")
    top_v3 = df_results.nlargest(10, 'v3_baseline')
    for _, row in top_v3.iterrows():
        print(f"  {row['symbol']:8s}  V3={row['v3_baseline']:>7.1f}  V2={row['v2_baseline']:>7.1f}  delta={row['v3_baseline']-row['v2_baseline']:>+7.1f}")

    print(f"\nTop 10 — V2 Baseline:")
    top_v2 = df_results.nlargest(10, 'v2_baseline')
    for _, row in top_v2.iterrows():
        print(f"  {row['symbol']:8s}  V2={row['v2_baseline']:>7.1f}  V3={row['v3_baseline']:>7.1f}  delta={row['v3_baseline']-row['v2_baseline']:>+7.1f}")

    # Rank correlation
    from scipy import stats
    corr, pval = stats.spearmanr(df_results['v2_baseline'], df_results['v3_baseline'])
    print(f"\nBaseline rank correlation (Spearman): r={corr:.3f}, p={pval:.4f}")

    # Mean Reversion comparison
    print(f"\n--- MEAN REVERSION STRATEGY ---")
    print(f"{'Metric':<30} {'V2':>10} {'V3':>10} {'Delta':>10}")
    print(f"{'-'*60}")

    v2_mr_mean = df_results['v2_mr'].mean()
    v3_mr_mean = df_results['v3_mr'].mean()
    print(f"{'Mean score':<30} {v2_mr_mean:>10.2f} {v3_mr_mean:>10.2f} {v3_mr_mean - v2_mr_mean:>+10.2f}")

    v2_mr_pos = (df_results['v2_mr'] > 0).sum()
    v3_mr_pos = (df_results['v3_mr'] > 0).sum()
    print(f"{'Positive scores':<30} {v2_mr_pos:>10d} {v3_mr_pos:>10d} {v3_mr_pos - v2_mr_pos:>+10d}")

    print(f"\nTop 10 — V3 Mean Reversion:")
    top_v3_mr = df_results.nlargest(10, 'v3_mr')
    for _, row in top_v3_mr.iterrows():
        print(f"  {row['symbol']:8s}  V3={row['v3_mr']:>7.1f}  V2={row['v2_mr']:>7.1f}  delta={row['v3_mr']-row['v2_mr']:>+7.1f}")

    print(f"\nTop 10 — V2 Mean Reversion:")
    top_v2_mr = df_results.nlargest(10, 'v2_mr')
    for _, row in top_v2_mr.iterrows():
        print(f"  {row['symbol']:8s}  V2={row['v2_mr']:>7.1f}  V3={row['v3_mr']:>7.1f}  delta={row['v3_mr']-row['v2_mr']:>+7.1f}")

    corr_mr, pval_mr = stats.spearmanr(df_results['v2_mr'], df_results['v3_mr'])
    print(f"\nMR rank correlation (Spearman): r={corr_mr:.3f}, p={pval_mr:.4f}")

    # Overlap analysis
    print(f"\n--- OVERLAP ANALYSIS ---")
    v3_top20_bl = set(df_results.nlargest(20, 'v3_baseline')['symbol'])
    v2_top20_bl = set(df_results.nlargest(20, 'v2_baseline')['symbol'])
    overlap_bl = v3_top20_bl & v2_top20_bl
    print(f"Baseline Top-20 overlap: {len(overlap_bl)}/20 ({len(overlap_bl)/20*100:.0f}%)")
    print(f"  V3 only: {sorted(v3_top20_bl - v2_top20_bl)}")
    print(f"  V2 only: {sorted(v2_top20_bl - v3_top20_bl)}")

    v3_top20_mr = set(df_results.nlargest(20, 'v3_mr')['symbol'])
    v2_top20_mr = set(df_results.nlargest(20, 'v2_mr')['symbol'])
    overlap_mr = v3_top20_mr & v2_top20_mr
    print(f"MR Top-20 overlap: {len(overlap_mr)}/20 ({len(overlap_mr)/20*100:.0f}%)")
    print(f"  V3 only: {sorted(v3_top20_mr - v2_top20_mr)}")
    print(f"  V2 only: {sorted(v2_top20_mr - v3_top20_mr)}")

    # Component breakdown for a sample symbol
    print(f"\n--- COMPONENT BREAKDOWN (AAPL) ---")
    aapl_data = load_symbol_data(db, 'AAPL', TARGET_DATE)
    if aapl_data is not None:
        with open(v3_path) as f:
            weights_config._weights = json.load(f)
        v3_comp = TechnicalAnalyzer.calculate_baseline_score(aapl_data)
        v3_mr_comp = TechnicalAnalyzer.calculate_mean_reversion_score(aapl_data)

        with open(v2_path) as f:
            weights_config._weights = json.load(f)
        v2_comp = TechnicalAnalyzer.calculate_baseline_score(aapl_data)
        v2_mr_comp = TechnicalAnalyzer.calculate_mean_reversion_score(aapl_data)

        print(f"\n  Baseline components:")
        all_keys = sorted(set(list(v2_comp.keys()) + list(v3_comp.keys())))
        for k in all_keys:
            v2v = v2_comp.get(k, 0.0)
            v3v = v3_comp.get(k, 0.0)
            if v2v != 0 or v3v != 0:
                print(f"    {k:<30} V2={v2v:>7.2f}  V3={v3v:>7.2f}")

        print(f"\n  MR components:")
        all_keys_mr = sorted(set(list(v2_mr_comp.keys()) + list(v3_mr_comp.keys())))
        for k in all_keys_mr:
            v2v = v2_mr_comp.get(k, 0.0)
            v3v = v3_mr_comp.get(k, 0.0)
            if v2v != 0 or v3v != 0:
                print(f"    {k:<30} V2={v2v:>7.2f}  V3={v3v:>7.2f}")

    # Restore V3 weights
    with open(v3_path) as f:
        weights_config._weights = json.load(f)

    print(f"\n{'='*80}")
    print("Done.")


if __name__ == '__main__':
    main()
