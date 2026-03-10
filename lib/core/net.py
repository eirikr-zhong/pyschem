"""Net class — read-only derived result from the pin graph.

In the vNext architecture, ``Net`` is a **derived** object.  It is never
created directly by user code; instead it is produced by
:func:`~lib.core.connect.derive_nets` which walks the pin graph (connected
components of :class:`~lib.core.part.Pin` objects) and builds one ``Net``
per component.

The ``Net.name`` is determined by any :class:`~lib.core.net.NetLabel`
component whose pin participates in the connected component.  If no
``NetLabel`` is present the net receives an auto-generated anonymous name
(``_anonN``).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

from lib.core.part import Part, Pin
from lib.core.render_style import TextPlacementStyle
from lib.core.style import Style

if TYPE_CHECKING:
    from lib.symbols.data import SymbolData


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


# Counter for auto-generated NetLabel refs.
_net_label_counter = itertools.count(1)

# Counter for auto-generated GroundNet refs.
_groundnet_counter = itertools.count(1)


@lru_cache(maxsize=1)
def _default_groundnet_symbol_data() -> "SymbolData":
    """Return built-in SymbolData for ``GroundNet``.

    Pin placement mirrors NetLabel: the wire connection point is at (-stem, 0)
    with orientation 0 and length = stem, so the pin stub draws from the
    connection point rightward to the origin.

    The ground symbol (three bars of decreasing width) extends rightward from
    the origin.  When direction="bottom" (the default for GroundNet), the
    renderer rotates the symbol so the bars point downward — the standard
    ground symbol orientation.
    """
    from lib.symbols.data import PinDefinition, SymbolData, SymbolPrimitive

    stem = 15.24
    return SymbolData(
        name="GroundNet",
        lib="GroundNet",
        pins=[
            PinDefinition(
                number="1",
                name="~",
                type="passive",
                x=-stem,
                y=0.0,
                orientation=0,
                length=stem,
            ),
        ],
        primitives=[
            # Wide bar
            SymbolPrimitive(
                kind="line",
                points=[(2.0, -8.0), (2.0, 8.0)],
                stroke_width=1.4,
            ),
            # Medium bar
            SymbolPrimitive(
                kind="line",
                points=[(6.0, -5.0), (6.0, 5.0)],
                stroke_width=1.4,
            ),
            # Narrow bar
            SymbolPrimitive(
                kind="line",
                points=[(10.0, -2.0), (10.0, 2.0)],
                stroke_width=1.4,
            ),
        ],
    )


@lru_cache(maxsize=1)
def _default_netlabel_symbol_data() -> "SymbolData":
    """Return built-in SymbolData fallback for ``NetLabel``.

    This keeps NetLabel rendering available even when external symbol
    libraries are not configured.
    """
    from lib.symbols.data import PinDefinition, SymbolData, SymbolPrimitive

    # Pin is placed at the stem outer end (wire connection point).
    # The flag polygon is shifted right by stem length (15.24) so that
    # the flag tip aligns with the origin and no special-case logic is
    # needed in the renderer — pin_endpoint_local() naturally returns the
    # correct wire connection point.
    stem = 15.24
    return SymbolData(
        name="NetLabel",
        lib="NetLabel",
        pins=[
            PinDefinition(
                number="1",
                name="~",
                type="passive",
                x=-stem,
                y=0.0,
                orientation=0,
                length=stem,
            ),
        ],
        primitives=[
            SymbolPrimitive(
                kind="polygon",
                points=[
                    (0.0, 0.0),
                    (8.0, -6.0),
                    (34.0, -6.0),
                    (34.0, 6.0),
                    (8.0, 6.0),
                    (0.0, 0.0),
                ],
                stroke_width=1.2,
                fill="background",
            ),
        ],
        # Explicitly set bbox to the polygon body only (excluding pin stem),
        # so text_position(position="center") lands in the visual center of
        # the flag body at (21, 0) rather than being skewed by the pin.
        bounding_box=(8.0, -6.0, 34.0, 6.0),
    )


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
    ``NetLabel`` now renders through the standard symbol pipeline like
    any other :class:`Part`.

    Attributes:
        net_name:  The net name this label assigns (e.g. ``"VCC"``,
                   ``"GND"``).
        direction: Visual direction of the flag label.
                   One of ``"left"``, ``"right"``, ``"top"``, ``"bottom"``.
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
            lib_id="NetLabel:NetLabel",
            ref=ref or f"#NL{next(_net_label_counter)}",
            value=name,
        )
        if self._symbol_data is None:
            try:
                from lib.symbols import get_default_symbols

                symbols = get_default_symbols()
                if symbols is not None:
                    from_library = symbols.get_symbol("net_labels", "NetLabel")
                    if from_library is not None:
                        self.attach_symbol(from_library)
            except Exception:
                pass
        if self._symbol_data is None:
            self.attach_symbol(_default_netlabel_symbol_data())
        # Pre-create the single pin.
        self.pin("1")
        # Hide ref text by default; NetLabel is primarily a net-name marker.
        # Users can override by calling set_style(Style(ref_text=TextPlacementStyle(visible=True))).
        self.set_style(Style(ref_text=TextPlacementStyle(visible=False)))

    @property
    def label_pin(self) -> Pin:
        """The single connection pin of this NetLabel."""
        return self.pins["1"]


class GroundNet(NetLabel):
    """Ground net label — renders a standard ground symbol.

    Inherits from ``NetLabel`` so the existing renderer handles it without
    modification.  The default net name is ``"GND"`` and the default
    direction is ``"bottom"``.
    """

    def __init__(
        self,
        name: str = "GND",
        *,
        direction: str = "bottom",
        ref: Optional[str] = None,
    ) -> None:
        # Use our own counter to avoid colliding with NetLabel refs.
        actual_ref = ref or f"#GND{next(_groundnet_counter)}"
        # Temporarily bypass NetLabel.__init__ symbol resolution —
        # we call super().__init__ then override the symbol data.
        super().__init__(name, direction=direction, ref=actual_ref)
        # Always attach ground symbol data (overrides NetLabel flag).
        self.attach_symbol(_default_groundnet_symbol_data())
