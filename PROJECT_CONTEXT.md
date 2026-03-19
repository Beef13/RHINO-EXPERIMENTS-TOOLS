# Project Context

## Purpose

This is a personal Rhino Python lab for:
- Procedural geometry experiments (grids, attractors, growth, subdivision)
- Building reusable tools that run inside Rhino's Python editor
- Gradually extracting stable helpers into a shared library

## Runtime Environment

| Property          | Value                                      |
|-------------------|--------------------------------------------|
| Python runtime    | IronPython 2.7 (inside Rhino)              |
| Target app        | Rhinoceros 7 or 8                          |
| Available APIs    | `rhinoscriptsyntax`, `Rhino.Geometry` (RhinoCommon), `scriptcontext` |
| Editor            | Cursor (VS Code fork)                      |
| OS                | Windows 10/11                              |

## Key APIs

### rhinoscriptsyntax (rs)

High-level wrapper. Good for quick scripts. Always imported as:

```python
import rhinoscriptsyntax as rs
```

### RhinoCommon (Rhino.Geometry)

Lower-level .NET API. Use for performance-sensitive code or when `rs` doesn't expose what you need:

```python
import Rhino.Geometry as rg
```

### scriptcontext

Access to the active document, sticky dictionary (persistent variables), and escape key checking:

```python
import scriptcontext as sc
```

## Architecture

```
experiments/   → disposable, dated studies (quick iteration)
tools/         → promoted scripts with UI (stable, reusable)
lib/           → shared helpers imported by experiments and tools
```

Scripts in `experiments/` and `tools/` add `lib/` to `sys.path` at the top:

```python
import sys, os
lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib")
sys.path.insert(0, lib_path)
```

## Constraints

- IronPython 2.7 has **no f-strings**, no `pathlib`, no `typing`, limited stdlib
- Use `str.format()` or `%` formatting
- Avoid third-party packages — they generally can't be installed in IronPython
- All geometry operations happen through `rhinoscriptsyntax` or `RhinoCommon`
- Scripts run single-threaded in Rhino's UI thread

## Conventions

- Experiments are named `YYYY-MM-topic/`
- Every experiment has `script.py` (entry point) and `notes.md` (learnings)
- Lib modules use snake_case and include docstrings
- Tools include a `ui.py` for Rhino command-line interaction
- See `docs/conventions.md` for full details
