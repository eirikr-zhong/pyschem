"""Unit tests for lib/core/schematic.py — Schematic and Sheet classes.

Test IDs
--------
SCH-01  test_sheet_parts_property_returns_copy
SCH-03  test_sheet_parts_empty_on_new_sheet
SCH-05  test_schematic_initializes_with_main_sheet
SCH-06  test_add_part_to_default_sheet
SCH-07  test_add_part_to_named_existing_sheet
SCH-08  test_add_part_to_nonexistent_sheet_falls_back_to_default
SCH-12  test_add_sheet_creates_and_returns_sheet
SCH-13  test_add_sheet_duplicate_name_raises_value_error
SCH-14  test_place_sets_style_on_part
SCH-15  test_place_all_params_stored_correctly
SCH-16  test_render_raises_not_implemented
SCH-17  test_export_dot_raises_not_implemented
SCH-18  test_parts_property_returns_all_parts
SCH-20  test_sheets_property_returns_copy_with_main
"""

import pytest

from lib.core.part import Part
from lib.core.render_style import TextPlacementStyle
from lib.core.schematic import Schematic, Sheet
from lib.core.style import Style


# ---------------------------------------------------------------------------
# Sheet tests
# ---------------------------------------------------------------------------

def test_sheet_parts_property_returns_copy() -> None:
    """Modifying returned parts list must not affect internal _parts."""
    sheet = Sheet(name="test")
    part = Part(lib_id="Device:R", ref="R1")
    sheet._parts.append(part)
    
    parts_copy = sheet.parts
    parts_copy.clear()
    
    assert len(sheet.parts) == 1


def test_sheet_parts_empty_on_new_sheet() -> None:
    """New Sheet should have empty parts list."""
    sheet = Sheet(name="empty")
    assert sheet.parts == []


# ---------------------------------------------------------------------------
# Schematic initialization tests
# ---------------------------------------------------------------------------

def test_schematic_initializes_with_main_sheet() -> None:
    """New Schematic must have a 'main' sheet in sheets dict."""
    sch = Schematic("test_sch")
    assert "main" in sch.sheets
    assert sch.sheets["main"].name == "main"


# ---------------------------------------------------------------------------
# add_part tests
# ---------------------------------------------------------------------------

def test_add_part_to_default_sheet() -> None:
    """add_part without sheet param adds to main sheet."""
    sch = Schematic("test")
    part = Part(lib_id="Device:R", ref="R1")
    sch.add_part(part)
    
    assert part in sch.parts
    assert part in sch.sheets["main"].parts


def test_add_part_to_named_existing_sheet() -> None:
    """add_part with existing sheet name adds to that sheet."""
    sch = Schematic("test")
    sch.add_sheet("sub")
    part = Part(lib_id="Device:R", ref="R1")
    sch.add_part(part, sheet="sub")
    
    assert part in sch.parts
    assert part in sch.sheets["sub"].parts


def test_add_part_to_nonexistent_sheet_falls_back_to_default() -> None:
    """add_part with nonexistent sheet name falls back to main sheet."""
    sch = Schematic("test")
    part = Part(lib_id="Device:R", ref="R1")
    sch.add_part(part, sheet="nonexistent")
    
    assert part in sch.parts
    assert part in sch.sheets["main"].parts


# ---------------------------------------------------------------------------
# add_sheet tests
# ---------------------------------------------------------------------------

def test_add_sheet_creates_and_returns_sheet() -> None:
    """add_sheet must create and return a new Sheet."""
    sch = Schematic("test")
    sheet = sch.add_sheet("page2")
    
    assert isinstance(sheet, Sheet)
    assert sheet.name == "page2"
    assert "page2" in sch.sheets


def test_add_sheet_duplicate_name_raises_value_error() -> None:
    """add_sheet with duplicate name must raise ValueError."""
    sch = Schematic("test")
    sch.add_sheet("page2")
    
    with pytest.raises(ValueError, match="already exists"):
        sch.add_sheet("page2")


# ---------------------------------------------------------------------------
# place tests
# ---------------------------------------------------------------------------

def test_place_sets_style_on_part() -> None:
    """place() must set a Style on the part."""
    sch = Schematic("test")
    part = Part(lib_id="Device:R", ref="R1")
    part.set_style(Style(ref_text=TextPlacementStyle(visible=False)))
    sch.add_part(part)
    
    sch.place(part, x=10.0, y=20.0)
    
    style = part.get_style()
    assert style.x == 10.0
    assert style.y == 20.0
    assert style.ref_text is not None
    assert style.ref_text.visible is False


def test_place_all_params_stored_correctly() -> None:
    """place() must store all parameters in the Style."""
    sch = Schematic("test")
    part = Part(lib_id="Device:R", ref="R1")
    sch.add_part(part)
    
    sch.place(part, x=5.0, y=15.0, anchor="left", rotation=90, scale=1.5, locked=True)
    
    style = part.get_style()
    assert style.x == 5.0
    assert style.y == 15.0
    assert style.anchor == "left"
    assert style.rotation == 90
    assert style.scale == 1.5
    assert style.locked is True


def test_place_auto_adds_part_if_missing() -> None:
    """place() auto-adds a part that has not yet been added."""
    sch = Schematic("test")
    part = Part(lib_id="Device:R", ref="R1")

    sch.place(part, x=12.0, y=34.0)

    assert part in sch.parts
    assert part in sch.sheets["main"].parts
    style = part.get_style()
    assert style.x == 12.0
    assert style.y == 34.0


def test_place_does_not_duplicate_existing_part() -> None:
    """place() should not append duplicate part entries."""
    sch = Schematic("test")
    part = Part(lib_id="Device:R", ref="R1")
    sch.add_part(part)

    sch.place(part, x=1.0, y=2.0)

    assert len([p for p in sch.parts if p is part]) == 1
# ---------------------------------------------------------------------------
# render tests
# ---------------------------------------------------------------------------

def test_render_dot_writes_file(tmp_path) -> None:
    """render(fmt=dot) must write a DOT file."""
    from lib.core.net import NetLabel
    from lib.core.connect import connect

    sch = Schematic("test")
    r1 = Part(lib_id="Device:R", ref="R1")
    sch.add_part(r1)
    vcc = NetLabel("VCC")
    sch.add_part(vcc)
    connect(vcc.label_pin, r1.pin(1))

    out = tmp_path / "out" / "graph.dot"
    sch.render(str(out), fmt="dot")

    assert out.exists()
    text = out.read_text()
    assert 'graph "test"' in text
    assert '"net:VCC"' in text


def test_export_dot_writes_file(tmp_path) -> None:
    """export_dot() must write a DOT file."""
    sch = Schematic("test")
    out = tmp_path / "output.dot"
    sch.export_dot(str(out))
    assert out.exists()


# ---------------------------------------------------------------------------
# property tests
# ---------------------------------------------------------------------------

def test_parts_property_returns_all_parts() -> None:
    """parts property must return all added parts."""
    sch = Schematic("test")
    r1 = Part(lib_id="Device:R", ref="R1")
    r2 = Part(lib_id="Device:R", ref="R2")
    sch.add_part(r1)
    sch.add_part(r2)
    
    parts = sch.parts
    assert len(parts) == 2
    assert r1 in parts
    assert r2 in parts


def test_sheets_property_returns_copy_with_main() -> None:
    """sheets property must return a copy with main sheet."""
    sch = Schematic("test")
    sch.add_sheet("page2")
    
    sheets = sch.sheets
    assert "main" in sheets
    assert "page2" in sheets
    
    # Verify it's a copy
    sheets["extra"] = Sheet(name="extra")
    assert "extra" not in sch.sheets
