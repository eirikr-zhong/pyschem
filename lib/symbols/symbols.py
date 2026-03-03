"""Symbols class for KiCad symbol and footprint library access.

This module provides the main Symbols class for searching KiCad symbol libraries
and footprint directories with in-memory indexing.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lib.errors import FootprintNotFoundError, SymbolNotFoundError
from lib.symbols import footprint_parser, symbol_parser
from lib.symbols.data import FootprintData, SymbolData


@dataclass
class LoadResult:
    """Result of a load operation."""
    success: bool
    loaded_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)


class Symbols:
    """Main entry point for KiCad symbol and footprint library access.

    This class provides methods to search for symbols and footprints across
    configured library paths. Libraries can be loaded on-demand (lazy loading)
    or all at once using load_all().

    Example:
        >>> symbols = Symbols(
        ...     symbol_paths=["~/Documents/kicad-symbols"],
        ...     footprint_paths=["~/Documents/kicad-footprints"],
        ... )
        >>> # Load all libraries at startup
        >>> result = symbols.load_all()
        >>> print(f"Loaded {result.loaded_count} libraries")
        >>> # Query from memory
        >>> symbol = symbols.find_symbol("Device", "R")
        >>> footprint = symbols.find_footprint("Resistor_SMD", "R_0805")
    """

    def __init__(
        self,
        symbol_paths: Optional[list[str]] = None,
        footprint_paths: Optional[list[str]] = None,
    ):
        """Initialize Symbols with library paths.

        Args:
            symbol_paths: List of directories containing .kicad_sym files.
                         Paths are expanded and searched in order.
            footprint_paths: List of directories containing .pretty folders.
                            Paths are expanded and searched in order.
        """
        self._symbol_paths = self._expand_paths(symbol_paths or [])
        self._footprint_paths = self._expand_paths(footprint_paths or [])

        # Cache for loaded libraries
        self._symbol_libraries: dict[str, symbol_parser.SymbolLibrary] = {}
        self._footprint_libraries: dict[str, footprint_parser.FootprintLibrary] = {}

        # In-memory indexes for fast lookup after loading
        self._symbol_index: dict[str, dict[str, SymbolData]] = {}  # lib -> {name -> SymbolData}
        self._footprint_index: dict[str, dict[str, FootprintData]] = {}  # lib -> {name -> FootprintData}
        
        self._loaded = False
        self._load_result: Optional[LoadResult] = None

    @staticmethod
    def _expand_paths(paths: list[str]) -> list[Path]:
        """Expand user paths and convert to Path objects.

        Args:
            paths: List of path strings (may contain ~ for home directory)

        Returns:
            List of expanded Path objects
        """
        expanded = []
        for p in paths:
            # Expand ~ and environment variables
            expanded_path = Path(p).expanduser().resolve()
            expanded.append(expanded_path)
        return expanded

    def load_all(self, raise_on_error: bool = False) -> LoadResult:
        """Load all symbol and footprint libraries into memory.

        This method discovers and loads all .kicad_sym files and .pretty directories
        from the configured paths. After loading, all queries are performed
        against the in-memory index for fast lookup.

        Args:
            raise_on_error: If True, raise exception on parsing errors.
                          If False, skip corrupted files and continue.

        Returns:
            LoadResult with information about loaded libraries and any errors.
        """
        if self._loaded and self._load_result is not None:
            return self._load_result

        result = LoadResult(success=True)
        
        # Discover and load symbol libraries
        for search_path in self._symbol_paths:
            if not search_path.exists():
                result.error_count += 1
                result.errors.append(f"Symbol path not found: {search_path}")
                continue

            # Find all .kicad_sym files in the path
            for sym_file in search_path.glob("*.kicad_sym"):
                lib_name = sym_file.stem
                try:
                    library = symbol_parser.load_library(sym_file)
                    library.load()  # Parse the file
                    
                    if library.load_error:
                        result.error_count += 1
                        result.errors.append(f"Error loading {lib_name}: {library.load_error}")
                        if raise_on_error:
                            raise RuntimeError(library.load_error)
                    else:
                        self._symbol_libraries[lib_name] = library
                        
                        # Build in-memory index
                        self._symbol_index[lib_name] = {}
                        for symbol in library.symbols:
                            self._symbol_index[lib_name][symbol.name] = symbol
                        
                        result.loaded_count += 1
                except Exception as e:
                    result.error_count += 1
                    result.errors.append(f"Error loading {sym_file.name}: {e}")
                    if raise_on_error:
                        raise

        # Discover and load footprint libraries
        for search_path in self._footprint_paths:
            if not search_path.exists():
                result.error_count += 1
                result.errors.append(f"Footprint path not found: {search_path}")
                continue

            # Find all .pretty directories in the path
            for pretty_dir in search_path.glob("*.pretty"):
                if not pretty_dir.is_dir():
                    continue
                    
                lib_name = pretty_dir.stem
                try:
                    library = footprint_parser.load_library(pretty_dir)
                    library.load()  # Parse all footprints in directory
                    
                    if library.load_errors:
                        for err in library.load_errors:
                            result.errors.append(f"Error in {lib_name}: {err}")
                        result.error_count += len(library.load_errors)
                    
                    self._footprint_libraries[lib_name] = library
                    
                    # Build in-memory index
                    self._footprint_index[lib_name] = {}
                    for fp_name, footprint in library.footprints.items():
                        self._footprint_index[lib_name][fp_name] = footprint
                    
                    result.loaded_count += 1
                except Exception as e:
                    result.error_count += 1
                    result.errors.append(f"Error loading {pretty_dir.name}: {e}")
                    if raise_on_error:
                        raise

        self._loaded = True
        self._load_result = result
        result.success = result.error_count == 0
        
        return result

    @property
    def is_loaded(self) -> bool:
        """Check if all libraries have been loaded."""
        return self._loaded

    @property
    def load_result(self) -> Optional[LoadResult]:
        """Get the result of the last load_all() operation."""
        return self._load_result

    def find_symbol(self, lib: str, name: str) -> SymbolData:
        """Find a symbol by library name and symbol name.

        If load_all() has been called, this searches the in-memory index.
        Otherwise, it performs lazy loading.

        Args:
            lib: Library name (e.g., "Device", "Amplifier")
            name: Symbol name within the library (e.g., "R", "C", "LM358")

        Returns:
            SymbolData object with symbol information

        Raises:
            SymbolNotFoundError: If the symbol is not found in any library
        """
        # If loaded, search in-memory index
        if self._loaded and lib in self._symbol_index:
            if name in self._symbol_index[lib]:
                return self._symbol_index[lib][name]
            raise SymbolNotFoundError(
                f"symbol '{name}' not found in library '{lib}'"
            )

        # Lazy loading fallback
        library = self._get_symbol_library(lib)

        if library is None:
            raise SymbolNotFoundError(
                f"symbol library '{lib}' not found in symbol paths"
            )

        symbol = library.find_symbol(name)
        if symbol is None:
            raise SymbolNotFoundError(
                f"symbol '{name}' not found in library '{lib}'"
            )

        return symbol

    def find_footprint(self, lib: str, name: str) -> FootprintData:
        """Find a footprint by library name and footprint name.

        If load_all() has been called, this searches the in-memory index.
        Otherwise, it performs lazy loading.

        Args:
            lib: Footprint library name (e.g., "Resistor_SMD", "SOIC")
            name: Footprint name within the library (e.g., "R_0805", "SOIC-8")

        Returns:
            FootprintData object with footprint information

        Raises:
            FootprintNotFoundError: If the footprint is not found in any library
        """
        # If loaded, search in-memory index
        if self._loaded and lib in self._footprint_index:
            if name in self._footprint_index[lib]:
                return self._footprint_index[lib][name]
            raise FootprintNotFoundError(
                f"footprint '{name}' not found in library '{lib}'"
            )

        # Lazy loading fallback
        library = self._get_footprint_library(lib)

        if library is None:
            raise FootprintNotFoundError(
                f"footprint library '{lib}' not found in footprint paths"
            )

        footprint = library.find_footprint(name)
        if footprint is None:
            raise FootprintNotFoundError(
                f"footprint '{name}' not found in library '{lib}'"
            )

        return footprint

    def get_symbol(self, lib: str, name: str) -> Optional[SymbolData]:
        """Find a symbol by library name and symbol name (returns None if not found).

        Args:
            lib: Library name
            name: Symbol name

        Returns:
            SymbolData if found, None otherwise
        """
        try:
            return self.find_symbol(lib, name)
        except SymbolNotFoundError:
            return None

    def get_footprint(self, lib: str, name: str) -> Optional[FootprintData]:
        """Find a footprint by library name and footprint name (returns None if not found).

        Args:
            lib: Footprint library name
            name: Footprint name

        Returns:
            FootprintData if found, None otherwise
        """
        try:
            return self.find_footprint(lib, name)
        except FootprintNotFoundError:
            return None

    def list_symbol_libraries(self) -> list[str]:
        """List all available symbol libraries.
        
        Returns:
            List of library names
        """
        if not self._loaded:
            self.load_all()
        return list(self._symbol_index.keys())

    def list_footprint_libraries(self) -> list[str]:
        """List all available footprint libraries.
        
        Returns:
            List of library names
        """
        if not self._loaded:
            self.load_all()
        return list(self._footprint_index.keys())

    def list_symbols(self, lib: str) -> list[str]:
        """List all symbols in a library.
        
        Args:
            lib: Library name
            
        Returns:
            List of symbol names
        """
        if not self._loaded:
            self.load_all()
        
        if lib in self._symbol_index:
            return list(self._symbol_index[lib].keys())
        
        # Lazy loading fallback
        library = self._get_symbol_library(lib)
        if library:
            return [s.name for s in library.symbols]
        return []

    def list_footprints(self, lib: str) -> list[str]:
        """List all footprints in a library.
        
        Args:
            lib: Library name
            
        Returns:
            List of footprint names
        """
        if not self._loaded:
            self.load_all()
        
        if lib in self._footprint_index:
            return list(self._footprint_index[lib].keys())
        
        # Lazy loading fallback
        library = self._get_footprint_library(lib)
        if library:
            return list(library.footprints.keys())
        return []

    def _get_symbol_library(self, lib: str) -> Optional[symbol_parser.SymbolLibrary]:
        """Get or load a symbol library by name.

        Args:
            lib: Library name to find

        Returns:
            SymbolLibrary if found, None otherwise
        """
        # Check cache first
        if lib in self._symbol_libraries:
            return self._symbol_libraries[lib]

        # Search in symbol paths for .kicad_sym file
        for search_path in self._symbol_paths:
            # Direct .kicad_sym file
            sym_file = search_path / f"{lib}.kicad_sym"
            if sym_file.exists():
                library = symbol_parser.load_library(sym_file)
                self._symbol_libraries[lib] = library
                return library

            # Check if search_path itself is a .kicad_sym file
            if search_path.is_file() and search_path.suffix == ".kicad_sym":
                if search_path.stem == lib:
                    library = symbol_parser.load_library(search_path)
                    self._symbol_libraries[lib] = library
                    return library

        return None

    def _get_footprint_library(self, lib: str) -> Optional[footprint_parser.FootprintLibrary]:
        """Get or load a footprint library by name.

        Args:
            lib: Library name to find

        Returns:
            FootprintLibrary if found, None otherwise
        """
        # Check cache first
        if lib in self._footprint_libraries:
            return self._footprint_libraries[lib]

        # Search in footprint paths for .pretty directory
        for search_path in self._footprint_paths:
            # Direct .pretty directory
            pretty_dir = search_path / f"{lib}.pretty"
            if pretty_dir.exists() and pretty_dir.is_dir():
                library = footprint_parser.load_library(pretty_dir)
                self._footprint_libraries[lib] = library
                return library

            # Check if search_path itself is a .pretty directory
            if search_path.is_dir() and search_path.suffix == ".pretty":
                if search_path.stem == lib:
                    library = footprint_parser.load_library(search_path)
                    self._footprint_libraries[lib] = library
                    return library

        return None


    def search_symbols(self, query: str, limit: int = 50) -> list[SymbolData]:
        """Search symbols in memory by name/lib/property.

        Args:
            query: Case-insensitive search term
            limit: Max results

        Returns:
            List of matching symbols
        """
        if not self._loaded:
            self.load_all()

        q = query.strip().lower()
        if not q:
            return []

        results: list[SymbolData] = []
        for lib_name, symbols in self._symbol_index.items():
            for sym_name, symbol in symbols.items():
                hay = f"{lib_name} {sym_name} " + " ".join(
                    f"{k}:{v}" for k, v in symbol.properties.items()
                )
                if q in hay.lower():
                    results.append(symbol)
                    if len(results) >= limit:
                        return results
        return results

    def search_footprints(self, query: str, limit: int = 50) -> list[FootprintData]:
        """Search footprints in memory by name/library."""
        if not self._loaded:
            self.load_all()

        q = query.strip().lower()
        if not q:
            return []

        results: list[FootprintData] = []
        for lib_name, fps in self._footprint_index.items():
            for fp_name, footprint in fps.items():
                if q in f"{lib_name} {fp_name}".lower():
                    results.append(footprint)
                    if len(results) >= limit:
                        return results
        return results

    @property
    def symbol_paths(self) -> list[Path]:
        """Get the configured symbol search paths."""
        return list(self._symbol_paths)

    @property
    def footprint_paths(self) -> list[Path]:
        """Get the configured footprint search paths."""
        return list(self._footprint_paths)


# ---------------------------------------------------------------------------
# Global singleton-style symbols manager (optional convenience layer)
# ---------------------------------------------------------------------------

_DEFAULT_SYMBOLS: Optional["Symbols"] = None


def configure_default_symbols(
    *,
    symbol_paths: Optional[list[str]] = None,
    footprint_paths: Optional[list[str]] = None,
    preload: bool = True,
) -> Symbols:
    """Configure a process-wide default Symbols manager.

    This lets application code set library paths once, then let Part auto-resolve
    symbols from lib_id (e.g. `Device:R` -> `Device.kicad_sym` symbol `R`).
    """
    global _DEFAULT_SYMBOLS
    _DEFAULT_SYMBOLS = Symbols(symbol_paths=symbol_paths or [], footprint_paths=footprint_paths or [])
    if preload:
        _DEFAULT_SYMBOLS.load_all()
    return _DEFAULT_SYMBOLS


def _parse_env_paths(env_var: str) -> list[str]:
    """Parse a colon- or semicolon-separated path list from an environment variable.

    On macOS/Linux the conventional separator is ``:``.  Semicolons are also
    accepted so that the same env var works on Windows-style tooling.

    Returns an empty list when the variable is unset or empty.
    """
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return []
    # Split on colon first, then handle any remaining semicolons
    parts: list[str] = []
    for segment in raw.replace(";", ":").split(":"):
        segment = segment.strip()
        if segment:
            parts.append(segment)
    return parts


def get_default_symbols() -> Optional[Symbols]:
    """Return the default Symbols manager.

    Priority:
    1. Singleton configured via ``configure_default_symbols()``.
    2. Paths from environment variables ``KICAD_SYMBOL_DIR`` and
       ``KICAD_FOOTPRINT_DIR`` (colon- or semicolon-separated, searched in
       order).
    3. ``None`` when neither source is available.
    """
    if _DEFAULT_SYMBOLS is not None:
        return _DEFAULT_SYMBOLS

    sym_paths = _parse_env_paths("KICAD_SYMBOL_DIR")
    fp_paths = _parse_env_paths("KICAD_FOOTPRINT_DIR")

    if not sym_paths and not fp_paths:
        return None

    return Symbols(symbol_paths=sym_paths, footprint_paths=fp_paths)
