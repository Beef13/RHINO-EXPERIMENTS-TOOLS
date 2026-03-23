# Voxel Field Tool v01

## Goal
Path-driven voxel field tool — generates a plain filled grid, then uses wander and slime mould paths as attractors to sculpt the field with Perlin noise variation.

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
- Initial generation produces a **plain filled grid** — all cells active at density 1.0 (no noise)
- Paths act as the primary shaping element; noise provides organic variation when paths are active
- **Linked sliders** — Grid XYZ and Voxel Size can be locked together so adjusting one axis updates all three
- Truncated octahedron mode uses 24-vertex / 38-face polyhedra (6 quads + 8 hexagons fan-triangulated) that space-fill when cell sizes are uniform

### Path Influence (primary shaping system)
Generated wander and slime mould paths act as attractors (or subtractors in carve mode). Perlin noise provides organic edge variation around the paths.

**Workflow:**
1. Set grid dimensions and optionally assign bounding geometry
2. Click Refresh — generates a plain filled grid
3. Generate wander and/or slime mould paths (Pathfinding section)
4. Enable **Use Paths as Attractors**, set Radius/Strength, adjust noise params
5. Click Refresh — voxels are sculpted around paths; live trails are cleared but preserved as **influence trails** for continued display
6. Toggle **Show Influence Paths** to keep the applied paths visible in the viewport; adjust line width and colour
7. Repeat: generate new paths on the sculpted grid, adjust, refresh

**Detection method:** Path influence uses **grid-cell-based detection**. Trail keys (grid indices) are stored directly from the pathfinder, so there is no coordinate-space conversion — the detection is exact. An influence field is pre-expanded from the path keys, mapping every grid cell within `Influence Radius` cells to its minimum squared distance from the nearest path cell. Lookup per voxel is O(1) dict access.

**Concentrate mode** (default): Noise provides a base 0–1 field. Within the influence radius (measured in grid cells), density is boosted by `(1 - d/radius) * strength` where d is the cell distance. Outside the radius, density is penalised by `strength * 0.5`. Threshold filters out low-density cells. Result: voxels cluster around paths with organic edges.

**Carve mode**: Noise provides a base 0–1 field. Within the influence radius, density is reduced by `(1 - d/radius) * strength`. Result: tunnels/voids are carved along paths with organic edges.

**Parameters**:

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Use Paths as Attractors | checkbox | off | Enable path-based density shaping |
| Carve Mode | checkbox | off | Subtract density near paths (default: concentrate) |
| Influence Radius (cells) | 0–30 | 3 | Number of grid cells of influence around each path cell |
| Path Strength | 0–3 | 1.0 | Effect intensity (>1 gives hard contrast) |
| Noise Scale | 0.01–1.0 | 0.15 | Perlin noise frequency (organic variation) |
| Threshold | 0–1 | 0.45 | Density cutoff for voxel visibility |
| Octaves | 1–6 | 3 | Noise detail layers |
| Seed | 0–100 | 0 | Random seed for noise variation |
| Show Influence Paths | checkbox | on | Display paths that were applied as influence |
| Line Width | 1–10 | 2 | Influence path line thickness |
| Path Colour | colour picker | orange | Influence path display colour |
| Clear Paths | button | — | Remove stored influence trails |

### Custom Voxel Geometry
- Replace default box voxels with any mesh/brep/surface shape
- Custom geometry is normalised to unit size and replicated at each voxel position
- Configurable custom scale factor
- Feature edge detection for wireframe overlay on custom shapes

### Pathfinding

Wander and Slime Mould are **two separate functions**, each with its own Generate button, Clear button, and Animate controls. Both share the same graph, targets, and core parameters.

Two **graph modes** — **Voxel Centres** (cell-to-cell adjacency, 6-connected for cubes, 14-connected for BCC/TO) or **Voxel Edges** (wireframe vertex adjacency with shared-vertex merging).

#### Wander Mode
- Generates paths through the voxel volume from user-assigned or auto-generated start points
- **Start points** — pick interactively in the viewport, or auto-generate random starts from graph nodes
- **Target attractors** — optional target points, curves, and meshes/breps/surfaces that pull paths toward them
- **Repulsion field** — buffer distance around attractor geometry that prevents path intersection (quadratic falloff)
- Scored greedy walk at each step evaluates every neighbour by:
  - **Density pull** — prefer high-density nodes
  - **Attractor pull** — proximity and directional bias toward nearest target geometry
  - **Repulsion** — strong penalty within repulsion distance of any attractor
  - **Momentum** — continue in the same direction (dot product of previous and candidate vectors)
  - **Separation** — penalise nodes previously visited by any agent (global visit counter)
  - **Wander** — random noise per candidate for organic variation
- **Branching** — probabilistic splitting spawns a new agent down the next-best edge, capped by max branches

#### Slime Mould Mode
- Simulates Physarum-style slime mould growth connecting all assigned target elements (points, curves, meshes/breps) into an organic, volume-filling network
- Anchor points are extracted from each target element: points used directly, curves contribute their midpoint, meshes/breps contribute their bounding-box centre; each snapped to the nearest graph node
- **Multiple agents per anchor** — `Mould Density` agents spawn from each anchor and seek the nearest other anchor (range 1–500, allowing extreme density)
- Agents stop when they reach any anchor (not just their initial target), creating a self-organising network
- **Positive reinforcement** — nodes already visited by earlier agents receive a bonus score (`Reinforcement` parameter), causing later agents to converge onto established paths (Physarum tube thickening)
- **Direction** — controls how strongly agents aim for their target (0 = pure wander/exploration, 3 = direct paths). Low values create dense volume-filling networks; high values create efficient direct connections
- **Branching** — agents can probabilistically branch (controlled by `Branch Prob` and `Max Branches`) to create even denser coverage; branch agents pick random targets so they spread through the volume
- **Separation** counterbalances reinforcement — controls how much agents spread vs. converge; low separation + high reinforcement = thick consolidated tubes; high separation + low reinforcement = many thin spread paths
- **Repulsion field** keeps paths from intersecting target geometry, creating an enveloping effect where the network wraps around targets at a configurable buffer distance
- Density pull, momentum, wander, and repulsion all apply to each agent step
- All agents are simulated in parallel per time step (synchronous stepping), so branching and positive reinforcement compound effectively

#### Dense Volume-Filling Networks
To make the slime mould consume the entire voxel volume:
- Set **Mould Density** high (100–500) — spawns many agents per anchor
- Set **Direction** low (0.0–0.5) — agents wander freely instead of heading straight to targets
- Set **Branch Prob** moderate (0.1–0.3) — agents fork repeatedly
- Set **Max Branches** high (200–500) — allows many forks
- Set **Wander** high (1.0–2.0) — agents explore randomly
- Set **Separation** high (1.0–2.0) — agents avoid each other's trails, spreading further
- Set **Max Steps** high (500–1000) — agents walk longer before stopping

#### Animation
- **Animate Wander** and **Animate Slime** are separate toggles (hidden by default)
- Each mode has its own Play/Pause/Reset buttons, Speed slider, and frame counter
- **Play** progressively reveals that mode's trails frame-by-frame
- **Pause** freezes at the current frame; **Reset** restores full trail visibility
- **Speed** (1–20) controls playback rate per mode
- Animation auto-prepares when that mode's paths are generated; cleared when that mode is cleared

#### Wander → Slime Targets
- **"Wander → Slime Targets"** button converts existing wander path polylines into target curves for slime mould mode
- Allows a two-phase workflow: explore with wander, then grow slime mould networks around the discovered paths
- Curves are appended to existing target curves, not replaced

#### Common Features
- Wander and slime mould trails are stored and displayed independently with separate colours, widths, and opacity
- Paths are drawn in the `DrawForeground` pipeline so they render on top of voxels regardless of voxel opacity
- Display controls per type: show/hide, line width, opacity, colour picker
- Start/anchor points shown as round control points with separate colour and size controls
- Paths auto-clear when voxels are regenerated (graph becomes stale)

#### Baking
- **Bake Mode** dropdown: **All Together** (one group), **Group by Type** (one group per bake), **Group by Agent** (one group per trail)
- **Bake Wander** / **Bake Slime** / **Bake All** buttons — bake to dedicated layers (`Wander_Paths`, `Slime_Paths`)
- Curves are grouped in the Rhino document according to the selected bake mode

#### Pathfinding Parameters

**Shared** (apply to both modes):

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Graph Mode | dropdown | Voxel Centres | Centre (cell-to-cell) or Edge (wireframe) traversal |
| Max Steps | 10–1000 | 200 | Maximum walk length per agent |
| Density Pull | 0.0–2.0 | 1.0 | Attraction toward high-density voxel nodes |
| Momentum | 0.0–2.0 | 0.8 | Preference for continuing in same direction |
| Separation | 0.0–2.0 | 0.3 | Penalty for visiting already-walked nodes |
| Wander | 0.0–2.0 | 0.3 | Random exploration factor |
| Repulsion Dist | 0.0–50.0 | 0.0 | Buffer around target geometry — paths pushed away |
| Branch Prob | 0.0–0.5 | 0.05 | Chance of spawning a branch per step |
| Max Branches | 0–500 | 50 | Cap on total branches across all agents |
| Seed | 0–100 | 42 | Random seed for reproducibility |

**Wander Only**:

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Agent Count | 1–50 | 5 | Number of random start points when auto-generating |
| Attractor Pull | 0.0–3.0 | 1.5 | Strength of pull toward target geometry |
| Attractor Radius | 1.0–200.0 | 50.0 | Max influence distance for target geometry |

**Slime Mould Only**:

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Mould Density | 1–500 | 5 | Agents spawned per anchor — higher = thicker network |
| Reinforcement | 0.0–3.0 | 0.8 | Bonus for already-visited nodes (tube thickening) |
| Direction | 0.0–3.0 | 1.0 | How directly agents aim for targets (0 = wander, 3 = direct) |

**Animation** (per mode):

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Animate Wander / Animate Slime | checkbox | off | Toggles visibility of that mode's animation controls |
| Speed | 1–20 | 5 | Playback speed per mode |

**Wander Display**:

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Show Wander | checkbox | on | Toggle wander trail visibility |
| Width | 1–10 | 2 | Line thickness in pixels |
| Opacity | 0–255 | 255 | Trail transparency |
| Wander Colour | picker | gold (255,200,50) | Colour of wander polylines |

**Slime Mould Display**:

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Show Slime | checkbox | on | Toggle slime trail visibility |
| Width | 1–10 | 2 | Line thickness in pixels |
| Opacity | 0–255 | 255 | Trail transparency |
| Slime Colour | picker | green (50,220,120) | Colour of slime polylines |

**Points**:

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Show Points | checkbox | on | Toggle point markers |
| Point Size | 2–20 | 8 | Display size of markers |
| Point Colour | picker | red (255,80,80) | Colour of point markers |

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
- **Bake Wander** / **Bake Slime** / **Bake All** — bake path polylines as curves on dedicated layers with grouping options

## Performance Notes
- Debounced UITimer at 60ms (16fps) with two dirty flags separates heavy recomputes from cheap display refreshes
- **Perlin noise**: gradient table pre-computed at init; all gradient dot products fully inlined (no inner function/closure creation); `math.floor` replaced with branchless int cast
- **Path influence**: trail keys (grid indices) are captured directly from the pathfinder — no Point3d-to-index conversion needed. An influence field dict is pre-expanded from path keys at build time; each voxel's influence lookup is a single O(1) dict access with no distance calculation in the inner loop
- **Mesh building**: all `.Add`/`.AddFace` method references cached as local variables to eliminate per-call attribute lookups; `mesh.Compact()` removed (unnecessary when building fresh); vertex counter tracked in Python (avoids `.Count` property access per voxel)
- **Display conduit**: transparent materials cached and reused across frames; edge/trail colours cached; `Display` object referenced once per draw call
- AABB pre-rejection on bounds (6-float compare) runs before expensive `Mesh.IsPointInside`
- Without paths active, grid fills at density 1.0 with zero noise computation
- Truncated octahedron hex face indices are pre-flattened into a flat (v0,v1,v2) tuple array to eliminate inner loop overhead
- Large grids (>50x50x50) will still be slow — this is IronPython, not C
- Slime mould with high Mould Density (200+) can produce thousands of agents — expect a pause during generation

## Removed Features
- **Hollow shell mode** — removed to simplify the pipeline
- **Voxel density rotation** — two-axis density-driven rotation removed
- **Voxel density scale** — neighbour-aware density scaling removed
- **Edge boids** — replaced by `VoxelPathfinder` system with attractor-driven pathfinding
- **Boid path attractor** — now integrated into pathfinder as target curves/geos
- **Melt / blend** — Laplacian mesh blending removed
- **Standalone noise generation** — noise no longer drives initial grid; grid starts filled, noise provides variation when paths are active
- **Point/Curve/Geometry attractors** — replaced by path-based attractor system (paths = attractors)
- **Base geometry** — replaced by path influence (paths are the primary shaping element)
- **Fill Grid toggle** — grid is always filled by default (paths sculpt it)

## Ideas to Explore
- [x] Path trail attractors — use generated paths as density modifiers (concentrate or carve)
- [ ] Trail mesh generation — sweep a profile along paths for 3D mycelium tubes
- [ ] Multi-agent species — different agent groups with competing rules/targets
- [x] Animated growth — step-by-step path growth with play/pause
- [ ] Multi-material / multi-colour voxels based on density ranges
- [ ] Export to STL or OBJ for 3D printing
- [ ] Marching cubes for smooth isosurface extraction instead of boxes
- [ ] Animation — sweep noise seed or attractor positions over time
- [ ] GPU-accelerated noise via compute shader (if moving to C#/GH plugin)
- [ ] Save/load parameter presets to JSON
- [ ] Undo support for bake operations
- [ ] Slime mould evaporation — trail decay over time for dynamic equilibrium

## Known Limitations
- Single-threaded — large grids block the UI during recompute
- No undo for bake operations (Rhino's built-in undo covers individual object additions)
- Brep bake can be slow for high voxel counts (each voxel becomes a polysurface)
- Custom geometry edge detection uses a fixed 20-degree angle threshold
- No persistence — closing the dialog loses all state
- Truncated octahedra only tile perfectly with uniform cell sizes (cell_w = cell_l = cell_h)
