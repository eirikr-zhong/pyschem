"""KiCad symbol library parsing.

This module provides functionality to parse KiCad symbol libraries
(``.kicad_sym`` files).
"""

from lib.symbols.data import PinDefinition, SymbolData, SymbolPrimitive
from lib.symbols.symbol_parser import SymbolLibrary
from lib.symbols.symbol_parser import load_library as load_symbol_library
from lib.symbols.symbols import (
    Symbols,
    configure_default_symbols,
    get_default_symbols,
)

__all__ = [
    # Main class
    "Symbols",
    "configure_default_symbols",
    "get_default_symbols",
    # Data classes
    "SymbolData",
    "SymbolPrimitive",
    "PinDefinition",
    # Parser classes (for advanced use)
    "SymbolLibrary",
    # Loader functions
    "load_symbol_library",
]
