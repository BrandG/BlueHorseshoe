import smtplib
import os
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

    def send_report(self, report_path: str, subject: str = None):
        """
        Sends the HTML report in the email body AND as an attachment.
        """
        if not self.smtp_user or not self.smtp_password or not self.recipient:
            logger.warning("Email configuration missing (SMTP_USER, SMTP_PASSWORD, or EMAIL_RECIPIENT). Skipping email.")
            return False

        if not os.path.exists(report_path):
            logger.error(f"Report file not found: {report_path}")
            return False

        try:
            msg = MIMEMultipart('mixed')
            msg['From'] = self.sender
            msg['To'] = self.recipient
            msg['Subject'] = subject or f"BlueHorseshoe Report - {os.path.basename(report_path)}"

            # Read HTML content
            with open(report_path, 'r', encoding='utf-8') as f:
                html_content = f.read()

            # Create alternative part for text/html body
            msg_alternative = MIMEMultipart('alternative')

            # Plain text fallback
            text_body = "This email contains an HTML report. Please use an HTML-compatible email client to view it."
            msg_alternative.attach(MIMEText(text_body, 'plain'))

            # HTML body
            msg_alternative.attach(MIMEText(html_content, 'html'))

            # Attach the alternative part
            msg.attach(msg_alternative)

            # Also attach as a file
            with open(report_path, 'rb') as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(report_path))
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(report_path)}"'
                msg.attach(part)

            # Send
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {self.recipient}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            return False
