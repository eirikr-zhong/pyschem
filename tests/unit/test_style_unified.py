"""Tests for unified Style resolution and compatibility behavior."""

from __future__ import annotations

import dataclasses
import re

import pytest

from lib.core.part import Part
from lib.core.render_style import PinStyle, RenderStyle, RenderTemplate, TextPlacementStyle
from lib.core.schematic import Schematic
from lib.core.style import Style
from lib.core.style_resolver import resolve_style
from lib.symbols.data import PinDefinition, SymbolData, SymbolPrimitive


def _test_symbol() -> SymbolData:
    return SymbolData(
        name="TestSym",
        lib="Test",
        primitives=[
            SymbolPrimitive(
                "polygon",
                [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0), (-10.0, -10.0)],
            )
        ],
        pins=[
            PinDefinition(number="11", name="IN_A", type="input", x=-15.0, y=0.0, orientation=180, length=5.0),
            PinDefinition(number="22", name="OUT_B", type="output", x=15.0, y=0.0, orientation=0, length=5.0),
        ],
    )


def _one_part_schematic(*, ref: str = "U1", value: str = "10k") -> tuple[Schematic, Part]:
    sch = Schematic("unified_style")
    part = Part("Test:TestSym", ref=ref, value=value)
    part.attach_symbol(_test_symbol())
    part.pin("11")
    part.pin("22")
    sch.add_part(part)
    return sch, part


def _extract_text_xy(svg: str, text: str) -> tuple[float, float]:
    m = re.search(rf'<text x="([^"]+)" y="([^"]+)"[^>]*>{re.escape(text)}</text>', svg)
    assert m is not None, f"Text '{text}' not found in SVG"
    return float(m.group(1)), float(m.group(2))


def test_style_default_has_complete_render_defaults() -> None:
    style = Style.default()
    # canvas_target_min_font_px is intentionally None by default (opt-in auto-scaling)
    _ALLOWED_NONE = {"canvas_target_min_font_px"}

    def _walk(value: object, path: str = "root") -> None:
        if dataclasses.is_dataclass(value):
            for f in dataclasses.fields(value):
                if path == "root" and f.name in {"x", "y"}:
                    continue
                _walk(getattr(value, f.name), f"{path}.{f.name}")
            return
        if path.rsplit(".", 1)[-1] in _ALLOWED_NONE:
            return
        assert value is not None, f"Found None render default at {path}"

    _walk(style)


def test_style_merge_none_does_not_override_values() -> None:
    base = Style.default().merge(
        Style(
            x=42.0,
            background="#101010",
            pin=PinStyle(pin_name_visible=False),
        )
    )
    merged = base.merge(Style(x=None, background=None, pin=PinStyle(pin_name_visible=None)))

    assert merged.x == 42.0
    assert merged.background == "#101010"
    assert merged.pin.pin_name_visible is False


def test_resolve_style_precedence_allows_per_part_visibility() -> None:
    sch = Schematic("precedence")
    r1 = Part("Test:TestSym", ref="R1", value="1k")
    r2 = Part("Test:TestSym", ref="R2", value="1k")
    sym = _test_symbol()
    r1.attach_symbol(sym)
    r2.attach_symbol(sym)
    sch.add_part(r1)
    sch.add_part(r2)

    r2.set_style(Style(ref_text=TextPlacementStyle(visible=True)))
    template = RenderTemplate.from_style(Style(ref_text=TextPlacementStyle(visible=False)))
    svg = sch.get_svg_string(template=template)

    assert ">R1<" not in svg
    assert ">R2<" in svg


def test_unified_visibility_toggles_hide_ref_value_and_pin_text() -> None:
    sch, _ = _one_part_schematic()
    style = Style.default().merge(
        Style(
            ref_text=TextPlacementStyle(visible=False),
            value_text=TextPlacementStyle(visible=False),
            pin=PinStyle(pin_name_visible=False, pin_value_visible=False),
        )
    )
    svg = sch.get_svg_string(template=RenderTemplate.from_style(style))

    assert ">U1<" not in svg
    assert ">10k<" not in svg
    assert ">IN_A<" not in svg
    assert ">OUT_B<" not in svg
    assert ">11<" not in svg
    assert ">22<" not in svg


def test_pin_value_visibility_can_replace_pin_name_labels() -> None:
    sch, _ = _one_part_schematic()
    style = Style.default().merge(
        Style(
            pin=PinStyle(pin_name_visible=False, pin_value_visible=True),
        )
    )
    svg = sch.get_svg_string(template=RenderTemplate.from_style(style))

    assert ">IN_A<" not in svg
    assert ">OUT_B<" not in svg
    assert ">11<" in svg
    assert ">22<" in svg


def test_ref_position_rotation_mode_changes_coordinates() -> None:
    sch, part = _one_part_schematic()
    part.set_style(Style(x=20.0, y=20.0, rotation=90, locked=True))

    component_mode = Style(
        ref_text=TextPlacementStyle(position="right", offset=4.0, rotation_mode="component")
    )
    screen_mode = Style(
        ref_text=TextPlacementStyle(position="right", offset=4.0, rotation_mode="screen")
    )

    svg_component = sch.get_svg_string(template=RenderTemplate.from_style(component_mode))
    svg_screen = sch.get_svg_string(template=RenderTemplate.from_style(screen_mode))
    comp_x, comp_y = _extract_text_xy(svg_component, "U1")
    scr_x, scr_y = _extract_text_xy(svg_screen, "U1")

    assert (comp_x, comp_y) != pytest.approx((scr_x, scr_y), rel=1e-6)
    assert comp_y < scr_y


def test_legacy_renderstyle_path_warns_and_still_resolves() -> None:
    legacy = RenderStyle(ref_text=TextPlacementStyle(visible=False), background="#ffeeaa")
    with pytest.warns(DeprecationWarning):
        template = RenderTemplate.from_style(legacy)
        resolved = resolve_style(None, template)

    assert resolved.background == "#ffeeaa"
    assert resolved.ref_text.visible is False


def test_resolve_style_handles_template_with_none_style() -> None:
    template = RenderTemplate(style=None)  # type: ignore[arg-type]

    resolved = resolve_style(template=template)

    assert resolved == Style.default()
