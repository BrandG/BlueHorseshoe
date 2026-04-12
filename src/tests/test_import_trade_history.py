"""Tests for trade history CSV import helpers."""

from datetime import date

from import_trade_history import (
    build_import_documents,
    fill_to_doc,
    format_dry_run_summary,
    generate_fill_documents,
    parse_csv,
    review_from_position,
    synthesize_positions,
)


def _csv(tmp_path, content: str):
    path = tmp_path / "trade_history.csv"
    path.write_text(content)
    return path


def _sample_csv(*rows: str) -> str:
    return "Date Received,Type,Quantity,Asset,Price\n" + "\n".join(rows) + "\n"


def test_parse_csv(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "12/12/2024,SOLD,2.1,KEX,117.597143",
            "12/12/2024,BOUGHT,14,FEIM,16.6",
        ),
    )

    fills = parse_csv(str(path))

    assert fills[0].date == date(2024, 12, 12)
    assert fills[0].side == "sell"
    assert fills[0].quantity == 2.1
    assert fills[0].symbol == "KEX"
    assert fills[0].price == 117.597143
    assert fills[1].side == "buy"


def test_fill_generation(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "12/12/2024,BOUGHT,14,FEIM,16.6",
            "12/12/2024,BOUGHT,0.25,FEIM,16.6",
            "12/12/2024,SOLD,14,FEIM,16.6",
        ),
    )

    docs = generate_fill_documents(synthesize_positions(parse_csv(str(path)))[1])

    assert docs[0]["fill_id"] == "csv_2024-12-12_FEIM_buy_1"
    assert docs[1]["fill_id"] == "csv_2024-12-12_FEIM_buy_2"
    assert docs[2]["fill_id"] == "csv_2024-12-12_FEIM_sell_1"
    assert docs[0]["side"] == "buy"
    assert docs[1]["quantity"] == 0.25
    assert docs[0]["commission"] == 0.0
    assert docs[0]["source"] == "csv"


def test_fifo_simple(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "1/2/2025,BOUGHT,10,ABC,10",
            "1/5/2025,SOLD,10,ABC,12",
        ),
    )

    positions, included, warnings = synthesize_positions(parse_csv(str(path)))

    assert len(included) == 2
    assert warnings == []
    assert len(positions) == 1
    assert positions[0]["status"] == "closed"
    assert positions[0]["total_quantity"] == 10
    assert positions[0]["actual_entry"] == 10
    assert positions[0]["legs"][0]["exit_price"] == 12
    assert positions[0]["total_pnl"] == 20
    assert positions[0]["legs"][0]["hold_days"] == 3


def test_fifo_split_fills(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "12/12/2024,BOUGHT,14,FEIM,16.6",
            "12/12/2024,BOUGHT,0.25,FEIM,16.6",
            "12/12/2024,SOLD,14,FEIM,16.6",
            "12/12/2024,SOLD,0.25,FEIM,16.6",
        ),
    )

    positions, _, _ = synthesize_positions(parse_csv(str(path)))

    assert len(positions) == 1
    assert positions[0]["total_quantity"] == 14.25
    assert positions[0]["actual_entry"] == 16.6
    assert positions[0]["legs"][0]["exit_price"] == 16.6
    assert positions[0]["total_pnl"] == 0
    assert positions[0]["legs"][0]["entry_fill_id"] == "csv_2024-12-12_FEIM_buy_1,csv_2024-12-12_FEIM_buy_2"


def test_fifo_reentry(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "1/2/2025,BOUGHT,10,ABC,10",
            "1/3/2025,SOLD,10,ABC,11",
            "1/4/2025,BOUGHT,5,ABC,20",
            "1/5/2025,SOLD,5,ABC,19",
        ),
    )

    positions, _, _ = synthesize_positions(parse_csv(str(path)))

    assert len(positions) == 2
    assert positions[0]["position_id"] == "pos_csv_2025-01-02_ABC_1"
    assert positions[0]["total_pnl"] == 10
    assert positions[1]["position_id"] == "pos_csv_2025-01-04_ABC_1"
    assert positions[1]["total_pnl"] == -5


def test_fifo_dca(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "1/2/2025,BOUGHT,10,IAU,10",
            "1/3/2025,BOUGHT,10,IAU,20",
            "1/4/2025,SOLD,15,IAU,30",
            "1/5/2025,SOLD,5,IAU,40",
        ),
    )

    positions, _, _ = synthesize_positions(parse_csv(str(path)))

    assert len(positions) == 1
    assert positions[0]["actual_entry"] == 15
    assert positions[0]["legs"][0]["exit_price"] == 32.5
    assert positions[0]["total_pnl"] == 350


def test_orphan_sell_skipped(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "12/12/2024,SOLD,2.1,KEX,117.597143",
            "12/12/2024,BOUGHT,14,FEIM,16.6",
            "12/12/2024,SOLD,14,FEIM,16.6",
        ),
    )

    fill_docs, positions, reviews, warnings = build_import_documents(parse_csv(str(path)))

    assert len(fill_docs) == 2
    assert len(positions) == 1
    assert positions[0]["tags"] == ["csv_import", "pre_bh"]
    assert reviews[0]["tags"] == ["csv_import", "pre_bh"]
    assert warnings == ["Skipped: KEX (orphan sell, no prior buy)"]
    assert all(doc["symbol"] != "KEX" for doc in fill_docs)


def test_dry_run_output(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "12/12/2024,SOLD,2.1,KEX,117.597143",
            "12/12/2024,BOUGHT,14,FEIM,16.6",
            "12/12/2024,SOLD,14,FEIM,16.6",
        ),
    )
    parsed = parse_csv(str(path))
    fill_docs, positions, reviews, warnings = build_import_documents(parsed)

    output = format_dry_run_summary(str(path), len(parsed), fill_docs, positions, reviews, warnings)

    assert f"Parsed 3 fills from {path}" in output
    assert "Skipped: KEX (orphan sell, no prior buy)" in output
    assert "Generated: 2 fill documents, 1 positions, 1 reviews" in output
    assert "Position Summary:" in output
    assert "Totals: 0 wins, 0 losses, 1 breakeven" in output


def test_position_pnl(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "1/2/2025,BOUGHT,3,XYZ,10",
            "1/3/2025,BOUGHT,2,XYZ,20",
            "1/4/2025,SOLD,4,XYZ,25",
            "1/5/2025,SOLD,1,XYZ,30",
        ),
    )

    positions, _, _ = synthesize_positions(parse_csv(str(path)))

    assert positions[0]["total_pnl"] == 60
    assert positions[0]["legs"][0]["pnl"] == 60


def test_review_outcome(tmp_path):
    win = {
        "position_id": "pos_csv_2025-01-02_WIN_1",
        "symbol": "WIN",
        "opened_at": fill_to_doc(parse_csv(str(_csv(tmp_path, _sample_csv("1/2/2025,BOUGHT,1,WIN,10"))))[0])["exec_time"],
        "actual_entry": 10,
        "total_pnl": 1,
        "legs": [{"exit_price": 11, "hold_days": 1}],
        "tags": ["csv_import", "pre_bh"],
    }
    loss = dict(win, position_id="pos_csv_2025-01-02_LOSS_1", symbol="LOSS", total_pnl=-1)
    flat = dict(win, position_id="pos_csv_2025-01-02_FLAT_1", symbol="FLAT", total_pnl=0)

    assert review_from_position(win)["outcome"] == "win"
    assert review_from_position(loss)["outcome"] == "loss"
    assert review_from_position(flat)["outcome"] == "breakeven"


def test_era_tags(tmp_path):
    path = _csv(
        tmp_path,
        _sample_csv(
            "12/31/2025,BOUGHT,1,OLD,10",
            "12/31/2025,SOLD,1,OLD,11",
            "1/2/2026,BOUGHT,1,NEW,10",
            "1/2/2026,SOLD,1,NEW,11",
        ),
    )

    _, positions, reviews, _ = build_import_documents(parse_csv(str(path)))
    by_symbol = {position["symbol"]: position for position in positions}
    reviews_by_symbol = {review["symbol"]: review for review in reviews}

    assert by_symbol["OLD"]["tags"] == ["csv_import", "pre_bh"]
    assert reviews_by_symbol["OLD"]["tags"] == ["csv_import", "pre_bh"]
    assert by_symbol["NEW"]["tags"] == ["csv_import", "bh_v2"]
    assert reviews_by_symbol["NEW"]["tags"] == ["csv_import", "bh_v2"]
