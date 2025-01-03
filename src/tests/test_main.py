import pytest
import sys
sys.path.append('/workspaces/BlueHorseshoe/src')

import logging
from main import debug_test

@pytest.fixture
def setup_logging():
    logging.basicConfig(filename='/workspaces/BlueHorseshoe/src/logs/blueHorseshoe_test.log', filemode='w',
                        level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    yield
    logging.shutdown()

def test_debug_test():
    assert debug_test() is None

# @patch('main.get_mongo_client')
# @patch('main.build_all_symbols_history')
# def test_main_update_recent_history(mock_build_all_symbols_history, mock_get_mongo_client, setup_logging):
#     mock_get_mongo_client.return_value = MagicMock()
#     sys.argv = ['main.py', '-u']
#     build_all_symbols_history(recent=True)
#     mock_build_all_symbols_history.assert_called_with(recent=True)

# @patch('main.get_mongo_client')
# @patch('main.build_all_symbols_history')
# def test_main_update_full_history(mock_build_all_symbols_history, mock_get_mongo_client, setup_logging):
#     mock_get_mongo_client.return_value = MagicMock()
#     sys.argv = ['main.py', '-b']
#     build_all_symbols_history(recent=False)
#     mock_build_all_symbols_history.assert_called_with(recent=False)

# @patch('main.get_mongo_client')
# @patch('main.SwingTrader')
# def test_main_predict(mock_swing_trader, mock_get_mongo_client, setup_logging):
#     mock_get_mongo_client.return_value = MagicMock()
#     mock_swing_trader_instance = mock_swing_trader.return_value
#     sys.argv = ['main.py', '-p']
#     importlib.import_module('main')

#     mock_swing_trader_instance.swing_predict.assert_called_once()
