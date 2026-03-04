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
    NetLabel,
    NetLabelStyle,
    PageConfig,
    Part,
    RenderStyle,
    RenderTemplate,
    Schematic,
    SymbolStyle,
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

r1 = Part("Device:R", ref="R1", value="10K")
r2 = Part("Device:R", ref="R2", value="10K")
r3 = Part("Device:R", ref="R3", value="10K")
r4 = Part("Device:R", ref="R4", value="10K")
r5 = Part("Device:R", ref="R5", value="10K")

for p in [q1, q2, r1, r2, r3, r4, r5]:
    sch.add_part(p)

# Named NetLabels for external signals (reset to the requested 5 labels).
nl_a = NetLabel("A", direction="right")
nl_b = NetLabel("B", direction="right")
nl_vcc = NetLabel("VCC", direction="top")
nl_gnd = NetLabel("GND", direction="bottom")
nl_a_and_b = NetLabel("A_AND_B", direction="right")

for nl in [nl_a, nl_b, nl_vcc, nl_gnd, nl_a_and_b]:
    sch.add_part(nl)

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
sch.place(q1, x=65, y=50, rotation=90)
sch.place(r3, x=120, y=50)
sch.place(r4, x=65, y=110)
sch.place(q2, x=155, y=50)
sch.place(r5, x=155, y=110)

# ---------------------------------------------------------------------------
# Wiring (R uses numeric pins; PNP uses B/C/E)
# ---------------------------------------------------------------------------

# Inputs
connect(nl_a.label_pin, r1.pin("1"))
connect(nl_b.label_pin, r2.pin("1"))

# First-stage drive
connect(r1.pin("2"), q1.pin("B"))
connect(r2.pin("2"), q1.pin("B"))
connect(nl_vcc.label_pin, q1.pin("E"))
connect(q1.pin("B"), r4.pin("1"))
connect(r4.pin("2"), nl_gnd.label_pin)

# Inter-stage and output stage
connect(q1.pin("C"), r3.pin("1"))
connect(r3.pin("2"), q2.pin("B"))
connect(q2.pin("B"), r5.pin("1"))
connect(r5.pin("2"), nl_gnd.label_pin)
connect(nl_vcc.label_pin, q2.pin("E"))
connect(q2.pin("C"), nl_a_and_b.label_pin)

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

svg_path = "out/transistor_and_gate.svg"
wire_color = "#1565c0"
page = PageConfig.a1(landscape=True)
render_template = RenderTemplate.from_style(
    RenderStyle(
        wire=WireStyle(color=wire_color),
        label_net=NetLabelStyle(color=wire_color),
        symbol=SymbolStyle(scale=6.0),
        canvas_scale_mode="auto",
        canvas_scale_min=1.0,
        canvas_scale_max=6.0,
        canvas_target_min_font_px=12.0,
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
