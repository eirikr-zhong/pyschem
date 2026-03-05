"""Tests for RenderTemplate (M1 skeleton).

Test-ID prefix: RT-
"""

import dataclasses

import pytest

from lib.core.page import PageConfig
from lib.core.render_style import (
    NetLabelStyle,
    RenderStyle,
    RenderTemplate,
    WireStyle,
)


# ---------------------------------------------------------------------------
# RT-01 .. RT-06  RenderTemplate construction
# ---------------------------------------------------------------------------


class TestRenderTemplateConstruction:
    def test_RT01_default_has_default_style_and_a1_page(self):
        """RT-01: RenderTemplate.default() wraps default style + A1 portrait."""
        tmpl = RenderTemplate.default()
        assert isinstance(tmpl.style, RenderStyle)
        assert tmpl.style.background == "#ffffff"
        assert tmpl.page.width == PageConfig.a1().width
        assert tmpl.page.height == PageConfig.a1().height

    def test_RT02_from_style_uses_default_page_when_none(self):
        """RT-02: from_style() with page=None defaults to A1 portrait."""
        style = RenderStyle.default()
        tmpl = RenderTemplate.from_style(style)
        assert tmpl.page.width == PageConfig.default().width
        assert tmpl.page.height == PageConfig.default().height

    def test_RT03_from_style_accepts_explicit_page(self):
        """RT-03: from_style() with explicit PageConfig stores it correctly."""
        style = RenderStyle.default()
        page = PageConfig.a3(landscape=True)
        tmpl = RenderTemplate.from_style(style, page=page)
        assert tmpl.page.width == page.width
        assert tmpl.page.height == page.height

    def test_RT04_direct_construction(self):
        """RT-04: direct RenderTemplate(style, page) works correctly."""
        style = RenderStyle(background="#cccccc")
        page = PageConfig.a4()
        tmpl = RenderTemplate(style=style, page=page)
        assert tmpl.style.background == "#cccccc"
        assert tmpl.page.width == PageConfig.a4().width

    def test_RT05_default_factory_called_when_not_provided(self):
        """RT-05: RenderTemplate() with no args produces valid defaults."""
        tmpl = RenderTemplate()
        assert isinstance(tmpl.style, RenderStyle)
        assert isinstance(tmpl.page, PageConfig)

    def test_RT06_is_frozen(self):
        """RT-06: RenderTemplate is frozen — mutation raises FrozenInstanceError."""
        tmpl = RenderTemplate.default()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            tmpl.page = PageConfig.a4()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RT-07 .. RT-12  dataclasses.replace integration
# ---------------------------------------------------------------------------


class TestRenderTemplateReplace:
    def test_RT07_replace_page(self):
        """RT-07: dataclasses.replace can swap page without touching style."""
        tmpl = RenderTemplate.default()
        a4 = PageConfig.a4()
        new_tmpl = dataclasses.replace(tmpl, page=a4)
        assert new_tmpl.page.width == a4.width
        assert new_tmpl.style is tmpl.style   # unchanged reference

    def test_RT08_replace_style(self):
        """RT-08: dataclasses.replace can swap style without touching page."""
        tmpl = RenderTemplate.default()
        custom = RenderStyle(background="#ff0000")
        new_tmpl = dataclasses.replace(tmpl, style=custom)
        assert new_tmpl.style.background == "#ff0000"
        assert new_tmpl.page is tmpl.page     # unchanged reference

    def test_RT09_original_unchanged_after_replace(self):
        """RT-09: replace() does not mutate original template."""
        tmpl = RenderTemplate.default()
        dataclasses.replace(tmpl, page=PageConfig.a4())
        assert tmpl.page.width == PageConfig.a1().width


# ---------------------------------------------------------------------------
# RT-10 .. RT-14  Export reachability
# ---------------------------------------------------------------------------


class TestRenderTemplateExports:
    def test_RT10_importable_from_lib_core(self):
        """RT-10: RenderTemplate is importable from lib.core."""
        from lib.core import RenderTemplate  # noqa: F401

    def test_RT11_importable_from_lib(self):
        """RT-11: RenderTemplate is importable from lib."""
        from lib import RenderTemplate  # noqa: F401

    def test_RT12_importable_from_pyschem(self):
        """RT-12: RenderTemplate is importable from pyschem."""
        from pyschem import RenderTemplate  # noqa: F401

    def test_RT13_wire_style_importable_from_pyschem(self):
        """RT-13: WireStyle is importable from pyschem."""
        from pyschem import WireStyle  # noqa: F401

    def test_RT14_label_net_style_importable_from_pyschem(self):
        """RT-14: NetLabelStyle is importable from pyschem."""
        from pyschem import NetLabelStyle  # noqa: F401

    def test_RT15_render_style_importable_from_pyschem(self):
        """RT-15: RenderStyle is importable from pyschem."""
        from pyschem import RenderStyle  # noqa: F401

    def test_RT16_junction_importable_from_pyschem(self):
        """RT-16: Junction is importable from pyschem."""
        from pyschem import Junction  # noqa: F401


# ---------------------------------------------------------------------------
# RT-17  Style merge end-to-end via template
# ---------------------------------------------------------------------------


class TestRenderTemplateEndToEnd:
    def test_RT17_merge_style_and_wrap_in_template(self):
        """RT-17: merge a custom style and wrap result in a template."""
        base = RenderStyle.default()
        override = RenderStyle(
            wire=WireStyle(color="#ff0000"),
            label_net=NetLabelStyle(font_size=20.0),
            background="#111111",
        )
        merged = base.merge(override)
        tmpl = RenderTemplate.from_style(merged, page=PageConfig.a2(landscape=True))
        assert tmpl.style.wire.color == "#ff0000"
        assert tmpl.style.wire.width == 1.8      # from default
        assert tmpl.style.label_net.font_size == 20.0
        assert tmpl.style.background == "#111111"
        assert tmpl.page.width == PageConfig.a2(landscape=True).width
