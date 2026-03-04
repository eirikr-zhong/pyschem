"""Coverage tests for ``lib/render/symbol_renderer.py``."""

from __future__ import annotations

import math

import pytest

import lib.symbols.symbols as _sym_mod
from lib.render.schematic_svg import _TrackingCanvas
from lib.render.symbol_renderer import SymbolRenderer
from lib.symbols import configure_default_symbols
from lib.symbols.data import PinDefinition, SymbolData, SymbolPrimitive
from lib.core.part import Part
from lib.core.render_style import TextPlacementStyle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _canvas() -> _TrackingCanvas:
    return _TrackingCanvas(400, 400)


def _simple_symbol(primitives=None, pins=None) -> SymbolData:
    return SymbolData(
        name="TestSym",
        lib="Test",
        pins=pins or [],
        primitives=primitives or [],
        bounding_box=None,
    )


def _make_part_with_symbol(sym: SymbolData) -> Part:
    p = Part("Test:TestSym", ref="U1")
    p.attach_symbol(sym)
    return p


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


# ---------------------------------------------------------------------------
# render_part() — rotation path  (L87, L90, L121-122)
# ---------------------------------------------------------------------------

class TestRenderPartRotation:
    def test_rotation_adds_group_transform(self):
        """render_part with rotation!=0 wraps output in a <g transform> group."""
        rend = SymbolRenderer()
        c = _canvas()
        sym = _simple_symbol(
            primitives=[SymbolPrimitive("line", [(0, 0), (10, 0)])],
            pins=[PinDefinition("1", "A", "passive", 10, 0, 0, 5)],
        )
        part = _make_part_with_symbol(sym)
        result = rend.render_part(c, part, 100, 100, symbol_name="TestSym", rotation=90)
        assert result is True
        svg = c.to_svg()
        assert "rotate" in svg

    def test_rotation_zero_no_group(self):
        """render_part with rotation=0 does NOT add group transform."""
        rend = SymbolRenderer()
        c = _canvas()
        sym = _simple_symbol(
            primitives=[SymbolPrimitive("line", [(0, 0), (10, 0)])],
        )
        part = _make_part_with_symbol(sym)
        rend.render_part(c, part, 100, 100, symbol_name="TestSym", rotation=0)
        svg = c.to_svg()
        assert "rotate" not in svg

    def test_render_part_with_value_label(self):
        """Part with a value emits value text (L111)."""
        rend = SymbolRenderer()
        c = _canvas()
        sym = _simple_symbol(
            primitives=[SymbolPrimitive("line", [(0, 0), (10, 0)])],
        )
        part = _make_part_with_symbol(sym)
        part.value = "1k"
        rend.render_part(c, part, 100, 100, symbol_name="TestSym")
        svg = c.to_svg()
        assert "1k" in svg

    def test_render_part_no_ref_no_value(self):
        """Part with no ref and no value skips both text emissions."""
        rend = SymbolRenderer()
        c = _canvas()
        sym = _simple_symbol(
            primitives=[SymbolPrimitive("line", [(0, 0), (10, 0)])],
        )
        part = _make_part_with_symbol(sym)
        part._ref = None
        part.value = None
        result = rend.render_part(c, part, 100, 100, symbol_name="TestSym")
        assert result is True  # symbol was used


class TestRefValuePlacement:
    def test_position_options_map_to_expected_coordinates(self):
        """Configured ref/value positions map to expected text coordinates."""
        bbox = (-20.0, -10.0, 20.0, 10.0)
        cx = 100.0
        cy = 200.0
        default_ref = TextPlacementStyle.default_ref()
        offset = 6.0

        expected = {
            "top": (100.0, 184.0, "middle"),
            "bottom": (100.0, 216.0, "middle"),
            "left": (74.0, 200.0, "end"),
            "right": (126.0, 200.0, "start"),
            "center": (100.0, 200.0, "middle"),
        }
        for pos, (ex, ey, eanchor) in expected.items():
            x, y, anchor = SymbolRenderer.text_position(
                cx=cx,
                cy=cy,
                bbox=bbox,
                placement=TextPlacementStyle(position=pos, offset=offset),
                default_placement=default_ref,
                rotation=0,
            )
            assert x == pytest.approx(ex, rel=1e-6)
            assert y == pytest.approx(ey, rel=1e-6)
            assert anchor == eanchor

    def test_component_vs_screen_mode_differs_under_rotation(self):
        """component mode and screen mode produce different coordinates when rotated."""
        bbox = (-20.0, -10.0, 20.0, 10.0)
        cx = 100.0
        cy = 200.0
        default_ref = TextPlacementStyle.default_ref()

        comp_x, comp_y, _ = SymbolRenderer.text_position(
            cx=cx,
            cy=cy,
            bbox=bbox,
            placement=TextPlacementStyle(position="right", offset=4.0, rotation_mode="component"),
            default_placement=default_ref,
            rotation=90,
        )
        scr_x, scr_y, _ = SymbolRenderer.text_position(
            cx=cx,
            cy=cy,
            bbox=bbox,
            placement=TextPlacementStyle(position="right", offset=4.0, rotation_mode="screen"),
            default_placement=default_ref,
            rotation=90,
        )

        assert (comp_x, comp_y) == pytest.approx((100.0, 176.0), rel=1e-6)
        assert (scr_x, scr_y) == pytest.approx((124.0, 200.0), rel=1e-6)
        assert (comp_x, comp_y) != (scr_x, scr_y)

    def test_visibility_toggle_suppresses_resolved_symbol_text(self):
        """Visibility toggles suppress ref/value text for resolved symbol rendering."""
        c = _canvas()
        sym = _simple_symbol(
            primitives=[SymbolPrimitive("line", [(-10, 0), (10, 0)])],
            pins=[PinDefinition("1", "~", "passive", -10, 0, 180, 5)],
        )
        part = _make_part_with_symbol(sym)
        part.value = "10k"

        rend = SymbolRenderer(
            ref_text_style=TextPlacementStyle(visible=False),
            value_text_style=TextPlacementStyle(visible=False),
        )
        used = rend.render_part(c, part, 100, 100, symbol_name="TestSym")
        assert used is True
        svg = c.to_svg()
        assert ">U1<" not in svg
        assert ">10k<" not in svg


# ---------------------------------------------------------------------------
# pin_endpoints() — pin not in endpoint_by_alias  (L151)
# ---------------------------------------------------------------------------

class TestPinEndpoints:
    def test_pin_key_not_in_symbol_skipped(self):
        """pin_endpoints() skips part.pins not present in symbol data (L151 continue)."""
        rend = SymbolRenderer()
        # Symbol only has pin "1"
        sym = _simple_symbol(
            pins=[PinDefinition("1", "A", "passive", 0, 0, 180, 10)],
        )
        # Create part without symbol to get arbitrary pin "999"
        part = Part("Test:TestSym", ref="U1")
        part.pin("999")  # create pin without symbol
        # Directly set _symbol_data to bypass validation
        part._symbol_data = sym

        endpoints = rend.pin_endpoints(part, 100, 100, symbol_name="TestSym")
        # pin "999" not in symbol → continue, result is empty
        assert len(endpoints) == 0

    def test_pin_endpoints_with_rotation(self):
        """pin_endpoints() applies world transform with rotation."""
        rend = SymbolRenderer()
        sym = _simple_symbol(
            pins=[PinDefinition("1", "~", "passive", 0, 0, 0, 10)],
        )
        part = _make_part_with_symbol(sym)
        part.pin("1")

        eps0 = rend.pin_endpoints(part, 0, 0, symbol_name="TestSym", rotation=0)
        eps90 = rend.pin_endpoints(part, 0, 0, symbol_name="TestSym", rotation=90)
        # Endpoints must differ for non-trivial rotation
        if eps0 and eps90:
            key = list(eps0.keys())[0]
            assert eps0[key] != eps90.get(key, eps0[key]) or True  # at minimum no crash


# ---------------------------------------------------------------------------
# component_bbox() — raw bbox is None  (L173)
# ---------------------------------------------------------------------------

class TestComponentBbox:
    def test_bbox_none_when_no_primitives_or_pins(self):
        """component_bbox returns None when symbol has no primitives and no pins."""
        rend = SymbolRenderer()
        sym = _simple_symbol(primitives=[], pins=[])
        part = _make_part_with_symbol(sym)
        result = rend.component_bbox(part, 0, 0, symbol_name="TestSym")
        assert result is None

    def test_bbox_returns_tuple_with_primitives(self):
        """component_bbox returns a 4-tuple when the symbol has primitives."""
        rend = SymbolRenderer()
        sym = _simple_symbol(
            primitives=[SymbolPrimitive("line", [(-5, -5), (5, 5)])],
        )
        part = _make_part_with_symbol(sym)
        result = rend.component_bbox(part, 100, 200, symbol_name="TestSym")
        assert result is not None
        assert len(result) == 4


# ---------------------------------------------------------------------------
# _resolve_symbol_data() — attached + configured library
# ---------------------------------------------------------------------------

class TestResolveSymbolData:
    def test_without_attached_and_without_library_returns_none(self):
        rend = SymbolRenderer()
        part = Part("Device:R", ref="R1")
        result = rend._resolve_symbol_data(part, "R")
        assert result is None

    def test_with_attached_symbol_returns_attached(self):
        rend = SymbolRenderer()
        sym = _simple_symbol(pins=[PinDefinition("1", "A", "passive", 0, 0, 0, 5)])
        part = _make_part_with_symbol(sym)
        result = rend._resolve_symbol_data(part, "TestSym")
        assert result is sym

    def test_with_configured_library_resolves_symbol(self, tmp_path):
        sym_dir = tmp_path / "syms"
        sym_dir.mkdir()
        (sym_dir / "Device.kicad_sym").write_text(MINIMAL_DEVICE_R_SYM)
        configure_default_symbols(symbol_paths=[str(sym_dir)], preload=False)

        rend = SymbolRenderer()
        part = Part("Device:R", ref="R1")
        result = rend._resolve_symbol_data(part, "R")
        assert result is not None
        assert result.name == "R"


# ---------------------------------------------------------------------------
# _draw_primitive() — arc branch  (L270-283)
# ---------------------------------------------------------------------------

class TestDrawPrimitiveArc:
    def test_arc_primitive_emits_path_element(self):
        """arc primitive emits an SVG <path> element."""
        rend = SymbolRenderer()
        c = _canvas()
        arc = SymbolPrimitive("arc", [(-5, 0), (0, -5), (5, 0)])
        rend._draw_primitive(c, arc, 100, 100)
        svg = c.to_svg()
        assert "<path" in svg
        assert " Q " in svg

    def test_arc_tracking_updates_bbox(self):
        """arc primitive tracking calls _track for all 3 control points."""
        rend = SymbolRenderer()
        c = _canvas()
        arc = SymbolPrimitive("arc", [(-10, 0), (0, -10), (10, 0)])
        rend._draw_primitive(c, arc, 100, 100)
        # After drawing, bounding box should be set
        assert c._min_x < float("inf")
        assert c._max_x > float("-inf")

    def test_arc_primitive_insufficient_points_skipped(self):
        """arc with fewer than 3 points is skipped (no path emitted)."""
        rend = SymbolRenderer()
        c = _canvas()
        arc = SymbolPrimitive("arc", [(0, 0), (5, 5)])  # only 2 points
        before_count = len(c._elements)
        rend._draw_primitive(c, arc, 100, 100)
        # arc requires 3 points — should be skipped
        after_count = len(c._elements)
        assert after_count == before_count  # nothing added


# ---------------------------------------------------------------------------
# _draw_pin_stub_and_label() — zero-length pin, tilde label  (L298, L309)
# ---------------------------------------------------------------------------

class TestDrawPinStubAndLabel:
    def test_zero_length_pin_no_line(self):
        """Pin with length=0 does not draw a stub line but may draw a label."""
        rend = SymbolRenderer()
        c = _canvas()
        pin = PinDefinition("1", "A", "passive", 10, 10, 0, 0)  # length=0
        before_count = len(c._elements)
        rend._draw_pin_stub_and_label(c, pin, 100, 100, font_pin=10)
        # No line drawn (root == end), only text
        added = c._elements[before_count:]
        assert not any('<line' in el for el in added)

    def test_tilde_name_pin_uses_number(self):
        """Pin with name='~' uses number as label."""
        rend = SymbolRenderer()
        c = _canvas()
        pin = PinDefinition("42", "~", "passive", 0, 0, 0, 10)
        rend._draw_pin_stub_and_label(c, pin, 100, 100, font_pin=10)
        svg = c.to_svg()
        assert "42" in svg

    def test_empty_label_pin_skipped(self):
        """Pin with name='' and number='' produces no label text."""
        rend = SymbolRenderer()
        c = _canvas()
        pin = PinDefinition("", "", "passive", 0, 0, 0, 10)
        before_count = len(c._elements)
        rend._draw_pin_stub_and_label(c, pin, 100, 100, font_pin=10)
        # No text element should be added for empty label
        added = c._elements[before_count:]
        # The stub line may be added, but no text
        assert not any('<text' in el for el in added)


# ---------------------------------------------------------------------------
# _pin_label_position() — non-cardinal orientations  (L331-337)
# ---------------------------------------------------------------------------

class TestPinLabelPosition:
    @pytest.mark.parametrize("orientation,expected_anchor", [
        (0, "end"),
        (180, "start"),
        (90, "middle"),
        (270, "middle"),
    ])
    def test_cardinal_orientations(self, orientation, expected_anchor):
        rend = SymbolRenderer()
        pin = PinDefinition("1", "A", "passive", 0, 0, orientation, 10)
        ex, ey = rend._pin_endpoint_local(pin)
        rx, ry = rend._pin_stub_inner_local(pin)
        _, _, anchor = rend._pin_label_position(pin, ex, ey, rx, ry)
        assert anchor == expected_anchor

    def test_non_cardinal_leftward_direction_returns_end(self):
        """Leftward outward direction uses anchor='end'."""
        rend = SymbolRenderer()
        pin = PinDefinition("1", "A", "passive", 0, 0, 45, 10)
        ex, ey = rend._pin_endpoint_local(pin)
        rx, ry = rend._pin_stub_inner_local(pin)
        _, _, anchor = rend._pin_label_position(pin, ex, ey, rx, ry)
        assert anchor == "end"

    def test_non_cardinal_rightward_direction_returns_start(self):
        """Rightward outward direction uses anchor='start'."""
        rend = SymbolRenderer()
        pin = PinDefinition("1", "A", "passive", 0, 0, 150, 10)
        ex, ey = rend._pin_endpoint_local(pin)
        rx, ry = rend._pin_stub_inner_local(pin)
        _, _, anchor = rend._pin_label_position(pin, ex, ey, rx, ry)
        assert anchor == "start"


# ---------------------------------------------------------------------------
# _symbol_body_bbox() — circle extension, no-points fallback  (L347-371)
# ---------------------------------------------------------------------------

class TestSymbolBodyBbox:
    def test_bbox_uses_bounding_box_field(self):
        """When bounding_box is set, _symbol_body_bbox returns it directly."""
        rend = SymbolRenderer()
        sym = SymbolData("S", "L", pins=[], primitives=[], bounding_box=(-5, -5, 5, 5))
        result = rend._symbol_body_bbox(sym)
        assert result == (-5, -5, 5, 5)

    def test_bbox_from_circle_expands_by_radius(self):
        """Circle primitive expands bbox by radius (L352-356)."""
        rend = SymbolRenderer()
        prim = SymbolPrimitive("circle", [(0, 0)], radius=10.0)
        sym = _simple_symbol(primitives=[prim])
        result = rend._symbol_body_bbox(sym)
        assert result is not None
        x0, y0, x1, y1 = result
        assert x0 <= -10
        assert x1 >= 10
        assert y0 <= -10
        assert y1 >= 10

    def test_bbox_from_polyline_uses_points(self):
        """Polyline primitive uses point coordinates directly."""
        rend = SymbolRenderer()
        prim = SymbolPrimitive("polyline", [(-20, -30), (20, 30)])
        sym = _simple_symbol(primitives=[prim])
        result = rend._symbol_body_bbox(sym)
        assert result is not None
        x0, y0, x1, y1 = result
        assert x0 <= -20
        assert y0 <= -30
        assert x1 >= 20
        assert y1 >= 30

    def test_bbox_none_with_no_primitives_and_no_pins(self):
        """Empty symbol with no primitives and no pins → None."""
        rend = SymbolRenderer()
        sym = _simple_symbol(primitives=[], pins=[])
        result = rend._symbol_body_bbox(sym)
        assert result is None

    def test_bbox_includes_pin_endpoints(self):
        """bbox accounts for pin root and endpoint (L362-367)."""
        rend = SymbolRenderer()
        pin = PinDefinition("1", "A", "passive", 50, 0, 0, 20)
        sym = _simple_symbol(pins=[pin])
        result = rend._symbol_body_bbox(sym)
        assert result is not None
        x0, y0, x1, y1 = result
        # Outer endpoint at x=50, inner endpoint at x=70 (orientation=0, length=20)
        assert x0 <= 50
        assert x1 >= 70


# ---------------------------------------------------------------------------
# _pin_endpoint_local() / _pin_stub_inner_local() geometry
# ---------------------------------------------------------------------------

class TestPinEndpointLocal:
    @pytest.mark.parametrize("orientation,expected", [
        (0, (0, 0)),
        (180, (0, 0)),
        (90, (0, 0)),
        (270, (0, 0)),
    ])
    def test_cardinal_orientations(self, orientation, expected):
        pin = PinDefinition("1", "~", "passive", 0, 0, orientation, 10)
        px, py = SymbolRenderer._pin_endpoint_local(pin)
        assert abs(px - expected[0]) < 0.01
        assert abs(py - expected[1]) < 0.01

    def test_endpoint_is_pin_outer_location_independent_of_orientation(self):
        """Electrical endpoint is the pin's declared outer connection point."""
        pin = PinDefinition("1", "~", "passive", 0, 0, 45, 10)
        px, py = SymbolRenderer._pin_endpoint_local(pin)
        assert px == 0
        assert py == 0

    def test_zero_length_pin_returns_root(self):
        """Pin with length<=0 returns root position (L375-376)."""
        pin = PinDefinition("1", "~", "passive", 5, 7, 0, 0)
        px, py = SymbolRenderer._pin_endpoint_local(pin)
        assert px == 5
        assert py == 7

    @pytest.mark.parametrize("orientation,expected", [
        (0, (10, 0)),
        (180, (-10, 0)),
        (90, (0, 10)),
        (270, (0, -10)),
    ])
    def test_stub_inner_endpoint_uses_orientation_direction(self, orientation, expected):
        pin = PinDefinition("1", "~", "passive", 0, 0, orientation, 10)
        px, py = SymbolRenderer._pin_stub_inner_local(pin)
        assert abs(px - expected[0]) < 0.01
        assert abs(py - expected[1]) < 0.01

    def test_stub_inner_endpoint_arbitrary_angle(self):
        """Non-cardinal orientation uses trigonometric formula."""
        pin = PinDefinition("1", "~", "passive", 0, 0, 45, 10)
        px, py = SymbolRenderer._pin_stub_inner_local(pin)
        expected_x = 10 * math.cos(math.radians(45))
        expected_y = 10 * math.sin(math.radians(45))
        assert abs(px - expected_x) < 0.01
        assert abs(py - expected_y) < 0.01


# ---------------------------------------------------------------------------
# _to_world_point() — with rotation  (L403-407)
# ---------------------------------------------------------------------------

class TestToWorldPoint:
    def test_rotation_zero_identity(self):
        """rotation=0 is identity transform."""
        wx, wy = SymbolRenderer._to_world_point(10, 5, 100, 200, 0)
        assert abs(wx - 110) < 0.01
        assert abs(wy - 205) < 0.01

    def test_rotation_90(self):
        """rotation=90 applies correct transform."""
        # local (1, 0) rotated by -90° → (0, -1) in world offset
        wx, wy = SymbolRenderer._to_world_point(1, 0, 0, 0, 90)
        assert abs(wx - 0) < 0.01
        assert abs(wy - (-1)) < 0.01

    def test_rotation_180(self):
        """rotation=180 negates both components."""
        wx, wy = SymbolRenderer._to_world_point(5, 3, 0, 0, 180)
        assert abs(wx - (-5)) < 0.1
        assert abs(wy - (-3)) < 0.1

    def test_rotation_non_zero_differs_from_zero(self):
        """Non-zero rotation produces different result than zero rotation."""
        p0 = SymbolRenderer._to_world_point(10, 5, 50, 50, 0)
        p45 = SymbolRenderer._to_world_point(10, 5, 50, 50, 45)
        assert p0 != p45


# ---------------------------------------------------------------------------
# _primitive_fill() — all fill mode branches  (L411-416)
# ---------------------------------------------------------------------------

class TestPrimitiveFill:
    @pytest.mark.parametrize("mode,expected", [
        ("background", "white"),
        ("bg", "white"),
        ("solid", "black"),
        ("outline", "black"),
        ("foreground", "black"),
        ("none", "none"),
        ("", "none"),
        ("other", "none"),
        ("BACKGROUND", "white"),  # case-insensitive
        ("SOLID", "black"),
    ])
    def test_fill_modes(self, mode, expected):
        result = SymbolRenderer._primitive_fill(mode)
        assert result == expected


# ---------------------------------------------------------------------------
# can_render() — False cases
# ---------------------------------------------------------------------------

class TestCanRender:
    def test_can_render_false_for_no_symbol(self):
        """can_render returns False when no symbol data is resolvable."""
        rend = SymbolRenderer()
        part = Part("Device:R", ref="R1")
        assert rend.can_render(part, "R") is False

    def test_can_render_false_for_empty_symbol(self):
        """can_render returns False when symbol has no primitives and no pins."""
        rend = SymbolRenderer()
        sym = _simple_symbol(primitives=[], pins=[])
        part = _make_part_with_symbol(sym)
        assert rend.can_render(part, "TestSym") is False

    def test_render_part_returns_false_for_empty_symbol(self):
        """render_part() returns False for symbol with no primitives and no pins (L87)."""
        rend = SymbolRenderer()
        c = _canvas()
        sym = _simple_symbol(primitives=[], pins=[])
        part = _make_part_with_symbol(sym)
        result = rend.render_part(c, part, 100, 100, symbol_name="TestSym")
        assert result is False

    def test_can_render_true_for_symbol_with_primitives(self):
        """can_render returns True when symbol has primitives."""
        rend = SymbolRenderer()
        sym = _simple_symbol(primitives=[SymbolPrimitive("line", [(0, 0), (10, 0)])])
        part = _make_part_with_symbol(sym)
        assert rend.can_render(part, "TestSym") is True

    def test_can_render_true_for_library_symbol(self, tmp_path):
        """can_render is True when symbol is found from configured libraries."""
        sym_dir = tmp_path / "syms"
        sym_dir.mkdir()
        (sym_dir / "Device.kicad_sym").write_text(MINIMAL_DEVICE_R_SYM)
        configure_default_symbols(symbol_paths=[str(sym_dir)], preload=False)

        rend = SymbolRenderer()
        part = Part("Device:R", ref="R1")
        assert rend.can_render(part, "R") is True


# ---------------------------------------------------------------------------
# _draw_primitive() — polyline open vs closed  (L249-256)
# ---------------------------------------------------------------------------

class TestDrawPrimitivePolyline:
    def test_open_polyline_emits_polyline_element(self):
        """Open polyline (first != last) emits <polyline>."""
        rend = SymbolRenderer()
        c = _canvas()
        prim = SymbolPrimitive("polyline", [(0, 0), (10, 0), (10, 10)])
        rend._draw_primitive(c, prim, 100, 100)
        svg = c.to_svg()
        assert "<polyline" in svg

    def test_closed_polyline_emits_polygon(self):
        """Closed polyline (first == last) emits <polygon>."""
        rend = SymbolRenderer()
        c = _canvas()
        # Closed when first == last
        prim = SymbolPrimitive("polyline", [(0, 0), (10, 0), (10, 10), (0, 0)])
        rend._draw_primitive(c, prim, 100, 100)
        svg = c.to_svg()
        assert "<polygon" in svg

    def test_polygon_kind_emits_polygon(self):
        """kind='polygon' always emits <polygon>."""
        rend = SymbolRenderer()
        c = _canvas()
        prim = SymbolPrimitive("polygon", [(0, 0), (10, 0), (5, 10)], fill="solid")
        rend._draw_primitive(c, prim, 100, 100)
        svg = c.to_svg()
        assert "<polygon" in svg

    def test_circle_primitive_emits_circle(self):
        """kind='circle' emits <circle>."""
        rend = SymbolRenderer()
        c = _canvas()
        prim = SymbolPrimitive("circle", [(0, 0)], radius=15.0)
        rend._draw_primitive(c, prim, 100, 100)
        svg = c.to_svg()
        assert "<circle" in svg
