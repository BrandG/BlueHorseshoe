"""
CSV legacy importer — imports historical trades from spreadsheets
into trade_fills and optionally synthesizes trade_positions.
"""
import csv
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pymongo.database import Database

from bluehorseshoe.trading.trade_models import make_idea_id, make_position_id

logger = logging.getLogger(__name__)

# Default column mapping: CSV header → internal field
DEFAULT_COLUMN_MAP = {
    "symbol": "symbol",
    "side": "side",
    "quantity": "quantity",
    "price": "price",
    "commission": "commission",
    "exec_time": "exec_time",
    "exec_id": "exec_id",
    "strategy": "strategy",
    "date": "date",
    "entry_price": "entry_price",
    "exit_price": "exit_price",
    "stop_loss": "stop_loss",
    "target": "target",
    "result": "result",
    "pnl": "pnl",
}


class CSVLegacyImporter:
    """
    Import historical trades from CSV into trade_fills and trade_positions.

    Handles flexible column mapping for different CSV formats.
    """

    def __init__(self, database: Database):
        self._db = database
        self._fills = database["trade_fills"]
        self._positions = database["trade_positions"]

    def import_file(
        self,
        csv_path: str,
        column_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, int]:
        """
        Import a CSV file of historical trades.

        If the CSV has entry/exit info per row (not raw fills), each row is
        converted into a pair of fills (buy entry + sell exit) and a position.

        Args:
            csv_path: Path to the CSV file.
            column_map: Optional custom column mapping (csv_header -> internal_field).

        Returns:
            {"fills_imported": N, "positions_created": M, "errors": E}
        """
        cmap = dict(DEFAULT_COLUMN_MAP)
        if column_map:
            cmap.update(column_map)

        # Build reverse map: internal_field -> csv_header
        reverse_map = {v: k for k, v in cmap.items()}

        stats = {"fills_imported": 0, "positions_created": 0, "errors": 0}

        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = set(reader.fieldnames or [])

                for idx, row in enumerate(reader):
                    try:
                        self._import_row(row, idx, headers, reverse_map, stats)
                    except Exception as e:
                        logger.error("Error importing row %d: %s", idx, e)
                        stats["errors"] += 1

        except FileNotFoundError:
            logger.error("CSV file not found: %s", csv_path)
            stats["errors"] += 1
        except Exception as e:
            logger.error("Error reading CSV file %s: %s", csv_path, e)
            stats["errors"] += 1

        logger.info(
            "Legacy import from %s: %d fills, %d positions, %d errors",
            csv_path, stats["fills_imported"], stats["positions_created"], stats["errors"],
        )
        return stats

    def _import_row(
        self,
        row: dict,
        idx: int,
        headers: set,
        reverse_map: Dict[str, str],
        stats: Dict[str, int],
    ) -> None:
        """Import a single CSV row."""

        def get_field(internal_name: str, default: str = "") -> str:
            csv_header = reverse_map.get(internal_name, internal_name)
            return row.get(csv_header, row.get(internal_name, default)).strip()

        symbol = get_field("symbol").upper()
        if not symbol:
            stats["errors"] += 1
            return

        strategy = get_field("strategy", "baseline")
        date = get_field("date", "")

        entry_price = float(get_field("entry_price", "0") or "0")
        exit_price = float(get_field("exit_price", "0") or "0")

        # If we have entry+exit, create paired fills and a position
        if entry_price > 0 and exit_price > 0:
            quantity = int(float(get_field("quantity", "1") or "1"))
            commission = float(get_field("commission", "0") or "0")
            stop_loss = float(get_field("stop_loss", "0") or "0")
            target = float(get_field("target", "0") or "0")
            pnl = float(get_field("pnl", "0") or "0")
            result = get_field("result", "")

            exec_time = None
            if date:
                try:
                    exec_time = datetime.fromisoformat(date)
                except ValueError:
                    try:
                        exec_time = datetime.strptime(date, "%Y-%m-%d")
                    except ValueError:
                        pass

            # Create entry fill
            entry_fill_id = f"fill_legacy_{idx}_entry"
            entry_doc = {
                "fill_id": entry_fill_id,
                "symbol": symbol,
                "side": "buy",
                "quantity": quantity,
                "price": entry_price,
                "commission": commission / 2,  # Split commission
                "exec_time": exec_time,
                "exec_id": f"legacy_{idx}_entry",
                "order_ref": None,
                "idea_id": None,
                "source": "legacy_csv",
                "created_at": datetime.now(timezone.utc),
            }
            self._fills.update_one(
                {"fill_id": entry_fill_id}, {"$set": entry_doc}, upsert=True,
            )
            stats["fills_imported"] += 1

            # Create exit fill
            exit_fill_id = f"fill_legacy_{idx}_exit"
            exit_doc = {
                "fill_id": exit_fill_id,
                "symbol": symbol,
                "side": "sell",
                "quantity": quantity,
                "price": exit_price,
                "commission": commission / 2,
                "exec_time": exec_time,
                "exec_id": f"legacy_{idx}_exit",
                "order_ref": None,
                "idea_id": None,
                "source": "legacy_csv",
                "created_at": datetime.now(timezone.utc),
            }
            self._fills.update_one(
                {"fill_id": exit_fill_id}, {"$set": exit_doc}, upsert=True,
            )
            stats["fills_imported"] += 1

            # Create position
            idea_id = make_idea_id(date, symbol, strategy) if date else f"legacy_{idx}"
            position_id = make_position_id(idea_id)

            # Determine close reason
            close_reason = "manual"
            if result:
                result_lower = result.lower()
                if "target" in result_lower or "tp" in result_lower:
                    close_reason = "take_profit_t2"
                elif "stop" in result_lower or "sl" in result_lower:
                    close_reason = "stop_loss"
                elif "timeout" in result_lower:
                    close_reason = "timeout"

            # Calculate PnL if not provided
            if pnl == 0 and entry_price > 0 and exit_price > 0:
                pnl = (exit_price - entry_price) * quantity - commission

            pos_doc = {
                "position_id": position_id,
                "idea_id": idea_id,
                "symbol": symbol,
                "strategy": strategy,
                "status": "closed",
                "planned_entry": entry_price,
                "planned_stop": stop_loss,
                "planned_target_t1": 0.0,
                "planned_target_t2": target,
                "actual_entry": entry_price,
                "legs": [{
                    "leg": "T2",
                    "quantity": quantity,
                    "entry_fill_id": entry_fill_id,
                    "exit_fill_id": exit_fill_id,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "close_reason": close_reason,
                    "pnl": round(pnl, 2),
                    "r_multiple": 0.0,
                    "hold_days": 0,
                }],
                "total_quantity": quantity,
                "total_pnl": round(pnl, 2),
                "total_commission": commission,
                "entry_slippage": 0.0,
                "opened_at": exec_time,
                "closed_at": exec_time,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            self._positions.update_one(
                {"position_id": position_id}, {"$set": pos_doc}, upsert=True,
            )
            stats["positions_created"] += 1

        else:
            # Raw fill row: just import as a single fill
            fill_id = f"fill_legacy_{idx}"
            side = get_field("side", "buy").lower()
            quantity = int(float(get_field("quantity", "0") or "0"))
            price = float(get_field("price", "0") or "0")
            commission = float(get_field("commission", "0") or "0")

            exec_time = None
            exec_time_str = get_field("exec_time", "")
            if exec_time_str:
                try:
                    exec_time = datetime.fromisoformat(exec_time_str)
                except ValueError:
                    pass

            doc = {
                "fill_id": fill_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "commission": commission,
                "exec_time": exec_time,
                "exec_id": get_field("exec_id", f"legacy_{idx}"),
                "order_ref": None,
                "idea_id": None,
                "source": "legacy_csv",
                "created_at": datetime.now(timezone.utc),
            }
            self._fills.update_one(
                {"fill_id": fill_id}, {"$set": doc}, upsert=True,
            )
            stats["fills_imported"] += 1

    def preview(self, csv_path: str, limit: int = 5) -> List[dict]:
        """Preview first N rows without importing."""
        rows = []
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if i >= limit:
                        break
                    rows.append(dict(row))
        except Exception as e:
            logger.error("Error previewing CSV: %s", e)
        return rows
