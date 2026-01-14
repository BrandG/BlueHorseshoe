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
    load_historical_data,
    BackfillConfig
)

@patch('bluehorseshoe.data.historical_data.requests.get')
def test_load_historical_data_from_net(mock_get):
    """
    Test the load_historical_data_from_net function to ensure it correctly loads and parses
    historical stock data from a network response.

    Args:
        mock_get (MagicMock): Mock object for the requests.get function.

    Mocks:
        - Mocks the network response to return a predefined JSON structure representing
          historical stock data for a single day.

    Asserts:
        - The result is not None.
        - The result contains the correct stock name ('AAPL').
        - The result contains data for exactly one day.
        - The date of the historical data matches '2023-01-01'.
        - The opening price of the historical data matches 100.0.
    """
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'Time Series (Daily)': {
            '2023-01-01': {
                '1. open': '100.0',
                '2. high': '110.0',
                '3. low': '90.0',
                '4. close': '105.0',
                '5. adjusted close': '105.0',
                '6. volume': '1000'
            }
        }
    }
    mock_get.return_value = mock_response

    result = load_historical_data_from_net('AAPL', recent=True)
    assert result is not None
    assert result['name'] == 'AAPL'
    assert len(result['days']) == 1
    assert result['days'][0]['date'] == '2023-01-01'
    assert result['days'][0]['open'] == 100.0

@patch('bluehorseshoe.data.historical_data.get_mongo_client')
def test_load_historical_data_from_mongo(mock_get_mongo_client):
    """
    Test the load_historical_data_from_mongo function to ensure it correctly loads
    historical data from a MongoDB collection.

    Args:
        mock_get_mongo_client (MagicMock): A mock object for the MongoDB client.

    Mocks:
        - mock_db: A mock database object.
        - mock_collection: A mock collection object within the database.
        - mock_collection.find_one: Mocked to return a dictionary with 'symbol' and 'days' keys.
        - mock_db.__getitem__: Mocked to return the mock_collection.
        - mock_get_mongo_client.return_value: Mocked to return the mock_db.

    Asserts:
        - The result is not None.
        - The 'symbol' key in the result is 'AAPL'.
        - The 'days' key is present in the result.
    """
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_collection.find_one.return_value = {'symbol': 'AAPL', 'days': []}
    mock_db.__getitem__.return_value = mock_collection
    mock_get_mongo_client.return_value = mock_db

    result = load_historical_data_from_mongo('AAPL', mock_db)
    assert result is not None
    assert result['symbol'] == 'AAPL'
    assert 'days' in result

@patch('bluehorseshoe.data.historical_data.get_mongo_client')
def test_save_historical_data_to_mongo(mock_get_mongo_client):
    """
    Test the save_historical_data_to_mongo function to ensure it correctly saves data to MongoDB.

    Args:
        mock_get_mongo_client (MagicMock): Mocked function to get the MongoDB client.

    Mocks:
        - mock_db (MagicMock): Mocked MongoDB database.
        - mock_collection (MagicMock): Mocked MongoDB collection.

    Test:
        - Mocks the MongoDB client, database, and collection.
        - Calls the save_historical_data_to_mongo function with sample data.
        - Asserts that the update_one method on the mocked collection is called.
    """
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__.return_value = mock_collection
    mock_get_mongo_client.return_value = mock_db

    data = {'symbol': 'AAPL', 'days': []}
    save_historical_data_to_mongo('AAPL', data, mock_db)
    mock_collection.update_one.assert_called()

@patch('bluehorseshoe.data.historical_data.get_symbol_list', return_value=[{'symbol': 'AAPL', 'name': 'Apple Inc.'}])
@patch('bluehorseshoe.data.historical_data.load_historical_data_from_net', return_value={'symbol': 'AAPL', 'full_name': 'Apple', 'days':
    [{'date': '2023-01-01', 'open': 100.0, 'close': 105.0, 'high': 110.0, 'low': 90.0, 'volume': 1000}]})
@patch('bluehorseshoe.data.historical_data.save_historical_data_to_mongo')
def test_build_all_symbols_history(mock_save_historical_data_to_mongo, mock_load_historical_data_from_net, mock_get_symbol_list):
    """
    Test the build_all_symbols_history function.

    This test verifies that the build_all_symbols_history function correctly:
    - Calls the get_symbol_list function once.
    - Calls the load_historical_data_from_net function once with the stock symbol 'AAPL' and recent set to False.
    - Calls the save_historical_data_to_mongo function once.
    - Ensures that the first argument passed to save_historical_data_to_mongo is 'AAPL'.
    - Ensures that the second argument passed to save_historical_data_to_mongo contains a key 'days'.
    - Ensures that the value associated with the 'days' key is a list.

    Args:
        mock_save_historical_data_to_mongo (Mock): Mock for the save_historical_data_to_mongo function.
        mock_load_historical_data_from_net (Mock): Mock for the load_historical_data_from_net function.
        mock_get_symbol_list (Mock): Mock for the get_symbol_list function.
    """
    build_all_symbols_history(BackfillConfig())
    mock_get_symbol_list.assert_called_once()
    mock_load_historical_data_from_net.assert_called_once_with(stock_symbol='AAPL', recent=False)
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

@patch('bluehorseshoe.data.historical_data.load_historical_data_from_mongo')
@patch('bluehorseshoe.data.historical_data.load_historical_data_from_file')
@patch('bluehorseshoe.data.historical_data.load_historical_data_from_net')
def test_load_historical_data(mock_net, mock_file, mock_mongo):
    """
    Test the load_historical_data function.

    This test mocks the network, file, and MongoDB interactions to verify that
    the load_historical_data function returns the expected result for a given
    symbol.

    Args:
        mock_net (Mock): Mock object for network interactions.
        mock_file (Mock): Mock object for file interactions.
        mock_mongo (Mock): Mock object for MongoDB interactions.

    Asserts:
        The result is not None.
        The result contains the correct symbol ('AAPL').
        The result contains a 'days' key.
    """
    mock_mongo.return_value = None
    mock_file.return_value = None
    mock_net.return_value = {'symbol': 'AAPL', 'days': []}

    result = load_historical_data('AAPL')
    assert result is not None
    assert result['symbol'] == 'AAPL'
    assert 'days' in result
