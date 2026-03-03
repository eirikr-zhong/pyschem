"""Unit tests for ``lib/symbols/`` symbol loading and lookup."""

from pathlib import Path

import pytest

from pyschem import PinDefinition, SymbolData, SymbolNotFoundError, Symbols


@pytest.mark.unit
@pytest.mark.P0
def test_symbols_init_no_crash():
    symbols = Symbols()
    assert symbols is not None
    assert symbols.symbol_paths == []


@pytest.mark.unit
@pytest.mark.P0
def test_symbols_init_with_paths():
    symbols = Symbols(symbol_paths=["/tmp/kicad-symbols"])
    assert len(symbols.symbol_paths) == 1


@pytest.mark.unit
@pytest.mark.P0
def test_find_symbol_returns_data(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    symbol = symbols.find_symbol("Device", "R")

    assert isinstance(symbol, SymbolData)
    assert symbol.name == "R"
    assert symbol.lib == "Device"
    assert len(symbol.pins) >= 2


@pytest.mark.unit
@pytest.mark.P0
def test_find_symbol_returns_pins(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    symbol = symbols.find_symbol("Device", "R")

    assert len(symbol.pins) > 0
    pin = symbol.pins[0]
    assert isinstance(pin, PinDefinition)
    assert hasattr(pin, "number")
    assert hasattr(pin, "name")
    assert hasattr(pin, "type")


@pytest.mark.unit
@pytest.mark.P0
def test_symbol_not_found_raises(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    with pytest.raises(SymbolNotFoundError) as exc_info:
        symbols.find_symbol("Device", "NonExistent")
    assert "NonExistent" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.P0
def test_library_not_found_raises():
    symbols = Symbols(symbol_paths=["/tmp/nonexistent"])
    with pytest.raises(SymbolNotFoundError) as exc_info:
        symbols.find_symbol("NonExistentLib", "R")
    assert "NonExistentLib" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.P1
def test_multiple_paths_priority(tmp_path):
    lib1_dir = tmp_path / "lib1"
    lib2_dir = tmp_path / "lib2"
    lib1_dir.mkdir()
    lib2_dir.mkdir()

    (lib1_dir / "Device.kicad_sym").write_text(
        "(kicad_symbol_lib (version 20211014) (generator test)\n"
        '  (symbol "R" (pin_names (offset 0)) (in_bom yes) (on_board yes)\n'
        '    (symbol "R_1_1"\n'
        '      (pin passive line (at -1.016 0 180) (length 1.016) (name "~" (effects (font (size 1.27 1.27))))'
        '        (number "1" (effects (font (size 1.27 1.27)))))\n'
        '      (pin passive line (at 1.016 0 0) (length 1.016) (name "~" (effects (font (size 1.27 1.27))))'
        '        (number "2" (effects (font (size 1.27 1.27)))))))\n'
        ")\n"
    )
    (lib2_dir / "Device.kicad_sym").write_text(
        "(kicad_symbol_lib (version 20211014) (generator test)\n"
        '  (symbol "C" (pin_names (offset 0)) (in_bom yes) (on_board yes))\n'
        ")\n"
    )

    symbols = Symbols(symbol_paths=[str(lib1_dir), str(lib2_dir)])
    symbol = symbols.find_symbol("Device", "R")
    assert symbol.name == "R"


@pytest.mark.unit
@pytest.mark.P1
def test_symbol_data_pins_parsed(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    symbol = symbols.find_symbol("Device", "R")
    for pin in symbol.pins:
        assert pin.number
        assert pin.name is not None
        assert pin.type is not None
        assert isinstance(pin.x, (int, float))
        assert isinstance(pin.y, (int, float))


@pytest.mark.unit
@pytest.mark.P1
def test_path_expansion_tilde(tmp_path):
    symbols = Symbols(symbol_paths=[str(tmp_path)])
    for path in symbols.symbol_paths:
        assert not str(path).startswith("~")


@pytest.mark.unit
@pytest.mark.P1
def test_library_caching(tmp_path):
    (tmp_path / "TestLib.kicad_sym").write_text(
        "(kicad_symbol_lib (version 20211014) (generator test)\n"
        '  (symbol "A" (pin_names (offset 0)) (in_bom yes) (on_board yes))\n'
        ")\n"
    )

    symbols = Symbols(symbol_paths=[str(tmp_path)])
    sym1 = symbols.find_symbol("TestLib", "A")
    sym2 = symbols.find_symbol("TestLib", "A")
    assert sym1 is sym2


@pytest.mark.unit
@pytest.mark.P1
def test_load_real_symbol_fixture():
    from lib.symbols.symbol_parser import parse_kicad_sym_file

    fixture_path = Path("tests/fixtures/kicad/Amplifier_Buffer.kicad_sym")
    symbols = parse_kicad_sym_file(fixture_path)
    assert len(symbols) == 11


@pytest.mark.unit
@pytest.mark.P1
def test_real_symbol_has_pins():
    from lib.symbols.symbol_parser import parse_kicad_sym_file

    fixture_path = Path("tests/fixtures/kicad/Amplifier_Buffer.kicad_sym")
    symbols = parse_kicad_sym_file(fixture_path)
    buf602 = next((s for s in symbols if s.name == "BUF602xD"), None)
    assert buf602 is not None
    assert len(buf602.pins) > 0


@pytest.mark.unit
@pytest.mark.P1
def test_real_symbol_properties():
    from lib.symbols.symbol_parser import parse_kicad_sym_file

    fixture_path = Path("tests/fixtures/kicad/Amplifier_Buffer.kicad_sym")
    symbols = parse_kicad_sym_file(fixture_path)
    buf602 = next((s for s in symbols if s.name == "BUF602xD"), None)
    assert buf602 is not None
    assert len(buf602.properties) > 0
    assert "Description" in buf602.properties


@pytest.mark.unit
@pytest.mark.P1
def test_symbols_load_all_with_real_fixtures():
    symbols = Symbols(symbol_paths=[str(Path("tests/fixtures/kicad"))])
    result = symbols.load_all()
    assert result.success
    assert result.loaded_count > 0
    assert "Amplifier_Buffer" in symbols.list_symbol_libraries()


@pytest.mark.unit
@pytest.mark.P1
def test_query_from_memory_after_load():
    symbols = Symbols(symbol_paths=[str(Path("tests/fixtures/kicad"))])
    symbols.load_all()
    symbol = symbols.find_symbol("Amplifier_Buffer", "BUF602xD")
    assert symbol is not None
    assert symbol.name == "BUF602xD"
    assert len(symbol.pins) > 0


@pytest.mark.unit
@pytest.mark.P1
def test_symbol_not_found_error():
    symbols = Symbols(symbol_paths=[str(Path("tests/fixtures/kicad"))])
    symbols.load_all()
    with pytest.raises(SymbolNotFoundError):
        symbols.find_symbol("Amplifier_Buffer", "NonExistentSymbol")


@pytest.mark.unit
def test_search_symbols_returns_matches(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    symbols.load_all()
    rows = symbols.search_symbols("res")
    assert any(symbol.name == "R" for symbol in rows)


@pytest.mark.unit
def test_load_all_returns_cached_result(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    r1 = symbols.load_all()
    r2 = symbols.load_all()
    assert r1 is r2


@pytest.mark.unit
def test_load_all_missing_symbol_path(tmp_path):
    symbols = Symbols(symbol_paths=[str(tmp_path / "no_such_dir")])
    result = symbols.load_all()
    assert result.error_count >= 1
    assert any("not found" in error for error in result.errors)


@pytest.mark.unit
def test_load_all_raise_on_error_symbol(tmp_path):
    sym_dir = tmp_path / "syms"
    sym_dir.mkdir()
    (sym_dir / "Bad.kicad_sym").write_text("NOT VALID CONTENT")

    symbols = Symbols(symbol_paths=[str(sym_dir)])
    with pytest.raises(Exception):
        symbols.load_all(raise_on_error=True)


@pytest.mark.unit
def test_load_all_skips_bad_symbol_file(tmp_path):
    sym_dir = tmp_path / "syms"
    sym_dir.mkdir()
    (sym_dir / "Bad.kicad_sym").write_text("NOT VALID CONTENT")

    symbols = Symbols(symbol_paths=[str(sym_dir)])
    result = symbols.load_all()
    assert result.error_count >= 1


@pytest.mark.unit
def test_load_result_property(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    assert symbols.load_result is None
    symbols.load_all()
    assert symbols.load_result is not None
    assert symbols.is_loaded


@pytest.mark.unit
def test_get_symbol_returns_none_when_not_found():
    symbols = Symbols(symbol_paths=["/tmp/nonexistent"])
    result = symbols.get_symbol("NoLib", "NoSym")
    assert result is None


@pytest.mark.unit
def test_get_symbol_returns_data(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    result = symbols.get_symbol("Device", "R")
    assert result is not None
    assert result.name == "R"


@pytest.mark.unit
def test_list_symbol_libraries_triggers_load(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    assert not symbols.is_loaded
    libs = symbols.list_symbol_libraries()
    assert symbols.is_loaded
    assert "Device" in libs


@pytest.mark.unit
def test_list_symbols_auto_loads(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    names = symbols.list_symbols("Device")
    assert "R" in names


@pytest.mark.unit
def test_list_symbols_unknown_lib_returns_empty():
    symbols = Symbols(symbol_paths=["/tmp/nonexistent"])
    names = symbols.list_symbols("NoSuchLib")
    assert names == []


@pytest.mark.unit
def test_get_symbol_library_path_is_file(tmp_path):
    sym_file = tmp_path / "Direct.kicad_sym"
    sym_file.write_text(
        "(kicad_symbol_lib (version 20211014) (generator test)\n"
        '  (symbol "X" (pin_names (offset 0)) (in_bom yes) (on_board yes))\n'
        ")\n"
    )
    symbols = Symbols(symbol_paths=[str(sym_file)])
    result = symbols.find_symbol("Direct", "X")
    assert result.name == "X"


@pytest.mark.unit
def test_search_symbols_empty_query(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    symbols.load_all()
    assert symbols.search_symbols("") == []
    assert symbols.search_symbols("   ") == []


@pytest.mark.unit
def test_search_symbols_auto_loads(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    assert not symbols.is_loaded
    results = symbols.search_symbols("R")
    assert symbols.is_loaded
    assert len(results) > 0


@pytest.mark.unit
def test_search_symbols_limit(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    symbols.load_all()
    results = symbols.search_symbols("R", limit=1)
    assert len(results) <= 1


@pytest.mark.unit
def test_list_symbols_lazy_fallback(mock_symbol_dir):
    symbols = Symbols(symbol_paths=[mock_symbol_dir])
    symbols._loaded = True
    symbols._symbol_index = {}
    names = symbols.list_symbols("Device")
    assert "R" in names
