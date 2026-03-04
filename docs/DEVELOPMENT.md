# PySchem Developer Guide

## Table of Contents

1. [Project Structure](#project-structure)
2. [Naming Conventions](#naming-conventions)
3. [Code Style](#code-style)
4. [Commit Conventions](#commit-conventions)
5. [Testing](#testing)
6. [Branch Strategy](#branch-strategy)

---

## Project Structure

```
PySchem/
├── lib/                  # Core library (importable as `lib.*`)
│   ├── core/             # Schematic model: Part, Net, connect, Schematic
│   ├── render/           # SVG/DOT rendering backends
│   ├── symbols/          # KiCad symbol parser and lookup
│   ├── errors/           # Custom exceptions
│   └── utils/            # Internal utilities
├── pyschem/              # Public package entry point (`import pyschem`)
├── examples/             # Runnable usage examples
│   └── kicad-symbols/    # Vendored KiCad symbol files for examples
├── tests/
│   ├── unit/             # Unit tests (no external dependencies)
│   └── fixtures/         # Static test data (KiCad files, etc.)
├── tools/                # Developer CLI tools (not part of public API)
├── docs/                 # Developer and user documentation
└── out/                  # Generated output files (gitignored)
```

---

## Naming Conventions

### Python

| Context | Convention | Example |
|---|---|---|
| Modules | `snake_case` | `symbol_parser.py` |
| Classes | `PascalCase` | `Schematic`, `NetLabel` |
| Functions / methods | `snake_case` | `find_symbol()`, `export_svg()` |
| Variables | `snake_case` | `pin_endpoints`, `wire_color` |
| Constants | `UPPER_SNAKE_CASE` | `_OBSTACLE_CLEARANCE` |
| Private members | `_leading_underscore` | `_symbol_index`, `_loaded` |
| Type aliases | `PascalCase` | `PinKey`, `PointPair` |

### Files and Directories

- Source files: `snake_case.py`
- Test files: `test_<module>.py` — one file per module under test
- Coverage-focused test files: `test_cov_<module>.py`
- Fixture files: match original tool naming (e.g., `Amplifier_Buffer.kicad_sym`)

---

## Code Style

### Formatter and Linter

This project uses **ruff** for linting and formatting.

```bash
# Lint
ruff check lib tests tools

# Format
ruff format lib tests tools
```

Configuration lives in `pyproject.toml` under `[tool.ruff]`.

### General Rules

- Line length: **100 characters**
- Target Python version: **3.9+** (no walrus operator in hot paths, avoid 3.10+ match syntax)
- Type hints: required for all public functions and methods; optional for internal helpers
- Docstrings: use one-line docstrings for simple functions; multi-line only when behavior needs explanation
- Avoid verbose docstrings that just repeat the signature — prefer clear naming instead

### Imports

Order (enforced by ruff/isort):
1. Standard library
2. Third-party packages
3. Internal (`lib.*`)

No wildcard imports (`from x import *`).

---

## Commit Conventions

This project follows **Conventional Commits** (`conventionalcommits.org`).

### Format

```
<type>(<scope>): <short summary>

[optional body]

[optional footer]
```

### Types

| Type | When to use |
|---|---|
| `feature` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code change with no behavior change |
| `test` | Adding or updating tests |
| `docs` | Documentation changes only |
| `chore` | Tooling, config, dependency updates |
| `perf` | Performance improvements |
| `style` | Formatting-only changes (no logic) |

### Scope (optional)

Use the affected module or area: `core`, `render`, `symbols`, `svg`, `erc`, `examples`, `tests`, `tools`.

### Examples

```
feature(render): add NetLabel flag rendering for top/bottom directions
fix(core): handle missing pin key in _resolve_pin_key gracefully
refactor(symbols): remove footprint support and related tests
test(svg): add obstacle avoidance wire routing coverage
docs: add developer guide
chore: sanitize hardcoded paths in examples
```

### Rules

- Summary line: **imperative mood**, no period at end, max **72 characters**
- Do not mix unrelated changes in a single commit
- Each commit should leave the test suite green

---

## Testing

### Running Tests

```bash
# All tests
python3 -m pytest

# With coverage
python3 -m pytest --cov=lib --cov-report=term-missing

# Single file
python3 -m pytest tests/unit/test_schematic.py -v
```

### Coverage Requirement

Minimum total coverage: **70%** (enforced in CI via `pyproject.toml`).  
Target: **90%+** for active development.

### Test File Conventions

- One test file per source module: `test_<module>.py`
- Coverage-gap focused tests: `test_cov_<module>.py`
- Each test function name should describe the scenario: `test_find_symbol_raises_when_lib_missing`
- Do **not** use `unittest.mock` to skip real logic — test real code paths
- Do **not** add tests that only exercise `example` scripts

### Fixtures

Static fixture files live in `tests/fixtures/`.  
Use `tmp_path` (pytest built-in) for files generated during tests.

---

## Branch Strategy

| Branch | Purpose |
|---|---|
| `main` | Stable, always green |
| `feature#<issue>` | Feature development |
| `fix#<issue>` | Bug fixes |
| `refactor#<issue>` | Refactoring work |
| `docs#<issue>` | Documentation only |

### Pull Request Rules

- All PRs must pass `pytest` (no failures)
- Coverage must not drop below the configured threshold
- Squash-merge preferred for feature branches to keep history clean
- At least one reviewer before merge (when team > 1)
