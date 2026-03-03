"""Symbols class for KiCad symbol library access.

This module provides the main ``Symbols`` class for searching KiCad symbol
libraries with optional in-memory indexing.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lib.errors import SymbolNotFoundError
from . import symbol_parser
from lib.symbols.data import SymbolData


@dataclass
class LoadResult:
    """Result of a load operation."""

    success: bool
    loaded_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)


class Symbols:
    """Main entry point for KiCad symbol library access.

    Libraries can be loaded on-demand (lazy loading) or all at once using
    ``load_all()``.
    """

    def __init__(self, symbol_paths: Optional[list[str]] = None):
        """Initialize Symbols with library paths.

        Args:
            symbol_paths: List of directories containing ``.kicad_sym`` files.
                Paths are expanded and searched in order.
        """

        self._symbol_paths = self._expand_paths(symbol_paths or [])

        # Cache for loaded libraries
        self._symbol_libraries: dict[str, symbol_parser.SymbolLibrary] = {}

        # In-memory indexes for fast lookup after loading
        self._symbol_index: dict[str, dict[str, SymbolData]] = {}

        self._loaded = False
        self._load_result: Optional[LoadResult] = None

    @staticmethod
    def _expand_paths(paths: list[str]) -> list[Path]:
        """Expand user paths and convert to Path objects."""

        expanded = []
        for p in paths:
            expanded.append(Path(p).expanduser().resolve())
        return expanded

    def load_all(self, raise_on_error: bool = False) -> LoadResult:
        """Load all symbol libraries into memory.

        Args:
            raise_on_error: If True, raise exception on parsing errors.
                If False, skip corrupted files and continue.
        """

        if self._loaded and self._load_result is not None:
            return self._load_result

        result = LoadResult(success=True)

        for search_path in self._symbol_paths:
            if not search_path.exists():
                result.error_count += 1
                result.errors.append(f"Symbol path not found: {search_path}")
                continue

            for sym_file in search_path.glob("*.kicad_sym"):
                lib_name = sym_file.stem
                try:
                    library = symbol_parser.load_library(sym_file)
                    library.load()

                    if library.load_error:
                        result.error_count += 1
                        result.errors.append(f"Error loading {lib_name}: {library.load_error}")
                        if raise_on_error:
                            raise RuntimeError(library.load_error)
                        continue

                    self._symbol_libraries[lib_name] = library
                    self._symbol_index[lib_name] = {}
                    for symbol in library.symbols:
                        self._symbol_index[lib_name][symbol.name] = symbol

                    result.loaded_count += 1
                except Exception as exc:
                    result.error_count += 1
                    result.errors.append(f"Error loading {sym_file.name}: {exc}")
                    if raise_on_error:
                        raise

        self._loaded = True
        self._load_result = result
        result.success = result.error_count == 0
        return result

    @property
    def is_loaded(self) -> bool:
        """Check if libraries have been loaded."""

        return self._loaded

    @property
    def load_result(self) -> Optional[LoadResult]:
        """Get the result of the last ``load_all()`` operation."""

        return self._load_result

    def find_symbol(self, lib: str, name: str) -> SymbolData:
        """Find a symbol by library name and symbol name."""

        if self._loaded and lib in self._symbol_index:
            if name in self._symbol_index[lib]:
                return self._symbol_index[lib][name]
            raise SymbolNotFoundError(f"symbol '{name}' not found in library '{lib}'")

        library = self._get_symbol_library(lib)
        if library is None:
            raise SymbolNotFoundError(f"symbol library '{lib}' not found in symbol paths")

        symbol = library.find_symbol(name)
        if symbol is None:
            raise SymbolNotFoundError(f"symbol '{name}' not found in library '{lib}'")

        return symbol

    def get_symbol(self, lib: str, name: str) -> Optional[SymbolData]:
        """Find a symbol by library name and symbol name.

        Returns ``None`` if not found.
        """

        try:
            return self.find_symbol(lib, name)
        except SymbolNotFoundError:
            return None

    def list_symbol_libraries(self) -> list[str]:
        """List all available symbol libraries."""

        if not self._loaded:
            self.load_all()
        return list(self._symbol_index.keys())

    def list_symbols(self, lib: str) -> list[str]:
        """List all symbols in a library."""

        if not self._loaded:
            self.load_all()

        if lib in self._symbol_index:
            return list(self._symbol_index[lib].keys())

        library = self._get_symbol_library(lib)
        if library:
            return [s.name for s in library.symbols]
        return []

    def _get_symbol_library(self, lib: str) -> Optional[symbol_parser.SymbolLibrary]:
        """Get or load a symbol library by name."""

        if lib in self._symbol_libraries:
            return self._symbol_libraries[lib]

        for search_path in self._symbol_paths:
            sym_file = search_path / f"{lib}.kicad_sym"
            if sym_file.exists():
                library = symbol_parser.load_library(sym_file)
                self._symbol_libraries[lib] = library
                return library

            if search_path.is_file() and search_path.suffix == ".kicad_sym":
                if search_path.stem == lib:
                    library = symbol_parser.load_library(search_path)
                    self._symbol_libraries[lib] = library
                    return library

        return None

    def search_symbols(self, query: str, limit: int = 50) -> list[SymbolData]:
        """Search symbols in memory by name/lib/property."""

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

    @property
    def symbol_paths(self) -> list[Path]:
        """Get the configured symbol search paths."""

        return list(self._symbol_paths)


_DEFAULT_SYMBOLS: Optional["Symbols"] = None


def configure_default_symbols(
    *,
    symbol_paths: Optional[list[str]] = None,
    preload: bool = True,
) -> Symbols:
    """Configure a process-wide default ``Symbols`` manager."""

    global _DEFAULT_SYMBOLS
    _DEFAULT_SYMBOLS = Symbols(symbol_paths=symbol_paths or [])
    if preload:
        _DEFAULT_SYMBOLS.load_all()
    return _DEFAULT_SYMBOLS


def _parse_env_paths(env_var: str) -> list[str]:
    """Parse a colon- or semicolon-separated path list from an env var."""

    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return []

    parts: list[str] = []
    for segment in raw.replace(";", ":").split(":"):
        segment = segment.strip()
        if segment:
            parts.append(segment)
    return parts


def get_default_symbols() -> Optional[Symbols]:
    """Return the default ``Symbols`` manager.

    Priority:
    1. Singleton configured via ``configure_default_symbols()``.
    2. Paths from environment variable ``KICAD_SYMBOL_DIR``.
    3. ``None`` when neither source is available.
    """

    if _DEFAULT_SYMBOLS is not None:
        return _DEFAULT_SYMBOLS

    sym_paths = _parse_env_paths("KICAD_SYMBOL_DIR")
    if not sym_paths:
        return None

    return Symbols(symbol_paths=sym_paths)
