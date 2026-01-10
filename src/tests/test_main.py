"""
Module: test_main

This module contains unit tests for the main functionalities of the BlueHorseshoe application.
It uses the pytest framework for testing and includes fixtures for setting up logging configurations.

Functions:
    setup_logging: A pytest fixture that sets up logging configuration for the application.
    test_debug_test: Tests the debug_test function to ensure it returns None.

Commented Out Tests:
    test_main_update_recent_history: Tests the update of recent history by mocking dependencies.
    test_main_update_full_history: Tests the update of full history by mocking dependencies.
    test_main_predict: Tests the prediction functionality by mocking dependencies.
"""

import logging
import sys
import pytest
sys.path.append('/workspaces/BlueHorseshoe/src') # pylint: disable=wrong-import-position
from main import debug_test

@pytest.fixture
def setup_logging():
    """
    Sets up logging configuration for the application.

    This function configures the logging to write logs to a file named
    'blueHorseshoe_test.log' located in the '/workspaces/BlueHorseshoe/src/logs/'
    directory. The log file is overwritten each time the function is called.
    The logging level is set to DEBUG, and the log messages are formatted to
    include the timestamp, log level, and message.

    Yields:
        None

    Shuts down the logging system after the yield statement.
    """
    logging.basicConfig(filename='/workspaces/BlueHorseshoe/src/logs/blueHorseshoe_test.log', filemode='w',
                        level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    yield
    logging.shutdown()

def test_debug_test():
    """
    Test the debug_test function to ensure it returns None.

    This test verifies that the debug_test function behaves as expected
    by asserting that its return value is None.
    """
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
