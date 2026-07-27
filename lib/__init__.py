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
from lib.symbols.symbol_parser import (
    SymbolLibrary,
    load_library as load_symbol_library,
)
from lib.core import (
    BoxStyle,
    DefaultPlacementStyle,
    GroundNet,
    NC,
    HaloStyle,
    Junction,
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
    resolve_style,
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
    "GroundNet",
    "NC",
    "Junction",
    "Style",
    "DefaultPlacementStyle",
    "resolve_style",
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
    "SymbolLibrary",
    "load_symbol_library",
]
