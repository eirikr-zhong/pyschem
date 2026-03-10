"""Unit tests for the Junction topology/graphics helper component."""

from lib.core.connect import derive_nets
from lib.core.junction import Junction
from lib.core.part import Part
from lib.core.schematic import Schematic


def test_junction_exposes_single_pin_property() -> None:
    junction = Junction(ref="J1")

    assert junction.junction_pin.key == "1"
    assert junction.junction_pin.part_ref == "J1"
    assert list(junction.pins.keys()) == ["1"]


def test_junction_has_no_name_attribute() -> None:
    junction = Junction()
    assert not hasattr(junction, "name")


def test_junction_pin_is_included_in_derived_nets() -> None:
    r1 = Part("Device:R", ref="R1")
    junction = Junction(ref="J1")

    r1.pin("1").connect(junction.junction_pin)
    nets = derive_nets([r1, junction])

    assert len(nets) == 1
    assert nets[0].pin_count == 2


def test_junction_renders_as_dot_without_missing_symbol_placeholder() -> None:
    sch = Schematic("junction_svg")
    r1 = Part("Device:R", ref="R1")
    junction = Junction(ref="J1")

    sch.place(r1, x=20.0, y=20.0)
    sch.place(junction, x=45.0, y=20.0)
    sch.connect(r1.pin("1"), junction.junction_pin)

    svg = sch.get_svg_string()
    assert "<circle" in svg
    assert "? power:Junction" not in svg
    assert ">J1<" not in svg
