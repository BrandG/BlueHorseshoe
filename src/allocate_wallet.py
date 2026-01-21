"""
Allocate wallet balances based on trade scores and market regime.
"""
import sys


# Ensure src is in PYTHONPATH
sys.path.append('/workspaces/BlueHorseshoe/src')

# pylint: disable=wrong-import-position
from bluehorseshoe.cli.context import create_cli_context
from bluehorseshoe.core.scores import score_manager
from bluehorseshoe.core.symbols import get_overview_from_mongo
from bluehorseshoe.analysis.market_regime import MarketRegime
from bluehorseshoe.data.historical_data import load_historical_data

def get_latest_date(database):
    """
    Find the most recent date in the trade_scores collection.

    Args:
        database: MongoDB database instance
    """
    latest = database.trade_scores.find_one(sort=[("date", -1)])
    return latest["date"] if latest else None

def get_entry_price(symbol, target_date, database):
    """
    Retrieve entry price from metadata or fall back to latest close.

    Args:
        symbol: Stock symbol
        target_date: Target date
        database: MongoDB database instance
    """
    data = load_historical_data(symbol, database=database)
    if not data or not data.get('days'):
        return 0.0
    for day in reversed(data['days']):
        if day['date'] <= target_date:
            return day['close']
    return data['days'][-1]['close']

def _select_candidates(candidates, max_positions):
    """Filter candidates based on score thresholds and market cap."""
    final_picks = []
    for cand in candidates:
        symbol = cand['symbol']
        strategy = cand.get('strategy', 'baseline')
        total_score = cand.get('score', 0)

        threshold = 12 if strategy == 'baseline' else 8

        if total_score >= threshold:
            # Check overview for safety
            overview = get_overview_from_mongo(symbol)
            if overview:
                # Basic safety filters
                market_cap = float(overview.get('MarketCapitalization', 0))
                if market_cap < 50000000: # 50M min
                    continue

            final_picks.append(cand)
            if len(final_picks) >= max_positions:
                break
    return final_picks

def allocate(database):
    """
    Main allocation logic.

    Args:
        database: MongoDB database instance
    """
    target_date = get_latest_date(database)
    if not target_date:
        print("No trade scores found.")
        return

    print(f"Allocating for {target_date}...")

    # Market Regime Filter
    regime_info = MarketRegime.get_market_health(target_date, database=database)
    print(f"Current Market Regime: {regime_info['status']}")

    if regime_info['status'] == 'Bearish':
        print("Bear market detected. Reducing exposure.")
        max_positions = 2
    else:
        max_positions = 5

    # Get scores
    scores_baseline = score_manager.get_scores(target_date, strategy='baseline')
    scores_mr = score_manager.get_scores(target_date, strategy='mean_reversion')
    scores = scores_baseline + scores_mr

    # Filter and sort by score
    candidates = [s for s in scores if s.get('score', 0) > 0]
    candidates.sort(key=lambda x: x.get('score', 0), reverse=True)

    # Select final positions
    final_picks = _select_candidates(candidates, max_positions)

    print(f"Selected {len(final_picks)} positions:")
    for p in final_picks:
        entry = get_entry_price(p['symbol'], target_date, database)
        print(f"- {p['symbol']} ({p['strategy']}): Score {p['score']:.2f}, Entry Est: {entry:.2f}")

if __name__ == "__main__":
    with create_cli_context() as ctx:
        allocate(ctx.db)
