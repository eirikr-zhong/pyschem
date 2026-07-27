"""Tests for grouped CSV bill-of-materials export."""

import csv

import pytest

from lib.core.junction import Junction
from lib.core.net import GroundNet, NetLabel
from lib.core.part import Part
from lib.core.schematic import Schematic
from lib.errors import RenderPathError


def _read_bom(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_bom_groups_matching_parts_and_naturally_sorts_references(tmp_path) -> None:
    sch = Schematic("bom")
    for ref in ("R10", "R2", "R1"):
        sch.add_part(
            Part(
                "Device:R",
                ref=ref,
                value="10k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                bom_fields={"Manufacturer": "Yageo", "MPN": "RC0603FR-0710KL"},
            )
        )

    output = tmp_path / "out" / "bom.csv"
    sch.export_bom(str(output))

    assert output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert _read_bom(output) == [
        {
            "References": "R1,R2,R10",
            "Quantity": "3",
            "Value": "10k",
            "Footprint": "Resistor_SMD:R_0603_1608Metric",
            "Lib ID": "Device:R",
            "MPN": "RC0603FR-0710KL",
            "Manufacturer": "Yageo",
        }
    ]


def test_export_bom_keeps_different_purchasing_data_in_separate_rows(tmp_path) -> None:
    sch = Schematic("bom_variants")
    sch.add_part(Part("Device:R", ref="R1", value="10k", footprint="R_0603"))
    sch.add_part(Part("Device:R", ref="R2", value="10k", footprint="R_0402"))
    sch.add_part(
        Part("Device:R", ref="R3", value="10k", footprint="R_0603", bom_fields={"MPN": "A"})
    )
    sch.add_part(
        Part("Device:R", ref="R4", value="10k", footprint="R_0603", bom_fields={"MPN": "B"})
    )

    output = tmp_path / "bom.csv"
    sch.export_bom(str(output))

    assert _read_bom(output) == [
        {
            "References": "R1",
            "Quantity": "1",
            "Value": "10k",
            "Footprint": "R_0603",
            "Lib ID": "Device:R",
            "MPN": "",
        },
        {
            "References": "R2",
            "Quantity": "1",
            "Value": "10k",
            "Footprint": "R_0402",
            "Lib ID": "Device:R",
            "MPN": "",
        },
        {
            "References": "R3",
            "Quantity": "1",
            "Value": "10k",
            "Footprint": "R_0603",
            "Lib ID": "Device:R",
            "MPN": "A",
        },
        {
            "References": "R4",
            "Quantity": "1",
            "Value": "10k",
            "Footprint": "R_0603",
            "Lib ID": "Device:R",
            "MPN": "B",
        },
    ]


def test_export_bom_treats_missing_and_empty_custom_fields_as_the_same_value(tmp_path) -> None:
    sch = Schematic("bom_empty_fields")
    sch.add_part(Part("Device:R", ref="R1", value="10k", footprint="R_0603"))
    sch.add_part(
        Part("Device:R", ref="R2", value="10k", footprint="R_0603", bom_fields={"MPN": ""})
    )

    output = tmp_path / "bom.csv"
    sch.export_bom(str(output))

    assert _read_bom(output) == [
        {
            "References": "R1,R2",
            "Quantity": "2",
            "Value": "10k",
            "Footprint": "R_0603",
            "Lib ID": "Device:R",
            "MPN": "",
        }
    ]


def test_export_bom_excludes_annotations_but_keeps_blank_footprint_parts(tmp_path) -> None:
    sch = Schematic("bom_annotations")
    sch.add_part(Part("Device:U", ref="U1", value="Controller"))
    sch.add_part(NetLabel("VCC"))
    sch.add_part(GroundNet())
    sch.add_part(Junction(ref="J1"))
    sch.add_part(Part("Annotation:NoConnect", ref="#NC1"))

    output = tmp_path / "bom.csv"
    sch.export_bom(str(output))

    assert _read_bom(output) == [
        {
            "References": "U1",
            "Quantity": "1",
            "Value": "Controller",
            "Footprint": "",
            "Lib ID": "Device:U",
        }
    ]


def test_export_bom_uses_csv_escaping_for_custom_fields(tmp_path) -> None:
    sch = Schematic("bom_csv")
    sch.add_part(
        Part(
            "Device:R",
            ref="R1",
            value='10k, 1% "precision"',
            footprint="R_0603",
            bom_fields={"Note": "line one\nline two"},
        )
    )

    output = tmp_path / "bom.csv"
    sch.export_bom(str(output))

    assert _read_bom(output)[0]["Value"] == '10k, 1% "precision"'
    assert _read_bom(output)[0]["Note"] == "line one\nline two"


def test_export_bom_bad_path_raises_render_path_error(tmp_path) -> None:
    sch = Schematic("bom_error")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    with pytest.raises(RenderPathError):
        sch.export_bom(str(blocker / "subdir" / "bom.csv"))
