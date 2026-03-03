#!/usr/bin/env python3
"""Search KiCad symbols/footprints from preloaded in-memory indexes.

Examples:
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols symbol LM358
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols footprint SOIC-8
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols --json symbol LM358
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols --exact symbol LM358
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols --show-properties symbol LM358
"""

import argparse
import json
import sys
from typing import Any, Sequence, Union

from pyschem import Symbols


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Search symbols/footprints from KiCad libraries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s symbol LM358
  %(prog)s footprint SOIC-8
  %(prog)s --json symbol LM358
  %(prog)s --exact symbol LM358
  %(prog)s --show-properties symbol LM358
        """
    )
    p.add_argument("kind", choices=["symbol", "footprint"], help="What to search")
    p.add_argument("query", help="Search keyword")
    p.add_argument("--symbol-path", action="append", default=[], 
                   help="Path to .kicad_sym libraries (can be repeated)")
    p.add_argument("--footprint-path", action="append", default=[],
                   help="Path to .pretty libraries (can be repeated)")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    p.add_argument("--json", action="store_true", 
                   help="Output results as JSON")
    p.add_argument("--exact", action="store_true",
                   help="Exact match (case-sensitive) instead of fuzzy search")
    p.add_argument("--show-properties", action="store_true",
                   help="Show properties for symbols")
    return p


def format_symbol_text(symbol: Any, show_pins: bool = True, show_properties: bool = False) -> str:
    """Format a SymbolData object as human-readable text."""
    lines = []
    fp = symbol.properties.get("Footprint", "-")
    desc = symbol.properties.get("Description", "-")
    
    lines.append(f"{symbol.lib}:{symbol.name} | pins={len(symbol.pins)} | footprint={fp}")
    if desc and desc != "-":
        lines.append(f"  Description: {desc}")
    
    if show_properties and symbol.properties:
        lines.append("  Properties:")
        for key, value in symbol.properties.items():
            lines.append(f"    {key}: {value}")
    
    if show_pins and symbol.pins:
        lines.append("  Pins:")
        for pin in symbol.pins:
            lines.append(f"    {pin.number}: {pin.name} ({pin.type})")
    
    return "\n".join(lines)


def format_footprint_text(footprint: Any) -> str:
    """Format a FootprintData object as human-readable text."""
    return f"{footprint.library}:{footprint.name} | pads={footprint.pads}"


def symbol_to_dict(symbol: Any) -> dict:
    """Convert SymbolData to a dictionary for JSON output."""
    return {
        "lib": symbol.lib,
        "name": symbol.name,
        "pins": [
            {
                "number": pin.number,
                "name": pin.name,
                "type": pin.type,
                "x": pin.x,
                "y": pin.y,
                "orientation": pin.orientation,
            }
            for pin in symbol.pins
        ],
        "properties": symbol.properties,
        "bounding_box": symbol.bounding_box,
    }


def footprint_to_dict(footprint: Any) -> dict:
    """Convert FootprintData to a dictionary for JSON output."""
    return {
        "library": footprint.library,
        "name": footprint.name,
        "pads": footprint.pads,
        "bounding_box": footprint.bounding_box,
    }


def search_symbols_exact(symbols: Symbols, query: str, limit: int) -> list:
    """Search symbols with exact (case-sensitive) matching."""
    if not symbols.is_loaded:
        symbols.load_all()
    
    results = []
    for lib_name, syms in symbols._symbol_index.items():
        for sym_name, symbol in syms.items():
            if sym_name == query:  # Exact match on symbol name
                results.append(symbol)
                if len(results) >= limit:
                    return results
    
    # Also check exact lib:name format
    if ":" in query:
        lib, name = query.split(":", 1)
        if lib in symbols._symbol_index and name in symbols._symbol_index[lib]:
            results.insert(0, symbols._symbol_index[lib][name])
    
    return results[:limit]


def search_footprints_exact(symbols: Symbols, query: str, limit: int) -> list:
    """Search footprints with exact (case-sensitive) matching."""
    if not symbols.is_loaded:
        symbols.load_all()
    
    results = []
    for lib_name, fps in symbols._footprint_index.items():
        for fp_name, footprint in fps.items():
            if fp_name == query:  # Exact match on footprint name
                results.append(footprint)
                if len(results) >= limit:
                    return results
    
    # Also check exact lib:name format
    if ":" in query:
        lib, name = query.split(":", 1)
        if lib in symbols._footprint_index and name in symbols._footprint_index[lib]:
            results.insert(0, symbols._footprint_index[lib][name])
    
    return results[:limit]


def main(argv: Union[Sequence[str], None] = None) -> int:
    args = build_parser().parse_args(argv)
    
    # Validate paths exist
    for path in args.symbol_path:
        from pathlib import Path
        p = Path(path).expanduser().resolve()
        if not p.exists():
            print(f"Error: Symbol path does not exist: {path}", file=sys.stderr)
            return 1
    
    for path in args.footprint_path:
        from pathlib import Path
        p = Path(path).expanduser().resolve()
        if not p.exists():
            print(f"Error: Footprint path does not exist: {path}", file=sys.stderr)
            return 1
    
    # Check that at least one path is provided
    if not args.symbol_path and not args.footprint_path:
        print("Error: At least one of --symbol-path or --footprint-path must be provided", 
              file=sys.stderr)
        return 1
    
    try:
        symbols = Symbols(
            symbol_paths=args.symbol_path, 
            footprint_paths=args.footprint_path
        )
        result = symbols.load_all()
        
        if not result.success and result.error_count > 0:
            # Print warning but continue
            for err in result.errors[:5]:  # Limit error output
                print(f"Warning: {err}", file=sys.stderr)
        
        # Perform search based on args
        if args.kind == "symbol":
            if args.exact:
                rows = search_symbols_exact(symbols, args.query, args.limit)
            else:
                rows = symbols.search_symbols(args.query, limit=args.limit)
            
            if not rows:
                print(f"No symbols found matching '{args.query}'", file=sys.stderr)
                return 1
            
            if args.json:
                output = {
                    "query": args.query,
                    "match_mode": "exact" if args.exact else "fuzzy",
                    "loaded_libs": result.loaded_count,
                    "load_errors": result.error_count,
                    "count": len(rows),
                    "results": [symbol_to_dict(s) for s in rows],
                }
                print(json.dumps(output, indent=2))
            else:
                print(f"Loaded libs: {result.loaded_count}, load errors: {result.error_count}")
                print(f"Symbol matches: {len(rows)}")
                for i, s in enumerate(rows, 1):
                    # Pins are shown by default in text mode for faster component inspection.
                    print(f"{i}. {format_symbol_text(s, True, args.show_properties)}")
                    if i < len(rows):
                        print()
        else:  # footprint
            if args.exact:
                rows = search_footprints_exact(symbols, args.query, args.limit)
            else:
                rows = symbols.search_footprints(args.query, limit=args.limit)
            
            if not rows:
                print(f"No footprints found matching '{args.query}'", file=sys.stderr)
                return 1
            
            if args.json:
                output = {
                    "query": args.query,
                    "match_mode": "exact" if args.exact else "fuzzy",
                    "loaded_libs": result.loaded_count,
                    "load_errors": result.error_count,
                    "count": len(rows),
                    "results": [footprint_to_dict(f) for f in rows],
                }
                print(json.dumps(output, indent=2))
            else:
                print(f"Loaded libs: {result.loaded_count}, load errors: {result.error_count}")
                print(f"Footprint matches: {len(rows)}")
                for i, f in enumerate(rows, 1):
                    print(f"{i}. {format_footprint_text(f)}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
