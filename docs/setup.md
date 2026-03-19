# Setup Guide

## Prerequisites

- **Rhinoceros 7 or 8** (Windows)
- **Cursor** (or VS Code) for editing
- Python scripts run inside Rhino's built-in IronPython 2.7 — no external Python install needed for Rhino scripts

## Getting Started

### 1. Clone the Repo

```
git clone <repo-url> rhino-python-lab
```

Or just copy the folder to a convenient location.

### 2. Open in Cursor

Open the `rhino-python-lab` folder in Cursor. The `.cursor/rules/` files will automatically provide context for AI suggestions.

### 3. Running Scripts in Rhino

**Option A — Paste and Run:**
1. Open Rhino's Python editor: `EditPythonScript`
2. Copy the contents of a script into the editor
3. Click Run

**Option B — RunPythonScript command:**
1. In Rhino's command line, type: `RunPythonScript`
2. Browse to the script file and open it

**Option C — Drag and drop:**
1. Drag a `.py` file from Explorer onto the Rhino viewport

### 4. Setting Up sys.path

Scripts in `experiments/` and `tools/` need access to `lib/`. Each script starts with a path setup block:

```python
import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.normpath(os.path.join(_here, "..", "..", "lib"))
if _lib not in sys.path:
    sys.path.insert(0, _lib)
```

If `__file__` is not defined (e.g., running from the Rhino editor with pasted code), hardcode the path:

```python
sys.path.insert(0, r"C:\path\to\rhino-python-lab\lib")
```

### 5. Optional: CPython Environment

For offline prototyping or running tests outside Rhino:

```
cd rhino-python-lab
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ImportError` for lib modules | Check that `sys.path` includes the `lib/` directory |
| `NameError: rhinoscriptsyntax` | Script must run inside Rhino, not CPython |
| Script seems to hang | Add `sc.escape_test(False)` in loops, press Escape in Rhino |
| Objects don't appear | Check `rs.EnableRedraw(True)` is called, or call `rs.Redraw()` |
