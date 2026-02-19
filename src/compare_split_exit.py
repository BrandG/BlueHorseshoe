"""
compare_split_exit.py

Comparison script that runs single-exit, Plan A (fixed_pct), and Plan B (atr_tiered)
on the same predictions and prints a side-by-side results table.

Predictions are generated once per date, then evaluated 3 ways — avoiding the cost
of re-running the full prediction pipeline for each exit mode.

Usage:
    docker exec bluehorseshoe python src/compare_split_exit.py 2026-01-15 [options]

Options:
    --end DATE          End date for range comparison
    --interval N        Days between dates (default: 7)
    --hold N            Hold days (default: 10)
    --top N             Top N candidates to evaluate (default: 10)
    --strategy STR      baseline or mean_reversion (default: baseline)
    --t1-pct PCT        Plan A T1 target as decimal (default: 0.02)
    --t1-atr MULT       Plan B T1 ATR multiple (default: 1.0)
    --t2-atr MULT       Plan B T2 ATR multiple (default: 2.0)
    --verbose           Show per-symbol breakdown
"""

import sys
import csv
import copy
import logging
from pathlib import Path
from typing import List, Dict, Optional

import pandas as pd

from bluehorseshoe.cli.context import create_cli_context
from bluehorseshoe.analysis.backtest import (
    Backtester, BacktestConfig, BacktestOptions, SplitExitConfig,
)

logging.basicConfig(level=logging.INFO)

WIN_STATUSES = ['success', 'closed_profit', 'split_full_profit', 'split_partial_profit']
LOSS_STATUSES = ['stopped_out', 'closed_loss']


def parse_args(argv: List[str]):
    """Parse CLI arguments."""
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)

    target_date = argv[1]

    def _get_arg(flag, default=None, cast=None):
        if flag in argv:
            val = argv[argv.index(flag) + 1]
            return cast(val) if cast else val
        return default

    return {
        'target_date': target_date,
        'end_date': _get_arg('--end'),
        'interval': _get_arg('--interval', 7, int),
        'hold_days': _get_arg('--hold', 10, int),
        'top_n': _get_arg('--top', 10, int),
        'strategy': _get_arg('--strategy', 'baseline'),
        't1_pct': _get_arg('--t1-pct', 0.02, float),
        't1_atr': _get_arg('--t1-atr', 1.0, float),
        't2_atr': _get_arg('--t2-atr', 2.0, float),
        'verbose': '--verbose' in argv,
    }


def _pnl_for_result(result: Dict) -> Optional[float]:
    """Extract P&L percentage from a result dict."""
    if result.get('exit_mode') == 'split_exit':
        return result.get('blended_pnl_pct')
    entry = result.get('entry')
    exit_price = result.get('exit_price')
    if entry and exit_price:
        return ((exit_price / entry) - 1) * 100
    return None


def summarize_variant(results: List[Dict]) -> Dict:
    """Summarize a list of backtest results into aggregate stats."""
    valid = [r for r in results if r.get('entry') is not None and r.get('exit_price') is not None]
    trades = len(valid)
    if trades == 0:
        return {
            'trades': 0, 'wins': 0, 'win_rate': 0.0,
            'avg_pnl': 0.0, 'total_pnl': 0.0,
            'stopped': 0, 'time_exit': 0,
        }

    wins = sum(1 for r in valid if r['status'] in WIN_STATUSES)
    pnls = [_pnl_for_result(r) for r in valid]
    pnls = [p for p in pnls if p is not None]
    total_pnl = sum(pnls) if pnls else 0.0
    avg_pnl = total_pnl / len(pnls) if pnls else 0.0
    stopped = sum(1 for r in valid if r['status'] in LOSS_STATUSES)
    time_exit = sum(1 for r in valid if r['status'] == 'time_exit')

    return {
        'trades': trades,
        'wins': wins,
        'win_rate': (wins / trades) * 100 if trades else 0.0,
        'avg_pnl': avg_pnl,
        'total_pnl': total_pnl,
        'stopped': stopped,
        'time_exit': time_exit,
    }


def print_comparison_table(date: str, n_candidates: int,
                           single_summary: Dict, plan_a_summary: Dict, plan_b_summary: Dict,
                           t1_pct: float):
    """Print a side-by-side comparison table for one date."""
    hdr_single = "Single Exit"
    hdr_a = f"Plan A ({t1_pct*100:.0f}%)"
    hdr_b = "Plan B (ATR)"
    col_w = 16

    print(f"\n--- {date} ({n_candidates} candidates) ---")
    print(f"{'':18s}{hdr_single:>{col_w}}{hdr_a:>{col_w}}{hdr_b:>{col_w}}")
    print(f"{'Trades:':18s}{single_summary['trades']:>{col_w}}{plan_a_summary['trades']:>{col_w}}{plan_b_summary['trades']:>{col_w}}")
    print(f"{'Wins:':18s}{single_summary['wins']:>{col_w}}{plan_a_summary['wins']:>{col_w}}{plan_b_summary['wins']:>{col_w}}")

    wr_s = f"{single_summary['win_rate']:.2f}%"
    wr_a = f"{plan_a_summary['win_rate']:.2f}%"
    wr_b = f"{plan_b_summary['win_rate']:.2f}%"
    print(f"{'Win Rate:':18s}{wr_s:>{col_w}}{wr_a:>{col_w}}{wr_b:>{col_w}}")

    ap_s = f"{single_summary['avg_pnl']:.2f}%"
    ap_a = f"{plan_a_summary['avg_pnl']:.2f}%"
    ap_b = f"{plan_b_summary['avg_pnl']:.2f}%"
    print(f"{'Avg PnL:':18s}{ap_s:>{col_w}}{ap_a:>{col_w}}{ap_b:>{col_w}}")

    tp_s = f"{single_summary['total_pnl']:.2f}%"
    tp_a = f"{plan_a_summary['total_pnl']:.2f}%"
    tp_b = f"{plan_b_summary['total_pnl']:.2f}%"
    print(f"{'Total PnL:':18s}{tp_s:>{col_w}}{tp_a:>{col_w}}{tp_b:>{col_w}}")

    st_s = f"{single_summary['stopped']}"
    st_a = f"{plan_a_summary['stopped']}"
    st_b = f"{plan_b_summary['stopped']}"
    print(f"{'Stopped Out:':18s}{st_s:>{col_w}}{st_a:>{col_w}}{st_b:>{col_w}}")

    te_s = f"{single_summary['time_exit']}"
    te_a = f"{plan_a_summary['time_exit']}"
    te_b = f"{plan_b_summary['time_exit']}"
    print(f"{'Time Exits:':18s}{te_s:>{col_w}}{te_a:>{col_w}}{te_b:>{col_w}}")


def print_verbose_detail(single_results: List[Dict], plan_a_results: List[Dict],
                         plan_b_results: List[Dict]):
    """Print per-symbol P&L breakdown."""
    # Build lookup by symbol
    def _by_symbol(results):
        return {r['symbol']: r for r in results if r.get('symbol')}

    single_map = _by_symbol(single_results)
    plan_a_map = _by_symbol(plan_a_results)
    plan_b_map = _by_symbol(plan_b_results)

    all_symbols = sorted(set(single_map) | set(plan_a_map) | set(plan_b_map))
    if not all_symbols:
        return

    print("\n  Per-symbol detail:")
    for sym in all_symbols:
        parts = []

        # Single
        sr = single_map.get(sym)
        if sr:
            pnl = _pnl_for_result(sr)
            parts.append(f"Single={pnl:+.2f}%" if pnl is not None else f"Single={sr.get('status', '?')}")
        else:
            parts.append("Single=N/A")

        # Plan A
        ar = plan_a_map.get(sym)
        if ar:
            pnl = _pnl_for_result(ar)
            t1 = ar.get('tranche1_pnl_pct')
            t2 = ar.get('tranche2_pnl_pct')
            pnl_str = f"{pnl:+.2f}%" if pnl is not None else ar.get('status', '?')
            tranche_str = ""
            if t1 is not None and t2 is not None:
                tranche_str = f" (T1:{t1:+.2f}%, T2:{t2:+.2f}%)"
            parts.append(f"PlanA={pnl_str}{tranche_str}")
        else:
            parts.append("PlanA=N/A")

        # Plan B
        br = plan_b_map.get(sym)
        if br:
            pnl = _pnl_for_result(br)
            t1 = br.get('tranche1_pnl_pct')
            t2 = br.get('tranche2_pnl_pct')
            pnl_str = f"{pnl:+.2f}%" if pnl is not None else br.get('status', '?')
            tranche_str = ""
            if t1 is not None and t2 is not None:
                tranche_str = f" (T1:{t1:+.2f}%, T2:{t2:+.2f}%)"
            parts.append(f"PlanB={pnl_str}{tranche_str}")
        else:
            parts.append("PlanB=N/A")

        print(f"  {sym}: {' | '.join(parts)}")


def write_csv(rows: List[Dict], target_date: str):
    """Export comparison results to CSV."""
    log_dir = Path('src/logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    csv_path = log_dir / f"split_comparison_{target_date}.csv"

    fieldnames = [
        'date', 'symbol', 'strategy',
        'single_status', 'single_pnl',
        'plan_a_status', 'plan_a_pnl', 'plan_a_t1_pnl', 'plan_a_t2_pnl',
        'plan_b_status', 'plan_b_pnl', 'plan_b_t1_pnl', 'plan_b_t2_pnl',
    ]

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nCSV exported to {csv_path}")


def run_comparison(args: Dict):
    """Run the split-exit comparison."""
    with create_cli_context() as ctx:
        config = BacktestConfig(hold_days=args['hold_days'])
        bt = Backtester(config=config, database=ctx.db)

        options = BacktestOptions(
            strategy=args['strategy'],
            top_n=args['top_n'],
        )

        plan_a = SplitExitConfig(mode='fixed_pct', t1_profit_pct=args['t1_pct'])
        plan_b = SplitExitConfig(
            mode='atr_tiered',
            t1_atr_multiple=args['t1_atr'],
            t2_atr_multiple=args['t2_atr'],
        )

        # Build list of dates
        dates = []
        current_ts = pd.to_datetime(args['target_date'])
        if args['end_date']:
            end_ts = pd.to_datetime(args['end_date'])
            while current_ts <= end_ts:
                dates.append(current_ts.strftime('%Y-%m-%d'))
                current_ts += pd.Timedelta(days=args['interval'])
        else:
            dates.append(args['target_date'])

        # Load symbols once
        symbols = bt._load_symbols()
        all_csv_rows = []

        # Aggregate accumulators
        agg_single, agg_plan_a, agg_plan_b = [], [], []

        for date_idx, date_str in enumerate(dates):
            print(f"\n{'='*60}")
            print(f"  Processing {date_str} ({date_idx+1}/{len(dates)})")
            print(f"{'='*60}")

            # Generate predictions ONCE
            predictions = bt._generate_predictions(symbols, date_str, options)
            top = bt._filter_and_sort_predictions(predictions, options)

            if not top:
                print(f"  No valid signals for {date_str}.")
                continue

            n_candidates = len(top)

            # Evaluate with 3 configs — use deep copies to avoid mutation issues
            top_single = copy.deepcopy(top)
            top_plan_a = copy.deepcopy(top)
            top_plan_b = copy.deepcopy(top)

            print(f"  Evaluating {n_candidates} candidates (single-exit)...")
            single_results = bt._evaluate_candidates(top_single, date_str, options, split_config=None)

            print(f"  Evaluating {n_candidates} candidates (Plan A)...")
            plan_a_results = bt._evaluate_candidates(top_plan_a, date_str, options, split_config=plan_a)

            print(f"  Evaluating {n_candidates} candidates (Plan B)...")
            plan_b_results = bt._evaluate_candidates(top_plan_b, date_str, options, split_config=plan_b)

            # Summarize
            s_single = summarize_variant(single_results)
            s_plan_a = summarize_variant(plan_a_results)
            s_plan_b = summarize_variant(plan_b_results)

            print_comparison_table(date_str, n_candidates, s_single, s_plan_a, s_plan_b,
                                   args['t1_pct'])

            if args['verbose']:
                print_verbose_detail(single_results, plan_a_results, plan_b_results)

            # Accumulate for aggregate
            agg_single.extend(single_results)
            agg_plan_a.extend(plan_a_results)
            agg_plan_b.extend(plan_b_results)

            # Build CSV rows
            single_map = {r['symbol']: r for r in single_results if r.get('symbol')}
            plan_a_map = {r['symbol']: r for r in plan_a_results if r.get('symbol')}
            plan_b_map = {r['symbol']: r for r in plan_b_results if r.get('symbol')}
            all_symbols = sorted(set(single_map) | set(plan_a_map) | set(plan_b_map))

            for sym in all_symbols:
                sr = single_map.get(sym, {})
                ar = plan_a_map.get(sym, {})
                br = plan_b_map.get(sym, {})
                row = {
                    'date': date_str,
                    'symbol': sym,
                    'strategy': args['strategy'],
                    'single_status': sr.get('status', ''),
                    'single_pnl': round(_pnl_for_result(sr) or 0.0, 2),
                    'plan_a_status': ar.get('status', ''),
                    'plan_a_pnl': round(_pnl_for_result(ar) or 0.0, 2),
                    'plan_a_t1_pnl': round(ar.get('tranche1_pnl_pct', 0.0), 2),
                    'plan_a_t2_pnl': round(ar.get('tranche2_pnl_pct', 0.0), 2),
                    'plan_b_status': br.get('status', ''),
                    'plan_b_pnl': round(_pnl_for_result(br) or 0.0, 2),
                    'plan_b_t1_pnl': round(br.get('tranche1_pnl_pct', 0.0), 2),
                    'plan_b_t2_pnl': round(br.get('tranche2_pnl_pct', 0.0), 2),
                }
                all_csv_rows.append(row)

        # Aggregate summary for range mode
        if len(dates) > 1:
            print(f"\n{'='*60}")
            print(f"  AGGREGATE SUMMARY ({len(dates)} dates)")
            print(f"{'='*60}")
            s_single = summarize_variant(agg_single)
            s_plan_a = summarize_variant(agg_plan_a)
            s_plan_b = summarize_variant(agg_plan_b)
            print_comparison_table("AGGREGATE", s_single['trades'], s_single, s_plan_a, s_plan_b,
                                   args['t1_pct'])

        # Export CSV
        if all_csv_rows:
            write_csv(all_csv_rows, args['target_date'])


if __name__ == '__main__':
    args = parse_args(sys.argv)
    run_comparison(args)
