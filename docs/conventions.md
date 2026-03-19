# Conventions

## Naming

| Item | Convention | Example |
|------|-----------|---------|
| Experiment folders | `YYYY-MM-topic` | `2026-03-grid-tester` |
| Python files | `snake_case.py` | `math_utils.py` |
| Functions | `snake_case` | `apply_attractor()` |
| Variables | `snake_case` | `point_count` |
| Constants | `UPPER_SNAKE` | `DEFAULT_RADIUS` |
| Classes (rare) | `PascalCase` | `VoxelGrid` |
| Layers in Rhino | `PascalCase` | `GridOutput`, `AttractorPoints` |

## File Structure

### Experiments

Each experiment lives in `experiments/YYYY-MM-topic/` with:

- `script.py` — the main entry point, runnable in Rhino
- `notes.md` — what you tried, what worked, what you learned
- `sample_inputs/` — optional reference geometry or data

Experiments are disposable. Don't worry about polish.

### Tools

Each tool lives in `tools/tool_name/` with:

- `script.py` — core logic, importable functions
- `ui.py` — Rhino command-line UI (GetObject, GetPoint, etc.)
- `notes.md` — usage notes and known limitations

Tools should be stable enough for repeated use.

### Lib Modules

Shared helpers in `lib/` are organised by domain:

- `geometry/` — pure geometry operations (attractors, subdivision, transforms)
- `rhino/` — Rhino API wrappers (selection, layers, preview, baking)
- `utils/` — general utilities (logging, data conversion, math)

Every public function in lib must have a docstring.

## Script Boilerplate

Every experiment and tool script starts with:

```python
"""One-line description of what this script does."""
import sys, os

_here = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.normpath(os.path.join(_here, "..", "..", "lib"))
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import rhinoscriptsyntax as rs
import scriptcontext as sc
```

## Rhino Practices

- Always check return values from `rs.GetObject()`, `rs.GetPoint()`, etc.
- Wrap bulk operations in `rs.EnableRedraw(False)` / `True`
- Use meaningful layer names
- Clean up preview geometry when done (or put it on a dedicated layer)
- Add `sc.escape_test(False)` in long-running loops

## Git

- Commit experiments early — they're notes, not production code
- Don't commit `.3dm` files (they're large and binary)
- Use clear commit messages: `add: grid-tester experiment`, `extract: attractor helpers to lib`
