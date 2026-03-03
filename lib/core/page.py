"""Page / Canvas configuration for schematic export.

Supports ISO A-series paper sizes (A0–A4) and arbitrary custom dimensions.
All dimensions are stored in pixels at 96 dpi (SVG default resolution).

Default page when nothing is specified: **A1 portrait**.

ISO A-series dimensions at 96 dpi (1 inch = 25.4 mm):
    A0: 2384 × 3370 px
    A1: 1684 × 2384 px
    A2: 1191 × 1684 px
    A3:  842 × 1191 px
    A4:  595 ×  842 px

Usage::

    # Predefined paper size (portrait)
    cfg = PageConfig.a1()

    # Landscape variant
    cfg = PageConfig.a1(landscape=True)

    # Fully custom
    cfg = PageConfig(width=1920, height=1080)
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# ISO A-series at 96 dpi, portrait (width < height)
# Computed as: mm / 25.4 * 96, rounded to nearest integer.
# ---------------------------------------------------------------------------
_A_SIZES_PX: dict[str, tuple[int, int]] = {
    "A0": (2384, 3370),
    "A1": (1684, 2384),
    "A2": (1191, 1684),
    "A3": (842, 1191),
    "A4": (595, 842),
}


@dataclass
class PageConfig:
    """Canvas / page dimensions for SVG export.

    Attributes:
        width:  Canvas width in SVG user-units (pixels at 96 dpi).
        height: Canvas height in SVG user-units (pixels at 96 dpi).

    The default instance (from :meth:`default`) is **A1 portrait**
    (1684 × 2384 px).

    Layout notes
    ------------
    * Parts are auto-arranged in a horizontal row within the drawable area
      (canvas minus ``_MARGIN`` on each side) unless explicit ``Style.x/y``
      coordinates are set.
    * For schematics with many parts, prefer A0 or a custom landscape size so
      that parts have room to spread out.
    * When explicit ``Style.x/y`` coordinates (in mm) are used, the scale
      factor is 3.0 px/mm; make sure the resulting pixel coordinates fit
      within the chosen canvas.
    """

    width: float
    height: float

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "PageConfig":
        """Return the default page: **A1 portrait** (1684 × 2384 px)."""
        return cls.a1()

    @classmethod
    def a0(cls, *, landscape: bool = False) -> "PageConfig":
        """A0 paper at 96 dpi."""
        return cls._from_key("A0", landscape=landscape)

    @classmethod
    def a1(cls, *, landscape: bool = False) -> "PageConfig":
        """A1 paper at 96 dpi (default page)."""
        return cls._from_key("A1", landscape=landscape)

    @classmethod
    def a2(cls, *, landscape: bool = False) -> "PageConfig":
        """A2 paper at 96 dpi."""
        return cls._from_key("A2", landscape=landscape)

    @classmethod
    def a3(cls, *, landscape: bool = False) -> "PageConfig":
        """A3 paper at 96 dpi."""
        return cls._from_key("A3", landscape=landscape)

    @classmethod
    def a4(cls, *, landscape: bool = False) -> "PageConfig":
        """A4 paper at 96 dpi."""
        return cls._from_key("A4", landscape=landscape)

    @classmethod
    def from_paper(cls, size: str, *, landscape: bool = False) -> "PageConfig":
        """Create a :class:`PageConfig` from a paper-size string (case-insensitive).

        Args:
            size:      One of ``"A0"``–``"A4"`` (or lower-case).
            landscape: If ``True``, swap width and height.

        Raises:
            ValueError: Unknown paper size string.
        """
        key = size.upper()
        if key not in _A_SIZES_PX:
            raise ValueError(
                f"Unknown paper size '{size}'. "
                f"Supported: {', '.join(sorted(_A_SIZES_PX))}"
            )
        return cls._from_key(key, landscape=landscape)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _from_key(cls, key: str, *, landscape: bool) -> "PageConfig":
        w, h = _A_SIZES_PX[key]
        if landscape:
            w, h = h, w
        return cls(width=float(w), height=float(h))
