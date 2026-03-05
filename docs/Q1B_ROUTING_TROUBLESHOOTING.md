# Q1.B Branch Routing Troubleshooting

## Observed phenomenon

- In the example schematic, wiring from `R1(1)` and `R2(2)` into `Q1(B)` is electrically correct but looks visually looped/dog-legged near `Q1(B)`.
- The rendered path appears to backtrack around the transistor body before terminating at the base pin, which looks like an unnecessary loop even though continuity is valid.

## Reproduction context (script, coordinates, visual behavior)

- Script: `examples/transistor_and_gate_svg.py`
- Relevant placement (schematic units):
  - `R1 @ (20, 25)`
  - `R2 @ (20, 75)`
  - `Q1 @ (65, 50)`
- Current reverted wiring state (intended baseline):

```python
connect(r1.pin("1"), r2.pin("2"))
connect(r2.pin("2"), q1.pin("B"))
```

- Reproduce:

```bash
python3 examples/transistor_and_gate_svg.py
```

- Inspect output: `out/transistor_and_gate.svg`
- Typical visual symptom in generated SVG around Q1 base:
  - A vertical trunk near `x=192.52`
  - A detour near `Q1(B)` around `x=204.52`
  - Horizontal stubs from `R1(1)` and `R2(2)` at different `y` levels, creating a loop-like rectangle

## Attempted changes and rollback history

1. **Baseline branch wiring**: direct two-step branch into `Q1(B)` (shown above).
2. **Experiment (rejected)**: introduced an explicit merge node/net marker named `Q1_BIAS` to force a cleaner tee-point before entering `Q1(B)`.
3. **Result**: electrical behavior remained correct, but visual behavior was not consistently improved and the schematic intent became noisier.
4. **Decision**: rejected `Q1_BIAS` merge-node approach and reverted.
5. **Current state**: back to the baseline two-line wiring:

```python
connect(r1.pin("1"), r2.pin("2"))
connect(r2.pin("2"), q1.pin("B"))
```

## Root-cause hypotheses

1. **Three-pin net trunking behavior**: the merged net (`R1(1)`, `R2(2)`, `Q1(B)`) is routed as a trunk + stubs topology, not as a user-directed tee at `Q1(B)`.
2. **Obstacle clearance detour**: obstacle-aware routing (with `_OBSTACLE_CLEARANCE = 6`) detours around `Q1` body bounds, producing a visually looped approach to the base pin.
3. **No branch-anchor hint**: current API expresses connectivity only; it does not encode a preferred visual merge/entry point for branch routing.
4. **Topological vs visual mismatch**: net topology is valid, but the geometric path selection heuristic is not optimized for readability in this placement.

## Investigation plan (step-by-step, measurable checks)

1. **Freeze baseline artifact**
   - Run `python3 examples/transistor_and_gate_svg.py`.
   - Save `out/transistor_and_gate.svg` as baseline output for comparison.
2. **Measure problematic geometry**
   - Confirm the Q1-base route includes a detour/trunk pattern (loop-like rectangle) via SVG line coordinates.
   - Record segment count in this local branch path (target metric for simplification).
3. **Instrument trunk decision for this net**
   - Add temporary debug logging for `_draw_wire_net` / `_choose_trunk_x` inputs and chosen `trunk_x` for the affected net.
   - Verify whether obstacle hits force detours near `Q1(B)`.
4. **A/B route strategy prototypes**
   - Compare current trunk strategy vs a pin-anchored strategy (favor branch merge near destination pin for 3-pin nets).
   - Measure bend count and visual crossings for the same endpoint set.
5. **Regression safety checks**
   - Validate electrical continuity remains unchanged for `R1(1)`, `R2(2)`, `Q1(B)`.
   - Ensure no new wire/component overlaps are introduced.

## Recommended implementation path

1. Keep the connectivity API unchanged (`connect(...)`) and avoid synthetic schematic nodes like `Q1_BIAS`.
2. Add a routing heuristic for small branch nets (especially 3-pin nets) that can prefer a destination-adjacent merge when one endpoint is obstacle-constrained.
3. Keep obstacle avoidance enabled, but bias detour selection toward minimal perceived looping (fewest bends and no backtrack box near pin endpoint).
4. Add a focused renderer regression test using this exact geometry to prevent reintroduction.

## Expected final effect (visual + electrical)

- **Visual**: branch into `Q1(B)` appears as a clean Manhattan tee/branch without loop-like backtracking.
- **Electrical**: unchanged continuity and net membership for `R1(1)`, `R2(2)`, and `Q1(B)`.
- **Maintainability**: no extra merge-label artifacts (`Q1_BIAS`) needed in the example netlist.

## Acceptance criteria

- Running `python3 examples/transistor_and_gate_svg.py` succeeds and produces `out/transistor_and_gate.svg`.
- The rendered path near `Q1(B)` has no obvious loop-like rectangle/backtrack.
- The net remains electrically continuous across `R1(1)`, `R2(2)`, `Q1(B)`.
- No explicit merge-node workaround (`Q1_BIAS`) is present in example wiring.
- A regression check exists (or is planned) for this geometry-specific readability case.
