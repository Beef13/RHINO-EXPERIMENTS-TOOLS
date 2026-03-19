# Rhino Python Lab

A personal workspace for writing, testing, and organising Rhino Python scripts using Cursor as the editor and Rhino as the runtime.

## What This Is

- A collection of **experiments** — short-lived procedural geometry studies
- A set of **tools** — scripts that have matured into something reusable
- A shared **lib** — helper modules extracted from experiments and tools
- A place to iterate fast without worrying about breaking things

## Repo Structure

```
experiments/    Dated experiment folders, each self-contained
tools/          Stable scripts with UI wrappers for use in Rhino
lib/            Reusable helpers (geometry, rhino wrappers, utilities)
docs/           Setup guide, conventions, experiment log
assets/         Sample geometry files and screenshots
tests/smoke/    Lightweight sanity checks
```

## Quick Start

1. Clone this repo somewhere convenient
2. Open the folder in **Cursor**
3. In Rhino, open the Python editor (`EditPythonScript`)
4. Point a script at an experiment or tool, e.g.:
   ```python
   import sys
   sys.path.insert(0, r"C:\path\to\rhino-python-lab\lib")
   import geometry.attractors as attractors
   ```
5. Run the script in Rhino

See [`docs/setup.md`](docs/setup.md) for detailed setup instructions.

## Workflow

### Starting a New Experiment

1. Create a dated folder: `experiments/YYYY-MM-topic/`
2. Add `script.py`, `notes.md`, and optionally `sample_inputs/`
3. Write quick-and-dirty code — experiments are disposable
4. Log what you learned in `notes.md`

### Promoting to a Tool

When an experiment produces something worth keeping:

1. Move the core logic to `tools/your_tool/script.py`
2. Add a Rhino command wrapper in `ui.py`
3. Extract any reusable functions into `lib/`

### Extracting to Lib

If you find yourself copying a helper between experiments:

1. Move it to the appropriate `lib/` submodule
2. Add a clear docstring
3. Import it from there going forward

## Conventions

- See [`docs/conventions.md`](docs/conventions.md) for naming and style rules
- See [`docs/experiment-log.md`](docs/experiment-log.md) for a running log of experiments

## Requirements

This repo targets **Rhino 7/8** with **IronPython 2.7** (Rhino's built-in Python).

Some offline helpers or tests may use CPython 3.x — see [`requirements.txt`](requirements.txt).

## License

Personal lab — not published. Add a license if you decide to share.
