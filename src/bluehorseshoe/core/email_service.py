import smtplib
import os
import re
import uuid
import mimetypes
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

JMAP_SESSION_URL = "https://api.fastmail.com/jmap/session"
_JMAP_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail",
               "urn:ietf:params:jmap:submission"]


class EmailService:
    """SMTP email delivery, decoupled from any specific document type.

    Generic layer: send() / send_file() handle arbitrary subjects, bodies,
    and attachments. Report-specific conventions (email-friendly body lookup,
    arcade sibling attachment) live only in send_report().
    """

    def __init__(self):
        # Backend: 'jmap' sends via the Fastmail JMAP API over 443 (DO blocks
        # outbound SMTP 25/465/587); 'smtp' (default) uses the Brevo relay on 2525.
        self.backend = os.environ.get('EMAIL_BACKEND', 'smtp').lower()
        self.smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
        self.smtp_user = os.environ.get('SMTP_USER')
        self.smtp_password = os.environ.get('SMTP_PASSWORD')
        self.recipient = os.environ.get('EMAIL_RECIPIENT')
        self.jmap_token = os.environ.get('FASTMAIL_JMAP_TOKEN')
        self.jmap_from = os.environ.get('FASTMAIL_JMAP_FROM')
        # For JMAP the From is the Fastmail identity; for SMTP it's EMAIL_SENDER.
        if self.backend == 'jmap':
            self.sender = self.jmap_from or os.environ.get('EMAIL_SENDER')
        else:
            self.sender = os.environ.get('EMAIL_SENDER', self.smtp_user)

    def is_configured(self) -> bool:
        if not self.recipient or not self.sender:
            logger.warning("Email configuration missing (EMAIL_RECIPIENT or EMAIL_SENDER). Skipping email.")
            return False
        if self.backend == 'jmap':
            if not self.jmap_token:
                logger.warning("JMAP configuration missing (FASTMAIL_JMAP_TOKEN). Skipping email.")
                return False
            return True
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
        subject_tagged = f"{subject} [id:{guid}]"

        if self.backend == 'jmap':
            return self._send_jmap(subject_tagged, guid, html_body, text_body, attachments)

        try:
            msg = MIMEMultipart('mixed')
            msg['From'] = self.sender
            msg['To'] = self.recipient
            msg['Subject'] = subject_tagged
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

    # ---- JMAP backend (Fastmail over 443; DO blocks outbound SMTP) ---------

    def _jmap_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.jmap_token}", "Content-Type": "application/json"}

    def _jmap_upload(self, upload_url: str, account_id: str, path: str, filename: str) -> dict:
        """Upload one attachment blob; return its Email bodyStructure part."""
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        url = upload_url.replace("{accountId}", account_id)
        resp = requests.post(url, headers={"Authorization": f"Bearer {self.jmap_token}",
                                           "Content-Type": mime_type}, data=data, timeout=120)
        resp.raise_for_status()
        blob = resp.json()
        return {"blobId": blob["blobId"], "type": blob.get("type", mime_type),
                "disposition": "attachment", "name": filename}

    @staticmethod
    def _jmap_body(html_body, text_body, attachment_parts):
        """Build (bodyStructure, bodyValues) for text, text+html, and attachments."""
        body_values = {"text": {"value": text_body or ""}}
        body = {"type": "text/plain", "partId": "text"}
        if html_body is not None:
            body_values["html"] = {"value": html_body}
            body = {"type": "multipart/alternative", "subParts": [
                {"type": "text/plain", "partId": "text"},
                {"type": "text/html", "partId": "html"},
            ]}
        if attachment_parts:
            return {"type": "multipart/mixed", "subParts": [body] + attachment_parts}, body_values
        return body, body_values

    def _send_jmap(self, subject, guid, html_body, text_body, attachments) -> str | None:
        """Send via the Fastmail JMAP API over HTTPS. Returns guid on acceptance, else None."""
        try:
            sess = requests.get(JMAP_SESSION_URL, headers=self._jmap_headers(), timeout=30)
            sess.raise_for_status()
            session = sess.json()
            api_url = session["apiUrl"]
            account_id = session["primaryAccounts"]["urn:ietf:params:jmap:mail"]

            meta = requests.post(api_url, headers=self._jmap_headers(), timeout=30, json={
                "using": _JMAP_USING, "methodCalls": [
                    ["Mailbox/get", {"accountId": account_id, "properties": ["role"]}, "m"],
                    ["Identity/get", {"accountId": account_id}, "i"],
                ]}).json()
            mboxes = meta["methodResponses"][0][1]["list"]
            drafts = next((m["id"] for m in mboxes if m.get("role") == "drafts"), None)
            sent = next((m["id"] for m in mboxes if m.get("role") == "sent"), None)
            identities = meta["methodResponses"][1][1]["list"]
            ident = next((i for i in identities
                          if i.get("email", "").lower() == (self.sender or "").lower()),
                         identities[0] if identities else None)
            if drafts is None or ident is None:
                logger.error("JMAP: missing Drafts mailbox or identity (id=%s)", guid)
                return None

            attachment_parts = []
            for item in attachments or []:
                path, filename = item if isinstance(item, tuple) else (item, None)
                attachment_parts.append(
                    self._jmap_upload(session["uploadUrl"], account_id, path,
                                      filename or os.path.basename(path)))

            structure, body_values = self._jmap_body(html_body, text_body, attachment_parts)
            on_success = {"mailboxIds/" + drafts: None, "keywords/$draft": None}
            if sent:
                on_success["mailboxIds/" + sent] = True

            logger.info("Submitting email via JMAP: %r id=%s", subject, guid)
            r = requests.post(api_url, headers=self._jmap_headers(), timeout=120, json={
                "using": _JMAP_USING, "methodCalls": [
                    ["Email/set", {"accountId": account_id, "create": {"d": {
                        "mailboxIds": {drafts: True},
                        "keywords": {"$draft": True},
                        "from": [{"email": self.sender}],
                        "to": [{"email": self.recipient}],
                        "subject": subject,
                        "header:X-BH-Message-Id:asText": guid,
                        "bodyStructure": structure,
                        "bodyValues": body_values,
                    }}}, "c"],
                    ["EmailSubmission/set", {"accountId": account_id,
                        "onSuccessUpdateEmail": {"#s": on_success},
                        "create": {"s": {"emailId": "#d", "identityId": ident["id"]}}}, "s"],
                ]}).json()

            # onSuccessUpdateEmail appends an implicit Email/set response that shares the
            # EmailSubmission call-id ("s"), so match by (method, cid), not a cid dict.
            mr = r["methodResponses"]
            draft_res = next((res for n, res, c in mr if n == "Email/set" and c == "c"), None) or {}
            sub_res = next((res for n, res, c in mr if n == "EmailSubmission/set" and c == "s"), None) or {}
            if not (draft_res.get("created") or {}).get("d"):
                logger.error("JMAP Email/set failed id=%s: %s", guid, draft_res.get("notCreated") or draft_res)
                return None
            if not (sub_res.get("created") or {}).get("s"):
                logger.error("JMAP EmailSubmission failed id=%s: %s", guid, sub_res.get("notCreated") or sub_res)
                return None
            logger.info("Email SENT via Fastmail JMAP to %s id=%s", self.recipient, guid)
            return guid
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to send via JMAP (id=%s): %s", guid, e, exc_info=True)
            return None

    @staticmethod
    def _read_text_file(file_path: str) -> str | None:
        try:
            return Path(file_path).read_text(encoding='utf-8')
        except UnicodeDecodeError:
            logger.info(f"File is not UTF-8 text; using attachment-only body: {file_path}")
            return None

    def send_file(self, file_path: str, subject: str | None = None, body: str | None = None,
                  inline_html: bool = True) -> bool:
        """Email any local file as an attachment.

        UTF-8 text files are used as the plain-text body by default. HTML files are
        additionally inlined as HTML so they render in the client — UNLESS
        ``inline_html=False``, in which case the file is attachment-only (needed for
        interactive/JS reports like the arcade report, whose scripts are stripped from
        an email body but run when the attachment is opened in a browser). The source
        file is always attached.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return False

        filename = os.path.basename(file_path)
        subject = subject or f"BlueHorseshoe File - {filename}"

        html_body = None
        text_body = body
        if file_path.lower().endswith(('.html', '.htm')):
            if inline_html:
                with open(file_path, 'r', encoding='utf-8') as f:
                    html_body = f.read()
                if text_body is None:
                    text_body = (f"This email contains the HTML file {filename}. "
                                 "Please use an HTML-compatible email client to view it.")
            elif text_body is None:
                text_body = (f"{filename} is attached — open it in a browser to view. "
                             "(Interactive reports don't render in the email body.)")
        elif text_body is None:
            text_body = self._read_text_file(file_path) or f"Attached: {filename}"

        return self.send(subject, html_body=html_body, text_body=text_body, attachments=[file_path])

    def send_report(self, report_path: str, subject: str = None) -> bool:
        """
        Sends the HTML report in the email body AND as an attachment.

        If an email-friendly version exists (email_report_YYYY-MM-DD.html),
        it will be used for the email body. Otherwise, falls back to the full report.
        The arcade sibling (arcade_report_YYYY-MM-DD.html) is attached when present.
        """
        if not os.path.exists(report_path):
            logger.error(f"Report file not found: {report_path}")
            return False

        report_dir = os.path.dirname(report_path)
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(report_path))
        report_date = date_match.group(1) if date_match else None

        email_friendly_path = (
            os.path.join(report_dir, f'email_report_{report_date}.html')
            if report_date else None
        )
        body_path = (
            email_friendly_path
            if email_friendly_path and os.path.exists(email_friendly_path)
            else report_path
        )

        if body_path == email_friendly_path:
            logger.info(f"Using email-friendly version for body: {email_friendly_path}")
        else:
            logger.info("Email-friendly version not found, using full report for body")

        with open(body_path, 'r', encoding='utf-8') as f:
            html_body = f.read()

        attachments: list = [report_path]
        if report_date:
            arcade_path = os.path.join(report_dir, f'arcade_report_{report_date}.html')
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
