"""Unit tests for environment-variable-based symbol/footprint path discovery.

Test IDs
--------
ENV-01  Single-path env var resolves symbol via get_default_symbols()
ENV-02  Multi-path env var (colon-separated) searches paths in order
ENV-03  Semicolons accepted as separators (in addition to colons)
ENV-04  Singleton takes priority over environment variables
ENV-05  Missing env vars return None from get_default_symbols()
ENV-06  Part('Device:R') auto-binds symbol when KICAD_SYMBOL_DIR is set
"""

import os
import pytest

import lib.symbols.symbols as _sym_mod
from lib.symbols.symbols import (
    Symbols,
    _parse_env_paths,
    configure_default_symbols,
    get_default_symbols,
)
from pyschem import Part


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_SYM = '''\
(kicad_symbol_lib
\t(version 20211014)
\t(generator "pyschem_test")
\t(symbol "R"
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
\t\t(symbol "R_1_1"
\t\t\t(pin passive line (at -2.54 0 180) (length 2.54)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t\t(pin passive line (at 2.54 0 0) (length 2.54)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27)))))))
)'''


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the global singleton and env vars before/after every test."""
    original = _sym_mod._DEFAULT_SYMBOLS
    _sym_mod._DEFAULT_SYMBOLS = None
    env_backup = {k: os.environ.pop(k, None) for k in ("KICAD_SYMBOL_DIR", "KICAD_FOOTPRINT_DIR")}
    yield
    _sym_mod._DEFAULT_SYMBOLS = original
    for k, v in env_backup.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def sym_dir(tmp_path):
    """A temp dir with a Device.kicad_sym file."""
    d = tmp_path / "syms"
    d.mkdir()
    (d / "Device.kicad_sym").write_text(MINIMAL_SYM)
    return d


@pytest.fixture
def second_sym_dir(tmp_path):
    """A second temp dir with an Amplifier.kicad_sym file."""
    d = tmp_path / "syms2"
    d.mkdir()
    content = MINIMAL_SYM.replace('"R"', '"OpAmp"', 1).replace(
        '(symbol "R"', '(symbol "OpAmp"', 1
    )
    (d / "Amplifier.kicad_sym").write_text(content)
    return d


# ---------------------------------------------------------------------------
# ENV-01  Single-path env var
# ---------------------------------------------------------------------------

def test_single_path_env_var_finds_symbol(sym_dir):
    """get_default_symbols() uses KICAD_SYMBOL_DIR when singleton is unset."""
    os.environ["KICAD_SYMBOL_DIR"] = str(sym_dir)

    mgr = get_default_symbols()
    assert mgr is not None
    sym = mgr.find_symbol("Device", "R")
    assert sym.name == "R"


# ---------------------------------------------------------------------------
# ENV-02  Multi-path colon-separated env var
# ---------------------------------------------------------------------------

def test_multi_path_env_var_colon_separated(sym_dir, second_sym_dir):
    """Colon-separated KICAD_SYMBOL_DIR searches both paths in order."""
    os.environ["KICAD_SYMBOL_DIR"] = f"{sym_dir}:{second_sym_dir}"

    mgr = get_default_symbols()
    assert mgr is not None

    sym_r = mgr.find_symbol("Device", "R")
    assert sym_r.name == "R"

    sym_amp = mgr.find_symbol("Amplifier", "OpAmp")
    assert sym_amp.name == "OpAmp"


# ---------------------------------------------------------------------------
# ENV-03  Semicolons accepted as separators
# ---------------------------------------------------------------------------

def test_semicolon_separator_accepted(sym_dir, second_sym_dir):
    """Semicolons work as path separators, same as colons."""
    os.environ["KICAD_SYMBOL_DIR"] = f"{sym_dir};{second_sym_dir}"

    paths = _parse_env_paths("KICAD_SYMBOL_DIR")
    assert str(sym_dir) in paths
    assert str(second_sym_dir) in paths

    mgr = get_default_symbols()
    assert mgr is not None
    assert mgr.find_symbol("Device", "R").name == "R"
    assert mgr.find_symbol("Amplifier", "OpAmp").name == "OpAmp"


# ---------------------------------------------------------------------------
# ENV-04  Singleton takes priority over environment variables
# ---------------------------------------------------------------------------

def test_singleton_has_priority_over_env_var(sym_dir, second_sym_dir):
    """When a singleton is configured, env vars are ignored."""
    # Singleton points only at sym_dir (Device library)
    singleton = configure_default_symbols(symbol_paths=[str(sym_dir)], preload=False)

    # Env var points at second_sym_dir only (Amplifier library, no Device)
    os.environ["KICAD_SYMBOL_DIR"] = str(second_sym_dir)

    mgr = get_default_symbols()
    assert mgr is singleton, "Expected the configured singleton to be returned"

    # Device:R is findable (singleton path) — env var path not consulted
    sym = mgr.find_symbol("Device", "R")
    assert sym.name == "R"


# ---------------------------------------------------------------------------
# ENV-05  Missing env vars → None
# ---------------------------------------------------------------------------

def test_missing_env_vars_return_none():
    """get_default_symbols() returns None when no singleton and no env vars."""
    # Both env vars are absent (reset_singleton fixture cleared them)
    result = get_default_symbols()
    assert result is None


# ---------------------------------------------------------------------------
# ENV-06  Part auto-binding uses KICAD_SYMBOL_DIR
# ---------------------------------------------------------------------------

def test_part_auto_binds_via_env_var(sym_dir):
    """Part('Device:R') auto-attaches SymbolData when KICAD_SYMBOL_DIR is set."""
    os.environ["KICAD_SYMBOL_DIR"] = str(sym_dir)

    part = Part("Device:R", ref="R99")
    # If auto-binding worked, available_pins is non-empty
    assert part.available_pins, (
        "Part should have auto-attached SymbolData via KICAD_SYMBOL_DIR, "
        f"but available_pins={part.available_pins!r}"
    )
    assert "1" in part.available_pins
    assert "2" in part.available_pins
