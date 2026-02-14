#!/usr/bin/env python3
"""
Quick script to manually send the latest report via email.
"""
import sys
sys.path.insert(0, '/workspaces/BlueHorseshoe/src')

from bluehorseshoe.core.email_service import EmailService
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main():
    # Path to latest report
    report_path = '/workspaces/BlueHorseshoe/src/logs/report_2026-02-13.html'

    # Create email service
    email_service = EmailService()

    # Send the report
    print(f"Sending report: {report_path}")
    success = email_service.send_report(
        report_path=report_path,
        subject="BlueHorseshoe Daily Report - 2026-02-13 (Manual Test)"
    )

    if success:
        print("✓ Email sent successfully!")
    else:
        print("✗ Email sending failed. Check logs for details.")
        sys.exit(1)

if __name__ == '__main__':
    main()
