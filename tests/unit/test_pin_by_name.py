"""Unit tests for pin-by-name (symbol name) connection support."""

import pytest

from lib.core.part import Part, Pin, parse_pins
from lib.errors.exceptions import PinNotFoundError
from lib.symbols.data import PinDefinition, SymbolData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bjt_symbol() -> SymbolData:
    """Minimal NPN BJT SymbolData with B/C/E named pins (numbers 1/2/3)."""
    return SymbolData(
        name="Q_NPN_BCE",
        lib="Device",
        pins=[
            PinDefinition(number="1", name="B", type="input", x=0, y=0),
            PinDefinition(number="2", name="C", type="passive", x=0, y=2.54),
            PinDefinition(number="3", name="E", type="passive", x=0, y=-2.54),
        ],
    )


def _bjt_part() -> Part:
    part = Part("Device:Q_NPN_BCE", ref="Q1")
    part.attach_symbol(_bjt_symbol())
    return part


# ---------------------------------------------------------------------------
# 1. Pin name alias → canonical number
# ---------------------------------------------------------------------------

def test_pin_by_name_returns_pin_with_number_as_key() -> None:
    """pin('B') on a BJT should return Pin with key == '1' (the pin number)."""
    q1 = _bjt_part()
    p = q1.pin("B")
    assert isinstance(p, Pin)
    assert p.key == "1"
    assert p.part_ref == "Q1"


def test_pin_by_name_all_bce_aliases() -> None:
    """B, C, E all resolve to their respective numbers."""
    q1 = _bjt_part()
    assert q1.pin("B").key == "1"
    assert q1.pin("C").key == "2"
    assert q1.pin("E").key == "3"


# ---------------------------------------------------------------------------
# 2. Pin number still works when symbol_data is attached
# ---------------------------------------------------------------------------

def test_pin_by_number_with_symbol_data() -> None:
    """Numeric key '1' resolves correctly when symbol_data is attached."""
    q1 = _bjt_part()
    p = q1.pin("1")
    assert p.key == "1"


def test_pin_by_int_with_symbol_data() -> None:
    """Integer key 1 is coerced to '1' and resolves correctly."""
    q1 = _bjt_part()
    p = q1.pin(1)
    assert p.key == "1"


# ---------------------------------------------------------------------------
# 3. Cache consistency: name alias and number return same object
# ---------------------------------------------------------------------------

def test_pin_name_and_number_return_same_object() -> None:
    """pin('B') and pin('1') must return the exact same Pin object."""
    q1 = _bjt_part()
    pin_by_name = q1.pin("B")
    pin_by_number = q1.pin("1")
    assert pin_by_name is pin_by_number


def test_pin_name_cached_across_multiple_calls() -> None:
    """Repeated calls to pin('B') return the same object."""
    q1 = _bjt_part()
    assert q1.pin("B") is q1.pin("B")


# ---------------------------------------------------------------------------
# 4. Unknown pin name raises PinNotFoundError
# ---------------------------------------------------------------------------

def test_unknown_pin_name_raises_error() -> None:
    """pin('X') on a BJT should raise PinNotFoundError."""
    q1 = _bjt_part()
    with pytest.raises(PinNotFoundError):
        q1.pin("X")


def test_error_message_contains_available_pins() -> None:
    """PinNotFoundError message should list available pins."""
    q1 = _bjt_part()
    with pytest.raises(PinNotFoundError, match="B"):
        q1.pin("Z")


# ---------------------------------------------------------------------------
# 5. Backwards compat: no symbol_data → lazy creation, no error
# ---------------------------------------------------------------------------

def test_no_symbol_data_lazy_creation() -> None:
    """Without attach_symbol, pin('B') lazily creates a Pin keyed 'B'."""
    part = Part("Device:Q_NPN_BCE", ref="Q2")
    p = part.pin("B")
    assert p.key == "B"
    assert p.part_ref == "Q2"


def test_no_symbol_data_numeric_key_lazy() -> None:
    """Without attach_symbol, pin(1) lazily creates a Pin keyed '1'."""
    part = Part("Device:R", ref="R1")
    p = part.pin(1)
    assert p.key == "1"


# ---------------------------------------------------------------------------
# 6. Mixed usage: number and name on same part
# ---------------------------------------------------------------------------

def test_mixed_number_and_name_usage() -> None:
    """pin('B') and pin(1) return the same object when B maps to number 1."""
    q1 = _bjt_part()
    by_name = q1.pin("B")
    by_num = q1.pin(1)
    assert by_name is by_num


def test_mixed_c_and_2() -> None:
    """pin('C') and pin(2) return the same object when C maps to number 2."""
    q1 = _bjt_part()
    assert q1.pin("C") is q1.pin(2)


# ---------------------------------------------------------------------------
# 7. parse_pins() batch helper
# ---------------------------------------------------------------------------

def test_parse_pins_returns_list_of_pins() -> None:
    """parse_pins(q1, 'B C E') returns three Pin objects."""
    q1 = _bjt_part()
    pins = parse_pins(q1, "B C E")
    assert len(pins) == 3
    assert all(isinstance(p, Pin) for p in pins)


def test_parse_pins_keys_are_numbers() -> None:
    """parse_pins resolves names to canonical numbers."""
    q1 = _bjt_part()
    pins = parse_pins(q1, "B C E")
    assert pins[0].key == "1"
    assert pins[1].key == "2"
    assert pins[2].key == "3"


def test_parse_pins_numeric_spec() -> None:
    """parse_pins works with numeric tokens too."""
    q1 = _bjt_part()
    pins = parse_pins(q1, "1 2 3")
    assert [p.key for p in pins] == ["1", "2", "3"]


def test_parse_pins_mixed_spec() -> None:
    """parse_pins handles mixed name/number tokens."""
    q1 = _bjt_part()
    # 'B' resolves to number '1'; '2' resolves to number '2' — different pins
    pins = parse_pins(q1, "B 2")
    assert pins[0].key == "1"  # B -> 1
    assert pins[1].key == "2"  # 2 -> 2
    assert pins[0] is not pins[1]

    # Separate pins
    pins2 = parse_pins(q1, "B C")
    assert pins2[0].key == "1"
    assert pins2[1].key == "2"
    assert pins2[0] is not pins2[1]


# ---------------------------------------------------------------------------
# 8. parse_pins() whitespace robustness
# ---------------------------------------------------------------------------

def test_parse_pins_extra_spaces_ignored() -> None:
    """Extra spaces and tabs in pin_spec are handled gracefully."""
    q1 = _bjt_part()
    pins = parse_pins(q1, "  B   C\tE  ")
    assert len(pins) == 3
    assert [p.key for p in pins] == ["1", "2", "3"]


def test_parse_pins_empty_string_returns_empty_list() -> None:
    """Empty string returns an empty list."""
    q1 = _bjt_part()
    assert parse_pins(q1, "") == []


def test_parse_pins_whitespace_only_returns_empty_list() -> None:
    """Whitespace-only string returns an empty list."""
    q1 = _bjt_part()
    assert parse_pins(q1, "   \t  ") == []


# ---------------------------------------------------------------------------
# 9. available_pins property
# ---------------------------------------------------------------------------

def test_available_pins_includes_numbers_and_names() -> None:
    """available_pins lists both numbers and non-tilde names."""
    q1 = _bjt_part()
    available = q1.available_pins
    assert "1" in available
    assert "2" in available
    assert "3" in available
    assert "B" in available
    assert "C" in available
    assert "E" in available


def test_available_pins_empty_without_symbol_data() -> None:
    """available_pins is empty when no symbol is attached."""
    part = Part("Device:R", ref="R1")
    assert part.available_pins == []


def test_available_pins_excludes_tilde_names() -> None:
    """Tilde '~' pin names (anonymous) are not included in available_pins."""
    sym = SymbolData(
        name="R",
        lib="Device",
        pins=[
            PinDefinition(number="1", name="~", type="passive", x=0, y=0),
            PinDefinition(number="2", name="~", type="passive", x=0, y=0),
        ],
    )
    part = Part("Device:R", ref="R1")
    part.attach_symbol(sym)
    available = part.available_pins
    assert "~" not in available
    assert "1" in available
    assert "2" in available


# ---------------------------------------------------------------------------
# 10. Integration: connect BJT pins to nets
# ---------------------------------------------------------------------------

def test_bjt_pin_names_connectable_to_net() -> None:
    """Named pins can be connected to a NetLabel exactly like numbered pins."""
    from lib.core.part import NetLabel

    q1 = _bjt_part()
    base_label = NetLabel("BASE")
    collector_label = NetLabel("VCC")
    emitter_label = NetLabel("GND")

    q1.pin("B").connect(base_label.pin("1"))
    q1.pin("C").connect(collector_label.pin("1"))
    q1.pin("E").connect(emitter_label.pin("1"))

    assert q1.pin("B").is_connected
    assert q1.pin("C").is_connected
    assert q1.pin("E").is_connected
