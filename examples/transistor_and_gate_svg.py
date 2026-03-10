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

from pathlib import Path

from pyschem import (
    BoxStyle,
    GroundNet,
    Junction,
    NetLabel,
    NetLabelStyle,
    Part,
    PinStyle,
    RenderTemplate,
    Style,
    Schematic,
    SymbolStyle,
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

r1 = Part("Device:R", ref="R1", value="10K")
r2 = Part("Device:R", ref="R2", value="10K")
r3 = Part("Device:R", ref="R3", value="10K")
r4 = Part("Device:R", ref="R4", value="10K")
r5 = Part("Device:R", ref="R5", value="10K")

# Named NetLabels for external signals.
nl_a = NetLabel("A", direction="left")
nl_b = NetLabel("B", direction="left")
nl_a_and_b = NetLabel("A_AND_B", direction="right")

# Duplicate VCC/GND label flags are intentional: they share same net name,
# but provide separate visual attachment points.
nl_vcc_q1 = NetLabel("VCC", direction="top")
nl_vcc_q2 = NetLabel("VCC", direction="top")
nl_gnd_left = GroundNet()
nl_gnd_right = GroundNet()

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

sch.place(r1, x=20, y=24.95)
sch.place(r2, x=20, y=75.05)
sch.place(q1, x=65, y=50)
sch.place(j_q1_bias, x=20, y=50)
sch.place(r3, x=70.07, y=82.67)
sch.place(r4, x=107.46, y=60.16, rotation=90)
sch.place(q2, x=155, y=60.16)
sch.place(r5, x=160.08, y=100)

# Label flags
sch.place(nl_a, x=5, y=17.33)
sch.place(nl_b, x=5, y=82.67)
sch.place(nl_vcc_q1, x=70.08, y=20)
sch.place(nl_vcc_q2, x=160.08, y=20)
sch.place(nl_a_and_b, x=185, y=80.32, style=Style(value_text=TextPlacementStyle(position="bottom", offset=8.0)))
sch.place(nl_gnd_left, x=70.07, y=110)
sch.place(nl_gnd_right, x=160.08, y=115)

# ---------------------------------------------------------------------------
# Wiring
#
# PySchem supports two equivalent connection styles:
#   - pin.connect(other)         — concise two-pin form
#   - connect(pin_a, pin_b, ...) — multi-pin form, useful for tee junctions
# ---------------------------------------------------------------------------
# A -> R1(2)
nl_a.label_pin.connect(r1.pin("2"))

# B -> R2(1)
nl_b.label_pin.connect(r2.pin("1"))

# Merge branch near Q1.B through an explicit tee junction.
connect(r1.pin("1"), r2.pin("2"), j_q1_bias.junction_pin)
j_q1_bias.junction_pin.connect(q1.pin("B"))

# VCC label flags -> transistor emitters
nl_vcc_q1.label_pin.connect(q1.pin("E"))
nl_vcc_q2.label_pin.connect(q2.pin("E"))

# Q1(C) -> R3(2), and R3(1) -> GND
q1.pin("C").connect(r3.pin("2"))
r3.pin("1").connect(nl_gnd_left.label_pin)

# Q1(C) -> R4(2), and R4(1) -> Q2(B)
q1.pin("C").connect(r4.pin("2"))
r4.pin("1").connect(q2.pin("B"))

# Q2(C) -> output label and pull-down branch
q2.pin("C").connect(nl_a_and_b.label_pin)
q2.pin("C").connect(r5.pin("2"))
r5.pin("1").connect(nl_gnd_right.label_pin)

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

svg_path = Path(__file__).resolve().parent / "out" / "transistor_and_gate.svg"
svg_path.parent.mkdir(parents=True, exist_ok=True)
wire_color = "#1565c0"
render_template = RenderTemplate.from_style(
    Style(
        wire=WireStyle(color=wire_color),
        label_net=NetLabelStyle(color=wire_color),
        box=BoxStyle(stroke="#d32f2f"),
        pin=PinStyle(stub_stroke="#d32f2f", key_fill="#000000", value_fill="#000000", font_value=8.0, pin_name_visible=False, pin_value_visible=False),
        value_text=TextPlacementStyle(position="center"),
        value_font_size=8.0,
    ),
)
sch.export_svg(str(svg_path), template=render_template, fit_to_content=True)

print(svg_path)
