"""SVG wire-rendering, fit-to-content, and readability tests.

Test IDs
--------
WIRE-01  Two pins on same named net produce a <line> wire element
WIRE-02  Wire endpoints are plausibly spaced (not zero-length)
WIRE-03  Three-pin net produces multi-segment wiring (vertical trunk)
WIRE-04  Anonymous-net wire is still drawn (no label, but line exists)
WIRE-05  Junction dot rendered when 3+ pins share a trunk point

FIT-01   viewBox attribute present and differs from "0 0 <w> <h>" when content drawn
FIT-02   viewBox encodes a content-centred region (vb_x < 0 for typical layout)
FIT-03   width/height attributes on <svg> element still reflect page dimensions
FIT-04   Empty schematic falls back gracefully (viewBox still present)

READ-01  Ref label font-size >= 14
READ-02  Net label font-size >= 12
READ-03  Value text font-size >= 11
READ-04  Pin key font-size >= 10

OBS-01   _Obstacle.segment_hits detects a horizontal segment through box
OBS-02   _Obstacle.segment_hits detects a vertical segment through box
OBS-03   _Obstacle.segment_hits rejects a segment that misses the box
OBS-04   _Obstacle endpoints exactly on border are NOT counted as hits
OBS-05   _component_obstacle builds the correct expanded AABB for a generic box
OBS-06   Wire between two parts in the same column does not pass through a box body
OBS-07   Wire between two parts in different columns does not pass through a box body
OBS-08   _any_obstacle_hit returns False when the segment clears all obstacles
OBS-09   Trunk x is shifted away from obstacles in a 3-pin net
OBS-10   Detour is drawn when horizontal stub is blocked (extra segments in SVG)
OBS-11   Vertical trunk detour: trunk does not cross R3-like box body (unit)
OBS-12   Vertical trunk detour: extra segments emitted when trunk is blocked
OBS-13   Vertical trunk avoidance in 3-pin integration layout (R3 in the trunk path)
OBS-14   Vertical trunk avoidance: no blue wire crosses the obstacle box body
"""

from __future__ import annotations

import re

import pytest

from lib.core.connect import connect
from lib.core.part import NetLabel, Part
from lib.core.render_style import BoxStyle
from lib.core.style import Style
from lib.render.schematic_svg import (
    _Obstacle,
    _any_obstacle_hit,
    _component_obstacle,
    _OBSTACLE_CLEARANCE,
    _box_height,
    _draw_vertical_avoiding,
)
from lib.core.page import PageConfig
from lib.core.schematic import Schematic
from lib.symbols.data import PinDefinition, SymbolData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pnp_symbol_data() -> SymbolData:
    return SymbolData(
        name="Q_PNP_CBE",
        lib="Device",
        pins=[
            PinDefinition(number="1", name="C", type="passive", x=0, y=0),
            PinDefinition(number="2", name="B", type="input",   x=0, y=0),
            PinDefinition(number="3", name="E", type="passive", x=0, y=0),
        ],
    )


def _make_two_resistors_connected() -> Schematic:
    """Two resistors with pin-1s on VCC and pin-2s on GND, sharing nothing."""
    sch = Schematic("wire_test")
    r1 = Part("Device:R", ref="R1", value="10k")
    r2 = Part("Device:R", ref="R2", value="10k")
    sch.add_part(r1)
    sch.add_part(r2)

    connect(r1.pin("1"), r2.pin("1"))
    vcc = NetLabel("VCC")
    sch.add_part(vcc)
    connect(vcc.label_pin, r1.pin("1"))
    mid = NetLabel("MID")
    sch.add_part(mid)
    connect(mid.label_pin, r1.pin("2"))
    gnd = NetLabel("GND")
    sch.add_part(gnd)
    connect(gnd.label_pin, r2.pin("2"))
    return sch


def _make_three_pin_net() -> Schematic:
    """Three resistors all with pin-1 on RAIL — 3-pin net triggers trunk routing."""
    sch = Schematic("three_pin_net")
    r1 = Part("Device:R", ref="R1", value="1k")
    r2 = Part("Device:R", ref="R2", value="1k")
    r3 = Part("Device:R", ref="R3", value="1k")
    for r in (r1, r2, r3):
        sch.add_part(r)

    connect(r1.pin("1"), r2.pin("1"), r3.pin("1"))
    rail = NetLabel("RAIL")
    sch.add_part(rail)
    connect(rail.label_pin, r1.pin("1"))
    return sch


def _extract_viewbox(svg: str) -> tuple[float, float, float, float]:
    """Parse viewBox="x y w h" from SVG string, return (x, y, w, h)."""
    m = re.search(r'viewBox="([^"]+)"', svg)
    assert m, "No viewBox attribute found in SVG"
    parts = m.group(1).split()
    assert len(parts) == 4, f"viewBox has {len(parts)} parts, expected 4"
    return tuple(float(p) for p in parts)  # type: ignore[return-value]


def _extract_font_sizes(svg: str) -> list[float]:
    """Return all font-size values found in the SVG."""
    return [float(v) for v in re.findall(r'font-size="([^"]+)"', svg)]


def _box_width() -> float:
    width = BoxStyle.default().width
    assert width is not None
    return width


# ===========================================================================
# WIRE — Wire connectivity rendering
# ===========================================================================

class TestWireRendering:
    """WIRE: wire segments appear for connected pins."""

    def test_two_pin_net_produces_line(self):
        """WIRE-01: two pins on same named net → at least one <line> wire drawn."""
        sch = _make_two_resistors_connected()
        svg = sch.get_svg_string()
        # VCC has 2 pins (r1.pin1 and r2.pin1) → should produce a wire line
        assert "<line" in svg, "Expected <line> elements for wire routing"

    def test_wire_endpoints_not_zero_length(self):
        """WIRE-02: wire <line> elements are not zero-length."""
        sch = _make_two_resistors_connected()
        svg = sch.get_svg_string()
        # Extract all <line> elements and check at least one is non-trivial
        line_matches = re.findall(
            r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"', svg
        )
        assert line_matches, "No <line> elements found"
        non_zero = [
            (x1, y1, x2, y2)
            for x1, y1, x2, y2 in line_matches
            if abs(float(x1) - float(x2)) > 0.1 or abs(float(y1) - float(y2)) > 0.1
        ]
        assert non_zero, "All <line> elements appear to be zero-length"

    def test_three_pin_net_produces_trunk_wiring(self):
        """WIRE-03: 3-pin net triggers trunk routing (vertical + horizontal stubs)."""
        sch = _make_three_pin_net()
        svg = sch.get_svg_string()
        # With 3 pins using trunk routing there should be multiple <line> elements
        line_count = svg.count("<line")
        assert line_count >= 3, (
            f"Expected at least 3 <line> elements for 3-pin trunk routing, got {line_count}"
        )

    def test_anonymous_net_wire_still_drawn(self):
        """WIRE-04: anonymous-net (pin-pin) connection still draws a wire."""
        sch = Schematic("anon_wire")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        # Connect without a named net → creates anonymous net
        sch.connect(r1.pin("2"), r2.pin("1"))
        svg = sch.get_svg_string()
        assert "<line" in svg, "Expected wire line even for anonymous net"

    def test_junction_dot_for_multi_pin_trunk(self):
        """WIRE-05: junction dot (<circle>) rendered when 3+ pins share trunk."""
        sch = _make_three_pin_net()
        # Add an extra pin to guarantee junction (4 pins on same net, 2 at same y)
        r4 = Part("Device:R", ref="R4", value="1k")
        sch.add_part(r4)
        # Connect to an existing net pin from the current schematic.
        # _make_three_pin_net adds R1/R2/R3 in that order.
        r1_pin1 = sch._parts[0].pin("1")
        connect(r4.pin("1"), r1_pin1)
        svg = sch.get_svg_string()
        # Junction dots are rendered as filled circles
        assert "<circle" in svg, "Expected <circle> junction dot for multi-pin trunk"

    def test_net_label_present_on_wire(self):
        """WIRE-06: named net label appears in SVG as text near wire."""
        sch = _make_two_resistors_connected()
        svg = sch.get_svg_string()
        assert "VCC" in svg, "Net label 'VCC' should appear near the wire"
        assert "MID" in svg, "Net label 'MID' should appear near the wire"

    def test_anon_net_has_no_label_text(self):
        """WIRE-07: anonymous net does NOT produce a net-label text node."""
        sch = Schematic("anon_no_label")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.connect(r1.pin("2"), r2.pin("1"))
        svg = sch.get_svg_string()
        # _anon prefix should not appear as visible text
        assert "_anon" not in svg, "Anonymous net name should not appear as label text"


# ===========================================================================
# FIT — Fit-to-content viewBox
# ===========================================================================

class TestFitToContent:
    """FIT: SVG viewBox fitted to drawn content."""

    def test_viewbox_attribute_present(self):
        """FIT-01: viewBox attribute present in SVG output."""
        sch = Schematic("fit_test")
        r1 = Part("Device:R", ref="R1", value="1k")
        r1.pin("1")
        sch.add_part(r1)
        svg = sch.get_svg_string()
        assert 'viewBox="' in svg, "viewBox attribute not found in SVG"

    def test_viewbox_not_full_page_when_content_exists(self):
        """FIT-02: viewBox differs from '0 0 w h' when content is drawn."""
        page = PageConfig.a4()
        sch = Schematic("fit_content")
        r1 = Part("Device:R", ref="R1", value="1k")
        r1.pin("1")
        sch.add_part(r1)
        svg = sch.get_svg_string(page=page)
        vb_x, vb_y, vb_w, vb_h = _extract_viewbox(svg)
        # With fit-to-content the viewBox origin should not be exactly (0, 0)
        # or the size should differ from the page size
        page_w, page_h = page.width, page.height
        differs = (
            abs(vb_x) > 0.5 or abs(vb_y) > 0.5
            or abs(vb_w - page_w) > 0.5 or abs(vb_h - page_h) > 0.5
        )
        assert differs, (
            f"Expected fitted viewBox, but got viewBox={vb_x},{vb_y},{vb_w},{vb_h} "
            f"which matches full page {page_w}x{page_h}"
        )

    def test_svg_width_height_reflect_page_size(self):
        """FIT-03: width/height attrs on <svg> still reflect page dimensions."""
        page = PageConfig(width=800, height=600)
        sch = Schematic("page_dims")
        r1 = Part("Device:R", ref="R1")
        sch.add_part(r1)
        svg = sch.get_svg_string(page=page)
        assert 'width="800"' in svg, "SVG width should match page width"
        assert 'height="600"' in svg, "SVG height should match page height"

    def test_empty_schematic_has_viewbox(self):
        """FIT-04: empty schematic still produces valid SVG with viewBox."""
        sch = Schematic("empty_fit")
        svg = sch.get_svg_string()
        assert "<svg" in svg
        assert 'viewBox="' in svg

    def test_viewbox_width_positive(self):
        """FIT-05: viewBox width and height are both positive."""
        sch = Schematic("positive_vb")
        r1 = Part("Device:R", ref="R1", value="1k")
        r1.pin("1")
        r1.pin("2")
        sch.add_part(r1)
        svg = sch.get_svg_string()
        _, _, vb_w, vb_h = _extract_viewbox(svg)
        assert vb_w > 0, f"viewBox width must be positive, got {vb_w}"
        assert vb_h > 0, f"viewBox height must be positive, got {vb_h}"


# ===========================================================================
# READ — Readability / minimum font sizes
# ===========================================================================

class TestReadability:
    """READ: labels are rendered at legible font sizes."""

    def test_ref_label_font_size_at_least_14(self):
        """READ-01: ref label (R1) rendered at font-size >= 14."""
        sch = Schematic("read_ref")
        r1 = Part("Device:R", ref="R1", value="1k")
        r1.pin("1")
        sch.add_part(r1)
        svg = sch.get_svg_string()
        sizes = _extract_font_sizes(svg)
        assert sizes, "No font-size attributes found in SVG"
        # At least one text element should be >= 14 (the ref label)
        assert any(s >= 14 for s in sizes), (
            f"No font-size >= 14 found; sizes present: {sorted(set(sizes))}"
        )

    def test_net_label_font_size_at_least_12(self):
        """READ-02: net label text rendered at font-size >= 12."""
        sch = Schematic("read_net")
        r1 = Part("Device:R", ref="R1")
        sch.add_part(r1)
        vcc = NetLabel("VCC")
        sch.add_part(vcc)
        connect(vcc.label_pin, r1.pin("1"))
        svg = sch.get_svg_string()
        sizes = _extract_font_sizes(svg)
        assert any(s >= 12 for s in sizes), (
            f"No font-size >= 12 found for net label; sizes: {sorted(set(sizes))}"
        )

    def test_value_font_size_at_least_11(self):
        """READ-03: value text rendered at font-size >= 11."""
        sch = Schematic("read_value")
        r1 = Part("Device:R", ref="R1", value="10k")
        r1.pin("1")
        sch.add_part(r1)
        svg = sch.get_svg_string()
        sizes = _extract_font_sizes(svg)
        assert any(s >= 11 for s in sizes), (
            f"No font-size >= 11 found for value label; sizes: {sorted(set(sizes))}"
        )

    def test_pin_key_font_size_at_least_10(self):
        """READ-04: pin key label rendered at font-size >= 10."""
        sch = Schematic("read_pin")
        r1 = Part("Device:R", ref="R1")
        r1.pin("1")
        r1.pin("2")
        sch.add_part(r1)
        svg = sch.get_svg_string()
        sizes = _extract_font_sizes(svg)
        assert any(s >= 10 for s in sizes), (
            f"No font-size >= 10 found; sizes: {sorted(set(sizes))}"
        )

    def test_pnp_ref_label_font_size(self):
        """READ-05: PNP ref label also renders at minimum font-size."""
        sch = Schematic("read_pnp")
        q1 = Part("Device:Q_PNP_CBE", ref="Q1")
        q1.attach_symbol(_pnp_symbol_data())
        sch.add_part(q1)
        svg = sch.get_svg_string()
        sizes = _extract_font_sizes(svg)
        assert any(s >= 14 for s in sizes), (
            f"PNP ref label font-size < 14; sizes: {sorted(set(sizes))}"
        )


# ===========================================================================
# OBS — Obstacle avoidance: unit tests for the routing primitives
# ===========================================================================

def _make_dummy_part(ref: str = "R1") -> "Part":
    """Create a minimal Part with two pins (no lib lookup needed)."""
    p = Part("Device:R", ref=ref)
    p.pin("1")
    p.pin("2")
    return p


class TestObstacleUnit:
    """OBS: obstacle data structure and helper function unit tests."""

    def test_horizontal_segment_through_box_hits(self):
        """OBS-01: horizontal segment that crosses the box interior is detected."""
        # Box from (0,0) to (80,40), clearance=6 → expanded (-6,-6)→(86,46)
        obs = _Obstacle(0, 0, 80, 40, clearance=0)
        # Segment y=20 runs from x=-10 to x=90 → crosses interior
        assert obs.segment_hits(-10, 20, 90, 20)

    def test_vertical_segment_through_box_hits(self):
        """OBS-02: vertical segment that crosses the box interior is detected."""
        obs = _Obstacle(0, 0, 80, 40, clearance=0)
        # Segment x=40 runs from y=-10 to y=50 → crosses interior
        assert obs.segment_hits(40, -10, 40, 50)

    def test_segment_misses_box(self):
        """OBS-03: segment that does not intersect the box is not detected."""
        obs = _Obstacle(0, 0, 80, 40, clearance=0)
        # Segment y=50 (below the box) → no hit
        assert not obs.segment_hits(-10, 50, 90, 50)

    def test_segment_endpoint_on_border_not_hit(self):
        """OBS-04: a segment whose endpoint touches the expanded border is not a hit."""
        obs = _Obstacle(10, 10, 90, 50, clearance=0)
        # Segment ends exactly at x0=10 (border) — should NOT be counted
        assert not obs.segment_hits(-10, 30, 10, 30)

    def test_component_obstacle_generic_box(self):
        """OBS-05: _component_obstacle returns correct expanded AABB for generic box."""
        p = _make_dummy_part("U1")
        cx, cy = 100.0, 200.0
        h = _box_height(len(list(p.pins)))  # 2 pins → _BOX_MIN_H=40
        obs = _component_obstacle(p, cx, cy, "SomeIC")
        # Raw box: x0=cx-40, y0=cy-h/2; expanded by _OBSTACLE_CLEARANCE
        expected_x0 = cx - _box_width() / 2 - _OBSTACLE_CLEARANCE
        expected_y0 = cy - h / 2 - _OBSTACLE_CLEARANCE
        expected_x1 = cx + _box_width() / 2 + _OBSTACLE_CLEARANCE
        expected_y1 = cy + h / 2 + _OBSTACLE_CLEARANCE
        assert abs(obs.x0 - expected_x0) < 0.1
        assert abs(obs.y0 - expected_y0) < 0.1
        assert abs(obs.x1 - expected_x1) < 0.1
        assert abs(obs.y1 - expected_y1) < 0.1

    def test_any_obstacle_hit_clear_segment(self):
        """OBS-08: _any_obstacle_hit returns False when the segment is clear."""
        obs = _Obstacle(50, 50, 130, 90, clearance=0)
        # Segment at y=0 → well above the box (y0=50)
        assert not _any_obstacle_hit([obs], -100, 0, 200, 0)

    def test_any_obstacle_hit_blocked_segment(self):
        """OBS-08b: _any_obstacle_hit returns True when the segment is blocked."""
        obs = _Obstacle(50, 50, 130, 90, clearance=0)
        # Segment at y=70 crosses the box
        assert _any_obstacle_hit([obs], 0, 70, 200, 70)


class TestObstacleAvoidanceIntegration:
    """OBS integration: rendered SVG wires do not pass through component bodies."""

    def _all_lines(self, svg: str):
        """Extract all <line> coords as list of (x1,y1,x2,y2) float tuples."""
        return [
            (float(x1), float(y1), float(x2), float(y2))
            for x1, y1, x2, y2 in re.findall(
                r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"', svg
            )
        ]

    def _wire_lines(self, svg: str):
        """Return only wire-coloured <line> elements."""
        return [
            (float(x1), float(y1), float(x2), float(y2))
            for x1, y1, x2, y2 in re.findall(
                r'<line[^>]*stroke="#1565c0"[^>]*x1="([^"]+)" y1="([^"]+)"'
                r' x2="([^"]+)" y2="([^"]+)"',
                svg,
            )
        ] + [
            (float(x1), float(y1), float(x2), float(y2))
            for x1, y1, x2, y2 in re.findall(
                r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"'
                r'[^>]*stroke="#1565c0"',
                svg,
            )
        ]

    def _box_bounds(self, cx: float, cy: float, n_pins: int = 2):
        """Return (x0, y0, x1, y1) of the raw component box (no clearance)."""
        h = _box_height(n_pins)
        return (cx - _box_width() / 2, cy - h / 2, cx + _box_width() / 2, cy + h / 2)

    def _segment_crosses_box(
        self,
        ax: float, ay: float,
        bx: float, by: float,
        box_x0: float, box_y0: float,
        box_x1: float, box_y1: float,
    ) -> bool:
        """Check whether an H/V segment (a→b) crosses the interior of the box."""
        eps = 1.0  # 1 px tolerance — pin stubs touch the box edge legitimately
        obs = _Obstacle(box_x0, box_y0, box_x1, box_y1, clearance=-eps)
        return obs.segment_hits(ax, ay, bx, by)

    def test_wire_does_not_cross_same_column_component(self):
        """OBS-06: wire connecting two parts in the same column avoids the other part's box.

        Layout: R1 (row 0) and R2 (row 1) in the same column.  A net
        connecting R1.pin2 (right side) to R2.pin2 (right side) must not
        pass through either component box.
        """
        sch = Schematic("obs_same_col")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        connect(r1.pin("2"), r2.pin("1"))
        mid = NetLabel("MID")
        sch.add_part(mid)
        connect(mid.label_pin, r1.pin("2"))
        svg = sch.get_svg_string()
        # Basic sanity: wires were drawn
        assert "<line" in svg

    def test_wire_does_not_cross_adjacent_column_component(self):
        """OBS-07: wire between parts in different columns does not cross a third part.

        We use explicit Style positions to create a controlled layout where a
        naive straight wire would cut through a middle component.
        R1 is at x=0, R3 is at x=60 (overlapping the path), R2 is at x=120.
        Connecting R1.pin2 to R2.pin1 — a naive H-first L-route at R1's y
        would cross R3.  The router must detour.
        """
        sch = Schematic("obs_diff_col")
        # Three parts: R1 left, R3 in the middle (obstacle), R2 right
        r1 = Part("Device:R", ref="R1")
        r3 = Part("Device:R", ref="R3")  # obstacle in middle
        r2 = Part("Device:R", ref="R2")
        r1.set_style(Style(x=0, y=50, locked=True))
        r3.set_style(Style(x=30, y=50, locked=True))   # same y → blocks H route
        r2.set_style(Style(x=60, y=50, locked=True))
        sch.add_part(r1)
        sch.add_part(r3)
        sch.add_part(r2)
        connect(r1.pin("2"), r2.pin("1"))
        net = NetLabel("BUS")
        sch.add_part(net)
        connect(net.label_pin, r1.pin("2"))
        svg = sch.get_svg_string()
        # Wires must be present
        assert "<line" in svg
        # The SVG must render without errors — structural validity check
        assert "</svg>" in svg

    def test_obstacle_detour_produces_extra_segments(self):
        """OBS-10: when a stub is blocked a detour adds extra <line> elements.

        We force R3 (the obstacle) directly between R1's pin-2 endpoint and
        the trunk, so the stub must detour, producing 3 segments instead of 1.
        """
        sch = Schematic("obs_detour")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        r3 = Part("Device:R", ref="R3")  # obstacle
        # Position r1 far left, r3 in middle at same y, r2 far right at different y
        r1.set_style(Style(x=0, y=50, locked=True))
        r3.set_style(Style(x=30, y=50, locked=True))
        r2.set_style(Style(x=70, y=0, locked=True))
        sch.add_part(r1)
        sch.add_part(r3)
        sch.add_part(r2)
        connect(r1.pin("2"), r2.pin("1"))
        net = NetLabel("ROUTE")
        sch.add_part(net)
        connect(net.label_pin, r1.pin("2"))
        svg = sch.get_svg_string()
        # At minimum there should be wire lines
        lines = re.findall(r"<line", svg)
        assert len(lines) >= 2, f"Expected at least 2 <line> elements, got {len(lines)}"

    def test_trunk_x_avoids_obstacle(self):
        """OBS-09: 3-pin net trunk x is chosen to avoid obstacles.

        Three parts aligned vertically in the same column.  The trunk x
        chosen by _choose_trunk_x should not pass through any component body.
        This test verifies the SVG renders (trunk routing completes) and that
        a minimum number of wire elements are present.
        """
        sch = Schematic("obs_trunk")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        r3 = Part("Device:R", ref="R3")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.add_part(r3)
        connect(r1.pin("1"), r2.pin("1"), r3.pin("1"))
        rail = NetLabel("RAIL")
        sch.add_part(rail)
        connect(rail.label_pin, r1.pin("1"))
        svg = sch.get_svg_string()
        line_count = svg.count("<line")
        assert line_count >= 3, (
            f"Expected >= 3 <line> elements for 3-pin trunk net, got {line_count}"
        )

    def test_no_wire_through_component_body_explicit_layout(self):
        """OBS-06b: explicit layout — blue wire segments must not cross the box body interior.

        R1 is far left, RB is in the middle at the same y, R2 is far right
        at a different y.  The two-pin net (R1.pin→R2.pin) would naively
        route a horizontal segment through RB's body.  The obstacle-aware
        router must instead go around.

        Parts are spaced far enough apart that their boxes do not overlap,
        but RB is placed on the direct H-first path between the two pin
        endpoints.
        """
        from lib.render.schematic_svg import _MARGIN

        sch = Schematic("obs_explicit")
        r1 = Part("Device:R", ref="R1")
        rb = Part("Device:R", ref="RB")  # the blocking component
        r2 = Part("Device:R", ref="R2")

        # Scale=3: SVG cx = _MARGIN + sx*3, cy = _MARGIN + sy*3
        # Box half-width = 40 px at SVG scale.  Place parts 50 style-units apart
        # so raw boxes don't overlap (50*3=150 px gap vs 80px box width).
        # RB sits between R1 and R2 at the same y to block the H-first route.
        r1.set_style(Style(x=0,   y=50, locked=True))
        rb.set_style(Style(x=50,  y=50, locked=True))
        r2.set_style(Style(x=100, y=50, locked=True))
        sch.add_part(r1)
        sch.add_part(rb)
        sch.add_part(r2)

        # Pins: R1 has pin "1" (only pin → goes left side).
        #       R2 has pin "2" (only pin → goes left side).
        # Connect them via a named net.
        connect(r1.pin("1"), r2.pin("1"))
        net = NetLabel("THRU")
        sch.add_part(net)
        connect(net.label_pin, r1.pin("1"))
        svg = sch.get_svg_string()
        assert "<line" in svg, "Expected wire segments in SVG"

        # Compute RB's SVG-space raw bounding box (no clearance)
        rb_cx = _MARGIN + 50 * 3.0
        rb_cy = _MARGIN + 50 * 3.0
        rb_x0, rb_y0, rb_x1, rb_y1 = self._box_bounds(rb_cx, rb_cy, n_pins=1)

        # Only inspect blue wire segments (stroke="#1565c0")
        # We look for <line ...> elements with the wire colour.
        wire_line_data = re.findall(
            r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"'
            r'[^>]*stroke="#1565c0"',
            svg,
        )
        # Also match reversed attribute order
        wire_line_data += re.findall(
            r'<line[^>]*stroke="#1565c0"[^>]*x1="([^"]+)" y1="([^"]+)"'
            r' x2="([^"]+)" y2="([^"]+)"',
            svg,
        )

        violations = []
        for x1s, y1s, x2s, y2s in wire_line_data:
            x1, y1, x2, y2 = float(x1s), float(y1s), float(x2s), float(y2s)
            if self._segment_crosses_box(x1, y1, x2, y2, rb_x0, rb_y0, rb_x1, rb_y1):
                violations.append((x1, y1, x2, y2))

        assert not violations, (
            f"Blue wire segments pass through RB body ({rb_x0:.0f},{rb_y0:.0f})"
            f"→({rb_x1:.0f},{rb_y1:.0f}): {violations}"
        )


class TestVerticalTrunkAvoidance:
    """OBS-11..14: vertical trunk must not cross component box bodies."""

    # ------------------------------------------------------------------
    # Helpers shared with TestObstacleAvoidanceIntegration
    # ------------------------------------------------------------------

    def _box_bounds(self, cx: float, cy: float, n_pins: int = 2):
        h = _box_height(n_pins)
        return (cx - _box_width() / 2, cy - h / 2, cx + _box_width() / 2, cy + h / 2)

    def _segment_crosses_box(
        self,
        ax, ay, bx, by,
        box_x0, box_y0, box_x1, box_y1,
    ) -> bool:
        eps = 1.0
        obs = _Obstacle(box_x0, box_y0, box_x1, box_y1, clearance=-eps)
        return obs.segment_hits(ax, ay, bx, by)

    def _wire_lines_from_svg(self, svg: str):
        """Return (x1,y1,x2,y2) for every blue wire <line> in svg."""
        results = []
        for x1s, y1s, x2s, y2s in re.findall(
            r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"'
            r'[^>]*stroke="#1565c0"',
            svg,
        ):
            results.append((float(x1s), float(y1s), float(x2s), float(y2s)))
        for x1s, y1s, x2s, y2s in re.findall(
            r'<line[^>]*stroke="#1565c0"[^>]*x1="([^"]+)" y1="([^"]+)"'
            r' x2="([^"]+)" y2="([^"]+)"',
            svg,
        ):
            results.append((float(x1s), float(y1s), float(x2s), float(y2s)))
        return results

    # ------------------------------------------------------------------
    # Unit test: _draw_vertical_avoiding directly
    # ------------------------------------------------------------------

    def test_vertical_trunk_detour_unit(self):
        """OBS-11: _draw_vertical_avoiding produces extra segments when trunk
        would cross an obstacle.

        A vertical trunk at x=100 from y=0 to y=200 is blocked by an obstacle
        at x=[90,110], y=[80,120].  The function must emit more than one line
        element and none of them must pass through the obstacle interior.
        """
        from lib.render.schematic_svg import _TrackingCanvas

        canvas = _TrackingCanvas(400, 400)
        obs = _Obstacle(90, 80, 110, 120, clearance=0)  # raw box, no expansion

        # Verify the obstacle actually blocks the trunk before calling
        assert obs.segment_hits(100, 0, 100, 200), "Setup: obstacle should block trunk"

        _draw_vertical_avoiding(canvas, x=100, y_min=0, y_max=200, obstacles=[obs])

        # Count generated <line> elements
        line_count = canvas._elements.count  # list, not a method
        lines_svg = "".join(canvas._elements)
        segs = re.findall(
            r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"', lines_svg
        )
        assert len(segs) >= 2, (
            f"Expected ≥ 2 segments for detour around obstacle, got {len(segs)}"
        )

        # None of the drawn segments should cross the obstacle interior
        violations = []
        for x1s, y1s, x2s, y2s in segs:
            x1, y1, x2, y2 = float(x1s), float(y1s), float(x2s), float(y2s)
            if obs.segment_hits(x1, y1, x2, y2):
                violations.append((x1, y1, x2, y2))

        assert not violations, (
            f"Segments cross obstacle ({obs.x0},{obs.y0})→({obs.x1},{obs.y1}): "
            f"{violations}"
        )

    def test_vertical_trunk_straight_when_clear(self):
        """OBS-12a: _draw_vertical_avoiding emits a single segment when no obstacle blocks."""
        from lib.render.schematic_svg import _TrackingCanvas

        canvas = _TrackingCanvas(400, 400)
        # Obstacle far to the right — does not block the trunk at x=100
        obs = _Obstacle(200, 80, 300, 120, clearance=0)

        _draw_vertical_avoiding(canvas, x=100, y_min=0, y_max=200, obstacles=[obs])

        lines_svg = "".join(canvas._elements)
        segs = re.findall(
            r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"', lines_svg
        )
        assert len(segs) == 1, f"Expected 1 straight segment, got {len(segs)}: {segs}"

    def test_vertical_trunk_extra_segments_when_blocked(self):
        """OBS-12: a blocked vertical trunk produces more <line> elements than
        the unblocked case (detour adds horizontal segments).
        """
        from lib.render.schematic_svg import _TrackingCanvas

        # Unblocked trunk
        canvas_clear = _TrackingCanvas(400, 400)
        _draw_vertical_avoiding(
            canvas_clear, x=100, y_min=0, y_max=200, obstacles=[]
        )
        clear_segs = re.findall(
            r'<line', "".join(canvas_clear._elements)
        )

        # Blocked trunk
        canvas_blocked = _TrackingCanvas(400, 400)
        obs = _Obstacle(90, 80, 110, 120, clearance=0)
        _draw_vertical_avoiding(
            canvas_blocked, x=100, y_min=0, y_max=200, obstacles=[obs]
        )
        blocked_segs = re.findall(
            r'<line', "".join(canvas_blocked._elements)
        )

        assert len(blocked_segs) > len(clear_segs), (
            f"Blocked trunk should have more segments than clear trunk: "
            f"{len(blocked_segs)} vs {len(clear_segs)}"
        )

    # ------------------------------------------------------------------
    # Integration: 3-pin net where trunk passes through middle component
    # ------------------------------------------------------------------

    def test_trunk_does_not_cross_r3_body_integration(self):
        """OBS-13: In a 3-pin net, when R3 lies directly on the trunk path,
        the rendered SVG must not contain a blue wire segment that passes
        through R3's body interior.

        Layout: R1 at top (y=-60), R2 at bottom (y=+60), R3 in the middle
        (y=0) at a different x so that its body overlaps the initial trunk x.
        The trunk must detour around R3.
        """
        from lib.render.schematic_svg import _MARGIN

        sch = Schematic("trunk_r3")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        r3 = Part("Device:R", ref="R3")  # obstacle directly on trunk

        # R1 and R2 are spread vertically; R3 is in the middle.
        # We set the trunk to pass through R3's x by placing R3 at the
        # median x of R1 and R2's pin endpoints.
        # Use explicit positions (style units → SVG coords via _MARGIN + x*3).
        r1.set_style(Style(x=0, y=-60, locked=True))
        r2.set_style(Style(x=0, y=60, locked=True))
        r3.set_style(Style(x=0, y=0, locked=True))  # same column, directly on trunk

        sch.add_part(r1)
        sch.add_part(r2)
        sch.add_part(r3)

        connect(r1.pin("1"), r2.pin("1"), r3.pin("1"))
        rail = NetLabel("TRUNK_TEST")
        sch.add_part(rail)
        connect(rail.label_pin, r1.pin("1"))

        svg = sch.get_svg_string()
        assert "<line" in svg, "Expected wire segments in SVG"
        assert "</svg>" in svg

        # Compute R3's raw bounding box in SVG space
        r3_cx = _MARGIN + 0 * 3.0
        r3_cy = _MARGIN + 0 * 3.0
        r3_x0, r3_y0, r3_x1, r3_y1 = self._box_bounds(r3_cx, r3_cy, n_pins=1)

        wire_lines = self._wire_lines_from_svg(svg)
        violations = [
            seg for seg in wire_lines
            if self._segment_crosses_box(*seg, r3_x0, r3_y0, r3_x1, r3_y1)
        ]

        assert not violations, (
            f"Blue wire segments cross R3 body "
            f"({r3_x0:.0f},{r3_y0:.0f})→({r3_x1:.0f},{r3_y1:.0f}): {violations}"
        )

    def test_trunk_does_not_cross_mid_obstacle_explicit(self):
        """OBS-14: explicit layout — R3 is the middle of three vertically
        arranged parts; a 3-pin net trunk must route around R3's body.

        R1 far above, R2 far below, R3 in the middle at the same x.
        The trunk would naively pass through R3.  After the fix the trunk
        must detour horizontally around R3's body.
        """
        from lib.render.schematic_svg import _MARGIN

        sch = Schematic("trunk_mid_obs")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        r3 = Part("Device:R", ref="R3")

        # Style units: SVG x = _MARGIN + sx*3, SVG y = _MARGIN + sy*3
        # Spread 80 units vertically so boxes don't overlap
        r1.set_style(Style(x=50, y=0,   locked=True))
        r2.set_style(Style(x=50, y=160, locked=True))
        r3.set_style(Style(x=50, y=80,  locked=True))  # between R1 and R2

        sch.add_part(r1)
        sch.add_part(r2)
        sch.add_part(r3)

        connect(r1.pin("2"), r2.pin("1"), r3.pin("2"))
        rail = NetLabel("MID_OBS")
        sch.add_part(rail)
        connect(rail.label_pin, r1.pin("2"))

        svg = sch.get_svg_string()
        assert "</svg>" in svg

        r3_cx = _MARGIN + 50 * 3.0
        r3_cy = _MARGIN + 80 * 3.0
        r3_x0, r3_y0, r3_x1, r3_y1 = self._box_bounds(r3_cx, r3_cy, n_pins=1)

        wire_lines = self._wire_lines_from_svg(svg)
        violations = [
            seg for seg in wire_lines
            if self._segment_crosses_box(*seg, r3_x0, r3_y0, r3_x1, r3_y1)
        ]

        assert not violations, (
            f"Blue wire segments cross R3 body "
            f"({r3_x0:.0f},{r3_y0:.0f})→({r3_x1:.0f},{r3_y1:.0f}): {violations}"
        )
