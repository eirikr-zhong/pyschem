"""Unified symbol renderer based on ``SymbolData`` + KiCad-like primitives.

This module centralizes per-symbol drawing, pin-endpoint computation, and
symbol-body bounding boxes so schematic-level rendering no longer needs
symbol-specific branches.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from lib.core.render_style import TextPlacementStyle
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
    ref_text: TextPlacementStyle = field(default_factory=TextPlacementStyle.default_ref)
    value_text: TextPlacementStyle = field(default_factory=TextPlacementStyle.default_value)
    pin_name_visible: bool = True
    pin_value_visible: bool = True


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
        ref_text_style: TextPlacementStyle | None = None,
        value_text_style: TextPlacementStyle | None = None,
        pin_name_visible: bool = True,
        pin_value_visible: bool = True,
    ) -> None:
        ref_default = TextPlacementStyle.default_ref()
        value_default = TextPlacementStyle.default_value()
        self._style = _DrawStyle(
            primitive_stroke=primitive_stroke,
            primitive_stroke_width=primitive_stroke_width,
            pin_stub_stroke=pin_stub_stroke,
            pin_stub_width=pin_stub_width,
            pin_text_fill=pin_text_fill,
            value_text_fill=value_text_fill,
            ref_text=(
                ref_default.merge(ref_text_style)
                if ref_text_style is not None
                else ref_default
            ),
            value_text=(
                value_default.merge(value_text_style)
                if value_text_style is not None
                else value_default
            ),
            pin_name_visible=bool(pin_name_visible),
            pin_value_visible=bool(pin_value_visible),
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

        rotation_norm = rotation % 360
        if rotation_norm:
            canvas.group_start(f"rotate({-rotation},{cx:.3f},{cy:.3f})")

        for primitive in symbol.primitives:
            self._draw_primitive(canvas, primitive, cx, cy)

        for pin in symbol.pins:
            self._draw_pin_stub_and_label(canvas, pin, cx, cy, font_pin=font_pin)

        bbox = self._symbol_body_bbox(symbol) or (-20.0, -20.0, 20.0, 20.0)
        ref = part.ref or ""
        value = part.value or ""

        if rotation_norm:
            canvas.group_end()

        if ref and self.text_visible(self._style.ref_text, TextPlacementStyle.default_ref()):
            ref_x, ref_y, ref_anchor = self.text_position(
                cx=cx,
                cy=cy,
                bbox=bbox,
                placement=self._style.ref_text,
                default_placement=TextPlacementStyle.default_ref(),
                rotation=rotation,
            )
            canvas.text(
                ref_x,
                ref_y,
                ref,
                font_size=font_ref,
                anchor=ref_anchor,
                dominant_baseline="middle",
            )
        if value and self.text_visible(self._style.value_text, TextPlacementStyle.default_value()):
            value_x, value_y, value_anchor = self.text_position(
                cx=cx,
                cy=cy,
                bbox=bbox,
                placement=self._style.value_text,
                default_placement=TextPlacementStyle.default_value(),
                rotation=rotation,
            )
            canvas.text(
                value_x,
                value_y,
                value,
                font_size=font_value,
                fill=self._style.value_text_fill,
                anchor=value_anchor,
                dominant_baseline="middle",
            )

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
        # Build reverse mapping: name → number and number → name
        name_to_number: dict[str, str] = {}
        number_to_name: dict[str, str] = {}
        for pin in symbol.pins:
            if pin.name and pin.name != "~":
                name_to_number[pin.name] = pin.number
                number_to_name[pin.number] = pin.name

        for pin_key in part.pins:
            if pin_key not in endpoint_by_alias:
                continue
            lx, ly = endpoint_by_alias[pin_key]
            wx, wy = self._to_world_point(lx, ly, cx, cy, rotation)
            result[(ref, pin_key)] = (wx, wy)
            # Also emit the complementary key (number↔name) so callers
            # can look up by either identifier.
            if pin_key in name_to_number:
                alt = name_to_number[pin_key]
                if (ref, alt) not in result:
                    result[(ref, alt)] = (wx, wy)
            elif pin_key in number_to_name:
                alt = number_to_name[pin_key]
                if (ref, alt) not in result:
                    result[(ref, alt)] = (wx, wy)
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
            canvas.line(
                cx + x1,
                cy + y1,
                cx + x2,
                cy + y2,
                stroke=stroke,
                stroke_width=stroke_width,
            )
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
        end_x, end_y = self._pin_endpoint_local(pin)
        root_x, root_y = self._pin_stub_inner_local(pin)

        if abs(root_x - end_x) > 0.01 or abs(root_y - end_y) > 0.01:
            canvas.line(
                cx + root_x,
                cy + root_y,
                cx + end_x,
                cy + end_y,
                stroke=self._style.pin_stub_stroke,
                stroke_width=self._style.pin_stub_width,
            )

        pin_name = pin.name if pin.name and pin.name != "~" else ""
        pin_value = pin.number if pin.number and pin.number != "~" else ""
        if self._style.pin_name_visible and pin_name:
            label = pin_name
        elif self._style.pin_value_visible and pin_value:
            label = pin_value
        else:
            label = ""
        if not label or label == "~":
            return

        tx, ty, anchor = self._pin_label_position(
            pin,
            end_x,
            end_y,
            root_x,
            root_y,
            font_pin=font_pin,
        )
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
        self,
        pin: PinDefinition,
        end_x: float,
        end_y: float,
        root_x: float,
        root_y: float,
        *,
        font_pin: float = 10.0,
    ) -> tuple[float, float, str]:
        offset = max(8.0, font_pin * 0.8)
        dx = end_x - root_x
        dy = end_y - root_y
        length = math.hypot(dx, dy)

        if length > 0.01:
            ux = dx / length
            uy = dy / length
        else:
            orientation = pin.orientation % 360
            rad = math.radians(orientation)
            ux = -math.cos(rad)
            uy = -math.sin(rad)

        tx = end_x + ux * offset
        ty = end_y + uy * offset

        if abs(ux) >= max(0.35, abs(uy)):
            anchor = "start" if ux > 0 else "end"
        else:
            anchor = "middle"
        return (tx, ty, anchor)

    @staticmethod
    def _normalized_position(
        position: str | None,
        *,
        fallback: str,
    ) -> str:
        raw = (fallback if position is None else position).strip().lower()
        if raw in {"top", "bottom", "left", "right", "center"}:
            return raw
        return fallback

    @staticmethod
    def _normalized_rotation_mode(
        mode: str | None,
        *,
        fallback: str,
    ) -> str:
        raw = (fallback if mode is None else mode).strip().lower()
        if raw in {"component", "screen"}:
            return raw
        return fallback

    @staticmethod
    def _resolved_offset(
        offset: float | None,
        *,
        fallback: float,
    ) -> float:
        return fallback if offset is None else float(offset)

    @staticmethod
    def text_visible(placement: TextPlacementStyle, default_placement: TextPlacementStyle) -> bool:
        if placement.visible is None:
            return bool(default_placement.visible)
        return bool(placement.visible)

    @classmethod
    def text_position(
        cls,
        *,
        cx: float,
        cy: float,
        bbox: tuple[float, float, float, float],
        placement: TextPlacementStyle,
        default_placement: TextPlacementStyle,
        rotation: int = 0,
    ) -> tuple[float, float, str]:
        """Return world-space ``(x, y, anchor)`` for a text placement style."""
        fallback_position = cls._normalized_position(default_placement.position, fallback="right")
        fallback_mode = cls._normalized_rotation_mode(
            default_placement.rotation_mode,
            fallback="component",
        )
        fallback_offset = float(default_placement.offset if default_placement.offset is not None else 0.0)

        position = cls._normalized_position(placement.position, fallback=fallback_position)
        mode = cls._normalized_rotation_mode(placement.rotation_mode, fallback=fallback_mode)
        offset = cls._resolved_offset(placement.offset, fallback=fallback_offset)

        x0, y0, x1, y1 = bbox
        mid_x = (x0 + x1) / 2.0
        mid_y = (y0 + y1) / 2.0
        if position == "top":
            lx, ly = mid_x, y0 - offset
            dx, dy = 0.0, -1.0
        elif position == "bottom":
            lx, ly = mid_x, y1 + offset
            dx, dy = 0.0, 1.0
        elif position == "left":
            lx, ly = x0 - offset, mid_y
            dx, dy = -1.0, 0.0
        elif position == "center":
            lx, ly = mid_x, mid_y
            dx, dy = 0.0, 0.0
        else:
            lx, ly = x1 + offset, mid_y
            dx, dy = 1.0, 0.0

        if mode == "component":
            wx, wy = cls._to_world_point(lx, ly, cx, cy, rotation)
            wdx, wdy = cls._rotated_vector(dx, dy, rotation=rotation)
        else:
            wx, wy = cx + lx, cy + ly
            wdx, wdy = dx, dy

        if abs(wdx) > abs(wdy):
            anchor = "start" if wdx > 0 else "end"
        else:
            anchor = "middle"
        return (wx, wy, anchor)

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rotated_vector(dx: float, dy: float, *, rotation: int) -> tuple[float, float]:
        rad = math.radians(-rotation % 360)
        c = math.cos(rad)
        s = math.sin(rad)
        return (dx * c - dy * s, dx * s + dy * c)

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
            outer_x, outer_y = self._pin_endpoint_local(pin)
            inner_x, inner_y = self._pin_stub_inner_local(pin)
            xs.extend([outer_x, inner_x])
            ys.extend([outer_y, inner_y])

        if not xs or not ys:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _pin_endpoint_local(pin: PinDefinition) -> tuple[float, float]:
        """Return the electrical connection point (outer pin endpoint)."""
        return (pin.x, pin.y)

    @staticmethod
    def _pin_stub_inner_local(pin: PinDefinition) -> tuple[float, float]:
        """Return the symbol-body side endpoint of the drawn pin stub."""
        if pin.length <= 0:
            return (pin.x, pin.y)

        orientation = pin.orientation % 360
        lx = pin.length
        px = pin.x
        py = pin.y
        rad = math.radians(orientation)
        return (
            px + lx * math.cos(rad),
            py + lx * math.sin(rad),
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

    def _primitive_fill(self, fill_mode: str) -> str:
        mode = (fill_mode or "none").lower()
        if mode in {"background", "bg"}:
            return "white"
        if mode in {"solid", "outline", "foreground"}:
            return self._style.primitive_stroke
        return "none"
