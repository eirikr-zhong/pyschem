"""Symbol data structures."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PinDefinition:
    """Represents a pin definition in a symbol.

    Attributes:
        number: Pin number (e.g., "1", "2", "A1")
        name: Pin name
        type: Pin type (e.g., "passive", "input", "output", "bidirectional")
        x: X position
        y: Y position
        orientation: Pin orientation (0, 90, 180, 270)
    """

    number: str
    name: str
    type: str
    x: float
    y: float
    orientation: int = 0
    length: float = 0.0


@dataclass
class SymbolPrimitive:
    """Represents a KiCad-like graphical primitive of a symbol body.

    The coordinate system is symbol-local (0, 0 at symbol centre by convention).
    Coordinates are pre-amplified at parse time to match renderer space.

    Attributes:
        kind: Primitive type, e.g. ``line``, ``polyline``, ``polygon``,
              ``circle``, ``arc``.
        points: Primitive points in symbol-local coordinates.
                - line: ``[(x1, y1), (x2, y2)]``
                - polyline/polygon: ordered vertex list
                - circle: ``[(cx, cy)]`` with ``radius``
                - arc: ``[(x_start, y_start), (x_mid, y_mid), (x_end, y_end)]``
        stroke_width: Stroke width (symbol units)
        fill: Fill mode, e.g. ``none``, ``background``, ``outline``, ``solid``.
        radius: Radius for circle primitives.
    """

    kind: str
    points: list[tuple[float, float]] = field(default_factory=list)
    stroke_width: float = 0.254
    fill: str = "none"
    radius: Optional[float] = None


@dataclass
class SymbolData:
    """Represents parsed symbol data from KiCad library.

    Attributes:
        name: Symbol name (e.g., "R", "C", "U1")
        lib: Library identifier (e.g., "Device")
        pins: List of pin definitions
        primitives: List of KiCad-like graphical primitives
        properties: Dict of parsed symbol properties (Description, Datasheet, etc.)
        bounding_box: Optional (min_x, min_y, max_x, max_y)
    """

    name: str
    lib: str
    pins: list[PinDefinition] = field(default_factory=list)
    primitives: list[SymbolPrimitive] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    bounding_box: Optional[tuple[float, float, float, float]] = None
