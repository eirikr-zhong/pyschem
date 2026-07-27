"""Unit tests for Part/Pin behavior in lib.core.part."""

import re

from lib.core.part import Part, Pin
from lib.core.style import Style
from lib.symbols.data import PinDefinition, SymbolData


def test_part_auto_generates_ref_when_missing() -> None:
    part = Part(lib_id="Device:R")
    assert part.ref is not None
    assert part.ref.startswith("U")


def test_part_keeps_explicit_ref() -> None:
    part = Part(lib_id="Device:C", ref="C1")
    assert part.ref == "C1"


def test_pin_key_is_normalized_to_string() -> None:
    pin = Pin(key=1, part_ref="U1")
    assert pin.key == "1"


def test_part_pin_lazily_created_and_cached() -> None:
    part = Part(lib_id="Device:R", ref="R1")

    p1 = part.pin(1)
    p1_again = part.pin("1")

    assert p1 is p1_again
    assert p1.key == "1"
    assert p1.part_ref == "R1"


def test_part_pins_property_returns_copy() -> None:
    part = Part(lib_id="Device:R", ref="R1")
    part.pin("1")

    pins_copy = part.pins
    pins_copy["2"] = Pin(key="2", part_ref="R1")

    assert "2" not in part.pins
    assert "1" in part.pins


def test_set_style_and_get_style_roundtrip() -> None:
    part = Part(lib_id="Device:R", ref="R1")
    style = Style(x=10, y=20, anchor="left", rotation=90, locked=True)

    part.set_style(style)

    assert part.get_style() is style


def test_get_style_returns_default_when_not_set() -> None:
    part = Part(lib_id="Device:R", ref="R1")

    style = part.get_style()

    assert style.x is None
    assert style.y is None
    assert style.anchor == "center"
    assert style.rotation == 0
    assert style.locked is False


def test_auto_ref_generation_increments() -> None:
    """Two consecutive auto-ref Parts must have different refs."""
    p1 = Part(lib_id="Device:R")
    p2 = Part(lib_id="Device:C")
    assert p1.ref != p2.ref
    assert re.match(r"^U\d+$", p1.ref)
    assert re.match(r"^U\d+$", p2.ref)


def test_pin_integer_key_equals_string_key() -> None:
    """pin(1) and pin('1') must return the same Pin object."""
    part = Part(lib_id="Device:R", ref="R1")
    pin_str = part.pin("1")
    pin_int = part.pin(1)
    assert pin_str is pin_int


def test_pins_property_empty_on_bare_part() -> None:
    """Part with no pin access should have empty pins dict."""
    part = Part(lib_id="Device:R", ref="R1", value="10k")
    assert part.pins == {}


def test_pins_property_reflects_accessed_pins() -> None:
    """After accessing pins, pins property must reflect them."""
    part = Part(lib_id="Device:R", ref="R1")
    part.pin("1")
    part.pin("2")
    part.pin("A1")
    pins = part.pins
    assert len(pins) == 3
    assert "1" in pins
    assert "2" in pins
    assert "A1" in pins


def test_multiple_pins_access_different_keys() -> None:
    """Accessing multiple different pins should create them all."""
    part = Part(lib_id="Device:OpAmp", ref="U1")
    pins = [part.pin(str(i)) for i in range(1, 9)]  # 8 pins
    assert len(part.pins) == 8
    for i, pin in enumerate(pins, 1):
        assert pin.key == str(i)


def test_pin_connect_ignores_self_and_duplicate_links() -> None:
    p1 = Pin(key="1", part_ref="U1")
    p2 = Pin(key="2", part_ref="U2")

    p1.connect(p1, p2, p2)

    assert p1.connected_pins == [p2]
    assert p2.connected_pins == [p1]


def test_pin_disconnect_is_bidirectional_and_idempotent() -> None:
    p1 = Pin(key="1", part_ref="U1")
    p2 = Pin(key="2", part_ref="U2")
    p1.connect(p2)

    p1.disconnect(p2)
    assert p1.connected_pins == []
    assert p2.connected_pins == []

    p1.disconnect(p2)
    assert p1.connected_pins == []
    assert p2.connected_pins == []


def test_pin_disconnect_all_removes_all_neighbors() -> None:
    p1 = Pin(key="1", part_ref="U1")
    p2 = Pin(key="2", part_ref="U2")
    p3 = Pin(key="3", part_ref="U3")
    p1.connect(p2, p3)

    p1.disconnect_all()

    assert p1.connected_pins == []
    assert p1 not in p2.connected_pins
    assert p1 not in p3.connected_pins


def test_part_autobind_symbol_lookup_errors_are_suppressed(monkeypatch) -> None:
    import lib.symbols as symbols_mod

    def _boom():
        raise RuntimeError("symbol lookup failed")

    monkeypatch.setattr(symbols_mod, "get_default_symbols", _boom)

    part = Part(lib_id="Device:R", ref="R1")

    assert part.ref == "R1"
    assert part.available_pins == []


def test_part_clone_copies_component_metadata_with_new_ref() -> None:
    source = Part(
        "Device:R",
        ref="R1",
        value="10k",
        footprint="Resistor_SMD:R_0603_1608Metric",
        bom_fields={"Manufacturer": "Yageo", "MPN": "RC0603FR-0710KL"},
    )

    clone = source.clone(ref="R2")

    assert clone is not source
    assert clone.lib_id == "Device:R"
    assert clone.ref == "R2"
    assert clone.value == "10k"
    assert clone.footprint == "Resistor_SMD:R_0603_1608Metric"
    assert clone.bom_fields == source.bom_fields

    clone.bom_fields["MPN"] = "RC0603FR-0722KL"
    assert source.bom_fields["MPN"] == "RC0603FR-0710KL"


def test_part_clone_generates_a_fresh_ref_by_default() -> None:
    source = Part("Device:R", ref="R1")

    clone = source.clone()

    assert clone.ref is not None
    assert clone.ref != source.ref
    assert clone.ref.startswith("U")


def test_part_clone_recreates_accessed_pins_without_connections() -> None:
    source = Part("Device:R", ref="R1")
    other = Part("Device:C", ref="C1")
    source.pin("1").connect(other.pin("1"))
    source.pin("2")

    clone = source.clone(ref="R2")

    assert set(clone.pins) == {"1", "2"}
    assert clone.pin("1") is not source.pin("1")
    assert clone.pin("1").part_ref == "R2"
    assert clone.pin("1").connected_pins == []
    assert clone.pin("2").connected_pins == []
    assert source.pin("1").connected_pins == [other.pin("1")]


def test_part_clone_preserves_symbol_pin_resolution_and_symbol_data() -> None:
    symbol = SymbolData(
        name="Q_NPN_BCE",
        lib="Device",
        pins=[PinDefinition(number="1", name="B", type="input", x=0, y=0)],
    )
    source = Part("Device:Q_NPN_BCE", ref="Q1")
    source.attach_symbol(symbol)
    source.pin("B")

    clone = source.clone(ref="Q2")

    assert clone._symbol_data is symbol
    assert clone.pin("B").key == "1"
    assert clone.pin("B").part_ref == "Q2"
    assert clone.pin("B") is not source.pin("B")


def test_part_clone_has_an_independent_style() -> None:
    source = Part("Device:R", ref="R1")
    source.set_style(Style(x=10, y=20, rotation=90, locked=True))

    clone = source.clone(ref="R2")
    clone_style = clone.get_style()

    assert clone_style == source.get_style()
    assert clone_style is not source.get_style()
    clone_style.x = 30
    assert source.get_style().x == 10
