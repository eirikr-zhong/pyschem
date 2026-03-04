"""Tests for WireStyle, LabelNetStyle, and RenderStyle (M1 skeleton).

Test-ID prefix: RS-
"""

import dataclasses

import pytest

from lib.core.render_style import NetLabelStyle, RenderStyle, SymbolStyle, WireStyle


# ---------------------------------------------------------------------------
# RS-01 .. RS-05  WireStyle
# ---------------------------------------------------------------------------


class TestWireStyle:
    def test_RS01_default_fields(self):
        """RS-01: WireStyle.default() returns fully-specified values."""
        ws = WireStyle.default()
        assert ws.color == "#1565c0"
        assert ws.width == 1.8
        assert ws.dash == ""
        assert ws.junction_radius == 3.0
        assert ws.junction_color == "#1565c0"

    def test_RS02_blank_is_all_none(self):
        """RS-02: WireStyle() without args has all None fields."""
        ws = WireStyle()
        assert ws.color is None
        assert ws.width is None
        assert ws.dash is None
        assert ws.junction_radius is None
        assert ws.junction_color is None

    def test_RS03_merge_override_single_field(self):
        """RS-03: merge() replaces only explicitly set fields."""
        base = WireStyle.default()
        override = WireStyle(color="#ff0000")
        merged = base.merge(override)
        assert merged.color == "#ff0000"
        assert merged.width == base.width
        assert merged.junction_radius == base.junction_radius

    def test_RS04_merge_empty_override_is_identity(self):
        """RS-04: merging an all-None override returns equal values."""
        base = WireStyle.default()
        merged = base.merge(WireStyle())
        assert merged.color == base.color
        assert merged.width == base.width
        assert merged.junction_radius == base.junction_radius

    def test_RS05_merge_full_override_wins(self):
        """RS-05: merging a fully specified override takes all override values."""
        base = WireStyle.default()
        override = WireStyle(
            color="#000000",
            width=3.0,
            dash="4 2",
            junction_radius=5.0,
            junction_color="#777777",
        )
        merged = base.merge(override)
        assert merged.color == "#000000"
        assert merged.width == 3.0
        assert merged.dash == "4 2"
        assert merged.junction_radius == 5.0
        assert merged.junction_color == "#777777"

    def test_RS06_merge_returns_new_instance(self):
        """RS-06: merge() does not mutate base or override."""
        base = WireStyle.default()
        override = WireStyle(color="#aabbcc")
        merged = base.merge(override)
        assert base.color == "#1565c0"   # unchanged
        assert merged is not base
        assert merged is not override


# ---------------------------------------------------------------------------
# RS-07 .. RS-12  LabelNetStyle
# ---------------------------------------------------------------------------


class TestNetLabelStyle:
    def test_RS07_default_fields(self):
        "RS-07: NetLabelStyle.default() returns fully-specified values."
        ln = NetLabelStyle.default()
        assert ln.color == "#d32f2f"
        assert ln.font_size == 12.0
        assert ln.font_style == "italic"
        assert ln.overline is True
        assert ln.bar_height == 2.0

    def test_RS08_blank_is_all_none(self):
        "RS-08: NetLabelStyle() without args has all None fields."
        ln = NetLabelStyle()
        assert ln.color is None
        assert ln.font_size is None
        assert ln.overline is None

    def test_RS09_merge_single_field(self):
        "RS-09: NetLabelStyle.merge() respects partial override."
        base = NetLabelStyle.default()
        merged = base.merge(NetLabelStyle(font_size=16.0))
        assert merged.font_size == 16.0
        assert merged.color == base.color
        assert merged.overline == base.overline

    def test_RS10_merge_overline_false_respected(self):
        "RS-10: bool False is a valid override, not skipped like None." 
        base = NetLabelStyle.default()
        merged = base.merge(NetLabelStyle(overline=False))
        assert merged.overline is False

    def test_RS11_merge_empty_is_identity(self):
        "RS-11: merging all-None override keeps base values." 
        base = NetLabelStyle.default()
        merged = base.merge(NetLabelStyle())
        assert merged.color == base.color
        assert merged.font_size == base.font_size

    def test_RS12_merge_returns_new_instance(self):
        "RS-12: merge() does not mutate base." 
        base = NetLabelStyle.default()
        base.merge(NetLabelStyle(color="#123456"))
        assert base.color == "#d32f2f"


# ---------------------------------------------------------------------------
# RS-13 .. RS-22  RenderStyle
# ---------------------------------------------------------------------------


class TestRenderStyle:
    def test_RS13_default_fields(self):
        """RS-13: RenderStyle.default() returns fully-specified values."""
        rs = RenderStyle.default()
        assert rs.canvas_scale == 1.0
        assert rs.background == "#ffffff"
        assert rs.ref_font_size == 14.0
        assert rs.value_font_size == 11.0
        assert rs.net_font_size == 12.0
        assert rs.pin_font_size == 10.0
        assert isinstance(rs.wire, WireStyle)
        assert isinstance(rs.label_net, NetLabelStyle)
        assert isinstance(rs.symbol, SymbolStyle)
        assert rs.symbol.scale == 1.0

    def test_RS14_blank_has_none_sub_styles(self):
        """RS-14: RenderStyle() without args has None wire and label_net."""
        rs = RenderStyle()
        assert rs.wire is None
        assert rs.label_net is None
        assert rs.symbol is None
        assert rs.canvas_scale is None
        assert rs.background is None

    def test_RS15_merge_scalar_field(self):
        """RS-15: merge() replaces only the overridden scalar field."""
        base = RenderStyle.default()
        override = RenderStyle(background="#f0f0f0")
        merged = base.merge(override)
        assert merged.background == "#f0f0f0"
        assert merged.ref_font_size == base.ref_font_size

    def test_RS16_merge_wire_sub_style(self):
        """RS-16: RenderStyle.merge() recursively merges WireStyle."""
        base = RenderStyle.default()
        override = RenderStyle(wire=WireStyle(color="#ff0000"))
        merged = base.merge(override)
        assert merged.wire.color == "#ff0000"
        assert merged.wire.width == base.wire.width

    def test_RS17_merge_label_net_sub_style(self):
        """RS-17: RenderStyle.merge() recursively merges LabelNetStyle."""
        base = RenderStyle.default()
        override = RenderStyle(label_net=NetLabelStyle(font_size=20.0))
        merged = base.merge(override)
        assert merged.label_net.font_size == 20.0
        assert merged.label_net.color == base.label_net.color

    def test_RS18_merge_empty_override_identity(self):
        """RS-18: merging all-None override keeps all base values."""
        base = RenderStyle.default()
        merged = base.merge(RenderStyle())
        assert merged.background == base.background
        assert merged.wire.color == base.wire.color

    def test_RS19_merge_does_not_mutate_base(self):
        """RS-19: merge() returns new instance, base unchanged."""
        base = RenderStyle.default()
        override = RenderStyle(background="#000000")
        merged = base.merge(override)
        assert base.background == "#ffffff"
        assert merged is not base

    def test_RS20_merge_none_wire_keeps_base_wire(self):
        """RS-20: override.wire=None → merged.wire == base.wire (same object)."""
        base = RenderStyle.default()
        override = RenderStyle(background="#aaa")
        merged = base.merge(override)
        assert merged.wire is base.wire

    def test_RS21_base_none_wire_uses_default_for_recursive_merge(self):
        """RS-21: when base.wire is None, override merges against WireStyle.default()."""
        base = RenderStyle()          # wire=None
        override = RenderStyle(wire=WireStyle(color="#ff0000"))
        merged = base.merge(override)
        assert merged.wire.color == "#ff0000"
        # Width should come from WireStyle.default(), not crash
        assert merged.wire.width == WireStyle.default().width

    def test_RS22_chained_merges(self):
        """RS-22: three-level merge chain produces correct final result."""
        base = RenderStyle.default()
        layer1 = RenderStyle(wire=WireStyle(color="#aaaaaa"), background="#111111")
        layer2 = RenderStyle(wire=WireStyle(width=3.0))
        merged = base.merge(layer1).merge(layer2)
        assert merged.wire.color == "#aaaaaa"    # from layer1
        assert merged.wire.width == 3.0           # from layer2
        assert merged.background == "#111111"    # from layer1

    def test_RS22b_merge_symbol_sub_style(self):
        """RS-22b: RenderStyle.merge() recursively merges SymbolStyle."""
        base = RenderStyle.default()
        override = RenderStyle(symbol=SymbolStyle(scale=1.8))
        merged = base.merge(override)
        assert merged.symbol.scale == 1.8

    def test_RS23_default_has_no_none_fields_anywhere(self):
        """RS-23: RenderStyle.default() tree has no None field values."""
        rs = RenderStyle.default()

        def _walk(value, path: str = "root"):
            if dataclasses.is_dataclass(value):
                for f in dataclasses.fields(value):
                    _walk(getattr(value, f.name), f"{path}.{f.name}")
                return
            assert value is not None, f"Found None at {path}"

        _walk(rs)

    def test_RS24_merge_canvas_scale_scalar(self):
        """RS-24: RenderStyle.merge() applies canvas_scale as scalar override."""
        base = RenderStyle.default()
        merged = base.merge(RenderStyle(canvas_scale=2.0))
        assert merged.canvas_scale == 2.0
        assert base.canvas_scale == 1.0

    def test_RS25_merge_canvas_scale_none_keeps_base(self):
        """RS-25: RenderStyle.merge() keeps base canvas_scale when override is None."""
        base = RenderStyle.default()
        merged = base.merge(RenderStyle(background="#101010"))
        assert merged.canvas_scale == 1.0
