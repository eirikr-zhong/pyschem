"""Coverage tests for missing-symbol fallback behavior in schematic SVG rendering."""

from __future__ import annotations

from dataclasses import replace

import pytest

import lib.symbols.symbols as _sym_mod
from lib.core.part import Part
from lib.core.render_style import RenderStyle, RenderTemplate, TextPlacementStyle
from lib.core.schematic import Schematic
from lib.symbols import configure_default_symbols
from lib.core.style import Style
from lib.render.schematic_svg import _effective_output_scale


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


class TestEffectiveOutputScale:
    def _make_style(self, **kwargs) -> Style:
        """Build a fully-resolved style with targeted field overrides."""
        return replace(Style.default(), **kwargs)

    def test_fixed_scale_mode(self):
        s = self._make_style(canvas_scale_mode="fixed", canvas_scale=2.0)
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 2.0

    def test_fixed_scale_mode_normalizes_mode_string(self):
        s = self._make_style(canvas_scale_mode="  FiXeD  ", canvas_scale=2.5)
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 2.5

    def test_fixed_scale_clamped_min(self):
        s = self._make_style(canvas_scale_mode="fixed", canvas_scale=0.5, canvas_scale_min=1.0)
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 1.0

    def test_fixed_scale_clamped_max(self):
        s = self._make_style(canvas_scale_mode="fixed", canvas_scale=3.0, canvas_scale_max=2.0)
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 2.0

    def test_auto_scale_mode(self):
        # target_font_px / baseline_font_px = 12 / 10 = 1.2
        s = self._make_style(canvas_scale_mode="auto", canvas_target_min_font_px=12.0)
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 1.2

    def test_auto_scale_mode_with_variable_fonts(self):
        # Smallest font is 5.0, target is 10.0 -> scale should be 2.0
        s = self._make_style(canvas_scale_mode="auto", canvas_target_min_font_px=10.0)
        scale = _effective_output_scale(s, font_ref=10, font_net=5, font_value=8, font_pin=12, ln_font_size=6)
        assert scale == 2.0

    def test_auto_scale_mode_uses_line_font_in_baseline(self):
        # Smallest font is ln_font_size=3.0, so 12 / 3 = 4.0.
        s = self._make_style(canvas_scale_mode="auto", canvas_target_min_font_px=12.0)
        scale = _effective_output_scale(s, font_ref=10, font_net=9, font_value=8, font_pin=7, ln_font_size=3)
        assert scale == 4.0

    def test_auto_scale_clamped_min(self):
        # target_font_px / baseline_font_px = 10 / 20 = 0.5. Clamped to 1.0.
        s = self._make_style(canvas_scale_mode="auto", canvas_target_min_font_px=10.0, canvas_scale_min=1.0)
        scale = _effective_output_scale(s, font_ref=20, font_net=20, font_value=20, font_pin=20, ln_font_size=20)
        assert scale == 1.0

    def test_auto_scale_clamped_max(self):
        # target_font_px / baseline_font_px = 20 / 5 = 4.0. Clamped to 3.0.
        s = self._make_style(canvas_scale_mode="auto", canvas_target_min_font_px=20.0, canvas_scale_max=3.0)
        scale = _effective_output_scale(s, font_ref=5, font_net=5, font_value=5, font_pin=5, ln_font_size=5)
        assert scale == 3.0

    def test_invalid_mode_defaults_to_auto(self):
        # Should default to auto: 10 / 10 = 1.0
        s = self._make_style(canvas_scale_mode="invalid", canvas_target_min_font_px=10.0)
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 1.0

    def test_min_scale_greater_than_max_scale(self):
        # Should swap min/max and then clamp. Scale 0.5 -> becomes 1.0-2.0, so 1.0
        s = self._make_style(canvas_scale_mode="fixed", canvas_scale=0.5, canvas_scale_min=2.0, canvas_scale_max=1.0)
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 1.0

    def test_auto_scale_swaps_min_and_max_bounds(self):
        # Bounds swap from 4.0..2.0 to 2.0..4.0; raw auto scale is 20 / 10 = 2.0.
        s = self._make_style(
            canvas_scale_mode="auto",
            canvas_target_min_font_px=20.0,
            canvas_scale_min=4.0,
            canvas_scale_max=2.0,
        )
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 2.0

    def test_fixed_scale_bounds_below_floor_clamp_to_point_one(self):
        # scale_min floor forces both bounds to 0.1 when max is also below 0.1.
        s = self._make_style(
            canvas_scale_mode="fixed",
            canvas_scale=-2.0,
            canvas_scale_min=-5.0,
            canvas_scale_max=0.0,
        )
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 0.1

    def test_zero_or_negative_target_font_px(self):
        # target_font_px is clamped to 0.1, so (0.1 / 10) = 0.01. Clamped to 0.1
        s = self._make_style(canvas_scale_mode="auto", canvas_target_min_font_px=-5.0, canvas_scale_min=0.1)
        scale = _effective_output_scale(s, font_ref=10, font_net=10, font_value=10, font_pin=10, ln_font_size=10)
        assert scale == 0.1

    def test_zero_or_negative_min_font_px(self):
        # baseline_font_px is clamped to 0.1, so (10 / 0.1) = 100.
        # Raise the max bound to avoid clamp-to-default-max affecting this assertion.
        s = self._make_style(
            canvas_scale_mode="auto",
            canvas_target_min_font_px=10.0,
            canvas_scale_max=200.0,
        )
        scale = _effective_output_scale(s, font_ref=-1, font_net=0, font_value=0.05, font_pin=10, ln_font_size=2)
        # The smallest font is 0 (from font_net), clamped to 0.1. So 10 / 0.1 = 100
        assert scale == 100.0
