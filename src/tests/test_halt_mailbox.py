"""HALT-mailbox auth + routing tests (no IMAP, no broker, no real sentinel)."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
import logging
import os
from email.message import EmailMessage

import pytest

import bh_swing.operator.halt_mailbox as hm


@pytest.fixture
def hm_env(tmp_path, monkeypatch):
    monkeypatch.setattr(hm, "KILL_SWITCH_PATH", str(tmp_path / ".sentinel"))
    # Don't let test log lines land in the production halt_mailbox.log.
    monkeypatch.setattr(hm.logger, "handlers", [logging.NullHandler()])
    monkeypatch.setattr(hm, "_confirm", lambda subject, body: None)
    monkeypatch.setattr(hm, "_do_flatten", lambda: "FLATTEN (stubbed)")
    monkeypatch.setitem(hm.HANDLERS, "FLATTEN", lambda: "FLATTEN (stubbed)")
    monkeypatch.setenv("HALT_SECRET_TOKEN", "swordfish")
    monkeypatch.setenv("HALT_ALLOWED_SENDER", "brandg@gmail.com")
    return hm


def _msg(frm, subj, body):
    m = EmailMessage()
    m["From"] = frm
    m["Subject"] = subj
    m.set_content(body)
    return m


def _frozen():
    return os.path.exists(hm.KILL_SWITCH_PATH)


def test_valid_halt_then_resume(hm_env):
    hm._handle_message(_msg("Brand <brandg@gmail.com>", "HALT", "swordfish"))
    assert _frozen()
    hm._handle_message(_msg("brandg@gmail.com", "RESUME", "swordfish"))
    assert not _frozen()


def test_token_in_subject_accepted(hm_env):
    # Token in the subject (signature-proof), body has no token.
    hm._handle_message(_msg("brandg@gmail.com", "HALT swordfish", "-- \nsignature only"))
    assert _frozen()
    hm._handle_message(_msg("brandg@gmail.com", "RESUME swordfish", "-- \nsig"))
    assert not _frozen()


def test_token_tolerates_env_quotes_and_case(hm_env, monkeypatch):
    # .env value carries surrounding quotes (run.sh exports verbatim) + different case.
    monkeypatch.setenv("HALT_SECRET_TOKEN", '"And Where Man"')
    hm._handle_message(_msg("brandg@gmail.com", "STATUS and where man", "no body token"))
    assert not _frozen()  # STATUS never mutates
    hm._handle_message(_msg("brandg@gmail.com", "HALT and where man", ""))
    assert _frozen()


def test_wrong_sender_rejected(hm_env):
    hm._handle_message(_msg("evil@bad.com", "HALT", "swordfish"))
    assert not _frozen()


def test_missing_token_rejected(hm_env):
    hm._handle_message(_msg("brandg@gmail.com", "HALT", "please stop"))
    assert not _frozen()


def test_command_is_case_insensitive(hm_env):
    hm._handle_message(_msg("brandg@gmail.com", "halt", "swordfish"))
    assert _frozen()


def test_non_command_ignored(hm_env):
    hm._handle_message(_msg("brandg@gmail.com", "hello there", "swordfish"))
    assert not _frozen()


def test_status_does_not_mutate(hm_env):
    hm._handle_message(_msg("brandg@gmail.com", "STATUS", "swordfish"))
    assert not _frozen()
