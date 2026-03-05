"""Junction component used as a pure tee-point marker in schematics."""

from __future__ import annotations

from typing import Optional

from lib.core.part import Part, Pin


class Junction(Part):
    """Single-pin topology/graphics tee point for explicit wire branch joins."""

    def __init__(self, *, ref: Optional[str] = None) -> None:
        super().__init__(lib_id="power:Junction", ref=ref)
        self.pin("1")

    @property
    def junction_pin(self) -> Pin:
        """The single connection pin for this junction marker."""
        return self.pin("1")
