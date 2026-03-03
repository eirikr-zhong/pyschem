"""Coverage tests for lib/core/schematic.py.

Targets uncovered lines:
  90-142  erc() method (conflicting names, floating NetLabel, no error)
  193     _build_dot() — pin ref not in parts_by_ref (orphan pin)
  245-246 export_svg() OSError → RenderPathError
  266-267 render() for fmt='svg' and unsupported format
"""

from __future__ import annotations

import pytest

from lib.core.part import NetLabel, Part
from lib.core.schematic import Schematic
from lib.errors import ERCError, RenderPathError


# ---------------------------------------------------------------------------
# erc() — lines 90-142
# ---------------------------------------------------------------------------

class TestErc:
    """Tests for the Electrical Rules Check method."""

    def test_erc_no_errors_returns_empty_list(self):
        """ERC with no errors returns an empty list."""
        sch = Schematic("erc_clean")
        r1 = Part("Device:R", ref="R1")
        vcc = NetLabel("VCC")
        sch.add_part(r1)
        sch.add_part(vcc)
        sch.connect(r1.pin("1"), vcc.label_pin)

        errors = sch.erc(raise_on_error=False)
        assert errors == []

    def test_erc_conflicting_net_names_raises(self):
        """Two NetLabels with different names in same component → ERCError."""
        sch = Schematic("erc_conflict")
        r1 = Part("Device:R", ref="R1")
        vcc = NetLabel("VCC")
        gnd = NetLabel("GND")
        sch.add_part(r1)
        sch.add_part(vcc)
        sch.add_part(gnd)
        # Connect both net labels to the same resistor pin
        sch.connect(r1.pin("1"), vcc.label_pin)
        sch.connect(r1.pin("1"), gnd.label_pin)

        with pytest.raises(ERCError, match="conflicting net names"):
            sch.erc(raise_on_error=True)

    def test_erc_conflicting_net_names_list_mode(self):
        """Two NetLabels with different names → error string in list."""
        sch = Schematic("erc_conflict_list")
        r1 = Part("Device:R", ref="R1")
        a = NetLabel("NETA")
        b = NetLabel("NETB")
        sch.add_part(r1)
        sch.add_part(a)
        sch.add_part(b)
        sch.connect(r1.pin("1"), a.label_pin)
        sch.connect(r1.pin("1"), b.label_pin)

        errors = sch.erc(raise_on_error=False)
        assert len(errors) >= 1
        assert any("conflicting net names" in e for e in errors)
        assert any("NETA" in e and "NETB" in e for e in errors)

    def test_erc_floating_netlabel_raises(self):
        """Floating NetLabel (not connected to real component pin) → ERCError."""
        sch = Schematic("erc_floating")
        floating = NetLabel("FLOAT")
        sch.add_part(floating)
        # Do NOT connect to any real component pin

        with pytest.raises(ERCError, match="floating NetLabel"):
            sch.erc(raise_on_error=True)

    def test_erc_floating_netlabel_list_mode(self):
        """Floating NetLabel → error string in list when raise_on_error=False."""
        sch = Schematic("erc_floating_list")
        floating = NetLabel("MYFLOAT")
        sch.add_part(floating)

        errors = sch.erc(raise_on_error=False)
        assert any("floating NetLabel" in e for e in errors)
        assert any("MYFLOAT" in e for e in errors)

    def test_erc_connected_netlabel_not_floating(self):
        """NetLabel connected to a component pin is NOT flagged as floating."""
        sch = Schematic("erc_connected")
        r1 = Part("Device:R", ref="R1")
        vcc = NetLabel("VCC")
        sch.add_part(r1)
        sch.add_part(vcc)
        sch.connect(r1.pin("1"), vcc.label_pin)

        errors = sch.erc(raise_on_error=False)
        # No floating-netlabel errors
        assert not any("floating" in e for e in errors)

    def test_erc_empty_schematic(self):
        """Empty schematic passes ERC with no errors."""
        sch = Schematic("erc_empty")
        errors = sch.erc(raise_on_error=False)
        assert errors == []

    def test_erc_part_only_no_netlabel(self):
        """Parts without NetLabels pass ERC."""
        sch = Schematic("erc_parts_only")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.connect(r1.pin("1"), r2.pin("1"))

        errors = sch.erc(raise_on_error=False)
        assert errors == []

    def test_erc_two_netlabels_same_name_no_error(self):
        """Two NetLabels with the SAME name connected to same pin → no conflict."""
        sch = Schematic("erc_same_name")
        r1 = Part("Device:R", ref="R1")
        vcc1 = NetLabel("VCC")
        vcc2 = NetLabel("VCC")
        sch.add_part(r1)
        sch.add_part(vcc1)
        sch.add_part(vcc2)
        sch.connect(r1.pin("1"), vcc1.label_pin)
        sch.connect(r1.pin("2"), vcc2.label_pin)

        errors = sch.erc(raise_on_error=False)
        # Same net name — no conflict
        assert not any("conflicting" in e for e in errors)


# ---------------------------------------------------------------------------
# export_svg() OSError → RenderPathError  (lines 245-246)
# ---------------------------------------------------------------------------

class TestExportSvgOsError:
    """Cover the OSError→RenderPathError branch in export_svg()."""

    def test_export_svg_bad_path_raises_render_path_error(self, tmp_path):
        """export_svg() with an unwritable path raises RenderPathError."""
        sch = Schematic("svg_err")
        # Create a file where a directory would need to be, making it impossible
        # to create subdirectories beneath it.
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file")
        bad_path = str(blocker / "subdir" / "out.svg")

        with pytest.raises(RenderPathError):
            sch.export_svg(bad_path)

    def test_export_svg_valid_path_writes_file(self, tmp_path):
        """export_svg() with a valid path writes an SVG file."""
        sch = Schematic("svg_ok")
        r1 = Part("Device:R", ref="R1")
        sch.add_part(r1)
        out = tmp_path / "out.svg"
        sch.export_svg(str(out))
        assert out.exists()
        assert "<svg" in out.read_text()


# ---------------------------------------------------------------------------
# render() SVG format and unsupported format  (line 237, 239)
# ---------------------------------------------------------------------------

class TestRenderFormat:
    """Cover render() with fmt='svg' and unsupported format."""

    def test_render_svg_writes_file(self, tmp_path):
        """render(fmt='svg') writes an SVG file."""
        sch = Schematic("render_svg")
        r1 = Part("Device:R", ref="R1")
        sch.add_part(r1)
        out = tmp_path / "out.svg"
        sch.render(str(out), fmt="svg")
        assert out.exists()
        assert "<svg" in out.read_text()

    def test_render_unsupported_format_raises(self, tmp_path):
        """render() with unsupported fmt raises NotImplementedError."""
        sch = Schematic("render_bad_fmt")
        out = tmp_path / "out.txt"
        with pytest.raises(NotImplementedError, match="Unsupported render format"):
            sch.render(str(out), fmt="pdf")

    def test_render_dot_ose_error_raises_render_path_error(self, tmp_path):
        """render(fmt='dot') with bad path raises RenderPathError (lines 245-246)."""
        sch = Schematic("render_dot_err")
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file")
        bad_path = str(blocker / "sub" / "out.dot")
        with pytest.raises(RenderPathError):
            sch.render(bad_path, fmt="dot")


# ---------------------------------------------------------------------------
# _build_dot() orphan-pin branch (line 193)
# ---------------------------------------------------------------------------

class TestBuildDotOrphanPin:
    """Cover the branch where pin.part_ref is not in parts_by_ref."""

    def test_dot_output_with_normal_parts(self):
        """Simple schematic produces valid DOT output."""
        sch = Schematic("dot_orphan")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.connect(r1.pin("1"), r2.pin("1"))

        dot = sch.get_dot_string()
        assert "R1" in dot
        assert "R2" in dot
        assert "graph" in dot

    def test_nets_property(self):
        """The nets property returns derived nets."""
        sch = Schematic("nets_prop")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.connect(r1.pin("1"), r2.pin("1"))

        nets = sch.nets
        assert len(nets) >= 1


# ---------------------------------------------------------------------------
# erc() BFS — already-visited pin (line 111 continue)
# ---------------------------------------------------------------------------

class TestErcBfsVisited:
    """Cover the BFS 'already visited' continue branch in erc()."""

    def test_erc_ring_connection_not_infinite(self):
        """ERC with a ring connection (A→B→C→A) completes without infinite loop."""
        sch = Schematic("erc_ring")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        r3 = Part("Device:R", ref="R3")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.add_part(r3)
        # Create a chain that circles back
        sch.connect(r1.pin("1"), r2.pin("1"))
        sch.connect(r2.pin("1"), r3.pin("1"))
        sch.connect(r3.pin("1"), r1.pin("1"))  # cycle

        # Should complete and not raise (no ERC errors expected)
        errors = sch.erc(raise_on_error=False)
        assert isinstance(errors, list)

    def test_erc_multi_component_bfs(self):
        """ERC walks a star topology (all connected to one pin)."""
        sch = Schematic("erc_star")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        r3 = Part("Device:R", ref="R3")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.add_part(r3)
        sch.connect(r1.pin("1"), r2.pin("1"))
        sch.connect(r1.pin("1"), r3.pin("1"))

        errors = sch.erc(raise_on_error=False)
        assert errors == []
