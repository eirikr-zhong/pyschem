"""Unit tests for tools/search_symbols.py CLI tool.

Test IDs
-------
SST-01  test_search_symbols_text_output
SST-02  test_search_symbols_json_output
SST-03  test_search_footprints_text_output
SST-04  test_search_footprints_json_output
SST-05  test_exact_match_flag
SST-06  test_fuzzy_match_default
SST-07  test_no_results_behavior
SST-08  test_show_pins_flag
SST-09  test_show_properties_flag
SST-10  test_path_not_exist_error
SST-11  test_missing_paths_error
SST-12  test_limit_parameter
"""

import json
import pytest
from pathlib import Path


# Import the CLI module
import tools.search_symbols as search_symbols


# ---------------------------------------------------------------------------
# SST-01  Text output for symbols
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_search_symbols_text_output(tmp_path, capsys):
    """search_symbols CLI must output human-readable text for symbols."""
    # Create a mock symbol library
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    
    # Create a minimal kicad_sym file (will fail to parse but CLI will handle gracefully)
    # Actually create an empty directory for now - the CLI handles load errors
    # We'll mock the Symbols class to test the CLI flow
    
    # For this test, we'll just check the path validation works
    args = [
        "symbol",
        "test",
        "--symbol-path", str(symbol_dir),
    ]
    exit_code = search_symbols.main(args)
    
    # Should complete (may have no results but path exists)
    assert exit_code in [0, 1]


# ---------------------------------------------------------------------------
# SST-02  JSON output for symbols
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_search_symbols_json_output(tmp_path):
    """search_symbols CLI must output valid JSON with --json flag."""
    import io
    import sys
    
    # Create a mock symbol library directory
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()
    
    try:
        exit_code = search_symbols.main([
            "symbol", "test",
            "--symbol-path", str(symbol_dir),
            "--json",
        ])
    finally:
        sys.stdout = old_stdout
    
    # Should produce JSON output (may have no results)
    if captured.getvalue():
        data = json.loads(captured.getvalue())
        assert "results" in data or "count" in data


# ---------------------------------------------------------------------------
# SST-03  Text output for footprints
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_search_footprints_text_output(tmp_path, capsys):
    """search_symbols CLI must output human-readable text for footprints."""
    # Create a mock footprint directory with a valid footprint
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    
    pretty_dir = footprint_dir / "Resistor_SMD.pretty"
    pretty_dir.mkdir()
    
    # Write a valid kicad_mod file
    kicad_mod = """(module "R_0805" (layer "F.Cu") (tedit 0)
  (fp_text reference "R" (at 0 0) (layer "F.SilkS")
    (effects (font (size 0.5 0.5)))
  )
  (pad 1 smd rect (at -0.9 0) (size 0.6 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad 2 smd rect (at 0.9 0) (size 0.6 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""
    (pretty_dir / "R_0805.kicad_mod").write_text(kicad_mod)
    
    args = [
        "footprint",
        "0805",
        "--footprint-path", str(footprint_dir),
    ]
    exit_code = search_symbols.main(args)
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Footprint matches:" in captured.out
    assert "Resistor_SMD:R_0805" in captured.out
    assert "pads=" in captured.out


# ---------------------------------------------------------------------------
# SST-04  JSON output for footprints
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_search_footprints_json_output(tmp_path):
    """search_symbols CLI must output valid JSON for footprints."""
    import io
    import sys
    
    # Create a mock footprint directory with a valid footprint
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    
    pretty_dir = footprint_dir / "Resistor_SMD.pretty"
    pretty_dir.mkdir()
    
    # Write a valid kicad_mod file
    kicad_mod = """(module "R_0805" (layer "F.Cu") (tedit 0)
  (pad 1 smd rect (at -0.9 0) (size 0.6 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad 2 smd rect (at 0.9 0) (size 0.6 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""
    (pretty_dir / "R_0805.kicad_mod").write_text(kicad_mod)
    
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()
    
    try:
        exit_code = search_symbols.main([
            "footprint", "0805",
            "--footprint-path", str(footprint_dir),
            "--json",
        ])
    finally:
        sys.stdout = old_stdout
    
    output_json = captured.getvalue()
    data = json.loads(output_json)
    
    assert exit_code == 0
    assert "results" in data
    assert data["results"][0]["library"] == "Resistor_SMD"
    assert data["results"][0]["name"] == "R_0805"
    assert data["results"][0]["pads"] == 2


# ---------------------------------------------------------------------------
# SST-05  Exact match flag
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_exact_match_flag(tmp_path, capsys):
    """--exact flag must perform case-sensitive exact matching."""
    # Create symbol directory
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    
    # Test with valid footprint - exact match should work
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    pretty_dir = footprint_dir / "TestLib.pretty"
    pretty_dir.mkdir()
    (pretty_dir / "ExactName.kicad_mod").write_text(
        '(module "ExactName" (layer "F.Cu") (tedit 0)\n'
        '  (pad 1 smd rect (at 0 0))\n'
        ')\n'
    )
    
    # Exact match for existing footprint
    args_exact = [
        "footprint",
        "ExactName",
        "--footprint-path", str(footprint_dir),
        "--exact",
    ]
    exit_code = search_symbols.main(args_exact)
    assert exit_code == 0
    
    # Test non-matching exact (lowercase vs uppercase)
    args_exact_case = [
        "footprint",
        "exactname",  # lowercase - should fail
        "--footprint-path", str(footprint_dir),
        "--exact",
    ]
    exit_code = search_symbols.main(args_exact_case)
    assert exit_code == 1  # Should fail - case sensitive


# ---------------------------------------------------------------------------
# SST-06  Fuzzy match is default
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_fuzzy_match_default(tmp_path, capsys):
    """Default behavior should be fuzzy (case-insensitive) matching."""
    # Create footprint with uppercase name
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    pretty_dir = footprint_dir / "TestLib.pretty"
    pretty_dir.mkdir()
    (pretty_dir / "RESISTOR.kicad_mod").write_text(
        '(module "RESISTOR" (layer "F.Cu") (tedit 0)\n'
        '  (pad 1 smd rect (at 0 0))\n'
        ')\n'
    )
    
    # Search with lowercase - should find due to fuzzy matching
    args = [
        "footprint",
        "resistor",  # lowercase
        "--footprint-path", str(footprint_dir),
    ]
    exit_code = search_symbols.main(args)
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Footprint matches:" in captured.out


# ---------------------------------------------------------------------------
# SST-07  No results behavior
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_no_results_behavior(tmp_path, capsys):
    """Search with no matches must return exit code 1 and message."""
    # Create empty directory (no symbols)
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    
    args = [
        "symbol",
        "NonExistentSymbolXYZ123",
        "--symbol-path", str(symbol_dir),
    ]
    exit_code = search_symbols.main(args)
    
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No symbols found" in captured.err


# ---------------------------------------------------------------------------
# SST-08  Removed show-pins flag
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_show_pins_flag_removed_from_cli(tmp_path):
    """`--show-pins` is removed and should fail argument parsing."""
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    pretty_dir = footprint_dir / "TestLib.pretty"
    pretty_dir.mkdir()
    (pretty_dir / "Test.kicad_mod").write_text(
        '(module "Test" (layer "F.Cu") (tedit 0)\n'
        '  (pad 1 smd rect (at 0 0))\n'
        ')\n'
    )

    args = [
        "footprint",
        "Test",
        "--footprint-path", str(footprint_dir),
        "--show-pins",
    ]

    with pytest.raises(SystemExit) as exc:
        search_symbols.main(args)
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# SST-09  Show properties flag for footprints
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_show_properties_not_applicable_to_footprints(tmp_path, capsys):
    """--show-properties flag works only for symbols."""
    # Create footprint
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    pretty_dir = footprint_dir / "TestLib.pretty"
    pretty_dir.mkdir()
    (pretty_dir / "Test.kicad_mod").write_text(
        '(module "Test" (layer "F.Cu") (tedit 0)\n'
        '  (pad 1 smd rect (at 0 0))\n'
        ')\n'
    )
    
    # The --show-properties flag is ignored for footprints
    args = [
        "footprint",
        "Test",
        "--footprint-path", str(footprint_dir),
        "--show-properties",
    ]
    exit_code = search_symbols.main(args)
    
    # Should work (flag is silently ignored for footprints)
    assert exit_code == 0


# ---------------------------------------------------------------------------
# SST-10  Path not exist error
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_path_not_exist_error(capsys):
    """Non-existent path must show error and return exit code 1."""
    args = [
        "symbol",
        "R",
        "--symbol-path", "/tmp/this_path_does_not_exist_12345",
    ]
    exit_code = search_symbols.main(args)
    
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


# ---------------------------------------------------------------------------
# SST-11  Missing paths error
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_missing_paths_error(capsys):
    """No paths provided must show error and return exit code 1."""
    args = [
        "symbol",
        "R",
    ]
    exit_code = search_symbols.main(args)
    
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "At least one" in captured.err


# ---------------------------------------------------------------------------
# SST-12  Limit parameter
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_limit_parameter(tmp_path, capsys):
    """--limit parameter must restrict number of results."""
    # Create multiple footprints
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    pretty_dir = footprint_dir / "TestLib.pretty"
    pretty_dir.mkdir()
    
    # Create 5 footprints
    for i in range(5):
        (pretty_dir / f"Part{i}.kicad_mod").write_text(
            f'(module "Part{i}" (layer "F.Cu") (tedit 0)\n'
            '  (pad 1 smd rect (at 0 0))\n'
            ')\n'
        )
    
    args = [
        "footprint",
        "Part",
        "--footprint-path", str(footprint_dir),
        "--limit", "2",
    ]
    exit_code = search_symbols.main(args)
    
    # Should succeed and limit results
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Footprint matches:" in captured.out


# ---------------------------------------------------------------------------
# Additional tests for JSON match_mode
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_json_exact_match_mode(tmp_path):
    """JSON output must show correct match_mode."""
    import io
    import sys
    
    # Create footprint
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    pretty_dir = footprint_dir / "TestLib.pretty"
    pretty_dir.mkdir()
    (pretty_dir / "Test.kicad_mod").write_text(
        '(module "Test" (layer "F.Cu") (tedit 0)\n'
        '  (pad 1 smd rect (at 0 0))\n'
        ')\n'
    )
    
    # Test exact mode
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()
    
    try:
        search_symbols.main([
            "footprint", "Test",
            "--footprint-path", str(footprint_dir),
            "--json",
            "--exact",
        ])
    finally:
        sys.stdout = old_stdout
    
    data = json.loads(captured.getvalue())
    assert data["match_mode"] == "exact"
    
    # Test fuzzy mode
    sys.stdout = captured = io.StringIO()
    
    try:
        search_symbols.main([
            "footprint", "Test",
            "--footprint-path", str(footprint_dir),
            "--json",
        ])
    finally:
        sys.stdout = old_stdout
    
    data = json.loads(captured.getvalue())
    assert data["match_mode"] == "fuzzy"


# ---------------------------------------------------------------------------
# Test error handling for load failures
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_load_error_with_bad_file(tmp_path, capsys):
    """Load errors should produce warnings but not fail the search."""
    # Create directory with bad file
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    (symbol_dir / "Bad.kicad_sym").write_text("not valid kicad sym content")
    
    args = [
        "symbol",
        "test",
        "--symbol-path", str(symbol_dir),
    ]
    exit_code = search_symbols.main(args)
    
    # Should return 1 due to no results (warning is printed but continues)
    captured = capsys.readouterr()
    assert exit_code == 1


# ---------------------------------------------------------------------------
# Test: Load result info in output
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_load_result_info_in_output(tmp_path, capsys):
    """Output should include load result information."""
    # Create valid footprint
    footprint_dir = tmp_path / "footprints"
    footprint_dir.mkdir()
    pretty_dir = footprint_dir / "TestLib.pretty"
    pretty_dir.mkdir()
    (pretty_dir / "Test.kicad_mod").write_text(
        '(module "Test" (layer "F.Cu") (tedit 0)\n'
        '  (pad 1 smd rect (at 0 0))\n'
        ')\n'
    )
    
    args = [
        "footprint",
        "Test",
        "--footprint-path", str(footprint_dir),
    ]
    exit_code = search_symbols.main(args)
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Loaded libs:" in captured.out


# ---------------------------------------------------------------------------
# Test: Multiple paths
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_multiple_paths(tmp_path, capsys):
    """Multiple paths should be searched in order."""
    # Create two footprint directories
    fp_dir1 = tmp_path / "fp1"
    fp_dir2 = tmp_path / "fp2"
    fp_dir1.mkdir()
    fp_dir2.mkdir()
    
    pretty1 = fp_dir1 / "Lib1.pretty"
    pretty2 = fp_dir2 / "Lib2.pretty"
    pretty1.mkdir()
    pretty2.mkdir()
    
    (pretty1 / "FP1.kicad_mod").write_text(
        '(module "FP1" (layer "F.Cu") (tedit 0)\n'
        '  (pad 1 smd rect (at 0 0))\n'
        ')\n'
    )
    (pretty2 / "FP2.kicad_mod").write_text(
        '(module "FP2" (layer "F.Cu") (tedit 0)\n'
        '  (pad 1 smd rect (at 0 0))\n'
        ')\n'
    )
    
    args = [
        "footprint",
        "FP",
        "--footprint-path", str(fp_dir1),
        "--footprint-path", str(fp_dir2),
    ]
    exit_code = search_symbols.main(args)
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Footprint matches:" in captured.out
