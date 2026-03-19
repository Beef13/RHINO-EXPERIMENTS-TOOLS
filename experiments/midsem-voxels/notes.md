# Voxel Field Tool v01

## Goal
Explore Perlin noise-driven voxel fields with real-time parameter control, running live inside Rhino via an Eto UI panel.

## How to Run
1. Open Rhino 8
2. `RunPythonScript` → select `script.py`
3. The Voxel Field Tool dialog opens as a modeless window
4. Adjust sliders — the viewport updates in real time (when Live Update is on)

## Architecture

The script is a single-file tool with four main classes:

| Class | Role |
|-------|------|
| `PerlinNoise` | Deterministic 3D gradient noise with octave layering |
| `VoxelConduit` | Rhino DisplayConduit subclass — draws preview meshes and bounds directly into the viewport without baking |
| `VoxelSystem` | Core engine — generates voxel fields and builds meshes for display |
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

### Display
- Live viewport preview via DisplayConduit (no baking required)
- Density-mapped vertex colours (false colour mode) or flat shaded
- Bounding box wireframe and voxel edge wireframe toggles
- Colour pickers for voxels, edges, and bounds
- Gradient bar showing the density-to-colour mapping

### Baking (Output)
- **Bake** — add voxel mesh to document with vertex colours
- **Bake Brep** — convert each voxel to a NURBS polysurface (no colour)

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
- **Edge boids** — agent-based surface pathfinding removed
- **Boid path attractor** — curve attractors for boid direction removed
- **Melt / blend** — Laplacian mesh blending removed

## Ideas to Explore
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
