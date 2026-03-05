# PySchem API Notes: Junction + Placement Auto-Add

## `Junction` (new)

`Junction` is a single-pin schematic element used as a pure topology/graphics tee point.

- It has one connectable pin: `junction_pin`.
- It does **not** carry a net name (use `NetLabel` for naming nets).
- It does **not** have a `name` attribute.
- You may optionally pass `ref` for debugging/telemetry visibility.

```python
from pyschem import Junction

j = Junction(ref="J_BIAS")  # ref is optional
```

## `Schematic.place()` simplified flow

`Schematic.add_part()` is still available and supported.

In addition, `Schematic.place(part, x=..., y=...)` now auto-adds `part` to the schematic if it is not already present.  
This enables a simpler build pattern where explicit `add_part()` calls are optional.

```python
from pyschem import Schematic, Part, Junction, connect

sch = Schematic("demo")
r1 = Part("Device:R", ref="R1")
r2 = Part("Device:R", ref="R2")
j = Junction()

sch.place(r1, x=20, y=20)   # auto-adds R1
sch.place(r2, x=20, y=60)   # auto-adds R2
sch.place(j, x=45, y=40)    # auto-adds Junction

connect(r1.pin("1"), r2.pin("2"), j.junction_pin)
```

## Tee-point wiring pattern (Q1.B branch)

Use `Junction` instead of a net-label workaround when you need a visible tee node:

1. Connect branch sources to the junction.
2. Connect junction to the destination pin.

```python
connect(r1.pin("1"), r2.pin("2"), j_q1_bias.junction_pin)
connect(j_q1_bias.junction_pin, q1.pin("B"))
```
