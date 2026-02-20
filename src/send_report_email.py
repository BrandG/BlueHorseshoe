#!/usr/bin/env python3
"""
Send the latest (or a specific date's) prediction report via email.

Usage:
    python src/send_report_email.py              # sends latest report
    python src/send_report_email.py 2026-02-17   # sends report for specific date
"""
import sys
import os
import glob
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")


def find_report(date: str = None) -> str | None:
    """Find report path by date, or the most recent report if no date given."""
    if date:
        path = os.path.join(LOGS_DIR, f"report_{date}.html")
        return path if os.path.exists(path) else None

    # Find most recent report (exclude _email variants)
    pattern = os.path.join(LOGS_DIR, "report_*.html")
    files = [f for f in glob.glob(pattern) if "_email" not in f and "_arcade" not in f]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else None
    report_path = find_report(date)

    if not report_path:
        label = date or "latest"
        logger.error(f"No report found for '{label}' in {LOGS_DIR}")
        sys.exit(1)

    logger.info(f"Sending report: {report_path}")

    from bluehorseshoe.core.email_service import EmailService
    service = EmailService()
    success = service.send_report(report_path)

    if success:
        logger.info("Email sent successfully.")
    else:
        logger.error("Email sending failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
