"""Regression tests for renderer scale/overlap/connectivity overhaul.

Test IDs
--------
RO-01  Parsed symbols use amplified pin geometry
RO-02  Page dimensions remain stable in exported SVG
RO-03  Labels avoid Q2 ref/VCC overlap and duplicate net text
RO-04  Q1.B and Q2.B nets stay continuous at pin endpoints
RO-05  Resistor pin endpoints use outer pin side
RO-06  Q1.B/Q2.B pin labels stay outside symbol body
RO-07  Q1.B branch avoids loop-like local backtrack
RO-08  Explicit Junction remains wire merge target
"""

from __future__ import annotations

import re
from collections import defaultdict, deque

import pytest

import lib.symbols.symbols as _sym_mod
from lib.core.junction import Junction
from lib.core.net import NetLabel
from lib.core.page import PageConfig
from lib.core.part import Part
from lib.core.render_style import RenderStyle, RenderTemplate, WireStyle
from lib.core.schematic import Schematic
from lib.render.schematic_svg import _MARGIN
from lib.render.symbol_renderer import SymbolRenderer
from lib.symbols import configure_default_symbols


@pytest.fixture(autouse=True)
def _configure_example_symbols() -> None:
    original = _sym_mod._DEFAULT_SYMBOLS
    _sym_mod._DEFAULT_SYMBOLS = None
    configure_default_symbols(symbol_paths=["examples/kicad-symbols"], preload=False)
    yield
    _sym_mod._DEFAULT_SYMBOLS = original


def _build_transistor_and_gate() -> tuple[Schematic, Part, Part]:
    sch = Schematic("transistor_and_gate")

    q1 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q1")
    q2 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q2")
    r1 = Part("Device:R", ref="R1", value="10K")
    r2 = Part("Device:R", ref="R2", value="10K")
    r3 = Part("Device:R", ref="R3", value="10K")
    r4 = Part("Device:R", ref="R4", value="10K")
    r5 = Part("Device:R", ref="R5", value="10K")

    for part in [q1, q2, r1, r2, r3, r4, r5]:
        sch.add_part(part)

    nl_a = NetLabel("A", direction="right")
    nl_b = NetLabel("B", direction="right")
    nl_vcc = NetLabel("VCC", direction="top")
    nl_gnd = NetLabel("GND", direction="bottom")
    nl_out = NetLabel("A_AND_B", direction="right")
    for nl in [nl_a, nl_b, nl_vcc, nl_gnd, nl_out]:
        sch.add_part(nl)

    sch.place(r1, x=20, y=25)
    sch.place(r2, x=20, y=75)
    sch.place(q1, x=65, y=50, rotation=90)
    sch.place(r3, x=120, y=50)
    sch.place(r4, x=65, y=110)
    sch.place(q2, x=155, y=50)
    sch.place(r5, x=155, y=110)

    sch.connect(nl_a.label_pin, r1.pin("1"))
    sch.connect(nl_b.label_pin, r2.pin("1"))
    sch.connect(r1.pin("2"), q1.pin("B"))
    sch.connect(r2.pin("2"), q1.pin("B"))
    sch.connect(nl_vcc.label_pin, q1.pin("E"))
    sch.connect(q1.pin("B"), r4.pin("1"))
    sch.connect(r4.pin("2"), nl_gnd.label_pin)

    sch.connect(q1.pin("C"), r3.pin("1"))
    sch.connect(r3.pin("2"), q2.pin("B"))
    sch.connect(q2.pin("B"), r5.pin("1"))
    sch.connect(r5.pin("2"), nl_gnd.label_pin)
    sch.connect(nl_vcc.label_pin, q2.pin("E"))
    sch.connect(q2.pin("C"), nl_out.label_pin)
    return sch, q1, q2


def _parse_text_nodes(svg: str) -> list[tuple[str, float, float, float, str]]:
    pattern = (
        r'<text x="([^"]+)" y="([^"]+)" font-size="([^"]+)"'
        r'[^>]*text-anchor="([^"]+)"[^>]*>([^<]+)</text>'
    )
    return [
        (text, float(x), float(y), float(font_size), anchor)
        for x, y, font_size, anchor, text in re.findall(pattern, svg)
    ]


def _parse_blue_wire_lines(svg: str) -> list[tuple[float, float, float, float]]:
    pattern = (
        r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"'
        r'[^>]*stroke="#1565c0"'
    )
    return [
        (float(x1), float(y1), float(x2), float(y2))
        for x1, y1, x2, y2 in re.findall(pattern, svg)
    ]


def _text_box(text: str, x: float, y: float, font_size: float, anchor: str) -> tuple[float, float, float, float]:
    width = len(text) * font_size * 0.6
    height = font_size
    if anchor == "middle":
        x0, x1 = x - width / 2, x + width / 2
    elif anchor == "end":
        x0, x1 = x - width, x
    else:
        x0, x1 = x, x + width
    y0, y1 = y - height / 2, y + height / 2
    return (x0, y0, x1, y1)


def _boxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _build_q1_b_branch_geometry() -> tuple[Schematic, Part, Part, Part]:
    """Exact geometry from docs/Q1B_ROUTING_TROUBLESHOOTING.md."""
    sch = Schematic("q1_b_branch_regression")

    q1 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q1")
    r1 = Part("Device:R", ref="R1", value="10K")
    r2 = Part("Device:R", ref="R2", value="10K")
    for part in [q1, r1, r2]:
        sch.add_part(part)

    sch.place(r1, x=20, y=25)
    sch.place(r2, x=20, y=75)
    sch.place(q1, x=65, y=50)

    sch.connect(r1.pin("1"), r2.pin("2"))
    sch.connect(r2.pin("2"), q1.pin("B"))
    return sch, r1, r2, q1


def _build_explicit_junction_bias_geometry() -> tuple[Schematic, Part, Part, Part, Junction]:
    sch = Schematic("junction_bias_regression")
    q1 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q1")
    r1 = Part("Device:R", ref="R1", value="10K")
    r2 = Part("Device:R", ref="R2", value="10K")
    j_bias = Junction(ref="J_Q1_BIAS")

    for part in [q1, r1, r2, j_bias]:
        sch.add_part(part)

    sch.place(r1, x=20, y=25)
    sch.place(r2, x=20, y=75)
    sch.place(q1, x=65, y=50)
    sch.place(j_bias, x=20, y=50)

    sch.connect(r1.pin("1"), j_bias.junction_pin)
    sch.connect(r2.pin("2"), j_bias.junction_pin)
    sch.connect(j_bias.junction_pin, q1.pin("B"))
    return sch, r1, r2, q1, j_bias


class TestRendererOverhaulRegressions:
    def test_RO_01_parsed_symbol_geometry_is_amplified(self):
        """RO-01: Parsed symbols expose amplified pin endpoint distance."""
        q2 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q2")
        q2.pin("B")
        q2.pin("C")
        q2.pin("E")

        renderer = SymbolRenderer()
        endpoints = renderer.pin_endpoints(q2, 100.0, 200.0, symbol_name="Q_PNP_CBE")
        q2_b = endpoints[("Q2", "2")]
        dist = abs(q2_b[0] - 100.0)
        assert dist == pytest.approx(30.48, rel=1e-6)

    def test_RO_02_page_dimensions_are_preserved(self):
        """RO-02: Exported SVG width/height match configured page size."""
        sch, _, _ = _build_transistor_and_gate()
        style = RenderStyle.default()
        tmpl = RenderTemplate.from_style(style, page=PageConfig(width=1200, height=900))
        svg = sch.get_svg_string(template=tmpl)

        m = re.search(r'<svg[^>]*width="([^"]+)"[^>]*height="([^"]+)"', svg)
        assert m is not None
        width = float(m.group(1))
        height = float(m.group(2))
        assert width == 1200.0
        assert height == 900.0

    def test_RO_03_high_scale_avoids_q2_vcc_overlap_and_duplicate_net_text(self):
        """RO-03: Render avoids Q2/VCC overlap and duplicate A_AND_B labels."""
        sch, _, _ = _build_transistor_and_gate()
        style = RenderStyle.default()
        tmpl = RenderTemplate.from_style(style, page=PageConfig.a1(landscape=True))
        svg = sch.get_svg_string(template=tmpl)
        nodes = _parse_text_nodes(svg)

        q2_node = next(node for node in nodes if node[0] == "Q2")
        q2_box = _text_box(*q2_node)

        vcc_near_q2 = [
            node for node in nodes
            if node[0] == "VCC" and node[1] > 400.0
        ]
        assert vcc_near_q2, "Expected at least one VCC label near Q2"
        for node in vcc_near_q2:
            assert not _boxes_overlap(q2_box, _text_box(*node))

        assert svg.count(">A_AND_B<") == 1

    def test_RO_04_q1_q2_b_pins_have_continuous_wire_connection(self):
        """RO-04: Blue wire segments terminate at Q1.B/Q2.B and continue."""
        sch, q1, q2 = _build_transistor_and_gate()
        style = RenderStyle.default()
        tmpl = RenderTemplate.from_style(style, page=PageConfig.a1(landscape=True))
        svg = sch.get_svg_string(template=tmpl)

        renderer = SymbolRenderer()
        q1_cx = _MARGIN + 65.0 * 3.0
        q1_cy = _MARGIN + 50.0 * 3.0
        q2_cx = _MARGIN + 155.0 * 3.0
        q2_cy = _MARGIN + 50.0 * 3.0
        q1_b = renderer.pin_endpoints(
            q1,
            q1_cx,
            q1_cy,
            symbol_name="Q_PNP_CBE",
            rotation=90,
        )[("Q1", "2")]
        q2_b = renderer.pin_endpoints(q2, q2_cx, q2_cy, symbol_name="Q_PNP_CBE")[("Q2", "2")]

        line_pattern = (
            r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"'
            r'[^>]*stroke="#1565c0"'
        )
        lines = [
            (float(x1), float(y1), float(x2), float(y2))
            for x1, y1, x2, y2 in re.findall(line_pattern, svg)
        ]
        assert lines, "Expected at least one blue wire segment"

        def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
            return abs(a[0] - b[0]) <= 0.2 and abs(a[1] - b[1]) <= 0.2

        def _point_on_segment(point: tuple[float, float], seg: tuple[float, float, float, float]) -> bool:
            px, py = point
            x1, y1, x2, y2 = seg
            if abs(y1 - y2) <= 0.2:  # horizontal
                if abs(py - y1) > 0.2:
                    return False
                lo, hi = min(x1, x2), max(x1, x2)
                return lo - 0.2 <= px <= hi + 0.2
            if abs(x1 - x2) <= 0.2:  # vertical
                if abs(px - x1) > 0.2:
                    return False
                lo, hi = min(y1, y2), max(y1, y2)
                return lo - 0.2 <= py <= hi + 0.2
            return False

        split_points: set[tuple[float, float]] = set()
        for x1, y1, x2, y2 in lines:
            split_points.add((round(x1, 2), round(y1, 2)))
            split_points.add((round(x2, 2), round(y2, 2)))

        for h in lines:
            hx1, hy1, hx2, hy2 = h
            if abs(hy1 - hy2) > 0.2:
                continue
            h_lo, h_hi = min(hx1, hx2), max(hx1, hx2)
            for v in lines:
                vx1, vy1, vx2, vy2 = v
                if abs(vx1 - vx2) > 0.2:
                    continue
                v_lo, v_hi = min(vy1, vy2), max(vy1, vy2)
                ix, iy = vx1, hy1
                if h_lo - 0.2 <= ix <= h_hi + 0.2 and v_lo - 0.2 <= iy <= v_hi + 0.2:
                    split_points.add((round(ix, 2), round(iy, 2)))

        graph: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
        for seg in lines:
            points = [point for point in split_points if _point_on_segment(point, seg)]
            x1, y1, x2, y2 = seg
            if abs(y1 - y2) <= 0.2:
                points.sort(key=lambda point: point[0])
            else:
                points.sort(key=lambda point: point[1])
            for idx in range(len(points) - 1):
                a = points[idx]
                b = points[idx + 1]
                graph[a].add(b)
                graph[b].add(a)

        def _node_for(endpoint: tuple[float, float]) -> tuple[float, float]:
            for node in graph:
                if _same_point(node, endpoint):
                    return node
            raise AssertionError(f"No wire node found for endpoint {endpoint}")

        def _assert_continuous_endpoint(endpoint: tuple[float, float], label: str) -> None:
            endpoint_node = _node_for(endpoint)
            neighbours = graph[endpoint_node]
            assert neighbours, f"No wire segment found at {label} endpoint {endpoint}"
            continued = any(len(graph[neighbour]) > 1 for neighbour in neighbours)
            assert continued, (
                f"{label} wire touches endpoint but does not continue into net routing"
            )

        _assert_continuous_endpoint(q1_b, "Q1.B")
        _assert_continuous_endpoint(q2_b, "Q2.B")

    def test_RO_05_resistor_pin_endpoints_use_outer_side(self):
        """RO-05: R pin endpoints stay at the outer connection side of stubs."""
        r1 = Part("Device:R", ref="R1")
        r1.pin("1")
        r1.pin("2")

        renderer = SymbolRenderer()
        endpoints = renderer.pin_endpoints(r1, 100.0, 200.0, symbol_name="R")

        assert endpoints[("R1", "1")] == pytest.approx((100.0, 222.86), rel=1e-6)
        assert endpoints[("R1", "2")] == pytest.approx((100.0, 177.14), rel=1e-6)

    def test_RO_06_q1_q2_b_labels_are_outside_component_boxes(self):
        """RO-06: Q1.B/Q2.B labels are not trapped inside component boxes."""
        sch, q1, q2 = _build_transistor_and_gate()
        style = RenderStyle.default()
        tmpl = RenderTemplate.from_style(style, page=PageConfig.a1(landscape=True))
        svg = sch.get_svg_string(template=tmpl)

        nodes = _parse_text_nodes(svg)
        b_nodes = [node for node in nodes if node[0] == "B"]
        assert b_nodes, "Expected at least one 'B' text node"

        renderer = SymbolRenderer()
        q1_center = (_MARGIN + 65.0 * 3.0, _MARGIN + 50.0 * 3.0)
        q2_center = (_MARGIN + 155.0 * 3.0, _MARGIN + 50.0 * 3.0)

        q1_box = renderer.component_bbox(
            q1,
            q1_center[0],
            q1_center[1],
            symbol_name="Q_PNP_CBE",
            rotation=90,
        )
        q2_box = renderer.component_bbox(
            q2,
            q2_center[0],
            q2_center[1],
            symbol_name="Q_PNP_CBE",
        )
        assert q1_box is not None
        assert q2_box is not None

        def _nearest_b(center: tuple[float, float]) -> tuple[str, float, float, float, str]:
            return min(
                b_nodes,
                key=lambda node: (node[1] - center[0]) ** 2 + (node[2] - center[1]) ** 2,
            )

        q1_b_text = _nearest_b(q1_center)
        q2_b_text = _nearest_b(q2_center)

        q1_label_box = _text_box(*q1_b_text)
        q2_label_box = _text_box(*q2_b_text)

        assert not _boxes_overlap(q1_label_box, q1_box)
        assert not _boxes_overlap(q2_label_box, q2_box)

    def test_RO_07_q1_b_branch_avoids_local_backtrack_and_keeps_continuity(self):
        """RO-07: Exact Q1.B branch geometry avoids local loop-like backtrack."""
        sch, r1, r2, q1 = _build_q1_b_branch_geometry()
        style = RenderStyle.default()
        tmpl = RenderTemplate.from_style(style, page=PageConfig.a1(landscape=True))
        svg = sch.get_svg_string(template=tmpl)
        lines = _parse_blue_wire_lines(svg)
        assert lines, "Expected at least one blue wire segment"

        renderer = SymbolRenderer()
        q1_cx = _MARGIN + 65.0 * 3.0
        q1_cy = _MARGIN + 50.0 * 3.0
        q1_b = renderer.pin_endpoints(q1, q1_cx, q1_cy, symbol_name="Q_PNP_CBE")[("Q1", "2")]

        r1_cx = _MARGIN + 20.0 * 3.0
        r1_cy = _MARGIN + 25.0 * 3.0
        r2_cx = _MARGIN + 20.0 * 3.0
        r2_cy = _MARGIN + 75.0 * 3.0
        r1_p1 = renderer.pin_endpoints(r1, r1_cx, r1_cy, symbol_name="R")[("R1", "1")]
        r2_p2 = renderer.pin_endpoints(r2, r2_cx, r2_cy, symbol_name="R")[("R2", "2")]

        def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
            return abs(a[0] - b[0]) <= 0.2 and abs(a[1] - b[1]) <= 0.2

        touching_q1_b: list[tuple[float, float]] = []
        for x1, y1, x2, y2 in lines:
            if _same_point((x1, y1), q1_b):
                touching_q1_b.append((x2, y2))
            elif _same_point((x2, y2), q1_b):
                touching_q1_b.append((x1, y1))

        assert touching_q1_b, f"No wire endpoint found at Q1.B endpoint {q1_b}"
        assert len(touching_q1_b) == 1, (
            "Q1.B should connect with a single local branch segment, "
            f"got {len(touching_q1_b)} touching segments"
        )
        q1_neighbor = touching_q1_b[0]
        assert abs(q1_neighbor[1] - q1_b[1]) <= 0.2, (
            "Q1.B local branch should not backtrack vertically near the pin"
        )
        assert q1_neighbor[0] < q1_b[0] - 0.2, "Expected Q1.B branch to merge from the left side"

        def _point_on_segment(point: tuple[float, float], seg: tuple[float, float, float, float]) -> bool:
            px, py = point
            x1, y1, x2, y2 = seg
            if abs(y1 - y2) <= 0.2:  # horizontal
                if abs(py - y1) > 0.2:
                    return False
                lo, hi = min(x1, x2), max(x1, x2)
                return lo - 0.2 <= px <= hi + 0.2
            if abs(x1 - x2) <= 0.2:  # vertical
                if abs(px - x1) > 0.2:
                    return False
                lo, hi = min(y1, y2), max(y1, y2)
                return lo - 0.2 <= py <= hi + 0.2
            return False

        split_points: set[tuple[float, float]] = set()
        for x1, y1, x2, y2 in lines:
            split_points.add((round(x1, 2), round(y1, 2)))
            split_points.add((round(x2, 2), round(y2, 2)))

        for h in lines:
            hx1, hy1, hx2, hy2 = h
            if abs(hy1 - hy2) > 0.2:
                continue
            h_lo, h_hi = min(hx1, hx2), max(hx1, hx2)
            for v in lines:
                vx1, vy1, vx2, vy2 = v
                if abs(vx1 - vx2) > 0.2:
                    continue
                v_lo, v_hi = min(vy1, vy2), max(vy1, vy2)
                ix, iy = vx1, hy1
                if h_lo - 0.2 <= ix <= h_hi + 0.2 and v_lo - 0.2 <= iy <= v_hi + 0.2:
                    split_points.add((round(ix, 2), round(iy, 2)))

        graph: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
        for seg in lines:
            pts_on_seg = [point for point in split_points if _point_on_segment(point, seg)]
            x1, y1, x2, y2 = seg
            if abs(y1 - y2) <= 0.2:
                pts_on_seg.sort(key=lambda point: point[0])
            else:
                pts_on_seg.sort(key=lambda point: point[1])
            for idx in range(len(pts_on_seg) - 1):
                a = pts_on_seg[idx]
                b = pts_on_seg[idx + 1]
                graph[a].add(b)
                graph[b].add(a)

        def _find_node(endpoint: tuple[float, float]) -> tuple[float, float]:
            for node in graph:
                if _same_point(node, endpoint):
                    return node
            raise AssertionError(f"No wire node found for endpoint {endpoint}")

        nodes = [_find_node(r1_p1), _find_node(r2_p2), _find_node(q1_b)]
        seen: set[tuple[float, float]] = set()
        q = deque([nodes[0]])
        while q:
            node = q.popleft()
            if node in seen:
                continue
            seen.add(node)
            q.extend(graph[node] - seen)

        assert nodes[1] in seen and nodes[2] in seen, (
            "Expected continuous electrical path across R1(1), R2(2), and Q1(B)"
        )

    def test_RO_08_explicit_junction_is_wire_landing_target(self):
        """RO-08: Explicit Junction stays the routed merge point for all branches."""
        sch, r1, r2, q1, junction = _build_explicit_junction_bias_geometry()
        style = RenderStyle.default().merge(RenderStyle(wire=WireStyle(color="#1565c0")))
        tmpl = RenderTemplate.from_style(style, page=PageConfig.a1(landscape=True))
        svg = sch.get_svg_string(template=tmpl)
        lines = _parse_blue_wire_lines(svg)
        assert lines, "Expected at least one blue wire segment"

        renderer = SymbolRenderer()
        q1_cx = _MARGIN + 65.0 * 3.0
        q1_cy = _MARGIN + 50.0 * 3.0
        r1_cx = _MARGIN + 20.0 * 3.0
        r1_cy = _MARGIN + 25.0 * 3.0
        r2_cx = _MARGIN + 20.0 * 3.0
        r2_cy = _MARGIN + 75.0 * 3.0
        junction_pt = (_MARGIN + 20.0 * 3.0, _MARGIN + 50.0 * 3.0)

        r1_p1 = renderer.pin_endpoints(r1, r1_cx, r1_cy, symbol_name="R")[("R1", "1")]
        r2_p2 = renderer.pin_endpoints(r2, r2_cx, r2_cy, symbol_name="R")[("R2", "2")]
        q1_b = renderer.pin_endpoints(q1, q1_cx, q1_cy, symbol_name="Q_PNP_CBE")[("Q1", "2")]

        def _point_on_segment(point: tuple[float, float], seg: tuple[float, float, float, float]) -> bool:
            px, py = point
            x1, y1, x2, y2 = seg
            if abs(y1 - y2) <= 0.2:
                if abs(py - y1) > 0.2:
                    return False
                lo, hi = min(x1, x2), max(x1, x2)
                return lo - 0.2 <= px <= hi + 0.2
            if abs(x1 - x2) <= 0.2:
                if abs(px - x1) > 0.2:
                    return False
                lo, hi = min(y1, y2), max(y1, y2)
                return lo - 0.2 <= py <= hi + 0.2
            return False

        def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
            return abs(a[0] - b[0]) <= 0.2 and abs(a[1] - b[1]) <= 0.2

        junction_touch_count = sum(
            1
            for x1, y1, x2, y2 in lines
            if _same_point((x1, y1), junction_pt) or _same_point((x2, y2), junction_pt)
        )
        assert junction_touch_count >= 3, (
            f"Expected at least three branch segments landing on explicit junction {junction_pt}"
        )

        split_points: set[tuple[float, float]] = set()
        for x1, y1, x2, y2 in lines:
            split_points.add((round(x1, 2), round(y1, 2)))
            split_points.add((round(x2, 2), round(y2, 2)))

        for h in lines:
            hx1, hy1, hx2, hy2 = h
            if abs(hy1 - hy2) > 0.2:
                continue
            h_lo, h_hi = min(hx1, hx2), max(hx1, hx2)
            for v in lines:
                vx1, vy1, vx2, vy2 = v
                if abs(vx1 - vx2) > 0.2:
                    continue
                v_lo, v_hi = min(vy1, vy2), max(vy1, vy2)
                ix, iy = vx1, hy1
                if h_lo - 0.2 <= ix <= h_hi + 0.2 and v_lo - 0.2 <= iy <= v_hi + 0.2:
                    split_points.add((round(ix, 2), round(iy, 2)))

        graph: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
        for seg in lines:
            pts_on_seg = [point for point in split_points if _point_on_segment(point, seg)]
            x1, y1, x2, y2 = seg
            if abs(y1 - y2) <= 0.2:
                pts_on_seg.sort(key=lambda point: point[0])
            else:
                pts_on_seg.sort(key=lambda point: point[1])
            for idx in range(len(pts_on_seg) - 1):
                a = pts_on_seg[idx]
                b = pts_on_seg[idx + 1]
                graph[a].add(b)
                graph[b].add(a)

        def _find_node(point: tuple[float, float]) -> tuple[float, float]:
            for node in graph:
                if _same_point(node, point):
                    return node
            raise AssertionError(f"No routed node found at {point}")

        junction_node = _find_node(junction_pt)
        branch_nodes = [_find_node(r1_p1), _find_node(r2_p2), _find_node(q1_b)]
        seen: set[tuple[float, float]] = set()
        queue = deque([junction_node])
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            queue.extend(graph[node] - seen)
        assert all(node in seen for node in branch_nodes), (
            "Expected R1(1), R2(2), and Q1(B) branches to reach explicit junction target"
        )

        assert f">{junction.ref}<" not in svg
