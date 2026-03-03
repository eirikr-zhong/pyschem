"""Coverage tests for lib/render/svg_renderer.py.

Targets uncovered lines:
- L70-71: polygon() method
- L131-132: group_start() with transform
- L136: group_end()
Also covers edge cases: stroke_dasharray on line, background="none", XML escaping.
"""

from __future__ import annotations

from lib.render.svg_renderer import SvgCanvas


class TestPolygon:
    """Cover the polygon() method (L76-89, specifically L85-89 output)."""

    def test_polygon_basic(self):
        """polygon() emits a <polygon> element with points."""
        c = SvgCanvas(width=100, height=100)
        c.polygon([(0, 0), (50, 0), (25, 50)], stroke="red", fill="blue")
        svg = c.to_svg()
        assert "<polygon" in svg
        assert "0,0 50,0 25,50" in svg
        assert 'fill="blue"' in svg
        assert 'stroke="red"' in svg

    def test_polygon_default_fill_black(self):
        """polygon() defaults to fill='black'."""
        c = SvgCanvas(width=100, height=100)
        c.polygon([(10, 10), (20, 10), (15, 20)])
        svg = c.to_svg()
        assert 'fill="black"' in svg


class TestGroupStartEnd:
    """Cover group_start() and group_end() (L129-136)."""

    def test_group_with_transform(self):
        """group_start(transform=...) emits <g transform=\"...\"> (L131-132)."""
        c = SvgCanvas(width=100, height=100)
        c.group_start(transform="translate(10,20)")
        c.line(0, 0, 10, 10)
        c.group_end()
        svg = c.to_svg()
        assert '<g transform="translate(10,20)">' in svg
        assert "</g>" in svg

    def test_group_without_transform(self):
        """group_start() without transform emits plain <g>."""
        c = SvgCanvas(width=100, height=100)
        c.group_start()
        c.circle(50, 50, 10)
        c.group_end()
        svg = c.to_svg()
        assert "<g>" in svg
        assert "</g>" in svg


class TestLineDasharray:
    """Cover the stroke_dasharray branch in line() (L55)."""

    def test_line_with_dasharray(self):
        """stroke_dasharray produces the stroke-dasharray attribute."""
        c = SvgCanvas(width=100, height=100)
        c.line(0, 0, 100, 100, stroke_dasharray="5,3")
        svg = c.to_svg()
        assert 'stroke-dasharray="5,3"' in svg

    def test_line_without_dasharray(self):
        """No dasharray → no stroke-dasharray attribute."""
        c = SvgCanvas(width=100, height=100)
        c.line(0, 0, 100, 100)
        svg = c.to_svg()
        assert "stroke-dasharray" not in svg


class TestBackgroundNone:
    """Cover the background='none' branch in to_svg() (L150)."""

    def test_no_background_rect_when_none(self):
        """background='none' skips the background rect."""
        c = SvgCanvas(width=100, height=100, background="none")
        svg = c.to_svg()
        # No background rect
        assert '<rect width="100" height="100"' not in svg


class TestTextXmlEscaping:
    """Cover XML special character escaping in text() (L121)."""

    def test_text_escapes_ampersand(self):
        c = SvgCanvas(width=100, height=100)
        c.text(50, 50, "R1 & R2")
        svg = c.to_svg()
        assert "R1 &amp; R2" in svg

    def test_text_escapes_angle_brackets(self):
        c = SvgCanvas(width=100, height=100)
        c.text(50, 50, "<val>")
        svg = c.to_svg()
        assert "&lt;val&gt;" in svg
