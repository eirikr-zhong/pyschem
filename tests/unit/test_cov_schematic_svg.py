"""Coverage tests for missing-symbol fallback behavior in schematic SVG rendering."""

from __future__ import annotations

import re

import pytest

import lib.symbols.symbols as _sym_mod
from lib.core.part import Part
from lib.core.render_style import RenderStyle, RenderTemplate, TextPlacementStyle
from lib.core.schematic import Schematic
from lib.symbols import configure_default_symbols
from lib.render.schematic_svg import (
    _Obstacle,
    _TrackingCanvas,
    _can_draw_straight,
    _draw_manhattan_wire,
    _draw_net_label,
    _netlabel_rotation,
    _draw_wire_net,
    _draw_segment_avoiding,
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

    @pytest.mark.parametrize(
        ("direction", "expected"),
        [
            ("right", 0),
            ("left", 180),
            ("top", 90),
            ("bottom", 270),
            ("up", 90),
            ("down", 270),
            ("invalid", 0),
        ],
    )
    def test_netlabel_rotation_mapping(self, direction: str, expected: int):
        assert _netlabel_rotation(direction, fallback=0) == expected


class TestTrackingCanvasFitFallback:
    def test_to_svg_fit_without_drawing_uses_full_page_viewbox(self):
        canvas = _TrackingCanvas(180.0, 120.0)

        svg = canvas.to_svg_fit(margin=20.0)

        assert 'viewBox="0 0 180.0 120.0"' in svg
        assert '<rect width="180.0" height="120.0" fill="white"/>' in svg
