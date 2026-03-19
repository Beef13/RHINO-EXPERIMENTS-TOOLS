# Voxel Field Tool v01

## Goal
Explore Perlin noise-driven voxel fields with real-time parameter control, running live inside Rhino via an Eto UI panel.

## How to Run
1. Open Rhino 8
2. `RunPythonScript` → select `script.py`
3. The Voxel Field Tool dialog opens as a modeless window
4. Adjust sliders — the viewport updates in real time (when Live Update is on)

## Architecture

The script is a single-file tool with five main classes:

| Class | Role |
|-------|------|
| `PerlinNoise` | Deterministic 3D gradient noise with octave layering |
| `VoxelConduit` | Rhino DisplayConduit subclass — draws preview meshes (with opacity), bounds, path trails, and start/end point markers directly into the viewport without baking |
| `VoxelSystem` | Core engine — generates voxel fields and builds meshes for display |
| `VoxelPathfinder` | Pathfinding engine — builds a traversal graph (voxel-centre adjacency or wireframe-edge adjacency) from the voxel field, runs scored greedy walks from user-assigned or auto-generated start points toward optional attractor geometry, with branching support |
| `VoxelDialog` | Eto.Forms UI — all sliders, buttons, and colour pickers in collapsible `Expander` sections. Uses a debounced UITimer (0.12s) with two dirty flags to separate heavy recomputes from cheap display refreshes |

## Current Capabilities

### Bounding Geometry
- Assign any closed mesh or brep as a bounding volume — voxels outside are clipped
- Works with arbitrary shapes (spheres, blobs, imported meshes — not limited to boxes)
- Two clip modes: **Center Point** (test voxel center only, fast) and **All Corners** (test all 8 voxel corners, stricter edge clipping)
- Auto-center option — grid origin snaps to the bounding geometry's center
- Breps are pre-converted to meshes on assign for faster `IsPointInside` containment testing
- AABB pre-rejection skips the expensive containment test for voxels clearly outside the volume
- Grid resolution (X/Y/Z) and cell sizes remain fully adjustable after assigning bounds

### Voxel Generation
- **Grid Type** dropdown: **Cube** (simple cubic lattice) or **Truncated Octahedron** (BCC lattice with body-center positions at half-cell offsets)
- 3D grid sampled from Perlin noise (configurable grid X/Y/Z, cell dimensions)
- Noise parameters: scale (frequency), threshold (density cutoff), octaves (detail layers), seed
- Fill Grid option — bypass noise, fill every cell at full density
- **Linked sliders** — Grid XYZ and Voxel Size can be locked together so adjusting one axis updates all three
- Truncated octahedron mode uses 24-vertex / 38-face polyhedra (6 quads + 8 hexagons fan-triangulated) that space-fill when cell sizes are uniform

### Attractors
- **Point attractors** — boost voxel density within a radius around selected points
- **Curve attractors** — density boost based on closest distance to curves
- **Geometry attractors** — density boost from meshes, surfaces, or breps
- All attractor types can be combined; each has configurable radius and strength

### Base Geometry
- Assign curves, meshes, surfaces, or breps as a base shape
- Concentrate mode — voxels cluster around the base geometry
- Carve mode — voxels are removed near the base geometry
- Auto-center option — grid origin snaps to the base geometry's bounding box center

### Custom Voxel Geometry
- Replace default box voxels with any mesh/brep/surface shape
- Custom geometry is normalised to unit size and replicated at each voxel position
- Configurable custom scale factor
- Feature edge detection for wireframe overlay on custom shapes

### Pathfinding
- Generates paths through the voxel volume from user-assigned or auto-generated start points
- Two **graph modes** — **Voxel Centres** (cell-to-cell adjacency, 6-connected for cubes, 14-connected for BCC/TO) or **Voxel Edges** (wireframe vertex adjacency with shared-vertex merging)
- **Start points** — pick interactively in the viewport, or auto-generate density-biased random starts from graph nodes
- **Target attractors** — optional target points, curves, and meshes/breps/surfaces that pull paths toward them
- Scored greedy walk at each step evaluates every neighbour by:
  - **Density pull** — prefer high-density nodes
  - **Attractor pull** — proximity and directional bias toward nearest target geometry
  - **Momentum** — continue in the same direction (dot product of previous and candidate vectors)
  - **Separation** — penalise nodes previously visited by any agent (global visit counter)
  - **Wander** — random noise per candidate for organic variation
- **Branching** — probabilistic splitting spawns a new agent down the next-best edge, capped by max branches
- Paths are drawn live via the display conduit as coloured polylines; start points shown as round control points
- Display controls: show/hide paths, show/hide points, path colour, point colour, path width, point size
- **Bake Paths** commits all trail polylines as curves and start points to the Rhino document
- Paths auto-clear when voxels are regenerated (graph becomes stale)

#### Pathfinding Parameters

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Graph Mode | dropdown | Voxel Centres | Centre (cell-to-cell) or Edge (wireframe) traversal |
| Agent Count | 1–50 | 5 | Number of random start points when auto-generating |
| Max Steps | 10–500 | 100 | Maximum walk length per agent |
| Branch Prob | 0.0–0.3 | 0.05 | Chance of spawning a branch per step |
| Max Branches | 0–200 | 50 | Cap on total branches across all agents |
| Density Pull | 0.0–2.0 | 1.0 | Attraction toward high-density voxel nodes |
| Attractor Pull | 0.0–3.0 | 1.5 | Strength of pull toward assigned target geometry |
| Attractor Radius | 1.0–200.0 | 50.0 | Max influence distance for target geometry |
| Momentum | 0.0–2.0 | 0.8 | Preference for continuing in same direction |
| Separation | 0.0–2.0 | 0.5 | Penalty for visiting already-walked nodes |
| Wander | 0.0–2.0 | 0.3 | Random exploration factor |
| Seed | 0–100 | 42 | Random seed for reproducibility |
| Path Width | 1–10 | 2 | Display line thickness in pixels |
| Point Size | 2–20 | 8 | Display size of start/end point markers |
| Path Colour | picker | gold (255,200,50) | Colour of path polylines in viewport |
| Point Colour | picker | red (255,80,80) | Colour of start point markers in viewport |

### Display
- Live viewport preview via DisplayConduit (no baking required)
- **Show Voxels** checkbox — hide voxel mesh while keeping paths visible
- **Voxel Opacity** slider (0–255) — translucent voxels via `DisplayMaterial.Transparency`; at full opacity vertex colours use `DrawMeshFalseColors`, at reduced opacity falls back to `DrawMeshShaded` with transparent material
- Density-mapped vertex colours (false colour mode) or flat shaded
- Bounding box wireframe and voxel edge wireframe toggles
- Colour pickers for voxels, edges, and bounds
- Gradient bar showing the density-to-colour mapping

### Baking (Output)
- **Bake** — add voxel mesh to document with vertex colours
- **Bake Brep** — convert each voxel to a NURBS polysurface (no colour)
- **Bake Paths** — add path polylines as curves and start points to document

## Performance Notes
- The debounced timer prevents recompute on every slider pixel — parameters are batched at 0.12s intervals
- Two dirty flags: `_compute_dirty` (full noise recompute, heavy) vs `_display_dirty` (mesh rebuild only, cheap)
- Perlin noise uses inlined fade/lerp/grad for speed
- Voxel mesh builds batch vertex/face additions to minimise .NET interop overhead
- Large grids (>50x50x50) will be slow — this is IronPython, not C
- Truncated octahedron mode generates ~2x as many voxels as cube mode (BCC body-centers) and each shape has 24 vertices vs 8, so expect ~6x more mesh data per grid cell
- Bounding geometry: breps are converted to meshes once on assign (not per-frame). AABB min/max are unpacked to plain floats before the generation loop to avoid .NET property access overhead. 6-float AABB rejection runs before the expensive `Mesh.IsPointInside` ray-cast

## Removed Features
- **Hollow shell mode** — removed to simplify the pipeline
- **Voxel density rotation** — two-axis density-driven rotation removed
- **Voxel density scale** — neighbour-aware density scaling removed
- **Edge boids** — replaced by `VoxelPathfinder` system with attractor-driven pathfinding
- **Boid path attractor** — now integrated into pathfinder as target curves/geos
- **Melt / blend** — Laplacian mesh blending removed

## Ideas to Explore
- [ ] Path trail attractors — use generated paths as curve attractors for voxel density
- [ ] Trail mesh generation — sweep a profile along paths for 3D mycelium tubes
- [ ] Multi-agent species — different agent groups with competing rules/targets
- [ ] Animated growth — step-by-step path growth with play/pause
- [ ] Multi-material / multi-colour voxels based on density ranges
- [ ] Export to STL or OBJ for 3D printing
- [ ] Marching cubes for smooth isosurface extraction instead of boxes
- [ ] Animation — sweep noise seed or attractor positions over time
- [ ] GPU-accelerated noise via compute shader (if moving to C#/GH plugin)
- [ ] Save/load parameter presets to JSON
- [ ] Undo support for bake operations

## Known Limitations
- Single-threaded — large grids block the UI during recompute
- No undo for bake operations (Rhino's built-in undo covers individual object additions)
- Brep bake can be slow for high voxel counts (each voxel becomes a polysurface)
- Custom geometry edge detection uses a fixed 20-degree angle threshold
- No persistence — closing the dialog loses all state
- Truncated octahedra only tile perfectly with uniform cell sizes (cell_w = cell_l = cell_h)
