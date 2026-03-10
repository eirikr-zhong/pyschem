import pytest
from typing import Any

from lib.core.connect import connect, derive_nets
from lib.core.net import NetLabel
from lib.core.part import Part


class TestConnect:
    def test_two_pins_connect(self):
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        connect(r1.pin(1), r2.pin(2))
        assert r2.pin(2) in r1.pin(1).connected_pins

    def test_three_pins_connect(self):
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        r3 = Part("Device:R", ref="R3")
        connect(r1.pin(1), r2.pin(1), r3.pin(1))
        assert r2.pin(1) in r1.pin(1).connected_pins
        assert r3.pin(1) in r1.pin(1).connected_pins

    def test_too_few_pins_raises(self):
        r1 = Part("Device:R", ref="R1")
        with pytest.raises(ValueError):
            connect(r1.pin(1))

    def test_wrong_type_raises(self):
        r1 = Part("Device:R", ref="R1")
        with pytest.raises(TypeError):
            bad: list[Any] = [r1.pin(1), "not_a_pin"]
            connect(*bad)

    def test_non_pin_raises_type_error(self):
        from lib.core.net import Net

        r1 = Part("Device:R", ref="R1")
        n = Net("VCC")
        with pytest.raises(TypeError):
            bad: list[Any] = [r1.pin(1), n]
            connect(*bad)


class TestDeriveNets:
    def test_two_connected_pins_form_one_net(self):
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        connect(r1.pin(1), r2.pin(2))
        nets = derive_nets([r1, r2])
        connected_nets = [n for n in nets if n.pin_count >= 2]
        assert len(connected_nets) == 1
        assert connected_nets[0].name.startswith("_anon")

    def test_netlabel_gives_name(self):
        r1 = Part("Device:R", ref="R1")
        vcc = NetLabel("VCC")
        connect(r1.pin(1), vcc.label_pin)
        nets = derive_nets([r1, vcc])
        named = [n for n in nets if n.name == "VCC"]
        assert len(named) == 1
        assert named[0].pin_count == 1

    def test_netlabel_pin_excluded_from_result(self):
        r1 = Part("Device:R", ref="R1")
        vcc = NetLabel("VCC")
        connect(r1.pin(1), vcc.label_pin)
        nets = derive_nets([r1, vcc])
        vcc_net = next(n for n in nets if n.name == "VCC")
        for pin in vcc_net.pins:
            assert pin.part_ref != vcc.ref

    def test_isolated_pin_no_net(self):
        r1 = Part("Device:R", ref="R1")
        r1.pin(1)
        nets = derive_nets([r1])
        assert len(nets) == 0

    def test_multiple_netlabels_same_name_ok(self):
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        vcc1 = NetLabel("VCC")
        vcc2 = NetLabel("VCC")
        connect(r1.pin(1), vcc1.label_pin)
        connect(r2.pin(1), vcc2.label_pin)
        nets = derive_nets([r1, r2, vcc1, vcc2])
        vcc_nets = [n for n in nets if n.name == "VCC"]
        assert len(vcc_nets) == 2


class TestSchematicConnect:
    def test_sch_connect_creates_pin_edges(self):
        from lib.core.schematic import Schematic

        sch = Schematic("test")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.connect(r1.pin(1), r2.pin(2))
        assert r2.pin(2) in r1.pin(1).connected_pins

    def test_sch_nets_derived(self):
        from lib.core.schematic import Schematic

        sch = Schematic("test")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.connect(r1.pin(1), r2.pin(2))
        nets = sch.nets
        connected = [n for n in nets if n.pin_count >= 2]
        assert len(connected) >= 1

    def test_sch_dot_includes_anon_net(self, tmp_path):
        from lib.core.schematic import Schematic

        sch = Schematic("wire_test")
        r1 = Part("Device:R", ref="R1")
        r2 = Part("Device:R", ref="R2")
        sch.add_part(r1)
        sch.add_part(r2)
        sch.connect(r1.pin(1), r2.pin(2))
        dot_path = str(tmp_path / "wire_test.dot")
        sch.export_dot(dot_path)
        content = open(dot_path).read()
        assert "_anon" in content
