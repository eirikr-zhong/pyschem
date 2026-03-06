"""Unit tests for PageConfig (canvas / page configuration).

Test IDs
--------
PAGE-01   PageConfig default() returns A1 portrait (1684 × 2384 px)
PAGE-02   PageConfig.a1() matches default()
PAGE-03   PageConfig.a1(landscape=True) swaps dimensions
PAGE-04   PageConfig.a0() returns 2384 × 3370
PAGE-05   PageConfig.a2() returns 1191 × 1684
PAGE-06   PageConfig.a3() returns 842 × 1191
PAGE-07   PageConfig.a4() returns 595 × 842
PAGE-08   PageConfig.from_paper('A3') matches .a3()
PAGE-09   PageConfig.from_paper case-insensitive ('a4' == 'A4')
PAGE-10   PageConfig.from_paper unknown size raises ValueError
PAGE-11   PageConfig custom width/height stored correctly
PAGE-12   SVG output uses A1 dimensions by default (no page/width/height given)
PAGE-13   SVG viewBox matches width/height from A1 default
PAGE-14   export_svg with PageConfig.a3() sets a3 dimensions in SVG
PAGE-15   get_svg_string(page=PageConfig.a4()) respects a4 dimensions
PAGE-16   render(fmt='svg', page=...) respects PageConfig dimensions
PAGE-17   Legacy width/height kwargs still work (backwards compat)
PAGE-18   PageConfig imported from top-level pyschem module
PAGE-19   Landscape A0 wider than tall
PAGE-20   PageConfig landscape flag correctly flips dimensions for all sizes
"""

from __future__ import annotations

import re

import pytest

from lib.core.page import PageConfig
from lib.core.schematic import Schematic
from lib.core.part import Part


# ---------------------------------------------------------------------------
# ISO A-series pixel dimensions at 96 dpi (portrait)
# ---------------------------------------------------------------------------
_A0 = (2384, 3370)
_A1 = (1684, 2384)
_A2 = (1191, 1684)
_A3 = (842, 1191)
_A4 = (595, 842)


# ===========================================================================
# PAGE — PageConfig construction
# ===========================================================================

class TestPageConfigFactories:
    """PAGE-01 to PAGE-11: construction and dimensions."""

    def test_default_is_a1_portrait(self):
        """PAGE-01: default() returns A1 portrait (1684 × 2384)."""
        cfg = PageConfig.default()
        assert cfg.width == _A1[0]
        assert cfg.height == _A1[1]

    def test_a1_matches_default(self):
        """PAGE-02: a1() produces same dimensions as default()."""
        assert PageConfig.a1().width == PageConfig.default().width
        assert PageConfig.a1().height == PageConfig.default().height

    def test_a1_landscape_swaps(self):
        """PAGE-03: a1(landscape=True) swaps width and height."""
        cfg = PageConfig.a1(landscape=True)
        assert cfg.width == _A1[1]
        assert cfg.height == _A1[0]

    def test_a0_portrait(self):
        """PAGE-04: a0() returns 2384 × 3370."""
        cfg = PageConfig.a0()
        assert cfg.width == _A0[0]
        assert cfg.height == _A0[1]

    def test_a2_portrait(self):
        """PAGE-05: a2() returns 1191 × 1684."""
        cfg = PageConfig.a2()
        assert cfg.width == _A2[0]
        assert cfg.height == _A2[1]

    def test_a3_portrait(self):
        """PAGE-06: a3() returns 842 × 1191."""
        cfg = PageConfig.a3()
        assert cfg.width == _A3[0]
        assert cfg.height == _A3[1]

    def test_a4_portrait(self):
        """PAGE-07: a4() returns 595 × 842."""
        cfg = PageConfig.a4()
        assert cfg.width == _A4[0]
        assert cfg.height == _A4[1]

    def test_from_paper_a3(self):
        """PAGE-08: from_paper('A3') matches a3()."""
        cfg = PageConfig.from_paper("A3")
        assert cfg.width == PageConfig.a3().width
        assert cfg.height == PageConfig.a3().height

    def test_from_paper_case_insensitive(self):
        """PAGE-09: from_paper is case-insensitive."""
        assert PageConfig.from_paper("a4").width == PageConfig.a4().width
        assert PageConfig.from_paper("A4").height == PageConfig.a4().height

    def test_from_paper_unknown_raises(self):
        """PAGE-10: from_paper with unknown size raises ValueError."""
        with pytest.raises(ValueError, match="Unknown paper size"):
            PageConfig.from_paper("B5")

    def test_custom_dimensions(self):
        """PAGE-11: custom width/height stored correctly."""
        cfg = PageConfig(width=1920.0, height=1080.0)
        assert cfg.width == 1920.0
        assert cfg.height == 1080.0

    def test_landscape_a0_wider_than_tall(self):
        """PAGE-19: landscape A0 is wider than it is tall."""
        cfg = PageConfig.a0(landscape=True)
        assert cfg.width > cfg.height

    def test_landscape_flip_all_sizes(self):
        """PAGE-20: landscape flag flips dimensions for all A-series sizes."""
        for method in (PageConfig.a0, PageConfig.a1, PageConfig.a2,
                       PageConfig.a3, PageConfig.a4):
            portrait = method()
            landscape = method(landscape=True)
            assert landscape.width == portrait.height
            assert landscape.height == portrait.width


# ===========================================================================
# PAGE — SVG integration
# ===========================================================================

def _simple_schematic() -> Schematic:
    sch = Schematic("page_test")
    r = Part("Device:R", ref="R1", value="1k")
    sch.add_part(r)
    return sch


def _svg_dims(svg: str) -> tuple[float, float]:
    m = re.search(r'<svg[^>]*width="([^"]+)"[^>]*height="([^"]+)"', svg)
    assert m is not None
    return float(m.group(1)), float(m.group(2))


class TestPageConfigSvgIntegration:
    """PAGE-12 to PAGE-18: PageConfig used by SVG render chain."""

    def test_default_svg_uses_a1_dimensions(self):
        """PAGE-12: SVG defaults to A1 dimensions."""
        sch = _simple_schematic()
        svg = sch.get_svg_string()
        width, height = _svg_dims(svg)
        assert width == pytest.approx(_A1[0])
        assert height == pytest.approx(_A1[1])

    def test_default_svg_viewbox_matches_a1(self):
        """PAGE-13: viewBox present; output width/height match page."""
        sch = _simple_schematic()
        svg = sch.get_svg_string()
        width, height = _svg_dims(svg)
        assert width == pytest.approx(_A1[0])
        assert height == pytest.approx(_A1[1])
        # viewBox is fit-to-content so it won't equal "0 0 1684.0 2384.0"
        assert 'viewBox="' in svg

    def test_export_svg_with_a3_page(self, tmp_path):
        """PAGE-14: export_svg with PageConfig.a3() keeps page width/height."""
        sch = _simple_schematic()
        out = tmp_path / "a3.svg"
        sch.export_svg(str(out), page=PageConfig.a3())
        content = out.read_text()
        width, height = _svg_dims(content)
        assert width == pytest.approx(_A3[0])
        assert height == pytest.approx(_A3[1])

    def test_get_svg_string_with_a4_page(self):
        """PAGE-15: get_svg_string(page=a4()) keeps page width/height."""
        sch = _simple_schematic()
        svg = sch.get_svg_string(page=PageConfig.a4())
        width, height = _svg_dims(svg)
        assert width == pytest.approx(_A4[0])
        assert height == pytest.approx(_A4[1])

    def test_render_svg_with_page(self, tmp_path):
        """PAGE-16: render(fmt='svg', page=...) keeps page width/height."""
        sch = _simple_schematic()
        out = tmp_path / "render.svg"
        sch.render(str(out), fmt="svg", page=PageConfig.a2())
        content = out.read_text()
        width, height = _svg_dims(content)
        assert width == pytest.approx(_A2[0])
        assert height == pytest.approx(_A2[1])

    def test_legacy_width_height_still_work(self):
        """PAGE-17: legacy width/height kwargs remain functional."""
        sch = _simple_schematic()
        svg = sch.get_svg_string(width=800, height=600)
        width, height = _svg_dims(svg)
        assert width == pytest.approx(800)
        assert height == pytest.approx(600)

    def test_pageconfig_importable_from_top_level(self):
        """PAGE-18: PageConfig is importable from the pyschem top-level."""
        import pyschem
        assert hasattr(pyschem, "PageConfig")
        assert pyschem.PageConfig.a1().width == _A1[0]

    def test_custom_page_dimensions_in_svg(self):
        """Custom PageConfig dimensions appear in SVG output."""
        sch = _simple_schematic()
        cfg = PageConfig(width=1200.0, height=900.0)
        svg = sch.get_svg_string(page=cfg)
        width, height = _svg_dims(svg)
        assert width == pytest.approx(cfg.width)
        assert height == pytest.approx(cfg.height)
        # viewBox is fit-to-content — verify it is present but not necessarily full-page
        assert 'viewBox="' in svg

    def test_a0_landscape_svg_dimensions(self):
        """A0 landscape page produces correct wide canvas dimensions in SVG."""
        sch = _simple_schematic()
        cfg = PageConfig.a0(landscape=True)
        svg = sch.get_svg_string(page=cfg)
        width, height = _svg_dims(svg)
        # Landscape A0 base: 3370 wide × 2384 tall
        assert width == pytest.approx(3370.0)
        assert height == pytest.approx(2384.0)
