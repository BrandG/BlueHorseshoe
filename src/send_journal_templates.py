#!/usr/bin/env python3
"""Send journal CSV templates via email."""
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")

TEMPLATES = [
    "journal_executed_trades.csv",
    "journal_skipped_signals.csv",
    "journal_capital_snapshots.csv",
]


def main():
    from bluehorseshoe.core.email_service import EmailService  # pylint: disable=import-outside-toplevel

    attachments = []
    for filename in TEMPLATES:
        path = os.path.join(LOGS_DIR, filename)
        if not os.path.exists(path):
            logger.error("Template not found: %s", path)
            return
        attachments.append((path, filename))

    body = (
        "Attached are 3 CSV templates for the Layer C trade journal:\n\n"
        "1. journal_executed_trades.csv - Core trade log (entries, exits, P&L, split-exit tracking)\n"
        "2. journal_skipped_signals.csv - BH picks you chose not to trade\n"
        "3. journal_capital_snapshots.csv - Daily/weekly equity state\n\n"
        "Fill in rows as you trade. The essential fields per trade are:\n"
        "  batch_date, symbol, strategy, entry/exit price, shares, dollar_pnl\n\n"
        "Everything else is nice-to-have for deeper analysis later."
    )

    guid = EmailService().send(
        subject="BlueHorseshoe - Trade Journal Templates",
        text_body=body,
        attachments=attachments,
    )
    if guid:
        logger.info("Journal templates sent (id=%s)", guid)
    else:
        logger.error("Journal templates not sent (email unconfigured or send failed)")


if __name__ == "__main__":
    main()
