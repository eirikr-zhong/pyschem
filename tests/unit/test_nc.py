"""Tests for explicit no-connect markers."""

import re

import pytest

from lib.core.connect import connect
from lib.core.net import NC
from lib.core.part import Part
from lib.core.schematic import Schematic
from lib.render.schematic_svg import _MARGIN
from lib.render.symbol_renderer import SymbolRenderer
from lib.symbols.data import PinDefinition, SymbolData


def test_nc_requires_pin() -> None:
    with pytest.raises(TypeError, match="requires a Pin"):
        NC("1")  # type: ignore[arg-type]


def test_nc_does_not_create_electrical_net() -> None:
    sch = Schematic("no_connect")
    u1 = Part("Device:U", ref="U1")
    marker = NC(u1.pin("7"))
    sch.add_part(u1)
    sch.add_part(marker)

    assert sch.nets == []
    assert marker.target_pin is u1.pin("7")


def test_nc_draws_x_at_target_pin_without_wire() -> None:
    sch = Schematic("no_connect_svg")
    u1 = Part("Device:U", ref="U1")
    unused_pin = u1.pin("7")
    marker = NC(unused_pin)
    sch.place(u1, x=40, y=30)
    sch.add_part(marker)

    svg = sch.get_svg_string()
    group = re.search(r'<g class="no-connect">(.*?)</g>', svg, flags=re.DOTALL)
    assert group, "Expected an SVG no-connect marker group"

    lines = re.findall(
        r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"',
        group.group(1),
    )
    assert len(lines) == 2
    assert all(float(x1) != float(x2) and float(y1) != float(y2)
               for x1, y1, x2, y2 in lines)
    assert '#1565c0' not in group.group(1), "NC must not render an electrical wire"


def test_nc_marks_rotated_outer_pin_endpoint_and_fits_content(tmp_path) -> None:
    sch = Schematic("rotated_no_connect_svg")
    u1 = Part("Test:Rotated", ref="U1")
    u1.attach_symbol(
        SymbolData(
            name="Rotated",
            lib="Test",
            pins=[PinDefinition("1", "NC", "passive", 20, 0, 0, 10)],
        )
    )
    marker = NC(u1.pin("1"))
    sch.place(u1, x=40, y=30, rotation=90)
    sch.add_part(marker)

    output_path = tmp_path / "rotated_no_connect.svg"
    sch.export_svg(output_path, fit_to_content=True)
    svg = output_path.read_text(encoding="utf-8")

    group = re.search(r'<g class="no-connect">(.*?)</g>', svg, flags=re.DOTALL)
    assert group, "Expected an SVG no-connect marker group"
    lines = re.findall(
        r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"',
        group.group(1),
    )
    assert len(lines) == 2

    endpoint = SymbolRenderer().pin_endpoints(
        u1,
        _MARGIN + 40 * 3,
        _MARGIN + 30 * 3,
        symbol_name="Rotated",
        rotation=90,
    )[("U1", "1")]
    for x1, y1, x2, y2 in lines:
        assert (float(x1) + float(x2)) / 2 == pytest.approx(endpoint[0])
        assert (float(y1) + float(y2)) / 2 == pytest.approx(endpoint[1])

    viewbox = re.search(r'viewBox="([^"]+)"', svg)
    assert viewbox, "Expected a fitted SVG viewBox"
    vb_x, vb_y, vb_width, vb_height = (float(value) for value in viewbox.group(1).split())
    for x1, y1, x2, y2 in lines:
        for x, y in ((float(x1), float(y1)), (float(x2), float(y2))):
            assert vb_x <= x <= vb_x + vb_width
            assert vb_y <= y <= vb_y + vb_height


def test_nc_is_omitted_from_dot_output() -> None:
    sch = Schematic("no_connect_dot")
    u1 = Part("Device:U", ref="U1")
    marker = NC(u1.pin("7"))
    sch.add_part(u1)
    sch.add_part(marker)

    dot = sch.get_dot_string()
    assert '"U1"' in dot
    assert marker.ref not in dot


def test_nc_on_connected_pin_is_erc_error() -> None:
    sch = Schematic("invalid_no_connect")
    u1 = Part("Device:U", ref="U1")
    r1 = Part("Device:R", ref="R1")
    marked_pin = u1.pin("7")
    marker = NC(marked_pin)
    sch.add_part(u1)
    sch.add_part(r1)
    sch.add_part(marker)
    connect(marked_pin, r1.pin("1"))

    errors = sch.erc(raise_on_error=False)
    assert errors == [
        f"ERC: NC marker '{marker.ref}' targets connected pin U1.7"
    ]


def test_nc_target_must_belong_to_schematic() -> None:
    sch = Schematic("missing_no_connect_target")
    u1 = Part("Device:U", ref="U1")
    marker = NC(u1.pin("7"))
    sch.add_part(marker)

    errors = sch.erc(raise_on_error=False)
    assert errors == [
        f"ERC: NC marker '{marker.ref}' targets a pin outside this schematic"
    ]
