# Unified Style Migration Guide

This project now uses a unified `Style` model for both placement and rendering.

## Precedence Rules

Effective style resolution is now:

1. `Style.default()`
2. `template.style`
3. `part.style`

In other words: `part.style > template.style > Style.default()`.

This resolution is implemented by `lib.core.style_resolver.resolve_style(...)` and is used by:

- schematic renderer
- symbol renderer setup
- missing-symbol placeholder renderer

## Field Mapping (Old -> New)

### Placement fields (unchanged)

| Old | New |
|---|---|
| `Style.x` | `Style.x` |
| `Style.y` | `Style.y` |
| `Style.anchor` | `Style.anchor` |
| `Style.rotation` | `Style.rotation` |
| `Style.locked` | `Style.locked` |
| `Style.z_index` | `Style.z_index` |

### RenderStyle to unified Style

All old `RenderStyle` fields are now fields on unified `Style` with the same names:

| Old `RenderStyle` | New `Style` |
|---|---|
| `wire` | `wire` |
| `label_net` | `label_net` |
| `halo` | `halo` |
| `box` | `box` |
| `pin` | `pin` |
| `symbol` | `symbol` |
| `ref_text` | `ref_text` |
| `value_text` | `value_text` |
| `canvas_scale_mode` | `canvas_scale_mode` |
| `canvas_scale` | `canvas_scale` |
| `canvas_scale_min` | `canvas_scale_min` |
| `canvas_scale_max` | `canvas_scale_max` |
| `canvas_target_min_font_px` | `canvas_target_min_font_px` |
| `background` | `background` |
| `ref_font_size` | `ref_font_size` |
| `value_font_size` | `value_font_size` |
| `net_font_size` | `net_font_size` |
| `pin_font_size` | `pin_font_size` |

### Pin visibility controls

`PinStyle` now includes:

- `pin_name_visible`
- `pin_value_visible`

These control whether pin names or pin numbers are rendered for symbols.

## Compatibility Boundary

- `RenderStyle` remains available for backward compatibility.
- `RenderTemplate.from_style(RenderStyle(...))` still works.
- Using the old `RenderStyle` path emits a `DeprecationWarning`.
- Internally, legacy `RenderStyle` objects are coerced to unified `Style`.

## Default and Merge Semantics

- `Style.default()` returns a fully resolved render style tree (no `None` render defaults).
- Merge semantics remain unchanged: `None` does not override.
- This applies to both scalar fields and nested style dataclasses.
