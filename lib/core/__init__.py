"""Core domain models for schematic representation."""

from lib.core.connect import connect, derive_nets
from lib.core.junction import Junction
from lib.core.net import GroundNet, Net, NetLabel
from lib.core.page import PageConfig
from lib.core.part import Part, Pin
from lib.core.render_style import (
    BoxStyle,
    HaloStyle,
    NetLabelStyle,
    PinStyle,
    RenderStyle,
    RenderTemplate,
    SymbolStyle,
    TextPlacementStyle,
    WireStyle,
)
from lib.core.schematic import Schematic, Sheet
from lib.core.style import DefaultPlacementStyle, Style
from lib.core.style_resolver import resolve_style

__all__ = [
    "Schematic",
    "Sheet",
    "Part",
    "Pin",
    "Net",
    "NetLabel",
    "GroundNet",
    "Junction",
    "Style",
    "DefaultPlacementStyle",
    "resolve_style",
    "PageConfig",
    "connect",
    "derive_nets",
    "WireStyle",
    "NetLabelStyle",
    "HaloStyle",
    "BoxStyle",
    "PinStyle",
    "SymbolStyle",
    "TextPlacementStyle",
    "RenderStyle",
    "RenderTemplate",
]
