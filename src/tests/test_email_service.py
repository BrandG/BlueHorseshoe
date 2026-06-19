from email.mime.multipart import MIMEMultipart

from bluehorseshoe.core import email_service
from bluehorseshoe.core.email_service import EmailService


class CapturingSMTP:
    messages = []

    def __init__(self, server, port, timeout=None):
        self.server = server
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user
        self.password = password

    def send_message(self, msg):
        self.messages.append(msg)


def configured_service(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-pass")
    monkeypatch.setenv("EMAIL_RECIPIENT", "to@example.com")
    monkeypatch.setenv("EMAIL_SENDER", "from@example.com")
    CapturingSMTP.messages = []
    monkeypatch.setattr(email_service.smtplib, "SMTP", CapturingSMTP)
    return EmailService()


def message_parts(msg):
    return list(msg.walk())


def test_send_file_inlines_utf8_text_and_attaches_file(tmp_path, monkeypatch):
    service = configured_service(monkeypatch)
    text_file = tmp_path / "note.txt"
    text_file.write_text("arbitrary text\nline two\n", encoding="utf-8")

    assert service.send_file(str(text_file), subject="Send this")

    msg = CapturingSMTP.messages[0]
    # Subject now carries a per-message GUID for delivery tracking: "Send this [id:<uuid>]"
    assert msg["Subject"].startswith("Send this [id:")
    assert msg["X-BH-Message-Id"] and msg["X-BH-Message-Id"] in msg["Subject"]
    plain_parts = [p for p in message_parts(msg) if p.get_content_type() == "text/plain"]
    attachments = [p for p in message_parts(msg) if p.get_filename() == "note.txt"]
    assert plain_parts[0].get_payload(decode=True).decode() == "arbitrary text\nline two\n"
    assert attachments[0].get_payload(decode=True) == b"arbitrary text\nline two\n"


def test_send_report_uses_email_body_and_keeps_report_attachments(tmp_path, monkeypatch):
    service = configured_service(monkeypatch)
    report = tmp_path / "report_2026-06-10.html"
    email_body = tmp_path / "report_2026-06-10_email.html"
    arcade = tmp_path / "report_2026-06-10_arcade.html"
    report.write_text("<html>full</html>", encoding="utf-8")
    email_body.write_text("<html>email</html>", encoding="utf-8")
    arcade.write_text("<html>arcade</html>", encoding="utf-8")

    assert service.send_report(str(report))

    msg = CapturingSMTP.messages[0]
    html_parts = [p for p in message_parts(msg) if p.get_content_type() == "text/html"]
    filenames = sorted(p.get_filename() for p in message_parts(msg) if p.get_filename())
    assert html_parts[0].get_payload(decode=True).decode() == "<html>email</html>"
    assert filenames == ["arcade_report_2026-06-10.html", "report_2026-06-10.html"]


def test_send_delegates_arbitrary_attachments(tmp_path, monkeypatch):
    service = configured_service(monkeypatch)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    assert service.send("Bundle", text_body="See attached.", attachments=[str(first), (str(second), "renamed.txt")])

    msg = CapturingSMTP.messages[0]
    assert isinstance(msg, MIMEMultipart)
    filenames = sorted(p.get_filename() for p in message_parts(msg) if p.get_filename())
    assert filenames == ["first.txt", "renamed.txt"]
