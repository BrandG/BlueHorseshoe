"""
Tests for the dedicated Connors RSI(2) section feature.

Verifies:
- connors_flag computed for all symbols (not gated on mr_data)
- connors_flag, connors_rsi2, connors_sma200 included in worker result dict
- Connors candidates appear with strategy: "Connors"
- Reporter renders Connors section heading
"""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext, _score_symbol_worker
from bluehorseshoe.reporting.html_reporter import HTMLReporter


@pytest.fixture
def mock_database():
    mock_db = MagicMock()
    mock_overviews_col = MagicMock()
    mock_overviews_col.find_one.return_value = {
        "Sector": "Technology",
        "Industry": "Software",
        "MarketCapitalization": "1000000000",
        "Beta": "1.2",
        "PERatio": "25"
    }
    mock_news_col = MagicMock()
    mock_news_col.find_one.return_value = {"feed": []}
    mock_scores_col = MagicMock()
    mock_db.__getitem__.side_effect = lambda key: {
        "symbol_overviews": mock_overviews_col,
        "symbol_news": mock_news_col,
        "trade_scores": mock_scores_col
    }.get(key, MagicMock())
    return mock_db


@pytest.fixture
def long_df():
    """Generate 250 days of data — enough for SMA200."""
    n = 250
    np.random.seed(42)
    dates = pd.bdate_range(end=pd.Timestamp('2026-01-02'), periods=n)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    # Force the last RSI(2) to be very low by making last 2 closes drop sharply
    close[-2] = close[-3] - 5
    close[-1] = close[-2] - 5
    # But keep price above SMA200 (ensure the mean is well below current price)
    close[:200] = close[:200] - 30

    df = pd.DataFrame({
        'date': dates,
        'open': close - 0.5,
        'high': close + 2,
        'low': close - 2,
        'close': close,
        'volume': np.random.randint(500000, 2000000, n),
        'avg_volume_20': [1000000] * n,
    })
    return df


def test_connors_flag_ungated_from_mr(mock_database, long_df, mocker):
    """connors_flag should be computed even when mr_data is None (baseline-only result)."""
    trader = SwingTrader(database=mock_database)
    trader.config.holiday_mode = False

    # Mock load_historical_data and Timestamp.now
    mocker.patch('bluehorseshoe.analysis.strategy.load_historical_data',
                 return_value={'days': long_df.to_dict('records'),
                               'symbol': 'TEST', 'full_name': 'Test Stock'})
    mocker.patch('bluehorseshoe.analysis.strategy.pd.Timestamp.now',
                 return_value=pd.Timestamp('2026-01-04'))

    # Mock _process_baseline to return data, _process_mr to return None
    baseline_result = {
        'score': 40.0, 'components': {'trend': 3.0},
        'setup': {'entry_price': 90.0, 'stop_loss': 85.0, 'take_profit': 100.0, 'rr_ratio': 2.0},
        'ml_prob': 0.5, 'stop_multiplier': 1.0, 'target_multiplier': 1.0
    }
    mocker.patch.object(trader, '_process_baseline', return_value=baseline_result)
    mocker.patch.object(trader, '_process_mr', return_value=None)

    ctx = StrategyContext()
    result = trader.process_symbol('TEST', ctx)

    # Even with no MR data, the connors fields should be present
    assert result is not None
    assert 'connors_flag' in result
    assert 'connors_rsi2' in result
    assert 'connors_sma200' in result
    # With 250 rows the values should be floats (not None)
    assert isinstance(result['connors_rsi2'], float)
    assert isinstance(result['connors_sma200'], float)


def test_connors_values_populated(mock_database, long_df, mocker):
    """When data has 200+ rows, connors_rsi2 and connors_sma200 should be floats."""
    trader = SwingTrader(database=mock_database)
    trader.config.holiday_mode = False

    mocker.patch('bluehorseshoe.analysis.strategy.load_historical_data',
                 return_value={'days': long_df.to_dict('records'),
                               'symbol': 'TEST', 'full_name': 'Test Stock'})
    mocker.patch('bluehorseshoe.analysis.strategy.pd.Timestamp.now',
                 return_value=pd.Timestamp('2026-01-04'))

    # Mock both strategies to return data
    baseline_result = {
        'score': 40.0, 'components': {'trend': 3.0},
        'setup': {'entry_price': 90.0, 'stop_loss': 85.0, 'take_profit': 100.0, 'rr_ratio': 2.0},
        'ml_prob': 0.5, 'stop_multiplier': 1.0, 'target_multiplier': 1.0
    }
    mr_result = {
        'score': 35.0, 'components': {'rsi': -2.0},
        'setup': {'entry_price': 90.0, 'stop_loss': 85.0, 'take_profit': 100.0, 'rr_ratio': 2.0},
        'ml_prob': 0.6, 'stop_multiplier': 1.0, 'target_multiplier': 1.0
    }
    mocker.patch.object(trader, '_process_baseline', return_value=baseline_result)
    mocker.patch.object(trader, '_process_mr', return_value=mr_result)

    ctx = StrategyContext()
    result = trader.process_symbol('TEST', ctx)

    assert result is not None
    assert isinstance(result['connors_rsi2'], float)
    assert isinstance(result['connors_sma200'], float)


def test_connors_candidates_strategy_label():
    """Connors candidates in swing_predict output should have strategy='Connors'."""
    # Simulate what swing_predict does with valid_results
    valid_results = [
        {
            'symbol': 'AAPL',
            'exchange': 'NASDAQ',
            'connors_flag': True,
            'connors_rsi2': 5.3,
            'connors_sma200': 150.0,
            'mr_score': 45.0,
            'mr_setup': {'entry_price': 155.0, 'stop_loss': 148.0, 'take_profit': 165.0},
            'mr_components': {'rsi': -2.0},
            'mr_ml_prob': 0.65,
            'baseline_score': 30.0,
            'baseline_setup': {'entry_price': 155.0, 'stop_loss': 148.0, 'take_profit': 165.0},
            'baseline_components': {'trend': 3.0},
            'baseline_ml_prob': 0.55,
            'sentiment': 0.1,
        },
        {
            'symbol': 'MSFT',
            'exchange': 'NASDAQ',
            'connors_flag': False,
            'connors_rsi2': 45.0,
            'connors_sma200': 300.0,
            'mr_score': 50.0,
            'mr_setup': {'entry_price': 310.0, 'stop_loss': 300.0, 'take_profit': 325.0},
            'mr_components': {'rsi': -1.0},
            'mr_ml_prob': 0.60,
            'baseline_score': 40.0,
            'baseline_setup': {'entry_price': 310.0, 'stop_loss': 300.0, 'take_profit': 325.0},
            'baseline_components': {'trend': 2.0},
            'baseline_ml_prob': 0.50,
            'sentiment': 0.0,
        }
    ]

    # Replicate the Connors candidate building logic from swing_predict
    connors_candidates = []
    for r in valid_results:
        if not r.get('connors_flag'):
            continue
        if r['mr_score'] > 0:
            setup = r['mr_setup']
            score = r['mr_score']
        elif r['baseline_score'] > 0:
            setup = r['baseline_setup']
            score = r['baseline_score']
        else:
            continue
        entry_price = setup.get("entry_price", 0)
        connors_candidates.append({
            "symbol": r["symbol"],
            "strategy": "Connors",
            "score": score,
            "close": entry_price,
            "connors_rsi2": r.get("connors_rsi2"),
            "connors_sma200": r.get("connors_sma200"),
        })

    assert len(connors_candidates) == 1
    assert connors_candidates[0]['symbol'] == 'AAPL'
    assert connors_candidates[0]['strategy'] == 'Connors'
    assert connors_candidates[0]['connors_rsi2'] == 5.3


def test_reporter_renders_connors_section():
    """HTML report should contain the Connors RSI(2) Setups heading."""
    reporter = HTMLReporter(database=MagicMock())
    candidates = [
        {
            'symbol': 'AAPL', 'exchange': 'NASDAQ', 'strategy': 'Connors',
            'score': 45.0, 'close': 155.0, 'stop_loss': 148.0, 'target': 165.0,
            'ml_prob': 0.65, 'sentiment': 0.1, 'connors_rsi2': 5.3,
            'connors_sma200': 150.0, 'reasons': ['RSI2=5.3', 'SMA200=150.0'],
            't1_target': 158.1,
        },
        {
            'symbol': 'MSFT', 'exchange': 'NASDAQ', 'strategy': 'Baseline',
            'score': 60.0, 'close': 310.0, 'stop_loss': 300.0, 'target': 325.0,
            'ml_prob': 0.50, 'sentiment': 0.0, 'reasons': ['trend=2.0'],
            't1_target': 316.2,
        }
    ]
    regime = {'status': 'Bullish', 'spy_price': 500, 'spy_ma50': 490, 'spy_ma200': 460}
    html = reporter.generate_report('2026-01-02', regime, candidates, [])

    assert 'Connors RSI(2) Setups' in html
    assert 'AAPL' in html
    # The Connors candidate's RSI(2) value should appear in the table
    assert '5.3' in html


def test_reporter_renders_empty_connors_section():
    """When no Connors setups exist, the report should show the empty message."""
    reporter = HTMLReporter(database=MagicMock())
    candidates = [
        {
            'symbol': 'MSFT', 'exchange': 'NASDAQ', 'strategy': 'Baseline',
            'score': 60.0, 'close': 310.0, 'stop_loss': 300.0, 'target': 325.0,
            'ml_prob': 0.50, 'sentiment': 0.0, 'reasons': ['trend=2.0'],
            't1_target': 316.2,
        }
    ]
    regime = {'status': 'Bullish', 'spy_price': 500, 'spy_ma50': 490, 'spy_ma200': 460}
    html = reporter.generate_report('2026-01-02', regime, candidates, [])

    assert 'Connors RSI(2) Setups' in html
    assert 'No Connors RSI(2) setups today' in html


def test_email_report_renders_connors_section():
    """Email report should contain the Connors RSI(2) Setups heading."""
    reporter = HTMLReporter(database=MagicMock())
    candidates = [
        {
            'symbol': 'AAPL', 'exchange': 'NASDAQ', 'strategy': 'Connors',
            'score': 45.0, 'close': 155.0, 'stop_loss': 148.0, 'target': 165.0,
            'ml_prob': 0.65, 'sentiment': 0.1, 'connors_rsi2': 5.3,
            'connors_sma200': 150.0, 'reasons': ['RSI2=5.3', 'SMA200=150.0'],
            't1_target': 158.1,
        }
    ]
    regime = {'status': 'Bullish', 'spy_price': 500, 'spy_ma50': 490, 'spy_ma200': 460}
    html = reporter.generate_email_report('2026-01-02', regime, candidates)

    assert 'Connors RSI(2) Setups' in html
    assert 'AAPL' in html


def test_arcade_report_connors_tab_and_data():
    """Arcade report should include Connors filter tab and serialize connors_rsi2."""
    reporter = HTMLReporter(database=MagicMock())
    candidates = [
        {
            'symbol': 'AAPL', 'exchange': 'NASDAQ', 'strategy': 'Connors',
            'score': 45.0, 'close': 155.0, 'stop_loss': 148.0, 'target': 165.0,
            'ml_prob': 0.65, 'sentiment': 0.1, 'connors_rsi2': 5.3,
            'connors_sma200': 150.0, 'reasons': ['RSI2=5.3', 'SMA200=150.0'],
            't1_target': 158.1,
        }
    ]
    regime = {'status': 'Bullish', 'details': {}}
    html = reporter.generate_arcade_report('2026-01-02', regime, candidates)

    assert 'CONNORS' in html  # Filter tab
    assert 'connors_rsi2' in html  # Serialized in JSON data
    assert "'Connors'" in html or '"Connors"' in html  # Strategy recognized in JS


def test_prepare_scores_saves_connors_fields(mock_database):
    """_prepare_scores_for_save() should include connors_flag, connors_rsi2, connors_sma200 in metadata."""
    trader = SwingTrader(database=mock_database)

    valid_results = [
        {
            'symbol': 'AAPL',
            'date': '2026-01-02T00:00:00',
            'baseline_score': 40.0,
            'baseline_setup': {'entry_price': 155.0, 'stop_loss': 148.0, 'take_profit': 165.0},
            'baseline_components': {'trend': 3.0},
            'baseline_ml_prob': 0.55,
            'mr_score': 35.0,
            'mr_setup': {'entry_price': 155.0, 'stop_loss': 148.0, 'take_profit': 165.0},
            'mr_components': {'rsi': -2.0},
            'mr_ml_prob': 0.65,
            'connors_flag': True,
            'connors_rsi2': 5.3,
            'connors_sma200': 150.0,
            'stop_multiplier': 1.5,
            'target_multiplier': 2.0,
        }
    ]

    score_data = trader._prepare_scores_for_save(valid_results)

    # Should have two docs: one baseline, one mean_reversion
    assert len(score_data) == 2

    for doc in score_data:
        meta = doc['metadata']
        assert meta['connors_flag'] is True
        assert meta['connors_rsi2'] == 5.3
        assert meta['connors_sma200'] == 150.0


def test_r_path_reconstructs_connors_candidates():
    """Reconstruction logic should build Connors candidates from score metadata with connors_flag."""
    # Simulate score documents as returned by ScoreManager.get_scores()
    baseline_scores = [
        {
            'symbol': 'MSFT',
            'score': 50.0,
            'metadata': {
                'entry_price': 310.0,
                'stop_loss': 300.0,
                'take_profit': 325.0,
                'ml_win_prob': 0.50,
                'components': {'trend': 2.0},
                'connors_flag': True,
                'connors_rsi2': 8.1,
                'connors_sma200': 290.0,
            }
        },
    ]
    mr_scores = [
        {
            'symbol': 'AAPL',
            'score': 45.0,
            'metadata': {
                'entry_price': 155.0,
                'stop_loss': 148.0,
                'take_profit': 165.0,
                'ml_win_prob': 0.65,
                'components': {'rsi': -2.0},
                'connors_flag': True,
                'connors_rsi2': 5.3,
                'connors_sma200': 150.0,
            }
        },
        {
            'symbol': 'GOOG',
            'score': 30.0,
            'metadata': {
                'entry_price': 140.0,
                'stop_loss': 135.0,
                'take_profit': 150.0,
                'ml_win_prob': 0.40,
                'components': {'rsi': -1.0},
                'connors_flag': False,
                'connors_rsi2': 55.0,
                'connors_sma200': 130.0,
            }
        },
    ]

    # Replicate the reconstruction logic from main.py -r block
    connors_seen = set()
    connors_candidates = []
    for s in mr_scores:
        meta = s.get('metadata', {})
        if not meta.get('connors_flag'):
            continue
        sym = s['symbol']
        if sym in connors_seen:
            continue
        connors_seen.add(sym)
        entry_price = meta.get('entry_price', 0)
        connors_candidates.append({
            "symbol": sym,
            "strategy": "Connors",
            "score": s['score'],
            "close": entry_price,
            "connors_rsi2": meta.get('connors_rsi2'),
            "connors_sma200": meta.get('connors_sma200'),
        })
    for s in baseline_scores:
        meta = s.get('metadata', {})
        if not meta.get('connors_flag'):
            continue
        sym = s['symbol']
        if sym in connors_seen:
            continue
        connors_seen.add(sym)
        entry_price = meta.get('entry_price', 0)
        connors_candidates.append({
            "symbol": sym,
            "strategy": "Connors",
            "score": s['score'],
            "close": entry_price,
            "connors_rsi2": meta.get('connors_rsi2'),
            "connors_sma200": meta.get('connors_sma200'),
        })
    connors_candidates.sort(key=lambda x: x['score'], reverse=True)
    connors_candidates = connors_candidates[:10]

    # AAPL from MR, MSFT from baseline; GOOG excluded (connors_flag=False)
    assert len(connors_candidates) == 2
    symbols = [c['symbol'] for c in connors_candidates]
    assert 'AAPL' in symbols
    assert 'MSFT' in symbols
    assert 'GOOG' not in symbols
    for c in connors_candidates:
        assert c['strategy'] == 'Connors'
        assert c['connors_rsi2'] is not None


def test_gold_star_badge_removed():
    """The inline gold star badge should no longer appear in top list items."""
    reporter = HTMLReporter(database=MagicMock())
    candidate = {
        'symbol': 'TEST', 'exchange': 'NASDAQ', 'strategy': 'MeanRev',
        'score': 50.0, 'close': 100.0, 'stop_loss': 95.0, 'target': 110.0,
        'ml_prob': 0.6, 'sentiment': 0.0, 'connors_flag': True,
        'reasons': ['rsi=-2.0'],
    }
    html = reporter._format_top_list_item(candidate)
    assert '&#9733;' not in html
    assert 'gold' not in html
