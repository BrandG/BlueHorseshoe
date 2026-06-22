#!/usr/bin/env python3
"""
Send a plain-text reminder email pointing at a handoff doc in this repo.

Reads SMTP config from .env (same keys as bluehorseshoe.core.email_service).
Intended to be invoked from cron for one-shot future reminders. Subject and
doc path are CLI args so this script is reusable for any reminder, not just
the contrarian thread.

Example crontab line:
  0 13 29 5 *  cd /root/BlueHorseshoe && ./run.sh python scripts/send_handoff_reminder.py \\
    --subject "Reminder: resume contrarian thread" \\
    --doc SESSION_HANDOFF.md \\
    >> src/logs/reminder.log 2>&1
  (The per-thread docs/handoff/*.md files were consolidated into the root SESSION_HANDOFF.md
   on 2026-06-22; point --doc there.)
"""
from __future__ import annotations

import argparse
import os
import smtplib
import socket
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subject", required=True, help="Email subject line")
    ap.add_argument("--doc", required=True, help="Path to handoff doc (relative to repo root or absolute)")
    ap.add_argument("--note", default="", help="Optional one-line note prepended to the body")
    args = ap.parse_args()

    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("EMAIL_SENDER", smtp_user)
    recipient = os.environ.get("EMAIL_RECIPIENT")

    if not all([smtp_server, smtp_user, smtp_password, recipient]):
        print("FATAL: SMTP config missing in .env (need SMTP_SERVER, SMTP_USER, "
              "SMTP_PASSWORD, EMAIL_RECIPIENT).", file=sys.stderr)
        return 2

    doc_path = Path(args.doc)
    if not doc_path.is_absolute():
        doc_path = REPO_ROOT / doc_path
    if not doc_path.exists():
        print(f"FATAL: handoff doc not found at {doc_path}", file=sys.stderr)
        return 3

    try:
        body_text = doc_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"FATAL: could not read {doc_path}: {e}", file=sys.stderr)
        return 4

    host = socket.gethostname()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    preamble_parts = [
        f"Reminder fired at {now} from {host}.",
        f"Handoff doc: {doc_path.relative_to(REPO_ROOT) if doc_path.is_relative_to(REPO_ROOT) else doc_path}",
    ]
    if args.note:
        preamble_parts.append(f"Note: {args.note}")
    preamble = "\n".join(preamble_parts) + "\n\n" + ("-" * 60) + "\n\n"
    full_body = preamble + body_text

    msg = MIMEText(full_body, "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = args.subject

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=60) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: SMTP send failed: {e}", file=sys.stderr)
        return 5

    print(f"OK: reminder sent to {recipient} (subject: {args.subject!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
