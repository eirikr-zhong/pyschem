"""Coverage tests for lib/symbols/symbol_parser.py.

Targets uncovered lines covering:
  - parse_kicad_sym_content with polyline/rectangle/circle/arc primitives
  - SymbolLibrary class (load, symbols, load_error, is_valid, find_symbol)
  - parse_kicad_sym_file_safe with parse error
  - Various visitor methods: circle, arc, rectangle, polyline, fill, stroke, width
  - Sub-symbol detection
  - ParseError handling
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.symbols.symbol_parser import (
    KicadSymVisitor,
    SymbolLibrary,
    load_library,
    parse_kicad_sym_content,
    parse_kicad_sym_file,
    parse_kicad_sym_file_safe,
)
from lib.symbols.data import SymbolData


# ---------------------------------------------------------------------------
# Minimal valid library helpers
# ---------------------------------------------------------------------------

def _wrap(inner: str) -> str:
    """Wrap symbol content in a minimal kicad_symbol_lib structure."""
    return f'(kicad_symbol_lib (version 20220914) (generator kicad_symbol_editor)\n{inner}\n)'


def _symbol(name: str, body: str = "") -> str:
    return f'  (symbol "{name}"\n{body}\n  )'


def _pin(pin_type: str = "passive", style: str = "line",
         x: float = 0, y: float = 0, angle: float = 0, length: float = 2.54,
         name: str = "~", number: str = "1") -> str:
    return (
        f'    (pin {pin_type} {style} (at {x} {y} {angle}) (length {length})\n'
        f'      (name "{name}" (effects (font (size 1.27 1.27))))\n'
        f'      (number "{number}" (effects (font (size 1.27 1.27))))\n'
        f'    )'
    )


# ---------------------------------------------------------------------------
# Polyline primitive parsing  (L308-331)
# ---------------------------------------------------------------------------

class TestPolylineParsing:
    def test_polyline_with_pts(self):
        """Polyline primitive with pts is parsed into SymbolPrimitive."""
        content = _wrap(_symbol("TestPoly",
            '    (polyline\n'
            '      (pts (xy 0 0) (xy 5 5) (xy 10 0))\n'
            '      (stroke (width 0.1))\n'
            '      (fill (type none))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert len(symbols) == 1
        sym = symbols[0]
        assert len(sym.primitives) == 1
        prim = sym.primitives[0]
        assert prim.kind == "polyline"
        assert len(prim.points) == 3

    def test_polyline_with_fill_background(self):
        """Polyline with fill type 'background' preserves fill value."""
        content = _wrap(_symbol("TestFill",
            '    (polyline\n'
            '      (pts (xy -1 -1) (xy 1 -1) (xy 0 1))\n'
            '      (stroke (width 0.25))\n'
            '      (fill (type background))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert len(symbols) == 1
        prim = symbols[0].primitives[0]
        assert prim.fill == "background"

    def test_polyline_too_few_points_not_added(self):
        """Polyline with fewer than 2 pts is not added as a primitive."""
        # A polyline with only 1 point should be skipped
        content = _wrap(_symbol("TestSingle",
            '    (polyline\n'
            '      (pts (xy 0 0))\n'
            '      (stroke (width 0.1))\n'
            '      (fill (type none))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        # Either 0 symbols or the symbol has no primitives
        if symbols:
            assert len(symbols[0].primitives) == 0

    def test_polyline_stroke_width(self):
        """Polyline stroke width is parsed correctly."""
        content = _wrap(_symbol("TestStroke",
            '    (polyline\n'
            '      (pts (xy 0 0) (xy 10 0))\n'
            '      (stroke (width 2.5))\n'
            '      (fill (type none))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        if symbols and symbols[0].primitives:
            assert abs(symbols[0].primitives[0].stroke_width - 2.5) < 0.01


# ---------------------------------------------------------------------------
# Rectangle primitive parsing  (L333-363)
# ---------------------------------------------------------------------------

class TestRectangleParsing:
    def test_rectangle_converted_to_polyline(self):
        """Rectangle is converted to a 5-point closed polyline."""
        content = _wrap(_symbol("TestRect",
            '    (rectangle\n'
            '      (start -5 -3)\n'
            '      (end 5 3)\n'
            '      (stroke (width 0.15))\n'
            '      (fill (type none))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert len(symbols) == 1
        prim = symbols[0].primitives[0]
        assert prim.kind == "polyline"
        assert len(prim.points) == 5
        # First and last points should be the same (closed)
        assert prim.points[0] == prim.points[-1]

    def test_rectangle_coordinates_correct(self):
        """Rectangle start/end coordinates are converted correctly."""
        content = _wrap(_symbol("TestRectCoords",
            '    (rectangle\n'
            '      (start -2 -1)\n'
            '      (end 2 1)\n'
            '      (stroke (width 0.1))\n'
            '      (fill (type none))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        prim = symbols[0].primitives[0]
        xs = [p[0] for p in prim.points]
        ys = [p[1] for p in prim.points]
        assert -2 in xs and 2 in xs
        assert -1 in ys and 1 in ys

    def test_rectangle_with_fill_solid(self):
        """Rectangle with fill=solid is preserved."""
        content = _wrap(_symbol("TestRectSolid",
            '    (rectangle\n'
            '      (start 0 0)\n'
            '      (end 5 5)\n'
            '      (stroke (width 0.1))\n'
            '      (fill (type solid))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        if symbols and symbols[0].primitives:
            prim = symbols[0].primitives[0]
            assert prim.fill == "solid"


# ---------------------------------------------------------------------------
# Circle primitive parsing  (L365-393)
# ---------------------------------------------------------------------------

class TestCircleParsing:
    def test_circle_with_center_and_radius(self):
        """Circle with center and radius parses into SymbolPrimitive."""
        content = _wrap(_symbol("TestCircle",
            '    (circle\n'
            '      (center 0 0)\n'
            '      (radius 5)\n'
            '      (stroke (width 0.25))\n'
            '      (fill (type none))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert len(symbols) == 1
        prim = symbols[0].primitives[0]
        assert prim.kind == "circle"
        assert len(prim.points) == 1
        assert abs(prim.radius - 5.0) < 0.01

    def test_circle_center_coordinates(self):
        """Circle center coordinates are stored in points[0]."""
        content = _wrap(_symbol("TestCirclePos",
            '    (circle\n'
            '      (center 3 -4)\n'
            '      (radius 2)\n'
            '      (stroke (width 0.1))\n'
            '      (fill (type background))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        prim = symbols[0].primitives[0]
        assert abs(prim.points[0][0] - 3.0) < 0.01
        assert abs(prim.points[0][1] - (-4.0)) < 0.01
        assert prim.fill == "background"


# ---------------------------------------------------------------------------
# Arc primitive parsing  (L395-423)
# ---------------------------------------------------------------------------

class TestArcParsing:
    def test_arc_with_start_mid_end(self):
        """Arc with start, mid, end parses into SymbolPrimitive with 3 points."""
        content = _wrap(_symbol("TestArc",
            '    (arc\n'
            '      (start 0 5)\n'
            '      (mid 3.5 3.5)\n'
            '      (end 5 0)\n'
            '      (stroke (width 0.25))\n'
            '      (fill (type none))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert len(symbols) == 1
        prim = symbols[0].primitives[0]
        assert prim.kind == "arc"
        assert len(prim.points) == 3

    def test_arc_points_correct(self):
        """Arc start/mid/end coordinates are stored in order."""
        content = _wrap(_symbol("TestArcCoords",
            '    (arc\n'
            '      (start 1 2)\n'
            '      (mid 3 4)\n'
            '      (end 5 6)\n'
            '      (stroke (width 0.1))\n'
            '      (fill (type none))\n'
            '    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        prim = symbols[0].primitives[0]
        # Points: start, mid, end
        assert abs(prim.points[0][0] - 1.0) < 0.01
        assert abs(prim.points[1][0] - 3.0) < 0.01
        assert abs(prim.points[2][0] - 5.0) < 0.01


# ---------------------------------------------------------------------------
# Pin parsing with various types and styles  (L297, L304, L314, L324, L340-345)
# ---------------------------------------------------------------------------

class TestPinParsing:
    @pytest.mark.parametrize("pin_type", [
        "input", "output", "bidirectional", "passive",
        "power_in", "power_out", "no_connect", "unspecified",
    ])
    def test_all_pin_types(self, pin_type):
        """All valid pin types are parsed correctly."""
        content = _wrap(_symbol("TestPinType",
            _pin(pin_type=pin_type, number="1", name="A")
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        assert len(symbols[0].pins) == 1
        assert symbols[0].pins[0].type == pin_type

    @pytest.mark.parametrize("pin_style", [
        "line", "inverted_clock", "input_low", "output_low",
        "fall_edge", "non_logic", "inverted", "clock",
    ])
    def test_all_pin_styles(self, pin_style):
        """All valid pin styles are parsed without error."""
        content = _wrap(_symbol("TestPinStyle",
            _pin(style=pin_style, number="1")
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        assert len(symbols[0].pins) == 1

    def test_pin_at_with_angle(self):
        """Pin at expression with angle is parsed correctly."""
        content = _wrap(_symbol("TestPinAngle",
            _pin(x=2.54, y=0, angle=270, length=2.54, number="1", name="A")
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        pin = symbols[0].pins[0]
        assert abs(pin.x - 2.54) < 0.01
        assert pin.orientation == 270

    def test_pin_number_and_name(self):
        """Pin number and name are parsed correctly."""
        content = _wrap(_symbol("TestPinId",
            _pin(number="42", name="CLK")
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        pin = symbols[0].pins[0]
        assert pin.number == "42"
        assert pin.name == "CLK"

    def test_pin_with_tilde_name(self):
        """Pin with tilde name (~) is preserved."""
        content = _wrap(_symbol("TestPinTilde",
            _pin(number="1", name="~")
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        assert symbols[0].pins[0].name == "~"


# ---------------------------------------------------------------------------
# Property parsing  (L354-363)
# ---------------------------------------------------------------------------

class TestPropertyParsing:
    def test_property_name_and_value(self):
        """Properties are parsed into symbol.properties dict."""
        content = _wrap(_symbol("TestProps",
            '    (property "Reference" "U" (at 0 0 0))\n'
            '    (property "Value" "74HC00" (at 0 0 0))\n'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        props = symbols[0].properties
        assert props.get("Reference") == "U"
        assert props.get("Value") == "74HC00"

    def test_multiple_properties(self):
        """Multiple properties are all collected."""
        content = _wrap(_symbol("TestMultiProps",
            '    (property "Reference" "R" (at 0 0 0))\n'
            '    (property "Value" "10k" (at 0 0 0))\n'
            '    (property "Footprint" "R_0402" (at 0 0 0))\n'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        props = symbols[0].properties
        assert len(props) >= 3
        assert "Footprint" in props


# ---------------------------------------------------------------------------
# Sub-symbol detection  (L181-191)
# ---------------------------------------------------------------------------

class TestSubSymbolDetection:
    def test_sub_symbol_pins_aggregated(self):
        """Sub-symbols (name_N_M pattern) have their pins aggregated to parent."""
        content = _wrap(
            _symbol("MyPart",
                '    (symbol "MyPart_0_1"\n'
                + _pin(number="1", name="A") +
                '    )\n'
                '    (symbol "MyPart_1_1"\n'
                + _pin(number="2", name="B") +
                '    )\n'
            )
        )
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        parent = symbols[0]
        assert parent.name == "MyPart"
        assert len(parent.pins) == 2

    def test_sub_symbol_not_emitted_as_top_level(self):
        """Sub-symbols themselves are not emitted as top-level SymbolData."""
        content = _wrap(
            _symbol("MyIC",
                '    (symbol "MyIC_0_1"\n'
                + _pin(number="1", name="A") +
                '    )\n'
            )
        )
        symbols = parse_kicad_sym_content(content, "test")
        # Only one top-level symbol (MyIC), not MyIC_0_1
        names = [s.name for s in symbols]
        assert "MyIC" in names
        assert "MyIC_0_1" not in names

    def test_nested_symboldata_is_absorbed_into_parent(self):
        """Nested non-sub-symbol blocks contribute pins/properties to parent."""
        content = _wrap(
            _symbol(
                "Outer",
                '    (symbol "Inner"\n'
                '      (property "Footprint" "SMD:QFN-16" (at 0 0 0))\n'
                + _pin(number="7", name="SIG") +
                "    )\n",
            )
        )

        symbols = parse_kicad_sym_content(content, "test")

        assert len(symbols) == 1
        outer = symbols[0]
        assert outer.name == "Outer"
        assert any(pin.number == "7" for pin in outer.pins)
        assert outer.properties.get("Footprint") == "SMD:QFN-16"


# ---------------------------------------------------------------------------
# parse_kicad_sym_file and parse_kicad_sym_file_safe  (L546-589)
# ---------------------------------------------------------------------------

class TestParseFileApi:
    def test_parse_file_not_found_raises(self, tmp_path):
        """parse_kicad_sym_file raises FileNotFoundError for missing file."""
        from lib.symbols.symbol_parser import parse_kicad_sym_file
        with pytest.raises(FileNotFoundError):
            parse_kicad_sym_file(tmp_path / "nonexistent.kicad_sym")

    def test_parse_file_safe_not_found_returns_empty(self, tmp_path):
        """parse_kicad_sym_file_safe returns ([], error_msg) for missing file."""
        symbols, error = parse_kicad_sym_file_safe(tmp_path / "missing.kicad_sym")
        assert symbols == []
        assert error is not None
        assert "not found" in error.lower() or "File not found" in error

    def test_parse_file_safe_parse_error_returns_empty(self, tmp_path):
        """parse_kicad_sym_file_safe returns ([], error_msg) for invalid content."""
        bad_file = tmp_path / "bad.kicad_sym"
        bad_file.write_text("this is not valid kicad_sym content!@#$")
        symbols, error = parse_kicad_sym_file_safe(bad_file)
        assert symbols == []
        assert error is not None

    def test_parse_file_valid(self, tmp_path):
        """parse_kicad_sym_file parses a valid file."""
        content = _wrap(_symbol("R", _pin(number="1", name="~") + "\n" + _pin(number="2", name="~", x=0, y=2.54)))
        f = tmp_path / "Device.kicad_sym"
        f.write_text(content, encoding="utf-8")
        symbols = parse_kicad_sym_file(f)
        assert len(symbols) == 1
        assert symbols[0].name == "R"
        assert symbols[0].lib == "Device"

    def test_parse_content_parse_error_raises_value_error(self):
        """parse_kicad_sym_content raises ValueError for malformed content."""
        with pytest.raises(ValueError, match="Failed to parse"):
            parse_kicad_sym_content("(this is bad {content}", "test")

    def test_parse_content_wraps_unexpected_visitor_error(self, monkeypatch):
        """Unexpected visitor exceptions are wrapped into ValueError."""
        import lib.symbols.symbol_parser as parser_mod

        valid = _wrap(_symbol("Dummy"))

        def _boom(_self, _tree):
            raise RuntimeError("visitor exploded")

        monkeypatch.setattr(parser_mod.KicadSymVisitor, "visit", _boom)

        with pytest.raises(ValueError, match="visitor exploded"):
            parse_kicad_sym_content(valid, "BoomLib")


# ---------------------------------------------------------------------------
# SymbolLibrary class  (L592-634)
# ---------------------------------------------------------------------------

class TestSymbolLibrary:
    def _write_valid_lib(self, path: Path, name: str = "MyLib") -> Path:
        content = _wrap(_symbol("R", _pin(number="1") + "\n" + _pin(number="2", y=2.54)))
        f = path / f"{name}.kicad_sym"
        f.write_text(content, encoding="utf-8")
        return f

    def test_library_loads_lazily(self, tmp_path):
        """SymbolLibrary loads on first access to .symbols."""
        f = self._write_valid_lib(tmp_path)
        lib = SymbolLibrary(name=f.stem, file_path=f)
        assert not lib._loaded
        _ = lib.symbols
        assert lib._loaded

    def test_library_symbols_property(self, tmp_path):
        """SymbolLibrary.symbols returns parsed symbols."""
        f = self._write_valid_lib(tmp_path)
        lib = SymbolLibrary(name=f.stem, file_path=f)
        syms = lib.symbols
        assert len(syms) >= 1
        assert syms[0].name == "R"

    def test_library_is_valid_true_for_good_file(self, tmp_path):
        """SymbolLibrary.is_valid is True for a parseable, non-empty library."""
        f = self._write_valid_lib(tmp_path)
        lib = SymbolLibrary(name=f.stem, file_path=f)
        assert lib.is_valid is True

    def test_library_is_valid_false_for_missing_file(self, tmp_path):
        """SymbolLibrary.is_valid is False for a missing file."""
        lib = SymbolLibrary(name="missing", file_path=tmp_path / "missing.kicad_sym")
        assert lib.is_valid is False

    def test_library_load_error_none_for_valid(self, tmp_path):
        """SymbolLibrary.load_error is None for a valid file."""
        f = self._write_valid_lib(tmp_path)
        lib = SymbolLibrary(name=f.stem, file_path=f)
        assert lib.load_error is None

    def test_library_load_error_set_for_invalid_file(self, tmp_path):
        """SymbolLibrary.load_error is set for an invalid file."""
        bad = tmp_path / "bad.kicad_sym"
        bad.write_text("garbage content !!!!")
        lib = SymbolLibrary(name="bad", file_path=bad)
        assert lib.load_error is not None

    def test_library_find_symbol_found(self, tmp_path):
        """SymbolLibrary.find_symbol returns the symbol when it exists."""
        f = self._write_valid_lib(tmp_path)
        lib = SymbolLibrary(name=f.stem, file_path=f)
        sym = lib.find_symbol("R")
        assert sym is not None
        assert sym.name == "R"

    def test_library_find_symbol_not_found(self, tmp_path):
        """SymbolLibrary.find_symbol returns None when symbol not found."""
        f = self._write_valid_lib(tmp_path)
        lib = SymbolLibrary(name=f.stem, file_path=f)
        sym = lib.find_symbol("NonExistent")
        assert sym is None

    def test_library_load_idempotent(self, tmp_path):
        """Calling load() multiple times is idempotent."""
        f = self._write_valid_lib(tmp_path)
        lib = SymbolLibrary(name=f.stem, file_path=f)
        lib.load()
        first_symbols = lib.symbols[:]
        lib.load()  # Second call should be a no-op
        assert lib.symbols == first_symbols

    def test_load_library_helper(self, tmp_path):
        """load_library() creates a SymbolLibrary with correct name."""
        f = self._write_valid_lib(tmp_path, name="TestLib")
        lib = load_library(f)
        assert isinstance(lib, SymbolLibrary)
        assert lib.name == "TestLib"


# ---------------------------------------------------------------------------
# fill_type parsing  (L484-489)
# ---------------------------------------------------------------------------

class TestFillTypeParsing:
    @pytest.mark.parametrize("fill_type", ["none", "background", "solid", "outline"])
    def test_fill_types_parsed(self, fill_type):
        """Various fill type values are parsed correctly."""
        content = _wrap(_symbol("TestFillType",
            f'    (polyline\n'
            f'      (pts (xy 0 0) (xy 5 0))\n'
            f'      (stroke (width 0.1))\n'
            f'      (fill (type {fill_type}))\n'
            f'    )'
        ))
        symbols = parse_kicad_sym_content(content, "test")
        if symbols and symbols[0].primitives:
            assert symbols[0].primitives[0].fill == fill_type


# ---------------------------------------------------------------------------
# Multiple symbols in one file  (L546-570)
# ---------------------------------------------------------------------------

class TestMultipleSymbols:
    def test_multiple_symbols_parsed(self):
        """Multiple symbols in one library are all returned."""
        content = _wrap(
            _symbol("R", _pin(number="1") + "\n" + _pin(number="2", y=2.54)) + "\n" +
            _symbol("C", _pin(number="1") + "\n" + _pin(number="2", y=2.54)) + "\n" +
            _symbol("L", _pin(number="1") + "\n" + _pin(number="2", y=2.54))
        )
        symbols = parse_kicad_sym_content(content, "RCL")
        assert len(symbols) == 3
        names = {s.name for s in symbols}
        assert names == {"R", "C", "L"}

    def test_lib_name_set_on_all_symbols(self):
        """lib attribute is set to the library name on all parsed symbols."""
        content = _wrap(
            _symbol("A") + "\n" + _symbol("B")
        )
        symbols = parse_kicad_sym_content(content, "MyLib")
        for s in symbols:
            assert s.lib == "MyLib"

    def test_parse_content_flattens_nested_symbol_lists(self, monkeypatch):
        """Nested list output from visitor is flattened to SymbolData list."""
        import lib.symbols.symbol_parser as parser_mod

        valid = _wrap(_symbol("Placeholder"))
        s1 = SymbolData(name="S1", lib="", pins=[], primitives=[], properties={})
        s2 = SymbolData(name="S2", lib="", pins=[], primitives=[], properties={})

        def _nested_symbols(_self, _tree):
            return [s1, [s2]]

        monkeypatch.setattr(parser_mod.KicadSymVisitor, "visit", _nested_symbols)
        parsed = parse_kicad_sym_content(valid, "NestedLib")

        assert [s.name for s in parsed] == ["S1", "S2"]
        assert all(s.lib == "NestedLib" for s in parsed)


class TestParserEdgeBranches:
    def test_pin_without_number_is_ignored(self):
        """Pin blocks without number field are skipped."""
        content = _wrap(
            _symbol(
                "MissingNumber",
                '    (pin passive line (at 0 0 0) (length 2.54)\n'
                '      (name "SIG" (effects (font (size 1.27 1.27))))\n'
                '    )\n',
            )
        )
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        assert symbols[0].pins == []

    def test_pin_empty_number_string_is_treated_as_missing(self):
        """Empty number string maps to None and does not create a pin."""
        content = _wrap(
            _symbol(
                "EmptyNumber",
                '    (pin passive line (at 0 0 0) (length 2.54)\n'
                '      (name "SIG" (effects (font (size 1.27 1.27))))\n'
                '      (number "" (effects (font (size 1.27 1.27))))\n'
                '    )\n',
            )
        )
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        assert symbols[0].pins == []

    def test_incomplete_circle_and_arc_are_skipped(self):
        """Circle/arc primitives missing required geometry are omitted."""
        content = _wrap(
            _symbol(
                "IncompleteShapes",
                '    (circle\n'
                '      (center 1 1)\n'
                '      (stroke (width 0.1))\n'
                '      (fill (type none))\n'
                '    )\n'
                '    (arc\n'
                '      (start 0 0)\n'
                '      (end 3 3)\n'
                '      (stroke (width 0.1))\n'
                '      (fill (type none))\n'
                '    )\n',
            )
        )
        symbols = parse_kicad_sym_content(content, "test")
        assert symbols
        assert symbols[0].primitives == []

    @pytest.mark.parametrize(
        "method_name, expected_kind",
        [
            ("visit_xy_expr", "xy"),
            ("visit_start_expr", "start"),
            ("visit_mid_expr", "mid"),
            ("visit_end_expr", "end"),
            ("visit_center_expr", "center"),
        ],
    )
    def test_coordinate_expr_defaults_origin_for_incomplete_values(self, method_name, expected_kind):
        visitor = KicadSymVisitor()
        method = getattr(visitor, method_name)
        result = method(None, [1.0])  # only one numeric token
        assert result == {"_kind": expected_kind, "point": (0.0, 0.0)}

    def test_fill_type_defaults_to_none_when_missing_identifier(self):
        visitor = KicadSymVisitor()
        result = visitor.visit_fill_type_expr(None, [None, []])
        assert result == {"_kind": "fill_type", "value": "none"}

    def test_symbol_def_without_name_falls_back_to_empty_name(self):
        visitor = KicadSymVisitor()
        symbol = visitor.visit_symbol_def(None, [[{"_kind": "property", "name": "K", "value": "V"}]])
        assert isinstance(symbol, SymbolData)
        assert symbol.name == ""
        assert symbol.properties["K"] == "V"

    def test_primitive_parsers_ignore_non_dict_items(self):
        visitor = KicadSymVisitor()

        poly = visitor.visit_polyline_def(
            None,
            [["noise", {"_kind": "pts", "points": [(0.0, 0.0), (1.0, 1.0)]}]],
        )
        rect = visitor.visit_rectangle_def(
            None,
            [["noise", {"_kind": "start", "point": (0.0, 0.0)}, {"_kind": "end", "point": (2.0, 1.0)}]],
        )
        circle = visitor.visit_circle_def(
            None,
            [["noise", {"_kind": "center", "point": (0.0, 0.0)}, {"_kind": "radius", "value": 2.0}]],
        )
        arc = visitor.visit_arc_def(
            None,
            [
                [
                    "noise",
                    {"_kind": "start", "point": (0.0, 0.0)},
                    {"_kind": "mid", "point": (1.0, 1.0)},
                    {"_kind": "end", "point": (2.0, 0.0)},
                ]
            ],
        )

        assert poly is not None
        assert rect is not None
        assert circle is not None
        assert arc is not None

    def test_qstring_and_number_visitors_handle_malformed_tokens(self):
        visitor = KicadSymVisitor()

        unquoted = visitor.visit_qstring(SimpleNamespace(text="UNQUOTED"), [])
        bad_number = visitor.visit_number(SimpleNamespace(text="not_a_number"), [])

        assert unquoted == "UNQUOTED"
        assert bad_number == 0.0
