"""Part, Pin, and NetLabel classes for schematic components.

vNext architecture: connections are driven by Pin.connect().
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Union, cast

from lib.core.style import DefaultPlacementStyle, Style
from lib.errors.exceptions import PinNotFoundError

if TYPE_CHECKING:
    from lib.symbols.data import SymbolData

# Global counter for auto-generated refs
_ref_counter = 0


def _generate_ref() -> str:
    """Generate a unique reference designator."""
    global _ref_counter
    _ref_counter += 1
    return f"U{_ref_counter}"


# Counter for auto-generated NetLabel refs
_net_label_counter = itertools.count(1)


@dataclass
class Pin:
    """Represents a component pin.

    In the vNext architecture, ``Pin`` is the primary connection primitive.
    Connections are stored as an adjacency list (``_connections``) forming
    a **pin graph**.  Nets are *derived* from connected components in this
    graph — they are never stored explicitly.

    Attributes:
        key: Pin identifier (e.g., "1", "2", "A1")
        part_ref: Reference designator of the parent part
    """

    key: str
    part_ref: str
    _connections: list["Pin"] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Ensure key is a string
        self.key = str(self.key)

    # ------------------------------------------------------------------
    # Connection API (vNext: pin-driven)
    # ------------------------------------------------------------------

    def connect(self, *others: "Pin") -> None:
        """Connect this pin to one or more other pins.

        Creates bidirectional edges in the pin graph.  Duplicate and
        self-connections are silently ignored.

        Args:
            *others: Pins to connect to.
        """
        for other in others:
            if other is self:
                continue
            if other not in self._connections:
                self._connections.append(other)
            if self not in other._connections:
                other._connections.append(self)

    def disconnect(self, other: "Pin") -> None:
        """Remove the connection between this pin and *other*.

        Silently ignored if the two pins are not connected.
        """
        if other in self._connections:
            self._connections.remove(other)
        if self in other._connections:
            other._connections.remove(self)

    def disconnect_all(self) -> None:
        """Remove all connections from this pin."""
        for other in list(self._connections):
            self.disconnect(other)

    @property
    def connected_pins(self) -> list["Pin"]:
        """Return a copy of the directly connected pins."""
        return list(self._connections)

    @property
    def is_connected(self) -> bool:
        """Return True if this pin has at least one connection."""
        return len(self._connections) > 0


@dataclass
class Part:
    """Represents a component instance.

    Attributes:
        lib_id: Symbol library identifier (e.g., "Device:R")
        ref: Reference designator (e.g., "R1"). If None, auto-generated.
        value: Component value (e.g., "10k")
        footprint: Optional PCB metadata string (not used by rendering)
    """

    lib_id: str
    ref: Optional[str] = None
    value: Optional[str] = None
    footprint: Optional[str] = None
    _style: Optional[Style] = field(default=None, repr=False)
    _pins: dict[str, Pin] = field(default_factory=dict, repr=False)
    _symbol_data: Optional["SymbolData"] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Auto-generate ref if not provided
        if self.ref is None:
            self.ref = _generate_ref()

        # Optional auto-binding via global Symbols singleton.
        # If configured, resolve lib_id like "Device:R" -> find_symbol("Device", "R").
        if ":" in self.lib_id:
            try:
                from lib.symbols import get_default_symbols

                mgr = get_default_symbols()
                if mgr is not None:
                    lib, name = self.lib_id.split(":", 1)
                    symbol = mgr.get_symbol(lib, name)
                    if symbol is not None:
                        self.attach_symbol(symbol)
            except Exception:
                # Keep Part construction resilient; lookup errors are handled when
                # users actively query/resolve symbols.
                pass

    def attach_symbol(self, symbol_data: "SymbolData") -> None:
        """Bind a SymbolData to this part, enabling pin-name resolution and validation."""
        self._symbol_data = symbol_data

    @property
    def available_pins(self) -> list[str]:
        """Return all pin numbers and names from the attached symbol (deduplicated)."""
        if self._symbol_data is None:
            return []
        seen: list[str] = []
        for p in self._symbol_data.pins:
            if p.number not in seen:
                seen.append(p.number)
            if p.name and p.name != "~" and p.name not in seen:
                seen.append(p.name)
        return seen

    def pin(self, key: Union[str, int]) -> Pin:
        """Get or create a pin by number or name.

        If a SymbolData is attached (via attach_symbol), the key is resolved
        against pin numbers first, then pin names.  An unknown key raises
        PinNotFoundError.  Without attached SymbolData the original lazy-
        creation behaviour is preserved for backwards compatibility.
        """
        key_str = str(key)

        if self._symbol_data is not None:
            # Resolve key -> canonical pin number via SymbolData
            canonical_number = self._resolve_pin_key(key_str)
            if canonical_number in self._pins:
                return self._pins[canonical_number]
            ref = cast(str, self.ref)
            self._pins[canonical_number] = Pin(key=canonical_number, part_ref=ref)
            return self._pins[canonical_number]

        # Original behaviour: lazy creation without validation
        if key_str not in self._pins:
            ref = cast(str, self.ref)
            self._pins[key_str] = Pin(key=key_str, part_ref=ref)
        return self._pins[key_str]

    def _resolve_pin_key(self, key_str: str) -> str:
        """Resolve a pin key (number or name) to the canonical pin number.

        Raises PinNotFoundError if no matching pin is found.
        """
        assert self._symbol_data is not None
        # Pass 1: match by number
        for p in self._symbol_data.pins:
            if p.number == key_str:
                return p.number
        # Pass 2: match by name
        for p in self._symbol_data.pins:
            if p.name == key_str:
                return p.number
        available = self.available_pins
        raise PinNotFoundError(
            f"pin '{key_str}' not found on '{self.lib_id}'. "
            f"Available pins: {available}"
        )

    def set_style(self, style: Style) -> None:
        """Set the component style."""
        self._style = style

    def get_style(self) -> Style:
        """Get the component style (default if unset)."""
        if self._style is None:
            return DefaultPlacementStyle()
        return self._style

    @property
    def pins(self) -> dict[str, Pin]:
        """Get all pins for this part (read-only copy)."""
        return dict(self._pins)


class NetLabel(Part):
    """Single-pin special component that assigns a name to a net.

    A ``NetLabel`` is a positionable component with exactly one pin.
    When its pin is connected to other pins in the pin graph, the
    entire connected component is assigned this label's ``net_name``.

    This replaces the old ``LabelNet`` class.  Unlike ``LabelNet``,
    ``NetLabel`` is a real component (``Part`` subclass) that can be
    placed, positioned, and styled in the schematic.

    Render semantics
    ~~~~~~~~~~~~~~~~
    The renderer draws a **flag label** at the NetLabel's pin endpoint
    (similar to KiCad net-label flags).  No wire is drawn *to* the
    NetLabel component itself — only between the other (non-NetLabel)
    pins in the same net.

    Attributes:
        net_name:  The net name this label assigns (e.g. ``"VCC"``,
                   ``"GND"``).
        direction: Visual direction of the flag label.
                   One of ``"left"``, ``"right"``, ``"up"``, ``"down"``.
    """

    net_name: str
    direction: str

    def __init__(
        self,
        name: str,
        *,
        direction: str = "right",
        ref: Optional[str] = None,
    ) -> None:
        self.net_name = name
        self.direction = direction
        super().__init__(
            lib_id="power:NetLabel",
            ref=ref or f"#NL{next(_net_label_counter)}",
            value=name,
        )
        # Pre-create the single pin
        self.pin("1")

    @property
    def label_pin(self) -> Pin:
        """The single connection pin of this NetLabel."""
        return self.pin("1")


def parse_pins(part: "Part", pin_spec: str) -> list[Pin]:
    """Parse a space-separated pin specification string into a list of Pins.

    Each whitespace-delimited token is passed to part.pin(), so both pin
    numbers ("1 2") and pin names ("B C E") are supported, as are mixed
    specs ("B 2").

    Example:
        parse_pins(q1, 'B C E')  -> [Pin('1'), Pin('2'), Pin('3')]
        parse_pins(r1, '1 2')    -> [Pin('1'), Pin('2')]
    """
    return [part.pin(token) for token in pin_spec.split() if token]
