"""Unit tests for ``tools/search_symbols.py`` CLI tool.

Test IDs
--------
SST-01  test_search_symbols_text_output
SST-02  test_search_symbols_json_output
SST-03  test_exact_match_flag
SST-04  test_fuzzy_match_default
SST-05  test_no_results_behavior
SST-06  test_show_pins_flag_removed_from_cli
SST-07  test_show_properties_flag_in_output
SST-08  test_path_not_exist_error
SST-09  test_missing_paths_error
SST-10  test_limit_parameter
SST-11  test_json_exact_match_mode
SST-12  test_load_error_with_bad_file
SST-13  test_load_result_info_in_output
SST-14  test_multiple_paths
"""

import json

import pytest

import tools.search_symbols as search_symbols


def _symbol_block(name: str, description: str) -> str:
    return f"""\
\t(symbol "{name}"
\t\t(pin_names (offset 0))
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "{name}" (at 0 0 0) (effects (font (size 1.27 1.27))))
\t\t(property "Description" "{description}" (at 0 0 0) (effects (font (size 1.27 1.27))))
\t\t(symbol "{name}_0_1"
\t\t\t(rectangle (start -1.27 -2.54) (end 1.27 2.54)
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type background))))
\t\t(symbol "{name}_1_1"
\t\t\t(pin passive line (at -2.54 0 180) (length 2.54)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t\t(pin passive line (at 2.54 0 0) (length 2.54)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))))
\t)
"""


def _write_library(base_dir, lib_name: str, symbols: list[tuple[str, str]]) -> None:
    body = "".join(_symbol_block(name, description) for name, description in symbols)
    content = (
        "(kicad_symbol_lib\n"
        '\t(version 20211014)\n'
        '\t(generator "pyschem_test")\n'
        f"{body}"
        ")\n"
    )
    (base_dir / f"{lib_name}.kicad_sym").write_text(content)


@pytest.mark.unit
@pytest.mark.P0
def test_search_symbols_text_output(tmp_path, capsys):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "Device", [("R", "Resistor")])

    exit_code = search_symbols.main(["R", "--symbol-path", str(symbol_dir)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Symbol matches:" in captured.out
    assert "Device:R" in captured.out


@pytest.mark.unit
@pytest.mark.P0
def test_search_symbols_json_output(tmp_path, capsys):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "Device", [("R", "Resistor")])

    exit_code = search_symbols.main(["R", "--symbol-path", str(symbol_dir), "--json"])

    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] >= 1
    assert any(result["name"] == "R" for result in data["results"])


@pytest.mark.unit
@pytest.mark.P0
def test_exact_match_flag(tmp_path):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "ExactLib", [("ExactName", "Exact test")])

    ok = search_symbols.main(
        ["ExactName", "--symbol-path", str(symbol_dir), "--exact"]
    )
    fail = search_symbols.main(
        ["exactname", "--symbol-path", str(symbol_dir), "--exact"]
    )

    assert ok == 0
    assert fail == 1


@pytest.mark.unit
@pytest.mark.P1
def test_fuzzy_match_default(tmp_path):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "TestLib", [("RESISTOR", "Uppercase name")])

    exit_code = search_symbols.main(["resistor", "--symbol-path", str(symbol_dir)])
    assert exit_code == 0


@pytest.mark.unit
@pytest.mark.P0
def test_no_results_behavior(tmp_path, capsys):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "Device", [("R", "Resistor")])

    exit_code = search_symbols.main(
        ["NonExistentSymbolXYZ123", "--symbol-path", str(symbol_dir)]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No symbols found" in captured.err


@pytest.mark.unit
@pytest.mark.P1
def test_show_pins_flag_removed_from_cli(tmp_path):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "Device", [("R", "Resistor")])

    with pytest.raises(SystemExit) as exc:
        search_symbols.main(
            ["R", "--symbol-path", str(symbol_dir), "--show-pins"]
        )
    assert exc.value.code == 2


@pytest.mark.unit
@pytest.mark.P1
def test_show_properties_flag_in_output(tmp_path, capsys):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "Device", [("R", "Resistor for property test")])

    exit_code = search_symbols.main(
        ["R", "--symbol-path", str(symbol_dir), "--show-properties"]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Properties:" in captured.out
    assert "Description: Resistor for property test" in captured.out


@pytest.mark.unit
@pytest.mark.P0
def test_path_not_exist_error(capsys):
    exit_code = search_symbols.main(
        ["R", "--symbol-path", "/tmp/this_path_does_not_exist_12345"]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


@pytest.mark.unit
@pytest.mark.P0
def test_missing_paths_error(capsys):
    exit_code = search_symbols.main(["R"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "At least one --symbol-path" in captured.err


@pytest.mark.unit
@pytest.mark.P1
def test_limit_parameter(tmp_path, capsys):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(
        symbol_dir,
        "Many",
        [(f"Part{i}", f"Part number {i}") for i in range(5)],
    )

    exit_code = search_symbols.main(
        ["Part", "--symbol-path", str(symbol_dir), "--limit", "2"]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Symbol matches: 2" in captured.out


@pytest.mark.unit
@pytest.mark.P1
def test_json_exact_match_mode(tmp_path, capsys):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "ModeLib", [("Test", "Mode test")])

    search_symbols.main(
        ["Test", "--symbol-path", str(symbol_dir), "--json", "--exact"]
    )
    data = json.loads(capsys.readouterr().out)
    assert data["match_mode"] == "exact"

    search_symbols.main(
        ["Test", "--symbol-path", str(symbol_dir), "--json"]
    )
    data = json.loads(capsys.readouterr().out)
    assert data["match_mode"] == "fuzzy"


@pytest.mark.unit
@pytest.mark.P1
def test_load_error_with_bad_file(tmp_path, capsys):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    (symbol_dir / "Bad.kicad_sym").write_text("not valid kicad sym content")

    exit_code = search_symbols.main(["test", "--symbol-path", str(symbol_dir)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Warning:" in captured.err


@pytest.mark.unit
@pytest.mark.P1
def test_load_result_info_in_output(tmp_path, capsys):
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    _write_library(symbol_dir, "Device", [("Test", "Load result test")])

    exit_code = search_symbols.main(["Test", "--symbol-path", str(symbol_dir)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Loaded libs:" in captured.out


@pytest.mark.unit
@pytest.mark.P1
def test_multiple_paths(tmp_path, capsys):
    sym_dir1 = tmp_path / "sym1"
    sym_dir2 = tmp_path / "sym2"
    sym_dir1.mkdir()
    sym_dir2.mkdir()
    _write_library(sym_dir1, "Lib1", [("A", "from first dir")])
    _write_library(sym_dir2, "Lib2", [("B", "from second dir")])

    exit_code = search_symbols.main(
        [
            "B",
            "--symbol-path",
            str(sym_dir1),
            "--symbol-path",
            str(sym_dir2),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Lib2:B" in captured.out
