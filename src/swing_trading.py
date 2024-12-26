"""
This module provides functions for swing trading analysis.

The module includes functions to calculate entry and exit points for trading based on historical price data and 
a temporary prediction function to identify top buy candidates.

Functions:
    get_entry_exit_points(price_data): Calculate entry and exit points for trading based on price data.
    swing_predict(): Temporary prediction function to identify top buy candidates.
"""
from globals import ReportSingleton, get_symbol_name_list
from historical_data import load_historical_data


def get_entry_exit_points(price_data):
    """
    Calculate entry and exit points for trading based on price data.

    This function analyzes the provided price data to determine potential entry and exit points for trading. 
    It calculates a score for the most recent day based on various indicators and sets the entry price, 
    stop loss, and take profit levels.

    Args:
        price_data (dict): A dictionary containing price data with the following structure:
            {
                'days': [
                    {
                        'close': float,
                        'ema_20': float,
                        'macd_line': float,
                        'macd_signal': float,
                        'adx': float,
                        'high': float,
                        'atr_14': float
                    },
                    ...
                ]
            }

    Returns:
        dict: The updated price data dictionary with added entry and exit points for the most recent day.
    """
    if len(price_data['days']) >= 2:
        yesterday = price_data['days'][-1]
        prev_day = price_data['days'][-2]

        yesterday['score'] = (
            (1 if yesterday['close'] > yesterday['ema_20'] else 0) +
            (1 if yesterday['macd_line'] > yesterday['macd_signal'] else 0) +
            (1 if yesterday['macd_line'] > 0 else 0) +
            (1 if yesterday['adx'] > 20 else 0)
        )

        yesterday['entry_price'] = max(yesterday['high'], prev_day['high']) + 0.2 * yesterday['atr_14']
        yesterday['stop_loss'] = yesterday['entry_price'] * 0.96
        yesterday['take_profit'] = yesterday['entry_price'] * 1.04

    return price_data

def swing_predict():
    """
    Temporary Prediction function

    Returns:
        None
    """
    symbols = get_symbol_name_list()
    results = []
    for _, symbol in enumerate(symbols):
        price_data = load_historical_data(symbol)
        if price_data is None:
            ReportSingleton().write(f"Failed to load historical data for {symbol}.")
            return
        price_data = get_entry_exit_points(price_data)
        yesterday = price_data['days'][-1]
        if 'entry_price' in yesterday and yesterday['entry_price'] > 0 and 'stop_loss' in yesterday \
            and 'take_profit' in yesterday and 'score' in yesterday:
            results.append({'symbol': symbol, 'entry_price': yesterday['entry_price'], 'stop_loss': yesterday['stop_loss'],
                            'take_profit': yesterday['take_profit'], 'score': yesterday['score']})
            # ReportSingleton().write(f'{yesterday["date"]} - {symbol} - Entry: {yesterday["entry_price"]} - Stop-Loss: {yesterday["stop_loss"]} - '
            # f'Take-Profit: {yesterday["take_profit"]}')
    sorted_days = sorted(results, key=lambda x: x.get('score', 0), reverse=True)
    ReportSingleton().write('Top 10 buy candidates:')
    for i in range(min(10, len(sorted_days))):
        ReportSingleton().write(f'{sorted_days[i]["symbol"]} - Entry: {sorted_days[i]["entry_price"]} - Stop-Loss: {sorted_days[i]["stop_loss"]} -' \
                                f' Take-Profit: {sorted_days[i]["take_profit"]}')
