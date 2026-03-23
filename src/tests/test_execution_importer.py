"""Tests for the execution importer."""
import os
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from bluehorseshoe.trading.execution_importer import ExecutionImporter


@pytest.fixture
def mock_db():
    db = MagicMock()
    collection = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db


@pytest.fixture
def mock_ibkr():
    return MagicMock()


@pytest.fixture
def importer(mock_db, mock_ibkr):
    return ExecutionImporter(database=mock_db, ibkr_client=mock_ibkr)


class TestImportFromIBKR:
    def test_imports_executions(self, importer, mock_ibkr, mock_db):
        mock_ibkr.get_executions.return_value = [
            {
                "exec_id": "E001",
                "symbol": "AAPL",
                "side": "bot",
                "quantity": 10,
                "price": 150.0,
                "commission": 1.0,
                "exec_time": datetime(2026, 3, 22, 14, 30),
                "order_id": 123,
            },
        ]
        count = importer.import_from_ibkr()
        assert count == 1

        collection = mock_db.__getitem__.return_value
        call_args = collection.update_one.call_args
        doc = call_args[0][1]["$set"]
        assert doc["fill_id"] == "fill_E001"
        assert doc["symbol"] == "AAPL"
        assert doc["side"] == "buy"  # "bot" normalized to "buy"
        assert doc["source"] == "ibkr"
        assert doc["broker_order_id"] == 123

    def test_deduplicates_by_fill_id(self, importer, mock_ibkr, mock_db):
        mock_ibkr.get_executions.return_value = [
            {"exec_id": "E001", "symbol": "AAPL", "side": "bot", "quantity": 10,
             "price": 150.0, "commission": 1.0, "exec_time": None, "order_id": 1},
        ]
        # Import twice
        importer.import_from_ibkr()
        importer.import_from_ibkr()

        collection = mock_db.__getitem__.return_value
        # Both calls should use upsert with same fill_id filter
        for call_args in collection.update_one.call_args_list:
            assert call_args[0][0] == {"fill_id": "fill_E001"}
            assert call_args[1].get("upsert") is True or call_args[0][2] is True

    def test_no_ibkr_client(self, mock_db):
        importer = ExecutionImporter(database=mock_db, ibkr_client=None)
        count = importer.import_from_ibkr()
        assert count == 0

    def test_empty_executions(self, importer, mock_ibkr):
        mock_ibkr.get_executions.return_value = []
        count = importer.import_from_ibkr()
        assert count == 0

    def test_sell_side_normalized(self, importer, mock_ibkr, mock_db):
        mock_ibkr.get_executions.return_value = [
            {"exec_id": "E002", "symbol": "AAPL", "side": "sld", "quantity": 5,
             "price": 155.0, "commission": 0.5, "exec_time": None, "order_id": 2},
        ]
        importer.import_from_ibkr()
        collection = mock_db.__getitem__.return_value
        doc = collection.update_one.call_args[0][1]["$set"]
        assert doc["side"] == "sell"


class TestImportFromCSV:
    def test_imports_csv(self, importer, mock_db, tmp_path):
        csv_file = tmp_path / "fills.csv"
        csv_file.write_text(
            "symbol,side,quantity,price,commission,exec_time,exec_id\n"
            "AAPL,buy,10,150.00,1.00,2026-03-22T14:30:00,CSV001\n"
            "MSFT,sell,5,300.00,0.50,,CSV002\n"
        )
        count = importer.import_from_csv(str(csv_file))
        assert count == 2

        collection = mock_db.__getitem__.return_value
        assert collection.update_one.call_count == 2

    def test_generates_exec_id_if_missing(self, importer, mock_db, tmp_path):
        csv_file = tmp_path / "fills.csv"
        csv_file.write_text(
            "symbol,side,quantity,price,commission,exec_time,exec_id\n"
            "AAPL,buy,10,150.00,1.00,,\n"
        )
        importer.import_from_csv(str(csv_file))

        collection = mock_db.__getitem__.return_value
        doc = collection.update_one.call_args[0][1]["$set"]
        assert doc["fill_id"] == "fill_csv_0"
        assert doc["exec_id"] == "csv_0"

    def test_file_not_found(self, importer):
        count = importer.import_from_csv("/nonexistent/file.csv")
        assert count == 0

    def test_uppercase_symbol(self, importer, mock_db, tmp_path):
        csv_file = tmp_path / "fills.csv"
        csv_file.write_text(
            "symbol,side,quantity,price,commission,exec_time,exec_id\n"
            "aapl,buy,10,150.00,0,,\n"
        )
        importer.import_from_csv(str(csv_file))
        collection = mock_db.__getitem__.return_value
        doc = collection.update_one.call_args[0][1]["$set"]
        assert doc["symbol"] == "AAPL"

    def test_custom_source_label(self, importer, mock_db, tmp_path):
        csv_file = tmp_path / "fills.csv"
        csv_file.write_text(
            "symbol,side,quantity,price,commission,exec_time,exec_id\n"
            "AAPL,buy,10,150.00,0,,\n"
        )
        importer.import_from_csv(str(csv_file), source="thinkorswim")
        collection = mock_db.__getitem__.return_value
        doc = collection.update_one.call_args[0][1]["$set"]
        assert doc["source"] == "thinkorswim"


class TestGetFills:
    def test_get_fills_no_filter(self, importer, mock_db):
        collection = mock_db.__getitem__.return_value
        collection.find.return_value.sort.return_value = [
            {"fill_id": "f1"}, {"fill_id": "f2"},
        ]
        result = importer.get_fills()
        assert len(result) == 2

    def test_get_fills_with_symbol(self, importer, mock_db):
        collection = mock_db.__getitem__.return_value
        collection.find.return_value.sort.return_value = []
        importer.get_fills(symbol="AAPL")
        call_args = collection.find.call_args
        assert call_args[0][0]["symbol"] == "AAPL"

    def test_get_unreconciled(self, importer, mock_db):
        collection = mock_db.__getitem__.return_value
        collection.find.return_value.sort.return_value = [{"fill_id": "f1"}]
        result = importer.get_unreconciled_fills()
        call_args = collection.find.call_args
        assert call_args[0][0] == {"idea_id": None}
