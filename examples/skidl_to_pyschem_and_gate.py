import os
from pyschem import Schematic, Part, NetLabel, connect, configure_default_symbols

# Configure global symbols singleton once (hidden lookup behavior)
_SYM_DIR = os.path.join(os.path.dirname(__file__), "kicad-symbols")
configure_default_symbols(symbol_paths=[os.path.join(_SYM_DIR, "Transistor_BJT.kicad_sym")])

sch = Schematic("transistor_and_gate")

# Parts
q1 = Part("Device:Q_PNP_CBE", ref="Q1")
q2 = Part("Device:Q_PNP_CBE", ref="Q2")

r1 = Part("Device:R", ref="R1", value="10K")
r2 = Part("Device:R", ref="R2", value="10K")
r3 = Part("Device:R", ref="R3", value="10K")
r4 = Part("Device:R", ref="R4", value="10K")
r5 = Part("Device:R", ref="R5", value="10K")

for p in [q1, q2, r1, r2, r3, r4, r5]:
    sch.add_part(p)

# Named net labels
nl_gnd1 = NetLabel("GND")
nl_gnd2 = NetLabel("GND")
nl_vcc1 = NetLabel("VCC")
nl_vcc2 = NetLabel("VCC")
nl_a = NetLabel("A")
nl_b = NetLabel("B")
nl_a_and_b = NetLabel("A_AND_B")

for nl in [nl_gnd1, nl_gnd2, nl_vcc1, nl_vcc2, nl_a, nl_b, nl_a_and_b]:
    sch.add_part(nl)

# Wiring (R uses numeric pins; PNP uses B/C/E)
connect(nl_a.label_pin, r1.pin(1))
connect(nl_b.label_pin, r2.pin(1))

# Q1 stage shared node
connect(r1.pin(2), r2.pin(2), r3.pin(1), q1.pin("B"), q1.pin("C"), r4.pin(1))

# Output stage shared node
connect(r4.pin(2), q2.pin("B"), q2.pin("C"), r5.pin(1))
connect(nl_a_and_b.label_pin, r4.pin(2))

# Power rails
connect(nl_vcc1.label_pin, q1.pin("E"))
connect(nl_vcc2.label_pin, q2.pin("E"))
connect(nl_gnd1.label_pin, r3.pin(2))
connect(nl_gnd2.label_pin, r5.pin(2))

out_path = os.path.join(os.path.dirname(__file__), "..", "out", "transistor_and_gate.dot")
sch.export_dot(out_path)
print(out_path)
