"""
Tests for historical data management and fetching.
"""
from unittest.mock import patch, MagicMock
import pandas as pd

from bluehorseshoe.data.historical_data import (
    load_historical_data_from_net,
    save_historical_data,
    build_all_symbols_history,
    get_technical_indicators,
    get_active_symbol_list,
    get_symbols_by_market_cap,
    mark_deep_backfill_done,
    get_deep_backfill_done,
    load_historical_data,
    process_symbol,
    BackfillConfig,
)

@patch('bluehorseshoe.data.historical_data.requests.get')
def test_load_historical_data_from_net(mock_get):
    """
    Test the load_historical_data_from_net function to ensure it correctly loads and parses
    historical stock data from a Tiingo API response.

    Asserts:
        - The result is not None.
        - The result contains the correct stock name ('AAPL').
        - The result contains data for exactly one day.
        - The date of the historical data matches '2023-01-03'.
        - The opening price of the historical data matches 100.0.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            'date': '2023-01-03T00:00:00+00:00',
            'open': 102.0,
            'high': 112.0,
            'low': 92.0,
            'close': 107.0,
            'volume': 1200,
            'adjOpen': 100.0,
            'adjHigh': 110.0,
            'adjLow': 90.0,
            'adjClose': 105.0,
            'adjVolume': 1000
        }
    ]
    mock_get.return_value = mock_response

    result = load_historical_data_from_net('AAPL', recent=True)
    assert result is not None
    assert result['name'] == 'AAPL'
    assert len(result['days']) == 1
    assert result['days'][0]['date'] == '2023-01-03'
    assert result['days'][0]['open'] == 100.0
    assert result['days'][0]['close'] == 105.0
    assert result['days'][0]['volume'] == 1000

def test_save_historical_data():
    """
    Test save_historical_data writes to DuckDB store.
    """
    mock_store = MagicMock()

    data = {'symbol': 'AAPL', 'full_name': 'Apple', 'days': [
        {'date': '2023-01-01', 'open': 100.0, 'high': 110.0, 'low': 90.0, 'close': 105.0, 'volume': 1000}
    ]}
    save_historical_data('AAPL', data, mock_store)
    mock_store.save_symbol.assert_called_once()

@patch('bluehorseshoe.data.historical_data.get_symbol_list', return_value=[{'symbol': 'AAPL', 'name': 'Apple Inc.'}])
@patch('bluehorseshoe.data.historical_data._get_provider_pool')
@patch('bluehorseshoe.data.historical_data.save_historical_data')
def test_build_all_symbols_history(mock_save_historical_data, mock_get_pool, mock_get_symbol_list):
    """
    Test the build_all_symbols_history function uses provider pool dispatch.

    Verifies:
    - get_symbol_list is called once
    - Provider pool's partition_symbols is called
    - Provider fetch is called for the symbol
    - save_historical_data is called with correct data
    """
    # Set up a fake provider returned by the pool
    fake_provider = MagicMock()
    fake_provider.name = "tiingo"
    fake_provider.config = MagicMock(cps=5, enabled=True, priority=0)
    fake_provider.is_available.return_value = True
    fake_provider.fetch.return_value = {
        'symbol': 'AAPL', 'full_name': 'Apple', 'name': 'AAPL',
        'days': [{'date': '2023-01-01', 'open': 100.0, 'close': 105.0,
                  'high': 110.0, 'low': 90.0, 'volume': 1000}]
    }

    mock_pool = MagicMock()
    mock_pool.providers = [fake_provider]
    mock_pool.partition_symbols.return_value = {"tiingo": ["AAPL"]}
    mock_get_pool.return_value = mock_pool

    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__.return_value = mock_collection

    mock_store = MagicMock()
    mock_store.load_symbol_dict.return_value = {}

    build_all_symbols_history(BackfillConfig(), database=mock_db, store=mock_store)
    mock_get_symbol_list.assert_called_once()
    mock_pool.partition_symbols.assert_called_once()
    fake_provider.fetch.assert_called_once_with('AAPL', recent=False)
    mock_save_historical_data.assert_called_once()
    args, _ = mock_save_historical_data.call_args
    assert args[0] == 'AAPL'
    assert 'days' in args[1]
    assert isinstance(args[1]['days'], list)

def test_get_technical_indicators():
    """
    Test the get_technical_indicators function.

    This test creates a sample DataFrame with columns 'close', 'high', 'low', and 'volume',
    and passes it to the get_technical_indicators function. It then asserts that the
    resulting DataFrame contains the 'ema_20' column.

    The sample data used for testing is as follows:
    - 'close': [100, 101, 102, 103, 104]
    - 'high': [110, 111, 112, 113, 114]
    - 'low': [90, 91, 92, 93, 94]
    - 'volume': [1000, 1001, 1002, 1003, 1004]

    Assertions:
    - The resulting DataFrame from get_technical_indicators should contain the 'ema_20' column.
    """
    data = {
        'close': [100, 101, 102, 103, 104],
        'high': [110, 111, 112, 113, 114],
        'low': [90, 91, 92, 93, 94],
        'volume': [1000, 1001, 1002, 1003, 1004]
    }
    df = pd.DataFrame(data)
    result = get_technical_indicators(df)
    assert 'ema_20' in result[0]

def test_get_active_symbol_list_market_cap():
    """
    Test that get_active_symbol_list queries symbol_overviews by market cap
    and returns the correct set of symbols.
    """
    mock_db = MagicMock()
    mock_overviews = MagicMock()
    mock_db.__getitem__.return_value = mock_overviews

    # Simulate aggregation returning two symbols above the market cap threshold
    mock_overviews.aggregate.return_value = [
        {"symbol": "AAPL"},
        {"symbol": "MSFT"},
    ]

    result = get_active_symbol_list(mock_db)

    # Verify it queries symbol_overviews (not historical_prices_recent)
    mock_db.__getitem__.assert_called_with("symbol_overviews")
    mock_overviews.aggregate.assert_called_once()

    # Verify the pipeline structure
    pipeline = mock_overviews.aggregate.call_args[0][0]
    assert len(pipeline) == 4  # $match, $addFields, $match, $project
    assert "$addFields" in pipeline[1]
    assert "mcap_num" in pipeline[1]["$addFields"]

    assert result == {"AAPL", "MSFT"}


def test_get_active_symbol_list_empty():
    """
    Test that get_active_symbol_list returns an empty set when no symbols
    meet the market cap threshold.
    """
    mock_db = MagicMock()
    mock_overviews = MagicMock()
    mock_db.__getitem__.return_value = mock_overviews
    mock_overviews.aggregate.return_value = []

    result = get_active_symbol_list(mock_db)
    assert result == set()


@patch('bluehorseshoe.data.historical_data.load_historical_data_from_file')
@patch('bluehorseshoe.data.historical_data.load_historical_data_from_net')
def test_load_historical_data(mock_net, mock_file):
    """
    Test the load_historical_data function falls back through file -> network
    when no DuckDB store is provided.

    Asserts:
        The result is not None.
        The result contains the correct symbol ('AAPL').
        The result contains a 'days' key.
    """
    mock_file.return_value = None
    mock_net.return_value = {'symbol': 'AAPL', 'days': []}

    mock_db = MagicMock()
    result = load_historical_data('AAPL', database=mock_db)
    assert result is not None
    assert result['symbol'] == 'AAPL'
    assert 'days' in result


# ------------------------------------------------------------------
# Deep backfill tests
# ------------------------------------------------------------------


def test_get_symbols_by_market_cap():
    """Verify sort order and structure of get_symbols_by_market_cap."""
    mock_db = MagicMock()
    mock_overviews = MagicMock()
    mock_symbols = MagicMock()

    def getitem(name):
        if name == "symbol_overviews":
            return mock_overviews
        if name == "symbols":
            return mock_symbols
        return MagicMock()

    mock_db.__getitem__ = MagicMock(side_effect=getitem)

    # Aggregation returns symbols already sorted by mcap descending
    mock_overviews.aggregate.return_value = [
        {"symbol": "AAPL", "mcap_num": 3_000_000_000_000},
        {"symbol": "MSFT", "mcap_num": 2_500_000_000_000},
        {"symbol": "GOOG", "mcap_num": 1_800_000_000_000},
    ]
    mock_symbols.find.return_value = [
        {"symbol": "AAPL", "name": "Apple Inc."},
        {"symbol": "MSFT", "name": "Microsoft Corp."},
        {"symbol": "GOOG", "name": "Alphabet Inc."},
    ]

    result = get_symbols_by_market_cap(mock_db)

    assert len(result) == 3
    assert result[0]["symbol"] == "AAPL"
    assert result[0]["mcap"] == 3_000_000_000_000
    assert result[0]["name"] == "Apple Inc."
    assert result[1]["symbol"] == "MSFT"
    assert result[2]["symbol"] == "GOOG"

    # Verify the pipeline uses $sort descending
    pipeline = mock_overviews.aggregate.call_args[0][0]
    sort_stage = [s for s in pipeline if "$sort" in s]
    assert len(sort_stage) == 1
    assert sort_stage[0]["$sort"]["mcap_num"] == -1


def test_deep_backfill_completion_tracking():
    """Test mark/get roundtrip for deep backfill completion."""
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    # Mark two symbols as done
    mark_deep_backfill_done("AAPL", "2006-01-03", 5000, mock_db)
    mark_deep_backfill_done("MSFT", "2006-02-15", 4800, mock_db)

    # Verify update_one was called with correct _id
    assert mock_collection.update_one.call_count == 2
    first_call = mock_collection.update_one.call_args_list[0]
    assert first_call[0][0] == {"_id": "AAPL"}
    assert first_call[1]["upsert"] is True

    # Now test get_deep_backfill_done
    mock_collection.find.return_value = [{"_id": "AAPL"}, {"_id": "MSFT"}]
    done = get_deep_backfill_done(mock_db)
    assert done == {"AAPL", "MSFT"}


@patch('bluehorseshoe.data.historical_data.save_historical_data')
@patch('bluehorseshoe.data.historical_data.get_technical_indicators')
def test_process_symbol_skip_only_for_recent(mock_indicators, mock_save):
    """Full backfill (recent=False) should NOT skip symbols that have today's data."""
    mock_store = MagicMock()
    # Simulate a symbol that already has up-to-date data
    today_str = str(pd.Timestamp.now(tz='US/Eastern').date())
    mock_store.load_symbol_dict.return_value = {
        'days': [{'date': today_str, 'open': 100, 'high': 110, 'low': 90,
                  'close': 105, 'volume': 1000}],
        'full_name': 'Test Co.',
        'symbol': 'TEST',
    }

    mock_provider = MagicMock()
    mock_provider.fetch.return_value = {
        'symbol': 'TEST', 'full_name': 'Test Co.', 'name': 'TEST',
        'days': [
            {'date': '2020-01-02', 'open': 50, 'high': 55, 'low': 45, 'close': 52, 'volume': 500},
            {'date': today_str, 'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 1000},
        ],
    }

    mock_indicators.return_value = [
        {'date': '2020-01-02', 'open': 50, 'close': 52},
        {'date': today_str, 'open': 100, 'close': 105},
    ]

    mock_db = MagicMock()
    mock_score_col = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_score_col)

    # recent=False should NOT skip
    process_symbol(
        {'symbol': 'TEST', 'name': 'Test Co.'}, 1, 1,
        save_to_file=False, recent=False, database=mock_db,
        provider=mock_provider, store=mock_store,
    )

    # Provider should have been called (symbol was NOT skipped)
    mock_provider.fetch.assert_called_once()
    mock_save.assert_called_once()
