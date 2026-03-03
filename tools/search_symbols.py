#!/usr/bin/env python3
"""Search KiCad symbols from preloaded in-memory indexes.

Examples:
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols LM358
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols --json LM358
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols --exact LM358
  python3 tools/search_symbols.py --symbol-path ~/Documents/kicad-symbols --show-properties LM358
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence, Union

from pyschem import Symbols


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search symbols from KiCad libraries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s LM358
  %(prog)s --json LM358
  %(prog)s --exact LM358
  %(prog)s --show-properties LM358
        """,
    )
    parser.add_argument("query", help="Search keyword")
    parser.add_argument(
        "--symbol-path",
        action="append",
        default=[],
        help="Path to .kicad_sym libraries (can be repeated)",
    )
    parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Exact match (case-sensitive) instead of fuzzy search",
    )
    parser.add_argument(
        "--show-properties",
        action="store_true",
        help="Show all symbol properties",
    )
    return parser


def format_symbol_text(symbol: Any, show_properties: bool = False) -> str:
    """Format a SymbolData object as human-readable text."""

    lines = []
    desc = symbol.properties.get("Description", "-")

    lines.append(f"{symbol.lib}:{symbol.name} | pins={len(symbol.pins)}")
    if desc and desc != "-":
        lines.append(f"  Description: {desc}")

    if show_properties and symbol.properties:
        lines.append("  Properties:")
        for key, value in symbol.properties.items():
            lines.append(f"    {key}: {value}")

    if symbol.pins:
        lines.append("  Pins:")
        for pin in symbol.pins:
            lines.append(f"    {pin.number}: {pin.name} ({pin.type})")

    return "\n".join(lines)


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


def search_symbols_exact(symbols: Symbols, query: str, limit: int) -> list:
    """Search symbols with exact (case-sensitive) matching."""

    if not symbols.is_loaded:
        symbols.load_all()

    results = []
    for lib_name, syms in symbols._symbol_index.items():
        for sym_name, symbol in syms.items():
            if sym_name == query:
                results.append(symbol)
                if len(results) >= limit:
                    return results

    if ":" in query:
        lib, name = query.split(":", 1)
        if lib in symbols._symbol_index and name in symbols._symbol_index[lib]:
            results.insert(0, symbols._symbol_index[lib][name])

    return results[:limit]


def main(argv: Union[Sequence[str], None] = None) -> int:
    args = build_parser().parse_args(argv)

    for path in args.symbol_path:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            print(f"Error: Symbol path does not exist: {path}", file=sys.stderr)
            return 1

    if not args.symbol_path:
        print("Error: At least one --symbol-path must be provided", file=sys.stderr)
        return 1

    try:
        symbols = Symbols(symbol_paths=args.symbol_path)
        result = symbols.load_all()

        if not result.success and result.error_count > 0:
            for err in result.errors[:5]:
                print(f"Warning: {err}", file=sys.stderr)

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
            for i, symbol in enumerate(rows, 1):
                print(f"{i}. {format_symbol_text(symbol, args.show_properties)}")
                if i < len(rows):
                    print()

        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
