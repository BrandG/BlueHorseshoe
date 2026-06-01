"""Tests for BH Swing strategy-only P&L history."""
from bh_swing import journal, pnl_history


def test_append_snapshot_read_history_roundtrip_and_single_header(tmp_path, monkeypatch):
    path = tmp_path / "pnl_history.csv"
    monkeypatch.setattr(pnl_history, "PNL_HISTORY_PATH", str(path))

    pnl_history.append_snapshot(
        "2026-06-01T14:30:00+00:00",
        net_liq=1_050_000.0,
        unrealized=-5.25,
        realized_cum=12.50,
        n_positions=2,
    )
    pnl_history.append_snapshot(
        "2026-06-01T14:35:00+00:00",
        net_liq=1_050_010.0,
        unrealized=None,
        realized_cum=12.50,
        n_positions=2,
    )

    rows = pnl_history.read_history()
    assert rows == [
        {
            "ts_utc": "2026-06-01T14:30:00+00:00",
            "net_liq": "1050000.0",
            "unrealized": "-5.25",
            "realized_cum": "12.5",
            "n_positions": "2",
        },
        {
            "ts_utc": "2026-06-01T14:35:00+00:00",
            "net_liq": "1050010.0",
            "unrealized": "",
            "realized_cum": "12.5",
            "n_positions": "2",
        },
    ]
    assert path.read_text(encoding="utf-8").count("ts_utc,net_liq,unrealized") == 1


def test_cumulative_realized_sums_only_sell_fill_detected_rows(tmp_path, monkeypatch):
    journal_path = tmp_path / "bh_swing_journal.csv"
    monkeypatch.setattr(journal, "JOURNAL_PATH", str(journal_path))

    journal.append(journal.JournalRow(
        event=journal.EVENT_FILL_DETECTED, side="buy", pnl=99.0,
    ))
    journal.append(journal.JournalRow(
        event=journal.EVENT_FILL_DETECTED, side="sell", pnl=-12.34,
    ))
    journal.append(journal.JournalRow(
        event=journal.EVENT_RUN_END, side="sell", pnl=50.0,
    ))
    journal.append(journal.JournalRow(
        event=journal.EVENT_FILL_DETECTED, side="sell", pnl=2.34,
    ))

    assert pnl_history.cumulative_realized() == -10.0
