"""KiCad symbol library parser (.kicad_sym format).

This module provides parsing for KiCad symbol library files (.kicad_sym).
The format uses s-expressions (like Lisp) with nested parentheses.

This parser uses parsimonious Grammar + NodeVisitor for robust parsing.
"""

from pathlib import Path
from typing import Optional

from parsimonious import Grammar, NodeVisitor, ParseError

from lib.symbols.data import PinDefinition, SymbolData, SymbolPrimitive


# ==============================================================================
# SECTION 1: PARSIMONIOUS GRAMMAR DEFINITION
# ==============================================================================

PIN_TYPES = frozenset([
    "input", "output", "bidirectional", "passive",
    "power_in", "power_out", "no_connect", "unspecified",
])

"""
KiCad Symbol Library Grammar.

Key design decisions:
- ws (whitespace) is placed between every token that may have spaces/tabs/newlines
- at_expr, name_expr, number_expr are specific rules that extract structured data
- sexpr is a catch-all for any balanced parentheses we don't need to inspect
- The grammar handles real KiCad files which use tabs and newlines liberally
"""

KICAD_SYM_GRAMMAR = Grammar(r"""
    library     = ws "(" ws "kicad_symbol_lib" ws body ws ")" ws
    body        = (top_item ws)*

    top_item    = symbol_def / sexpr

    # Symbol definition: (symbol "Name" body...)
    symbol_def  = "(" ws "symbol" ws qstring ws symbol_body ws ")"
    symbol_body = (symbol_item ws)*
    symbol_item = symbol_def / property_def / pin_def /
                  polyline_def / rectangle_def / circle_def / arc_def / sexpr

    # Property: (property "Name" "Value" ...)
    property_def  = "(" ws "property" ws qstring ws qstring ws prop_body ws ")"
    prop_body     = (sexpr ws)*

    # Pin: (pin TYPE STYLE body...)
    pin_def     = "(" ws "pin" ws pin_type ws pin_style ws pin_body ws ")"
    pin_type    = "input" / "output" / "bidirectional" / "passive" /
                  "power_in" / "power_out" / "no_connect" / "unspecified"
    pin_style   = "line" / "inverted_clock" / "input_low" / "output_low" /
                  "fall_edge" / "non_logic" / "inverted" / "clock"
    pin_body    = (pin_item ws)*
    pin_item    = at_expr / length_expr / name_expr / number_expr / sexpr

    # (at X Y [ANGLE])  - whitespace between each token
    at_expr     = "(" ws "at" ws number ws number ws number? ws ")"
    length_expr = "(" ws "length" ws number ws ")"

    # (name "TEXT" ...)
    name_expr   = "(" ws "name" ws qstring ws prop_body ws ")"

    # (number "TEXT" ...)
    number_expr = "(" ws "number" ws qstring ws prop_body ws ")"

    # Graphic primitives used by KiCad symbols
    polyline_def   = "(" ws "polyline" ws polyline_body ws ")"
    polyline_body  = (polyline_item ws)*
    polyline_item  = pts_expr / stroke_expr / fill_expr / sexpr

    pts_expr       = "(" ws "pts" ws (xy_expr ws)+ ")"
    xy_expr        = "(" ws "xy" ws number ws number ws ")"

    rectangle_def  = "(" ws "rectangle" ws rectangle_body ws ")"
    rectangle_body = (rectangle_item ws)*
    rectangle_item = start_expr / end_expr / stroke_expr / fill_expr / sexpr

    circle_def     = "(" ws "circle" ws circle_body ws ")"
    circle_body    = (circle_item ws)*
    circle_item    = center_expr / radius_expr / stroke_expr / fill_expr / sexpr

    arc_def        = "(" ws "arc" ws arc_body ws ")"
    arc_body       = (arc_item ws)*
    arc_item       = start_expr / mid_expr / end_expr / stroke_expr / fill_expr / sexpr

    start_expr     = "(" ws "start" ws number ws number ws ")"
    mid_expr       = "(" ws "mid" ws number ws number ws ")"
    end_expr       = "(" ws "end" ws number ws number ws ")"
    center_expr    = "(" ws "center" ws number ws number ws ")"
    radius_expr    = "(" ws "radius" ws number ws ")"

    stroke_expr    = "(" ws "stroke" ws stroke_body ws ")"
    stroke_body    = (stroke_item ws)*
    stroke_item    = width_expr / sexpr
    width_expr     = "(" ws "width" ws number ws ")"

    fill_expr      = "(" ws "fill" ws fill_body ws ")"
    fill_body      = (fill_item ws)*
    fill_item      = fill_type_expr / sexpr
    fill_type_expr = "(" ws "type" ws ident ws ")"
    ident          = ~r"[A-Za-z_][A-Za-z0-9_]*"

    # Generic balanced-paren catch-all
    sexpr         = "(" sexpr_inner ")"
    sexpr_inner   = (sexpr / non_paren)*
    non_paren     = ~r"[^()]+"

    # Quoted string: "..." (no escaping needed for KiCad files)
    qstring     = '"' ~r'[^"]*' '"'

    # Floating point / integer
    number      = ~r"-?[0-9]+\.?[0-9]*"

    # Whitespace (spaces, tabs, newlines)
    ws          = ~r"\s*"
""")


# ==============================================================================
# SECTION 2: NODE VISITOR IMPLEMENTATION
# ==============================================================================

class KicadSymVisitor(NodeVisitor):
    """Transform parse tree into SymbolData objects."""

    # ------------------------------------------------------------------ library

    def visit_library(self, node, children):
        """Return list[SymbolData] collected from body."""
        symbols = []
        for item in self._flatten(children):
            if isinstance(item, SymbolData):
                symbols.append(item)
        return symbols

    def visit_body(self, node, children):
        return self._flatten(children)

    # ---------------------------------------------------------------- symbol_def

    def visit_symbol_def(self, node, children):
        """Build SymbolData from name + collected child items."""
        flat = self._flatten(children)

        name = None
        properties: dict[str, str] = {}
        pins: list[PinDefinition] = []
        primitives: list[SymbolPrimitive] = []

        for item in flat:
            if isinstance(item, str) and name is None:
                name = item
            elif isinstance(item, SymbolData):
                # Top-level sub-symbol: collect its pins/properties upward
                pins.extend(item.pins)
                primitives.extend(item.primitives)
                properties.update(item.properties)
            elif isinstance(item, dict):
                kind = item.get("_kind")
                if kind == "property":
                    properties[item["name"]] = item["value"]
                elif kind == "pin":
                    pin = item.get("pin")
                    if pin is not None:
                        pins.append(pin)
                elif kind == "sub_symbol":
                    # Sub-symbol: absorb its pins
                    pins.extend(item.get("pins", []))
                    primitives.extend(item.get("primitives", []))
                elif kind == "primitive":
                    prim = item.get("primitive")
                    if prim is not None:
                        primitives.append(prim)

        if name is None:
            name = ""

        # Detect sub-symbol pattern: "ParentName_N_M"
        parts = name.rsplit("_", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            return {
                "_kind": "sub_symbol",
                "name": name,
                "pins": pins,
                "primitives": primitives,
            }

        return SymbolData(
            name=name,
            lib="",
            pins=pins,
            primitives=primitives,
            properties=properties,
            bounding_box=None,
        )

    def visit_symbol_body(self, node, children):
        return self._flatten(children)

    def visit_symbol_item(self, node, children):
        return self._flatten(children)

    # -------------------------------------------------------------- property_def

    def visit_property_def(self, node, children):
        flat = self._flatten(children)
        name = None
        value = None
        for item in flat:
            if isinstance(item, str) and item:
                if name is None:
                    name = item
                elif value is None:
                    value = item
        return {"_kind": "property", "name": name or "", "value": value or ""}

    def visit_prop_body(self, node, children):
        return self._flatten(children)

    # ------------------------------------------------------------------ pin_def

    def visit_pin_def(self, node, children):
        flat = self._flatten(children)
        pin_type = "passive"
        x = y = 0.0
        orientation = 0
        length = 0.0
        pin_name = "~"
        pin_number = None

        for item in flat:
            if isinstance(item, str) and item in PIN_TYPES:
                pin_type = item
            elif isinstance(item, dict):
                kind = item.get("_kind")
                if kind == "at":
                    x, y, orientation = item["pos"]
                elif kind == "length":
                    length = item["value"]
                elif kind == "name":
                    pin_name = item["value"]
                elif kind == "number":
                    pin_number = item["value"]

        if pin_number is not None:
            return {
                "_kind": "pin",
                "pin": PinDefinition(
                    number=pin_number,
                    name=pin_name,
                    type=pin_type,
                    x=x,
                    y=y,
                    orientation=orientation,
                    length=length,
                ),
            }
        return {"_kind": "pin", "pin": None}

    def visit_pin_body(self, node, children):
        return self._flatten(children)

    def visit_pin_item(self, node, children):
        return self._flatten(children)

    def visit_pin_type(self, node, children):
        return node.text.strip()

    def visit_pin_style(self, node, children):
        return None  # We don't need pin style

    # ------------------------------------------------------------------ at_expr

    def visit_at_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        x = nums[0] if len(nums) > 0 else 0.0
        y = nums[1] if len(nums) > 1 else 0.0
        o = int(nums[2]) if len(nums) > 2 else 0
        return {"_kind": "at", "pos": (x, y, o)}

    def visit_length_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        return {"_kind": "length", "value": nums[0] if nums else 0.0}

    # ---------------------------------------------------------------- name/number expr

    def visit_name_expr(self, node, children):
        flat = self._flatten(children)
        for item in flat:
            if isinstance(item, str) and item:
                return {"_kind": "name", "value": item}
        return {"_kind": "name", "value": "~"}

    def visit_number_expr(self, node, children):
        flat = self._flatten(children)
        for item in flat:
            if isinstance(item, str) and item:
                return {"_kind": "number", "value": item}
        return {"_kind": "number", "value": None}

    # ------------------------------------------------------------ primitive defs

    def visit_polyline_def(self, node, children):
        points: list[tuple[float, float]] = []
        stroke_width = 0.254
        fill = "none"
        for item in self._flatten(children):
            if not isinstance(item, dict):
                continue
            kind = item.get("_kind")
            if kind == "pts":
                points = item.get("points", [])
            elif kind == "stroke":
                stroke_width = item.get("width", stroke_width)
            elif kind == "fill":
                fill = item.get("fill", fill)

        if len(points) < 2:
            return None
        primitive = SymbolPrimitive(
            kind="polyline",
            points=points,
            stroke_width=stroke_width,
            fill=fill,
        )
        return {"_kind": "primitive", "primitive": primitive}

    def visit_rectangle_def(self, node, children):
        start = None
        end = None
        stroke_width = 0.254
        fill = "none"
        for item in self._flatten(children):
            if not isinstance(item, dict):
                continue
            kind = item.get("_kind")
            if kind == "start":
                start = item.get("point")
            elif kind == "end":
                end = item.get("point")
            elif kind == "stroke":
                stroke_width = item.get("width", stroke_width)
            elif kind == "fill":
                fill = item.get("fill", fill)

        if start is None or end is None:
            return None

        x0, y0 = start
        x1, y1 = end
        points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        primitive = SymbolPrimitive(
            kind="polyline",
            points=points,
            stroke_width=stroke_width,
            fill=fill,
        )
        return {"_kind": "primitive", "primitive": primitive}

    def visit_circle_def(self, node, children):
        center = None
        radius = None
        stroke_width = 0.254
        fill = "none"
        for item in self._flatten(children):
            if not isinstance(item, dict):
                continue
            kind = item.get("_kind")
            if kind == "center":
                center = item.get("point")
            elif kind == "radius":
                radius = item.get("value")
            elif kind == "stroke":
                stroke_width = item.get("width", stroke_width)
            elif kind == "fill":
                fill = item.get("fill", fill)

        if center is None or radius is None:
            return None

        primitive = SymbolPrimitive(
            kind="circle",
            points=[center],
            radius=radius,
            stroke_width=stroke_width,
            fill=fill,
        )
        return {"_kind": "primitive", "primitive": primitive}

    def visit_arc_def(self, node, children):
        start = mid = end = None
        stroke_width = 0.254
        fill = "none"
        for item in self._flatten(children):
            if not isinstance(item, dict):
                continue
            kind = item.get("_kind")
            if kind == "start":
                start = item.get("point")
            elif kind == "mid":
                mid = item.get("point")
            elif kind == "end":
                end = item.get("point")
            elif kind == "stroke":
                stroke_width = item.get("width", stroke_width)
            elif kind == "fill":
                fill = item.get("fill", fill)

        if start is None or mid is None or end is None:
            return None

        primitive = SymbolPrimitive(
            kind="arc",
            points=[start, mid, end],
            stroke_width=stroke_width,
            fill=fill,
        )
        return {"_kind": "primitive", "primitive": primitive}

    def visit_pts_expr(self, node, children):
        points = [
            p.get("point") for p in self._flatten(children)
            if isinstance(p, dict) and p.get("_kind") == "xy"
        ]
        return {"_kind": "pts", "points": [p for p in points if p is not None]}

    def visit_xy_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        if len(nums) >= 2:
            return {"_kind": "xy", "point": (nums[0], nums[1])}
        return {"_kind": "xy", "point": (0.0, 0.0)}

    def visit_start_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        if len(nums) >= 2:
            return {"_kind": "start", "point": (nums[0], nums[1])}
        return {"_kind": "start", "point": (0.0, 0.0)}

    def visit_mid_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        if len(nums) >= 2:
            return {"_kind": "mid", "point": (nums[0], nums[1])}
        return {"_kind": "mid", "point": (0.0, 0.0)}

    def visit_end_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        if len(nums) >= 2:
            return {"_kind": "end", "point": (nums[0], nums[1])}
        return {"_kind": "end", "point": (0.0, 0.0)}

    def visit_center_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        if len(nums) >= 2:
            return {"_kind": "center", "point": (nums[0], nums[1])}
        return {"_kind": "center", "point": (0.0, 0.0)}

    def visit_radius_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        return {"_kind": "radius", "value": nums[0] if nums else 0.0}

    def visit_stroke_expr(self, node, children):
        width = 0.254
        for item in self._flatten(children):
            if isinstance(item, dict) and item.get("_kind") == "width":
                width = item.get("value", width)
        return {"_kind": "stroke", "width": width}

    def visit_width_expr(self, node, children):
        nums = [c for c in self._flatten(children) if isinstance(c, float)]
        return {"_kind": "width", "value": nums[0] if nums else 0.254}

    def visit_fill_expr(self, node, children):
        fill = "none"
        for item in self._flatten(children):
            if isinstance(item, dict) and item.get("_kind") == "fill_type":
                fill = item.get("value", fill)
        return {"_kind": "fill", "fill": fill}

    def visit_fill_type_expr(self, node, children):
        flat = self._flatten(children)
        for item in flat:
            if isinstance(item, str) and item:
                return {"_kind": "fill_type", "value": item}
        return {"_kind": "fill_type", "value": "none"}

    def visit_ident(self, node, children):
        return node.text.strip()

    # ----------------------------------------------------------------- primitives

    def visit_qstring(self, node, children):
        text = node.text
        # Strip surrounding quotes
        if text.startswith('"') and text.endswith('"'):
            return text[1:-1]
        return text

    def visit_number(self, node, children):
        try:
            return float(node.text)
        except (ValueError, TypeError):
            return 0.0

    # ----------------------------------------------------------------- catch-alls

    def visit_sexpr(self, node, children):
        return None

    def visit_sexpr_inner(self, node, children):
        return None

    def visit_non_paren(self, node, children):
        return None

    def visit_top_item(self, node, children):
        return self._flatten(children)

    def generic_visit(self, node, children):
        return self._flatten(children)

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _flatten(children) -> list:
        """Recursively flatten nested lists, dropping None values."""
        result = []
        for child in children:
            if child is None:
                continue
            elif isinstance(child, list):
                result.extend(KicadSymVisitor._flatten(child))
            else:
                result.append(child)
        return result


# ==============================================================================
# SECTION 3: PUBLIC API
# ==============================================================================

def parse_kicad_sym_file(file_path: Path) -> list[SymbolData]:
    """Parse a KiCad symbol library file (.kicad_sym)."""
    if not file_path.exists():
        raise FileNotFoundError(f"Symbol library not found: {file_path}")
    content = file_path.read_text(encoding="utf-8")
    return parse_kicad_sym_content(content, file_path.stem)


def parse_kicad_sym_content(content: str, lib_name: str) -> list[SymbolData]:
    """Parse KiCad symbol library content."""
    try:
        tree = KICAD_SYM_GRAMMAR.parse(content)
        visitor = KicadSymVisitor()
        symbols = visitor.visit(tree) or []
        # visitor.visit may return a nested list due to generic_visit on library
        if isinstance(symbols, list):
            flat: list[SymbolData] = []
            def _collect(items):
                for item in items:
                    if isinstance(item, SymbolData):
                        flat.append(item)
                    elif isinstance(item, list):
                        _collect(item)
            _collect(symbols)
            symbols = flat
        for symbol in symbols:
            symbol.lib = lib_name
        return symbols
    except ParseError as e:
        raise ValueError(f"Failed to parse {lib_name}: {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to parse {lib_name}: {e}") from e


def parse_kicad_sym_file_safe(file_path: Path) -> tuple[list[SymbolData], Optional[str]]:
    """Parse with error handling."""
    if not file_path.exists():
        return ([], f"File not found: {file_path}")
    try:
        content = file_path.read_text(encoding="utf-8")
        symbols = parse_kicad_sym_content(content, file_path.stem)
        return (symbols, None)
    except Exception as e:
        return ([], f"Parse error in {file_path.name}: {e}")


class SymbolLibrary:
    """Represents a loaded KiCad symbol library."""

    def __init__(self, name: str, file_path: Path):
        self.name = name
        self.file_path = file_path
        self._symbols: list[SymbolData] = []
        self._loaded = False
        self._load_error: Optional[str] = None

    def load(self):
        if self._loaded:
            return
        symbols, error = parse_kicad_sym_file_safe(self.file_path)
        self._symbols = symbols
        self._load_error = error
        self._loaded = True

    @property
    def symbols(self) -> list[SymbolData]:
        if not self._loaded:
            self.load()
        return self._symbols

    @property
    def load_error(self) -> Optional[str]:
        if not self._loaded:
            self.load()
        return self._load_error

    @property
    def is_valid(self) -> bool:
        if not self._loaded:
            self.load()
        return self._load_error is None and len(self._symbols) > 0

    def find_symbol(self, name: str) -> Optional[SymbolData]:
        if not self._loaded:
            self.load()
        for symbol in self._symbols:
            if symbol.name == name:
                return symbol
        return None


def load_library(file_path: Path) -> SymbolLibrary:
    """Load a KiCad symbol library from a file."""
    return SymbolLibrary(name=file_path.stem, file_path=file_path)
