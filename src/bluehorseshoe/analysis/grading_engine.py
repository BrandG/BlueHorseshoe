"""
grading_engine.py

This module provides the GradingEngine class, which evaluates historical
trading signals (scores) against actual market outcomes to quantify performance.
"""

import logging
from typing import List, Dict
from dataclasses import dataclass
import pandas as pd
from bluehorseshoe.core.database import db
from bluehorseshoe.data.historical_data import load_historical_data

@dataclass
class TradeParams: # pylint: disable=too-many-instance-attributes
    """Parameters defining a trade entry and exit conditions."""
    symbol: str
    signal_date: str
    entry_price: float
    stop_loss: float
    take_profit: float
    score: float
    strategy: str
    components: Dict[str, float]

@dataclass
class TradeResult:
    """Outcome of a graded trade."""
    status: str
    exit_price: float
    exit_date: str
    max_gain: float
    min_low: float
    days_held: int

class GradingEngine:
    """
    Evaluates historical predictions stored in 'trade_scores' against actual price action.
    """

    def __init__(self, hold_days: int = 10, database=None):
        """
        Initialize GradingEngine with optional dependency injection.

        Args:
            hold_days: Number of days to hold a trade
            database: MongoDB database instance. If None, uses global singleton.
        """
        self.hold_days = hold_days
        self.database = database

    def _simulate_trade(self, params: TradeParams, future_data: pd.DataFrame) -> TradeResult:
        """Core simulation logic for iterating through future price action."""
        status = 'hold'
        exit_date = None
        exit_price = None
        max_gain = -999.0

        all_lows = future_data['low'].values
        min_low = min(all_lows) if len(all_lows) > 0 else params.entry_price
        min_low = min(min_low, params.entry_price)

        for _, day in future_data.iterrows():
            high = day['high']
            low = day['low']

            current_max_gain = ((high / params.entry_price) - 1) * 100
            max_gain = max(max_gain, current_max_gain)

            if high >= params.take_profit:
                status, exit_price, exit_date = 'success', params.take_profit, day['date']
                break

            if low <= params.stop_loss:
                status, exit_price, exit_date = 'failure', params.stop_loss, day['date']
                break

        if status == 'hold':
            last_day = future_data.iloc[-1]
            exit_price, exit_date = last_day['close'], last_day['date']
            status = 'success' if exit_price > params.entry_price else 'failure'

        days_held = len(future_data[future_data['date'] <= exit_date]) if exit_date else self.hold_days

        return TradeResult(
            status=status,
            exit_price=exit_price,
            exit_date=exit_date,
            max_gain=max_gain,
            min_low=min_low,
            days_held=days_held
        )

    def evaluate_score(self, score_doc: Dict) -> Dict:
        """
        Evaluates a single score document from the trade_scores collection.
        """
        symbol = score_doc['symbol']
        signal_date = score_doc['date']
        metadata = score_doc.get('metadata', {})

        params = TradeParams(
            symbol=symbol,
            signal_date=signal_date,
            entry_price=metadata.get('entry_price'),
            stop_loss=metadata.get('stop_loss'),
            take_profit=metadata.get('take_profit'),
            score=score_doc.get('score'),
            strategy=score_doc.get('strategy', 'unknown'),
            components=metadata.get('components', {})
        )

        if any(v is None for v in [params.entry_price, params.stop_loss, params.take_profit]):
            return {'symbol': symbol, 'date': signal_date, 'score': params.score, 'status': 'missing_metadata'}

        price_data = load_historical_data(symbol, database=self.database)
        if not price_data or 'days' not in price_data:
            return {'symbol': symbol, 'date': signal_date, 'score': params.score, 'status': 'no_data'}

        df = pd.DataFrame(price_data['days'])
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

        return self._evaluate_with_df(score_doc, df)

    def run_grading(self, query: Dict = None, limit: int = 5000) -> List[Dict]:
        """
        Runs grading on a batch of scores from MongoDB.
        Optimized to load historical data once per symbol.
        """
        if query is None:
            query = {"metadata.entry_price": {"$exists": True}}

        coll = db.get_db()['trade_scores']
        scores = list(coll.find(query).sort("date", -1).limit(limit))
        logging.info("Found %d scores to grade. Grouping by symbol...", len(scores))

        symbol_map = {}
        for s in scores:
            symbol_map.setdefault(s['symbol'], []).append(s)

        results = []
        for i, (symbol, sym_scores) in enumerate(symbol_map.items()):
            results.extend(self._process_symbol_scores(symbol, sym_scores))
            if (i + 1) % 100 == 0:
                logging.info("Processed %d/%d symbols...", i + 1, len(symbol_map))

        return results

    def _process_symbol_scores(self, symbol: str, sym_scores: List[Dict]) -> List[Dict]:
        """Helper to process all scores for a single symbol."""
        price_data = load_historical_data(symbol, database=self.database)
        if not price_data or 'days' not in price_data:
            return [{'symbol': symbol, 'date': s['date'], 'score': s.get('score'), 'status': 'no_data'}
                    for s in sym_scores]

        df = pd.DataFrame(price_data['days'])
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

        return [self._evaluate_with_df(s, df) for s in sym_scores]

    def _evaluate_with_df(self, score_doc: Dict, df: pd.DataFrame) -> Dict:
        """
        Internal method to evaluate a score using a pre-loaded DataFrame.
        """
        metadata = score_doc.get('metadata', {})
        params = TradeParams(
            symbol=score_doc['symbol'],
            signal_date=score_doc['date'],
            entry_price=metadata.get('entry_price'),
            stop_loss=metadata.get('stop_loss'),
            take_profit=metadata.get('take_profit'),
            score=score_doc.get('score'),
            strategy=score_doc.get('strategy', 'unknown'),
            components=metadata.get('components', {})
        )

        if any(v is None for v in [params.entry_price, params.stop_loss, params.take_profit]):
            return {'symbol': params.symbol, 'date': params.signal_date,
                    'score': params.score, 'status': 'missing_metadata'}

        # Get data strictly after signal_date
        future_data = df[df['date'] > params.signal_date].sort_values('date').head(self.hold_days)
        if future_data.empty:
            return {'symbol': params.symbol, 'date': params.signal_date,
                    'score': params.score, 'status': 'no_future_data'}

        sim = self._simulate_trade(params, future_data)

        # ATR at signal date (or closest before)
        signal_rows = df[df['date'] <= params.signal_date]
        atr = signal_rows.iloc[-1].get('atr_14', 1.0) if not signal_rows.empty else 1.0
        if pd.isna(atr) or atr <= 0:
            atr = 1.0

        pnl = ((sim.exit_price / params.entry_price) - 1) * 100
        mae_atr = (params.entry_price - sim.min_low) / atr if atr > 0 else 0

        return {
            'symbol': params.symbol,
            'date': params.signal_date,
            'score': params.score,
            'strategy': params.strategy,
            'components': params.components,
            'status': sim.status,
            'entry': params.entry_price,
            'exit_price': sim.exit_price,
            'exit_date': sim.exit_date,
            'pnl': pnl,
            'max_gain': sim.max_gain,
            'mae_atr': mae_atr,
            'days_held': sim.days_held
        }

    @staticmethod
    def summarize_results(results: List[Dict]) -> pd.DataFrame:
        """
        Summarizes results by score tier.
        """
        df = pd.DataFrame(results)
        # Filter out errors
        if 'status' not in df.columns:
            return pd.DataFrame()
        df = df[df['status'].isin(['success', 'failure'])]

        if df.empty:
            return pd.DataFrame()

        # Group by score and calculate metrics
        summary = df.groupby('score').agg(
            count=('symbol', 'count'),
            win_rate=('status', lambda x: (x == 'success').mean() * 100),
            avg_pnl=('pnl', 'mean'),
            avg_max_gain=('max_gain', 'mean'),
            profit_factor=('pnl', lambda x: x[x > 0].sum() / abs(x[x < 0].sum()) if x[x < 0].sum() != 0 else float('inf'))
        ).reset_index()

        return summary.sort_values('score', ascending=False)

    @staticmethod
    def summarize_components(results: List[Dict]) -> pd.DataFrame:
        """
        Summarizes performance by individual indicator components.
        Checks if the component was positive (bullish signal) or negative (bearish/penalty).
        """
        df = pd.DataFrame(results)
        if 'status' not in df.columns or 'components' not in df.columns:
            logging.warning("Missing 'status' or 'components' columns in results. Columns: %s", df.columns.tolist())
            return pd.DataFrame()

        df = df[df['status'].isin(['success', 'failure'])]
        if df.empty:
            return pd.DataFrame()

        # Expand components into individual rows
        comp_rows = []
        valid_comp_count = 0
        for _, row in df.iterrows():
            comps = row['components']
            if not isinstance(comps, dict) or not comps:
                continue

            valid_comp_count += 1
            for comp_name, comp_val in comps.items():
                if comp_val != 0: # Only analyze if the indicator actually triggered
                    comp_rows.append({
                        'component': comp_name,
                        'value': comp_val,
                        'is_bullish': comp_val > 0,
                        'status': row['status'],
                        'pnl': row['pnl']
                    })

        logging.info("Found %d rows with valid component data.", valid_comp_count)
        if not comp_rows:
            return pd.DataFrame()

        comp_df = pd.DataFrame(comp_rows)

        summary = comp_df.groupby(['component', 'is_bullish']).agg(
            count=('status', 'count'),
            win_rate=('status', lambda x: (x == 'success').mean() * 100),
            avg_pnl=('pnl', 'mean')
        ).reset_index()

        return summary.sort_values(['component', 'is_bullish'])
