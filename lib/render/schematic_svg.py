"""Schematic-level SVG renderer.

Renders each Part in the schematic.  Recognised symbol types get their
native graphic; all other parts fall back to a generic box.

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
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, List, Optional, Tuple

from lib.render.svg_renderer import SvgCanvas
from lib.render.symbol_renderer import SymbolRenderer

if TYPE_CHECKING:
    from lib.core.schematic import Schematic
    from lib.core.part import Part
    from lib.core.page import PageConfig
    from lib.core.render_style import RenderTemplate as _RenderTemplateT


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

_MARGIN = 40            # fit-to-content outer margin (px)
_COL_WIDTH = 180        # auto-layout: horizontal spacing between column centres
_ROW_HEIGHT = 140       # auto-layout: vertical spacing between parts in a column
_PARTS_PER_COL = 4      # max parts per column before wrapping to a new column

# Symbol size constants
_BOX_W = 80             # generic box width
_BOX_MIN_H = 40         # minimum generic box height
_BOX_PIN_ROW = 16       # height per pin row in auto-sized generic box
_PIN_STUB = 20          # pin stub length from box edge

# Font sizes (minimum readable values)
_FONT_REF = 14
_FONT_NET = 12
_FONT_VALUE = 11
_FONT_PIN = 10

# Wire style
_WIRE_COLOR = "#1565c0"
_WIRE_WIDTH = 1.8
_JUNCTION_R = 3.5       # junction dot radius
_JUNCTION_COLOR = "#1565c0"

# Label halo (white background behind net labels)
_LABEL_HALO_PAD = 2     # padding around label text for the halo rect
_LABEL_HALO_FILL = "white"
_LABEL_HALO_OPACITY = "0.85"

# Obstacle avoidance
_OBSTACLE_CLEARANCE = 6  # px of extra clearance added around each component AABB

# Cross-net wire avoidance
_WIRE_SEG_CLEARANCE = 4   # px clearance zone around each drawn wire segment
_WIRE_SEG_HALF = _WIRE_SEG_CLEARANCE  # half-width of the fattened segment obstacle


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
    from lib.core.render_style import (
        RenderTemplate as _RenderTemplate,
        WireStyle, NetLabelStyle, HaloStyle, BoxStyle, PinStyle, RenderStyle,
    )

    # Resolve template → style sub-objects
    if template is None:
        tmpl = _RenderTemplate.default()
    else:
        tmpl = template

    # Merge with defaults so None sub-fields fall back cleanly
    base_style = RenderStyle.default()
    effective_style = base_style.merge(tmpl.style)

    wire_style: WireStyle = effective_style.wire or WireStyle.default()
    ln_style: NetLabelStyle = effective_style.label_net or NetLabelStyle.default()
    halo_style: HaloStyle = effective_style.halo or HaloStyle.default()
    box_style: BoxStyle = effective_style.box or BoxStyle.default()
    pin_style: PinStyle = effective_style.pin or PinStyle.default()

    # Resolved style scalars — used throughout this function
    wire_color: str = wire_style.color or _WIRE_COLOR
    wire_width: float = wire_style.width if wire_style.width is not None else _WIRE_WIDTH
    junction_r: float = wire_style.junction_radius if wire_style.junction_radius is not None else _JUNCTION_R
    wire_dash: Optional[str] = wire_style.dash  # None → solid

    ln_color: str = ln_style.color or "#000000"
    ln_font_size: float = ln_style.font_size if ln_style.font_size is not None else _FONT_NET
    ln_font_style: str = ln_style.font_style or "italic"
    ln_overline: bool = ln_style.overline if ln_style.overline is not None else True
    ln_body_fill: str = ln_style.body_fill or "#ffffff"
    ln_body_stroke_width: float = ln_style.body_stroke_width if ln_style.body_stroke_width is not None else 1.2
    ln_stem_stroke_width: float = ln_style.stem_stroke_width if ln_style.stem_stroke_width is not None else 1.4

    halo_fill: str = halo_style.fill or _LABEL_HALO_FILL
    halo_opacity: str = halo_style.opacity or _LABEL_HALO_OPACITY
    halo_pad: float = halo_style.pad if halo_style.pad is not None else _LABEL_HALO_PAD

    box_stroke: str = box_style.stroke or "#333"
    box_stroke_width: float = box_style.stroke_width if box_style.stroke_width is not None else 1.8
    box_fill: str = box_style.fill or "none"

    pin_stub_stroke: str = pin_style.stub_stroke or "#555"
    pin_stub_stroke_width: float = pin_style.stub_stroke_width if pin_style.stub_stroke_width is not None else 1.5
    pin_key_fill: str = pin_style.key_fill or "#333"
    pin_value_fill: str = pin_style.value_fill or "#555"

    symbol_renderer = SymbolRenderer(
        primitive_stroke=box_stroke,
        primitive_stroke_width=box_stroke_width,
        pin_stub_stroke=pin_stub_stroke,
        pin_stub_width=pin_stub_stroke_width,
        pin_text_fill=pin_key_fill,
        value_text_fill=pin_value_fill,
    )

    background: str = effective_style.background or "#ffffff"
    font_ref: float = effective_style.ref_font_size if effective_style.ref_font_size is not None else _FONT_REF
    font_net: float = effective_style.net_font_size if effective_style.net_font_size is not None else _FONT_NET
    font_value: float = effective_style.value_font_size if effective_style.value_font_size is not None else _FONT_VALUE
    font_pin: float = effective_style.pin_font_size if effective_style.pin_font_size is not None else _FONT_PIN

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
    from lib.core.part import NetLabel

    parts = schematic.parts
    positions: dict[str, tuple[float, float]] = {}
    for idx, part in enumerate(parts):
        if isinstance(part, NetLabel):
            continue
        cx, cy = _part_position(part, idx, canvas_w, canvas_h, len(parts))
        ref = part.ref or f"_part{idx}"
        positions[ref] = (cx, cy)

    # --- Phase 1b: build obstacle list (one per component body) -------------
    obstacles: list[_Obstacle] = []
    for idx, part in enumerate(parts):
        if isinstance(part, NetLabel):
            continue
        ref = part.ref or f"_part{idx}"
        cx, cy = positions[ref]
        lib_id = part.lib_id or ""
        symbol_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
        obs = _component_obstacle(
            part,
            cx,
            cy,
            symbol_name,
            symbol_renderer=symbol_renderer,
        )
        obstacles.append(obs)

    # --- Phase 2: compute pin endpoints (world coords) ----------------------
    # pin_endpoints[(part_ref, pin_key)] = (px, py)
    pin_endpoints: dict[tuple[str, str], tuple[float, float]] = {}
    for idx, part in enumerate(parts):
        if isinstance(part, NetLabel):
            continue
        ref = part.ref or f"_part{idx}"
        cx, cy = positions[ref]
        lib_id = part.lib_id or ""
        symbol_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
        ep = _compute_pin_endpoints(
            part,
            cx,
            cy,
            symbol_name,
            symbol_renderer=symbol_renderer,
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

    # --- Phase 4: draw into a tracking canvas -------------------------------
    canvas = _TrackingCanvas(canvas_w, canvas_h, background=background)

    # Title
    canvas.text(canvas_w / 2, 20, schematic.name,
                font_size=font_ref, anchor="middle", dominant_baseline="middle")

    # Draw all symbols
    for idx, part in enumerate(parts):
        if isinstance(part, NetLabel):
            continue
        ref = part.ref or f"_part{idx}"
        cx, cy = positions[ref]
        lib_id = part.lib_id or ""
        symbol_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
        rotation = getattr(part.get_style(), "rotation", 0)
        used_symbol_path = symbol_renderer.render_part(
            canvas,
            part,
            cx,
            cy,
            symbol_name=symbol_name,
            rotation=rotation,
            font_ref=font_ref,
            font_value=font_value,
            font_pin=font_pin,
        )
        if not used_symbol_path:
            _render_generic_box(canvas, part, cx, cy,
                                font_ref=font_ref,
                                font_value=font_value,
                                font_pin=font_pin,
                                box_stroke=box_stroke,
                                box_stroke_width=box_stroke_width,
                                box_fill=box_fill,
                                pin_stub_stroke=pin_stub_stroke,
                                pin_stub_stroke_width=pin_stub_stroke_width,
                                pin_key_fill=pin_key_fill,
                                pin_value_fill=pin_value_fill)

    # Draw wires for each net.
    # Route nets with fewer pins first so that simple 2-pin wires (e.g. VCC/GND)
    # are committed before complex trunk trees.  This gives the trunk router a
    # chance to detect and avoid the already-drawn wire segments.
    drawn_segs: list[_WireSegment] = []
    sorted_net_items = sorted(net_components, key=lambda kv: len(kv[1]))
    for net_name, pts in sorted_net_items:
        _draw_wire_net(
            canvas, pts, net_name, obstacles, drawn_segs,
            wire_color=wire_color, wire_width=wire_width,
            junction_r=junction_r, font_net=font_net,
            halo_fill=halo_fill, halo_opacity=halo_opacity, halo_pad=halo_pad,
        )

    # Draw NetLabel flag labels (one per pin, no wire routing).
    # All side='left' labels share a unified tip_x so their bodies align
    # to the same vertical column (avoids ragged stagger across pin offsets).
    _left_xs = [pt[0] for _, pt, side, _ in label_net_pin_endpoints if side == "left"]
    left_align_x: float | None = max(_left_xs) if _left_xs else None

    seen_label_pts: set[tuple[float, float]] = set()
    occupied_label_slots: dict[tuple[str, int, int], int] = {}
    for net_name, pt, side, auto_side in label_net_pin_endpoints:
        if pt not in seen_label_pts:
            seen_label_pts.add(pt)
            selected_side = side
            selected_align_x = left_align_x if selected_side == "left" else None

            # Keep labels from sitting on component bodies:
            # 1) preferred side  2) auto side  3) opposite side  4) vertical fallback
            opposite_side = "left" if side == "right" else "right"
            candidate_sides: list[str] = [side, auto_side, opposite_side, "top", "bottom"]
            unique_candidates: list[str] = []
            for candidate in candidate_sides:
                if candidate not in unique_candidates:
                    unique_candidates.append(candidate)

            for candidate in unique_candidates:
                candidate_align_x = left_align_x if candidate == "left" else None
                if not _flag_label_hits_obstacles(
                    pt[0], pt[1], net_name,
                    side=candidate, align_x=candidate_align_x,
                    obstacles=obstacles, ln_font_size=ln_font_size,
                ):
                    selected_side = candidate
                    selected_align_x = candidate_align_x
                    break
            else:
                nudge_candidates = [auto_side, opposite_side, side]
                for candidate in nudge_candidates:
                    if candidate not in {"left", "right"}:
                        continue
                    candidate_align_x = left_align_x if candidate == "left" else None
                    nudged_align_x = _nudge_horizontal_flag_tip(
                        pt[0], pt[1], net_name,
                        side=candidate, align_x=candidate_align_x,
                        obstacles=obstacles, ln_font_size=ln_font_size,
                    )
                    if nudged_align_x is None:
                        continue
                    if not _flag_label_hits_obstacles(
                        pt[0], pt[1], net_name,
                        side=candidate, align_x=nudged_align_x,
                        obstacles=obstacles, ln_font_size=ln_font_size,
                    ):
                        selected_side = candidate
                        selected_align_x = nudged_align_x
                        break

            draw_x, draw_y = pt[0], pt[1]
            # De-overlap labels that resolve to the same slot (same net + near-identical text center).
            for _ in range(4):
                _, _, _, _, _, _, tx, ty = _flag_label_geometry(
                    draw_x,
                    draw_y,
                    net_name,
                    side=selected_side,
                    ln_font_size=ln_font_size,
                    align_x=selected_align_x,
                )
                slot = (net_name, int(round(tx)), int(round(ty)))
                n = occupied_label_slots.get(slot, 0)
                if n == 0:
                    occupied_label_slots[slot] = 1
                    break
                draw_y += 12.0

            _draw_flag_label(
                canvas, draw_x, draw_y, net_name, side=selected_side, align_x=selected_align_x,
                wire_color=wire_color,
                ln_color=ln_color,
                ln_font_size=ln_font_size,
                ln_font_style=ln_font_style,
                ln_body_fill=ln_body_fill,
                ln_body_stroke_width=ln_body_stroke_width,
                ln_stem_stroke_width=ln_stem_stroke_width,
                halo_fill=halo_fill,
                halo_opacity=halo_opacity,
            )

    # --- Phase 5: apply fit-to-content viewBox -----------------------------
    return canvas.to_svg_fit(margin=_MARGIN)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _part_position(
    part: "Part",
    idx: int,
    total_w: float,
    total_h: float,
    n_parts: int,
) -> tuple[float, float]:
    """Return (cx, cy) for a part.

    Priority:
    1. Explicit Style(x, y) — scaled to SVG coords.
    2. Column-based auto-layout: parts are grouped into columns of at most
       ``_PARTS_PER_COL`` rows, arranged left-to-right.  Within each column
       parts are stacked vertically and centred.
    """
    style = part.get_style()
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

def _box_height(n_pins: int) -> float:
    """Compute auto-sized box height for *n_pins* pins."""
    n_side = max(1, math.ceil(n_pins / 2))
    return max(_BOX_MIN_H, n_side * _BOX_PIN_ROW)


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
) -> _Obstacle:
    """Return the routing obstacle (expanded AABB) for a component."""
    renderer = symbol_renderer or SymbolRenderer()
    rotation = getattr(part.get_style(), "rotation", 0)
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

    pins = list(part.pins.items())
    h = _box_height(len(pins))
    w = _BOX_W
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
) -> dict[tuple[str, str], tuple[float, float]]:
    """Return {(part_ref, pin_key): (px, py)} for all pins of *part*."""
    renderer = symbol_renderer or SymbolRenderer()
    rotation = getattr(part.get_style(), "rotation", 0)
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

    return _generic_box_pin_endpoints(part, cx, cy)


def _generic_box_pin_endpoints(
    part: "Part",
    cx: float,
    cy: float,
) -> dict[tuple[str, str], tuple[float, float]]:
    """Pin endpoints for generic box, matching _render_generic_box geometry."""
    ref = part.ref or "?"
    pins = list(part.pins.items())
    h = _box_height(len(pins))
    w = _BOX_W
    x0, y0 = cx - w / 2, cy - h / 2
    result: dict[tuple[str, str], tuple[float, float]] = {}

    n_left = math.ceil(len(pins) / 2)
    for i, (pin_key, _) in enumerate(pins):
        if i < n_left:
            # Left side
            row = i
            py = y0 + (row + 0.5) * (h / n_left)
            ex = x0 - _PIN_STUB
            result[(ref, pin_key)] = (ex, py)
        else:
            # Right side
            row = i - n_left
            n_right = len(pins) - n_left
            py = y0 + (row + 0.5) * (h / max(n_right, 1))
            ex = x0 + w + _PIN_STUB
            result[(ref, pin_key)] = (ex, py)

    return result


# ---------------------------------------------------------------------------
# Wire routing
# ---------------------------------------------------------------------------

def _extract_wire_segs_from_elements(
    elements: list[str], start: int, *, wire_color: str = _WIRE_COLOR
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
    wire_marker = f'stroke="{wire_color}"'
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
    wire_color: str = _WIRE_COLOR,
    wire_width: float = _WIRE_WIDTH,
    junction_r: float = _JUNCTION_R,
    font_net: float = _FONT_NET,
    halo_fill: str = _LABEL_HALO_FILL,
    halo_opacity: str = _LABEL_HALO_OPACITY,
    halo_pad: float = _LABEL_HALO_PAD,
) -> None:
    """Draw Manhattan wire routes connecting all endpoints in *pts*.

    Uses obstacle-aware routing to avoid drawing wires through component
    bodies.  See module docstring for the full algorithm description.

    *drawn_segs* is a shared list of _WireSegment objects from previously
    routed nets.  These act as soft obstacles so that later nets reroute
    around already-drawn wires, preventing visual crossings.
    """
    is_anon = net_name.startswith("_anon")

    if len(pts) < 1:
        return

    unique_pts = list(dict.fromkeys(pts))  # deduplicate preserving order

    # Single-pin net: no wire to draw but still show the net name label
    if len(unique_pts) == 1 and not is_anon:
        px, py = unique_pts[0]
        _draw_net_label(canvas, px, py - 10, net_name,
                        wire_color=wire_color, font_net=font_net,
                        halo_fill=halo_fill, halo_opacity=halo_opacity, halo_pad=halo_pad)
        return

    if len(unique_pts) < 2:
        return

    is_anon = net_name.startswith("_anon")

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
                             wire_color=wire_color, wire_width=wire_width)
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
                wire_color=wire_color, wire_width=wire_width,
            )

        # Horizontal stubs from each point to trunk
        for px, py in unique_pts:
            if abs(px - trunk_x) > 0.5:
                _draw_horizontal_stub(canvas, px, py, trunk_x, eff_obstacles,
                                      wire_color=wire_color, wire_width=wire_width)

        # Junctions at trunk intersections:
        # - Any point where a horizontal stub meets the trunk is a potential junction.
        # - We draw a junction dot if a stub meets the trunk AND the trunk passes
        #   through that point (i.e., the trunk extends above or below).
        # - Additionally, draw junctions where 2+ stubs share the same y.
        y_counts = Counter(round(y, 1) for y in trunk_ys)
        for (px, py) in unique_pts:
            py_round = round(py, 1)
            # Draw junction if: 2+ stubs at same y, OR this stub hits interior of trunk
            is_interior = trunk_y_min < py < trunk_y_max
            is_multi = y_counts[py_round] >= 2
            if is_interior or is_multi:
                canvas.circle(trunk_x, py, junction_r,
                              stroke=wire_color, stroke_width=0,
                              fill=wire_color)

        # Update label position to trunk midpoint
        bbox_mid_x = trunk_x
        bbox_mid_y = (trunk_y_min + trunk_y_max) / 2

    # Capture newly-drawn wire segments and append to drawn_segs
    if drawn_segs is not None:
        new_segs = _extract_wire_segs_from_elements(canvas._elements, el_start,
                                                     wire_color=wire_color)
        drawn_segs.extend(new_segs)

    # Draw wire-net label for named nets (not anonymous)
    if not is_anon:
        _draw_net_label(canvas, bbox_mid_x, bbox_mid_y - 10, net_name,
                        wire_color=wire_color, font_net=font_net,
                        halo_fill=halo_fill, halo_opacity=halo_opacity, halo_pad=halo_pad)


def _choose_trunk_x(
    sorted_xs: list[float],
    pts: list[tuple[float, float]],
    obstacles: list[_Obstacle],
) -> float:
    """Pick a trunk x that avoids passing through any obstacle body.

    Starts from the median x of the pin endpoints.  If the vertical segment
    at that x would pass through an obstacle the function tries nearby x
    values (stepping by _OBSTACLE_CLEARANCE) until a clear path is found or
    candidates are exhausted (falls back to median).
    """
    median_x = sorted_xs[len(sorted_xs) // 2]
    ys = [p[1] for p in pts]
    y_min, y_max = min(ys), max(ys)

    def trunk_clear(tx: float) -> bool:
        return not _any_obstacle_hit(obstacles, tx, y_min, tx, y_max)

    if trunk_clear(median_x):
        return median_x

    step = _OBSTACLE_CLEARANCE * 2
    for delta in range(1, 20):
        for candidate in (median_x + delta * step, median_x - delta * step):
            if trunk_clear(candidate):
                return candidate

    return median_x  # fallback — best effort


def _draw_vertical_avoiding(
    canvas: "_TrackingCanvas",
    x: float,
    y_min: float,
    y_max: float,
    obstacles: list[_Obstacle],
    *,
    wire_color: str = _WIRE_COLOR,
    wire_width: float = _WIRE_WIDTH,
) -> None:
    """Draw a vertical wire from (x, y_min) to (x, y_max), routing around obstacles.

    If any obstacle blocks the straight vertical segment, the trunk is split:
    a 3-segment detour goes left or right around the blocking obstacle.
    The detour direction (left/right) is chosen to minimise extra wire length.
    Only one level of re-routing is attempted per obstacle to avoid unbounded
    recursion; if the detour sub-segments are also blocked the code falls back
    to a straight line for that sub-segment.
    """
    gap = _OBSTACLE_CLEARANCE

    # Collect obstacles that block the vertical trunk segment
    blocking = [o for o in obstacles if o.segment_hits(x, y_min, x, y_max)]
    if not blocking:
        canvas.line(x, y_min, x, y_max, stroke=wire_color, stroke_width=wire_width)
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
        canvas.line(x, enter_y, dx, enter_y, stroke=wire_color, stroke_width=wire_width)
        canvas.line(dx, enter_y, dx, exit_y, stroke=wire_color, stroke_width=wire_width)
        canvas.line(dx, exit_y, x, exit_y, stroke=wire_color, stroke_width=wire_width)

        current_y = exit_y

    # Draw remaining straight segment to y_max
    if y_max > current_y + 0.5:
        canvas.line(
            x, current_y, x, y_max,
            stroke=wire_color, stroke_width=wire_width,
        )


def _draw_horizontal_stub(
    canvas: "_TrackingCanvas",
    px: float,
    py: float,
    trunk_x: float,
    obstacles: list[_Obstacle],
    *,
    wire_color: str = _WIRE_COLOR,
    wire_width: float = _WIRE_WIDTH,
) -> None:
    """Draw a horizontal stub from (px, py) to (trunk_x, py).

    If the straight segment passes through an obstacle, a 3-segment detour
    is drawn around the obstacle (going above or below it).
    """
    if not _any_obstacle_hit(obstacles, px, py, trunk_x, py):
        canvas.line(px, py, trunk_x, py, stroke=wire_color, stroke_width=wire_width)
        return

    # Find the blocking obstacle and route around it
    blocking = [o for o in obstacles if o.segment_hits(px, py, trunk_x, py)]
    if not blocking:
        canvas.line(px, py, trunk_x, py, stroke=wire_color, stroke_width=wire_width)
        return

    obs = blocking[0]
    # Detour above or below the obstacle
    gap = _OBSTACLE_CLEARANCE
    detour_y_top = obs.y0 - gap
    detour_y_bot = obs.y1 + gap

    # Pick the detour direction closest to the current y
    if abs(detour_y_top - py) <= abs(detour_y_bot - py):
        dy = detour_y_top
    else:
        dy = detour_y_bot

    # 3-segment path: (px,py) → (px,dy) → (trunk_x,dy) → (trunk_x,py)
    canvas.line(px, py, px, dy, stroke=wire_color, stroke_width=wire_width)
    canvas.line(px, dy, trunk_x, dy, stroke=wire_color, stroke_width=wire_width)
    canvas.line(trunk_x, dy, trunk_x, py, stroke=wire_color, stroke_width=wire_width)


def _draw_manhattan_wire(
    canvas: "_TrackingCanvas",
    p0: tuple[float, float],
    p1: tuple[float, float],
    obstacles: list[_Obstacle],
    *,
    wire_color: str = _WIRE_COLOR,
    wire_width: float = _WIRE_WIDTH,
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
    x0, y0 = p0
    x1, y1 = p1

    if abs(x0 - x1) < 0.5 or abs(y0 - y1) < 0.5:
        # Already aligned — draw with possible detour
        _draw_segment_avoiding(canvas, x0, y0, x1, y1, obstacles,
                               wire_color=wire_color, wire_width=wire_width)
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
        canvas.line(x0, y0, x1, y0, stroke=wire_color, stroke_width=wire_width)
        canvas.line(x1, y0, x1, y1, stroke=wire_color, stroke_width=wire_width)
        return

    if v_ok:
        canvas.line(x0, y0, x0, y1, stroke=wire_color, stroke_width=wire_width)
        canvas.line(x0, y1, x1, y1, stroke=wire_color, stroke_width=wire_width)
        return

    # Both L-routes blocked → detour around the first blocking obstacle
    blocking: list[_Obstacle] = []
    for o in obstacles:
        if (o.segment_hits(x0, y0, x1, y0) or o.segment_hits(x1, y0, x1, y1)
                or o.segment_hits(x0, y0, x0, y1) or o.segment_hits(x0, y1, x1, y1)):
            blocking.append(o)

    if not blocking:
        # Nothing actually blocks — fall back to H-first
        canvas.line(x0, y0, x1, y0, stroke=wire_color, stroke_width=wire_width)
        canvas.line(x1, y0, x1, y1, stroke=wire_color, stroke_width=wire_width)
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
                           wire_color=wire_color, wire_width=wire_width)
    _draw_segment_avoiding(canvas, x0, dy, x1, dy, obstacles,
                           wire_color=wire_color, wire_width=wire_width)
    _draw_segment_avoiding(canvas, x1, dy, x1, y1, obstacles,
                           wire_color=wire_color, wire_width=wire_width)


def _draw_segment_avoiding(
    canvas: "_TrackingCanvas",
    x0: float, y0: float,
    x1: float, y1: float,
    obstacles: list[_Obstacle],
    *,
    wire_color: str = _WIRE_COLOR,
    wire_width: float = _WIRE_WIDTH,
) -> None:
    """Draw a straight (H or V) segment from (x0,y0) to (x1,y1).

    If the segment is blocked by an obstacle a 3-segment detour is inserted.
    This function does NOT recurse — if the detour sub-segments are also
    blocked (e.g. the endpoint is inside an obstacle because of an extreme
    layout), it falls back to drawing a straight line to ensure the wire
    always terminates at the requested endpoint.
    """
    if not _any_obstacle_hit(obstacles, x0, y0, x1, y1):
        canvas.line(x0, y0, x1, y1, stroke=wire_color, stroke_width=wire_width)
        return

    blocking = [o for o in obstacles if o.segment_hits(x0, y0, x1, y1)]
    if not blocking:
        canvas.line(x0, y0, x1, y1, stroke=wire_color, stroke_width=wire_width)
        return

    obs = blocking[0]
    gap = _OBSTACLE_CLEARANCE

    # Horizontal segment blocked → detour above or below
    if abs(y0 - y1) < 0.5:
        dy_top = obs.y0 - gap
        dy_bot = obs.y1 + gap
        dy = dy_top if abs(y0 - dy_top) <= abs(y0 - dy_bot) else dy_bot
        # Draw 3-segment detour straight (no further recursion)
        canvas.line(x0, y0, x0, dy, stroke=wire_color, stroke_width=wire_width)
        canvas.line(x0, dy, x1, dy, stroke=wire_color, stroke_width=wire_width)
        canvas.line(x1, dy, x1, y1, stroke=wire_color, stroke_width=wire_width)
        return

    # Vertical segment blocked → detour left or right
    dx_left = obs.x0 - gap
    dx_right = obs.x1 + gap
    dx = dx_left if abs(x0 - dx_left) <= abs(x0 - dx_right) else dx_right
    canvas.line(x0, y0, dx, y0, stroke=wire_color, stroke_width=wire_width)
    canvas.line(dx, y0, dx, y1, stroke=wire_color, stroke_width=wire_width)
    canvas.line(dx, y1, x1, y1, stroke=wire_color, stroke_width=wire_width)


def _draw_net_label(
    canvas: "_TrackingCanvas",
    x: float,
    y: float,
    net_name: str,
    *,
    wire_color: str = _WIRE_COLOR,
    font_net: float = _FONT_NET,
    halo_fill: str = _LABEL_HALO_FILL,
    halo_opacity: str = _LABEL_HALO_OPACITY,
    halo_pad: float = _LABEL_HALO_PAD,
) -> None:
    """Draw a net label with a white halo background at (x, y).

    The halo is a semi-transparent white rectangle drawn before the text,
    ensuring readability over wire lines (netlistsvg technique).
    """
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
    wire_color: str = _WIRE_COLOR,
    ln_color: str = "#000000",
    ln_font_size: float = _FONT_NET,
    ln_font_style: str = "italic",
    ln_body_fill: str = "#ffffff",
    ln_body_stroke_width: float = 1.2,
    ln_stem_stroke_width: float = 1.4,
    halo_fill: str = _LABEL_HALO_FILL,
    halo_opacity: str = _LABEL_HALO_OPACITY,
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
    pad_x = 8.0
    tip_x, tip_y, box_x, box_y, box_w, box_h, text_x, text_y = _flag_label_geometry(
        x, y, net_name, side=side, ln_font_size=ln_font_size, align_x=align_x
    )

    # Halo (covers body + any horizontal stem)
    halo_x = box_x - pad_x
    halo_y = box_y - 6
    halo_w = box_w + pad_x * 2
    halo_h = box_h + 12
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

def _render_generic_box(
    canvas: "_TrackingCanvas",
    part: "Part",
    cx: float,
    cy: float,
    *,
    font_ref: float = _FONT_REF,
    font_value: float = _FONT_VALUE,
    font_pin: float = _FONT_PIN,
    box_stroke: str = "#333",
    box_stroke_width: float = 1.8,
    box_fill: str = "none",
    pin_stub_stroke: str = "#555",
    pin_stub_stroke_width: float = 1.5,
    pin_key_fill: str = "#333",
    pin_value_fill: str = "#555",
) -> None:
    """Render a generic part as a labelled rectangle with pin stubs.

    Box height is auto-sized based on pin count so that pins are not
    crowded (netlistsvg-style adaptive height).
    """
    pins = list(part.pins.items())
    h = _box_height(len(pins))
    w = _BOX_W
    x0, y0 = cx - w / 2, cy - h / 2

    # Box outline
    canvas.polyline(
        [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)],
        stroke=box_stroke,
        fill=box_fill,
        stroke_width=box_stroke_width,
    )

    # Ref and value labels
    ref = part.ref or "?"
    value = part.value or ""
    canvas.text(cx, cy - 7 if value else cy, ref,
                font_size=font_ref, anchor="middle", dominant_baseline="middle")
    if value:
        canvas.text(cx, cy + 8, value,
                    font_size=font_value, fill=pin_value_fill,
                    anchor="middle", dominant_baseline="middle")

    # Pin stubs
    n_left = math.ceil(len(pins) / 2)
    for i, (pin_key, pin_obj) in enumerate(pins):
        if i < n_left:
            row = i
            py = y0 + (row + 0.5) * (h / n_left)
            px = x0
            ex = x0 - _PIN_STUB
            anchor = "end"
            lx = ex - 4
        else:
            row = i - n_left
            n_right = len(pins) - n_left
            py = y0 + (row + 0.5) * (h / max(n_right, 1))
            px = x0 + w
            ex = x0 + w + _PIN_STUB
            anchor = "start"
            lx = ex + 4

        canvas.line(px, py, ex, py, stroke=pin_stub_stroke, stroke_width=pin_stub_stroke_width)
        canvas.text(lx, py, pin_key, font_size=font_pin,
                    fill=pin_key_fill, anchor=anchor, dominant_baseline="middle")
        # Net names are rendered only via NetLabel flag labels in phase 6.


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

    def to_svg_fit(self, margin: float = 40) -> str:
        """Return SVG string with viewBox fitted to content + *margin*."""
        if self._min_x == float("inf"):
            # Nothing was drawn — fall back to full-page viewBox
            return self.to_svg()

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
            f' width="{self._width}" height="{self._height}"'
            f' viewBox="{vb_x:.1f} {vb_y:.1f} {vb_w:.1f} {vb_h:.1f}">\n'
        )
        if self._background and self._background != "none":
            header += (
                f'  <rect width="100%" height="100%"'
                f' fill="{self._background}"/>\n'
            )
        body = "\n".join(f"  {el}" for el in self._elements)
        return header + body + "\n</svg>\n"
