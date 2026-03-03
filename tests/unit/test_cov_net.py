from lib.core.net import Net
from lib.core.part import Part


class TestReadOnlyNet:
    def test_net_creation_with_pins(self):
        r1 = Part("Device:R", ref="R1")
        net = Net("VCC", _pins=[r1.pin("1")])
        assert net.pin_count == 1

    def test_net_pins_returns_copy(self):
        r1 = Part("Device:R", ref="R1")
        net = Net("GND", _pins=[r1.pin("1")])
        copy = net.pins
        copy.clear()
        assert net.pin_count == 1

    def test_net_name(self):
        net = Net("DATA")
        assert net.name == "DATA"
