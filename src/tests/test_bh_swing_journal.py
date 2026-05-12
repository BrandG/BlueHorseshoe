"""Tests for bh_swing journal append + dedup helpers."""
from unittest.mock import patch

import pytest

from bh_swing import journal


@pytest.fixture
def temp_journal(tmp_path, monkeypatch):
    """Redirect JOURNAL_PATH at module load time."""
    p = tmp_path / "bh_swing_journal.csv"
    monkeypatch.setattr(journal, "JOURNAL_PATH", str(p))
    return str(p)


class TestAppend:
    def test_creates_header_on_first_write(self, temp_journal):
        journal.append(journal.JournalRow(
            run_mode="live", event=journal.EVENT_RUN_START,
        ))
        with open(temp_journal, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert lines[0].startswith("ts_utc,run_mode,event")
        assert "run_start" in lines[1]

    def test_appends_without_duplicating_header(self, temp_journal):
        journal.append(journal.JournalRow(run_mode="live", event="a"))
        journal.append(journal.JournalRow(run_mode="live", event="b"))
        with open(temp_journal, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 3  # 1 header + 2 events
        assert lines[0].count(",") == lines[1].count(",")

    def test_auto_timestamp(self, temp_journal):
        row = journal.JournalRow(run_mode="live", event="x")
        journal.append(row)
        with open(temp_journal, "r", encoding="utf-8") as f:
            data = f.read()
        # ISO 8601 with timezone offset
        assert "+00:00" in data or "Z" in data

    def test_append_many_empty_is_noop(self, temp_journal):
        journal.append_many([])
        import os
        assert not os.path.exists(temp_journal)


class TestReadAndDedup:
    def test_read_recent_empty(self, temp_journal):
        assert journal.read_recent() == []

    def test_read_recent_returns_newest_first(self, temp_journal):
        journal.append(journal.JournalRow(run_mode="live", event="first"))
        journal.append(journal.JournalRow(run_mode="live", event="second"))
        rows = journal.read_recent()
        assert rows[0]["event"] == "second"
        assert rows[1]["event"] == "first"

    def test_last_seen_exec_ids(self, temp_journal):
        journal.append(journal.JournalRow(
            run_mode="live", event="fill_detected", exec_id="EXEC-1",
        ))
        journal.append(journal.JournalRow(
            run_mode="live", event="fill_detected", exec_id="EXEC-2",
        ))
        journal.append(journal.JournalRow(
            run_mode="live", event="run_start",  # no exec_id
        ))
        assert journal.last_seen_exec_ids() == {"EXEC-1", "EXEC-2"}

    def test_last_seen_skips_blank_exec_ids(self, temp_journal):
        journal.append(journal.JournalRow(
            run_mode="live", event="fill_detected", exec_id="",
        ))
        assert journal.last_seen_exec_ids() == set()
