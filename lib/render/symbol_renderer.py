"""Unified symbol renderer based on ``SymbolData`` + KiCad-like primitives.

This module centralizes per-symbol drawing, pin-endpoint computation, and
symbol-body bounding boxes so schematic-level rendering no longer needs
symbol-specific branches.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lib.render.svg_renderer import SvgCanvas
from lib.symbols import get_default_symbols
from lib.symbols.data import PinDefinition, SymbolData, SymbolPrimitive

if TYPE_CHECKING:
    from lib.core.part import Part


@dataclass
class _DrawStyle:
    primitive_stroke: str = "#222"
    primitive_stroke_width: float = 1.8
    pin_stub_stroke: str = "#555"
    pin_stub_width: float = 1.5
    pin_text_fill: str = "#333"
    value_text_fill: str = "#555"


class SymbolRenderer:
    """Renders a symbol via ``SymbolData`` primitives and pin definitions."""

    def __init__(
        self,
        *,
        primitive_stroke: str = "#222",
        primitive_stroke_width: float = 1.8,
        pin_stub_stroke: str = "#555",
        pin_stub_width: float = 1.5,
        pin_text_fill: str = "#333",
        value_text_fill: str = "#555",
    ) -> None:
        self._style = _DrawStyle(
            primitive_stroke=primitive_stroke,
            primitive_stroke_width=primitive_stroke_width,
            pin_stub_stroke=pin_stub_stroke,
            pin_stub_width=pin_stub_width,
            pin_text_fill=pin_text_fill,
            value_text_fill=value_text_fill,
        )

    # ------------------------------------------------------------------
    # Public API used by schematic renderer
    # ------------------------------------------------------------------

    def can_render(self, part: "Part", symbol_name: str) -> bool:
        sd = self._resolve_symbol_data(part, symbol_name)
        return sd is not None and (len(sd.primitives) > 0 or len(sd.pins) > 0)

    def render_part(
        self,
        canvas: SvgCanvas,
        part: "Part",
        cx: float,
        cy: float,
        *,
        symbol_name: str,
        rotation: int = 0,
        font_ref: float = 14,
        font_value: float = 11,
        font_pin: float = 10,
    ) -> bool:
        """Render *part*; return True when symbol path is used."""
        symbol = self._resolve_symbol_data(part, symbol_name)
        if symbol is None:
            return False
        if not symbol.primitives and not symbol.pins:
            return False

        if rotation % 360:
            canvas.group_start(f"rotate({-rotation},{cx:.3f},{cy:.3f})")

        for primitive in symbol.primitives:
            self._draw_primitive(canvas, primitive, cx, cy)

        for pin in symbol.pins:
            self._draw_pin_stub_and_label(canvas, pin, cx, cy, font_pin=font_pin)

        _, _, max_x, _ = self._symbol_body_bbox(symbol) or (-20.0, -20.0, 20.0, 20.0)
        ref = part.ref or ""
        value = part.value or ""
        if ref:
            canvas.text(
                cx + max_x + 4.0,
                cy - 8.0,
                ref,
                font_size=font_ref,
                anchor="start",
                dominant_baseline="middle",
            )
        if value:
            canvas.text(
                cx + max_x + 4.0,
                cy + 8.0,
                value,
                font_size=font_value,
                fill=self._style.value_text_fill,
                anchor="start",
                dominant_baseline="middle",
            )

        if rotation % 360:
            canvas.group_end()

        return True

    def pin_endpoints(
        self,
        part: "Part",
        cx: float,
        cy: float,
        *,
        symbol_name: str,
        rotation: int = 0,
    ) -> dict[tuple[str, str], tuple[float, float]]:
        """Return wire-connection endpoints for existing ``part.pins`` keys."""
        symbol = self._resolve_symbol_data(part, symbol_name)
        if symbol is None:
            return {}

        endpoint_by_alias: dict[str, tuple[float, float]] = {}
        for pin in symbol.pins:
            px, py = self._pin_endpoint_local(pin)
            endpoint_by_alias[pin.number] = (px, py)
            if pin.name and pin.name != "~":
                endpoint_by_alias[pin.name] = (px, py)

        ref = part.ref or "?"
        result: dict[tuple[str, str], tuple[float, float]] = {}
        for pin_key in part.pins:
            if pin_key not in endpoint_by_alias:
                continue
            lx, ly = endpoint_by_alias[pin_key]
            wx, wy = self._to_world_point(lx, ly, cx, cy, rotation)
            result[(ref, pin_key)] = (wx, wy)
        return result

    def component_bbox(
        self,
        part: "Part",
        cx: float,
        cy: float,
        *,
        symbol_name: str,
        rotation: int = 0,
    ) -> tuple[float, float, float, float] | None:
        """Return world-space AABB of the symbol body for obstacle routing."""
        symbol = self._resolve_symbol_data(part, symbol_name)
        if symbol is None:
            return None

        raw = self._symbol_body_bbox(symbol)
        if raw is None:
            return None

        x0, y0, x1, y1 = raw
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        world = [self._to_world_point(x, y, cx, cy, rotation) for x, y in corners]
        xs = [p[0] for p in world]
        ys = [p[1] for p in world]
        return (min(xs), min(ys), max(xs), max(ys))

    # ------------------------------------------------------------------
    # Symbol resolution
    # ------------------------------------------------------------------

    def _resolve_symbol_data(self, part: "Part", symbol_name: str) -> SymbolData | None:
        attached: SymbolData | None = getattr(part, "_symbol_data", None)
        if attached is not None:
            return attached
        lib_id = getattr(part, "lib_id", "") or ""
        if ":" not in lib_id:
            return None
        lib, name_from_lib_id = lib_id.split(":", 1)
        if not lib or not name_from_lib_id:
            return None
        symbols = get_default_symbols()
        if symbols is None:
            return None
        resolved = symbols.get_symbol(lib, name_from_lib_id)
        if resolved is not None:
            return resolved
        if symbol_name and symbol_name != name_from_lib_id:
            return symbols.get_symbol(lib, symbol_name)
        return None

    # ------------------------------------------------------------------
    # Primitive rendering
    # ------------------------------------------------------------------

    def _draw_primitive(self, canvas: SvgCanvas, primitive: SymbolPrimitive, cx: float, cy: float) -> None:
        stroke_width = (
            primitive.stroke_width
            if primitive.stroke_width > 0
            else self._style.primitive_stroke_width
        )
        stroke = self._style.primitive_stroke
        fill = self._primitive_fill(primitive.fill)
        kind = primitive.kind.lower()

        if kind == "line" and len(primitive.points) >= 2:
            (x1, y1), (x2, y2) = primitive.points[0], primitive.points[1]
            canvas.line(cx + x1, cy + y1, cx + x2, cy + y2, stroke=stroke, stroke_width=stroke_width)
            return

        if kind in {"polyline", "polygon"} and len(primitive.points) >= 2:
            points = [(cx + x, cy + y) for x, y in primitive.points]
            is_closed = kind == "polygon" or (points[0] == points[-1])
            if is_closed:
                canvas.polygon(points, stroke=stroke, stroke_width=stroke_width, fill=fill)
            else:
                canvas.polyline(points, stroke=stroke, stroke_width=stroke_width, fill="none")
            return

        if kind == "circle" and primitive.points and primitive.radius is not None:
            cx0, cy0 = primitive.points[0]
            canvas.circle(
                cx + cx0,
                cy + cy0,
                primitive.radius,
                stroke=stroke,
                stroke_width=stroke_width,
                fill=fill,
            )
            return

        if kind == "arc" and len(primitive.points) >= 3:
            (sx, sy), (mx, my), (ex, ey) = primitive.points[0:3]
            d = (
                f"M {cx + sx:.3f} {cy + sy:.3f} "
                f"Q {cx + mx:.3f} {cy + my:.3f} {cx + ex:.3f} {cy + ey:.3f}"
            )
            canvas._elements.append(
                f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}"/>'
            )
            track = getattr(canvas, "_track", None)
            if callable(track):
                track(cx + sx, cy + sy)
                track(cx + mx, cy + my)
                track(cx + ex, cy + ey)

    def _draw_pin_stub_and_label(
        self,
        canvas: SvgCanvas,
        pin: PinDefinition,
        cx: float,
        cy: float,
        *,
        font_pin: float,
    ) -> None:
        root_x, root_y = pin.x, pin.y
        end_x, end_y = self._pin_endpoint_local(pin)

        if abs(root_x - end_x) > 0.01 or abs(root_y - end_y) > 0.01:
            canvas.line(
                cx + root_x,
                cy + root_y,
                cx + end_x,
                cy + end_y,
                stroke=self._style.pin_stub_stroke,
                stroke_width=self._style.pin_stub_width,
            )

        label = pin.name if pin.name and pin.name != "~" else pin.number
        if not label or label == "~":
            return

        tx, ty, anchor = self._pin_label_position(pin, end_x, end_y)
        canvas.text(
            cx + tx,
            cy + ty,
            label,
            font_size=font_pin,
            fill=self._style.pin_text_fill,
            anchor=anchor,
            dominant_baseline="middle",
        )

    def _pin_label_position(
        self, pin: PinDefinition, end_x: float, end_y: float
    ) -> tuple[float, float, str]:
        offset = 8.0
        orientation = pin.orientation % 360
        if orientation == 180:
            return (end_x - offset, end_y, "end")
        if orientation == 0:
            return (end_x + offset, end_y, "start")
        if orientation == 90:
            return (end_x, end_y - offset, "middle")
        if orientation == 270:
            return (end_x, end_y + offset, "middle")
        if end_x < 0:
            return (end_x - offset, end_y, "end")
        return (end_x + offset, end_y, "start")

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _symbol_body_bbox(self, symbol: SymbolData) -> tuple[float, float, float, float] | None:
        if symbol.bounding_box is not None:
            return symbol.bounding_box

        xs: list[float] = []
        ys: list[float] = []

        for primitive in symbol.primitives:
            kind = primitive.kind.lower()
            if kind == "circle" and primitive.points and primitive.radius is not None:
                cx0, cy0 = primitive.points[0]
                r = primitive.radius
                xs.extend([cx0 - r, cx0 + r])
                ys.extend([cy0 - r, cy0 + r])
            else:
                for x, y in primitive.points:
                    xs.append(x)
                    ys.append(y)

        for pin in symbol.pins:
            xs.append(pin.x)
            ys.append(pin.y)
            px, py = self._pin_endpoint_local(pin)
            xs.append(px)
            ys.append(py)

        if not xs or not ys:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _pin_endpoint_local(pin: PinDefinition) -> tuple[float, float]:
        if pin.length <= 0:
            return (pin.x, pin.y)

        orientation = pin.orientation % 360
        if orientation == 0:
            return (pin.x - pin.length, pin.y)
        if orientation == 180:
            return (pin.x + pin.length, pin.y)
        if orientation == 90:
            return (pin.x, pin.y + pin.length)
        if orientation == 270:
            return (pin.x, pin.y - pin.length)
        rad = math.radians(orientation)
        return (
            pin.x - pin.length * math.cos(rad),
            pin.y + pin.length * math.sin(rad),
        )

    @staticmethod
    def _to_world_point(
        lx: float,
        ly: float,
        cx: float,
        cy: float,
        rotation: int,
    ) -> tuple[float, float]:
        if rotation % 360 == 0:
            return (cx + lx, cy + ly)
        rad = math.radians(-rotation)
        return (
            cx + lx * math.cos(rad) - ly * math.sin(rad),
            cy + lx * math.sin(rad) + ly * math.cos(rad),
        )

    @staticmethod
    def _primitive_fill(fill_mode: str) -> str:
        mode = (fill_mode or "none").lower()
        if mode in {"background", "bg"}:
            return "white"
        if mode in {"solid", "outline", "foreground"}:
            return "black"
        return "none"
