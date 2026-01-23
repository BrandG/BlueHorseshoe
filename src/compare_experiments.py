#!/usr/bin/env python3
"""
Compare results from indicator experiments.

Performs statistical testing to determine if differences are significant.

Usage:
    # Compare two experiments
    python src/compare_experiments.py exp1_name exp2_name

    # Compare multiple experiments
    python src/compare_experiments.py exp1 exp2 exp3

    # List available experiments
    python src/compare_experiments.py --list
"""

import sys
import json
from pathlib import Path
import numpy as np
from scipy import stats
from typing import List, Dict

EXPERIMENTS_DIR = Path("/workspaces/BlueHorseshoe/src/experiments/results")


def load_experiment(name: str) -> Dict:
    """Load experiment results from JSON file."""
    # Try exact match first
    exp_path = EXPERIMENTS_DIR / f"{name}.json"
    if not exp_path.exists():
        # Try finding partial match
        matches = list(EXPERIMENTS_DIR.glob(f"{name}*.json"))
        if not matches:
            raise FileNotFoundError(f"Experiment '{name}' not found in {EXPERIMENTS_DIR}")
        if len(matches) > 1:
            print(f"Multiple matches for '{name}':")
            for m in matches:
                print(f"  - {m.stem}")
            raise ValueError(f"Ambiguous experiment name. Please be more specific.")
        exp_path = matches[0]

    with open(exp_path, 'r') as f:
        return json.load(f)


def list_experiments():
    """List all available experiments."""
    if not EXPERIMENTS_DIR.exists():
        print("No experiments directory found")
        return

    json_files = list(EXPERIMENTS_DIR.glob("*.json"))
    config_files = [f for f in json_files if f.stem.endswith('_config')]
    result_files = [f for f in json_files if not f.stem.endswith('_config')]

    if not result_files:
        print("No experiment results found")
        return

    print("Available Experiments:")
    print("=" * 80)
    for f in sorted(result_files):
        try:
            exp = load_experiment(f.stem)
            metrics = exp['metrics']
            print(f"\n{f.stem}")
            print(f"  Indicator: {exp['indicator']}")
            print(f"  Multiplier: {exp['multiplier']}")
            print(f"  Trades: {metrics['total_trades']}")
            print(f"  Win Rate: {metrics['win_rate']:.2f}%")
            print(f"  Avg PnL: {metrics['avg_pnl']:.2f}%")
            print(f"  Sharpe: {metrics['sharpe_ratio']:.3f}")
        except Exception as e:
            print(f"\n{f.stem} - Error loading: {e}")


def calculate_pnl_array(experiment: Dict) -> np.ndarray:
    """Extract PnL values from experiment trades."""
    trades = experiment.get('trades', [])
    return np.array([t['pnl_pct'] for t in trades if 'pnl_pct' in t])


def compare_two_experiments(exp1: Dict, exp2: Dict) -> Dict:
    """
    Statistically compare two experiments.

    Returns dict with comparison metrics and significance tests.
    """
    # Extract PnL arrays
    pnl1 = calculate_pnl_array(exp1)
    pnl2 = calculate_pnl_array(exp2)

    if len(pnl1) == 0 or len(pnl2) == 0:
        return {'error': 'One or both experiments have no trades'}

    # T-test for mean PnL difference
    t_stat, t_pvalue = stats.ttest_ind(pnl1, pnl2)

    # Mann-Whitney U test (non-parametric alternative)
    u_stat, u_pvalue = stats.mannwhitneyu(pnl1, pnl2, alternative='two-sided')

    # Chi-square test for win rate
    wins1 = exp1['metrics']['winning_trades']
    total1 = exp1['metrics']['total_trades']
    wins2 = exp2['metrics']['winning_trades']
    total2 = exp2['metrics']['total_trades']

    # Contingency table: [wins, losses] for each experiment
    contingency = np.array([
        [wins1, total1 - wins1],
        [wins2, total2 - wins2]
    ])

    chi2_stat, chi2_pvalue = stats.chi2_contingency(contingency)[:2]

    # Effect sizes
    mean1 = exp1['metrics']['avg_pnl']
    mean2 = exp2['metrics']['avg_pnl']
    std1 = exp1['metrics']['pnl_std']
    std2 = exp2['metrics']['pnl_std']

    # Cohen's d (effect size)
    pooled_std = np.sqrt((std1**2 + std2**2) / 2)
    cohens_d = (mean1 - mean2) / pooled_std if pooled_std > 0 else 0

    return {
        'pnl_difference': mean1 - mean2,
        'pnl_difference_pct': ((mean1 - mean2) / abs(mean2) * 100) if mean2 != 0 else 0,
        'win_rate_difference': exp1['metrics']['win_rate'] - exp2['metrics']['win_rate'],
        'sharpe_difference': exp1['metrics']['sharpe_ratio'] - exp2['metrics']['sharpe_ratio'],
        'tests': {
            't_test': {
                'statistic': t_stat,
                'p_value': t_pvalue,
                'significant': t_pvalue < 0.05
            },
            'mann_whitney': {
                'statistic': u_stat,
                'p_value': u_pvalue,
                'significant': u_pvalue < 0.05
            },
            'chi_square_winrate': {
                'statistic': chi2_stat,
                'p_value': chi2_pvalue,
                'significant': chi2_pvalue < 0.05
            }
        },
        'effect_size': {
            'cohens_d': cohens_d,
            'interpretation': interpret_cohens_d(cohens_d)
        }
    }


def interpret_cohens_d(d: float) -> str:
    """Interpret Cohen's d effect size."""
    abs_d = abs(d)
    if abs_d < 0.2:
        return "negligible"
    elif abs_d < 0.5:
        return "small"
    elif abs_d < 0.8:
        return "medium"
    else:
        return "large"


def print_comparison(exp1: Dict, exp2: Dict, comparison: Dict):
    """Pretty print comparison results."""
    print("\n" + "=" * 80)
    print("EXPERIMENT COMPARISON")
    print("=" * 80)

    print(f"\nExperiment A: {exp1['experiment_name']}")
    print(f"  Indicator: {exp1['indicator']} (multiplier: {exp1['multiplier']})")
    print(f"  Trades: {exp1['metrics']['total_trades']}")
    print(f"  Win Rate: {exp1['metrics']['win_rate']:.2f}%")
    print(f"  Avg PnL: {exp1['metrics']['avg_pnl']:.2f}%")
    print(f"  Sharpe Ratio: {exp1['metrics']['sharpe_ratio']:.3f}")
    print(f"  Max Drawdown: {exp1['metrics']['max_drawdown']:.2f}%")

    print(f"\nExperiment B: {exp2['experiment_name']}")
    print(f"  Indicator: {exp2['indicator']} (multiplier: {exp2['multiplier']})")
    print(f"  Trades: {exp2['metrics']['total_trades']}")
    print(f"  Win Rate: {exp2['metrics']['win_rate']:.2f}%")
    print(f"  Avg PnL: {exp2['metrics']['avg_pnl']:.2f}%")
    print(f"  Sharpe Ratio: {exp2['metrics']['sharpe_ratio']:.3f}")
    print(f"  Max Drawdown: {exp2['metrics']['max_drawdown']:.2f}%")

    if 'error' in comparison:
        print(f"\nError: {comparison['error']}")
        return

    print("\n" + "-" * 80)
    print("DIFFERENCES (A - B)")
    print("-" * 80)
    print(f"PnL Difference: {comparison['pnl_difference']:+.2f}% ({comparison['pnl_difference_pct']:+.1f}%)")
    print(f"Win Rate Difference: {comparison['win_rate_difference']:+.2f}%")
    print(f"Sharpe Ratio Difference: {comparison['sharpe_difference']:+.3f}")

    print("\n" + "-" * 80)
    print("STATISTICAL SIGNIFICANCE TESTS")
    print("-" * 80)

    t_test = comparison['tests']['t_test']
    print(f"\nT-Test (Mean PnL):")
    print(f"  Statistic: {t_test['statistic']:.4f}")
    print(f"  P-value: {t_test['p_value']:.4f}")
    print(f"  Result: {'SIGNIFICANT' if t_test['significant'] else 'Not significant'} (α=0.05)")

    mw_test = comparison['tests']['mann_whitney']
    print(f"\nMann-Whitney U Test (PnL Distribution):")
    print(f"  Statistic: {mw_test['statistic']:.0f}")
    print(f"  P-value: {mw_test['p_value']:.4f}")
    print(f"  Result: {'SIGNIFICANT' if mw_test['significant'] else 'Not significant'} (α=0.05)")

    chi_test = comparison['tests']['chi_square_winrate']
    print(f"\nChi-Square Test (Win Rate):")
    print(f"  Statistic: {chi_test['statistic']:.4f}")
    print(f"  P-value: {chi_test['p_value']:.4f}")
    print(f"  Result: {'SIGNIFICANT' if chi_test['significant'] else 'Not significant'} (α=0.05)")

    print("\n" + "-" * 80)
    print("EFFECT SIZE")
    print("-" * 80)
    effect = comparison['effect_size']
    print(f"Cohen's d: {effect['cohens_d']:.3f} ({effect['interpretation']})")

    print("\n" + "-" * 80)
    print("RECOMMENDATION")
    print("-" * 80)

    # Determine winner
    if comparison['pnl_difference'] > 0:
        better_exp = "Experiment A"
        worse_exp = "Experiment B"
    else:
        better_exp = "Experiment B"
        worse_exp = "Experiment A"

    is_significant = t_test['significant'] or mw_test['significant']
    effect_size = abs(effect['cohens_d'])

    if is_significant and effect_size >= 0.5:
        print(f"✓ {better_exp} shows STRONG evidence of better performance")
        print(f"  Recommendation: Use {better_exp} configuration")
    elif is_significant and effect_size >= 0.2:
        print(f"⚠ {better_exp} shows MODERATE evidence of better performance")
        print(f"  Recommendation: Consider using {better_exp}, but run more tests")
    elif effect_size >= 0.5:
        print(f"⚠ {better_exp} shows large effect but NOT statistically significant")
        print(f"  Recommendation: Run more tests to increase confidence")
    else:
        print(f"○ No meaningful difference detected")
        print(f"  Recommendation: Keep current configuration or test other variations")

    print("=" * 80)


def compare_multiple_experiments(experiments: List[Dict]):
    """Compare multiple experiments and rank them."""
    print("\n" + "=" * 80)
    print(f"MULTI-EXPERIMENT COMPARISON ({len(experiments)} experiments)")
    print("=" * 80)

    # Create ranking table
    rankings = []
    for exp in experiments:
        rankings.append({
            'name': exp['experiment_name'],
            'indicator': exp['indicator'],
            'multiplier': exp['multiplier'],
            'trades': exp['metrics']['total_trades'],
            'win_rate': exp['metrics']['win_rate'],
            'avg_pnl': exp['metrics']['avg_pnl'],
            'total_pnl': exp['metrics']['total_pnl'],
            'sharpe': exp['metrics']['sharpe_ratio'],
            'max_dd': exp['metrics']['max_drawdown']
        })

    # Sort by Sharpe ratio (best risk-adjusted returns)
    rankings.sort(key=lambda x: x['sharpe'], reverse=True)

    print("\nRanked by Sharpe Ratio (Risk-Adjusted Returns):")
    print("-" * 80)
    print(f"{'Rank':<5} {'Name':<25} {'Mult':<6} {'Win%':<7} {'AvgPnL':<9} {'Sharpe':<8} {'MaxDD':<8}")
    print("-" * 80)

    for i, r in enumerate(rankings, 1):
        print(f"{i:<5} {r['name'][:24]:<25} {r['multiplier']:<6.1f} "
              f"{r['win_rate']:<7.2f} {r['avg_pnl']:<9.2f} "
              f"{r['sharpe']:<8.3f} {r['max_dd']:<8.2f}")

    print("\n" + "-" * 80)
    print("BEST PERFORMER")
    print("-" * 80)
    best = rankings[0]
    print(f"Experiment: {best['name']}")
    print(f"Indicator: {best['indicator']} (multiplier: {best['multiplier']})")
    print(f"Win Rate: {best['win_rate']:.2f}%")
    print(f"Avg PnL: {best['avg_pnl']:.2f}%")
    print(f"Sharpe Ratio: {best['sharpe']:.3f}")
    print(f"Max Drawdown: {best['max_dd']:.2f}%")
    print("=" * 80)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare indicator experiment results"
    )
    parser.add_argument(
        'experiments',
        nargs='*',
        help='Experiment names to compare (2 or more)'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all available experiments'
    )

    args = parser.parse_args()

    if args.list:
        list_experiments()
        return

    if len(args.experiments) < 2:
        print("Error: Please provide at least 2 experiment names to compare")
        print("\nUse --list to see available experiments")
        sys.exit(1)

    # Load experiments
    try:
        loaded_exps = [load_experiment(name) for name in args.experiments]
    except Exception as e:
        print(f"Error loading experiments: {e}")
        sys.exit(1)

    if len(loaded_exps) == 2:
        # Pairwise comparison
        comparison = compare_two_experiments(loaded_exps[0], loaded_exps[1])
        print_comparison(loaded_exps[0], loaded_exps[1], comparison)
    else:
        # Multi-experiment comparison
        compare_multiple_experiments(loaded_exps)


if __name__ == "__main__":
    main()
