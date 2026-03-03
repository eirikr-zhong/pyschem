"""KiCad footprint parser (.pretty directory format).

This module provides parsing for KiCad footprint files (.kicad_mod).
Footprints are stored in .pretty directories, each as a separate .kicad_mod file.

This parser does NOT use regex - it uses basic string parsing to find
matching parentheses and extract footprint information.
"""

from pathlib import Path
from typing import Optional

from lib.symbols.data import FootprintData


def find_matching_end(s: str, start: int) -> int:
    """Find the matching closing parenthesis for an opening one.
    
    Args:
        s: The string to search
        start: Position of the opening parenthesis
        
    Returns:
        Position of matching closing parenthesis, or -1 if not found
    """
    depth = 0
    i = start
    while i < len(s):
        if s[i] == '(':
            depth += 1
        elif s[i] == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def extract_footprint(content: str, library_name: str) -> FootprintData:
    """Extract footprint data from .kicad_mod content.
    
    Args:
        content: The file content
        library_name: Name of the library
        
    Returns:
        FootprintData object
    """
    # Find the footprint name (first quoted string)
    footprint_name = None
    if '"' in content:
        start = content.find('"')
        end = content.find('"', start + 1)
        if start != -1 and end != -1:
            footprint_name = content[start+1:end]
    
    if not footprint_name:
        footprint_name = "unknown"
    
    # Count pads
    pad_count = count_pads(content)
    
    return FootprintData(
        name=footprint_name,
        library=library_name,
        pads=pad_count,
        bounding_box=None,
    )


def count_pads(content: str) -> int:
    """Count the number of pads in a footprint.
    
    Args:
        content: The footprint content
        
    Returns:
        Number of pads found
    """
    count = 0
    i = 0
    while i < len(content):
        # Match both (pad N and (pad "N" formats
        if content[i:i+5] == '(pad ':
            # Check this is a real pad - has a number or quoted number after pad
            rest = content[i+5:i+25]
            # Either starts with digit: (pad 1
            # Or starts with quote and digit: (pad "1"
            if rest and (rest[0].isdigit() or (rest.startswith('"') and len(rest) > 1 and rest[1].isdigit())):
                count += 1
                # Skip to end of this pad
                end = find_matching_end(content, i)
                if end != -1:
                    i = end + 1
                    continue
        i += 1
    return count


def parse_kicad_mod_file(file_path: Path, library_name: str) -> FootprintData:
    """Parse a KiCad footprint file (.kicad_mod).

    Args:
        file_path: Path to the .kicad_mod file
        library_name: Name of the footprint library (directory name)

    Returns:
        FootprintData object

    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Footprint file not found: {file_path}")

    content = file_path.read_text(encoding="utf-8")
    return parse_kicad_mod_content(content, file_path.stem, library_name)


def parse_kicad_mod_content(content: str, footprint_name: str, library_name: str) -> FootprintData:
    """Parse KiCad footprint content.

    Args:
        content: The s-expression content of the footprint
        footprint_name: Name of the footprint (from filename)
        library_name: Name of the library (directory name)

    Returns:
        FootprintData object
    """
    try:
        return extract_footprint(content, library_name)
    except Exception:
        # Return default footprint data on parse error
        return FootprintData(
            name=footprint_name,
            library=library_name,
            pads=0,
            bounding_box=None,
        )


def parse_kicad_mod_file_safe(file_path: Path, library_name: str) -> tuple[FootprintData, Optional[str]]:
    """Parse a KiCad footprint file with error handling.

    This function catches parsing errors and returns them as part of the result
    instead of raising, allowing the caller to handle or ignore errors.

    Args:
        file_path: Path to the .kicad_mod file
        library_name: Name of the footprint library

    Returns:
        Tuple of (FootprintData, error message or None)
    """
    if not file_path.exists():
        return (FootprintData(name=file_path.stem, library=library_name), 
                f"File not found: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
        footprint = parse_kicad_mod_content(content, file_path.stem, library_name)
        return (footprint, None)
    except Exception as e:
        return (FootprintData(name=file_path.stem, library=library_name),
                f"Parse error in {file_path.name}")


class FootprintLibrary:
    """Represents a loaded KiCad footprint library (.pretty directory)."""

    def __init__(self, name: str, dir_path: Path):
        """Initialize a footprint library.

        Args:
            name: Library name (directory name)
            dir_path: Path to the .pretty directory
        """
        self.name = name
        self.dir_path = dir_path
        self._footprints: dict[str, FootprintData] = {}
        self._loaded = False
        self._load_errors: list[str] = []

    def load(self) -> None:
        """Load all footprints from the library directory."""
        if self._loaded:
            return

        if not self.dir_path.exists():
            self._load_errors.append(f"Footprint library not found: {self.dir_path}")
            self._loaded = True
            return

        # Look for .kicad_mod files
        for mod_file in self.dir_path.glob("*.kicad_mod"):
            fp_data, error = parse_kicad_mod_file_safe(mod_file, self.name)
            if error:
                self._load_errors.append(error)
            else:
                self._footprints[fp_data.name] = fp_data

        self._loaded = True

    @property
    def footprints(self) -> dict[str, FootprintData]:
        """Get all footprints in this library."""
        if not self._loaded:
            self.load()
        return dict(self._footprints)

    @property
    def load_errors(self) -> list[str]:
        """Get list of errors from loading."""
        if not self._loaded:
            self.load()
        return list(self._load_errors)

    @property
    def is_valid(self) -> bool:
        """Check if library loaded successfully."""
        if not self._loaded:
            self.load()
        return len(self._load_errors) == 0 and len(self._footprints) > 0

    def find_footprint(self, name: str) -> Optional[FootprintData]:
        """Find a footprint by name.

        Args:
            name: Footprint name to find

        Returns:
            FootprintData if found, None otherwise
        """
        if not self._loaded:
            self.load()
        return self._footprints.get(name)


def load_library(dir_path: Path) -> FootprintLibrary:
    """Load a KiCad footprint library from a .pretty directory.

    Args:
        dir_path: Path to .pretty directory

    Returns:
        FootprintLibrary object

    Raises:
        FileNotFoundError: If the directory doesn't exist
    """
    return FootprintLibrary(name=dir_path.stem, dir_path=dir_path)
