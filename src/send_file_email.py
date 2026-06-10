#!/usr/bin/env python3
"""
Email any local file(s) to the configured recipient (EMAIL_RECIPIENT).

Usage:
    ./run.sh python src/send_file_email.py PATH [PATH ...] [--subject SUBJECT] [--body TEXT]

Examples:
    ./run.sh python src/send_file_email.py src/logs/backtest_log.csv
    ./run.sh python src/send_file_email.py src/graphs/swing_tracker.html --subject "Swing tracker"
    ./run.sh python src/send_file_email.py a.csv b.csv --subject "Two files" --body "See attached."
"""
import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Email local file(s) as attachments.")
    parser.add_argument("paths", nargs="+", help="File(s) to send")
    parser.add_argument("--subject", default=None, help="Email subject (default derives from filename)")
    parser.add_argument("--body", default=None, help="Plain-text body (default derives from filenames)")
    args = parser.parse_args()

    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        for p in missing:
            logger.error(f"File not found: {p}")
        sys.exit(1)

    from bluehorseshoe.core.email_service import EmailService
    service = EmailService()

    if len(args.paths) == 1:
        success = service.send_file(args.paths[0], subject=args.subject, body=args.body)
    else:
        names = ", ".join(os.path.basename(p) for p in args.paths)
        success = service.send(
            args.subject or f"BlueHorseshoe Files - {names}",
            text_body=args.body or f"Attached: {names}",
            attachments=list(args.paths),
        )

    if success:
        logger.info("Email sent successfully.")
    else:
        logger.error("Email sending failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
