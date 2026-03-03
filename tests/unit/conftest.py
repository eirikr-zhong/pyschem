"""Unit test fixtures for pyschem library."""

import pytest

from pyschem import NetLabel, Part, Pin, Schematic, Sheet, Style
from lib.symbols.data import PinDefinition, SymbolData


# ── 基础对象 fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def bare_part() -> Part:
    """最简 Part，无引脚，用于实例化断言。"""
    return Part("Device:R", ref="R1", value="10k")


@pytest.fixture
def simple_part() -> Part:
    """带两个引脚的 Part，覆盖 pin 访问测试。"""
    p = Part("Device:R", ref="R1", value="10k")
    # 访问引脚会惰性创建
    p.pin("1")
    p.pin("2")
    return p


@pytest.fixture
def styled_part(simple_part: Part) -> Part:
    """已设置定位 Style 的 Part。"""
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
    """分压器场景：R1、R2，三条网络，用于渲染/回归测试。"""
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


# ── 路径 fixture ─────────────────────────────────────────────────────────────

@pytest.fixture
def temp_output_dir(tmp_path):
    """临时输出目录，测试结束自动清理。"""
    out = tmp_path / "output"
    # 故意不 mkdir，验证 export 自动创建目录
    return out


@pytest.fixture
def mock_symbol_dir(tmp_path):
    """构造最小虚拟符号目录，用于 symbols 单元测试（不依赖真实 KiCad 库）。"""
    lib_dir = tmp_path / "kicad_sym"
    lib_dir.mkdir()
    # Write minimal legal .kicad_sym content
    content = '''(kicad_symbol_lib
	(version 20211014)
	(generator "pyschem_test")
	(symbol "R"
		(pin_names (offset 0))
		(in_bom yes)
		(on_board yes)
		(property "Reference" "R"
			(at 0 0 0)
			(effects (font (size 1.27 1.27))))
		(property "Value" "R"
			(at 0 0 0)
			(effects (font (size 1.27 1.27))))
		(property "Footprint" "Device_R_SMD"
			(at 0 0 0)
			(effects (font (size 1.27 1.27)) (hide yes)))
		(property "Description" "Resistor"
			(at 0 0 0)
			(effects (font (size 1.27 1.27)) (hide yes)))
		(symbol "R_0_1"
			(rectangle (at -1.27 -2.54) (extent 2.54 5.08)
				(stroke (width 0.254) (type default))
				(fill (type background))))
		(symbol "R_1_1"
			(pin passive line (at -2.54 0 180) (length 2.54)
				(name "~" (effects (font (size 1.27 1.27))))
				(number "1" (effects (font (size 1.27 1.27)))))
			(pin passive line (at 2.54 0 0) (length 2.54)
				(name "~" (effects (font (size 1.27 1.27))))
				(number "2" (effects (font (size 1.27 1.27))))))
	)
)'''
    (lib_dir / "Device.kicad_sym").write_text(content)
    return str(lib_dir)


# ── 布局 fixture ─────────────────────────────────────────────────────────────

@pytest.fixture
def bjt_symbol_data() -> SymbolData:
    """虚拟 NPN BJT SymbolData，包含 B/C/E 命名引脚（编号 1/2/3）。"""
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
    """绑定了 BJT SymbolData 的 Part，可用 pin('B')/'C'/'E' 引用引脚。"""
    part = Part("Device:Q_NPN_BCE", ref="Q1")
    part.attach_symbol(bjt_symbol_data)
    return part


@pytest.fixture
def locked_part() -> Part:
    """已锁定位置的器件。"""
    p = Part("Device:R", ref="U1")
    p.set_style(Style(x=0.0, y=0.0, locked=True))
    return p


@pytest.fixture
def unlocked_part() -> Part:
    """未锁定位置的器件，布局器应自动注入默认值。"""
    p = Part("Device:R", ref="U2")
    # 不设置 Style
    return p


@pytest.fixture
def overlapping_locked_parts() -> list:
    """两个固定在同一坐标的器件，触发 LayoutConstraintError。"""
    a = Part("Device:R", ref="P1")
    a.set_style(Style(x=10.0, y=10.0, locked=True))
    b = Part("Device:C", ref="P2")
    b.set_style(Style(x=10.0, y=10.0, locked=True))
    return [a, b]
