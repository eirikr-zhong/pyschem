"""Unit tests for SVG visualization of Q_PNP_CBE.

Test IDs
--------
SVG-GEN-01  export_svg() creates the file
SVG-GEN-02  render(fmt='svg') creates the file
SVG-GEN-03  get_svg_string() returns non-empty string
SVG-GEN-04  SVG string contains valid XML header

SVG-BODY-01  SVG contains Q_PNP_CBE body elements (circle)
SVG-BODY-02  SVG contains ref label text (Q1)
SVG-BODY-03  SVG contains pin name 'B'
SVG-BODY-04  SVG contains pin name 'C'
SVG-BODY-05  SVG contains pin name 'E'

SVG-NET-01   SVG contains net label text when pin connected to named net
SVG-NET-02   Multiple net labels rendered (BASE, VCC, GND all present)
SVG-NET-03   Anonymous-net pins produce NO net-label text in PNP symbol

SVG-DOT-REG  DOT export still works after SVG code added (regression guard)
"""

from __future__ import annotations

import re

import pytest

import lib.symbols.symbols as _sym_mod
from lib.core.connect import connect
from lib.core.part import NetLabel, Part
from lib.core.render_style import BoxStyle, RenderTemplate
from lib.core.schematic import Schematic
from lib.core.style import Style
from lib.symbols import configure_default_symbols


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _configure_example_symbols() -> None:
    original = _sym_mod._DEFAULT_SYMBOLS
    _sym_mod._DEFAULT_SYMBOLS = None
    configure_default_symbols(
        symbol_paths=["examples/kicad-symbols"],
        preload=False,
    )
    yield
    _sym_mod._DEFAULT_SYMBOLS = original


def _make_pnp_sch(net_b: str = "BASE", net_c: str = "VCC", net_e: str = "GND") -> Schematic:
    sch = Schematic("Q_PNP_CBE_demo")
    q1 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q1")
    sch.add_part(q1)

    b = NetLabel(net_b)
    c = NetLabel(net_c)
    e = NetLabel(net_e)
    for nl in [b, c, e]:
        sch.add_part(nl)

    connect(q1.pin("B"), b.label_pin)
    connect(q1.pin("C"), c.label_pin)
    connect(q1.pin("E"), e.label_pin)

    return sch


# ===========================================================================
# SVG-GEN — File generation
# ===========================================================================

class TestSvgGeneration:
    """SVG-GEN: basic file/string generation."""

    def test_export_svg_creates_file(self, tmp_path):
        """SVG-GEN-01: export_svg() writes a file."""
        sch = _make_pnp_sch()
        out = tmp_path / "q1.svg"
        sch.export_svg(str(out))
        assert out.exists(), "SVG file was not created"
        assert out.stat().st_size > 0

    def test_render_svg_creates_file(self, tmp_path):
        """SVG-GEN-02: render(fmt='svg') writes a file."""
        sch = _make_pnp_sch()
        out = tmp_path / "q1_render.svg"
        sch.render(str(out), fmt="svg")
        assert out.exists(), "SVG file from render() was not created"

    def test_get_svg_string_nonempty(self):
        """SVG-GEN-03: get_svg_string() returns non-empty string."""
        sch = _make_pnp_sch()
        svg = sch.get_svg_string()
        assert isinstance(svg, str)
        assert len(svg) > 50

    def test_svg_has_xml_header(self):
        """SVG-GEN-04: SVG string starts with XML declaration."""
        sch = _make_pnp_sch()
        svg = sch.get_svg_string()
        assert '<?xml' in svg
        assert '<svg' in svg

    def test_export_svg_debug_renders_overlay_geometry(self, tmp_path):
        """SVG-GEN-05: export_svg(debug=True) emits obstacle/trunk/pin overlays."""
        sch = Schematic("debug_overlay")
        r1 = Part("Device:R", ref="R1", value="10K")
        r2 = Part("Device:R", ref="R2", value="10K")
        q1 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q1")
        for part in (r1, r2, q1):
            sch.add_part(part)
        sch.place(r1, x=20, y=30)
        sch.place(r2, x=20, y=60)
        sch.place(q1, x=80, y=45)
        connect(r1.pin("1"), q1.pin("B"))
        connect(r2.pin("1"), q1.pin("B"))

        out = tmp_path / "debug_overlay.svg"
        sch.export_svg(str(out), debug=True)
        svg = out.read_text(encoding="utf-8")

        assert 'fill="rgba(255,0,0,0.2)"' in svg
        assert 'stroke-dasharray="2,2"' in svg
        assert re.search(r'<text [^>]*fill="red"[^>]*>R1</text>', svg)
        assert re.search(r'<text [^>]*fill="red"[^>]*>R2</text>', svg)
        assert re.search(r'<text [^>]*fill="red"[^>]*>Q1</text>', svg)
        assert 'stroke="green"' in svg
        assert 'stroke-dasharray="5,5"' in svg
        assert "trunk x=" in svg
        assert 'fill="blue"' in svg
        assert 'r="3"' in svg


# ===========================================================================
# SVG-BODY — Component body elements
# ===========================================================================

class TestSvgBody:
    """SVG-BODY: schematic symbol graphical elements."""

    def test_body_has_circle(self):
        """SVG-BODY-01: PNP body rendered as <circle>."""
        sch = _make_pnp_sch()
        svg = sch.get_svg_string()
        assert "<circle" in svg

    def test_ref_label_present(self):
        """SVG-BODY-02: part ref 'Q1' appears in SVG text."""
        sch = _make_pnp_sch()
        svg = sch.get_svg_string()
        assert "Q1" in svg

    def test_pin_name_b_present(self):
        """SVG-BODY-03: pin name 'B' appears in SVG."""
        sch = _make_pnp_sch()
        svg = sch.get_svg_string()
        assert ">B<" in svg

    def test_pin_name_c_present(self):
        """SVG-BODY-04: pin name 'C' appears in SVG."""
        sch = _make_pnp_sch()
        svg = sch.get_svg_string()
        assert ">C<" in svg

    def test_pin_name_e_present(self):
        """SVG-BODY-05: pin name 'E' appears in SVG."""
        sch = _make_pnp_sch()
        svg = sch.get_svg_string()
        assert ">E<" in svg

    def test_pnp_arrow_fill_uses_component_symbol_colour(self):
        """SVG-BODY-06: PNP filled arrow follows configured symbol stroke colour."""
        sch = _make_pnp_sch()
        template = RenderTemplate.from_style(Style(box=BoxStyle(stroke="#cc0000")))
        svg = sch.get_svg_string(template=template)
        assert '<polygon' in svg
        assert 'fill="#cc0000"' in svg


# ===========================================================================
# SVG-NET — Net labels
# ===========================================================================

class TestSvgNetLabels:
    """SVG-NET: net label rendering."""

    def test_single_net_label_present(self):
        """SVG-NET-01: net label text appears when pin connected to named net."""
        sch = Schematic("pn_test")
        q1 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q1")
        sch.add_part(q1)
        base = NetLabel("BASE")
        sch.add_part(base)
        connect(q1.pin("B"), base.label_pin)

        svg = sch.get_svg_string()
        assert "BASE" in svg

    def test_all_three_net_labels_present(self):
        """SVG-NET-02: all three net labels (BASE, VCC, GND) appear in SVG."""
        sch = _make_pnp_sch()
        svg = sch.get_svg_string()
        assert "BASE" in svg
        assert "VCC" in svg
        assert "GND" in svg

    def test_no_net_label_for_unconnected_pin(self):
        """SVG-NET-03: unconnected PNP pin produces no net label text for it."""
        sch = Schematic("bare_pnp")
        q1 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q1")
        sch.add_part(q1)
        # Connect only B; leave C and E unconnected
        base = NetLabel("BASE")
        sch.add_part(base)
        connect(q1.pin("B"), base.label_pin)

        svg = sch.get_svg_string()
        # VCC and GND should not appear — they were not connected
        assert "VCC" not in svg
        assert "GND" not in svg
        # BASE should appear
        assert "BASE" in svg


# ===========================================================================
# SVG-DOT-REG — Regression guard: DOT still works
# ===========================================================================

class TestDotRegression:
    """SVG-DOT-REG: ensure DOT export still functions after SVG additions."""

    def test_dot_export_still_works(self, tmp_path):
        """SVG-DOT-REG-01: export_dot() produces valid DOT after SVG code added."""
        sch = _make_pnp_sch()
        out = tmp_path / "q1.dot"
        sch.export_dot(str(out))
        assert out.exists()
        dot = out.read_text()
        assert 'graph "Q_PNP_CBE_demo"' in dot

    def test_get_dot_string_unaffected(self):
        """SVG-DOT-REG-02: get_dot_string() still returns DOT syntax."""
        sch = _make_pnp_sch()
        dot = sch.get_dot_string()
        assert dot.startswith('graph')
        assert "Q1" in dot

    def test_render_unsupported_fmt_raises(self):
        """SVG-DOT-REG-03: render() with unknown format raises NotImplementedError."""
        sch = Schematic("x")
        with pytest.raises(NotImplementedError):
            sch.render("/tmp/dummy.xyz", fmt="xyz")
