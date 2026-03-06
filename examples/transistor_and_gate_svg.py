"""transistor_and_gate_svg.py — Transistor AND-gate schematic exported as SVG.

This example builds a two-transistor AND gate (resistor-transistor logic)
and exports it as an SVG file using an A1 landscape canvas.

Symbols are resolved from local KiCad libraries in `examples/kicad-symbols/`.

Layout (explicit Style positions for a clean, readable schematic):

  Input A ──R1──┐
                ├── Q1 (PNP) ──R3──┐
  Input B ──R2──┘   │              ├── Q2 (PNP) ── A_AND_B
                    R4──GND        └──R5──GND

Output: out/transistor_and_gate.svg
"""

from __future__ import annotations

import re
from pathlib import Path

from pyschem import (
    BoxStyle,
    Junction,
    NetLabel,
    NetLabelStyle,
    PageConfig,
    Part,
    PinStyle,
    RenderTemplate,
    Style,
    Schematic,
    TextPlacementStyle,
    WireStyle,
    configure_default_symbols,
    connect,
)

# ---------------------------------------------------------------------------
# Build schematic
# ---------------------------------------------------------------------------

symbol_dir = Path(__file__).resolve().parent / "kicad-symbols"
configure_default_symbols(symbol_paths=[str(symbol_dir)], preload=True)

sch = Schematic("transistor_and_gate")

# Parts
q1 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q1")
q2 = Part("Transistor_BJT:Q_PNP_CBE", ref="Q2")
j_q1_bias = Junction(ref="J_Q1_BIAS")
j_vcc_q1 = Junction(ref="J_VCC_Q1")
j_vcc_q2 = Junction(ref="J_VCC_Q2")
j_a_and_b = Junction(ref="J_A_AND_B")
j_gnd_left = Junction(ref="J_GND_LEFT")
j_gnd_right = Junction(ref="J_GND_RIGHT")

r1 = Part("Device:R", ref="R1", value="10K")
r2 = Part("Device:R", ref="R2", value="10K")
r3 = Part("Device:R", ref="R3", value="10K")
r4 = Part("Device:R", ref="R4", value="10K")
r5 = Part("Device:R", ref="R5", value="10K")

# Named NetLabels for external signals.
nl_a = NetLabel("A", direction="right")
nl_b = NetLabel("B", direction="right")
nl_a_and_b = NetLabel("A_AND_B", direction="right")

# Duplicate VCC/GND label flags are intentional: they share same net name,
# but provide separate visual attachment points.
nl_vcc_q1 = NetLabel("VCC", direction="top")
nl_vcc_q2 = NetLabel("VCC", direction="top")
nl_gnd_left = NetLabel("GND", direction="bottom")
nl_gnd_right = NetLabel("GND", direction="bottom")

# ---------------------------------------------------------------------------
# Explicit layout positions (x, y in schematic units → scaled × 3 in SVG)
# Arranged in a left-to-right RTL AND-gate topology:
#
#   Col 1 (x=20): R1 (top), R2 (bottom) — input resistors
#   Col 2 (x=60): Q1 — first PNP stage + R4 (bias to GND)
#   Col 3 (x=120): R3 (inter-stage)
#   Col 4 (x=130): Q2 — output PNP stage
#   Col 5 (x=160): R5 (output pull-down)
# ---------------------------------------------------------------------------

sch.place(r1, x=20, y=25)
sch.place(r2, x=20, y=75)
sch.place(q1, x=65, y=50)
sch.place(j_q1_bias, x=20, y=50)  # ← x=20 对齐 R1/R2
sch.place(r3, x=65, y=75)  # R3 X 与 Q1(C) 对齐，在 Q1 下方
sch.place(r4, x=125, y=50)  # R4(2) 与 Q1(C) 水平对齐，X 不遮挡 Q1
sch.place(q2, x=175, y=50, rotation=0)  # Q2 跟着右移，保持水平
sch.place(r5, x=205, y=100)

# Label flags
sch.place(nl_a, x=5, y=25)
sch.place(nl_b, x=5, y=75)
sch.place(nl_vcc_q1, x=65, y=20)
sch.place(nl_vcc_q2, x=155, y=20)
sch.place(nl_a_and_b, x=185, y=50)
sch.place(nl_gnd_left, x=90, y=110)
sch.place(nl_gnd_right, x=175, y=115)

# Place explicit junction anchors at NetLabel pin endpoints so
# rendered wires visibly terminate at each label.
sch.place(j_vcc_q1, x=65, y=25.08)
sch.place(j_vcc_q2, x=155, y=25.08)
sch.place(j_a_and_b, x=179.92, y=50)
sch.place(j_gnd_left, x=90, y=104.92)
sch.place(j_gnd_right, x=175, y=109.92)

# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
# A -> R1(2)
connect(nl_a.label_pin, r1.pin("2"))

# B -> R2(1)
connect(nl_b.label_pin, r2.pin("1"))

# Merge branch near Q1.B through an explicit tee junction.
connect(r1.pin("1"), j_q1_bias.junction_pin)
connect(r2.pin("2"), j_q1_bias.junction_pin)
connect(j_q1_bias.junction_pin, q1.pin("B"))

# VCC label flags -> transistor emitters
connect(nl_vcc_q1.label_pin, j_vcc_q1.junction_pin)
connect(j_vcc_q1.junction_pin, q1.pin("E"))
connect(nl_vcc_q2.label_pin, j_vcc_q2.junction_pin)
connect(j_vcc_q2.junction_pin, q2.pin("E"))

# Q1(C) -> R3(2), and R3(1) -> GND
connect(q1.pin("C"), r3.pin("2"))
connect(r3.pin("1"), j_gnd_left.junction_pin)
connect(j_gnd_left.junction_pin, nl_gnd_left.label_pin)

# Q1(C) -> R4(2), and R4(1) -> Q2(B)
connect(q1.pin("C"), r4.pin("2"))
connect(r4.pin("1"), q2.pin("B"))

# Q2(C) -> output label and pull-down branch
connect(q2.pin("C"), j_a_and_b.junction_pin)
connect(j_a_and_b.junction_pin, nl_a_and_b.label_pin)
connect(q2.pin("C"), r5.pin("2"))
connect(r5.pin("1"), j_gnd_right.junction_pin)
connect(j_gnd_right.junction_pin, nl_gnd_right.label_pin)

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

svg_path = "out/transistor_and_gate.svg"
wire_color = "#1565c0"
page = PageConfig.a1(landscape=True)
render_template = RenderTemplate.from_style(
    Style(
        wire=WireStyle(color=wire_color),
        label_net=NetLabelStyle(color=wire_color),
        box=BoxStyle(stroke="#d32f2f"),
        pin=PinStyle(stub_stroke="#d32f2f", key_fill="#000000", value_fill="#000000", font_value=8.0),
        value_text=TextPlacementStyle(position="center"),
        value_font_size=8.0,
    ),
    page=page,
)
sch.export_svg(svg_path, template=render_template)

# Dynamic output size: rewrite <svg width/height> from fitted viewBox (tight canvas)
svg_file = Path(svg_path)
content = svg_file.read_text(encoding="utf-8")
m = re.search(r'viewBox="([^"]+)"', content)
size = re.search(r'<svg[^>]*width="([^"]+)"[^>]*height="([^"]+)"', content)
if m and size:
    _, _, vb_w, vb_h = [float(x) for x in m.group(1).split()]
    output_scale = max(float(size.group(1)) / page.width, float(size.group(2)) / page.height)
    content = re.sub(r'width="[^"]+"', f'width="{vb_w * output_scale:.1f}"', content, count=1)
    content = re.sub(r'height="[^"]+"', f'height="{vb_h * output_scale:.1f}"', content, count=1)
    svg_file.write_text(content, encoding="utf-8")

print(svg_path)
