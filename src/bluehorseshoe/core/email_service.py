import smtplib
import os
import re
import uuid
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailService:
    """SMTP email delivery, decoupled from any specific document type.

    Generic layer: send() / send_file() handle arbitrary subjects, bodies,
    and attachments. Report-specific conventions (email-friendly body lookup,
    arcade sibling attachment) live only in send_report().
    """

    def __init__(self):
        self.smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
        self.smtp_user = os.environ.get('SMTP_USER')
        self.smtp_password = os.environ.get('SMTP_PASSWORD')
        self.recipient = os.environ.get('EMAIL_RECIPIENT')
        self.sender = os.environ.get('EMAIL_SENDER', self.smtp_user)

    def is_configured(self) -> bool:
        if not self.recipient or not self.sender:
            logger.warning("Email configuration missing (EMAIL_RECIPIENT or EMAIL_SENDER). Skipping email.")
            return False
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP configuration missing (SMTP_USER or SMTP_PASSWORD). Skipping email.")
            return False
        return True

    @staticmethod
    def _attach_file(msg: MIMEMultipart, file_path: str, filename: str | None = None):
        filename = filename or os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            part = MIMEApplication(f.read(), Name=filename)
        part['Content-Disposition'] = f'attachment; filename="{filename}"'
        msg.attach(part)

    def send(self, subject: str, html_body: str | None = None, text_body: str | None = None,
             attachments: list | None = None) -> str | None:
        """Queue an email at the SMTP relay. Returns a per-message GUID on relay
        ACCEPTANCE, else None.

        IMPORTANT: a non-None return means the relay (e.g. Brevo) ACCEPTED/queued the
        message -- it does NOT prove delivery. A suspended or throttled account can keep
        returning 250-queued at the relay while silently dropping the mail downstream
        (this exact failure cost us a debugging session). The GUID is embedded in the
        Subject as `[id:<guid>]` and in an `X-BH-Message-Id` header so delivery can be
        independently verified later (e.g. by searching the recipient mailbox for the id).

        attachments: list of file paths, or (file_path, attachment_filename) tuples.
        """
        if not self.is_configured():
            return None

        guid = str(uuid.uuid4())
        try:
            msg = MIMEMultipart('mixed')
            msg['From'] = self.sender
            msg['To'] = self.recipient
            msg['Subject'] = f"{subject} [id:{guid}]"
            msg['X-BH-Message-Id'] = guid

            msg_alternative = MIMEMultipart('alternative')
            msg_alternative.attach(MIMEText(text_body or '', 'plain'))
            if html_body is not None:
                msg_alternative.attach(MIMEText(html_body, 'html'))
            msg.attach(msg_alternative)

            for item in attachments or []:
                file_path, filename = item if isinstance(item, tuple) else (item, None)
                self._attach_file(msg, file_path, filename)

            logger.info(f"Submitting email to relay: {subject!r} id={guid}")
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=120) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                refused = server.send_message(msg)
            if refused:
                logger.error(f"Relay refused recipients {refused} (id={guid})")
                return None

            # 250 from the relay == QUEUED, not delivered. Report it as such.
            logger.info(f"Email QUEUED at relay (delivery NOT confirmed) to "
                        f"{self.recipient} id={guid}")
            return guid

        except Exception as e:
            logger.error(f"Failed to submit email (id={guid}): {e}", exc_info=True)
            return None

    @staticmethod
    def _read_text_file(file_path: str) -> str | None:
        try:
            return Path(file_path).read_text(encoding='utf-8')
        except UnicodeDecodeError:
            logger.info(f"File is not UTF-8 text; using attachment-only body: {file_path}")
            return None

    def send_file(self, file_path: str, subject: str | None = None, body: str | None = None) -> bool:
        """Email any local file as an attachment.

        UTF-8 text files are used as the plain-text body by default. HTML files
        are additionally inlined as HTML so they render in the client. The
        source file is always attached.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return False

        filename = os.path.basename(file_path)
        subject = subject or f"BlueHorseshoe File - {filename}"

        html_body = None
        text_body = body
        if file_path.lower().endswith(('.html', '.htm')):
            with open(file_path, 'r', encoding='utf-8') as f:
                html_body = f.read()
            if text_body is None:
                text_body = (f"This email contains the HTML file {filename}. "
                             "Please use an HTML-compatible email client to view it.")
        elif text_body is None:
            text_body = self._read_text_file(file_path) or f"Attached: {filename}"

        return self.send(subject, html_body=html_body, text_body=text_body, attachments=[file_path])

    def send_report(self, report_path: str, subject: str = None) -> bool:
        """
        Sends the HTML report in the email body AND as an attachment.

        If an email-friendly version exists (report_YYYY-MM-DD_email.html),
        it will be used for the email body. Otherwise, falls back to the full report.
        The arcade sibling (report_YYYY-MM-DD_arcade.html) is attached when present.
        """
        if not os.path.exists(report_path):
            logger.error(f"Report file not found: {report_path}")
            return False

        email_friendly_path = report_path.replace('.html', '_email.html')
        body_path = email_friendly_path if os.path.exists(email_friendly_path) else report_path

        if body_path == email_friendly_path:
            logger.info(f"Using email-friendly version for body: {email_friendly_path}")
        else:
            logger.info("Email-friendly version not found, using full report for body")

        with open(body_path, 'r', encoding='utf-8') as f:
            html_body = f.read()

        attachments: list = [report_path]
        date_match = re.search(r'report_(\d{4}-\d{2}-\d{2})', os.path.basename(report_path))
        if date_match:
            report_date = date_match.group(1)
            arcade_path = os.path.join(os.path.dirname(report_path), f'report_{report_date}_arcade.html')
            if os.path.exists(arcade_path):
                attachments.append((arcade_path, f'arcade_report_{report_date}.html'))
                logger.info(f"Arcade report attached: {arcade_path}")
            else:
                logger.info(f"Arcade report not found at {arcade_path}, skipping attachment")

        return self.send(
            subject or f"BlueHorseshoe Report - {os.path.basename(report_path)}",
            html_body=html_body,
            text_body="This email contains an HTML report. Please use an HTML-compatible email client to view it.",
            attachments=attachments,
        )
