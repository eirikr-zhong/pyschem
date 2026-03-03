"""Net class — read-only derived result from the pin graph.

In the vNext architecture, ``Net`` is a **derived** object.  It is never
created directly by user code; instead it is produced by
:func:`~lib.core.connect.derive_nets` which walks the pin graph (connected
components of :class:`~lib.core.part.Pin` objects) and builds one ``Net``
per component.

The ``Net.name`` is determined by any :class:`~lib.core.part.NetLabel`
component whose pin participates in the connected component.  If no
``NetLabel`` is present the net receives an auto-generated anonymous name
(``_anonN``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lib.core.part import Pin


@dataclass
class Net:
    """Represents an electrical network (read-only, derived from pin graph).

    Attributes:
        name: Network name (e.g., "VIN", "VOUT", "GND", or "_anon1")
    """
    name: str
    _pins: list[Pin] = field(default_factory=list)

    @property
    def pins(self) -> list[Pin]:
        """Get all pins connected to this net (read-only copy)."""
        return list(self._pins)

    @property
    def pin_count(self) -> int:
        """Get the number of pins connected to this net."""
        return len(self._pins)
