"""Ratchet-watcher tests: bootstrap suppresses history, new events email once."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
import csv
import logging

import pytest

import bh_swing.operator.ratchet_watcher as rw

HEADER = ["ts_utc", "event", "symbol", "order_id", "stop_price", "price", "note"]


def _write_journal(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _ratchet(ts, sym, oid, old, new):
    return {"ts_utc": ts, "event": "stop_ratcheted", "symbol": sym,
            "order_id": oid, "stop_price": old, "price": new, "note": "up-day ratchet"}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    journal = tmp_path / "journal.csv"
    state = tmp_path / "state.json"
    monkeypatch.setattr(rw, "JOURNAL_PATH", str(journal))
    monkeypatch.setattr(rw, "STATE_PATH", str(state))
    monkeypatch.setattr(rw.logger, "handlers", [logging.NullHandler()])  # don't touch prod log
    sent = []
    monkeypatch.setattr(rw, "_email", lambda rows, first: sent.append((first, list(rows))))
    return journal, state, sent


def test_bootstrap_does_not_email(wired):
    journal, state, sent = wired
    _write_journal(journal, [_ratchet("2026-06-30T14:00", "BSY", "99", "28.71", "30.42")])
    rw.main()
    assert sent == []            # first run seeds silently
    assert state.exists()


def test_first_new_event_emails_as_first(wired):
    journal, _, sent = wired
    _write_journal(journal, [])  # empty
    rw.main()                    # bootstrap on empty
    _write_journal(journal, [_ratchet("2026-06-30T14:05", "FG", "42", "26.03", "27.10")])
    rw.main()
    assert len(sent) == 1
    first_flag, rows = sent[0]
    assert first_flag is True and rows[0]["symbol"] == "FG"


def test_each_event_reported_once(wired):
    journal, _, sent = wired
    _write_journal(journal, [])
    rw.main()
    _write_journal(journal, [_ratchet("2026-06-30T14:05", "FG", "42", "26.03", "27.10")])
    rw.main()
    rw.main()                    # second run: nothing new
    assert len(sent) == 1
