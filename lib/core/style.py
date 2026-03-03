"""Style dataclass for positioning fields."""

from dataclasses import dataclass
from typing import Optional

from lib.errors import StyleValidationError

VALID_ROTATIONS = {0, 90, 180, 270}
VALID_ANCHORS = {"center", "left", "right", "top", "bottom"}


@dataclass
class Style:
    """Style object for component positioning.

    Currently only supports positioning fields:
    - x, y: absolute coordinates in mm
    - anchor: anchor point (center/left/right/top/bottom)
    - rotation: rotation angle (0/90/180/270)
    - locked: whether position is fixed
    - z_index: z-order (reserved for future use)
    """

    x: Optional[float] = None
    y: Optional[float] = None
    anchor: str = "center"
    rotation: int = 0
    locked: bool = False
    z_index: int = 0

    def __post_init__(self) -> None:
        """Validate style fields after initialization."""
        # Validate rotation
        if not isinstance(self.rotation, int):
            raise StyleValidationError(
                f"rotation must be an integer, got {type(self.rotation).__name__}"
            )
        if self.rotation not in VALID_ROTATIONS:
            raise StyleValidationError(
                f"rotation must be one of {sorted(VALID_ROTATIONS)}, got {self.rotation}"
            )

        # Validate anchor
        if not isinstance(self.anchor, str):
            raise StyleValidationError(
                f"anchor must be a string, got {type(self.anchor).__name__}"
            )
        if self.anchor not in VALID_ANCHORS:
            raise StyleValidationError(
                f"anchor must be one of {sorted(VALID_ANCHORS)}, got {self.anchor}"
            )

        # Validate locked
        if not isinstance(self.locked, bool):
            raise StyleValidationError(
                f"locked must be a boolean, got {type(self.locked).__name__}"
            )

        # Validate z_index
        if not isinstance(self.z_index, int):
            raise StyleValidationError(
                f"z_index must be an integer, got {type(self.z_index).__name__}"
            )

        # Validate x and y (must be float or None)
        if self.x is not None and not isinstance(self.x, (int, float)):
            raise StyleValidationError(
                f"x must be a number or None, got {type(self.x).__name__}"
            )
        if self.y is not None and not isinstance(self.y, (int, float)):
            raise StyleValidationError(
                f"y must be a number or None, got {type(self.y).__name__}"
            )


def DefaultPlacementStyle() -> Style:
    """Return default placement style.

    This is used when a Part has no explicit style set.
    """
    return Style(
        x=None,
        y=None,
        anchor="center",
        rotation=0,
        locked=False,
        z_index=0,
    )
