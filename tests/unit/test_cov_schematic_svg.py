"""Coverage tests for missing-symbol fallback behavior in schematic SVG rendering."""

from __future__ import annotations

from dataclasses import replace
import re

import pytest

import lib.symbols.symbols as _sym_mod
from lib.core.part import Part
from lib.core.render_style import RenderStyle, RenderTemplate, TextPlacementStyle
from lib.core.schematic import Schematic
from lib.symbols import configure_default_symbols
from lib.core.style import Style
from lib.render.schematic_svg import (
    _Obstacle,
    _TrackingCanvas,
    _can_draw_straight,
    _draw_flag_label,
    _draw_manhattan_wire,
    _draw_net_label,
    _draw_wire_net,
    _draw_segment_avoiding,
    _effective_output_scale,
    _nudge_horizontal_flag_tip,
)


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


def _line_segments(canvas: _TrackingCanvas) -> list[tuple[float, float, float, float]]:
    segments = []
    for x1, y1, x2, y2 in re.findall(
        r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"',
        "".join(canvas._elements),
    ):
        segments.append((float(x1), float(y1), float(x2), float(y2)))
    return segments


class _FlakyObstacle:
    """Stateful obstacle used to force fallback branches deterministically."""

    def __init__(self, *, true_calls: int) -> None:
        self._true_calls = true_calls
        self._calls = 0

    def segment_hits(self, *_args) -> bool:
        self._calls += 1
        return self._calls <= self._true_calls


class TestWireRoutingFallbacks:
    def test_can_draw_straight_requires_axis_alignment(self):
        assert _can_draw_straight((0.0, 0.0), (10.0, 5.0), obstacles=[]) is False

    def test_can_draw_straight_rejects_blocked_aligned_segment(self):
        obstacles = [_Obstacle(4.0, -1.0, 6.0, 1.0, clearance=0.0)]
        assert _can_draw_straight((0.0, 0.0), (10.0, 0.0), obstacles=obstacles) is False

    def test_can_draw_straight_accepts_clear_aligned_segment(self):
        obstacles = [_Obstacle(4.0, 4.0, 6.0, 6.0, clearance=0.0)]
        assert _can_draw_straight((0.0, 0.0), (10.0, 0.0), obstacles=obstacles) is True

    def test_can_draw_straight_allows_endpoint_clearance_exit(self):
        obstacles = [_Obstacle(-1.0, -1.0, 1.0, 1.0, clearance=0.0)]
        assert _can_draw_straight((0.8, 0.0), (10.0, 0.0), obstacles=obstacles) is True

    def test_draw_wire_net_prefers_single_straight_segment_for_clear_pair(self):
        canvas = _TrackingCanvas(200, 200)

        _draw_wire_net(
            canvas,
            [(0.0, 0.0), (20.0, 0.0)],
            "_anon_straight",
            obstacles=[],
            drawn_segs=[],
            show_label=False,
        )

        assert _line_segments(canvas) == [(0.0, 0.0, 20.0, 0.0)]

    def test_draw_wire_net_falls_back_when_aligned_pair_is_blocked(self):
        canvas = _TrackingCanvas(200, 200)
        blocked = [_Obstacle(8.0, -1.0, 12.0, 1.0, clearance=0.0)]

        _draw_wire_net(
            canvas,
            [(0.0, 0.0), (20.0, 0.0)],
            "_anon_blocked",
            obstacles=blocked,
            drawn_segs=[],
            show_label=False,
        )

        segments = _line_segments(canvas)
        assert segments != [(0.0, 0.0, 20.0, 0.0)]
        assert len(segments) >= 2

    def test_draw_manhattan_wire_prefers_h_first_when_clear(self):
        canvas = _TrackingCanvas(200, 200)

        _draw_manhattan_wire(canvas, (0.0, 0.0), (10.0, 10.0), obstacles=[])

        assert _line_segments(canvas) == [
            (0.0, 0.0, 10.0, 0.0),
            (10.0, 0.0, 10.0, 10.0),
        ]

    def test_draw_manhattan_wire_falls_back_when_blocking_list_empty(self):
        canvas = _TrackingCanvas(200, 200)
        obstacle = _FlakyObstacle(true_calls=2)

        _draw_manhattan_wire(canvas, (0.0, 0.0), (10.0, 10.0), obstacles=[obstacle])  # type: ignore[list-item]

        assert _line_segments(canvas) == [
            (0.0, 0.0, 10.0, 0.0),
            (10.0, 0.0, 10.0, 10.0),
        ]

    def test_draw_segment_avoiding_falls_back_to_straight_line(self):
        canvas = _TrackingCanvas(200, 200)
        obstacle = _FlakyObstacle(true_calls=1)

        _draw_segment_avoiding(canvas, 0.0, 0.0, 20.0, 0.0, [obstacle])  # type: ignore[list-item]

        assert _line_segments(canvas) == [(0.0, 0.0, 20.0, 0.0)]


class TestNetLabelAndFlagRendering:
    def test_draw_net_label_adds_halo_and_centered_text(self):
        canvas = _TrackingCanvas(200, 200)

        _draw_net_label(canvas, 50.0, 60.0, "BUS_A")

        assert len(canvas._elements) == 2
        assert canvas._elements[0].startswith('<rect x="')
        assert 'opacity="' in canvas._elements[0]
        assert "BUS_A</text>" in canvas._elements[1]
        assert 'text-anchor="middle"' in canvas._elements[1]

    @pytest.mark.parametrize("side, expect_above", [("top", True), ("bottom", False)])
    def test_draw_flag_label_supports_vertical_tags(self, side: str, expect_above: bool):
        canvas = _TrackingCanvas(300, 300)

        _draw_flag_label(canvas, 100.0, 100.0, "NET_V", side=side)

        path = next(el for el in canvas._elements if el.startswith('<path d="M '))
        m = re.search(r'd="M [^ ]+ ([^ ]+)', path)
        assert m is not None
        first_y = float(m.group(1))
        assert (first_y < 100.0) is expect_above
        assert "L 100.0 100.0" in path

    def test_nudge_horizontal_flag_tip_returns_none_for_vertical_side(self):
        nudged = _nudge_horizontal_flag_tip(
            100.0,
            100.0,
            "N1",
            side="top",
            align_x=None,
            obstacles=[],
            ln_font_size=11.0,
        )
        assert nudged is None

    def test_nudge_horizontal_flag_tip_returns_align_x_when_no_overlap(self):
        nudged = _nudge_horizontal_flag_tip(
            100.0,
            100.0,
            "N2",
            side="left",
            align_x=120.0,
            obstacles=[_Obstacle(400.0, 400.0, 460.0, 460.0)],
            ln_font_size=11.0,
        )
        assert nudged == 120.0


class TestTrackingCanvasFitFallback:
    def test_to_svg_fit_without_drawing_uses_full_page_viewbox(self):
        canvas = _TrackingCanvas(180.0, 120.0)

        svg = canvas.to_svg_fit(margin=20.0)

        assert 'viewBox="0 0 180.0 120.0"' in svg
        assert '<rect width="180.0" height="120.0" fill="white"/>' in svg
