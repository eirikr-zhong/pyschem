"""Render style and template data classes for schematic SVG export.

This module defines the data structures for controlling the visual appearance
of the schematic SVG output.  All hardcoded visual constants in the renderer
have corresponding fields here; ``RenderTemplate.default()`` reproduces the
original hard-coded defaults exactly.

Hierarchy
---------
WireStyle       – appearance of electrical wire segments
NetLabelStyle   – appearance of NetLabel flag labels
RenderStyle     – aggregates WireStyle + NetLabelStyle + misc visual knobs
RenderTemplate  – immutable snapshot (RenderStyle + PageConfig) passed to
                  renderers; created via ``RenderTemplate.from_style(style)``
                  or ``RenderTemplate.default()``.

Merge semantics (overlay pattern)
----------------------------------
``RenderStyle.merge(override)`` returns a *new* ``RenderStyle`` where every
field that is explicitly set (non-None) in *override* replaces the field from
*self*.  This lets users layer partial overrides on top of a base style.

``WireStyle.merge`` and ``NetLabelStyle.merge`` follow the same rule.

Example::

    base = RenderStyle.default()
    custom = RenderStyle(wire=WireStyle(color="#ff0000"))
    merged = base.merge(custom)
    assert merged.wire.color == "#ff0000"
    assert merged.wire.width == base.wire.width  # unchanged
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Optional

from lib.core.page import PageConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_fields(base: object, override: object) -> dict:
    """Return a dict of field values for *override* applied on top of *base*.

    A field value from *override* wins only when it is **not None**.
    Bool ``False`` and numeric ``0`` are preserved (only ``None`` is skipped).
    """
    result = {}
    for f in fields(base):  # type: ignore[arg-type]
        ov = getattr(override, f.name)
        result[f.name] = getattr(base, f.name) if ov is None else ov
    return result


# ---------------------------------------------------------------------------
# WireStyle
# ---------------------------------------------------------------------------


@dataclass
class WireStyle:
    """Visual properties for electrical wire segments.

    All fields default to ``None`` so that partial overrides work cleanly with
    :meth:`merge`.  The renderer falls back to hard-coded defaults when a field
    is ``None``.

    Attributes:
        color:     CSS colour string, e.g. ``"#1565c0"`` (blue).
        width:     Stroke width in SVG user-units (px).
        dash:      SVG ``stroke-dasharray`` value, or ``None`` for solid lines.
        junction_radius: Radius of junction dots at T-intersections.
    """

    color: Optional[str] = None
    width: Optional[float] = None
    dash: Optional[str] = None
    junction_radius: Optional[float] = None

    @classmethod
    def default(cls) -> "WireStyle":
        """Return a fully-specified default wire style."""
        return cls(
            color="#1565c0",
            width=1.8,
            dash=None,
            junction_radius=3.0,
        )

    def merge(self, override: "WireStyle") -> "WireStyle":
        """Return a new :class:`WireStyle` with *override* fields applied.

        Only fields that are *not* ``None`` in *override* replace the
        corresponding field in *self*.
        """
        return WireStyle(**_merge_fields(self, override))


# ---------------------------------------------------------------------------
# HaloStyle
# ---------------------------------------------------------------------------


@dataclass
class HaloStyle:
    """Visual properties for the halo rectangle drawn behind net labels.

    Attributes:
        fill:    CSS fill colour of the halo.  Default: ``"white"``.
        opacity: SVG opacity value (0–1 string or float).  Default: ``"0.85"``.
        pad:     Padding (px) added around the label text bounding box.
                 Default: ``2``.
    """

    fill: Optional[str] = None
    opacity: Optional[str] = None
    pad: Optional[float] = None

    @classmethod
    def default(cls) -> "HaloStyle":
        """Return a fully-specified default halo style."""
        return cls(fill="white", opacity="0.85", pad=2.0)

    def merge(self, override: "HaloStyle") -> "HaloStyle":
        """Return a new :class:`HaloStyle` with *override* fields applied."""
        return HaloStyle(**_merge_fields(self, override))


# ---------------------------------------------------------------------------
# BoxStyle
# ---------------------------------------------------------------------------


@dataclass
class BoxStyle:
    """Visual properties for the generic component box outline.

    Attributes:
        stroke:       CSS stroke colour.  Default: ``"#333333"``.
        stroke_width: Stroke width in px.  Default: ``1.8``.
        fill:         CSS fill colour.  Default: ``"none"``.
    """

    stroke: Optional[str] = None
    stroke_width: Optional[float] = None
    fill: Optional[str] = None

    @classmethod
    def default(cls) -> "BoxStyle":
        """Return a fully-specified default box style."""
        return cls(stroke="#333", stroke_width=1.8, fill="none")

    def merge(self, override: "BoxStyle") -> "BoxStyle":
        """Return a new :class:`BoxStyle` with *override* fields applied."""
        return BoxStyle(**_merge_fields(self, override))


# ---------------------------------------------------------------------------
# PinStyle
# ---------------------------------------------------------------------------


@dataclass
class PinStyle:
    """Visual properties for pin stubs and pin key annotations on generic boxes.

    Attributes:
        stub_stroke:       Stroke colour of pin stub lines.  Default: ``"#555555"``.
        stub_stroke_width: Stroke width of pin stub lines (px).  Default: ``1.5``.
        key_fill:          Fill colour for pin key text labels.  Default: ``"#333333"``.
        value_fill:        Fill colour for component value text.  Default: ``"#555555"``.
    """

    stub_stroke: Optional[str] = None
    stub_stroke_width: Optional[float] = None
    key_fill: Optional[str] = None
    value_fill: Optional[str] = None

    @classmethod
    def default(cls) -> "PinStyle":
        """Return a fully-specified default pin style."""
        return cls(
            stub_stroke="#555",
            stub_stroke_width=1.5,
            key_fill="#333",
            value_fill="#555",
        )

    def merge(self, override: "PinStyle") -> "PinStyle":
        """Return a new :class:`PinStyle` with *override* fields applied."""
        return PinStyle(**_merge_fields(self, override))


# ---------------------------------------------------------------------------
# NetLabelStyle
# ---------------------------------------------------------------------------


@dataclass
class NetLabelStyle:
    """Visual properties for NetLabel flag labels.

    Attributes:
        color:             CSS colour of the label text.
        font_size:         Font size in SVG user-units.
        font_style:        CSS ``font-style`` value (e.g. ``"italic"``).
        overline:          Whether to draw an overline bar above the text.
        bar_height:        Distance (px) from text baseline to the overline bar.
        body_fill:         Fill colour for the flag body rectangle/triangle.
                           Default: ``"#ffffff"``.
        body_stroke_width: Stroke width (px) for the flag body outline.
                           Default: ``1.2``.
        stem_stroke_width: Stroke width (px) for the horizontal stem connecting
                           a pin endpoint to the flag body.  Default: ``1.4``.
    """

    color: Optional[str] = None
    font_size: Optional[float] = None
    font_style: Optional[str] = None
    overline: Optional[bool] = None
    bar_height: Optional[float] = None
    body_fill: Optional[str] = None
    body_stroke_width: Optional[float] = None
    stem_stroke_width: Optional[float] = None

    @classmethod
    def default(cls) -> "NetLabelStyle":
        """Return a fully-specified default label-net style."""
        return cls(
            color="#d32f2f",
            font_size=12.0,
            font_style="italic",
            overline=True,
            bar_height=2.0,
            body_fill="#ffffff",
            body_stroke_width=1.6,
            stem_stroke_width=1.6,
        )

    def merge(self, override: "NetLabelStyle") -> "NetLabelStyle":
        """Return a new :class:`NetLabelStyle` with *override* fields applied."""
        return NetLabelStyle(**_merge_fields(self, override))


# ---------------------------------------------------------------------------
# RenderStyle
# ---------------------------------------------------------------------------


@dataclass
class RenderStyle:
    """Aggregate visual style for a full schematic render.

    Sub-styles (``wire``, ``label_net``, ``halo``, ``box``, ``pin``) are
    optional; when ``None`` the renderer uses the corresponding ``*.default()``
    values.

    Attributes:
        wire:            Wire segment style.
        label_net:       NetLabel flag label style.
        halo:            Net-label halo rectangle style.
        box:             Generic component box outline style.
        pin:             Pin stub and annotation style.
        background:      SVG canvas background colour.
        ref_font_size:   Font size for component reference designators.
        value_font_size: Font size for component value text.
        net_font_size:   Font size for named-net labels on wires.
        pin_font_size:   Font size for pin key annotations.
    """

    wire: Optional[WireStyle] = None
    label_net: Optional[NetLabelStyle] = None
    halo: Optional[HaloStyle] = None
    box: Optional[BoxStyle] = None
    pin: Optional[PinStyle] = None
    background: Optional[str] = None
    ref_font_size: Optional[float] = None
    value_font_size: Optional[float] = None
    net_font_size: Optional[float] = None
    pin_font_size: Optional[float] = None

    @classmethod
    def default(cls) -> "RenderStyle":
        """Return a fully-specified default render style."""
        return cls(
            wire=WireStyle.default(),
            label_net=NetLabelStyle.default(),
            halo=HaloStyle.default(),
            box=BoxStyle.default(),
            pin=PinStyle.default(),
            background="#ffffff",
            ref_font_size=14.0,
            value_font_size=11.0,
            net_font_size=12.0,
            pin_font_size=10.0,
        )

    def merge(self, override: "RenderStyle") -> "RenderStyle":
        """Return a new :class:`RenderStyle` with *override* fields applied.

        Sub-style fields are merged recursively when *both* sides are non-None;
        otherwise the override value wins outright.
        """
        _sub_defaults = {
            "wire": WireStyle.default,
            "label_net": NetLabelStyle.default,
            "halo": HaloStyle.default,
            "box": BoxStyle.default,
            "pin": PinStyle.default,
        }

        merged_subs: dict = {}
        for fname, default_fn in _sub_defaults.items():
            base_sub = getattr(self, fname) or default_fn()
            ovr_sub = getattr(override, fname)
            if ovr_sub is not None:
                merged_subs[fname] = base_sub.merge(ovr_sub)
            else:
                merged_subs[fname] = getattr(self, fname)

        scalar_names = {f.name for f in fields(self)} - set(_sub_defaults)
        scalars = {
            name: (
                getattr(self, name)
                if getattr(override, name) is None
                else getattr(override, name)
            )
            for name in scalar_names
        }

        return RenderStyle(**merged_subs, **scalars)


# ---------------------------------------------------------------------------
# RenderTemplate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderTemplate:
    """Immutable combination of :class:`RenderStyle` and :class:`PageConfig`.

    Pass a :class:`RenderTemplate` to renderer functions to fully control the
    output appearance and canvas size without touching global state.

    Attributes:
        style:  Visual style settings.
        page:   Canvas / page dimensions.

    Note:
        ``RenderTemplate`` is *frozen* (immutable).  Derive a modified copy
        with ``dataclasses.replace(tmpl, page=PageConfig.a3())``.
    """

    style: RenderStyle = field(default_factory=RenderStyle.default)
    page: PageConfig = field(default_factory=PageConfig.default)

    @classmethod
    def default(cls) -> "RenderTemplate":
        """Return a template with :meth:`RenderStyle.default` and A1 portrait."""
        return cls(style=RenderStyle.default(), page=PageConfig.default())

    @classmethod
    def from_style(cls, style: RenderStyle, page: Optional[PageConfig] = None) -> "RenderTemplate":
        """Create a :class:`RenderTemplate` from an explicit *style*.

        Args:
            style: Fully or partially specified render style.  ``None`` sub-
                   fields will be interpreted as defaults by the renderer.
            page:  Page config to use; defaults to :meth:`PageConfig.default`.
        """
        return cls(style=style, page=page if page is not None else PageConfig.default())
