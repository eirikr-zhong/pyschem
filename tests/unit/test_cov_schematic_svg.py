"""Coverage tests for missing-symbol fallback behavior in schematic SVG rendering."""

from __future__ import annotations

import pytest

import lib.symbols.symbols as _sym_mod
from lib.core.part import Part
from lib.core.render_style import RenderStyle, RenderTemplate, TextPlacementStyle
from lib.core.schematic import Schematic
from lib.symbols import configure_default_symbols


MINIMAL_DEVICE_R_SYM = '''\
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
)
'''


@pytest.fixture(autouse=True)
def _reset_default_symbols() -> None:
    original = _sym_mod._DEFAULT_SYMBOLS
    _sym_mod._DEFAULT_SYMBOLS = None
    yield
    _sym_mod._DEFAULT_SYMBOLS = original


class TestMissingSymbolPlaceholder:
    def test_missing_symbol_renders_red_dashed_placeholder(self):
        sch = Schematic("missing_symbol")
        p = Part("Device:NoSuchSymbol", ref="U1")
        p.pin("1")
        sch.add_part(p)

        svg = sch.get_svg_string()
        assert 'stroke="#d32f2f"' in svg
        assert 'stroke-dasharray="6,4"' in svg
        assert "? Device:NoSuchSymbol" in svg

    def test_missing_symbol_label_uses_lib_id(self):
        sch = Schematic("missing_symbol_label")
        p = Part("CustomLib:Foo", ref="X1")
        p.pin("1")
        sch.add_part(p)

        svg = sch.get_svg_string()
        assert "? CustomLib:Foo" in svg

    def test_visibility_toggle_suppresses_placeholder_ref_and_value(self):
        sch = Schematic("missing_symbol_hidden_text")
        p = Part("CustomLib:Foo", ref="X1", value="10k")
        p.pin("1")
        sch.add_part(p)
        style = RenderStyle.default().merge(
            RenderStyle(
                ref_text=TextPlacementStyle(visible=False),
                value_text=TextPlacementStyle(visible=False),
            )
        )
        tmpl = RenderTemplate.from_style(style)
        svg = sch.get_svg_string(template=tmpl)
        assert "? CustomLib:Foo" in svg
        assert ">X1<" not in svg
        assert ">10k<" not in svg


class TestLibrarySymbolResolution:
    def test_configured_library_avoids_missing_symbol_placeholder(self, tmp_path):
        sym_dir = tmp_path / "syms"
        sym_dir.mkdir()
        (sym_dir / "Device.kicad_sym").write_text(MINIMAL_DEVICE_R_SYM)
        configure_default_symbols(symbol_paths=[str(sym_dir)], preload=False)

        sch = Schematic("resolved_symbol")
        r1 = Part("Device:R", ref="R1", value="1k")
        r1.pin("1")
        r1.pin("2")
        sch.add_part(r1)

        svg = sch.get_svg_string()
        assert "? Device:R" not in svg
        assert "R1" in svg
