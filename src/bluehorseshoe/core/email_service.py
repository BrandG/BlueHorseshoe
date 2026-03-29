import smtplib
import os
import re
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
        self.smtp_user = os.environ.get('SMTP_USER')
        self.smtp_password = os.environ.get('SMTP_PASSWORD')
        self.recipient = os.environ.get('EMAIL_RECIPIENT')
        self.sender = os.environ.get('EMAIL_SENDER', self.smtp_user)

    def _build_report_email(self, report_path: str, subject: str | None):
        email_friendly_path = report_path.replace('.html', '_email.html')
        body_path = email_friendly_path if os.path.exists(email_friendly_path) else report_path

        if body_path == email_friendly_path:
            logger.info(f"Using email-friendly version for body: {email_friendly_path}")
        else:
            logger.info("Email-friendly version not found, using full report for body")

        msg = MIMEMultipart('mixed')
        msg['From'] = self.sender
        msg['To'] = self.recipient
        msg['Subject'] = subject or f"BlueHorseshoe Report - {os.path.basename(report_path)}"

        with open(body_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        text_body = "This email contains an HTML report. Please use an HTML-compatible email client to view it."
        msg_alternative = MIMEMultipart('alternative')
        msg_alternative.attach(MIMEText(text_body, 'plain'))
        msg_alternative.attach(MIMEText(html_content, 'html'))
        msg.attach(msg_alternative)

        with open(report_path, 'rb') as f:
            report_bytes = f.read()
        report_filename = os.path.basename(report_path)
        part = MIMEApplication(report_bytes, Name=report_filename)
        part['Content-Disposition'] = f'attachment; filename="{report_filename}"'
        msg.attach(part)

        date_match = re.search(r'report_(\d{4}-\d{2}-\d{2})', os.path.basename(report_path))
        if date_match:
            report_date = date_match.group(1)
            arcade_path = os.path.join(os.path.dirname(report_path), f'report_{report_date}_arcade.html')
            if os.path.exists(arcade_path):
                arcade_filename = f'arcade_report_{report_date}.html'
                with open(arcade_path, 'rb') as f:
                    arcade_bytes = f.read()
                arcade_part = MIMEApplication(arcade_bytes, Name=arcade_filename)
                arcade_part['Content-Disposition'] = f'attachment; filename="{arcade_filename}"'
                msg.attach(arcade_part)
                logger.info(f"Arcade report attached: {arcade_path}")
            else:
                logger.info(f"Arcade report not found at {arcade_path}, skipping attachment")

        return msg

    def send_report(self, report_path: str, subject: str = None):
        """
        Sends the HTML report in the email body AND as an attachment.

        If an email-friendly version exists (report_YYYY-MM-DD_email.html),
        it will be used for the email body. Otherwise, falls back to the full report.
        """
        if not self.recipient or not self.sender:
            logger.warning("Email configuration missing (EMAIL_RECIPIENT or EMAIL_SENDER). Skipping email.")
            return False

        if not os.path.exists(report_path):
            logger.error(f"Report file not found: {report_path}")
            return False

        try:
            if not self.smtp_user or not self.smtp_password:
                logger.warning("SMTP configuration missing (SMTP_USER or SMTP_PASSWORD). Skipping email.")
                return False

            msg = self._build_report_email(report_path, subject)
            logger.info("Sending report via SMTP")
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=120) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {self.recipient}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            return False
