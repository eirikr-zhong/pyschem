"""Minimal SVG canvas — supports line, polyline, circle, text.

Only standard SVG 1.1 primitives; no external dependencies.
"""

from __future__ import annotations

from typing import Sequence


class SvgCanvas:
    """Accumulates SVG elements and serialises to a complete SVG document.

    Coordinate system: x right, y down (standard SVG).

    All coordinates are in raw user-units; callers are responsible for
    choosing a sensible scale (e.g. 1 unit = 1 px).

    Usage::

        c = SvgCanvas(width=200, height=200)
        c.line(0, 0, 100, 100, stroke="black")
        c.text(50, 50, "Hello", font_size=12)
        svg_str = c.to_svg()
    """

    def __init__(
        self,
        width: float = 400,
        height: float = 300,
        *,
        background: str = "white",
    ) -> None:
        self._width = width
        self._height = height
        self._background = background
        self._elements: list[str] = []

    # ------------------------------------------------------------------
    # Primitive builders
    # ------------------------------------------------------------------

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = "black",
        stroke_width: float = 1.5,
        stroke_dasharray: str = "",
    ) -> None:
        """Draw a straight line segment."""
        extra = f' stroke-dasharray="{stroke_dasharray}"' if stroke_dasharray else ""
        self._elements.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"'
            f' stroke="{stroke}" stroke-width="{stroke_width}"{extra}/>'
        )

    def polyline(
        self,
        points: Sequence[tuple[float, float]],
        *,
        stroke: str = "black",
        stroke_width: float = 1.5,
        fill: str = "none",
    ) -> None:
        """Draw a connected sequence of line segments (open path)."""
        pts = " ".join(f"{x},{y}" for x, y in points)
        self._elements.append(
            f'<polyline points="{pts}"'
            f' stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}"/>'
        )

    def polygon(
        self,
        points: Sequence[tuple[float, float]],
        *,
        stroke: str = "black",
        stroke_width: float = 1.5,
        fill: str = "black",
    ) -> None:
        """Draw a closed polygon (solid fill by default — useful for arrowheads)."""
        pts = " ".join(f"{x},{y}" for x, y in points)
        self._elements.append(
            f'<polygon points="{pts}"'
            f' stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}"/>'
        )

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        *,
        stroke: str = "black",
        stroke_width: float = 1.5,
        fill: str = "none",
    ) -> None:
        """Draw a circle."""
        self._elements.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}"'
            f' stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}"/>'
        )

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        font_size: float = 11,
        font_family: str = "monospace",
        fill: str = "black",
        anchor: str = "middle",
        dominant_baseline: str = "middle",
    ) -> None:
        """Render text at (x, y)."""
        # Escape minimal XML special characters
        escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._elements.append(
            f'<text x="{x}" y="{y}"'
            f' font-size="{font_size}" font-family="{font_family}"'
            f' fill="{fill}" text-anchor="{anchor}"'
            f' dominant-baseline="{dominant_baseline}">{escaped}</text>'
        )

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        stroke: str = "none",
        stroke_width: float = 0,
        fill: str = "white",
        rx: float = 0,
    ) -> None:
        """Draw a rectangle."""
        rx_attr = f' rx="{rx}"' if rx else ""
        self._elements.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}"'
            f' stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}"{rx_attr}/>'
        )

    def group_start(self, transform: str = "") -> None:
        """Open a <g> group (for transforms)."""
        attr = f' transform="{transform}"' if transform else ""
        self._elements.append(f"<g{attr}>")

    def group_end(self) -> None:
        """Close a <g> group."""
        self._elements.append("</g>")

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_svg(self) -> str:
        """Return the complete SVG document as a string."""
        header = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg"'
            f' width="{self._width}" height="{self._height}"'
            f' viewBox="0 0 {self._width} {self._height}">\n'
        )
        if self._background and self._background != "none":
            header += (
                f'  <rect width="{self._width}" height="{self._height}"'
                f' fill="{self._background}"/>\n'
            )
        body = "\n".join(f"  {el}" for el in self._elements)
        return header + body + "\n</svg>\n"
