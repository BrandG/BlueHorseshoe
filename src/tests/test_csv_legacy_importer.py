"""Tests for the CSV legacy importer."""
import pytest
from unittest.mock import MagicMock

from bluehorseshoe.trading.csv_legacy_importer import CSVLegacyImporter


@pytest.fixture
def mock_db():
    db = MagicMock()
    fills_col = MagicMock()
    positions_col = MagicMock()
    collections = {"trade_fills": fills_col, "trade_positions": positions_col}
    db.__getitem__ = MagicMock(side_effect=lambda name: collections[name])
    return db, fills_col, positions_col


class TestImportFile:
    def test_imports_entry_exit_row(self, mock_db, tmp_path):
        db, fills_col, positions_col = mock_db
        csv_file = tmp_path / "trades.csv"
        csv_file.write_text(
            "symbol,strategy,date,entry_price,exit_price,quantity,commission,stop_loss,target,result,pnl\n"
            "AAPL,baseline,2026-03-15,150.00,155.00,10,2.00,145.00,160.00,target,48.00\n"
        )

        importer = CSVLegacyImporter(database=db)
        result = importer.import_file(str(csv_file))

        assert result["fills_imported"] == 2  # entry + exit
        assert result["positions_created"] == 1
        assert result["errors"] == 0

        # Check entry fill
        entry_call = fills_col.update_one.call_args_list[0]
        entry_doc = entry_call[0][1]["$set"]
        assert entry_doc["side"] == "buy"
        assert entry_doc["price"] == 150.0

        # Check exit fill
        exit_call = fills_col.update_one.call_args_list[1]
        exit_doc = exit_call[0][1]["$set"]
        assert exit_doc["side"] == "sell"
        assert exit_doc["price"] == 155.0

        # Check position
        pos_call = positions_col.update_one.call_args
        pos_doc = pos_call[0][1]["$set"]
        assert pos_doc["symbol"] == "AAPL"
        assert pos_doc["status"] == "closed"
        assert pos_doc["total_pnl"] == 48.0
        assert len(pos_doc["legs"]) == 1

    def test_imports_raw_fill_row(self, mock_db, tmp_path):
        db, fills_col, positions_col = mock_db
        csv_file = tmp_path / "fills.csv"
        csv_file.write_text(
            "symbol,side,quantity,price,commission,exec_time,exec_id\n"
            "AAPL,buy,10,150.00,1.00,2026-03-22T14:30:00,RAW001\n"
        )

        importer = CSVLegacyImporter(database=db)
        result = importer.import_file(str(csv_file))

        assert result["fills_imported"] == 1
        assert result["positions_created"] == 0

    def test_close_reason_detection(self, mock_db, tmp_path):
        db, fills_col, positions_col = mock_db
        csv_file = tmp_path / "trades.csv"
        csv_file.write_text(
            "symbol,strategy,date,entry_price,exit_price,quantity,commission,stop_loss,target,result,pnl\n"
            "AAPL,baseline,2026-03-15,150.00,145.00,10,2.00,145.00,160.00,stop_loss,-52.00\n"
        )

        importer = CSVLegacyImporter(database=db)
        importer.import_file(str(csv_file))

        pos_doc = positions_col.update_one.call_args[0][1]["$set"]
        assert pos_doc["legs"][0]["close_reason"] == "stop_loss"

    def test_pnl_calculated_if_not_provided(self, mock_db, tmp_path):
        db, fills_col, positions_col = mock_db
        csv_file = tmp_path / "trades.csv"
        csv_file.write_text(
            "symbol,strategy,date,entry_price,exit_price,quantity,commission,stop_loss,target,result,pnl\n"
            "AAPL,baseline,2026-03-15,100.00,110.00,5,2.00,95.00,115.00,target,0\n"
        )

        importer = CSVLegacyImporter(database=db)
        importer.import_file(str(csv_file))

        pos_doc = positions_col.update_one.call_args[0][1]["$set"]
        # (110 - 100) * 5 - 2 = 48.0
        assert pos_doc["total_pnl"] == 48.0

    def test_file_not_found(self, mock_db):
        db, _, _ = mock_db
        importer = CSVLegacyImporter(database=db)
        result = importer.import_file("/nonexistent/file.csv")
        assert result["errors"] == 1

    def test_empty_symbol_skipped(self, mock_db, tmp_path):
        db, fills_col, positions_col = mock_db
        csv_file = tmp_path / "trades.csv"
        csv_file.write_text(
            "symbol,strategy,date,entry_price,exit_price,quantity,commission,stop_loss,target,result,pnl\n"
            ",baseline,2026-03-15,150.00,155.00,10,2.00,145.00,160.00,target,48.00\n"
        )

        importer = CSVLegacyImporter(database=db)
        result = importer.import_file(str(csv_file))
        assert result["errors"] == 1
        assert result["fills_imported"] == 0


class TestPreview:
    def test_preview_returns_rows(self, mock_db, tmp_path):
        db, _, _ = mock_db
        csv_file = tmp_path / "trades.csv"
        csv_file.write_text(
            "symbol,price\n"
            "AAPL,150.00\n"
            "MSFT,300.00\n"
            "GOOG,140.00\n"
        )

        importer = CSVLegacyImporter(database=db)
        rows = importer.preview(str(csv_file), limit=2)
        assert len(rows) == 2
        assert rows[0]["symbol"] == "AAPL"

    def test_preview_does_not_write(self, mock_db, tmp_path):
        db, fills_col, positions_col = mock_db
        csv_file = tmp_path / "trades.csv"
        csv_file.write_text("symbol,price\nAAPL,150.00\n")

        importer = CSVLegacyImporter(database=db)
        importer.preview(str(csv_file))

        fills_col.update_one.assert_not_called()
        positions_col.update_one.assert_not_called()

    def test_preview_file_not_found(self, mock_db):
        db, _, _ = mock_db
        importer = CSVLegacyImporter(database=db)
        rows = importer.preview("/nonexistent.csv")
        assert rows == []
