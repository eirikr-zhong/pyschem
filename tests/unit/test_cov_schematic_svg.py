"""Coverage tests for lib/render/schematic_svg.py.

Targets uncovered lines:
- L66-67: _part_position with explicit Style(x, y) → scaled SVG coords
- L83: _render_generic_box dispatch (non-PNP symbol)
- L95: pin with net_label=None (continue branch in _render_pnp_cbe)
- L125-163: _render_generic_box body (box outline, labels, pin stubs, net labels)
"""

from __future__ import annotations

import pytest

from lib.core.part import NetLabel
from lib.core.part import Part
from lib.core.schematic import Schematic
from lib.core.style import Style
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


# ===========================================================================
# Generic box rendering (L83, L125-163)
# ===========================================================================

class TestGenericBoxRendering:
    """Cover _render_generic_box for non-PNP parts."""

    def test_generic_box_rendered_for_resistor(self):
        """Non-PNP parts dispatch to _render_generic_box (L83)."""
        sch = Schematic("generic_test")
        r1 = Part("Device:R", ref="R1", value="10k")
        r1.pin("1")
        r1.pin("2")
        sch.add_part(r1)

        svg = sch.get_svg_string()
        # Box outline uses <polyline>
        assert "<polyline" in svg
        # Ref label should appear
        assert "R1" in svg
        # Value label should appear
        assert "10k" in svg

    def test_generic_box_ref_only_no_value(self):
        """Generic box with ref but no value (L138: value else branch)."""
        sch = Schematic("no_value")
        r1 = Part("Device:R", ref="R1")
        r1.pin("1")
        sch.add_part(r1)

        svg = sch.get_svg_string()
        assert "R1" in svg

    def test_generic_box_pin_stubs_drawn(self):
        """Pin stubs are drawn as <line> elements (L158)."""
        sch = Schematic("pin_stubs")
        r1 = Part("Device:R", ref="R1", value="1k")
        r1.pin("1")
        r1.pin("2")
        sch.add_part(r1)

        svg = sch.get_svg_string()
        # Pin stubs use <line>, pin keys appear as text
        assert "<line" in svg

    def test_generic_box_pin_labels(self):
        """Pin key text labels are rendered (L159-160)."""
        sch = Schematic("pin_labels")
        c1 = Part("Device:C", ref="C1", value="100n")
        c1.pin("1")
        c1.pin("2")
        sch.add_part(c1)

        svg = sch.get_svg_string()
        # Pin key "1" appears in text (may be in different contexts)
        assert ">1<" in svg
        assert ">2<" in svg

    def test_generic_box_with_net_labels(self):
        """Net labels on generic box pins are rendered (L162-164)."""
        sch = Schematic("gen_net_labels")
        r1 = Part("Device:R", ref="R1", value="10k")
        sch.add_part(r1)

        vcc = NetLabel("VCC")
        gnd = NetLabel("GND")
        sch.add_part(vcc)
        sch.add_part(gnd)

        sch.connect(r1.pin("1"), vcc.pin("1"))
        sch.connect(r1.pin("2"), gnd.pin("1"))

        svg = sch.get_svg_string()
        assert "VCC" in svg
        assert "GND" in svg

    def test_generic_box_odd_and_even_pins(self):
        """Pin placement: even indices on left, odd indices on right (L148-157)."""
        sch = Schematic("multi_pin")
        u1 = Part("Device:U", ref="U1", value="IC")
        for i in range(1, 5):
            u1.pin(str(i))
        sch.add_part(u1)

        svg = sch.get_svg_string()
        # All four pin keys should appear
        for i in range(1, 5):
            assert f">{i}<" in svg

    def test_generic_box_no_value(self):
        """Part with no value shows only ref (L140: value is falsy, skip)."""
        sch = Schematic("no_value2")
        p = Part("Device:R", ref="X1")
        p.pin("1")
        sch.add_part(p)

        svg = sch.get_svg_string()
        assert "X1" in svg


# ===========================================================================
# Style-based positioning (L64-67)
# ===========================================================================

class TestStylePositioning:
    """Cover _part_position with explicit Style(x, y)."""

    def test_styled_part_uses_explicit_position(self):
        """Part with Style(x, y) uses scaled coordinates (L66-67)."""
        sch = Schematic("styled")
        r1 = Part("Device:R", ref="R1", value="10k")
        r1.pin("1")
        r1.pin("2")
        r1.set_style(Style(x=50.0, y=40.0, locked=True))
        sch.add_part(r1)

        svg = sch.get_svg_string()
        assert "R1" in svg
        assert "<polyline" in svg

    def test_multiple_styled_parts(self):
        """Multiple parts with explicit positions render correctly."""
        sch = Schematic("multi_styled")
        r1 = Part("Device:R", ref="R1", value="10k")
        r1.set_style(Style(x=20.0, y=30.0, locked=True))
        r1.pin("1")
        r1.pin("2")
        r2 = Part("Device:R", ref="R2", value="5k")
        r2.set_style(Style(x=60.0, y=30.0, locked=True))
        r2.pin("1")
        r2.pin("2")
        sch.add_part(r1)
        sch.add_part(r2)

        svg = sch.get_svg_string()
        assert "R1" in svg
        assert "R2" in svg


# ===========================================================================
# PNP pin with net_label=None (L94-95)
# ===========================================================================

class TestPnpNetLabelNoneBranch:
    """Cover the `continue` branch in _render_pnp_cbe when net_label is None."""

    def test_pnp_pin_without_net_label(self):
        """Pins without net_label hit the `continue` at L95."""
        sch = Schematic("pnp_partial")
        q1 = Part("Device:Q_PNP_CBE", ref="Q1")
        q1.attach_symbol(_pnp_symbol_data())
        sch.add_part(q1)

        # Access pins but DON'T connect them to any net
        q1.pin("1")
        q1.pin("2")
        q1.pin("3")

        svg = sch.get_svg_string()
        # Body should still be rendered
        assert "<circle" in svg
        assert "Q1" in svg


# ===========================================================================
# Width/height auto-compute (L41-44)
# ===========================================================================

class TestCanvasSizeAutoCompute:
    """Cover width/height auto-computation paths."""

    def test_explicit_width_height(self):
        """Passing explicit width/height skips auto-compute (L41-44)."""
        sch = Schematic("explicit_size")
        r1 = Part("Device:R", ref="R1")
        sch.add_part(r1)

        svg = sch.get_svg_string(width=800, height=600)
        assert 'width="800"' in svg
        assert 'height="600"' in svg

    def test_empty_schematic_auto_size(self):
        """Empty schematic (n=0 parts) still computes valid canvas size."""
        sch = Schematic("empty")
        svg = sch.get_svg_string()
        assert "<svg" in svg


# ===========================================================================
# lib_id edge cases (L77-78)
# ===========================================================================

class TestLibIdParsing:
    """Cover lib_id parsing for symbol name extraction."""

    def test_part_without_lib_id(self):
        """Part with empty lib_id uses generic box."""
        sch = Schematic("no_libid")
        p = Part("")
        p.pin("1")
        sch.add_part(p)

        svg = sch.get_svg_string()
        # Should use generic box (polyline)
        assert "<polyline" in svg

    def test_part_with_plain_symbol_name(self):
        """Part with lib_id without colon (plain name)."""
        sch = Schematic("plain_name")
        p = Part("R", ref="R99")
        p.pin("1")
        sch.add_part(p)

        svg = sch.get_svg_string()
        assert "R99" in svg
