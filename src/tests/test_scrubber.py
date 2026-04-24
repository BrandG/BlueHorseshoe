"""Tests for bh_ftmo.logging.scrubber."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from bh_ftmo.logging.scrubber import (
    DEFAULT_PATTERNS,
    REDACTION,
    SecretScrubber,
    install,
    secrets_from_env,
)


TOKEN_LIKE = "a" * 32 + "-" + "b" * 32
ACCOUNT_LIKE = "001-001-21321256-001"


def _record(msg: str, *args) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=None,
    )


# ---- exact-secret matching ----------------------------------------------


def test_scrubs_exact_secret_in_message():
    scrubber = SecretScrubber(secrets=["super-secret-token"])
    rec = _record("using token=super-secret-token for request")
    scrubber.filter(rec)
    assert "super-secret-token" not in rec.getMessage()
    assert REDACTION in rec.getMessage()


def test_scrubs_exact_secret_after_format_args():
    scrubber = SecretScrubber(secrets=["s3cret-X"])
    rec = _record("user=%s token=%s", "alice", "s3cret-X")
    scrubber.filter(rec)
    assert "s3cret-X" not in rec.getMessage()
    assert "alice" in rec.getMessage()


def test_leaves_nonmatching_messages_alone():
    scrubber = SecretScrubber(secrets=["abc"])
    rec = _record("nothing to scrub here")
    scrubber.filter(rec)
    assert rec.getMessage() == "nothing to scrub here"


def test_skips_too_short_secrets():
    """A 2-char 'secret' would false-positive everywhere — ignored."""
    scrubber = SecretScrubber(secrets=["ab"])
    rec = _record("abacus and other words")
    scrubber.filter(rec)
    assert "abacus" in rec.getMessage()


def test_longer_secret_replaced_before_shorter_substring():
    scrubber = SecretScrubber(secrets=["abc-xyz", "abc"])
    rec = _record("value=abc-xyz")
    scrubber.filter(rec)
    # Longest match wins: full "abc-xyz" becomes REDACTED, not just "abc"
    assert rec.getMessage() == f"value={REDACTION}"


# ---- pattern matching ---------------------------------------------------


def test_scrubs_oanda_token_pattern_without_exact_match():
    scrubber = SecretScrubber(secrets=[])
    rec = _record(f"bearer {TOKEN_LIKE} authenticated")
    scrubber.filter(rec)
    assert TOKEN_LIKE not in rec.getMessage()
    assert REDACTION in rec.getMessage()


def test_scrubs_account_id_pattern():
    scrubber = SecretScrubber(secrets=[])
    rec = _record(f"account {ACCOUNT_LIKE} balance=0")
    scrubber.filter(rec)
    assert ACCOUNT_LIKE not in rec.getMessage()


def test_patterns_can_be_overridden():
    custom = [re.compile(r"XXX-\d+")]
    scrubber = SecretScrubber(secrets=[], patterns=custom)
    rec = _record(f"saw XXX-42 and also {TOKEN_LIKE}")
    scrubber.filter(rec)
    msg = rec.getMessage()
    assert "XXX-42" not in msg
    # Default patterns no longer active → token still visible
    assert TOKEN_LIKE in msg


def test_default_patterns_exposed_as_tuple():
    assert len(DEFAULT_PATTERNS) >= 2


# ---- multi-occurrence ---------------------------------------------------


def test_scrubs_multiple_occurrences():
    scrubber = SecretScrubber(secrets=["topsecret"])
    rec = _record("topsecret twice: topsecret and topsecret")
    scrubber.filter(rec)
    assert "topsecret" not in rec.getMessage()
    assert rec.getMessage().count(REDACTION) == 3


# ---- exc_text -----------------------------------------------------------


def test_scrubs_exc_text():
    scrubber = SecretScrubber(secrets=["sektoken"])
    rec = _record("oh no")
    rec.exc_text = "Traceback: auth=sektoken failed"
    scrubber.filter(rec)
    assert "sektoken" not in (rec.exc_text or "")


# ---- filter return value ------------------------------------------------


def test_filter_always_returns_true():
    scrubber = SecretScrubber(secrets=[])
    rec = _record("hello")
    assert scrubber.filter(rec) is True


# ---- secrets_from_env ---------------------------------------------------


def test_secrets_from_env_reads_env_vars(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "envtoken")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "envaccount")
    monkeypatch.delenv("FTMO_ACCOUNT_ID", raising=False)
    secrets = secrets_from_env(env_path=Path("/nonexistent"))
    assert "envtoken" in secrets
    assert "envaccount" in secrets


def test_secrets_from_env_falls_back_to_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("FTMO_ACCOUNT_ID", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'OANDA_API_TOKEN="file-token"\n'
        "OANDA_ACCOUNT_ID=file-acct\n",
        encoding="utf-8",
    )
    secrets = secrets_from_env(env_path=env_file)
    assert "file-token" in secrets
    assert "file-acct" in secrets


def test_secrets_from_env_skips_empty_values(monkeypatch, tmp_path):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("FTMO_ACCOUNT_ID", raising=False)
    secrets = secrets_from_env(env_path=tmp_path / "does-not-exist")
    assert secrets == []


# ---- install ------------------------------------------------------------


def test_install_attaches_filter_to_logger_and_handlers(caplog):
    logger = logging.getLogger("bh_ftmo.test.scrubber.install")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    scrubber = install(logger, secrets=["wowsecret"], load_env=False)
    try:
        assert scrubber in logger.filters
        assert scrubber in handler.filters
    finally:
        logger.removeFilter(scrubber)
        handler.removeFilter(scrubber)
        logger.handlers.clear()


def test_install_end_to_end_logger_does_not_emit_secret(caplog):
    logger = logging.getLogger("bh_ftmo.test.scrubber.e2e")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    scrubber = install(logger, secrets=["hunter2"], load_env=False)
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            logger.info("password=%s", "hunter2")
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "hunter2" not in joined
        assert REDACTION in joined
    finally:
        logger.removeFilter(scrubber)
        logger.handlers.clear()
