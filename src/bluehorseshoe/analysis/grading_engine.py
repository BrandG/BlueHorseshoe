"""
grading_engine.py

This module provides the GradingEngine class, which evaluates historical
trading signals (scores) against actual market outcomes to quantify performance.
"""

import logging
from typing import List, Dict
import pandas as pd
from bluehorseshoe.core.database import db
from bluehorseshoe.data.historical_data import load_historical_data

class GradingEngine:
    """
    Evaluates historical predictions stored in 'trade_scores' against actual price action.
    """

    def __init__(self, hold_days: int = 10):
        self.hold_days = hold_days

    def evaluate_score(self, score_doc: Dict) -> Dict:
        """
        Evaluates a single score document from the trade_scores collection.

        Logic:
        1. Extract entry_price, stop_loss, and take_profit from metadata.
        2. Load historical data for the symbol.
        3. Iterate through subsequent days up to hold_days.
        4. Determine if the trade hit take_profit, stop_loss, or timed out.
        """
        symbol = score_doc['symbol']
        signal_date = score_doc['date']
        metadata = score_doc.get('metadata', {})

        # We need entry, stop, and take_profit to evaluate.
        entry_price = metadata.get('entry_price')
        stop_loss = metadata.get('stop_loss')
        take_profit = metadata.get('take_profit')

        if entry_price is None or stop_loss is None or take_profit is None:
            return {'symbol': symbol, 'date': signal_date, 'score': score_doc.get('score'), 'status': 'missing_metadata'}

        price_data = load_historical_data(symbol)
        if not price_data or 'days' not in price_data:
            return {'symbol': symbol, 'date': signal_date, 'score': score_doc.get('score'), 'status': 'no_data'}

        df = pd.DataFrame(price_data['days'])
        # Ensure date is string for comparison
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

        # Get data strictly after signal_date
        future_data = df[df['date'] > signal_date].sort_values('date').head(self.hold_days)
        if future_data.empty:
            return {'symbol': symbol, 'date': signal_date, 'score': score_doc.get('score'), 'status': 'no_future_data'}

        status = 'hold'
        exit_date = None
        exit_price = None
        max_gain = -999.0

        # Track min_low over the entire hold window for ML training
        all_lows = future_data['low'].values
        min_low = min(all_lows) if len(all_lows) > 0 else entry_price
        min_low = min(min_low, entry_price)

        # ATR at signal date (or closest before)
        signal_row = df[df['date'] <= signal_date].iloc[-1] if not df[df['date'] <= signal_date].empty else None
        atr = signal_row.get('atr_14', 1.0) if signal_row is not None else 1.0
        if pd.isna(atr) or atr <= 0:
            atr = 1.0

        for _, day in future_data.iterrows():
            high = day['high']
            low = day['low']

            # Calculate max gain seen so far relative to entry
            current_max_gain = ((high / entry_price) - 1) * 100
            max_gain = max(max_gain, current_max_gain)

            # Success condition: High hits or exceeds take_profit
            if high >= take_profit:
                status = 'success'
                exit_price = take_profit
                exit_date = day['date']
                break

            # Failure condition: Low hits or drops below stop_loss
            if low <= stop_loss:
                status = 'failure'
                exit_price = stop_loss
                exit_date = day['date']
                break

        if status == 'hold':
            # Time-based exit at the end of the hold period (Close price)
            last_day = future_data.iloc[-1]
            exit_price = last_day['close']
            exit_date = last_day['date']
            status = 'success' if exit_price > entry_price else 'failure'

        pnl = ((exit_price / entry_price) - 1) * 100
        mae = entry_price - min_low
        mae_atr = mae / atr if atr > 0 else 0

        return {
            'symbol': symbol,
            'date': signal_date,
            'score': score_doc['score'],
            'strategy': score_doc.get('strategy', 'unknown'),
            'components': metadata.get('components', {}),
            'status': status,
            'entry': entry_price,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'pnl': pnl,
            'max_gain': max_gain,
            'mae_atr': mae_atr,
            'days_held': len(future_data[future_data['date'] <= exit_date]) if exit_date else self.hold_days
        }

    def run_grading(self, query: Dict = None, limit: int = 5000) -> List[Dict]:
        """
        Runs grading on a batch of scores from MongoDB.
        Optimized to load historical data once per symbol.
        """
        if query is None:
            # Default to scores that have the necessary metadata
            query = {"metadata.entry_price": {"$exists": True}}

        coll = db.get_db()['trade_scores']
        scores = list(coll.find(query).sort("date", -1).limit(limit))

        logging.info("Found %d scores to grade. Grouping by symbol...", len(scores))

        # Group scores by symbol
        symbol_map = {}
        for s in scores:
            sym = s['symbol']
            if sym not in symbol_map:
                symbol_map[sym] = []
            symbol_map[sym].append(s)

        results = []
        total_symbols = len(symbol_map)
        for i, (symbol, sym_scores) in enumerate(symbol_map.items()):
            # Load price data once for this symbol
            price_data = load_historical_data(symbol)
            if not price_data or 'days' not in price_data:
                for s in sym_scores:
                    results.append({'symbol': symbol, 'date': s['date'], 'score': s.get('score'), 'status': 'no_data'})
                continue

            df = pd.DataFrame(price_data['days'])
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

            for score_doc in sym_scores:
                res = self._evaluate_with_df(score_doc, df)
                results.append(res)

            if (i + 1) % 100 == 0:
                logging.info("Processed %d/%d symbols...", i + 1, total_symbols)

        return results

    def _evaluate_with_df(self, score_doc: Dict, df: pd.DataFrame) -> Dict:
        """
        Internal method to evaluate a score using a pre-loaded DataFrame.
        """
        symbol = score_doc['symbol']
        signal_date = score_doc['date']
        metadata = score_doc.get('metadata', {})

        entry_price = metadata.get('entry_price')
        stop_loss = metadata.get('stop_loss')
        take_profit = metadata.get('take_profit')

        if entry_price is None or stop_loss is None or take_profit is None:
            return {'symbol': symbol, 'date': signal_date, 'score': score_doc.get('score'), 'status': 'missing_metadata'}

        # Get data strictly after signal_date
        future_data = df[df['date'] > signal_date].sort_values('date').head(self.hold_days)
        if future_data.empty:
            return {'symbol': symbol, 'date': signal_date, 'score': score_doc.get('score'), 'status': 'no_future_data'}

        status = 'hold'
        exit_date = None
        exit_price = None
        max_gain = -999.0

        # Track min_low over the entire hold window for ML training
        all_lows = future_data['low'].values
        min_low = min(all_lows) if len(all_lows) > 0 else entry_price
        min_low = min(min_low, entry_price)

        # ATR at signal date (or closest before)
        signal_rows = df[df['date'] <= signal_date]
        atr = signal_rows.iloc[-1].get('atr_14', 1.0) if not signal_rows.empty else 1.0
        if pd.isna(atr) or atr <= 0:
            atr = 1.0

        for _, day in future_data.iterrows():
            high = day['high']
            low = day['low']

            current_max_gain = ((high / entry_price) - 1) * 100
            max_gain = max(max_gain, current_max_gain)

            if high >= take_profit:
                status = 'success'
                exit_price = take_profit
                exit_date = day['date']
                break

            if low <= stop_loss:
                status = 'failure'
                exit_price = stop_loss
                exit_date = day['date']
                break

        if status == 'hold':
            last_day = future_data.iloc[-1]
            exit_price = last_day['close']
            exit_date = last_day['date']
            status = 'success' if exit_price > entry_price else 'failure'

        pnl = ((exit_price / entry_price) - 1) * 100
        mae = entry_price - min_low
        mae_atr = mae / atr if atr > 0 else 0

        return {
            'symbol': symbol,
            'date': signal_date,
            'score': score_doc['score'],
            'strategy': score_doc.get('strategy', 'unknown'),
            'components': metadata.get('components', {}),
            'status': status,
            'entry': entry_price,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'pnl': pnl,
            'max_gain': max_gain,
            'mae_atr': mae_atr,
            'days_held': len(future_data[future_data['date'] <= exit_date]) if exit_date else self.hold_days
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
