import pytest

from lib.core.net import Net
from lib.core.part import Part


def test_net_name_stored():
    net = Net("MY_NET")
    assert net.name == "MY_NET"


def test_net_pins_empty_on_creation():
    net = Net("VIN")
    assert net.pins == []
    assert net.pin_count == 0


def test_net_pins_property_returns_copy():
    r1 = Part("Device:R", ref="R1")
    net = Net("VIN", _pins=[r1.pin("1")])
    pins_copy = net.pins
    pins_copy.clear()
    assert net.pin_count == 1


def test_net_pin_count_reflects_init_pins():
    r1 = Part("Device:R", ref="R1")
    net = Net("VOUT", _pins=[r1.pin("1"), r1.pin("2")])
    assert net.pin_count == 2
