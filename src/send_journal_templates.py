#!/usr/bin/env python3
"""Send journal CSV templates via email."""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")

TEMPLATES = [
    "journal_executed_trades.csv",
    "journal_skipped_signals.csv",
    "journal_capital_snapshots.csv",
]


def main():
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT")

    if not all([smtp_user, smtp_password, recipient]):
        logger.error("Missing SMTP_USER, SMTP_PASSWORD, or EMAIL_RECIPIENT")
        return

    msg = MIMEMultipart()
    msg["From"] = os.environ.get("EMAIL_SENDER", smtp_user)
    msg["To"] = recipient
    msg["Subject"] = "BlueHorseshoe - Trade Journal Templates"

    body = (
        "Attached are 3 CSV templates for the Layer C trade journal:\n\n"
        "1. journal_executed_trades.csv - Core trade log (entries, exits, P&L, split-exit tracking)\n"
        "2. journal_skipped_signals.csv - BH picks you chose not to trade\n"
        "3. journal_capital_snapshots.csv - Daily/weekly equity state\n\n"
        "Fill in rows as you trade. The essential fields per trade are:\n"
        "  batch_date, symbol, strategy, entry/exit price, shares, dollar_pnl\n\n"
        "Everything else is nice-to-have for deeper analysis later."
    )
    msg.attach(MIMEText(body, "plain"))

    for filename in TEMPLATES:
        path = os.path.join(LOGS_DIR, filename)
        if not os.path.exists(path):
            logger.error(f"Template not found: {path}")
            return
        with open(path, "rb") as f:
            part = MIMEApplication(f.read(), Name=filename)
            part["Content-Disposition"] = f'attachment; filename="{filename}"'
            msg.attach(part)
        logger.info(f"Attached {filename}")

    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    with smtplib.SMTP(smtp_server, smtp_port, timeout=120) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)

    logger.info(f"Journal templates sent to {recipient}")


if __name__ == "__main__":
    main()
