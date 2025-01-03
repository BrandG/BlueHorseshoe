from datetime import datetime
import pytest
import os
from unittest.mock import patch, mock_open, MagicMock

from src.globals import (
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

@pytest.fixture
def setup_invalid_symbols_file(tmp_path):
    invalid_symbols_file = tmp_path / "invalid_symbols.txt"
    invalid_symbols_file.write_text("AAPL\nGOOGL\nMSFT\n")
    GlobalData.base_path = str(tmp_path)
    yield
    GlobalData.base_path = '/workspaces/BlueHorseshoe/src/historical_data/'

def test_load_invalid_symbols(setup_invalid_symbols_file):
    load_invalid_symbols()
    assert GlobalData.invalid_symbols == ["AAPL", "GOOGL", "MSFT"]

def test_load_invalid_symbols_file_not_found():
    GlobalData.base_path = "/invalid/path"
    load_invalid_symbols()
    assert GlobalData.invalid_symbols == []

@patch("pymongo.MongoClient")
def test_get_mongo_client(mock_mongo_client):
    mock_client_instance = MagicMock()
    mock_mongo_client.return_value = mock_client_instance
    client = get_mongo_client()
    assert client is not None
    mock_mongo_client.assert_called_once()

@patch("requests.get")
def test_get_symbol_list_from_net(mock_get):
    mock_response = MagicMock()
    mock_response.text = "symbol,name,status,exchange,assetType\nAAPL,Apple Inc,Active,NYSE,Stock\nGOOGL,Alphabet Inc,Active,NASDAQ,Stock\n"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    symbols = get_symbol_list_from_net()
    assert symbols == [{"symbol": "AAPL", "name": "Apple Inc"}, {"symbol": "GOOGL", "name": "Alphabet Inc"}]

@patch("builtins.open", new_callable=mock_open, read_data='[{"symbol": "AAPL", "name": "Apple Inc"}]')
def test_get_symbol_list_from_file(mock_file):
    symbols = get_symbol_list_from_file()
    assert symbols == [{"symbol": "AAPL", "name": "Apple Inc"}]

@patch("src.globals.get_symbol_list_from_net")
@patch("src.globals.get_symbol_list_from_file", return_value=None)
@patch("builtins.open", new_callable=mock_open)
def test_get_symbol_list(mock_open, mock_get_symbol_list_from_file, mock_get_symbol_list_from_net):
    mock_get_symbol_list_from_net.return_value = [{"symbol": "AAPL", "name": "Apple Inc"}]
    symbols = get_symbol_list()
    assert symbols == [{"symbol": "AAPL", "name": "Apple Inc"}]

@patch("datetime.datetime")
def test_graph(mock_datetime):
    mock_datetime.now.return_value = datetime(2021, 1, 1)
    graph_data = GraphData(
        x_label="X Axis",
        y_label="Y Axis",
        title="Test Graph",
        curves=[{"curve": [1, 2, 3], "color": "b", "label": "Curve 1"}],
        lines=[{"y": 2, "color": "r", "linestyle": "--", "label": "Line 1"}],
        points=[{"x": 1, "y": 2, "color": "g"}],
        x_values=["A", "B", "C"]
    )
    graph(graph_data)
    filepath = f'/workspaces/BlueHorseshoe/src/graphs/Test Graph_{int(datetime.now().timestamp())}.png'
    assert os.path.exists(filepath)
    os.remove(filepath)
    assert not os.path.exists(filepath)


def test_report_singleton_write():
    report = ReportSingleton()
    report.write("Test log entry")
    report.close()
    with open(report._log_path, 'r', encoding='utf-8') as file:
        content = file.read()
    assert "Test log entry" in content

def test_report_singleton_context_manager():
    with ReportSingleton() as report:
        report.write("Test log entry in context manager")
    with open(report._log_path, 'r', encoding='utf-8') as file:
        content = file.read()
    assert "Test log entry in context manager" in content