from bluehorseshoe.core.invalid_symbols import (
    load_invalid_symbol_set,
    load_invalid_symbols,
    resolve_invalid_symbols_path,
)


def test_load_invalid_symbols_reads_file(tmp_path):
    invalid_file = tmp_path / "invalid_symbols.txt"
    invalid_file.write_text("AAPL\nmsft\n\n", encoding="utf-8")

    assert load_invalid_symbols(invalid_file) == ["AAPL", "msft"]
    assert load_invalid_symbol_set(invalid_file) == {"AAPL", "MSFT"}


def test_resolve_invalid_symbols_path_uses_base_path(tmp_path):
    resolved = resolve_invalid_symbols_path(str(tmp_path))
    assert resolved == tmp_path / "invalid_symbols.txt"
