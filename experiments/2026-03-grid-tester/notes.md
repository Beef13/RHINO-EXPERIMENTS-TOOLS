# Grid Tester

## Goal
Generate rectangular point grids and deform them with attractor points.

## How to Run
1. Open Rhino
2. `RunPythonScript` → select `script.py`
3. Pick an attractor point when prompted
4. Grid of points appears, deformed in Z based on distance to attractor

## Parameters
- `x_count`, `y_count` — grid resolution (default 20x20)
- `spacing` — distance between points (default 2.0)
- `max_height` — peak Z displacement (default 10.0)
- `radius` — attractor influence radius (default 30.0)

## Ideas to Try
- [ ] Connect points with lines or a mesh
- [ ] Multiple attractors
- [ ] Colour points by distance
- [ ] Export height data to CSV

## Observations
_Add notes here as you experiment._
