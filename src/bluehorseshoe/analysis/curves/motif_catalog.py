"""
Motif catalog builder.

Scans historical data, extracts signatures at every date, measures forward
outcomes, and builds a scored catalog keyed by motif_key + window_size.
"""

import logging
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from bluehorseshoe.analysis.curves.segmenter import segment_price_series
from bluehorseshoe.analysis.curves.signature import extract_signature


def measure_forward_outcomes(
    df: pd.DataFrame,
    window_size: int = 40,
    epsilon: float = 1.0,
    forward_days: int = 5,
    win_pct: float = 0.02,
    loss_pct: float = 0.02,
) -> List[Dict]:
    """
    Scan a single symbol's full history and measure forward outcome for each
    date's motif signature.

    Args:
        df: DataFrame with date, close, high, low columns. Must be sorted by date.
        window_size: Bars to use for segmentation.
        epsilon: RDP simplification threshold.
        forward_days: Days to look ahead for outcome.
        win_pct: Target profit percentage (0.02 = 2%).
        loss_pct: Stop loss percentage (0.02 = 2%).

    Returns:
        List of {motif_key, outcome, forward_return} dicts.
    """
    if len(df) < window_size + forward_days:
        return []

    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    # Pre-compute rolling max-high and min-low for forward outcome
    # For each bar i, we want max(high[i+1:i+1+forward_days]) and min(low[i+1:i+1+forward_days])
    n = len(df)
    fwd_max_high = np.full(n, np.nan)
    fwd_min_low = np.full(n, np.nan)

    for i in range(n - forward_days):
        fwd_max_high[i] = np.max(high[i + 1:i + 1 + forward_days])
        fwd_min_low[i] = np.min(low[i + 1:i + 1 + forward_days])

    # Also compute simple forward return (close-to-close)
    fwd_return = np.full(n, np.nan)
    for i in range(n - forward_days):
        fwd_return[i] = (close[i + forward_days] - close[i]) / close[i]

    results = []
    # Start from window_size (need enough history) up to n - forward_days (need forward data)
    for end_idx in range(window_size, n - forward_days):
        window_df = df.iloc[end_idx - window_size:end_idx + 1]

        try:
            seg = segment_price_series(window_df, window_size=window_size, epsilon=epsilon)
            sig = extract_signature(seg)
        except Exception:  # pylint: disable=broad-except
            continue

        entry_price = close[end_idx]
        max_high = fwd_max_high[end_idx]
        min_low = fwd_min_low[end_idx]

        if np.isnan(max_high) or np.isnan(min_low):
            continue

        # Win: price hit +win_pct before -loss_pct
        target = entry_price * (1 + win_pct)
        stop = entry_price * (1 - loss_pct)

        # Simplified: check if target was hit at all and stop was not
        hit_target = max_high >= target
        hit_stop = min_low <= stop

        if hit_target and not hit_stop:
            outcome = 1  # win
        elif hit_stop and not hit_target:
            outcome = 0  # loss
        elif hit_target and hit_stop:
            # Both hit — need to determine which came first via day-by-day scan
            outcome = _determine_first_hit(
                high[end_idx + 1:end_idx + 1 + forward_days],
                low[end_idx + 1:end_idx + 1 + forward_days],
                target, stop
            )
        else:
            outcome = 0  # neither hit = loss (timeout)

        key = f"{sig.motif_key}_{window_size}"
        results.append({
            'motif_key': key,
            'outcome': outcome,
            'forward_return': float(fwd_return[end_idx]),
        })

    return results


def _determine_first_hit(
    highs: np.ndarray, lows: np.ndarray, target: float, stop: float
) -> int:
    """Day-by-day scan to determine if target or stop was hit first."""
    for h, l in zip(highs, lows):
        if l <= stop:
            return 0  # stop hit first
        if h >= target:
            return 1  # target hit first
    return 0  # timeout


def _process_symbol(args: Tuple) -> Dict[str, Dict]:
    """Worker function for parallel catalog building."""
    _symbol, df_dict, windows, epsilon, forward_days, win_pct, loss_pct = args

    df = pd.DataFrame(df_dict)
    accumulator = defaultdict(lambda: {'wins': 0, 'total': 0, 'sum_returns': 0.0})

    for window_size in windows:
        outcomes = measure_forward_outcomes(
            df, window_size=window_size, epsilon=epsilon,
            forward_days=forward_days, win_pct=win_pct, loss_pct=loss_pct
        )
        for r in outcomes:
            key = r['motif_key']
            accumulator[key]['total'] += 1
            accumulator[key]['wins'] += r['outcome']
            accumulator[key]['sum_returns'] += r['forward_return']

    # Convert to serializable dict
    return {k: dict(v) for k, v in accumulator.items()}


def build_motif_catalog(
    store,
    symbols: List[str],
    database=None,
    windows: Tuple[int, ...] = (20, 40),
    epsilon: float = 1.0,
    forward_days: int = 5,
    win_pct: float = 0.02,
    loss_pct: float = 0.02,
    n_workers: int = 4,
) -> Dict[str, Dict]:
    """
    Build a motif catalog by scanning historical data for all symbols.

    Args:
        store: DuckDBStore for loading OHLCV data.
        symbols: List of stock symbols to process.
        database: MongoDB database for saving catalog (optional).
        windows: Window sizes for segmentation.
        epsilon: RDP threshold.
        forward_days: Forward outcome horizon.
        win_pct: Win target percentage.
        loss_pct: Loss stop percentage.
        n_workers: Number of parallel workers.

    Returns:
        Dict mapping motif_key to statistics.
    """
    logging.info("Building motif catalog for %d symbols with windows %s...", len(symbols), windows)

    # Process in chunks to avoid OOM — load batch, process, discard
    load_chunk_size = 200  # symbols per loading batch
    global_accumulator = defaultdict(lambda: {'wins': 0, 'total': 0, 'sum_returns': 0.0})
    completed = 0
    skipped = 0
    total_prepared = 0
    min_bars = max(windows) + forward_days + 10

    for chunk_start in range(0, len(symbols), load_chunk_size):
        chunk_symbols = symbols[chunk_start:chunk_start + load_chunk_size]

        # Load this chunk's data
        tasks = []
        for sym in chunk_symbols:
            try:
                df = store.load_symbol(sym)
                if df is None or len(df) < min_bars:
                    skipped += 1
                    continue
                if not all(c in df.columns for c in ['date', 'close', 'high', 'low']):
                    skipped += 1
                    continue
                tasks.append((sym, df.to_dict('list'), windows, epsilon,
                              forward_days, win_pct, loss_pct))
            except Exception as e:  # pylint: disable=broad-except
                logging.debug("Skipping %s: %s", sym, e)
                skipped += 1

        total_prepared += len(tasks)

        # Process this chunk
        if n_workers <= 1:
            for task in tasks:
                result = _process_symbol(task)
                _merge_results(global_accumulator, result)
                completed += 1
                if completed % 100 == 0:
                    logging.info("Processed %d symbols (%d skipped)...", completed, skipped)
        else:
            map_chunk = max(1, len(tasks) // (n_workers * 4))
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                for result in executor.map(_process_symbol, tasks, chunksize=map_chunk):
                    _merge_results(global_accumulator, result)
                    completed += 1
                    if completed % 100 == 0:
                        logging.info("Processed %d symbols (%d skipped)...", completed, skipped)

        # Explicitly free chunk data
        del tasks

    logging.info("Prepared %d symbols total (%d skipped)", total_prepared, skipped)

    # Compute statistics
    catalog = _compute_catalog_stats(global_accumulator)
    logging.info("Catalog built: %d unique motif keys", len(catalog))

    # Save to MongoDB if database provided
    if database is not None:
        _save_catalog_to_mongo(catalog, database)

    return catalog


def _merge_results(accumulator: dict, results: dict) -> None:
    """Merge worker results into global accumulator."""
    for key, stats in results.items():
        accumulator[key]['wins'] += stats['wins']
        accumulator[key]['total'] += stats['total']
        accumulator[key]['sum_returns'] += stats['sum_returns']


def _compute_catalog_stats(accumulator: dict) -> Dict[str, Dict]:
    """Compute final statistics for each motif."""
    # Compute baseline win rate across all motifs
    total_wins = sum(v['wins'] for v in accumulator.values())
    total_samples = sum(v['total'] for v in accumulator.values())
    baseline_win_rate = total_wins / total_samples if total_samples > 0 else 0.5

    catalog = {}
    for key, stats in accumulator.items():
        n = stats['total']
        if n < 5:  # minimum sample count
            continue

        win_rate = stats['wins'] / n
        edge = win_rate - baseline_win_rate
        avg_return = stats['sum_returns'] / n if n > 0 else 0.0

        # Edge z-score (binomial test)
        se = np.sqrt(baseline_win_rate * (1 - baseline_win_rate) / n)
        edge_zscore = edge / se if se > 0 else 0.0

        # Stability proxy: penalize low-sample motifs, reward consistency
        # With cross-symbol data, true rolling stability isn't meaningful
        # (returns are interleaved across symbols, not chronological).
        # Use a confidence-based proxy: how tight is the z-score?
        stability = min(1.0, abs(edge_zscore) / 3.0) if edge > 0 else 0.0

        # Support: saturates at 100 samples
        support = min(1.0, n / 100)

        composite = score_motif({'edge': edge, 'stability': stability, 'support': support})

        catalog[key] = {
            'motif_key': key,
            'sample_count': n,
            'win_rate': float(win_rate),
            'baseline_win_rate': float(baseline_win_rate),
            'edge': float(edge),
            'edge_zscore': float(edge_zscore),
            'stability': float(stability),
            'support': float(support),
            'composite_score': float(composite),
            'avg_forward_return_5d': float(avg_return),
        }

    return catalog


def score_motif(stats: Dict) -> float:
    """Compute composite motif score: edge * stability * support."""
    return stats.get('edge', 0.0) * stats.get('stability', 0.0) * stats.get('support', 0.0)


def _save_catalog_to_mongo(catalog: Dict[str, Dict], database) -> None:
    """Save catalog to MongoDB motif_catalog collection."""
    collection = database['motif_catalog']
    collection.drop()  # Replace entire catalog

    if not catalog:
        return

    docs = []
    now = datetime.utcnow()
    for key, stats in catalog.items():
        doc = stats.copy()
        doc['updated_at'] = now
        # Split composite key to extract window_size
        parts = key.rsplit('_', 1)
        if len(parts) == 2:
            doc['window_size'] = int(parts[1])
        docs.append(doc)

    if docs:
        collection.insert_many(docs)
        logging.info("Saved %d motif entries to MongoDB", len(docs))


def load_motif_scores(database, min_composite: float = 0.02, min_zscore: float = 1.96) -> Dict[str, float]:
    """
    Load scored motifs from MongoDB as a lookup dict.

    Returns:
        Dict mapping 'motif_key_window' to composite_score.
        Only includes motifs passing inclusion thresholds.
    """
    if database is None:
        return {}

    collection = database['motif_catalog']
    try:
        cursor = collection.find(
            {'composite_score': {'$gt': min_composite}, 'edge_zscore': {'$gt': min_zscore}},
            {'motif_key': 1, 'composite_score': 1, '_id': 0}
        )
        return {doc['motif_key']: doc['composite_score'] for doc in cursor}
    except Exception as e:  # pylint: disable=broad-except
        logging.warning("Failed to load motif scores: %s", e)
        return {}
