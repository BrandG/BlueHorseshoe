"""
build_test_dates.py

Classifies trading dates by market regime using SPY/QQQ EMAs + breadth,
then selects 30 stratified dates (6 per bucket) for a representative test set.

5 buckets: Strong Bull, Mild Bull, Neutral, Mild Bear, Strong Bear

Usage:
    docker exec bluehorseshoe python src/build_test_dates.py
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from pymongo import MongoClient

from bluehorseshoe.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

OUTPUT_PATH = Path("/workspaces/BlueHorseshoe/src/test_dates.json")

# Breadth stocks (same as MarketRegime)
BREADTH_STOCKS = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'NVDA', 'JNJ', 'JPM',
    'V', 'PG', 'MA', 'HD', 'UNH', 'DIS', 'BAC', 'ADBE', 'CRM', 'XOM'
]

DATES_PER_BUCKET = 6
BUCKETS = ['strong_bull', 'mild_bull', 'neutral', 'mild_bear', 'strong_bear']

# Minimum gap between selected dates (trading days)
MIN_GAP_DAYS = 5


def load_symbol_df(db, symbol: str, store=None) -> pd.DataFrame:
    """Load full history for a symbol from DuckDB (or MongoDB fallback)."""
    if store is not None:
        df = store.load_symbol(symbol)
        if df is not None and not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            return df.sort_values('date').reset_index(drop=True)
    doc = db['historical_prices'].find_one({'symbol': symbol})
    if not doc or not doc.get('days'):
        return pd.DataFrame()
    df = pd.DataFrame(doc['days'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    return df


def compute_regime_scores(db, start_date: str = '2024-06-01', end_date: str = '2026-02-28'):
    """
    For each trading day in range, compute a market regime score (0-10).

    Score components:
      SPY: +1 each for close > EMA20, EMA50, EMA200, not-downtrend (0-4)
      QQQ: same (0-4)
      Breadth: +2 if >60%, +1 if >40% (0-2)
    Total: 0-10
    """
    log.info("Loading SPY and QQQ data...")
    spy = load_symbol_df(db, 'SPY')
    qqq = load_symbol_df(db, 'QQQ')

    if spy.empty or qqq.empty:
        log.error("SPY or QQQ data missing. Run: docker exec bluehorseshoe python src/main.py -b --symbols SPY,QQQ")
        sys.exit(1)

    # Compute EMAs for SPY and QQQ
    for df in [spy, qqq]:
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        # Simple trend: close vs 20-day SMA slope
        df['sma20_slope'] = df['close'].rolling(20).mean().diff(5)

    # Index by date for fast lookup
    spy = spy.set_index('date')
    qqq = qqq.set_index('date')

    # Load breadth stocks
    log.info("Loading %d breadth stocks...", len(BREADTH_STOCKS))
    breadth_dfs = {}
    for sym in BREADTH_STOCKS:
        bdf = load_symbol_df(db, sym)
        if not bdf.empty and len(bdf) > 50:
            bdf['ema50'] = bdf['close'].ewm(span=50, adjust=False).mean()
            bdf = bdf.set_index('date')
            breadth_dfs[sym] = bdf

    log.info("Loaded %d/%d breadth stocks", len(breadth_dfs), len(BREADTH_STOCKS))

    # Get trading days from SPY
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    trading_days = spy.loc[start:end].index

    log.info("Scoring %d trading days (%s to %s)...", len(trading_days), start_date, end_date)

    results = []
    for day in trading_days:
        # SPY score (0-4)
        spy_score = 0
        if day in spy.index:
            row = spy.loc[day]
            if row['close'] > row['ema20']:
                spy_score += 1
            if row['close'] > row['ema50']:
                spy_score += 1
            if row['close'] > row['ema200']:
                spy_score += 1
            if row['sma20_slope'] > 0:  # Not downtrend proxy
                spy_score += 1

        # QQQ score (0-4)
        qqq_score = 0
        if day in qqq.index:
            row = qqq.loc[day]
            if row['close'] > row['ema20']:
                qqq_score += 1
            if row['close'] > row['ema50']:
                qqq_score += 1
            if row['close'] > row['ema200']:
                qqq_score += 1
            if row['sma20_slope'] > 0:
                qqq_score += 1

        # Breadth (0-2)
        above = 0
        total = 0
        for sym, bdf in breadth_dfs.items():
            if day in bdf.index:
                if bdf.loc[day, 'close'] > bdf.loc[day, 'ema50']:
                    above += 1
                total += 1
        breadth_pct = above / total if total > 0 else 0.5
        breadth_score = 2 if breadth_pct > 0.6 else (1 if breadth_pct > 0.4 else 0)

        total_score = spy_score + qqq_score + breadth_score

        results.append({
            'date': day.strftime('%Y-%m-%d'),
            'score': total_score,
            'spy_score': spy_score,
            'qqq_score': qqq_score,
            'breadth_pct': round(breadth_pct, 3),
            'breadth_score': breadth_score,
        })

    return results


def classify_bucket(score: int) -> str:
    """Classify a 0-10 score into one of 5 buckets."""
    if score >= 9:
        return 'strong_bull'
    elif score >= 7:
        return 'mild_bull'
    elif score >= 5:
        return 'neutral'
    elif score >= 3:
        return 'mild_bear'
    else:
        return 'strong_bear'


def _satisfies_gap(pdate: datetime, selected_dates: set, min_gap: int) -> bool:
    """Check if pdate is at least min_gap calendar days from all selected dates."""
    for existing in selected_dates:
        if abs((pdate - existing).days) < min_gap:
            return False
    return True


def select_dates(scored_days: list, dates_per_bucket: int = 6) -> dict:
    """
    Select stratified dates, preferring even calendar spacing.
    Ensures minimum gap between selected dates across all buckets.

    Strategy: for each bucket, build evenly-spaced candidate indices, then
    greedily pick from the full pool starting near each candidate. If the
    ideal pick violates the gap constraint, scan nearby dates for a valid
    alternative. If a bucket's pool is smaller than dates_per_bucket, take
    all that satisfy the gap (relaxing the gap if needed to hit the target).
    """
    # Group by bucket
    buckets = {b: [] for b in BUCKETS}
    for day in scored_days:
        bucket = classify_bucket(day['score'])
        buckets[bucket].append(day)

    log.info("\nBucket distribution:")
    for b in BUCKETS:
        log.info("  %-15s %d dates available", b, len(buckets[b]))

    selected = {}
    all_selected_dates = set()

    for bucket_name in BUCKETS:
        pool = buckets[bucket_name]
        if not pool:
            log.warning("  WARNING: No dates for bucket '%s'", bucket_name)
            selected[bucket_name] = []
            continue

        pool.sort(key=lambda x: x['date'])
        n_want = min(dates_per_bucket, len(pool))

        # Build ideal anchor indices (evenly spaced through pool)
        if n_want >= len(pool):
            anchors = list(range(len(pool)))
        else:
            step = len(pool) / n_want
            anchors = [int(i * step) for i in range(n_want)]

        # First pass: try to fill from anchors, scanning nearby if anchor conflicts
        used_indices = set()
        final_picks = []

        for anchor_idx in anchors:
            if len(final_picks) >= n_want:
                break
            # Try anchor first, then search outward (±1, ±2, ...) for a valid date
            best = None
            for offset in range(len(pool)):
                for candidate_idx in [anchor_idx + offset, anchor_idx - offset]:
                    if candidate_idx < 0 or candidate_idx >= len(pool):
                        continue
                    if candidate_idx in used_indices:
                        continue
                    cdate = datetime.strptime(pool[candidate_idx]['date'], '%Y-%m-%d')
                    if _satisfies_gap(cdate, all_selected_dates, MIN_GAP_DAYS):
                        best = candidate_idx
                        break
                if best is not None:
                    break

            if best is not None:
                pdate = datetime.strptime(pool[best]['date'], '%Y-%m-%d')
                final_picks.append(pool[best])
                all_selected_dates.add(pdate)
                used_indices.add(best)

        # Second pass: if still short, scan entire pool for any remaining valid dates
        if len(final_picks) < n_want:
            for idx, day in enumerate(pool):
                if len(final_picks) >= n_want:
                    break
                if idx in used_indices:
                    continue
                pdate = datetime.strptime(day['date'], '%Y-%m-%d')
                if _satisfies_gap(pdate, all_selected_dates, MIN_GAP_DAYS):
                    final_picks.append(day)
                    all_selected_dates.add(pdate)
                    used_indices.add(idx)

        # Third pass: if STILL short (small pool with tight clustering),
        # relax gap constraint progressively
        if len(final_picks) < n_want:
            for relaxed_gap in range(MIN_GAP_DAYS - 1, 0, -1):
                for idx, day in enumerate(pool):
                    if len(final_picks) >= n_want:
                        break
                    if idx in used_indices:
                        continue
                    pdate = datetime.strptime(day['date'], '%Y-%m-%d')
                    if _satisfies_gap(pdate, all_selected_dates, relaxed_gap):
                        final_picks.append(day)
                        all_selected_dates.add(pdate)
                        used_indices.add(idx)
                        log.info("  %s: relaxed gap to %d days for %s",
                                 bucket_name, relaxed_gap, day['date'])
                if len(final_picks) >= n_want:
                    break

        # Sort final picks by date
        final_picks.sort(key=lambda x: x['date'])
        selected[bucket_name] = final_picks

    return selected


def main():
    settings = get_settings()
    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db]

    try:
        scored_days = compute_regime_scores(db)

        if not scored_days:
            log.error("No scored days found.")
            sys.exit(1)

        selected = select_dates(scored_days)

        # Build output
        output = {
            'description': 'Stratified test dates by market regime (5 buckets, ~6 per bucket)',
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'score_ranges': {
                'strong_bull': '9-10 (SPY+QQQ all above EMAs, strong breadth)',
                'mild_bull': '7-8',
                'neutral': '5-6',
                'mild_bear': '3-4',
                'strong_bear': '0-2 (indices below EMAs, weak breadth)',
            },
            'buckets': {},
            'all_dates': [],
        }

        total = 0
        for bucket_name in BUCKETS:
            dates_info = selected[bucket_name]
            output['buckets'][bucket_name] = dates_info
            for d in dates_info:
                output['all_dates'].append(d['date'])
            total += len(dates_info)
            log.info("\n%s (%d dates):", bucket_name.upper(), len(dates_info))
            for d in dates_info:
                log.info("  %s  score=%d  (SPY=%d QQQ=%d breadth=%.0f%%)",
                         d['date'], d['score'], d['spy_score'], d['qqq_score'],
                         d['breadth_pct'] * 100)

        output['all_dates'].sort()

        log.info("\n" + "=" * 50)
        log.info("Total selected: %d dates across %d buckets", total, len(BUCKETS))
        log.info("Saving to %s", OUTPUT_PATH)

        with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)

        log.info("Done.")

    finally:
        client.close()


if __name__ == '__main__':
    main()
