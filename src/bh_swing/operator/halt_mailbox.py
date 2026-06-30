"""HALT mailbox — out-of-band kill switch for the BH Swing automated trader.

Polls a dedicated IMAP inbox for control messages from the operator and trips the
management kill switch (FREEZE), clears it (RESUME), or runs the emergency flatten
(FLATTEN). Designed to run from cron every minute, in a process that is *independent*
of the trader, so a wedged or runaway trader cannot block the kill.

Security (both required, or the message is ignored):
  * From: must match HALT_ALLOWED_SENDER (sender allowlist).
  * The body must contain HALT_SECRET_TOKEN (shared secret).
Only UNSEEN messages are processed, and each is marked \\Seen after handling, so a
command fires exactly once. The command is the Subject line (case-insensitive).

Commands:
  HALT     -> create the management sentinel: stops new entries AND exit-side
              mutations. Resting broker stops stay live and keep protecting you.
  RESUME   -> remove the sentinel: trading/management resumes on the next tick.
  FLATTEN  -> run the emergency flatten (closes every position now).
  STATUS   -> reply with the current kill-switch state (no mutation).

Env (.env):
  HALT_IMAP_HOST        default imap.fastmail.com
  HALT_IMAP_PORT        default 993
  HALT_IMAP_USER        dedicated mailbox address
  HALT_IMAP_PASS        IMAP app password (NOT your login password)
  HALT_SECRET_TOKEN     shared secret that must appear in the message body
  HALT_ALLOWED_SENDER   sender allowlist (default: EMAIL_RECIPIENT)

Every action is logged to src/logs/halt_mailbox.log and confirmed back by email.
Fail-safe: any error is logged and swallowed so the cron never crash-loops.
"""
import email
import fcntl
import imaplib
import logging
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr

from bh_swing.trading.safety import KILL_SWITCH_PATH

REPO_ROOT = os.path.dirname(KILL_SWITCH_PATH)
LOG_PATH = os.path.join(REPO_ROOT, "src", "logs", "halt_mailbox.log")
LOCK_PATH = os.path.join(REPO_ROOT, ".halt_mailbox.lock")
FLATTEN_SCRIPT = os.path.join(REPO_ROOT, "src", "gordon", "swing_flatten.py")

# Configure the named logger EXPLICITLY — do not use logging.basicConfig(), which
# no-ops when an imported module (bluehorseshoe.*) has already configured the root
# logger, silently dropping our FileHandler and leaving the kill switch unobservable.
logger = logging.getLogger("halt_mailbox")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)sZ %(levelname)s halt_mailbox: %(message)s")
    _fmt.converter = __import__("time").gmtime
    _fh = logging.FileHandler(LOG_PATH)
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    logger.addHandler(_sh)

VALID_COMMANDS = {"HALT", "RESUME", "FLATTEN", "STATUS"}


def _decode(raw) -> str:
    if raw is None:
        return ""
    parts = decode_header(raw)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _body_text(msg) -> str:
    """Flatten the message to plain text (handles multipart)."""
    if msg.is_multipart():
        chunks = []
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    chunks.append(payload.decode(part.get_content_charset() or "utf-8",
                                                 errors="replace"))
        return "\n".join(chunks)
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return str(msg.get_payload())


def _confirm(subject: str, body: str) -> None:
    """Best-effort email confirmation back to the operator."""
    try:
        from bluehorseshoe.core.email_service import EmailService  # pylint: disable=import-outside-toplevel
        svc = EmailService()
        if svc.is_configured():
            svc.send(subject=subject, text_body=body)
    except Exception as e:  # noqa: BLE001
        logger.warning("confirmation email failed: %s", e)


def _do_halt() -> str:
    with open(KILL_SWITCH_PATH, "w", encoding="utf-8") as f:
        f.write(f"halted via mailbox {datetime.now(timezone.utc).isoformat()}\n")
    return ("FROZEN. New entries and exit-side mutations are halted as of the next "
            "tick. Resting broker stops remain live and keep protecting open positions. "
            "Send RESUME to clear.")


def _do_resume() -> str:
    if os.path.exists(KILL_SWITCH_PATH):
        os.remove(KILL_SWITCH_PATH)
        return "RESUMED. The kill switch is cleared; management resumes next tick."
    return "RESUME: kill switch was already clear; nothing to do."


def _do_flatten() -> str:
    """Run the emergency flatten against the configured account (paper during Stage 0)."""
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO_ROOT, "src"))
    try:
        proc = subprocess.run(
            [sys.executable, FLATTEN_SCRIPT, "--execute"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
            check=False,   # returncode is reported to the operator, not raised
        )
        tail = (proc.stdout or "")[-1500:]
        err = (proc.stderr or "")[-500:]
        return (f"FLATTEN exit={proc.returncode}\n--- stdout ---\n{tail}\n"
                + (f"--- stderr ---\n{err}\n" if err.strip() else ""))
    except subprocess.TimeoutExpired:
        return "FLATTEN TIMED OUT after 300s — check positions manually."


def _do_status() -> str:
    frozen = os.path.exists(KILL_SWITCH_PATH)
    return f"STATUS: kill switch is {'ACTIVE (frozen)' if frozen else 'clear (trading enabled)'}."


HANDLERS = {"HALT": _do_halt, "RESUME": _do_resume, "FLATTEN": _do_flatten, "STATUS": _do_status}


def _handle_message(msg) -> None:
    sender = parseaddr(_decode(msg.get("From")))[1].lower().strip()
    raw_subject = _decode(msg.get("Subject")).strip()
    subject = raw_subject.upper()
    allowed = (os.environ.get("HALT_ALLOWED_SENDER")
               or os.environ.get("EMAIL_RECIPIENT") or "").lower().strip()
    # Tolerate surrounding quotes in the .env value: run.sh exports verbatim, so
    # HALT_SECRET_TOKEN="a b c" keeps its quotes. Match case-insensitively.
    token = os.environ.get("HALT_SECRET_TOKEN", "").strip().strip("\"'").strip()
    cmd = next((c for c in VALID_COMMANDS if subject == c or subject.startswith(c + " ")), None)

    if cmd is None:
        logger.info("ignoring non-command subject %r from %s", subject, sender)
        return
    if allowed and sender != allowed:
        logger.warning("REJECT %s: sender %s not in allowlist", cmd, sender)
        return
    # The token may appear in the SUBJECT (easiest on mobile, signature-proof) or
    # anywhere in the body.
    haystack = (raw_subject + "\n" + _body_text(msg)).lower()
    if not token or token.lower() not in haystack:
        logger.warning("REJECT %s from %s: missing/invalid token", cmd, sender)
        return

    logger.info("EXECUTING %s (from %s)", cmd, sender)
    result = HANDLERS[cmd]()
    logger.info("%s result: %s", cmd, result.splitlines()[0] if result else "")
    _confirm(subject=f"[BH HALT] {cmd} executed", body=result)


def poll_once() -> int:
    """Connect, process all unseen command messages, return the count handled."""
    host = os.environ.get("HALT_IMAP_HOST", "imap.fastmail.com")
    port = int(os.environ.get("HALT_IMAP_PORT", "993"))
    user = os.environ.get("HALT_IMAP_USER")
    password = os.environ.get("HALT_IMAP_PASS")
    if not user or not password:
        logger.error("HALT_IMAP_USER / HALT_IMAP_PASS not set; cannot poll")
        return 0

    socket.setdefaulttimeout(30)
    handled = 0
    imap = imaplib.IMAP4_SSL(host, port)
    try:
        imap.login(user, password)
        imap.select("INBOX")
        typ, data = imap.search(None, "UNSEEN")
        if typ != "OK":
            return 0
        for num in data[0].split():
            typ, msg_data = imap.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            try:
                _handle_message(msg)
                handled += 1
            finally:
                imap.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    return handled


def main() -> int:
    # Single-flight: never let cron runs overlap. flock auto-releases on close.
    with open(LOCK_PATH, "w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("another poll is running; skipping")
            return 0
        try:
            n = poll_once()
            if n:
                logger.info("handled %d command message(s)", n)
            return 0
        except Exception as e:  # noqa: BLE001  — fail-safe: never crash the cron
            logger.error("poll failed: %s", e)
            return 0


if __name__ == "__main__":
    sys.exit(main())
