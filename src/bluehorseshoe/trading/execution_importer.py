"""
Execution importer — pulls real fills from IBKR or CSV into trade_fills.
"""
import csv
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pymongo.database import Database

from bluehorseshoe.data.ibkr_client import IBKRClient

logger = logging.getLogger(__name__)

# Map IBKR side codes to normalized values
IBKR_SIDE_MAP = {"bot": "buy", "sld": "sell", "buy": "buy", "sell": "sell"}


class ExecutionImporter:
    """Imports trade fills from IBKR or CSV into the trade_fills collection."""

    def __init__(
        self,
        database: Database,
        ibkr_client: Optional[IBKRClient] = None,
    ):
        self._db = database
        self._ibkr = ibkr_client
        self._collection = database["trade_fills"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            self._collection.create_index(
                [("fill_id", 1)], unique=True, name="ux_fill_id"
            )
            self._collection.create_index(
                [("order_ref", 1)], name="ix_order_ref"
            )
            self._collection.create_index(
                [("symbol", 1), ("exec_time", 1)], name="ix_symbol_time"
            )
        except Exception as e:
            logger.warning("Failed to create trade_fills indexes: %s", e)

    def import_from_ibkr(self, since: Optional[datetime] = None) -> int:
        """
        Pull executions from IBKR Gateway and store as trade_fills.

        Args:
            since: Only import executions after this time. Defaults to last 24h.

        Returns:
            Number of new fills imported.
        """
        if self._ibkr is None:
            logger.error("No IBKR client available for execution import")
            return 0

        executions = self._ibkr.get_executions(since=since)
        if not executions:
            logger.info("No executions found from IBKR")
            return 0

        imported = 0
        for ex in executions:
            fill_id = f"fill_{ex['exec_id']}"
            side = IBKR_SIDE_MAP.get(ex.get("side", "").lower(), ex.get("side", "unknown"))

            doc = {
                "fill_id": fill_id,
                "symbol": ex["symbol"],
                "side": side,
                "quantity": ex["quantity"],
                "price": ex["price"],
                "commission": ex.get("commission", 0.0),
                "exec_time": ex.get("exec_time"),
                "exec_id": ex["exec_id"],
                "order_ref": None,  # Set during reconciliation
                "idea_id": None,    # Set during reconciliation
                "source": "ibkr",
                "broker_order_id": ex.get("order_id"),
                "created_at": datetime.now(timezone.utc),
            }

            try:
                self._collection.update_one(
                    {"fill_id": fill_id},
                    {"$set": doc},
                    upsert=True,
                )
                imported += 1
            except Exception as e:
                logger.error("Failed to import fill %s: %s", fill_id, e)

        logger.info("Imported %d fills from IBKR", imported)
        return imported

    def import_from_csv(self, csv_path: str, source: str = "csv") -> int:
        """
        Import fills from a CSV file.

        Expected columns: symbol, side, quantity, price, commission, exec_time, exec_id
        (exec_id is optional — generated from row index if missing)

        Args:
            csv_path: Path to the CSV file.
            source: Source label (e.g., "csv", "ibkr_export").

        Returns:
            Number of new fills imported.
        """
        imported = 0
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    exec_id = row.get("exec_id", "").strip() or f"csv_{idx}"
                    fill_id = f"fill_{exec_id}"

                    exec_time = None
                    if row.get("exec_time"):
                        try:
                            exec_time = datetime.fromisoformat(row["exec_time"].strip())
                        except ValueError:
                            pass

                    doc = {
                        "fill_id": fill_id,
                        "symbol": row.get("symbol", "").strip().upper(),
                        "side": row.get("side", "buy").strip().lower(),
                        "quantity": int(float(row.get("quantity", 0))),
                        "price": float(row.get("price", 0)),
                        "commission": float(row.get("commission", 0)),
                        "exec_time": exec_time,
                        "exec_id": exec_id,
                        "order_ref": None,
                        "idea_id": None,
                        "source": source,
                        "created_at": datetime.now(timezone.utc),
                    }

                    try:
                        self._collection.update_one(
                            {"fill_id": fill_id},
                            {"$set": doc},
                            upsert=True,
                        )
                        imported += 1
                    except Exception as e:
                        logger.error("Failed to import CSV fill row %d: %s", idx, e)

        except FileNotFoundError:
            logger.error("CSV file not found: %s", csv_path)
        except Exception as e:
            logger.error("Error reading CSV file %s: %s", csv_path, e)

        logger.info("Imported %d fills from CSV: %s", imported, csv_path)
        return imported

    def get_fills(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> List[dict]:
        """Query fills with optional filters."""
        query: Dict = {}
        if symbol:
            query["symbol"] = symbol
        if since:
            query["exec_time"] = {"$gte": since}
        return list(self._collection.find(query, {"_id": 0}).sort("exec_time", 1))

    def get_unreconciled_fills(self) -> List[dict]:
        """Get fills not yet linked to a position (idea_id is None)."""
        return list(
            self._collection.find(
                {"idea_id": None},
                {"_id": 0},
            ).sort("exec_time", 1)
        )
