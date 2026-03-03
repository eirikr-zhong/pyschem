"""KiCad symbol and footprint library parsing.

This module provides functionality to parse KiCad symbol libraries (.kicad_sym)
and footprint libraries (.pretty directories).
"""

from lib.symbols.data import FootprintData, PinDefinition, SymbolData, SymbolPrimitive
from lib.symbols.footprint_parser import FootprintLibrary
from lib.symbols.footprint_parser import load_library as load_footprint_library
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
    "FootprintData",
    "PinDefinition",
    # Parser classes (for advanced use)
    "SymbolLibrary",
    "FootprintLibrary",
    # Loader functions
    "load_symbol_library",
    "load_footprint_library",
]
