"""pyschem - Python schematic rendering library.

A library for creating, manipulating, and rendering schematics.
"""

from lib._version import __version__
from lib.symbols import (
    PinDefinition,
    SymbolData,
    SymbolPrimitive,
    Symbols,
    configure_default_symbols,
    get_default_symbols,
)
from lib.core import (
    BoxStyle,
    DefaultPlacementStyle,
    HaloStyle,
    Net,
    NetLabel,
    NetLabelStyle,
    PageConfig,
    Part,
    Pin,
    PinStyle,
    SymbolStyle,
    TextPlacementStyle,
    RenderStyle,
    RenderTemplate,
    Schematic,
    Sheet,
    Style,
    WireStyle,
    connect,
    derive_nets,
)
from lib.errors import (
    ERCError,
    LayoutConstraintError,
    PinNotFoundError,
    PySchemException,
    RenderLayoutError,
    RenderPathError,
    StyleValidationError,
    SymbolNotFoundError,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "Schematic",
    "Sheet",
    "Part",
    "Pin",
    "Net",
    "NetLabel",
    "Style",
    "DefaultPlacementStyle",
    "PageConfig",
    # Render style / template
    "WireStyle",
    "NetLabelStyle",
    "HaloStyle",
    "BoxStyle",
    "PinStyle",
    "SymbolStyle",
    "TextPlacementStyle",
    "RenderStyle",
    "RenderTemplate",
    # Connection API
    "connect",
    "derive_nets",
    # Errors
    "PySchemException",
    "StyleValidationError",
    "PinNotFoundError",
    "SymbolNotFoundError",
    "LayoutConstraintError",
    "RenderLayoutError",
    "RenderPathError",
    "ERCError",
    # Symbols
    "Symbols",
    "SymbolData",
    "SymbolPrimitive",
    "PinDefinition",
    "configure_default_symbols",
    "get_default_symbols",
]
