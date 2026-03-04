"""Regression tests for renderer scale/overlap/connectivity overhaul.

Test IDs
--------
RO-01  Symbol scale=6 expands pin endpoint geometry predictably
RO-02  canvas_scale=2 scales exported SVG width/height
RO-03  High-scale labels avoid Q2 ref/VCC overlap and duplicate net text
RO-04  Q2.B net has continuous wire connection at pin endpoint
"""

from __future__ import annotations

import re

import pytest

import lib.symbols.symbols as _sym_mod
from lib.core.page import PageConfig
from lib.core.part import NetLabel, Part
from lib.core.render_style import RenderStyle, RenderTemplate, SymbolStyle
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


def _build_transistor_and_gate() -> tuple[Schematic, Part]:
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
    return sch, q2


def _parse_text_nodes(svg: str) -> list[tuple[str, float, float, float, str]]:
    pattern = (
        r'<text x="([^"]+)" y="([^"]+)" font-size="([^"]+)"'
        r'[^>]*text-anchor="([^"]+)"[^>]*>([^<]+)</text>'
    )
    return [
        (text, float(x), float(y), float(font_size), anchor)
        for x, y, font_size, anchor, text in re.findall(pattern, svg)
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


class TestRendererOverhaulRegressions:
    def test_RO_01_symbol_scale_6_expands_pin_geometry(self):
        """RO-01: SymbolStyle(scale=6) scales endpoint distance from centre."""
        q2 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q2")
        q2.pin("B")
        q2.pin("C")
        q2.pin("E")

        renderer_1x = SymbolRenderer(symbol_scale=1.0)
        renderer_6x = SymbolRenderer(symbol_scale=6.0)
        endpoints_1x = renderer_1x.pin_endpoints(q2, 100.0, 200.0, symbol_name="Q_PNP_CBE")
        endpoints_6x = renderer_6x.pin_endpoints(q2, 100.0, 200.0, symbol_name="Q_PNP_CBE")

        q2_b_1x = endpoints_1x[("Q2", "2")]
        q2_b_6x = endpoints_6x[("Q2", "2")]
        dist_1x = abs(q2_b_1x[0] - 100.0)
        dist_6x = abs(q2_b_6x[0] - 100.0)
        assert dist_6x == pytest.approx(dist_1x * 6.0, rel=1e-6)

    def test_RO_02_canvas_scale_scales_output_dimensions(self):
        """RO-02: RenderStyle.canvas_scale multiplies final SVG width/height."""
        sch, _ = _build_transistor_and_gate()
        style = RenderStyle.default().merge(
            RenderStyle(symbol=SymbolStyle(scale=6.0), canvas_scale=2.0)
        )
        tmpl = RenderTemplate.from_style(style, page=PageConfig(width=1200, height=900))
        svg = sch.get_svg_string(template=tmpl)

        m = re.search(r'<svg[^>]*width="([^"]+)"[^>]*height="([^"]+)"', svg)
        assert m is not None
        width = float(m.group(1))
        height = float(m.group(2))
        assert width == 2400.0
        assert height == 1800.0

    def test_RO_03_high_scale_avoids_q2_vcc_overlap_and_duplicate_net_text(self):
        """RO-03: High-scale render avoids Q2/VCC overlap and duplicate A_AND_B labels."""
        sch, _ = _build_transistor_and_gate()
        style = RenderStyle.default().merge(
            RenderStyle(symbol=SymbolStyle(scale=6.0), canvas_scale=2.0)
        )
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

    def test_RO_04_q2_b_pin_has_continuous_wire_connection(self):
        """RO-04: At scale=6, a blue wire segment terminates at Q2.B endpoint and continues."""
        sch, q2 = _build_transistor_and_gate()
        style = RenderStyle.default().merge(
            RenderStyle(symbol=SymbolStyle(scale=6.0), canvas_scale=2.0)
        )
        tmpl = RenderTemplate.from_style(style, page=PageConfig.a1(landscape=True))
        svg = sch.get_svg_string(template=tmpl)

        renderer = SymbolRenderer(symbol_scale=6.0)
        q2_cx = _MARGIN + 155.0 * 3.0
        q2_cy = _MARGIN + 50.0 * 3.0
        q2_endpoints = renderer.pin_endpoints(q2, q2_cx, q2_cy, symbol_name="Q_PNP_CBE")
        q2_b = q2_endpoints[("Q2", "2")]

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

        segments_at_q2b = [
            seg for seg in lines
            if _same_point((seg[0], seg[1]), q2_b) or _same_point((seg[2], seg[3]), q2_b)
        ]
        assert segments_at_q2b, f"No wire endpoint found at Q2.B endpoint {q2_b}"

        continued = False
        for seg in segments_at_q2b:
            if _same_point((seg[0], seg[1]), q2_b):
                other = (seg[2], seg[3])
            else:
                other = (seg[0], seg[1])
            for other_seg in lines:
                if other_seg == seg:
                    continue
                if _same_point((other_seg[0], other_seg[1]), other) or _same_point((other_seg[2], other_seg[3]), other):
                    continued = True
                    break
            if continued:
                break

        assert continued, "Q2.B wire touches endpoint but does not continue into net routing"
