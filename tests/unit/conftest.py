"""Unit test fixtures for pyschem library."""

import pytest

from pyschem import NetLabel, Part, Pin, Schematic, Sheet, Style
from lib.symbols.data import PinDefinition, SymbolData


# ── Basic object fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def bare_part() -> Part:
    """Minimal Part with no pins — used for instantiation assertions."""
    return Part("Device:R", ref="R1", value="10k")


@pytest.fixture
def simple_part() -> Part:
    """Part with two pins — covers pin access tests."""
    p = Part("Device:R", ref="R1", value="10k")
    # Accessing pins triggers lazy creation
    p.pin("1")
    p.pin("2")
    return p


@pytest.fixture
def styled_part(simple_part: Part) -> Part:
    """Part with an explicit Style set."""
    simple_part.set_style(
        Style(
            x=40.0,
            y=30.0,
            rotation=0,
            anchor="center",
            locked=True,
        )
    )
    return simple_part


@pytest.fixture
def two_device_schematic() -> Schematic:
    """Voltage divider: R1, R2, three nets — used for render/regression tests."""
    sch = Schematic("divider")
    r1 = Part("Device:R", ref="R1", value="10k")
    r2 = Part("Device:R", ref="R2", value="5k")
    sch.add_part(r1)
    sch.add_part(r2)

    vin = NetLabel("VIN")
    vout = NetLabel("VOUT")
    gnd = NetLabel("GND")
    for nl in [vin, vout, gnd]:
        sch.add_part(nl)

    sch.connect(vin.label_pin, r1.pin("1"))
    sch.connect(r1.pin("2"), r2.pin("1"), vout.label_pin)
    sch.connect(gnd.label_pin, r2.pin("2"))

    r1.set_style(Style(x=40.0, y=30.0, locked=True))
    r2.set_style(Style(x=70.0, y=30.0, rotation=90, locked=True))
    return sch


# ── Path fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def temp_output_dir(tmp_path):
    """Temporary output directory — auto-cleaned after test."""
    out = tmp_path / "output"
    # Intentionally not mkdir'd — verifies that export creates the directory
    return out


@pytest.fixture
def mock_symbol_dir(tmp_path):
    """Minimal fake symbol directory for symbols unit tests (no real KiCad libs needed)."""
    lib_dir = tmp_path / "kicad_sym"
    lib_dir.mkdir()
    # Write minimal legal .kicad_sym content
    content = '''(kicad_symbol_lib
\t(version 20211014)
\t(generator "pyschem_test")
\t(symbol "R"
\t\t(pin_names (offset 0))
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "R"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Value" "R"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Footprint" "Device_R_SMD"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Description" "Resistor"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(symbol "R_0_1"
\t\t\t(rectangle (at -1.27 -2.54) (extent 2.54 5.08)
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type background))))
\t\t(symbol "R_1_1"
\t\t\t(pin passive line (at -2.54 0 180) (length 2.54)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t\t(pin passive line (at 2.54 0 0) (length 2.54)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))))
\t)
)'''
    (lib_dir / "Device.kicad_sym").write_text(content)
    return str(lib_dir)


# ── Layout fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def bjt_symbol_data() -> SymbolData:
    """Fake NPN BJT SymbolData with B/C/E named pins (numbered 1/2/3)."""
    return SymbolData(
        name="Q_NPN_BCE",
        lib="Device",
        pins=[
            PinDefinition(number="1", name="B", type="input", x=0, y=0),
            PinDefinition(number="2", name="C", type="passive", x=0, y=2.54),
            PinDefinition(number="3", name="E", type="passive", x=0, y=-2.54),
        ],
    )


@pytest.fixture
def bjt_part(bjt_symbol_data: SymbolData) -> Part:
    """Part with BJT SymbolData attached — supports pin('B')/'C'/'E' access."""
    part = Part("Device:Q_NPN_BCE", ref="Q1")
    part.attach_symbol(bjt_symbol_data)
    return part


@pytest.fixture
def locked_part() -> Part:
    """Part with a locked position."""
    p = Part("Device:R", ref="U1")
    p.set_style(Style(x=0.0, y=0.0, locked=True))
    return p


@pytest.fixture
def unlocked_part() -> Part:
    """Part with no Style set — layout engine should inject defaults."""
    p = Part("Device:R", ref="U2")
    return p


@pytest.fixture
def overlapping_locked_parts() -> list:
    """Two parts locked at the same coordinates — triggers LayoutConstraintError."""
    a = Part("Device:R", ref="P1")
    a.set_style(Style(x=10.0, y=10.0, locked=True))
    b = Part("Device:C", ref="P2")
    b.set_style(Style(x=10.0, y=10.0, locked=True))
    return [a, b]
