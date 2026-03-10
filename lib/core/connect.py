"""Pin-graph connection API and net derivation.

vNext Design
------------
Connections are stored as bidirectional edges on :class:`~lib.core.part.Pin`
objects (the **pin graph**).  The single entry point for wiring is
:func:`connect`, which delegates to :meth:`Pin.connect`.

Nets are **derived** from the pin graph by :func:`derive_nets`, which
performs a BFS over all pins in a schematic and groups them into connected
components.  Each component becomes a :class:`~lib.core.net.Net`.  If the
component contains a :class:`~lib.core.net.NetLabel` pin, the net takes
that label's name; otherwise it receives an auto-generated ``_anonN`` name.

Thread-safety
~~~~~~~~~~~~~
The pin graph is **not** thread-safe; schematics are expected to be
constructed in a single thread.
"""

from __future__ import annotations

from typing import Union

from lib.core.net import Net, NetLabel
from lib.core.part import Part, Pin

# Sentinel prefix for auto-generated anonymous net names.
_ANON_PREFIX = "_anon"


def connect(*pins: Pin) -> None:
    """Connect pins together in the pin graph.

    This is the primary public API for wiring components together.

    Examples::

        from lib.core.connect import connect
        from lib.core.net import NetLabel
        from lib.core.part import Part

        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")

        # Pin ↔ Pin  (anonymous connection)
        connect(r1.pin(1), r2.pin(2))

        # Pin ↔ NetLabel  (named net)
        vcc = NetLabel("VCC")
        connect(r1.pin(1), vcc.pin(1))

    Args:
        *pins: Two or more :class:`~lib.core.part.Pin` objects to connect.

    Raises:
        ValueError: If fewer than two pins are provided.
        TypeError: If an item is not a ``Pin``.
    """
    if len(pins) < 2:
        raise ValueError("connect() requires at least two pins")

    for item in pins:
        if not isinstance(item, Pin):
            raise TypeError(
                f"connect() accepts Pin objects, got {type(item).__name__}"
            )

    first = pins[0]
    for other in pins[1:]:
        first.connect(other)


def derive_nets(parts: list[Part]) -> list[Net]:
    """Derive nets from the pin graph (connected components).

    Algorithm:
    1. Collect all pins from all parts.
    2. BFS to find connected components in the pin graph.
    3. For each component, look for :class:`NetLabel` parts to determine
       the net name.  Multiple ``NetLabel`` objects with the **same** name
       in one component are fine; conflicting names are an ERC concern
       (not resolved here — the first name found wins).
    4. Components with no ``NetLabel`` receive an anonymous name.
    5. The resulting :class:`Net` contains only non-NetLabel pins (real
       component pins).  NetLabel pins are used for naming only.

    Args:
        parts: All parts in the schematic (including NetLabel instances).

    Returns:
        A list of :class:`Net` objects, one per connected component that
        has at least one real pin or a net name.
    """
    # Build pin → Part lookup
    pin_to_part: dict[int, Part] = {}
    all_pins: list[Pin] = []
    for part in parts:
        for pin in part.pins.values():
            pin_to_part[id(pin)] = part
            all_pins.append(pin)

    visited: set[int] = set()
    nets: list[Net] = []
    anon_counter = 0

    for pin in all_pins:
        if id(pin) in visited:
            continue

        # BFS to find connected component
        component: list[Pin] = []
        queue: list[Pin] = [pin]
        while queue:
            p = queue.pop(0)
            if id(p) in visited:
                continue
            visited.add(id(p))
            component.append(p)
            for neighbor in p.connected_pins:
                if id(neighbor) not in visited:
                    queue.append(neighbor)

        # Determine net name from NetLabel parts in this component
        net_name: str | None = None
        for p in component:
            owner = pin_to_part.get(id(p))
            if isinstance(owner, NetLabel):
                net_name = owner.net_name
                break  # first NetLabel wins

        # Collect real (non-NetLabel) pins
        real_pins: list[Pin] = []
        for p in component:
            owner = pin_to_part.get(id(p))
            if not isinstance(owner, NetLabel):
                real_pins.append(p)

        # Skip isolated single pins with no name (unconnected pins)
        if not real_pins and net_name is None:
            continue
        # Skip single unconnected pin with no connections
        if len(component) == 1 and not pin.is_connected and net_name is None:
            continue

        if net_name is None:
            anon_counter += 1
            net_name = f"{_ANON_PREFIX}{anon_counter}"

        if real_pins or net_name:
            nets.append(Net(name=net_name, _pins=real_pins))

    return nets


def _find_net_labels(parts: list[Part]) -> list[NetLabel]:
    """Return all NetLabel instances from a parts list."""
    return [p for p in parts if isinstance(p, NetLabel)]
