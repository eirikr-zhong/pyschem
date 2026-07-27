"""Schematic and Sheet classes for circuit representation.

Canvas / page defaults
----------------------
When exporting to SVG without specifying a *page*, the schematic uses
**A1 portrait** (1684 × 2384 px at 96 dpi) as the default canvas.  Pass a
:class:`~lib.core.page.PageConfig` to ``get_svg_string()``,
``export_svg()``, or ``render()`` to choose a different paper size or
custom dimensions::

    from lib.core.page import PageConfig
    sch.export_svg("out.svg", page=PageConfig.a3(landscape=True))
    sch.export_svg("out.svg", page=PageConfig(width=1920, height=1080))
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Optional

from lib.core.connect import connect as _connect_pins, derive_nets
from lib.core.net import Net, NetLabel
from lib.core.page import PageConfig
from lib.core.part import Part, Pin
from lib.core.style import Style
from lib.errors import RenderPathError

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from lib.core.render_style import RenderTemplate


_BOM_BASE_COLUMNS = ("References", "Quantity", "Value", "Footprint", "Lib ID")


def _natural_reference_key(ref: str) -> tuple[tuple[int, object], ...]:
    """Return a stable natural-sort key for a reference designator."""
    return tuple(
        (0, int(fragment)) if fragment.isdigit() else (1, fragment.casefold())
        for fragment in re.split(r"(\d+)", ref)
    )


@dataclass
class Sheet:
    """Represents a schematic sheet for organizing components."""

    name: str
    _parts: list[Part] = field(default_factory=list)

    @property
    def parts(self) -> list[Part]:
        return list(self._parts)


@dataclass
class Schematic:
    """Represents a schematic diagram (possibly multi-page)."""

    name: str
    _parts: list[Part] = field(default_factory=list)
    _sheets: dict[str, Sheet] = field(default_factory=dict)
    _default_sheet: Sheet = field(default_factory=lambda: Sheet(name="main"))

    def __post_init__(self) -> None:
        self._sheets["main"] = self._default_sheet

    def add_part(self, part: Part, sheet: Optional[str] = None) -> Part:
        target_sheet = self._sheets.get(sheet, self._default_sheet) if sheet else self._default_sheet
        target_sheet._parts.append(part)
        self._parts.append(part)
        return part

    def connect(self, *pins: Pin) -> None:
        """Connect pins together in the pin graph.

        Args:
            *pins: Two or more :class:`~lib.core.part.Pin` objects.

        Raises:
            ValueError: If fewer than two pins are provided.
            TypeError: If an item is not a ``Pin``.
        """
        _connect_pins(*pins)

    def erc(self, *, raise_on_error: bool = True) -> list[str]:
        """Run Electrical Rules Check based on the pin graph.

        Checks:
        - Conflicting net names: two NetLabels with different names
          in the same connected component.
        - Floating NetLabels: a NetLabel whose pin is not connected
          to any real component pin.

        Args:
            raise_on_error: When ``True`` (default) and there are ERC errors,
                            raise :exc:`~lib.errors.ERCError`.

        Returns:
            A list of human-readable error strings (empty when no errors).
        """
        from lib.errors import ERCError

        errors: list[str] = []

        pin_to_part: dict[int, Part] = {}
        all_pins: list[Pin] = []
        for part in self._parts:
            for pin in part.pins.values():
                pin_to_part[id(pin)] = part
                all_pins.append(pin)

        visited: set[int] = set()
        for pin in all_pins:
            if id(pin) in visited:
                continue

            component: list[Pin] = []
            queue: list[Pin] = [pin]
            while queue:
                p = queue.pop(0)
                if id(p) in visited:
                    continue
                visited.add(id(p))
                component.append(p)
                for neighbor in p.connected_pins:
                    if id(neighbor) not in visited:
                        queue.append(neighbor)

            net_names: set[str] = set()
            has_real_pin = False
            for p in component:
                owner = pin_to_part.get(id(p))
                if isinstance(owner, NetLabel):
                    net_names.add(owner.net_name)
                else:
                    has_real_pin = True

            if len(net_names) > 1:
                names_str = ", ".join(sorted(net_names))
                errors.append(
                    f"ERC: conflicting net names in same component: {names_str}"
                )

            if net_names and not has_real_pin and len(component) == 1:
                name = next(iter(net_names))
                errors.append(
                    f"ERC: floating NetLabel '{name}' — not connected to any component pin"
                )

        if errors and raise_on_error:
            raise ERCError("\n".join(errors))

        return errors

    def add_sheet(self, name: str) -> Sheet:
        if name in self._sheets:
            raise ValueError(f"sheet '{name}' already exists")
        sheet = Sheet(name=name)
        self._sheets[name] = sheet
        return sheet

    def place(
        self,
        part: Part,
        *,
        x: float,
        y: float,
        anchor: str = "center",
        rotation: int = 0,
        locked: bool = True,
        style: "Style | None" = None,
    ) -> None:
        if not any(existing is part for existing in self._parts):
            self.add_part(part)
        # Preserve existing per-part render settings (for example Junction/NetLabel
        # ref-text visibility defaults) while applying placement parameters.
        base_style = part.get_style().merge(
            Style(x=x, y=y, anchor=anchor, rotation=rotation, locked=locked)
        )
        if style is not None:
            base_style = base_style.merge(style)
        part.set_style(base_style)

    def _build_dot(self) -> str:
        """Build a DOT graph from the pin-graph–derived nets."""
        parts_by_ref = {p.ref: p for p in self._parts}
        nets = derive_nets(self._parts)

        lines: list[str] = [f'graph "{self.name}" {{', "  rankdir=LR;"]

        for part in self._parts:
            if isinstance(part, NetLabel):
                continue
            ref = part.ref or "?"
            value = part.value or ""
            label = f"{ref}\\n{value}" if value else ref
            lines.append(f'  "{ref}" [shape=box,label="{label}"];')

        for net in nets:
            is_anon = net.name.startswith("_anon")
            net_id = f"net:{net.name}"

            if is_anon:
                lines.append(
                    f'  "{net_id}" [shape=ellipse,style=dashed,label="{net.name}"];'
                )
            else:
                lines.append(f'  "{net_id}" [shape=ellipse,label="{net.name}"];')

            for pin in net.pins:
                ref = pin.part_ref
                if ref not in parts_by_ref:
                    lines.append(f'  "{ref}" [shape=box,label="{ref}"];')

                if is_anon:
                    edge_label = pin.key
                else:
                    edge_label = f"{pin.key} [{net.name}]"

                lines.append(f'  "{net_id}" -- "{ref}" [label="{edge_label}"];')

        lines.append("}")
        return "\n".join(lines) + "\n"

    def get_dot_string(self) -> str:
        return self._build_dot()

    def _build_svg(
        self,
        *,
        page: Optional[PageConfig] = None,
        width: float = 0,
        height: float = 0,
        template: Optional["RenderTemplate"] = None,
        debug: bool = False,
        viewbox: Optional[tuple[float, float, float, float]] = None,
        fit_to_content: bool = False,
    ) -> str:
        from lib.render.schematic_svg import render_schematic_svg
        return render_schematic_svg(self, page=page, width=width, height=height,
                                    template=template, debug=debug, viewbox=viewbox,
                                    fit_to_content=fit_to_content)

    def get_svg_string(
        self,
        *,
        page: Optional[PageConfig] = None,
        width: float = 0,
        height: float = 0,
        template: Optional["RenderTemplate"] = None,
    ) -> str:
        return self._build_svg(page=page, width=width, height=height,
                               template=template)

    def render(self, path: str, *, fmt: str = "dot", page: Optional[PageConfig] = None,
               template: Optional["RenderTemplate"] = None) -> None:
        fmt_lower = fmt.lower()
        if fmt_lower == "dot":
            content = self._build_dot()
        elif fmt_lower == "svg":
            content = self._build_svg(page=page, template=template)
        else:
            raise NotImplementedError(f"Unsupported render format: '{fmt}'. Use 'dot' or 'svg'.")

        out = Path(path).expanduser()
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise RenderPathError(f"cannot create/write output path: {path}") from exc

    def export_dot(self, path: str) -> None:
        self.render(path, fmt="dot")

    def export_bom(self, path: str) -> None:
        """Write a grouped bill of materials as a UTF-8 CSV file.

        Physical parts with the same value, footprint, library ID, and BOM
        fields are grouped into one row. Net labels and annotation markers are
        excluded because they are not purchasable components.
        """
        from lib.core.junction import Junction

        purchasable_parts = [
            part
            for part in self._parts
            if not isinstance(part, (NetLabel, Junction))
            and part.lib_id != "Annotation:NoConnect"
        ]
        custom_columns = sorted(
            {field_name for part in purchasable_parts for field_name in part.bom_fields}
        )
        grouped: dict[
            tuple[str, str, str, tuple[tuple[str, str], ...]], list[Part]
        ] = {}
        for part in purchasable_parts:
            fields = tuple(
                (field_name, part.bom_fields.get(field_name, ""))
                for field_name in custom_columns
            )
            key = (
                part.value or "",
                part.footprint or "",
                part.lib_id,
                fields,
            )
            grouped.setdefault(key, []).append(part)

        rows: list[dict[str, str]] = []
        for parts in grouped.values():
            sorted_parts = sorted(parts, key=lambda part: _natural_reference_key(part.ref or ""))
            first_part = sorted_parts[0]
            row = {
                "References": ",".join(part.ref or "" for part in sorted_parts),
                "Quantity": str(len(sorted_parts)),
                "Value": first_part.value or "",
                "Footprint": first_part.footprint or "",
                "Lib ID": first_part.lib_id,
            }
            row.update({column: first_part.bom_fields.get(column, "") for column in custom_columns})
            rows.append(row)

        rows.sort(key=lambda row: _natural_reference_key(row["References"].split(",", 1)[0]))
        fieldnames = [*_BOM_BASE_COLUMNS, *custom_columns]

        out = Path(path).expanduser()
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        except OSError as exc:
            raise RenderPathError(f"cannot create/write output path: {path}") from exc

    def export_svg(
        self,
        path: str,
        *,
        page: Optional[PageConfig] = None,
        width: float = 0,
        height: float = 0,
        template: Optional["RenderTemplate"] = None,
        debug: bool = False,
        viewbox: Optional[tuple[float, float, float, float]] = None,
        fit_to_content: bool = False,
    ) -> None:
        content = self._build_svg(page=page, width=width, height=height,
                                  template=template, debug=debug, viewbox=viewbox,
                                  fit_to_content=fit_to_content)
        out = Path(path).expanduser()
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise RenderPathError(f"cannot create/write output path: {path}") from exc

    @property
    def parts(self) -> list[Part]:
        return list(self._parts)

    @property
    def nets(self) -> list[Net]:
        return derive_nets(self._parts)

    @property
    def sheets(self) -> dict[str, Sheet]:
        return dict(self._sheets)
