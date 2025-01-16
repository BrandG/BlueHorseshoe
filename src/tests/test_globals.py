"""
Module: test_globals

This module contains unit tests for the functions and classes defined in the globals module.
The tests are written using the pytest framework and include fixtures, mocks, and assertions
to verify the correct behavior of the functions and classes.

Functions:
    setup_invalid_symbols_file(tmp_path): Sets up a temporary file with invalid stock symbols for testing purposes.
    test_load_invalid_symbols(): Tests the load_invalid_symbols function.
    test_load_invalid_symbols_file_not_found(): Tests the load_invalid_symbols function when the symbols file is not found.
    test_get_mongo_client(mock_mongo_client): Tests the get_mongo_client function to ensure it returns a non-None client instance.
    test_get_symbol_list_from_net(mock_get): Tests the get_symbol_list_from_net function to ensure it correctly parses 
        the symbol list from the network response.
    test_get_symbol_list_from_file(): Tests the get_symbol_list_from_file function.
    test_get_symbol_list(mock_get_symbol_list_from_net): Tests the get_symbol_list function.
    test_graph(mock_datetime): Tests the graph function from globals module.
    test_report_singleton_write(): Tests the write functionality of ReportSingleton.
    test_report_singleton_context_manager(): Tests the ReportSingleton class context manager functionality.
"""

from datetime import datetime
import json
import os
from unittest.mock import patch, MagicMock, mock_open
import sys
import pytest

sys.path.append('/workspaces/BlueHorseshoe/src')
from globals import (  # pylint: disable=wrong-import-position
    load_invalid_symbols,
    get_mongo_client,
    graph,
    get_symbol_list_from_net,
    get_symbol_list_from_file,
    get_symbol_list,
    GlobalData,
    GraphData,
    ReportSingleton
)

# Mock data for the symbol list as a JSON string
mock_symbol_list = json.dumps([{"symbol": "AAPL", "name": "Apple Inc"}, {"symbol": "GOOGL", "name": "Alphabet Inc"}])

@pytest.fixture
def setup_invalid_symbols_file(tmp_path):
    """
    Sets up a temporary file with invalid stock symbols for testing purposes.

    This function creates a file named 'invalid_symbols.txt' in the provided
    temporary directory and writes a list of invalid stock symbols to it.
    It also temporarily sets the GlobalData.base_path to the temporary directory
    path for the duration of the test.

    Args:
        tmp_path (pathlib.Path): A temporary directory path provided by pytest.

    Yields:
        None: This function is a pytest fixture and does not return a value.
    """
    invalid_symbols_file = tmp_path / "invalid_symbols.txt"
    invalid_symbols_file.write_text("AAPL\nGOOGL\nMSFT\n")
    GlobalData.base_path = str(tmp_path)
    yield
    GlobalData.base_path = '/workspaces/BlueHorseshoe/src/historical_data/'

def test_load_invalid_symbols():
    """
    Test the load_invalid_symbols function.

    This test ensures that the load_invalid_symbols function correctly loads
    invalid symbols into the GlobalData.invalid_symbols list.

    Asserts:
        GlobalData.invalid_symbols is set to ["AAPL", "GOOGL", "MSFT"].
    """
    load_invalid_symbols()
    assert len(GlobalData.invalid_symbols) > 0

def test_load_invalid_symbols_file_not_found():
    """
    Test case for load_invalid_symbols function when the symbols file is not found.

    This test sets the GlobalData.base_path to an invalid path and calls the 
    load_invalid_symbols function. It asserts that the GlobalData.invalid_symbols 
    list remains empty, indicating that the function handles the file not found 
    scenario correctly.
    """
    GlobalData.base_path = "/invalid/path"
    load_invalid_symbols()
    assert not GlobalData.invalid_symbols

@patch("pymongo.MongoClient")
def test_get_mongo_client(mock_mongo_client):
    """
    Test the get_mongo_client function to ensure it returns a non-None client instance
    and that the mock_mongo_client is called exactly once.

    Args:
        mock_mongo_client (MagicMock): A mock object for the MongoDB client.

    Asserts:
        The client returned by get_mongo_client is not None.
        The mock_mongo_client is called exactly once.
    """
    mock_client_instance = MagicMock()
    mock_mongo_client.return_value = mock_client_instance
    client = get_mongo_client()
    assert client is not None
    mock_mongo_client.assert_called_once()

@patch("requests.get")
def test_get_symbol_list_from_net(mock_get):
    """
    Test the get_symbol_list_from_net function to ensure it correctly parses
    the symbol list from the network response.

    Args:
        mock_get (MagicMock): Mock object for the requests.get function.

    Mocks:
        - Mock the network response to return a predefined CSV string.
        - Mock the raise_for_status method to simulate a successful request.

    Asserts:
        - The returned symbol list matches the expected list of dictionaries
          containing symbol and name.
    """
    mock_response = MagicMock()
    mock_response.text = "symbol,name,status,exchange,assetType\nAAPL,Apple Inc,Active,NYSE,Stock\nGOOGL,Alphabet Inc,Active,NASDAQ,Stock\n"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    symbols = get_symbol_list_from_net()
    assert symbols == [{"symbol": "AAPL", "name": "Apple Inc"}, {"symbol": "GOOGL", "name": "Alphabet Inc"}]

@patch("builtins.open", new_callable=mock_open, read_data=mock_symbol_list)
@patch("os.path.exists", return_value=True)
def test_get_symbol_list_from_file( mock_open, mock_exists): # pylint: disable=unused-argument, redefined-outer-name
    """
    Test the get_symbol_list_from_file function.

    This test checks if the get_symbol_list_from_file function correctly
    retrieves a list of symbols from a file. It uses a mock file to simulate
    the file input and asserts that the returned list of symbols matches
    the expected output.

    Asserts:
        The returned list of symbols is equal to the expected list of symbols.
    """
    symbols = get_symbol_list_from_file()
    assert len(symbols) > 0
    assert symbols == [{"symbol": "AAPL", "name": "Apple Inc"}, {"symbol": "GOOGL", "name": "Alphabet Inc"}]

@patch("globals.get_symbol_list_from_net")
@patch("globals.get_symbol_list_from_file")
def test_get_symbol_list(mock_get_symbol_list_from_file, mock_get_symbol_list_from_net):
    """
    Test the get_symbol_list function.

    This test mocks the behavior of the get_symbol_list function by simulating
    the return value of the mock_get_symbol_list_from_net function. It verifies
    that the get_symbol_list function returns the expected list of symbols.

    Args:
        mock_open (Mock): Mock object for the open function.
        mock_get_symbol_list_from_file (Mock): Mock object for the get_symbol_list_from_file function.
        mock_get_symbol_list_from_net (Mock): Mock object for the get_symbol_list_from_net function.

    Asserts:
        The returned list of symbols matches the expected list.
    """
    mock_get_symbol_list_from_file.return_value = [{"symbol": "AAPL", "name": "Apple Inc"}]
    mock_get_symbol_list_from_net.return_value = [{"symbol": "AAPL", "name": "Apple Inc"}]
    symbols = get_symbol_list()
    assert len(symbols) > 0
    assert symbols == [{"symbol": "AAPL", "name": "Apple Inc"}]

@patch("datetime.datetime")
def test_graph(mock_datetime):
    """Test the graph function from globals module.

    This test verifies that the graph function correctly generates and saves a plot file
    using the provided GraphData configuration, and then properly cleans up by removing
    the generated file.

    Args:
        mock_datetime: A pytest fixture that mocks the datetime object for consistent testing

    Test Steps:
        1. Mocks the datetime.now() to return a fixed date
        2. Creates a GraphData object with test data including curves, lines and points
        3. Calls graph function to generate plot
        4. Verifies file was created
        5. Removes file
        6. Verifies file was removed

    Returns:
        None

    Raises:
        AssertionError: If the file is not created or not properly removed
    """
    mock_datetime.now.return_value = datetime(2021, 1, 1)
    graph_data = GraphData(
        labels={'x_label':'X Axis', 'y_label':'Y Axis', 'title':"Test Graph"},
        curves=[{"curve": [1, 2, 3], "color": "b", "label": "Curve 1"}],
        lines=[{"y": 2, "color": "r", "linestyle": "--", "label": "Line 1"}],
        points=[{"x": 1, "y": 2, "color": "g"}],
        x_values=["A", "B", "C"]
    )

    filepath = graph(graph_data)
    assert os.path.exists(filepath)
    os.remove(filepath)
    assert not os.path.exists(filepath)


def test_report_singleton_write():
    """Test the write functionality of ReportSingleton.

    This test verifies that the ReportSingleton class correctly writes log entries to a file.
    It checks if a test log message can be written to the log file and confirms its presence
    in the file contents after writing.

    Returns:
        None

    Raises:
        AssertionError: If the test log entry is not found in the log file contents
    """
    report = ReportSingleton()
    report.write("Test log entry")
    report.close()
    with open(report.log_path, 'r', encoding='utf-8') as file:
        content = file.read()
    assert "Test log entry" in content

def test_report_singleton_context_manager():
    """Tests the ReportSingleton class context manager functionality.

    This test verifies that:
    1. The ReportSingleton can be used as a context manager
    2. Log entries written within the context are properly saved to the log file
    3. The log file can be read after the context is exited

    Returns:
        None

    Raises:
        AssertionError: If the written test log entry is not found in the log file
    """
    with ReportSingleton() as report:
        report.write("Test log entry in context manager")
    with open(report.log_path, 'r', encoding='utf-8') as file:
        content = file.read()
    assert "Test log entry in context manager" in content
