"""Schematic-level SVG renderer.

Renders each Part in the schematic. Components resolve their symbols from
KiCad libraries; unresolved symbols are shown as a red dashed placeholder.

Layout strategy (netlistsvg-inspired)
--------------------------------------
Parts without explicit Style(x, y) are placed using a **column-based
left-to-right auto-layout**, inspired by ELK's layered algorithm used in
netlistsvg:

1. Parts are sorted into columns (layers) based on their index.  Each
   column has its parts stacked vertically with equal spacing, and columns
   are arranged horizontally with a fixed gap.
2. Parts with explicit Style positions are placed exactly as specified.

This gives a compact, readable layout that avoids the wide empty rows of
the previous flat horizontal approach.

Wire / net routing
------------------
After all symbols are drawn, the renderer routes **wires** for each net:
every pin in the net has a known endpoint (px, py).  The router connects
all endpoints of a net with a Manhattan L-route tree:

1. For a 2-pin net the route is a single orthogonal L.  The bend direction
   is chosen to avoid component bounding boxes (H-first and V-first are
   both evaluated; the first collision-free option is used).  If both
   single-bend routes are blocked a simple 3-segment detour is generated
   that routes around the obstacle.
2. For a 3+-pin net the router picks the **median x** as a vertical trunk
   (shifted away from obstacles if needed) and runs horizontal stubs from
   each pin to the trunk, then one vertical trunk segment from min-y to
   max-y.  Individual stubs are also tested against obstacles and detoured
   when necessary.

Obstacle avoidance
------------------
Each component body is treated as an axis-aligned bounding box (AABB) with
an additional routing clearance margin (_OBSTACLE_CLEARANCE px) on all
sides.  Before committing any wire segment the router checks whether the
segment intersects any expanded AABB.  Intersecting segments are replaced
by 3-segment detours that route around the top or bottom edge of the
obstacle (whichever produces the shorter total path).

Junctions
---------
A filled dot (junction) is drawn whenever two or more horizontal stubs
reach the same y-coordinate on the trunk.  Additionally, for 2-pin nets,
a junction is drawn if the bend-point lies on an existing wire segment.

Net label placement
-------------------
Net labels (named nets only) are placed **at the midpoint** of the wire
tree bounding box, offset upward by a small gap.  A white halo rectangle
is drawn behind each label to keep it readable over wires — matching the
netlistsvg edge-label technique.  Each named net receives exactly one label
(no per-pin duplicate labels).

Fit-to-content + margin
-----------------------
After drawing all elements the renderer computes the bounding box of all
primitives and adjusts the SVG ``viewBox`` to fit the content with a
configurable margin (default 40 px).  The ``width``/``height`` attributes
on the root ``<svg>`` element still reflect the page dimensions so that
the document prints at the correct size; only the ``viewBox`` changes.

Font sizes
----------
* Part reference (ref): minimum 14 px
* Net label: minimum 12 px
* Component value: minimum 11 px
* Pin name stub: minimum 10 px

Canvas / page size
------------------
The canvas dimensions come from a :class:`~lib.core.page.PageConfig` passed
in by the caller.  When no ``PageConfig`` is provided the renderer uses
**A1 portrait** (1684 × 2384 px at 96 dpi) as the default.

Canvas output scaling
---------------------
Final SVG ``width``/``height`` are multiplied by an effective output scale.
In ``fixed`` mode this uses ``Style.canvas_scale``.  In ``auto`` mode
the renderer derives a scale from style font sizes and a readability target,
then clamps to configured min/max bounds.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, List, Optional, Tuple, TypeVar

from lib.core.render_style import (
    BoxStyle,
    HaloStyle,
    NetLabelStyle,
    PinStyle,
    SymbolStyle,
    RenderTemplate as _RenderTemplateT,
    TextPlacementStyle,
    WireStyle,
)
from lib.core.style import Style
from lib.core.style_resolver import resolve_style
from lib.render.svg_renderer import SvgCanvas
from lib.render.symbol_renderer import SymbolRenderer

if TYPE_CHECKING:
    from lib.core.schematic import Schematic
    from lib.core.part import Part
    from lib.core.page import PageConfig


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

_MARGIN = 40            # fit-to-content outer margin (px)
_COL_WIDTH = 180        # auto-layout: horizontal spacing between column centres
_ROW_HEIGHT = 140       # auto-layout: vertical spacing between parts in a column
_PARTS_PER_COL = 4      # max parts per column before wrapping to a new column

# Obstacle avoidance
_OBSTACLE_CLEARANCE = 6  # px of extra clearance added around each component AABB

# Cross-net wire avoidance
_WIRE_SEG_CLEARANCE = 4   # px clearance zone around each drawn wire segment
_WIRE_SEG_HALF = _WIRE_SEG_CLEARANCE  # half-width of the fattened segment obstacle

_T = TypeVar("_T")


def _default_wire_style() -> WireStyle:
    return WireStyle.default()


def _default_net_label_style() -> NetLabelStyle:
    return NetLabelStyle.default()


def _default_halo_style() -> HaloStyle:
    return HaloStyle.default()


def _default_box_style() -> BoxStyle:
    return BoxStyle.default()


def _default_pin_style() -> PinStyle:
    return PinStyle.default()


def _style_value(value: _T | None, *, field_name: str) -> _T:
    if value is None:
        raise ValueError(f"Style.default() produced None for {field_name}")
    return value


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _effective_output_scale(
    style: Style,
    *,
    font_ref: float,
    font_net: float,
    font_value: float,
    font_pin: float,
    ln_font_size: float,
) -> float:
    """Resolve final output scale from Style fixed/auto settings."""
    mode_raw = (_style_value(style.canvas_scale_mode, field_name="canvas_scale_mode") or "auto")
    mode = mode_raw.strip().lower()
    if mode not in {"fixed", "auto"}:
        mode = "auto"

    scale_min = float(_style_value(style.canvas_scale_min, field_name="canvas_scale_min"))
    scale_max = float(_style_value(style.canvas_scale_max, field_name="canvas_scale_max"))
    if scale_min > scale_max:
        scale_min, scale_max = scale_max, scale_min
    scale_min = max(0.1, scale_min)
    scale_max = max(scale_min, scale_max)

    if mode == "fixed":
        raw_scale = float(_style_value(style.canvas_scale, field_name="canvas_scale"))
    else:
        target_font_px = max(
            0.1,
            float(
                _style_value(
                    style.canvas_target_min_font_px,
                    field_name="canvas_target_min_font_px",
                )
            ),
        )
        # Conservative baseline: smallest effective text size should meet target.
        baseline_font_px = max(0.1, min(font_net, font_ref, font_value, font_pin, ln_font_size))
        raw_scale = target_font_px / baseline_font_px

    return _clamp(raw_scale, scale_min, scale_max)


def _symbol_renderer_from_style(style: Style) -> SymbolRenderer:
    """Build a symbol renderer configured from a resolved unified style."""
    box_style = style.box or BoxStyle.default()
    pin_style = style.pin or PinStyle.default()
    symbol_style = style.symbol or SymbolStyle.default()
    ref_text_style = style.ref_text or TextPlacementStyle.default_ref()
    value_text_style = style.value_text or TextPlacementStyle.default_value()
    return SymbolRenderer(
        primitive_stroke=_style_value(box_style.stroke, field_name="box.stroke"),
        primitive_stroke_width=_style_value(
            box_style.stroke_width, field_name="box.stroke_width"
        ),
        pin_stub_stroke=_style_value(pin_style.stub_stroke, field_name="pin.stub_stroke"),
        pin_stub_width=_style_value(pin_style.stub_stroke_width, field_name="pin.stub_stroke_width"),
        pin_text_fill=_style_value(pin_style.key_fill, field_name="pin.key_fill"),
        value_text_fill=_style_value(pin_style.value_fill, field_name="pin.value_fill"),
        symbol_scale=max(0.1, float(_style_value(symbol_style.scale, field_name="symbol.scale"))),
        ref_text_style=ref_text_style,
        value_text_style=value_text_style,
        pin_name_visible=_style_value(pin_style.pin_name_visible, field_name="pin.pin_name_visible"),
        pin_value_visible=_style_value(
            pin_style.pin_value_visible,
            field_name="pin.pin_value_visible",
        ),
    )


# ---------------------------------------------------------------------------
# Obstacle data structure
# ---------------------------------------------------------------------------

class _Obstacle:
    """Axis-aligned bounding box used for wire obstacle avoidance.

    The box is expanded by *clearance* on all sides relative to the raw
    component bounding box so that wires do not pass right along the body
    edge.
    """

    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        clearance: float = _OBSTACLE_CLEARANCE,
    ) -> None:
        self.x0 = x0 - clearance
        self.y0 = y0 - clearance
        self.x1 = x1 + clearance
        self.y1 = y1 + clearance

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def segment_hits(
        self, ax: float, ay: float, bx: float, by: float
    ) -> bool:
        """Return True if the axis-aligned segment A→B passes through this box.

        Only horizontal and vertical segments are considered (Manhattan routing).
        Diagonal segments are not used by this router.

        Endpoints that sit exactly on the expanded boundary are *not* counted
        as hits because pin stubs legitimately start/end at the box edge.
        """
        eps = 0.5  # small tolerance

        if abs(ay - by) < eps:  # horizontal segment
            y = (ay + by) / 2
            if not (self.y0 < y < self.y1):
                return False
            lo, hi = (min(ax, bx), max(ax, bx))
            # Segment must genuinely cross the box interior
            return lo < self.x1 - eps and hi > self.x0 + eps

        if abs(ax - bx) < eps:  # vertical segment
            x = (ax + bx) / 2
            if not (self.x0 < x < self.x1):
                return False
            lo, hi = (min(ay, by), max(ay, by))
            return lo < self.y1 - eps and hi > self.y0 + eps

        return False  # neither h nor v — shouldn't happen


def _any_obstacle_hit(
    obstacles: list[_Obstacle],
    ax: float, ay: float,
    bx: float, by: float,
) -> bool:
    """Return True if any obstacle blocks the segment from A to B."""
    return any(o.segment_hits(ax, ay, bx, by) for o in obstacles)


def _obstacle_contains_point(obstacle: object, x: float, y: float) -> bool:
    """Return True when *(x, y)* lies inside an obstacle-like AABB.

    Works for both component obstacles and previously drawn wire-segment
    soft obstacles, both of which expose x0/y0/x1/y1.
    """
    x0 = getattr(obstacle, "x0", None)
    y0 = getattr(obstacle, "y0", None)
    x1 = getattr(obstacle, "x1", None)
    y1 = getattr(obstacle, "y1", None)
    if x0 is None or y0 is None or x1 is None or y1 is None:
        return False
    return bool(x0 <= x <= x1 and y0 <= y <= y1)


# ---------------------------------------------------------------------------
# Wire-segment obstacle: treats already-drawn wire segments as soft obstacles
# ---------------------------------------------------------------------------

class _WireSegment:
    """A previously-drawn wire segment used as a soft obstacle for later nets.

    Orthogonal (H or V) segments are fattened by *_WIRE_SEG_HALF* px in the
    perpendicular direction so that later routes can detect and avoid them.
    Only genuine interior crossings are flagged — overlapping co-linear
    segments (shared trunk runs) are allowed.

    The ``x0/y0/x1/y1`` properties expose the fattened AABB so that detour
    logic in routing functions (which access ``obs.x0`` etc.) works
    identically for both component obstacles and wire-segment soft obstacles.
    """

    __slots__ = ("ax", "ay", "bx", "by", "x0", "y0", "x1", "y1",
                 "_is_h", "_is_v")

    def __init__(self, ax: float, ay: float, bx: float, by: float) -> None:
        self.ax = ax
        self.ay = ay
        self.bx = bx
        self.by = by
        half = _WIRE_SEG_HALF
        eps = 0.5
        self._is_h = abs(ay - by) < eps
        self._is_v = abs(ax - bx) < eps
        if self._is_h:
            # Horizontal segment — fatten vertically
            self.x0 = min(ax, bx)
            self.x1 = max(ax, bx)
            self.y0 = ay - half
            self.y1 = ay + half
        elif self._is_v:
            # Vertical segment — fatten horizontally
            self.x0 = ax - half
            self.x1 = ax + half
            self.y0 = min(ay, by)
            self.y1 = max(ay, by)
        else:
            # Diagonal (shouldn't happen in Manhattan routing)
            self.x0 = min(ax, bx) - half
            self.x1 = max(ax, bx) + half
            self.y0 = min(ay, by) - half
            self.y1 = max(ay, by) + half

    def segment_hits(
        self, ax: float, ay: float, bx: float, by: float
    ) -> bool:
        """Return True if the query segment genuinely crosses this stored segment.

        Only H↔V crossings are flagged (not H↔H or V↔V overlaps).
        An endpoint touching the stored segment is NOT counted as a hit so
        that T-junctions at trunk endpoints are allowed.
        """
        eps = 0.5

        sx0, sy0, sx1, sy1 = self.ax, self.ay, self.bx, self.by

        is_query_h = abs(ay - by) < eps
        is_query_v = abs(ax - bx) < eps

        # Only flag H↔V crossings (skip co-linear pairs)
        if self._is_h and is_query_v:
            # Stored is H, query is V → check if query vertical crosses stored horizontal
            qx = (ax + bx) / 2  # query x (constant)
            sx_lo = min(sx0, sx1)
            sx_hi = max(sx0, sx1)
            # Query x must be strictly inside stored horizontal extent
            if not (sx_lo + eps < qx < sx_hi - eps):
                return False
            # Stored y must be strictly inside query vertical extent (not at endpoints)
            qy_lo = min(ay, by)
            qy_hi = max(ay, by)
            sy = (sy0 + sy1) / 2
            return qy_lo + eps < sy < qy_hi - eps

        if self._is_v and is_query_h:
            # Stored is V, query is H → check if query horizontal crosses stored vertical
            qy = (ay + by) / 2  # query y (constant)
            sy_lo = min(sy0, sy1)
            sy_hi = max(sy0, sy1)
            if not (sy_lo + eps < qy < sy_hi - eps):
                return False
            qx_lo = min(ax, bx)
            qx_hi = max(ax, bx)
            sx = (sx0 + sx1) / 2
            return qx_lo + eps < sx < qx_hi - eps

        # H↔H or V↔V: parallel segments — no perpendicular crossing
        return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_schematic_svg(
    schematic: "Schematic",
    *,
    page: Optional["PageConfig"] = None,
    width: float = 0,
    height: float = 0,
    template: Optional["_RenderTemplateT"] = None,
) -> str:
    """Render *schematic* to an SVG string.

    Args:
        schematic: The schematic to render.
        page:      Optional :class:`~lib.core.page.PageConfig` that sets the
                   canvas dimensions.  Defaults to **A1 portrait** when
                   neither *page* nor the legacy *width*/*height* kwargs are
                   provided.  When *template* is given its page field is used
                   unless *page* is also explicitly supplied.
        width:     Legacy override — canvas width in px.  Ignored when *page*
                   is given.
        height:    Legacy override — canvas height in px.  Ignored when *page*
                   is given.
        template:  Optional :class:`~lib.core.render_style.RenderTemplate`
                   controlling colours, stroke widths, font sizes, and page
                   layout.  When ``None`` the renderer uses
                   :meth:`~lib.core.render_style.RenderTemplate.default` which
                   is bit-for-bit compatible with the previous hard-coded
                   defaults.

    Returns:
        Complete SVG document as a string.
    """
    from lib.core.page import PageConfig as _PageConfig

    # Resolve template → style sub-objects
    if template is None:
        tmpl = _RenderTemplateT.default()
    else:
        tmpl = template

    # Unified style resolution root for schematic-level controls.
    canvas_style = resolve_style(None, tmpl)

    wire_style: WireStyle = canvas_style.wire or _default_wire_style()
    ln_style: NetLabelStyle = canvas_style.label_net or _default_net_label_style()
    halo_style: HaloStyle = canvas_style.halo or _default_halo_style()
    pin_style: PinStyle = canvas_style.pin or _default_pin_style()

    # Resolved style scalars — used throughout this function
    wire_color: str = _style_value(wire_style.color, field_name="wire.color")
    wire_width: float = _style_value(wire_style.width, field_name="wire.width")
    junction_r: float = _style_value(wire_style.junction_radius, field_name="wire.junction_radius")
    junction_color: str = _style_value(wire_style.junction_color, field_name="wire.junction_color")
    wire_dash: str = _style_value(wire_style.dash, field_name="wire.dash")

    ln_color: str = _style_value(ln_style.color, field_name="label_net.color")
    ln_font_size: float = _style_value(ln_style.font_size, field_name="label_net.font_size")
    ln_font_style: str = _style_value(ln_style.font_style, field_name="label_net.font_style")
    ln_overline: bool = _style_value(ln_style.overline, field_name="label_net.overline")
    ln_body_fill: str = _style_value(ln_style.body_fill, field_name="label_net.body_fill")
    ln_body_stroke_width: float = _style_value(
        ln_style.body_stroke_width, field_name="label_net.body_stroke_width"
    )
    ln_stem_stroke_width: float = _style_value(
        ln_style.stem_stroke_width, field_name="label_net.stem_stroke_width"
    )

    halo_fill: str = _style_value(halo_style.fill, field_name="halo.fill")
    halo_opacity: str = _style_value(halo_style.opacity, field_name="halo.opacity")
    halo_pad: float = _style_value(halo_style.pad, field_name="halo.pad")

    canvas_symbol_style = canvas_style.symbol or SymbolStyle.default()
    symbol_scale = max(
        0.1,
        float(_style_value(canvas_symbol_style.scale, field_name="symbol.scale")),
    )

    background: str = _style_value(canvas_style.background, field_name="background")
    font_ref: float = _style_value(
        pin_style.font_ref if pin_style.font_ref is not None else canvas_style.ref_font_size,
        field_name="ref_font_size",
    )
    font_net: float = _style_value(canvas_style.net_font_size, field_name="net_font_size")
    font_value: float = _style_value(
        pin_style.font_value if pin_style.font_value is not None else canvas_style.value_font_size,
        field_name="value_font_size",
    )
    font_pin: float = _style_value(
        pin_style.font_pin if pin_style.font_pin is not None else canvas_style.pin_font_size,
        field_name="pin_font_size",
    )
    output_scale = _effective_output_scale(
        canvas_style,
        font_ref=font_ref,
        font_net=font_net,
        font_value=font_value,
        font_pin=font_pin,
        ln_font_size=ln_font_size,
    )

    # Resolve canvas dimensions — explicit page > template.page > legacy w/h > default
    if page is not None:
        canvas_w = page.width
        canvas_h = page.height
    elif template is not None:
        canvas_w = tmpl.page.width
        canvas_h = tmpl.page.height
    elif width or height:
        parts = schematic.parts
        n = max(len(parts), 1)
        canvas_w = width or (_MARGIN * 2 + n * _COL_WIDTH)
        canvas_h = height or (_MARGIN * 2 + _ROW_HEIGHT)
    else:
        default_page = _PageConfig.default()
        canvas_w = default_page.width
        canvas_h = default_page.height

    # --- Phase 1: compute part positions ------------------------------------
    from lib.core.junction import Junction
    from lib.core.part import NetLabel

    parts = schematic.parts
    resolved_part_styles: dict[str, Style] = {}
    for idx, part in enumerate(parts):
        if isinstance(part, NetLabel):
            continue
        ref = part.ref or f"_part{idx}"
        resolved_part_styles[ref] = resolve_style(part, tmpl)

    positions: dict[str, tuple[float, float]] = {}
    for idx, part in enumerate(parts):
        if isinstance(part, NetLabel):
            continue
        ref = part.ref or f"_part{idx}"
        cx, cy = _part_position(
            part,
            idx,
            canvas_w,
            canvas_h,
            len(parts),
            resolved_style=resolved_part_styles[ref],
        )
        positions[ref] = (cx, cy)

    # --- Phase 1b: build obstacle list (one per component body) -------------
    obstacles: list[_Obstacle] = []
    for idx, part in enumerate(parts):
        if isinstance(part, (NetLabel, Junction)):
            continue
        ref = part.ref or f"_part{idx}"
        part_style = resolved_part_styles[ref]
        part_renderer = _symbol_renderer_from_style(part_style)
        cx, cy = positions[ref]
        lib_id = part.lib_id or ""
        symbol_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
        obs = _component_obstacle(
            part,
            cx,
            cy,
            symbol_name,
            symbol_renderer=part_renderer,
            box_style=part_style.box or _default_box_style(),
            rotation=part_style.rotation,
        )
        obstacles.append(obs)

    # --- Phase 2: compute pin endpoints (world coords) ----------------------
    # pin_endpoints[(part_ref, pin_key)] = (px, py)
    pin_endpoints: dict[tuple[str, str], tuple[float, float]] = {}
    junction_points: set[tuple[float, float]] = set()
    for idx, part in enumerate(parts):
        if isinstance(part, NetLabel):
            continue
        ref = part.ref or f"_part{idx}"
        if isinstance(part, Junction):
            cx, cy = positions[ref]
            junction_pin = part.junction_pin
            pin_endpoints[(junction_pin.part_ref, junction_pin.key)] = (cx, cy)
            junction_points.add((cx, cy))
            continue
        part_style = resolved_part_styles[ref]
        part_renderer = _symbol_renderer_from_style(part_style)
        cx, cy = positions[ref]
        lib_id = part.lib_id or ""
        symbol_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
        ep = _compute_pin_endpoints(
            part,
            cx,
            cy,
            symbol_name,
            symbol_renderer=part_renderer,
            box_style=part_style.box or _default_box_style(),
            pin_style=part_style.pin or _default_pin_style(),
            rotation=part_style.rotation,
        )
        pin_endpoints.update(ep)

    # --- Phase 3: gather net→endpoints mapping (derived from pin graph) ----
    from lib.core.connect import derive_nets
    from lib.core.part import NetLabel

    derived_nets = derive_nets(list(schematic._parts))
    # Keep per-connected-component net endpoints separate even when names are equal
    # (e.g. two independent "VCC" islands must NOT be merged into one routed wire).
    net_components: list[tuple[str, list[tuple[float, float]]]] = []
    label_net_pin_endpoints: list[tuple[str, tuple[float, float], str, str]] = []

    # Build a lookup from Pin identity to its NetLabel owner (if any)
    netlabel_parts = [p for p in schematic._parts if isinstance(p, NetLabel)]

    for net in derived_nets:
        pts: list[tuple[float, float]] = []
        for pin in net.pins:
            key = (pin.part_ref, pin.key)
            if key in pin_endpoints:
                pts.append(pin_endpoints[key])

        if pts:
            net_components.append((net.name, pts))

    # Collect NetLabel flag label endpoints
    for nl in netlabel_parts:
        nl_pin = nl.label_pin
        # Find pins connected to this NetLabel's pin
        for connected_pin in nl_pin.connected_pins:
            key = (connected_pin.part_ref, connected_pin.key)
            if key not in pin_endpoints:
                continue
            pt = pin_endpoints[key]
            pcx, _ = positions.get(connected_pin.part_ref, (pt[0], pt[1]))
            # Determine placement side from NetLabel.direction.
            # Supported: left/right/top/bottom (aliases: up->top, down->bottom).
            d = (nl.direction or "").lower()
            auto_side = "right" if pt[0] <= pcx else "left"
            if d in {"left", "right", "top", "bottom"}:
                side = d
            elif d == "up":
                side = "top"
            elif d == "down":
                side = "bottom"
            else:
                side = auto_side
            label_net_pin_endpoints.append((nl.net_name, pt, side, auto_side))

    flagged_endpoints_by_net: dict[str, set[tuple[float, float]]] = {}
    for net_name, pt, _, _ in label_net_pin_endpoints:
        flagged_endpoints_by_net.setdefault(net_name, set()).add(pt)

    # --- Phase 4: draw into a tracking canvas -------------------------------
    canvas = _TrackingCanvas(canvas_w, canvas_h, background=background)

    # Title
    canvas.text(canvas_w / 2, 20, schematic.name,
                font_size=font_ref, anchor="middle", dominant_baseline="middle")

    # Draw all symbols
    for idx, part in enumerate(parts):
        if isinstance(part, (NetLabel, Junction)):
            continue
        ref = part.ref or f"_part{idx}"
        part_style = resolved_part_styles[ref]
        part_box_style = part_style.box or _default_box_style()
        part_pin_style = part_style.pin or _default_pin_style()
        part_ref_text_style = part_style.ref_text or TextPlacementStyle.default_ref()
        part_value_text_style = part_style.value_text or TextPlacementStyle.default_value()
        part_symbol_renderer = _symbol_renderer_from_style(part_style)
        cx, cy = positions[ref]
        lib_id = part.lib_id or ""
        symbol_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
        rotation = part_style.rotation
        part_font_ref = _style_value(
            part_pin_style.font_ref if part_pin_style.font_ref is not None else part_style.ref_font_size,
            field_name="ref_font_size",
        )
        part_font_value = _style_value(
            (
                part_pin_style.font_value
                if part_pin_style.font_value is not None
                else part_style.value_font_size
            ),
            field_name="value_font_size",
        )
        part_font_pin = _style_value(
            part_pin_style.font_pin if part_pin_style.font_pin is not None else part_style.pin_font_size,
            field_name="pin_font_size",
        )
        used_symbol_path = part_symbol_renderer.render_part(
            canvas,
            part,
            cx,
            cy,
            symbol_name=symbol_name,
            rotation=rotation,
            font_ref=part_font_ref,
            font_value=part_font_value,
            font_pin=part_font_pin,
        )
        if not used_symbol_path:
            _render_missing_symbol_placeholder(
                canvas,
                part,
                cx,
                cy,
                rotation=rotation,
                font_ref=part_font_ref,
                font_value=part_font_value,
                box_width=_style_value(part_box_style.width, field_name="box.width"),
                box_min_height=_style_value(part_box_style.min_height, field_name="box.min_height"),
                box_pin_row_height=_style_value(
                    part_box_style.pin_row_height,
                    field_name="box.pin_row_height",
                ),
                ref_text_style=part_ref_text_style,
                value_text_style=part_value_text_style,
                value_text_fill=_style_value(part_pin_style.value_fill, field_name="pin.value_fill"),
            )

    # Draw wires for each net.
    # Route nets with fewer pins first so that simple 2-pin wires (e.g. VCC/GND)
    # are committed before complex trunk trees.  This gives the trunk router a
    # chance to detect and avoid the already-drawn wire segments.
    drawn_segs: list[_WireSegment] = []
    sorted_net_items = sorted(net_components, key=lambda kv: len(kv[1]))
    for net_name, pts in sorted_net_items:
        flagged_points = flagged_endpoints_by_net.get(net_name, set())
        show_wire_label = not any(point in flagged_points for point in pts)
        _draw_wire_net(
            canvas, pts, net_name, obstacles, drawn_segs,
            wire_color=wire_color, wire_width=wire_width,
            wire_dash=wire_dash, junction_color=junction_color,
            junction_r=junction_r, font_net=font_net,
            halo_fill=halo_fill, halo_opacity=halo_opacity, halo_pad=halo_pad,
            show_label=show_wire_label,
            suppress_junction_points=junction_points,
        )

    # Draw explicit Junction components as fixed tee dots.
    for jx, jy in sorted(junction_points):
        canvas.circle(
            jx,
            jy,
            junction_r,
            stroke=junction_color,
            stroke_width=0,
            fill=junction_color,
        )

    # Draw NetLabel flag labels (one per pin, no wire routing).
    # All side='left' labels share a unified tip_x so their bodies align
    # to the same vertical column (avoids ragged stagger across pin offsets).
    _left_xs = [pt[0] for _, pt, side, _ in label_net_pin_endpoints if side == "left"]
    left_align_x: float | None = max(_left_xs) if _left_xs else None

    seen_label_pts: set[tuple[float, float]] = set()
    occupied_label_boxes: list[tuple[float, float, float, float]] = []
    extra_label_clearance = max(
        0.0,
        max(font_ref, font_value, font_pin) * 0.5 + max(0.0, symbol_scale - 1.0) * font_pin
    )
    flag_obstacles: list[_Obstacle] = list(obstacles)
    if extra_label_clearance > 0.0:
        for obs in obstacles:
            flag_obstacles.append(
                _Obstacle(obs.x0, obs.y0, obs.x1, obs.y1, clearance=extra_label_clearance)
            )

    row_step = max(ln_font_size + 4.0, font_pin + 2.0)
    row_offsets = [0.0, row_step, -row_step, row_step * 2.0, -row_step * 2.0]
    for net_name, pt, side, auto_side in label_net_pin_endpoints:
        if pt not in seen_label_pts:
            seen_label_pts.add(pt)
            selected_side = side
            selected_align_x = left_align_x if selected_side == "left" else None
            selected_y = pt[1]

            # Keep labels from sitting on component bodies:
            # 1) preferred side  2) auto side  3) opposite side  4) vertical fallback
            opposite_side = "left" if side == "right" else "right"
            candidate_sides: list[str] = [side, auto_side, opposite_side, "top", "bottom"]
            unique_candidates: list[str] = []
            for candidate in candidate_sides:
                if candidate not in unique_candidates:
                    unique_candidates.append(candidate)

            placed = False
            for candidate in unique_candidates:
                candidate_align_x = left_align_x if candidate == "left" else None
                for y_offset in row_offsets:
                    trial_y = pt[1] + y_offset
                    if _flag_label_hits_obstacles(
                        pt[0], trial_y, net_name,
                        side=candidate, align_x=candidate_align_x,
                        obstacles=flag_obstacles, ln_font_size=ln_font_size,
                    ):
                        continue
                    trial_box = _flag_label_box(
                        pt[0], trial_y, net_name,
                        side=candidate,
                        ln_font_size=ln_font_size,
                        halo_pad=halo_pad,
                        align_x=candidate_align_x,
                    )
                    if _boxes_overlap_any(trial_box, occupied_label_boxes):
                        continue
                    selected_side = candidate
                    selected_align_x = candidate_align_x
                    selected_y = trial_y
                    placed = True
                    break
                if placed:
                    break

            if not placed:
                nudge_candidates = [auto_side, opposite_side, side]
                for candidate in nudge_candidates:
                    if candidate not in {"left", "right"}:
                        continue
                    candidate_align_x = left_align_x if candidate == "left" else None
                    nudged_align_x = _nudge_horizontal_flag_tip(
                        pt[0], pt[1], net_name,
                        side=candidate, align_x=candidate_align_x,
                        obstacles=flag_obstacles, ln_font_size=ln_font_size,
                    )
                    if nudged_align_x is None:
                        continue
                    for y_offset in row_offsets:
                        trial_y = pt[1] + y_offset
                        if _flag_label_hits_obstacles(
                            pt[0], trial_y, net_name,
                            side=candidate, align_x=nudged_align_x,
                            obstacles=flag_obstacles, ln_font_size=ln_font_size,
                        ):
                            continue
                        trial_box = _flag_label_box(
                            pt[0], trial_y, net_name,
                            side=candidate,
                            ln_font_size=ln_font_size,
                            halo_pad=halo_pad,
                            align_x=nudged_align_x,
                        )
                        if _boxes_overlap_any(trial_box, occupied_label_boxes):
                            continue
                        selected_side = candidate
                        selected_align_x = nudged_align_x
                        selected_y = trial_y
                        placed = True
                        break
                    if placed:
                        break

            _draw_flag_label(
                canvas, pt[0], selected_y, net_name, side=selected_side, align_x=selected_align_x,
                wire_color=wire_color,
                ln_color=ln_color,
                ln_font_size=ln_font_size,
                ln_font_style=ln_font_style,
                ln_body_fill=ln_body_fill,
                ln_body_stroke_width=ln_body_stroke_width,
                ln_stem_stroke_width=ln_stem_stroke_width,
                halo_fill=halo_fill,
                halo_opacity=halo_opacity,
                halo_pad=halo_pad,
            )
            occupied_label_boxes.append(
                _flag_label_box(
                    pt[0],
                    selected_y,
                    net_name,
                    side=selected_side,
                    ln_font_size=ln_font_size,
                    halo_pad=halo_pad,
                    align_x=selected_align_x,
                )
            )

    # --- Phase 5: apply fit-to-content viewBox -----------------------------
    return canvas.to_svg_fit(margin=_MARGIN, output_scale=output_scale)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _part_position(
    part: "Part",
    idx: int,
    total_w: float,
    total_h: float,
    n_parts: int,
    *,
    resolved_style: Style | None = None,
) -> tuple[float, float]:
    """Return (cx, cy) for a part.

    Priority:
    1. Explicit Style(x, y) — scaled to SVG coords.
    2. Column-based auto-layout: parts are grouped into columns of at most
       ``_PARTS_PER_COL`` rows, arranged left-to-right.  Within each column
       parts are stacked vertically and centred.
    """
    style = resolved_style if resolved_style is not None else part.get_style()
    sx = getattr(style, "x", None)
    sy = getattr(style, "y", None)
    if sx is not None and sy is not None:
        scale = 3.0
        return _MARGIN + float(sx) * scale, _MARGIN + float(sy) * scale

    # Column-based auto-layout
    per_col = max(1, _PARTS_PER_COL)
    n_cols = max(1, math.ceil(n_parts / per_col))
    col = idx // per_col
    row = idx % per_col
    # How many parts are in this column?
    col_start = col * per_col
    col_count = min(per_col, n_parts - col_start)

    # Centre the column vertically in the canvas
    col_total_h = col_count * _ROW_HEIGHT
    col_y_start = (total_h - col_total_h) / 2 + _ROW_HEIGHT / 2

    cx = _MARGIN + col * _COL_WIDTH + _COL_WIDTH / 2
    cy = col_y_start + row * _ROW_HEIGHT
    return cx, cy


# ---------------------------------------------------------------------------
# Generic box height helper
# ---------------------------------------------------------------------------

def _box_height(
    n_pins: int,
    *,
    box_min_height: float | None = None,
    box_pin_row_height: float | None = None,
) -> float:
    """Compute auto-sized box height for *n_pins* pins."""
    default_box = _default_box_style()
    min_h = (
        _style_value(default_box.min_height, field_name="box.min_height")
        if box_min_height is None
        else box_min_height
    )
    pin_row = (
        _style_value(default_box.pin_row_height, field_name="box.pin_row_height")
        if box_pin_row_height is None
        else box_pin_row_height
    )
    n_side = max(1, math.ceil(n_pins / 2))
    return max(min_h, n_side * pin_row)


# ---------------------------------------------------------------------------
# Obstacle construction (must match symbol drawing geometry)
# ---------------------------------------------------------------------------

def _component_obstacle(
    part: "Part",
    cx: float,
    cy: float,
    symbol_name: str,
    *,
    symbol_renderer: SymbolRenderer | None = None,
    box_style: BoxStyle | None = None,
    rotation: int = 0,
) -> _Obstacle:
    """Return the routing obstacle (expanded AABB) for a component."""
    renderer = symbol_renderer or SymbolRenderer()
    bbox = renderer.component_bbox(
        part,
        cx,
        cy,
        symbol_name=symbol_name,
        rotation=rotation,
    )
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        return _Obstacle(x0, y0, x1, y1)

    # Fallback geometry used by unresolved-symbol placeholders.
    resolved_box = box_style or _default_box_style()
    pins = list(part.pins.items())
    h = _box_height(
        len(pins),
        box_min_height=resolved_box.min_height,
        box_pin_row_height=resolved_box.pin_row_height,
    )
    w = _style_value(resolved_box.width, field_name="box.width")
    x0, y0 = cx - w / 2, cy - h / 2
    return _Obstacle(x0, y0, x0 + w, y0 + h)


# ---------------------------------------------------------------------------
# Pin endpoint computation (must match symbol drawing geometry)
# ---------------------------------------------------------------------------

def _compute_pin_endpoints(
    part: "Part",
    cx: float,
    cy: float,
    symbol_name: str,
    *,
    symbol_renderer: SymbolRenderer | None = None,
    box_style: BoxStyle | None = None,
    pin_style: PinStyle | None = None,
    rotation: int = 0,
) -> dict[tuple[str, str], tuple[float, float]]:
    """Return {(part_ref, pin_key): (px, py)} for all pins of *part*."""
    renderer = symbol_renderer or SymbolRenderer()
    endpoints = renderer.pin_endpoints(
        part,
        cx,
        cy,
        symbol_name=symbol_name,
        rotation=rotation,
    )
    if endpoints:
        return endpoints
    if renderer.can_render(part, symbol_name):
        return endpoints

    return _generic_box_pin_endpoints(part, cx, cy, box_style=box_style, pin_style=pin_style)


def _generic_box_pin_endpoints(
    part: "Part",
    cx: float,
    cy: float,
    *,
    box_style: BoxStyle | None = None,
    pin_style: PinStyle | None = None,
) -> dict[tuple[str, str], tuple[float, float]]:
    """Pin endpoints for unresolved-symbol placeholder geometry."""
    resolved_box = box_style or _default_box_style()
    resolved_pin = pin_style or _default_pin_style()
    ref = part.ref or "?"
    pins = list(part.pins.items())
    h = _box_height(
        len(pins),
        box_min_height=resolved_box.min_height,
        box_pin_row_height=resolved_box.pin_row_height,
    )
    w = _style_value(resolved_box.width, field_name="box.width")
    stub_len = _style_value(resolved_pin.stub_length, field_name="pin.stub_length")
    x0, y0 = cx - w / 2, cy - h / 2
    result: dict[tuple[str, str], tuple[float, float]] = {}

    n_left = math.ceil(len(pins) / 2)
    for i, (pin_key, _) in enumerate(pins):
        if i < n_left:
            # Left side
            row = i
            py = y0 + (row + 0.5) * (h / n_left)
            ex = x0 - stub_len
            result[(ref, pin_key)] = (ex, py)
        else:
            # Right side
            row = i - n_left
            n_right = len(pins) - n_left
            py = y0 + (row + 0.5) * (h / max(n_right, 1))
            ex = x0 + w + stub_len
            result[(ref, pin_key)] = (ex, py)

    return result


# ---------------------------------------------------------------------------
# Wire routing
# ---------------------------------------------------------------------------

def _extract_wire_segs_from_elements(
    elements: list[str], start: int, *, wire_color: str | None = None
) -> list["_WireSegment"]:
    """Parse newly-added SVG <line> elements (from *start* index) into _WireSegments.

    Only lines with the wire stroke colour are captured so that pin stubs,
    junction circles, and other graphics are excluded.
    """
    import re
    segs: list[_WireSegment] = []
    # SVG line format: <line x1="..." y1="..." x2="..." y2="..." stroke="..." .../>
    pat = re.compile(
        r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"'
    )
    default_wire = _default_wire_style()
    resolved_wire_color = (
        _style_value(default_wire.color, field_name="wire.color")
        if wire_color is None
        else wire_color
    )
    wire_marker = f'stroke="{resolved_wire_color}"'
    for el in elements[start:]:
        if wire_marker not in el:
            continue
        m = pat.search(el)
        if m:
            x1, y1, x2, y2 = (float(v) for v in m.groups())
            segs.append(_WireSegment(x1, y1, x2, y2))
    return segs


def _draw_wire_net(
    canvas: "_TrackingCanvas",
    pts: list[tuple[float, float]],
    net_name: str,
    obstacles: list[_Obstacle],
    drawn_segs: "list[_WireSegment] | None" = None,
    *,
    wire_color: str | None = None,
    wire_width: float | None = None,
    wire_dash: str | None = None,
    junction_color: str | None = None,
    junction_r: float | None = None,
    font_net: float | None = None,
    halo_fill: str | None = None,
    halo_opacity: str | None = None,
    halo_pad: float | None = None,
    show_label: bool = True,
    suppress_junction_points: set[tuple[float, float]] | None = None,
) -> None:
    """Draw Manhattan wire routes connecting all endpoints in *pts*.

    Uses obstacle-aware routing to avoid drawing wires through component
    bodies.  See module docstring for the full algorithm description.

    *drawn_segs* is a shared list of _WireSegment objects from previously
    routed nets.  These act as soft obstacles so that later nets reroute
    around already-drawn wires, preventing visual crossings.
    """
    default_wire = _default_wire_style()
    default_halo = _default_halo_style()
    default_style = Style.default()

    wire_color = (
        _style_value(default_wire.color, field_name="wire.color")
        if wire_color is None
        else wire_color
    )
    wire_width = (
        _style_value(default_wire.width, field_name="wire.width")
        if wire_width is None
        else wire_width
    )
    wire_dash = (
        _style_value(default_wire.dash, field_name="wire.dash")
        if wire_dash is None
        else wire_dash
    )
    junction_color = (
        _style_value(default_wire.junction_color, field_name="wire.junction_color")
        if junction_color is None
        else junction_color
    )
    junction_r = (
        _style_value(default_wire.junction_radius, field_name="wire.junction_radius")
        if junction_r is None
        else junction_r
    )
    font_net = (
        _style_value(default_style.net_font_size, field_name="net_font_size")
        if font_net is None
        else font_net
    )
    halo_fill = (
        _style_value(default_halo.fill, field_name="halo.fill")
        if halo_fill is None
        else halo_fill
    )
    halo_opacity = (
        _style_value(default_halo.opacity, field_name="halo.opacity")
        if halo_opacity is None
        else halo_opacity
    )
    halo_pad = (
        _style_value(default_halo.pad, field_name="halo.pad")
        if halo_pad is None
        else halo_pad
    )

    is_anon = net_name.startswith("_anon")

    if len(pts) < 1:
        return

    unique_pts = list(dict.fromkeys(pts))  # deduplicate preserving order

    # Single-pin net: no wire to draw but still show the net name label
    if len(unique_pts) == 1 and not is_anon and show_label:
        px, py = unique_pts[0]
        _draw_net_label(canvas, px, py - 10, net_name,
                        wire_color=wire_color, font_net=font_net,
                        halo_fill=halo_fill, halo_opacity=halo_opacity, halo_pad=halo_pad)
        return

    if len(unique_pts) < 2:
        return

    is_anon = net_name.startswith("_anon")

    suppressed_keys = {
        (round(x, 2), round(y, 2))
        for x, y in (suppress_junction_points or set())
    }

    # Build effective obstacle list: component bodies + already-drawn wire segs
    eff_obstacles: list = list(obstacles)
    if drawn_segs:
        eff_obstacles.extend(drawn_segs)

    # Compute bounding box of endpoints (for label placement)
    xs = [p[0] for p in unique_pts]
    ys = [p[1] for p in unique_pts]
    bbox_mid_x = (min(xs) + max(xs)) / 2
    bbox_mid_y = (min(ys) + max(ys)) / 2

    # Record canvas elements count before drawing so we can capture new segments
    el_start = len(canvas._elements)

    if len(unique_pts) == 2:
        p0, p1 = unique_pts
        _draw_manhattan_wire(canvas, p0, p1, eff_obstacles,
                             wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash)
    else:
        # Trunk tree: use median-x trunk, shifted away from obstacles if needed
        sorted_xs = sorted(set(p[0] for p in unique_pts))
        trunk_x = _choose_trunk_x(sorted_xs, unique_pts, eff_obstacles)

        trunk_ys = [p[1] for p in unique_pts]
        trunk_y_min = min(trunk_ys)
        trunk_y_max = max(trunk_ys)

        # Vertical trunk (may be split into segments to avoid obstacles)
        if trunk_y_min < trunk_y_max:
            _draw_vertical_avoiding(
                canvas, trunk_x, trunk_y_min, trunk_y_max, eff_obstacles,
                wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash,
            )

        # Horizontal stubs from each point to trunk
        for px, py in unique_pts:
            if abs(px - trunk_x) > 0.5:
                _draw_horizontal_stub(canvas, px, py, trunk_x, eff_obstacles,
                                      trunk_y_span=(trunk_y_min, trunk_y_max),
                                      wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash)

        # Junctions at trunk intersections:
        # - Any point where a horizontal stub meets the trunk is a potential junction.
        # - We draw a junction dot if a stub meets the trunk AND the trunk passes
        #   through that point (i.e., the trunk extends above or below).
        # - Additionally, draw junctions where 2+ stubs share the same y.
        y_counts = Counter(round(y, 1) for y in trunk_ys)
        drawn_junction_keys: set[tuple[float, float]] = set()
        for (px, py) in unique_pts:
            py_round = round(py, 1)
            # Draw junction if: 2+ stubs at same y, OR this stub hits interior of trunk
            is_interior = trunk_y_min < py < trunk_y_max
            is_multi = y_counts[py_round] >= 2
            if is_interior or is_multi:
                key = (round(trunk_x, 2), round(py, 2))
                if key in suppressed_keys or key in drawn_junction_keys:
                    continue
                drawn_junction_keys.add(key)
                canvas.circle(trunk_x, py, junction_r,
                              stroke=junction_color, stroke_width=0,
                              fill=junction_color)

        # Update label position to trunk midpoint
        bbox_mid_x = trunk_x
        bbox_mid_y = (trunk_y_min + trunk_y_max) / 2

    # Capture newly-drawn wire segments and append to drawn_segs
    if drawn_segs is not None:
        new_segs = _extract_wire_segs_from_elements(canvas._elements, el_start,
                                                     wire_color=wire_color)
        drawn_segs.extend(new_segs)

    # Draw wire-net label for named nets (not anonymous)
    if not is_anon and show_label:
        _draw_net_label(canvas, bbox_mid_x, bbox_mid_y - 10, net_name,
                        wire_color=wire_color, font_net=font_net,
                        halo_fill=halo_fill, halo_opacity=halo_opacity, halo_pad=halo_pad)


def _choose_trunk_x(
    sorted_xs: list[float],
    pts: list[tuple[float, float]],
    obstacles: list[_Obstacle],
) -> float:
    """Pick a trunk x that avoids obstacle bodies and reduces visual looping.

    For general multi-pin nets this prefers the median-x trunk while searching
    nearby clear alternatives when blocked.  For 3-pin branch nets the scoring
    also biases toward destination-adjacent merge points when exactly one
    endpoint sits inside obstacle clearance (typical transistor-base branch).
    """
    median_x = sorted_xs[len(sorted_xs) // 2]
    ys = [p[1] for p in pts]
    y_min, y_max = min(ys), max(ys)

    def trunk_clear(tx: float) -> bool:
        return not _any_obstacle_hit(obstacles, tx, y_min, tx, y_max)

    step = _OBSTACLE_CLEARANCE * 2
    candidates: list[float] = []

    def add_candidate(tx: float) -> None:
        if not trunk_clear(tx):
            return
        if any(abs(tx - existing) <= 0.5 for existing in candidates):
            return
        candidates.append(tx)

    # Baseline seeds: endpoint x values and median.
    for sx in sorted_xs:
        add_candidate(sx)
    add_candidate(median_x)

    # Nearby clear options around the median, alternating right/left.
    for delta in range(1, 20):
        add_candidate(median_x + delta * step)
        add_candidate(median_x - delta * step)

    if not candidates:
        return median_x  # fallback — best effort

    def stub_block_stats(tx: float) -> tuple[int, int, float]:
        """Return (hard_blocks, all_blocks, bend_cost) for stubs at *tx*.

        hard_blocks: stub blocked by obstacles that do not contain endpoint.
        all_blocks: any blocked stub.
        bend_cost: rough bend estimate used as a readability tie-break.
        """
        hard_blocks = 0
        all_blocks = 0
        bend_cost = 0.0
        for px, py in pts:
            if abs(px - tx) <= 0.5:
                continue
            blocking = [o for o in obstacles if o.segment_hits(px, py, tx, py)]
            if not blocking:
                continue
            all_blocks += 1
            endpoint_only = all(_obstacle_contains_point(o, px, py) for o in blocking)
            if endpoint_only:
                bend_cost += 1.0
            else:
                hard_blocks += 1
                bend_cost += 2.0
        return hard_blocks, all_blocks, bend_cost

    # For 3-pin branch nets, if exactly one endpoint is in obstacle clearance,
    # bias trunk choice to stay near that constrained endpoint.
    anchor_x: float | None = None
    if len(pts) == 3:
        constrained_pts = [
            (px, py)
            for px, py in pts
            if any(_obstacle_contains_point(o, px, py) for o in obstacles)
        ]
        unique_constrained = list(dict.fromkeys(constrained_pts))
        if len(unique_constrained) == 1:
            anchor_x = unique_constrained[0][0]
            for delta in range(1, 20):
                add_candidate(anchor_x + delta * step)
                add_candidate(anchor_x - delta * step)

    def score(tx: float) -> tuple[float, float, float, float, float, float]:
        hard_blocks, all_blocks, bend_cost = stub_block_stats(tx)
        total_stub_len = sum(abs(px - tx) for px, _ in pts)
        anchor_bias = abs(tx - anchor_x) if anchor_x is not None else 0.0
        return (
            float(hard_blocks),
            float(all_blocks),
            anchor_bias,
            bend_cost,
            total_stub_len,
            abs(tx - median_x),
        )

    return min(candidates, key=score)


def _draw_vertical_avoiding(
    canvas: "_TrackingCanvas",
    x: float,
    y_min: float,
    y_max: float,
    obstacles: list[_Obstacle],
    *,
    wire_color: str | None = None,
    wire_width: float | None = None,
    wire_dash: str | None = None,
) -> None:
    """Draw a vertical wire from (x, y_min) to (x, y_max), routing around obstacles.

    If any obstacle blocks the straight vertical segment, the trunk is split:
    a 3-segment detour goes left or right around the blocking obstacle.
    The detour direction (left/right) is chosen to minimise extra wire length.
    Only one level of re-routing is attempted per obstacle to avoid unbounded
    recursion; if the detour sub-segments are also blocked the code falls back
    to a straight line for that sub-segment.
    """
    default_wire = _default_wire_style()
    wire_color = (
        _style_value(default_wire.color, field_name="wire.color")
        if wire_color is None
        else wire_color
    )
    wire_width = (
        _style_value(default_wire.width, field_name="wire.width")
        if wire_width is None
        else wire_width
    )
    wire_dash = (
        _style_value(default_wire.dash, field_name="wire.dash")
        if wire_dash is None
        else wire_dash
    )
    gap = _OBSTACLE_CLEARANCE

    # Collect obstacles that block the vertical trunk segment
    blocking = [o for o in obstacles if o.segment_hits(x, y_min, x, y_max)]
    if not blocking:
        canvas.line(
            x,
            y_min,
            x,
            y_max,
            stroke=wire_color,
            stroke_width=wire_width,
            stroke_dasharray=wire_dash,
        )
        return

    # Sort blocking obstacles top-to-bottom so we can process them in order
    blocking.sort(key=lambda o: o.y0)

    # Build a list of y-intervals that need a detour.
    # Walk from y_min to y_max, emitting straight segments between obstacles
    # and 3-segment detours around each obstacle.
    current_y = y_min

    for obs in blocking:
        # Skip obstacles that are entirely below current_y (already passed)
        if obs.y1 <= current_y:
            continue

        enter_y = max(obs.y0, current_y)  # where the trunk enters the obstacle
        exit_y = obs.y1                   # where the trunk exits the obstacle

        # Draw straight segment from current_y up to the obstacle entry
        if enter_y > current_y + 0.5:
            canvas.line(
                x, current_y, x, enter_y,
                stroke=wire_color, stroke_width=wire_width,
                stroke_dasharray=wire_dash,
            )

        # Detour left or right around the obstacle
        dx_left = obs.x0 - gap
        dx_right = obs.x1 + gap

        # Pick the side that requires less lateral travel from x
        if abs(dx_left - x) <= abs(dx_right - x):
            dx = dx_left
        else:
            dx = dx_right

        # 3-segment detour: go horizontal to dx, vertical past obstacle, back
        canvas.line(
            x, enter_y, dx, enter_y,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            dx, enter_y, dx, exit_y,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            dx, exit_y, x, exit_y,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )

        current_y = exit_y

    # Draw remaining straight segment to y_max
    if y_max > current_y + 0.5:
        canvas.line(
            x, current_y, x, y_max,
            stroke=wire_color, stroke_width=wire_width,
            stroke_dasharray=wire_dash,
        )


def _draw_horizontal_stub(
    canvas: "_TrackingCanvas",
    px: float,
    py: float,
    trunk_x: float,
    obstacles: list[_Obstacle],
    *,
    trunk_y_span: tuple[float, float] | None = None,
    wire_color: str | None = None,
    wire_width: float | None = None,
    wire_dash: str | None = None,
) -> None:
    """Draw a horizontal stub from (px, py) to (trunk_x, py).

    If the straight segment passes through an obstacle, a 3-segment detour
    is drawn around the obstacle (going above or below it).
    """
    default_wire = _default_wire_style()
    wire_color = (
        _style_value(default_wire.color, field_name="wire.color")
        if wire_color is None
        else wire_color
    )
    wire_width = (
        _style_value(default_wire.width, field_name="wire.width")
        if wire_width is None
        else wire_width
    )
    wire_dash = (
        _style_value(default_wire.dash, field_name="wire.dash")
        if wire_dash is None
        else wire_dash
    )
    if not _any_obstacle_hit(obstacles, px, py, trunk_x, py):
        canvas.line(
            px, py, trunk_x, py,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    # Find the blocking obstacle and route around it
    blocking = [o for o in obstacles if o.segment_hits(px, py, trunk_x, py)]
    if not blocking:
        canvas.line(
            px, py, trunk_x, py,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    # Special case: endpoint lies in obstacle clearance and the requested
    # segment exits that clearance outward. In this constrained-pin case we
    # prefer a direct horizontal branch to avoid local loop-like backtracking.
    def _moves_outward_from_obs(obs: object) -> bool:
        x0 = float(getattr(obs, "x0"))
        x1 = float(getattr(obs, "x1"))
        if x0 <= trunk_x <= x1:
            return False
        moving_left = trunk_x < px
        dist_left = abs(px - x0)
        dist_right = abs(x1 - px)
        if moving_left:
            return dist_left <= dist_right + 0.5
        return dist_right <= dist_left + 0.5

    if (
        all(isinstance(obs, _Obstacle) for obs in blocking)
        and all(_obstacle_contains_point(obs, px, py) for obs in blocking)
        and all(_moves_outward_from_obs(obs) for obs in blocking)
    ):
        canvas.line(
            px, py, trunk_x, py,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    obs = blocking[0]
    # Detour above or below the obstacle
    gap = _OBSTACLE_CLEARANCE
    detour_y_top = obs.y0 - gap
    detour_y_bot = obs.y1 + gap

    def _can_join_trunk_without_backtrack(detour_y: float) -> bool:
        if trunk_y_span is None:
            return False
        trunk_y_min, trunk_y_max = trunk_y_span
        if not (trunk_y_min - 0.5 <= detour_y <= trunk_y_max + 0.5):
            return False
        return not _any_obstacle_hit(obstacles, trunk_x, detour_y, trunk_x, py)

    options = [detour_y_top, detour_y_bot]
    dy = min(
        options,
        key=lambda candidate: (
            0 if _can_join_trunk_without_backtrack(candidate) else 1,
            abs(candidate - py),
        ),
    )
    join_without_backtrack = _can_join_trunk_without_backtrack(dy)

    # 3-segment path: (px,py) → (px,dy) → (trunk_x,dy) → (trunk_x,py)
    # If detour_y already intersects a clear trunk segment, stop there to avoid
    # drawing a local backtracking rectangle near the destination pin.
    canvas.line(
        px, py, px, dy,
        stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
    )
    canvas.line(
        px, dy, trunk_x, dy,
        stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
    )
    if not join_without_backtrack:
        canvas.line(
            trunk_x, dy, trunk_x, py,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )


def _draw_manhattan_wire(
    canvas: "_TrackingCanvas",
    p0: tuple[float, float],
    p1: tuple[float, float],
    obstacles: list[_Obstacle],
    *,
    wire_color: str | None = None,
    wire_width: float | None = None,
    wire_dash: str | None = None,
) -> None:
    """Draw an obstacle-aware L-shaped (Manhattan) wire from p0 to p1.

    Algorithm:
    1. If the two points are already axis-aligned, draw the straight segment
       (with a detour if the segment is blocked).
    2. Otherwise try H-first (horizontal to x1, then vertical to y1).
       If neither segment is blocked, use it.
    3. Otherwise try V-first (vertical to y1, then horizontal to x1).
       If neither segment is blocked, use it.
    4. If both simple L-routes are blocked, generate a 3-segment detour
       around the first blocking obstacle found.
    """
    default_wire = _default_wire_style()
    wire_color = (
        _style_value(default_wire.color, field_name="wire.color")
        if wire_color is None
        else wire_color
    )
    wire_width = (
        _style_value(default_wire.width, field_name="wire.width")
        if wire_width is None
        else wire_width
    )
    wire_dash = (
        _style_value(default_wire.dash, field_name="wire.dash")
        if wire_dash is None
        else wire_dash
    )
    x0, y0 = p0
    x1, y1 = p1

    if abs(x0 - x1) < 0.5 or abs(y0 - y1) < 0.5:
        # Already aligned — draw with possible detour
        _draw_segment_avoiding(canvas, x0, y0, x1, y1, obstacles,
                               wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash)
        return

    bend_h = (x1, y0)  # bend point for H-first route
    bend_v = (x0, y1)  # bend point for V-first route

    h_ok = (
        not _any_obstacle_hit(obstacles, x0, y0, x1, y0)
        and not _any_obstacle_hit(obstacles, x1, y0, x1, y1)
    )
    v_ok = (
        not _any_obstacle_hit(obstacles, x0, y0, x0, y1)
        and not _any_obstacle_hit(obstacles, x0, y1, x1, y1)
    )

    if h_ok:
        canvas.line(
            x0, y0, x1, y0,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            x1, y0, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    if v_ok:
        canvas.line(
            x0, y0, x0, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            x0, y1, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    # Both L-routes blocked → detour around the first blocking obstacle
    blocking: list[_Obstacle] = []
    for o in obstacles:
        if (o.segment_hits(x0, y0, x1, y0) or o.segment_hits(x1, y0, x1, y1)
                or o.segment_hits(x0, y0, x0, y1) or o.segment_hits(x0, y1, x1, y1)):
            blocking.append(o)

    if not blocking:
        # Nothing actually blocks — fall back to H-first
        canvas.line(
            x0, y0, x1, y0,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            x1, y0, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    obs = blocking[0]
    gap = _OBSTACLE_CLEARANCE

    # Try routing above and below the obstacle; pick shorter total path
    # Route above: go to y = obs.y0 - gap, across, then down
    dy_top = obs.y0 - gap
    dy_bot = obs.y1 + gap

    dist_top = abs(y0 - dy_top) + abs(x1 - x0) + abs(y1 - dy_top)
    dist_bot = abs(y0 - dy_bot) + abs(x1 - x0) + abs(y1 - dy_bot)

    dy = dy_top if dist_top <= dist_bot else dy_bot

    # 3-segment detour: (x0,y0)→(x0,dy)→(x1,dy)→(x1,y1)
    # Use _draw_segment_avoiding for each sub-segment so that
    # individual segments that are themselves blocked get re-routed.
    _draw_segment_avoiding(canvas, x0, y0, x0, dy, obstacles,
                           wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash)
    _draw_segment_avoiding(canvas, x0, dy, x1, dy, obstacles,
                           wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash)
    _draw_segment_avoiding(canvas, x1, dy, x1, y1, obstacles,
                           wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash)


def _draw_segment_avoiding(
    canvas: "_TrackingCanvas",
    x0: float, y0: float,
    x1: float, y1: float,
    obstacles: list[_Obstacle],
    *,
    wire_color: str | None = None,
    wire_width: float | None = None,
    wire_dash: str | None = None,
) -> None:
    """Draw a straight (H or V) segment from (x0,y0) to (x1,y1).

    If the segment is blocked by an obstacle a 3-segment detour is inserted.
    This function does NOT recurse — if the detour sub-segments are also
    blocked (e.g. the endpoint is inside an obstacle because of an extreme
    layout), it falls back to drawing a straight line to ensure the wire
    always terminates at the requested endpoint.
    """
    default_wire = _default_wire_style()
    wire_color = (
        _style_value(default_wire.color, field_name="wire.color")
        if wire_color is None
        else wire_color
    )
    wire_width = (
        _style_value(default_wire.width, field_name="wire.width")
        if wire_width is None
        else wire_width
    )
    wire_dash = (
        _style_value(default_wire.dash, field_name="wire.dash")
        if wire_dash is None
        else wire_dash
    )
    if not _any_obstacle_hit(obstacles, x0, y0, x1, y1):
        canvas.line(
            x0, y0, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    blocking = [o for o in obstacles if o.segment_hits(x0, y0, x1, y1)]
    if not blocking:
        canvas.line(
            x0, y0, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    obs = blocking[0]
    gap = _OBSTACLE_CLEARANCE

    # Horizontal segment blocked → detour above or below
    if abs(y0 - y1) < 0.5:
        dy_top = obs.y0 - gap
        dy_bot = obs.y1 + gap
        dy = dy_top if abs(y0 - dy_top) <= abs(y0 - dy_bot) else dy_bot
        # Draw 3-segment detour straight (no further recursion)
        canvas.line(
            x0, y0, x0, dy,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            x0, dy, x1, dy,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            x1, dy, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    # Vertical segment blocked → detour left or right
    dx_left = obs.x0 - gap
    dx_right = obs.x1 + gap
    dx = dx_left if abs(x0 - dx_left) <= abs(x0 - dx_right) else dx_right
    canvas.line(
        x0, y0, dx, y0,
        stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
    )
    canvas.line(
        dx, y0, dx, y1,
        stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
    )
    canvas.line(
        dx, y1, x1, y1,
        stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
    )


def _draw_net_label(
    canvas: "_TrackingCanvas",
    x: float,
    y: float,
    net_name: str,
    *,
    wire_color: str | None = None,
    font_net: float | None = None,
    halo_fill: str | None = None,
    halo_opacity: str | None = None,
    halo_pad: float | None = None,
) -> None:
    """Draw a net label with a white halo background at (x, y).

    The halo is a semi-transparent white rectangle drawn before the text,
    ensuring readability over wire lines (netlistsvg technique).
    """
    default_wire = _default_wire_style()
    default_halo = _default_halo_style()
    default_style = Style.default()
    wire_color = (
        _style_value(default_wire.color, field_name="wire.color")
        if wire_color is None
        else wire_color
    )
    font_net = (
        _style_value(default_style.net_font_size, field_name="net_font_size")
        if font_net is None
        else font_net
    )
    halo_fill = (
        _style_value(default_halo.fill, field_name="halo.fill")
        if halo_fill is None
        else halo_fill
    )
    halo_opacity = (
        _style_value(default_halo.opacity, field_name="halo.opacity")
        if halo_opacity is None
        else halo_opacity
    )
    halo_pad = (
        _style_value(default_halo.pad, field_name="halo.pad")
        if halo_pad is None
        else halo_pad
    )

    char_w = font_net * 0.6
    text_w = len(net_name) * char_w
    halo_x = x - text_w / 2 - halo_pad
    halo_y = y - font_net / 2 - halo_pad
    halo_w = text_w + halo_pad * 2
    halo_h = font_net + halo_pad * 2

    # Draw halo rectangle (not tracked for bbox — it follows the text)
    canvas._elements.append(
        f'<rect x="{halo_x:.1f}" y="{halo_y:.1f}"'
        f' width="{halo_w:.1f}" height="{halo_h:.1f}"'
        f' fill="{halo_fill}" opacity="{halo_opacity}"/>'
    )

    canvas.text(x, y, net_name,
                font_size=font_net, fill=wire_color,
                anchor="middle", dominant_baseline="middle")


def _flag_label_geometry(
    x: float,
    y: float,
    net_name: str,
    *,
    side: str,
    ln_font_size: float,
    align_x: float | None = None,
) -> tuple[float, float, float, float, float, float, float, float]:
    """Return flag-label geometry tuple.

    Result: (tip_x, tip_y, box_x, box_y, box_w, box_h, text_x, text_y)
    """
    char_w = ln_font_size * 0.62
    text_w = max(34.0, len(net_name) * char_w)
    box_h = max(18.0, ln_font_size + 6.0)
    tri_w = 6.0
    box_w = text_w + 12.0

    tip_x, tip_y = x, y

    if side == "left":
        tip_x = align_x if align_x is not None else x
        box_x = tip_x + tri_w
        box_y = tip_y - box_h / 2
        text_x = box_x + box_w / 2
        text_y = tip_y
    elif side == "right":
        tip_x = align_x if align_x is not None else x
        box_x = tip_x - tri_w - box_w
        box_y = tip_y - box_h / 2
        text_x = box_x + box_w / 2
        text_y = tip_y
    elif side == "top":
        box_x = tip_x - box_w / 2
        box_y = tip_y - tri_w - box_h
        text_x = tip_x
        text_y = box_y + box_h / 2
    else:  # bottom
        box_x = tip_x - box_w / 2
        box_y = tip_y + tri_w
        text_x = tip_x
        text_y = box_y + box_h / 2

    return tip_x, tip_y, box_x, box_y, box_w, box_h, text_x, text_y


def _flag_label_box(
    x: float,
    y: float,
    net_name: str,
    *,
    side: str,
    ln_font_size: float,
    halo_pad: float,
    align_x: float | None = None,
) -> tuple[float, float, float, float]:
    """Return conservative (x0, y0, x1, y1) bounds for a flag label."""
    _, _, box_x, box_y, box_w, box_h, _, _ = _flag_label_geometry(
        x, y, net_name, side=side, ln_font_size=ln_font_size, align_x=align_x
    )
    # Include halo padding used by _draw_flag_label so overlap checks match render.
    halo_pad_x, halo_pad_y = _flag_label_halo_padding(halo_pad)
    return (
        box_x - halo_pad_x,
        box_y - halo_pad_y,
        box_x + box_w + halo_pad_x,
        box_y + box_h + halo_pad_y,
    )


def _flag_label_halo_padding(halo_pad: float) -> tuple[float, float]:
    """Return (pad_x, pad_y) used by flag-label halo geometry."""
    # Keep legacy default visual when halo.pad=2.0 -> (8, 6),
    # while still allowing template-level halo pad scaling.
    return (max(2.0, halo_pad + 6.0), max(2.0, halo_pad + 4.0))


def _boxes_overlap_any(
    box: tuple[float, float, float, float],
    others: list[tuple[float, float, float, float]],
) -> bool:
    """Return True if *box* overlaps any box in *others*."""
    x0, y0, x1, y1 = box
    for ox0, oy0, ox1, oy1 in others:
        if _rects_overlap(x0, y0, x1, y1, ox0, oy0, ox1, oy1):
            return True
    return False


def _rects_overlap(
    ax0: float, ay0: float, ax1: float, ay1: float,
    bx0: float, by0: float, bx1: float, by1: float,
) -> bool:
    """Return True when two AABBs overlap with non-zero area."""
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def _flag_label_hits_obstacles(
    x: float,
    y: float,
    net_name: str,
    *,
    side: str,
    align_x: float | None,
    obstacles: list[_Obstacle],
    ln_font_size: float,
) -> bool:
    """Return True if the flag body intersects any component obstacle box."""
    _, _, box_x, box_y, box_w, box_h, _, _ = _flag_label_geometry(
        x, y, net_name, side=side, ln_font_size=ln_font_size, align_x=align_x
    )
    bx0 = box_x
    by0 = box_y
    bx1 = box_x + box_w
    by1 = box_y + box_h

    for obs in obstacles:
        if _rects_overlap(bx0, by0, bx1, by1, obs.x0, obs.y0, obs.x1, obs.y1):
            return True
    return False


def _nudge_horizontal_flag_tip(
    x: float,
    y: float,
    net_name: str,
    *,
    side: str,
    align_x: float | None,
    obstacles: list[_Obstacle],
    ln_font_size: float,
) -> float | None:
    """Return a nudged tip-x for horizontal flags so label body clears obstacles."""
    if side not in {"left", "right"}:
        return None

    tip_x, _, box_x, box_y, box_w, box_h, _, _ = _flag_label_geometry(
        x, y, net_name, side=side, ln_font_size=ln_font_size, align_x=align_x
    )

    overlaps: list[_Obstacle] = []
    by0 = box_y
    by1 = box_y + box_h
    bx0 = box_x
    bx1 = box_x + box_w
    for obs in obstacles:
        if _rects_overlap(bx0, by0, bx1, by1, obs.x0, obs.y0, obs.x1, obs.y1):
            overlaps.append(obs)

    if not overlaps:
        return align_x

    tri_w = 6.0
    gap = 2.0
    if side == "left":
        rightmost_x = max(obs.x1 for obs in overlaps)
        nudged_tip_x = max(tip_x, rightmost_x + gap - tri_w)
    else:
        leftmost_x = min(obs.x0 for obs in overlaps)
        nudged_tip_x = min(tip_x, leftmost_x - gap + tri_w)
    return nudged_tip_x


def _draw_flag_label(
    canvas: "_TrackingCanvas",
    x: float,
    y: float,
    net_name: str,
    *,
    side: str = "left",
    align_x: float | None = None,
    wire_color: str | None = None,
    ln_color: str | None = None,
    ln_font_size: float | None = None,
    ln_font_style: str | None = None,
    ln_body_fill: str | None = None,
    ln_body_stroke_width: float | None = None,
    ln_stem_stroke_width: float | None = None,
    halo_fill: str | None = None,
    halo_opacity: str | None = None,
    halo_pad: float | None = None,
) -> None:
    """Draw a label-net as a small *symbol-like component*.

    The stem is always **horizontal**, parallel to the pin stub, so it
    visually continues the stub line without any diagonal artefact.

    Geometry:
    - side='left'  (right-protruding stub): triangle tip at (align_x or x, y),
      body extends further right.  A horizontal stem runs from (x, y) to the
      tip when align_x != x.
    - side='right' (left-protruding stub): triangle tip at (x, y), body
      extends to the left.  No stem needed — tip is already at pin endpoint.

    For side='left', *align_x* sets a shared column for the triangle tip so
    that all left-side labels in the same schematic align their bodies to the
    same vertical line (a purely horizontal stem connects each pin to it).
    """
    default_wire = _default_wire_style()
    default_ln = _default_net_label_style()
    default_halo = _default_halo_style()

    wire_color = (
        _style_value(default_wire.color, field_name="wire.color")
        if wire_color is None
        else wire_color
    )
    ln_color = (
        _style_value(default_ln.color, field_name="label_net.color")
        if ln_color is None
        else ln_color
    )
    ln_font_size = (
        _style_value(default_ln.font_size, field_name="label_net.font_size")
        if ln_font_size is None
        else ln_font_size
    )
    ln_font_style = (
        _style_value(default_ln.font_style, field_name="label_net.font_style")
        if ln_font_style is None
        else ln_font_style
    )
    ln_body_fill = (
        _style_value(default_ln.body_fill, field_name="label_net.body_fill")
        if ln_body_fill is None
        else ln_body_fill
    )
    ln_body_stroke_width = (
        ln_body_stroke_width
        if ln_body_stroke_width is not None
        else _style_value(default_ln.body_stroke_width, field_name="label_net.body_stroke_width")
    )
    ln_stem_stroke_width = (
        ln_stem_stroke_width
        if ln_stem_stroke_width is not None
        else _style_value(default_ln.stem_stroke_width, field_name="label_net.stem_stroke_width")
    )
    halo_fill = (
        _style_value(default_halo.fill, field_name="halo.fill")
        if halo_fill is None
        else halo_fill
    )
    halo_opacity = (
        _style_value(default_halo.opacity, field_name="halo.opacity")
        if halo_opacity is None
        else halo_opacity
    )
    halo_pad = (
        _style_value(default_halo.pad, field_name="halo.pad")
        if halo_pad is None
        else halo_pad
    )

    pad_x, pad_y = _flag_label_halo_padding(halo_pad)
    tip_x, tip_y, box_x, box_y, box_w, box_h, text_x, text_y = _flag_label_geometry(
        x, y, net_name, side=side, ln_font_size=ln_font_size, align_x=align_x
    )

    # Halo (covers body + any horizontal stem)
    halo_x = box_x - pad_x
    halo_y = box_y - pad_y
    halo_w = box_w + pad_x * 2
    halo_h = box_h + pad_y * 2
    canvas._elements.append(
        f'<rect x="{halo_x:.1f}" y="{halo_y:.1f}" width="{halo_w:.1f}" height="{halo_h:.1f}" '
        f'fill="{halo_fill}" opacity="{halo_opacity}"/>'
    )

    # Horizontal stem from pin endpoint to triangle tip.
    if tip_y == y and tip_x != x:
        canvas.line(x, y, tip_x, tip_y, stroke=ln_color, stroke_width=ln_stem_stroke_width)

    # Label body (iconoir-like tag outline): hollow shape, unified stroke.
    # Keep text inside for readability.
    if side in {"left", "right"}:
        # Horizontal tag
        if side == "left":
            x0 = box_x
            x1 = box_x + box_w
            y0 = box_y
            y1 = box_y + box_h
            notch = min(10.0, box_w * 0.22)
            d = (
                f"M {x1:.1f} {y0:.1f} "
                f"L {x0 + notch:.1f} {y0:.1f} "
                f"L {tip_x:.1f} {tip_y:.1f} "
                f"L {x0 + notch:.1f} {y1:.1f} "
                f"L {x1:.1f} {y1:.1f} Z"
            )
        else:
            x0 = box_x
            x1 = box_x + box_w
            y0 = box_y
            y1 = box_y + box_h
            notch = min(10.0, box_w * 0.22)
            d = (
                f"M {x0:.1f} {y0:.1f} "
                f"L {x1 - notch:.1f} {y0:.1f} "
                f"L {tip_x:.1f} {tip_y:.1f} "
                f"L {x1 - notch:.1f} {y1:.1f} "
                f"L {x0:.1f} {y1:.1f} Z"
            )
    else:
        # Vertical tag
        x0 = box_x
        x1 = box_x + box_w
        y0 = box_y
        y1 = box_y + box_h
        notch = min(10.0, box_h * 0.28)
        if side == "top":
            d = (
                f"M {x0:.1f} {y0:.1f} "
                f"L {x1:.1f} {y0:.1f} "
                f"L {x1:.1f} {y1 - notch:.1f} "
                f"L {tip_x:.1f} {tip_y:.1f} "
                f"L {x0:.1f} {y1 - notch:.1f} Z"
            )
        else:
            d = (
                f"M {x0:.1f} {y1:.1f} "
                f"L {x1:.1f} {y1:.1f} "
                f"L {x1:.1f} {y0 + notch:.1f} "
                f"L {tip_x:.1f} {tip_y:.1f} "
                f"L {x0:.1f} {y0 + notch:.1f} Z"
            )

    canvas._elements.append(
        f'<path d="{d}" fill="{ln_body_fill}" stroke="{ln_color}" stroke-width="{ln_body_stroke_width}"/>'
    )

    canvas._elements.append(
        f'<text x="{text_x:.1f}" y="{text_y:.1f}" font-size="{ln_font_size}" fill="{ln_color}" '
        f'text-anchor="middle" dominant-baseline="middle" font-style="{ln_font_style}">{net_name}</text>'
    )

    canvas._track(halo_x, halo_y)
    canvas._track(halo_x + halo_w, halo_y + halo_h)

def _render_missing_symbol_placeholder(
    canvas: "_TrackingCanvas",
    part: "Part",
    cx: float,
    cy: float,
    *,
    rotation: int = 0,
    font_ref: float | None = None,
    font_value: float | None = None,
    box_width: float | None = None,
    box_min_height: float | None = None,
    box_pin_row_height: float | None = None,
    ref_text_style: TextPlacementStyle | None = None,
    value_text_style: TextPlacementStyle | None = None,
    value_text_fill: str | None = None,
) -> None:
    """Render a red dashed missing-symbol placeholder.

    This fallback is used only when no symbol could be resolved from either
    the attached part symbol data or configured KiCad symbol libraries.
    """
    default_style = Style.default()
    default_box = _default_box_style()

    font_ref = (
        _style_value(default_style.ref_font_size, field_name="ref_font_size")
        if font_ref is None
        else font_ref
    )
    font_value = (
        _style_value(default_style.value_font_size, field_name="value_font_size")
        if font_value is None
        else font_value
    )
    box_width = (
        _style_value(default_box.width, field_name="box.width")
        if box_width is None
        else box_width
    )
    box_min_height = (
        box_min_height
        if box_min_height is not None
        else _style_value(default_box.min_height, field_name="box.min_height")
    )
    box_pin_row_height = (
        box_pin_row_height
        if box_pin_row_height is not None
        else _style_value(default_box.pin_row_height, field_name="box.pin_row_height")
    )
    ref_text_style = (
        TextPlacementStyle.default_ref()
        if ref_text_style is None
        else TextPlacementStyle.default_ref().merge(ref_text_style)
    )
    value_text_style = (
        TextPlacementStyle.default_value()
        if value_text_style is None
        else TextPlacementStyle.default_value().merge(value_text_style)
    )
    value_text_fill = (
        _style_value(_default_pin_style().value_fill, field_name="pin.value_fill")
        if value_text_fill is None
        else value_text_fill
    )

    h = _box_height(
        len(list(part.pins.items())),
        box_min_height=box_min_height,
        box_pin_row_height=box_pin_row_height,
    )
    w = box_width
    x0, y0 = cx - w / 2, cy - h / 2
    x1, y1 = x0 + w, y0 + h

    placeholder_color = "#d32f2f"
    placeholder_dash = "6,4"
    placeholder_stroke_width = 2.0

    canvas.line(
        x0,
        y0,
        x1,
        y0,
        stroke=placeholder_color,
        stroke_width=placeholder_stroke_width,
        stroke_dasharray=placeholder_dash,
    )
    canvas.line(
        x1,
        y0,
        x1,
        y1,
        stroke=placeholder_color,
        stroke_width=placeholder_stroke_width,
        stroke_dasharray=placeholder_dash,
    )
    canvas.line(
        x1,
        y1,
        x0,
        y1,
        stroke=placeholder_color,
        stroke_width=placeholder_stroke_width,
        stroke_dasharray=placeholder_dash,
    )
    canvas.line(
        x0,
        y1,
        x0,
        y0,
        stroke=placeholder_color,
        stroke_width=placeholder_stroke_width,
        stroke_dasharray=placeholder_dash,
    )

    missing_label = f"? {part.lib_id or '?'}"
    canvas.text(
        cx,
        cy,
        missing_label,
        font_size=max(10.0, font_ref * 0.7),
        fill=placeholder_color,
        anchor="middle",
        dominant_baseline="middle",
    )

    local_bbox = (-w / 2, -h / 2, w / 2, h / 2)
    ref_text = part.ref or ""
    value_text = part.value or ""

    if ref_text and SymbolRenderer.text_visible(ref_text_style, TextPlacementStyle.default_ref()):
        ref_x, ref_y, ref_anchor = SymbolRenderer.text_position(
            cx=cx,
            cy=cy,
            bbox=local_bbox,
            placement=ref_text_style,
            default_placement=TextPlacementStyle.default_ref(),
            rotation=rotation,
        )
        canvas.text(
            ref_x,
            ref_y,
            ref_text,
            font_size=font_ref,
            anchor=ref_anchor,
            dominant_baseline="middle",
        )

    if value_text and SymbolRenderer.text_visible(value_text_style, TextPlacementStyle.default_value()):
        value_x, value_y, value_anchor = SymbolRenderer.text_position(
            cx=cx,
            cy=cy,
            bbox=local_bbox,
            placement=value_text_style,
            default_placement=TextPlacementStyle.default_value(),
            rotation=rotation,
        )
        canvas.text(
            value_x,
            value_y,
            value_text,
            font_size=font_value,
            fill=value_text_fill,
            anchor=value_anchor,
            dominant_baseline="middle",
        )


# ---------------------------------------------------------------------------
# Tracking canvas — extends SvgCanvas with bounding-box tracking
# ---------------------------------------------------------------------------

class _TrackingCanvas(SvgCanvas):
    """SvgCanvas that tracks the bounding box of all drawn primitives.

    After drawing, call :meth:`to_svg_fit` to obtain an SVG string whose
    ``viewBox`` is fitted to the content with a given margin.
    """

    def __init__(self, width: float, height: float, *, background: str = "white") -> None:
        super().__init__(width=width, height=height, background=background)
        self._min_x = float("inf")
        self._min_y = float("inf")
        self._max_x = float("-inf")
        self._max_y = float("-inf")

    # ------------------------------------------------------------------
    # BBox tracking helpers
    # ------------------------------------------------------------------

    def _track(self, x: float, y: float) -> None:
        if x < self._min_x:
            self._min_x = x
        if x > self._max_x:
            self._max_x = x
        if y < self._min_y:
            self._min_y = y
        if y > self._max_y:
            self._max_y = y

    # Override primitives to also update bounding box

    def line(self, x1, y1, x2, y2, **kw):
        self._track(x1, y1)
        self._track(x2, y2)
        super().line(x1, y1, x2, y2, **kw)

    def polyline(self, points, **kw):
        for x, y in points:
            self._track(x, y)
        super().polyline(points, **kw)

    def polygon(self, points, **kw):
        for x, y in points:
            self._track(x, y)
        super().polygon(points, **kw)

    def circle(self, cx, cy, r, **kw):
        self._track(cx - r, cy - r)
        self._track(cx + r, cy + r)
        super().circle(cx, cy, r, **kw)

    def text(self, x, y, content, *, font_size=11, **kw):
        # Approximate text bounding box
        char_w = font_size * 0.6
        text_w = len(content) * char_w
        text_h = font_size
        anchor = kw.get("anchor", "middle")
        if anchor == "middle":
            self._track(x - text_w / 2, y - text_h / 2)
            self._track(x + text_w / 2, y + text_h / 2)
        elif anchor == "end":
            self._track(x - text_w, y - text_h / 2)
            self._track(x, y + text_h / 2)
        else:  # start
            self._track(x, y - text_h / 2)
            self._track(x + text_w, y + text_h / 2)
        super().text(x, y, content, font_size=font_size, **kw)

    # ------------------------------------------------------------------
    # Fit-to-content serialisation
    # ------------------------------------------------------------------

    def to_svg_fit(self, margin: float = 40, output_scale: float = 1.0) -> str:
        """Return SVG string with viewBox fitted to content + *margin*.

        Args:
            margin: Extra whitespace around tracked content in viewBox units.
            output_scale: Final SVG output scaling factor. This multiplies the
                exported ``width``/``height`` attributes while keeping logical
                drawing coordinates unchanged.
        """
        scale = max(0.1, float(output_scale))
        if abs(scale - 1.0) < 1e-9:
            scaled_width = self._width
            scaled_height = self._height
        else:
            scaled_width = self._width * scale
            scaled_height = self._height * scale
        if self._min_x == float("inf"):
            # Nothing was drawn — fall back to full-page viewBox
            header = (
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<svg xmlns="http://www.w3.org/2000/svg"'
                f' width="{scaled_width}" height="{scaled_height}"'
                f' viewBox="0 0 {self._width} {self._height}">\n'
            )
            if self._background and self._background != "none":
                header += (
                    f'  <rect width="{self._width}" height="{self._height}"'
                    f' fill="{self._background}"/>\n'
                )
            body = "\n".join(f"  {el}" for el in self._elements)
            return header + body + "\n</svg>\n"

        vb_x = self._min_x - margin
        vb_y = self._min_y - margin
        vb_w = (self._max_x - self._min_x) + 2 * margin
        vb_h = (self._max_y - self._min_y) + 2 * margin

        # Clamp to non-negative
        vb_w = max(vb_w, 1)
        vb_h = max(vb_h, 1)

        header = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg"'
            f' width="{scaled_width}" height="{scaled_height}"'
            f' viewBox="{vb_x:.1f} {vb_y:.1f} {vb_w:.1f} {vb_h:.1f}">\n'
        )
        if self._background and self._background != "none":
            header += (
                f'  <rect width="100%" height="100%"'
                f' fill="{self._background}"/>\n'
            )
        body = "\n".join(f"  {el}" for el in self._elements)
        return header + body + "\n</svg>\n"
