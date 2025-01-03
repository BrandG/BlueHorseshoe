from unittest.mock import patch, MagicMock
import pandas as pd

from src.historical_data import (
    load_historical_data_from_net,
    load_historical_data_from_mongo,
    save_historical_data_to_mongo,
    build_all_symbols_history,
    get_technical_indicators,
    load_historical_data_from_file,
    load_historical_data
)

@patch('src.historical_data.requests.get')
def test_load_historical_data_from_net(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'Time Series (Daily)': {
            '2023-01-01': {
                '1. open': '100.0',
                '2. high': '110.0',
                '3. low': '90.0',
                '4. close': '105.0',
                '5. volume': '1000'
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

@patch('src.historical_data.get_mongo_client')
def test_load_historical_data_from_mongo(mock_get_mongo_client):
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_collection.find_one.return_value = {'symbol': 'AAPL', 'days': []}
    mock_db.__getitem__.return_value = mock_collection
    mock_get_mongo_client.return_value = mock_db

    result = load_historical_data_from_mongo('AAPL', mock_db)
    assert result is not None
    assert result['symbol'] == 'AAPL'
    assert 'days' in result

@patch('src.historical_data.get_mongo_client')
def test_save_historical_data_to_mongo(mock_get_mongo_client):
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__.return_value = mock_collection
    mock_get_mongo_client.return_value = mock_db

    data = {'symbol': 'AAPL', 'days': []}
    save_historical_data_to_mongo('AAPL', data, mock_db)
    mock_collection.update_one.assert_called()

@patch('src.historical_data.get_symbol_list', return_value=[{'symbol': 'AAPL', 'name': 'Apple Inc.'}])
@patch('src.historical_data.load_historical_data_from_net', return_value={'symbol': 'AAPL', 'days': [{'date': '2023-01-01', 'open': 100.0, 'close': 105.0, 'high': 110.0, 'low': 90.0, 'volume': 1000}]})
@patch('src.historical_data.save_historical_data_to_mongo')
def test_build_all_symbols_history(mock_save_historical_data_to_mongo, mock_load_historical_data_from_net, mock_get_symbol_list):
    build_all_symbols_history()
    mock_get_symbol_list.assert_called_once()
    mock_load_historical_data_from_net.assert_called_once_with(stock_symbol='AAPL', recent=False)
    mock_save_historical_data_to_mongo.assert_called_once()
    args, kwargs = mock_save_historical_data_to_mongo.call_args
    assert args[0] == 'AAPL'
    assert 'days' in args[1]
    assert isinstance(args[1]['days'], list)
    
def test_get_technical_indicators():
    data = {
        'close': [100, 101, 102, 103, 104],
        'high': [110, 111, 112, 113, 114],
        'low': [90, 91, 92, 93, 94],
        'volume': [1000, 1001, 1002, 1003, 1004]
    }
    df = pd.DataFrame(data)
    result = get_technical_indicators(df)
    assert 'ema_20' in result[0]

@patch('builtins.open', new_callable=MagicMock)
@patch('src.historical_data.json.load')
def test_load_historical_data_from_file(mock_json_load, mock_open):
    mock_json_load.return_value = {'symbol': 'AAPL', 'days': []}
    result = load_historical_data_from_file('AAPL')
    assert result['symbol'] == 'AAPL'
    assert 'days' in result

@patch('src.historical_data.load_historical_data_from_mongo')
@patch('src.historical_data.load_historical_data_from_file')
@patch('src.historical_data.load_historical_data_from_net')
def test_load_historical_data(mock_net, mock_file, mock_mongo):
    mock_mongo.return_value = None
    mock_file.return_value = None
    mock_net.return_value = {'symbol': 'AAPL', 'days': []}

    result = load_historical_data('AAPL')
    assert result is not None
    assert result['symbol'] == 'AAPL'
    assert 'days' in result