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

1. For a 2-pin net the router first attempts a direct straight segment when
   endpoints are aligned and clear.  Otherwise the route is a single
   orthogonal L.  The bend direction is chosen to avoid component bounding
   boxes (H-first and V-first are both evaluated; the first collision-free
   option is used).  If both single-bend routes are blocked a simple
   3-segment detour is generated that routes around the obstacle.
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

"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, List, Optional, Tuple, TypeVar

from lib.core.render_style import (
    BoxStyle,
    HaloStyle,
    PinStyle,
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
_OBSTACLE_CLEARANCE = 0.0  # no expansion/shrinkage — obstacle matches component body exactly
_OBSTACLE_HORIZONTAL_EXTRA = 0.0  # no extra horizontal padding
_ROUTING_GAP = 6.0  # routing gap (px) used when detouring around obstacles

# Cross-net wire avoidance
_WIRE_SEG_CLEARANCE = 4   # px clearance zone around each drawn wire segment
_WIRE_SEG_HALF = _WIRE_SEG_CLEARANCE  # half-width of the fattened segment obstacle

_T = TypeVar("_T")


def _default_wire_style() -> WireStyle:
    return WireStyle.default()


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


def _symbol_renderer_from_style(style: Style) -> SymbolRenderer:
    """Build a symbol renderer configured from a resolved unified style."""
    box_style = style.box or BoxStyle.default()
    pin_style = style.pin or PinStyle.default()
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

    The box is expanded by *clearance* on top/bottom and by an additional
    horizontal margin on left/right so that wires keep a little more distance
    from vertical body edges.
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
        horizontal_clearance = clearance + _OBSTACLE_HORIZONTAL_EXTRA
        self.x0 = x0 - horizontal_clearance
        self.y0 = y0 - clearance
        self.x1 = x1 + horizontal_clearance
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


def _moves_outward_from_obstacle(
    obstacle: object,
    from_pt: tuple[float, float],
    to_pt: tuple[float, float],
) -> bool:
    """Return True if movement goes from an interior endpoint outward."""
    ox0 = float(getattr(obstacle, "x0"))
    oy0 = float(getattr(obstacle, "y0"))
    ox1 = float(getattr(obstacle, "x1"))
    oy1 = float(getattr(obstacle, "y1"))
    fx, fy = from_pt
    tx, ty = to_pt

    if abs(fx - tx) < 0.5:
        if oy0 <= ty <= oy1:
            return False
        moving_up = ty < fy
        dist_top = abs(fy - oy0)
        dist_bottom = abs(oy1 - fy)
        if moving_up:
            return dist_top <= dist_bottom + 0.5
        return dist_bottom <= dist_top + 0.5

    if abs(fy - ty) < 0.5:
        if ox0 <= tx <= ox1:
            return False
        moving_left = tx < fx
        dist_left = abs(fx - ox0)
        dist_right = abs(ox1 - fx)
        if moving_left:
            return dist_left <= dist_right + 0.5
        return dist_right <= dist_left + 0.5

    return False


def _can_draw_straight(
    p0: tuple[float, float],
    p1: tuple[float, float],
    obstacles: list[_Obstacle],
) -> bool:
    """Return True if p0→p1 can be drawn as one straight wire segment.

    A straight segment is allowed only when points are axis-aligned and no
    obstacle blocks the direct segment.
    """
    x0, y0 = p0
    x1, y1 = p1
    is_aligned = abs(x0 - x1) < 0.5 or abs(y0 - y1) < 0.5
    if not is_aligned:
        return False
    blocking = [obstacle for obstacle in obstacles if obstacle.segment_hits(x0, y0, x1, y1)]
    if not blocking:
        return True

    for obstacle in blocking:
        p0_inside = _obstacle_contains_point(obstacle, x0, y0)
        p1_inside = _obstacle_contains_point(obstacle, x1, y1)
        if p0_inside and _moves_outward_from_obstacle(obstacle, p0, p1):
            continue
        if p1_inside and _moves_outward_from_obstacle(obstacle, p1, p0):
            continue
        return False

    return True


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
    debug: bool = False,
    viewbox: tuple[float, float, float, float] | None = None,
    fit_to_content: bool = False,
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
        debug:     When ``True``, draw debug overlays on top of the final
                   schematic (component obstacles, trunk guides, and pin
                   endpoint markers).

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
    halo_style: HaloStyle = canvas_style.halo or _default_halo_style()
    pin_style: PinStyle = canvas_style.pin or _default_pin_style()

    # Resolved style scalars — used throughout this function
    wire_color: str = _style_value(wire_style.color, field_name="wire.color")
    wire_width: float = _style_value(wire_style.width, field_name="wire.width")
    junction_r: float = _style_value(wire_style.junction_radius, field_name="wire.junction_radius")
    junction_color: str = _style_value(wire_style.junction_color, field_name="wire.junction_color")
    wire_dash: str = _style_value(wire_style.dash, field_name="wire.dash")

    halo_fill: str = _style_value(halo_style.fill, field_name="halo.fill")
    halo_opacity: str = _style_value(halo_style.opacity, field_name="halo.opacity")
    halo_pad: float = _style_value(halo_style.pad, field_name="halo.pad")

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

    # Auto-scale: enlarge output dimensions so the smallest font meets the
    # target minimum pixel size on the final canvas.
    # Only applied when page is passed directly (not via template), so that
    # explicit template dimensions are preserved exactly.
    if page is not None:
        target_min = getattr(canvas_style, "canvas_target_min_font_px", None)
        scale_min = getattr(canvas_style, "canvas_scale_min", None)
        scale_max = getattr(canvas_style, "canvas_scale_max", None)
        if target_min is not None and scale_min is not None and scale_max is not None:
            from lib.core.render_style import NetLabelStyle as _NetLabelStyle
            label_net_style = canvas_style.label_net or _NetLabelStyle.default()
            baseline = min(
                font_ref,
                font_net,
                font_value,
                font_pin,
                _style_value(label_net_style.font_size, field_name="label_net.font_size"),
            )
            if baseline > 0:
                raw_scale = target_min / baseline
                auto_scale = max(scale_min, min(scale_max, raw_scale))
                canvas_w *= auto_scale
                canvas_h *= auto_scale

    # --- Phase 1: compute part positions ------------------------------------
    from lib.core.junction import Junction
    from lib.core.part import NetLabel

    parts = schematic.parts
    resolved_part_styles: dict[str, Style] = {}
    for idx, part in enumerate(parts):
        ref = part.ref or f"_part{idx}"
        part_style = resolve_style(part, tmpl)
        if isinstance(part, NetLabel):
            # Determine value_text position: part's own setting wins over default "center"
            part_own_style = part.get_style()
            part_own_vt = part_own_style.value_text if part_own_style else None
            vt_position = (
                part_own_vt.position
                if part_own_vt is not None and part_own_vt.position is not None
                else "center"
            )
            part_style = part_style.merge(
                Style(
                    rotation=_netlabel_rotation(part.direction, fallback=part_style.rotation),
                    ref_text=TextPlacementStyle(visible=False),
                    value_text=TextPlacementStyle(
                        position=vt_position,
                        offset=part_own_vt.offset if part_own_vt is not None and part_own_vt.offset is not None else 0.0,
                        visible=True,
                        rotation_mode="component",
                    ),
                    pin=PinStyle(pin_name_visible=False, pin_value_visible=False),
                )
            )
        resolved_part_styles[ref] = part_style

    positions: dict[str, tuple[float, float]] = {}
    for idx, part in enumerate(parts):
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
    debug_component_obstacles: list[tuple[str, _Obstacle]] = []
    for idx, part in enumerate(parts):
        if isinstance(part, Junction):
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
        if debug:
            debug_component_obstacles.append((ref, obs))

    # --- Phase 2: compute pin endpoints (world coords) ----------------------
    # pin_endpoints[(part_ref, pin_key)] = (px, py)
    pin_endpoints: dict[tuple[str, str], tuple[float, float]] = {}
    for idx, part in enumerate(parts):
        ref = part.ref or f"_part{idx}"
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
    junction_refs = {part.ref for part in parts if isinstance(part, Junction)}
    junction_points = {
        point
        for (part_ref, _), point in pin_endpoints.items()
        if part_ref in junction_refs
    }

    # --- Phase 3: gather net→endpoints mapping (derived from pin graph) ----
    from lib.core.connect import derive_nets
    from lib.core.part import NetLabel

    derived_nets = derive_nets(list(schematic._parts))
    # Keep per-connected-component net endpoints separate even when names are equal
    # (e.g. two independent "VCC" islands must NOT be merged into one routed wire).
    net_components: list[tuple[str, list[tuple[float, float]], bool]] = []

    # Build a lookup from Pin identity to its NetLabel owner (if any)
    netlabel_parts = [p for p in schematic._parts if isinstance(p, NetLabel)]

    def _netlabel_component_endpoint(
        netlabel: NetLabel,
        component_pin_ids: set[int],
    ) -> tuple[float, float] | None:
        """Return NetLabel endpoint when it belongs to the target component."""
        label_pin = netlabel.label_pin
        label_key = (label_pin.part_ref, label_pin.key)
        label_endpoint = pin_endpoints.get(label_key)
        if label_endpoint is None:
            return None

        visited: set[int] = set()
        queue = [label_pin]
        while queue:
            current = queue.pop(0)
            current_id = id(current)
            if current_id in visited:
                continue
            visited.add(current_id)
            if current_id in component_pin_ids:
                return label_endpoint
            for neighbor in current.connected_pins:
                if id(neighbor) not in visited:
                    queue.append(neighbor)
        return None

    for net in derived_nets:
        pts: list[tuple[float, float]] = []
        component_pin_ids = {id(pin) for pin in net.pins}
        for pin in net.pins:
            key = (pin.part_ref, pin.key)
            if key in pin_endpoints:
                pts.append(pin_endpoints[key])

        had_single_real_endpoint = len(pts) <= 1
        # NetLabel pins are intentionally excluded from derive_nets()
        # results, but their endpoints must still participate in rendering
        # so wires visibly connect to their label flag.
        for netlabel in netlabel_parts:
            if netlabel.net_name != net.name:
                continue
            label_endpoint = _netlabel_component_endpoint(netlabel, component_pin_ids)
            if label_endpoint is not None:
                pts.append(label_endpoint)

        pts = list(dict.fromkeys(pts))
        if pts:
            net_components.append((net.name, pts, had_single_real_endpoint))

    # Collect component endpoints that are explicitly covered by a NetLabel
    # symbol so wire-level labels can be suppressed for those endpoints.
    label_net_pin_endpoints: list[tuple[str, tuple[float, float]]] = []
    for nl in netlabel_parts:
        nl_pin = nl.label_pin
        for connected_pin in nl_pin.connected_pins:
            key = (connected_pin.part_ref, connected_pin.key)
            if key not in pin_endpoints:
                continue
            label_net_pin_endpoints.append((nl.net_name, pin_endpoints[key]))

    flagged_endpoints_by_net: dict[str, set[tuple[float, float]]] = {}
    for net_name, pt in label_net_pin_endpoints:
        flagged_endpoints_by_net.setdefault(net_name, set()).add(pt)

    # --- Phase 4: draw into a tracking canvas -------------------------------
    canvas = _TrackingCanvas(canvas_w, canvas_h, background=background)

    # Title
    canvas.text(_MARGIN, 20, schematic.name,
                font_size=font_ref, anchor="start", dominant_baseline="middle")

    # Draw all symbols
    for idx, part in enumerate(parts):
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
        if isinstance(part, Junction):
            ref_visible = (part_style.ref_text or TextPlacementStyle.default_ref()).visible
            if part.ref and ref_visible is not False:
                canvas.text(
                    cx,
                    cy,
                    part.ref,
                    font_size=part_font_ref,
                    anchor="middle",
                    dominant_baseline="middle",
                )
            continue
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
    debug_trunks: list[tuple[float, float, float]] = []
    sorted_net_items = sorted(net_components, key=lambda kv: (kv[2], len(kv[1])))
    for net_name, pts, _ in sorted_net_items:
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
            junction_targets=junction_points,
            debug_trunks=debug_trunks if debug else None,
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

    if debug:
        _draw_debug_overlays(
            canvas,
            component_obstacles=debug_component_obstacles,
            trunk_segments=debug_trunks,
            pin_endpoints=pin_endpoints,
        )

    # --- Phase 5: apply fit-to-content viewBox -----------------------------
    return canvas.to_svg_fit(margin=_MARGIN, viewbox=viewbox, fit_size=fit_to_content)


# ---------------------------------------------------------------------------
# Debug overlays
# ---------------------------------------------------------------------------

def _draw_debug_overlays(
    canvas: "_TrackingCanvas",
    *,
    component_obstacles: list[tuple[str, _Obstacle]],
    trunk_segments: list[tuple[float, float, float]],
    pin_endpoints: dict[tuple[str, str], tuple[float, float]],
) -> None:
    """Render debug geometry above all normal schematic elements."""
    obstacle_font = 10.0
    pin_font = 9.0
    trunk_font = 10.0

    for part_ref, obstacle in component_obstacles:
        x = obstacle.x0
        y = obstacle.y0
        width = obstacle.x1 - obstacle.x0
        height = obstacle.y1 - obstacle.y0
        canvas._elements.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" '
            f'fill="rgba(255,0,0,0.2)" stroke="red" stroke-width="1" stroke-dasharray="2,2"/>'
        )
        canvas._track(obstacle.x0, obstacle.y0)
        canvas._track(obstacle.x1, obstacle.y1)
        canvas.text(
            obstacle.x0 + 2.0,
            obstacle.y0 - 6.0,
            part_ref,
            font_size=obstacle_font,
            fill="red",
            anchor="start",
            dominant_baseline="middle",
        )

    for trunk_x, trunk_y_min, trunk_y_max in trunk_segments:
        canvas.line(
            trunk_x,
            trunk_y_min,
            trunk_x,
            trunk_y_max,
            stroke="green",
            stroke_width=2,
            stroke_dasharray="5,5",
        )
        canvas.text(
            trunk_x + 4.0,
            min(trunk_y_min, trunk_y_max) - 8.0,
            f"trunk x={trunk_x:.1f}",
            font_size=trunk_font,
            fill="green",
            anchor="start",
            dominant_baseline="middle",
        )

    for _, (px, py) in pin_endpoints.items():
        canvas.circle(px, py, 3, stroke="none", stroke_width=0, fill="blue")
        canvas.text(
            px + 5.0,
            py - 5.0,
            f"({px:.1f}, {py:.1f})",
            font_size=pin_font,
            fill="blue",
            anchor="start",
            dominant_baseline="middle",
        )


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _netlabel_rotation(direction: str | None, *, fallback: int = 0) -> int:
    """Return clockwise rotation mapped from NetLabel direction."""
    mapping = {
        "right": 0,
        "left": 180,
        "top": 90,
        "bottom": 270,
        "up": 90,
        "down": 270,
    }
    key = (direction or "").strip().lower()
    return mapping.get(key, fallback)


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
    from lib.core.junction import Junction

    if isinstance(part, Junction):
        if not part.pins:
            return {}
        marker_pin = part.junction_pin
        return {(marker_pin.part_ref, marker_pin.key): (cx, cy)}

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

    return _generic_box_pin_endpoints(
        part,
        cx,
        cy,
        box_style=box_style,
        pin_style=pin_style,
    )


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


def _pick_first_horizontal_blocker(
    start_x: float,
    end_x: float,
    blocking: list[_Obstacle],
) -> _Obstacle:
    """Pick the first blocker encountered from *start_x* toward *end_x*."""
    if not blocking:
        raise ValueError("blocking must not be empty")
    moving_left = end_x < start_x
    if moving_left:
        return min(
            blocking,
            key=lambda obstacle: (max(0.0, start_x - obstacle.x1), -obstacle.x1),
        )
    return min(
        blocking,
        key=lambda obstacle: (max(0.0, obstacle.x0 - start_x), obstacle.x0),
    )


def _pick_first_vertical_blocker(
    start_y: float,
    end_y: float,
    blocking: list[_Obstacle],
) -> _Obstacle:
    """Pick the first blocker encountered from *start_y* toward *end_y*."""
    if not blocking:
        raise ValueError("blocking must not be empty")
    moving_up = end_y < start_y
    if moving_up:
        return min(
            blocking,
            key=lambda obstacle: (max(0.0, start_y - obstacle.y1), -obstacle.y1),
        )
    return min(
        blocking,
        key=lambda obstacle: (max(0.0, obstacle.y0 - start_y), obstacle.y0),
    )


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
    junction_targets: set[tuple[float, float]] | None = None,
    debug_trunks: list[tuple[float, float, float]] | None = None,
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
    junction_target_keys = {
        (round(x, 2), round(y, 2))
        for x, y in (junction_targets or set())
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

    def _draw_endpoint_pair(p0: tuple[float, float], p1: tuple[float, float]) -> None:
        if _can_draw_straight(p0, p1, eff_obstacles):
            canvas.line(
                p0[0],
                p0[1],
                p1[0],
                p1[1],
                stroke=wire_color,
                stroke_width=wire_width,
                stroke_dasharray=wire_dash,
            )
            return
        _draw_manhattan_wire(
            canvas,
            p0,
            p1,
            eff_obstacles,
            wire_color=wire_color,
            wire_width=wire_width,
            wire_dash=wire_dash,
        )

    if len(unique_pts) == 2:
        p0, p1 = unique_pts
        _draw_endpoint_pair(p0, p1)
    else:
        explicit_junction_pts = [
            point
            for point in unique_pts
            if (round(point[0], 2), round(point[1], 2)) in junction_target_keys
        ]
        if explicit_junction_pts:
            # Explicit junction components are user-authored tee targets.
            # Route every branch to the selected junction anchor so all
            # connected endpoints visibly terminate at that point.
            anchor = explicit_junction_pts[0]
            for point in unique_pts:
                if point == anchor:
                    continue
                _draw_endpoint_pair(point, anchor)
            bbox_mid_x, bbox_mid_y = anchor
        else:
            # Trunk tree: use median-x trunk, shifted away from obstacles if needed
            sorted_xs = sorted(set(p[0] for p in unique_pts))
            trunk_x = _choose_trunk_x(sorted_xs, unique_pts, eff_obstacles)
            trunk_y = _choose_trunk_y(unique_pts)

            # Phase 2: direct same-y links before trunk routing.
            same_y_groups: dict[float, list[tuple[float, float]]] = {}
            for point in unique_pts:
                same_y_groups.setdefault(round(point[1], 1), []).append(point)

            same_y_links: dict[tuple[float, float], set[tuple[float, float]]] = {}
            for group in same_y_groups.values():
                if len(group) < 2:
                    continue
                ordered = sorted(group, key=lambda point: point[0])
                for left_pt, right_pt in zip(ordered, ordered[1:]):
                    if abs(right_pt[0] - left_pt[0]) <= 0.5:
                        continue
                    if not _can_draw_straight(left_pt, right_pt, eff_obstacles):
                        continue
                    canvas.line(
                        left_pt[0],
                        left_pt[1],
                        right_pt[0],
                        right_pt[1],
                        stroke=wire_color,
                        stroke_width=wire_width,
                        stroke_dasharray=wire_dash,
                    )
                    same_y_links.setdefault(left_pt, set()).add(right_pt)
                    same_y_links.setdefault(right_pt, set()).add(left_pt)

            trunk_skip_points: set[tuple[float, float]] = set()
            visited_same_y: set[tuple[float, float]] = set()
            for start in same_y_links:
                if start in visited_same_y:
                    continue
                stack = [start]
                component: set[tuple[float, float]] = set()
                while stack:
                    point = stack.pop()
                    if point in visited_same_y:
                        continue
                    visited_same_y.add(point)
                    component.add(point)
                    stack.extend(same_y_links.get(point, ()))
                if len(component) < 2:
                    continue
                anchor = min(
                    component,
                    key=lambda point: (
                        abs(point[0] - trunk_x),
                        abs(point[1] - trunk_y),
                        point[0],
                    ),
                )
                for point in component:
                    if point != anchor:
                        trunk_skip_points.add(point)

            trunk_points = [point for point in unique_pts if point not in trunk_skip_points]
            if not trunk_points:
                trunk_points = unique_pts

            trunk_ys = [p[1] for p in trunk_points]
            trunk_y_min = min(trunk_ys)
            trunk_y_max = max(trunk_ys)
            if trunk_y_min > trunk_y:
                trunk_y_min = trunk_y
            if trunk_y_max < trunk_y:
                trunk_y_max = trunk_y
            if debug_trunks is not None:
                debug_trunks.append((trunk_x, trunk_y_min, trunk_y_max))

            # Vertical trunk — split at each on-trunk pin y so that
            # every pin endpoint appears as an explicit wire node.
            on_trunk_ys = sorted({
                py for px, py in trunk_points
                if abs(px - trunk_x) <= 0.5
            })
            # Include trunk boundaries
            split_ys = sorted(set([trunk_y_min] + on_trunk_ys + [trunk_y_max]))
            for seg_i in range(len(split_ys) - 1):
                sy_min = split_ys[seg_i]
                sy_max = split_ys[seg_i + 1]
                if sy_max - sy_min < 0.5:
                    continue
                _draw_vertical_avoiding(
                    canvas, trunk_x, sy_min, sy_max, eff_obstacles,
                    wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash,
                )

            # Horizontal stubs from each trunk-routed point to trunk
            trunk_touch_points: set[tuple[float, float]] = set()
            actual_trunk_connections: dict[tuple[float, float], tuple[float, float]] = {}
            for px, py in trunk_points:
                if abs(px - trunk_x) > 0.5:
                    actual_conn = _draw_horizontal_stub(
                        canvas,
                        px,
                        py,
                        trunk_x,
                        eff_obstacles,
                        trunk_y_span=(trunk_y_min, trunk_y_max),
                        wire_color=wire_color,
                        wire_width=wire_width,
                        wire_dash=wire_dash,
                    )
                    trunk_touch_points.add((px, py))
                    actual_trunk_connections[(px, py)] = actual_conn
                    continue

                trunk_touch_points.add((px, py))

                # Endpoint sits on the trunk x. If the trunk itself must detour
                # around an obstacle that contains this endpoint, add a short
                # escape stub so the endpoint remains electrically connected.
                local_blockers = [
                    obstacle
                    for obstacle in eff_obstacles
                    if obstacle.segment_hits(trunk_x, trunk_y_min, trunk_x, trunk_y_max)
                    and _obstacle_contains_point(obstacle, px, py)
                ]
                if not local_blockers:
                    continue

                blocker = local_blockers[0]
                escape_left = blocker.x0 - _ROUTING_GAP
                escape_right = blocker.x1 + _ROUTING_GAP
                if abs(escape_left - trunk_x) <= abs(escape_right - trunk_x):
                    escape_x = escape_left
                else:
                    escape_x = escape_right

                if _can_draw_straight((px, py), (escape_x, py), eff_obstacles):
                    canvas.line(
                        px,
                        py,
                        escape_x,
                        py,
                        stroke=wire_color,
                        stroke_width=wire_width,
                        stroke_dasharray=wire_dash,
                    )
                else:
                    _draw_segment_avoiding(
                        canvas,
                        px,
                        py,
                        escape_x,
                        py,
                        eff_obstacles,
                        wire_color=wire_color,
                        wire_width=wire_width,
                        wire_dash=wire_dash,
                    )

            # Junctions at trunk intersections:
            # - Any point where a horizontal stub meets the trunk is a potential junction.
            # - We draw a junction dot if a stub meets the trunk AND the trunk passes
            #   through that point (i.e., the trunk extends above or below).
            # - Additionally, draw junctions where 2+ stubs share the same y.
            y_counts = Counter(round(y, 1) for _, y in trunk_touch_points)
            drawn_junction_keys: set[tuple[float, float]] = set()
            for endpoint, actual_conn in actual_trunk_connections.items():
                _, py = endpoint
                actual_x, actual_y = actual_conn
                py_round = round(py, 1)
                # Draw junction if: 2+ stubs at same y, OR this stub hits interior of trunk
                is_interior = trunk_y_min < actual_y < trunk_y_max
                is_multi = y_counts[py_round] >= 2
                if is_interior or is_multi:
                    key = (round(actual_x, 2), round(actual_y, 2))
                    if key in suppressed_keys or key in drawn_junction_keys:
                        continue
                    drawn_junction_keys.add(key)
                    canvas.circle(
                        actual_x,
                        actual_y,
                        junction_r,
                        stroke=junction_color,
                        stroke_width=0,
                        fill=junction_color,
                    )
            
            # Also draw junctions for points directly on trunk (no horizontal stub)
            for _, py in trunk_touch_points:
                if (_, py) in actual_trunk_connections:
                    continue  # Already handled above
                py_round = round(py, 1)
                # Draw junction if: 2+ stubs at same y, OR this stub hits interior of trunk
                is_interior = trunk_y_min < py < trunk_y_max
                is_multi = y_counts[py_round] >= 2
                if is_interior or is_multi:
                    key = (round(trunk_x, 2), round(py, 2))
                    if key in suppressed_keys or key in drawn_junction_keys:
                        continue
                    drawn_junction_keys.add(key)
                    canvas.circle(
                        trunk_x,
                        py,
                        junction_r,
                        stroke=junction_color,
                        stroke_width=0,
                        fill=junction_color,
                    )

            # Update label position to chosen trunk axis and aligned y.
            bbox_mid_x = trunk_x
            bbox_mid_y = trunk_y

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

    step = max(_OBSTACLE_CLEARANCE * 2, _ROUTING_GAP)
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

    # Smart seeds around each pin and around blockers that intersect trunk span.
    for px, _ in pts:
        add_candidate(px + step)
        add_candidate(px - step)

    for obstacle in obstacles:
        if obstacle.y1 < y_min - 0.5 or obstacle.y0 > y_max + 0.5:
            continue
        add_candidate(obstacle.x0 - step)
        add_candidate(obstacle.x1 + step)

    if not candidates:
        return median_x  # fallback — best effort

    def _can_join_stub_on_trunk(tx: float, py: float, detour_y: float) -> bool:
        if not (y_min - 0.5 <= detour_y <= y_max + 0.5):
            return False
        return not _any_obstacle_hit(obstacles, tx, detour_y, tx, py)

    def stub_route_penalty(tx: float) -> tuple[int, int, float, float]:
        """Return (hard_blocks, all_blocks, backtrack_count, backtrack_depth_sum)."""
        hard_blocks = 0
        all_blocks = 0
        backtrack_count = 0.0
        backtrack_depth_sum = 0.0
        for px, py in pts:
            if abs(px - tx) <= 0.5:
                continue
            blocking = [o for o in obstacles if o.segment_hits(px, py, tx, py)]
            if not blocking:
                continue
            all_blocks += 1
            endpoint_only = all(_obstacle_contains_point(o, px, py) for o in blocking)
            if not endpoint_only:
                hard_blocks += 1

            first_blocker = _pick_first_horizontal_blocker(px, tx, blocking)
            detour_y_top = first_blocker.y0 - _ROUTING_GAP
            detour_y_bot = first_blocker.y1 + _ROUTING_GAP
            detour_options = [detour_y_top, detour_y_bot]
            best_detour_y = min(
                detour_options,
                key=lambda candidate: (
                    0 if _can_join_stub_on_trunk(tx, py, candidate) else 1,
                    abs(candidate - py),
                ),
            )
            if not _can_join_stub_on_trunk(tx, py, best_detour_y):
                backtrack_count += 1.0
                backtrack_depth_sum += abs(py - best_detour_y)

        return hard_blocks, all_blocks, backtrack_count, backtrack_depth_sum

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

    def score(tx: float) -> tuple[float, float, float, float, float, float, float, float]:
        constrained_on_trunk = sum(
            1
            for px, py in pts
            if abs(px - tx) <= 0.5
            and any(isinstance(o, _Obstacle) and _obstacle_contains_point(o, px, py) for o in obstacles)
        )
        hard_blocks, all_blocks, backtrack_count, backtrack_depth_sum = stub_route_penalty(tx)
        total_stub_len = sum(abs(px - tx) for px, _ in pts)
        anchor_bias = abs(tx - anchor_x) if anchor_x is not None else 0.0
        return (
            float(constrained_on_trunk),
            float(hard_blocks),
            float(all_blocks),
            backtrack_count,
            backtrack_depth_sum,
            anchor_bias,
            total_stub_len,
            abs(tx - median_x),
        )

    scored_candidates = [(score(tx), tx) for tx in candidates]
    clear_backtrack_free = [
        (sc, tx) for sc, tx in scored_candidates
        if sc[1] <= 0.0 and sc[2] <= 0.0 and sc[3] <= 0.0
    ]
    if clear_backtrack_free:
        return min(
            clear_backtrack_free,
            key=lambda item: (item[0][5], item[0][6], item[0][7]),
        )[1]
    return min(scored_candidates, key=lambda item: item[0])[1]


def _choose_trunk_y(
    pts: list[tuple[float, float]],
) -> float:
    """Pick trunk-y by the most frequently occurring endpoint y."""
    if not pts:
        raise ValueError("pts must not be empty")
    y_counts = Counter(round(y, 1) for _, y in pts)
    return float(y_counts.most_common(1)[0][0])


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
    gap = max(abs(_OBSTACLE_CLEARANCE), 6.0)

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
) -> tuple[float, float]:
    """Draw a horizontal stub from (px, py) to (trunk_x, py).

    If the straight segment passes through an obstacle, a 3-segment detour
    is drawn around the obstacle (going above or below it).
    
    Returns the actual connection point on the trunk (may differ from trunk_x if detour occurred).
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
        return (trunk_x, py)

    # Find the blocking obstacle and route around it
    blocking = [o for o in obstacles if o.segment_hits(px, py, trunk_x, py)]
    if not blocking:
        canvas.line(
            px, py, trunk_x, py,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return (trunk_x, py)

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
        return (trunk_x, py)

    obs = _pick_first_horizontal_blocker(px, trunk_x, blocking)
    # Detour above or below the obstacle
    gap = _ROUTING_GAP
    detour_y_top = obs.y0 - gap
    detour_y_bot = obs.y1 + gap

    def _can_join_trunk_without_backtrack(detour_y: float) -> bool:
        if trunk_y_span is None:
            return False
        trunk_y_min, trunk_y_max = trunk_y_span
        if not (trunk_y_min - 0.5 <= detour_y <= trunk_y_max + 0.5):
            return False
        return not _any_obstacle_hit(obstacles, trunk_x, detour_y, trunk_x, py)

    def _detour_segments_clear(detour_y: float) -> bool:
        return (
            not _any_obstacle_hit(obstacles, px, py, px, detour_y)
            and not _any_obstacle_hit(obstacles, px, detour_y, trunk_x, detour_y)
        )

    detour_candidates = [detour_y_top, detour_y_bot]
    if trunk_y_span is not None:
        trunk_y_min, trunk_y_max = trunk_y_span
        detour_candidates.extend([trunk_y_min, trunk_y_max])
    deduped_candidates = list(dict.fromkeys(detour_candidates))
    dy = min(
        deduped_candidates,
        key=lambda candidate: (
            0 if _detour_segments_clear(candidate) else 1,
            0 if _can_join_trunk_without_backtrack(candidate) else 1,
            0.0 if _can_join_trunk_without_backtrack(candidate) else abs(candidate - py),
            abs(candidate - py),
        ),
    )
    join_without_backtrack = _can_join_trunk_without_backtrack(dy)

    # 3-segment path: (px,py) → (px,dy) → (trunk_x,dy) → (trunk_x,py)
    # If detour_y already intersects a clear trunk segment, stop there to avoid
    # drawing a local backtracking rectangle near the destination pin.
    if abs(py - dy) > 0.5:
        canvas.line(
            px, py, px, dy,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
    canvas.line(
        px, dy, trunk_x, dy,
        stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
    )
    if not join_without_backtrack and abs(py - dy) > 0.5:
        canvas.line(
            trunk_x, dy, trunk_x, py,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
    
    # Return the actual connection point on the trunk
    if join_without_backtrack:
        return (trunk_x, dy)
    else:
        return (trunk_x, py)


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

    h_first_clear = _can_draw_straight((x0, y0), (x1, y0), obstacles)
    h_first_blocked = not h_first_clear
    h_second_clear = h_first_clear and _can_draw_straight((x1, y0), (x1, y1), obstacles)
    v_first_clear = _can_draw_straight((x0, y0), (x0, y1), obstacles)
    v_first_blocked = not v_first_clear
    v_second_clear = v_first_clear and _can_draw_straight((x0, y1), (x1, y1), obstacles)

    if h_first_clear and h_second_clear:
        canvas.line(
            x0, y0, x1, y0,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            x1, y0, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    if v_first_clear and v_second_clear:
        canvas.line(
            x0, y0, x0, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            x0, y1, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    blocking: list[_Obstacle] = []
    for obstacle in obstacles:
        if (
            obstacle.segment_hits(x0, y0, x1, y0)
            or obstacle.segment_hits(x1, y0, x1, y1)
            or obstacle.segment_hits(x0, y0, x0, y1)
            or obstacle.segment_hits(x0, y1, x1, y1)
        ):
            blocking.append(obstacle)

    if not blocking:
        # No obstacle consistently blocks either L-route segment.
        # Preserve historical H-first fallback for deterministic output.
        canvas.line(
            x0, y0, x1, y0,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        canvas.line(
            x1, y0, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    def _route_h_first_with_avoidance() -> None:
        _draw_segment_avoiding(
            canvas, x0, y0, x1, y0, obstacles,
            wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash,
        )
        _draw_segment_avoiding(
            canvas, x1, y0, x1, y1, obstacles,
            wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash,
        )

    def _route_v_first_with_avoidance() -> None:
        _draw_segment_avoiding(
            canvas, x0, y0, x0, y1, obstacles,
            wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash,
        )
        _draw_segment_avoiding(
            canvas, x0, y1, x1, y1, obstacles,
            wire_color=wire_color, wire_width=wire_width, wire_dash=wire_dash,
        )

    if h_first_clear and not v_first_clear:
        _route_h_first_with_avoidance()
        return
    if v_first_clear and not h_first_clear:
        _route_v_first_with_avoidance()
        return
    if h_first_clear and v_first_clear:
        h_rank = (0 if h_second_clear else 1, abs(y1 - y0), abs(x1 - x0))
        v_rank = (0 if v_second_clear else 1, abs(x1 - x0), abs(y1 - y0))
        if h_rank <= v_rank:
            _route_h_first_with_avoidance()
        else:
            _route_v_first_with_avoidance()
        return

    # Both L-routes blocked → detour around the first blocking obstacle
    obs = blocking[0]
    gap = _ROUTING_GAP

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
    if _can_draw_straight((x0, y0), (x1, y1), obstacles):
        canvas.line(
            x0, y0, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    blocking = [
        obstacle
        for obstacle in obstacles
        if obstacle.segment_hits(x0, y0, x1, y1)
        and not (
            _obstacle_contains_point(obstacle, x0, y0)
            and _moves_outward_from_obstacle(obstacle, (x0, y0), (x1, y1))
        )
        and not (
            _obstacle_contains_point(obstacle, x1, y1)
            and _moves_outward_from_obstacle(obstacle, (x1, y1), (x0, y0))
        )
    ]
    if not blocking:
        canvas.line(
            x0, y0, x1, y1,
            stroke=wire_color, stroke_width=wire_width, stroke_dasharray=wire_dash
        )
        return

    gap = _ROUTING_GAP

    # Horizontal segment blocked → detour above or below
    if abs(y0 - y1) < 0.5:
        obs = _pick_first_horizontal_blocker(x0, x1, blocking)
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
    obs = _pick_first_vertical_blocker(y0, y1, blocking)
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

    def to_svg_fit(self, margin: float = 40, viewbox: tuple[float, float, float, float] | None = None, fit_size: bool = False) -> str:
        """Return SVG string with viewBox fitted to content + *margin*.

        Args:
            margin: Extra whitespace around tracked content in viewBox units.
            viewbox: Optional explicit (x, y, w, h) to override fit-to-content.
            fit_size: If True, set SVG width/height to match the viewBox dimensions
                      instead of the original canvas size (fit-to-content output).
        """
        if viewbox is not None:
            vb_x, vb_y, vb_w, vb_h = viewbox
        elif self._min_x == float("inf"):
            # Nothing was drawn — fall back to full-page viewBox
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
        else:
            vb_x = self._min_x - margin
            vb_y = self._min_y - margin
            vb_w = (self._max_x - self._min_x) + 2 * margin
            vb_h = (self._max_y - self._min_y) + 2 * margin
            # Clamp to non-negative
            vb_w = max(vb_w, 1)
            vb_h = max(vb_h, 1)

        svg_w = f"{vb_w:.1f}" if fit_size else f"{self._width}"
        svg_h = f"{vb_h:.1f}" if fit_size else f"{self._height}"
        header = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg"'
            f' width="{svg_w}" height="{svg_h}"'
            f' viewBox="{vb_x:.1f} {vb_y:.1f} {vb_w:.1f} {vb_h:.1f}">\n'
        )
        if self._background and self._background != "none":
            header += (
                f'  <rect width="100%" height="100%"'
                f' fill="{self._background}"/>\n'
            )
        body = "\n".join(f"  {el}" for el in self._elements)
        return header + body + "\n</svg>\n"
