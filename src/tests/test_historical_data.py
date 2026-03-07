"""
Tests for historical data management and fetching.
"""
from unittest.mock import patch, MagicMock
import pandas as pd

from bluehorseshoe.data.historical_data import (
    load_historical_data_from_net,
    load_historical_data_from_mongo,
    save_historical_data_to_mongo,
    build_all_symbols_history,
    get_technical_indicators,
    get_active_symbol_list,
    load_historical_data,
    BackfillConfig
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

def test_load_historical_data_from_mongo():
    """
    Test the load_historical_data_from_mongo function to ensure it correctly loads
    historical data from a MongoDB collection.

    Mocks:
        - mock_db: A mock database object.
        - mock_collection: A mock collection object within the database.
        - mock_collection.find_one: Mocked to return a dictionary with 'symbol' and 'days' keys.

    Asserts:
        - The result is not None.
        - The 'symbol' key in the result is 'AAPL'.
        - The 'days' key is present in the result.
    """
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_collection.find_one.return_value = {'symbol': 'AAPL', 'days': []}
    mock_db.__getitem__.return_value = mock_collection

    result = load_historical_data_from_mongo('AAPL', mock_db)
    assert result is not None
    assert result['symbol'] == 'AAPL'
    assert 'days' in result

def test_save_historical_data_to_mongo():
    """
    Test the save_historical_data_to_mongo function to ensure it correctly saves data to MongoDB.

    Mocks:
        - mock_db (MagicMock): Mocked MongoDB database.
        - mock_collection (MagicMock): Mocked MongoDB collection.

    Test:
        - Mocks the MongoDB database and collection.
        - Calls the save_historical_data_to_mongo function with sample data.
        - Asserts that the update_one method on the mocked collection is called.
    """
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__.return_value = mock_collection

    data = {'symbol': 'AAPL', 'days': []}
    save_historical_data_to_mongo('AAPL', data, mock_db)
    mock_collection.update_one.assert_called()

@patch('bluehorseshoe.data.historical_data.get_symbol_list', return_value=[{'symbol': 'AAPL', 'name': 'Apple Inc.'}])
@patch('bluehorseshoe.data.historical_data._get_provider_pool')
@patch('bluehorseshoe.data.historical_data.save_historical_data_to_mongo')
def test_build_all_symbols_history(mock_save_historical_data_to_mongo, mock_get_pool, mock_get_symbol_list):
    """
    Test the build_all_symbols_history function uses provider pool dispatch.

    Verifies:
    - get_symbol_list is called once
    - Provider pool's partition_symbols is called
    - Provider fetch is called for the symbol
    - save_historical_data_to_mongo is called with correct data
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

    build_all_symbols_history(BackfillConfig(), database=mock_db)
    mock_get_symbol_list.assert_called_once()
    mock_pool.partition_symbols.assert_called_once()
    fake_provider.fetch.assert_called_once_with('AAPL', recent=False)
    mock_save_historical_data_to_mongo.assert_called_once()
    args, _ = mock_save_historical_data_to_mongo.call_args
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
    Test the load_historical_data function falls back through file → network
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
