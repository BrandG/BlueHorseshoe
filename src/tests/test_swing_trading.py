import pytest
import pandas as pd
from swing_trading import SwingTrader, TechnicalAnalyzer

@pytest.fixture
def sample_data():
    df = pd.DataFrame([{
            'date': pd.Timestamp.now().normalize() - pd.Timedelta(days=30-i),
            'open': 1.5 * i,
            'high': 1.5 * i,
            'low': 1.5 * i,
            'close': 1.5 * i,
            'volume': 100000 * i,
            'avg_volume_20': 100000 * i,
            'dmi_p': 25 * i,
            'dmi_n': 20 * i,
            'adx': 30 * i,
            'macd_line': 1 * i,
            'macd_signal': 0.5 * i,
            'rsi_14': 50 * i,
            'roc_5': 0.5 * i,
            'bb_lower': 8 * i,
            'bb_upper': 12 * i,
            'stoch_k': 80 * i,
            'stoch_d': 80 * i,
        } for i in range(30)])
    return df

@pytest.fixture
def swing_trader():
    return SwingTrader()

def test_calculate_trend(sample_data):
    trend = TechnicalAnalyzer.calculate_trend(sample_data)
    assert trend == "Strong Uptrend"

def test_calculate_entry_price(swing_trader, sample_data):
    entry_price = swing_trader.calculate_entry_price(sample_data)
    assert entry_price == sample_data.iloc[-1]['close'] * 1.05

def test_calculate_technical_score(sample_data):
    score = TechnicalAnalyzer.calculate_technical_score(sample_data, 'IBM')
    assert score > 0

def test_process_symbol(swing_trader, sample_data, mocker):
    mocker.patch('swing_trading.load_historical_data', return_value={'days': sample_data.to_dict('records'), 'symbol':'IBM', 'full_name': 'Test Stock'})
    mocker.patch('swing_trading.GlobalData', holiday=False)
    mocker.patch('swing_trading.pd.Timestamp.now', return_value=pd.Timestamp.now().normalize())

    result = swing_trader.process_symbol('IBM')
    assert result is not None
    assert result['symbol'] == 'IBM'
    assert result['name'] == 'Test Stock'
    assert result['entry_price'] > 0
    assert result['stop_loss'] > 0
    assert result['take_profit'] > 0
    assert result['score'] > 0
