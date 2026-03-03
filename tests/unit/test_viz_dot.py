"""Unit tests for DOT visualization rules (lib/core/schematic._build_dot).

Test IDs
--------
VIZ-PP-01  Pin-pin: anonymous net rendered in DOT output
VIZ-PP-02  Pin-pin: anon net node uses dashed style
VIZ-PP-03  Pin-pin: both part nodes appear in DOT
VIZ-PP-04  Pin-pin: edge label contains pin key (not net name)

VIZ-PN-01  Pin-net: named net node present
VIZ-PN-02  Pin-net: named net node NOT dashed
VIZ-PN-03  Pin-net: edge label contains pin key AND net name (e.g. "1 [VCC]")
VIZ-PN-04  Pin-net: part node present

VIZ-STR-01 get_dot_string() returns same content as written file
VIZ-STR-02 get_dot_string() includes graph header with schematic name
"""

from __future__ import annotations

import pytest

from lib.core.connect import connect
from lib.core.part import NetLabel, Part
from lib.core.schematic import Schematic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sch(name: str = "sch") -> Schematic:
    return Schematic(name)


def _add(sch: Schematic, *refs: str) -> list[Part]:
    parts = [Part("Device:R", ref=ref) for ref in refs]
    for p in parts:
        sch.add_part(p)
    return parts


# ===========================================================================
# VIZ-PP — Pin ↔ Pin (anonymous net)
# ===========================================================================

class TestPinPinVisualization:
    """VIZ-PP: pin-pin connections rendered as dashed anonymous net."""

    def test_pp_anon_net_present_in_dot(self):
        """VIZ-PP-01: anonymous net identifier appears in DOT."""
        sch = _make_sch("pp_test")
        r1, r2 = _add(sch, "R1", "R2")
        sch.connect(r1.pin(1), r2.pin(2))
        dot = sch.get_dot_string()
        # The _anon net should appear as "net:_anonN"
        assert "net:_anon" in dot

    def test_pp_anon_net_node_is_dashed(self):
        """VIZ-PP-02: anonymous net node carries style=dashed."""
        sch = _make_sch("pp_dashed")
        r1, r2 = _add(sch, "R1", "R2")
        sch.connect(r1.pin(1), r2.pin(2))
        dot = sch.get_dot_string()
        assert "style=dashed" in dot

    def test_pp_both_parts_in_dot(self):
        """VIZ-PP-03: both part nodes appear in DOT."""
        sch = _make_sch("pp_parts")
        r1, r2 = _add(sch, "R1", "R2")
        sch.connect(r1.pin(1), r2.pin(2))
        dot = sch.get_dot_string()
        assert '"R1"' in dot
        assert '"R2"' in dot

    def test_pp_edge_label_is_pin_key_only(self):
        """VIZ-PP-04: edge label for anon net is pin key only (no net name)."""
        sch = _make_sch("pp_edge")
        r1, r2 = _add(sch, "R1", "R2")
        sch.connect(r1.pin("1"), r2.pin("2"))
        dot = sch.get_dot_string()
        # The edge label should be just the pin key, e.g. label="1"
        assert 'label="1"' in dot
        assert 'label="2"' in dot
        # And it should NOT contain brackets (which are for named nets)
        # Find edges involving the anon net and ensure no brackets
        lines_with_anon = [ln for ln in dot.splitlines() if "_anon" in ln and "--" in ln]
        for ln in lines_with_anon:
            assert "[" not in ln.split('label=')[1] if 'label=' in ln else True


# ===========================================================================
# VIZ-PN — Pin ↔ Net (named net)
# ===========================================================================

class TestPinNetVisualization:
    """VIZ-PN: pin-net connections show net label on the edge."""

    def test_pn_named_net_node_present(self):
        """VIZ-PN-01: named net node appears in DOT."""
        sch = _make_sch("pn_test")
        r1, = _add(sch, "R1")
        vcc = NetLabel("VCC")
        sch.add_part(vcc)
        sch.connect(r1.pin(1), vcc.label_pin)
        dot = sch.get_dot_string()
        assert '"net:VCC"' in dot

    def test_pn_named_net_node_not_dashed(self):
        """VIZ-PN-02: named net node does NOT have style=dashed."""
        sch = _make_sch("pn_no_dash")
        r1, = _add(sch, "R1")
        vcc = NetLabel("VCC")
        sch.add_part(vcc)
        sch.connect(r1.pin(1), vcc.label_pin)
        dot = sch.get_dot_string()
        # Find the line declaring the VCC node
        node_lines = [ln for ln in dot.splitlines() if '"net:VCC"' in ln and "shape=ellipse" in ln]
        assert node_lines, "VCC node declaration not found"
        for ln in node_lines:
            assert "dashed" not in ln

    def test_pn_edge_label_contains_pin_and_net_name(self):
        """VIZ-PN-03: edge label is "pin_key [net_name]" format."""
        sch = _make_sch("pn_edge")
        r1, = _add(sch, "R1")
        vcc = NetLabel("VCC")
        sch.add_part(vcc)
        sch.connect(r1.pin("1"), vcc.label_pin)
        dot = sch.get_dot_string()
        # Edge label should look like: label="1 [VCC]"
        assert 'label="1 [VCC]"' in dot

    def test_pn_part_node_present(self):
        """VIZ-PN-04: the part node appears in DOT output."""
        sch = _make_sch("pn_part")
        r1, = _add(sch, "R1")
        gnd = NetLabel("GND")
        sch.add_part(gnd)
        sch.connect(r1.pin(2), gnd.label_pin)
        dot = sch.get_dot_string()
        assert '"R1"' in dot


# ===========================================================================
# VIZ-STR — get_dot_string()
# ===========================================================================

class TestGetDotString:
    """VIZ-STR: get_dot_string() consistency checks."""

    def test_dot_string_matches_file(self, tmp_path):
        """VIZ-STR-01: get_dot_string() content matches what is written to disk."""
        sch = _make_sch("match_test")
        r1, = _add(sch, "R1")
        vcc = NetLabel("VCC")
        sch.add_part(vcc)
        connect(r1.pin(1), vcc.label_pin)

        dot_str = sch.get_dot_string()
        out = tmp_path / "match.dot"
        sch.export_dot(str(out))
        assert out.read_text() == dot_str

    def test_dot_string_has_graph_header(self):
        """VIZ-STR-02: DOT string begins with graph declaration containing schematic name."""
        sch = _make_sch("header_check")
        dot = sch.get_dot_string()
        assert 'graph "header_check"' in dot
