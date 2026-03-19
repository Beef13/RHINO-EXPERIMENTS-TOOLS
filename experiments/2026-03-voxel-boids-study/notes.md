# Voxel Field Tool v01

## Goal
Explore Perlin noise-driven voxel fields with real-time parameter control, agent-based surface pathfinding (boids), and mesh blending — all running live inside Rhino via an Eto UI panel.

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
| `VoxelConduit` | Rhino DisplayConduit subclass — draws preview meshes, trails, and bounds directly into the viewport without baking |
| `VoxelSystem` | Core engine — generates voxel fields, builds meshes, runs boid pathfinding, creates pipes, applies Laplacian smoothing |
| `VoxelDialog` | Eto.Forms UI — all sliders, buttons, and colour pickers. Uses a debounced UITimer (0.12s) with two dirty flags to separate heavy recomputes from cheap display refreshes |

## Current Capabilities

### Voxel Generation
- 3D grid sampled from Perlin noise (configurable grid X/Y/Z, cell dimensions)
- Noise parameters: scale (frequency), threshold (density cutoff), octaves (detail layers), seed
- Hollow shell mode — removes interior voxels, keeps only outer shell at configurable thickness

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

### Voxel Transforms
- **Density rotation** — rotate each voxel by an angle proportional to its noise density value
- Two independent rotation axes can be stacked for compound twist effects
- **Density scale** — shrink lower-density voxels while keeping full-density ones at full size
- Neighbour-aware scaling — shared faces between adjacent voxels stay full-size to prevent gaps

### Edge Boids (Agent-Based Surface Pathfinding)
- Builds a graph of vertices on exposed voxel faces
- Agents walk the surface choosing between straight continuation and turning
- Parameters: agent count, trail steps, turn chance, min/max turn angle, straight threshold
- Diagonal edge connections (optional 45-degree traversal)
- Overlap control — allow or prevent agents from reusing edges
- Surface offset with smoothed normals and configurable tightness
- Corner filleting via quadratic Bezier arcs
- Boid path attractor curves — bias agent direction toward selected curves

### Pipe Mesh Generation
- Extrude circular cross-sections along boid trail polylines
- Parallel transport frame to prevent twist
- Watertight tubes with start/end caps
- Configurable radius and segment count

### Melt / Blend
- Combines voxel mesh and pipe mesh into one
- Applies iterative Laplacian smoothing to blend them into an organic form
- Configurable iteration count and smoothing strength

### Display
- Live viewport preview via DisplayConduit (no baking required)
- Density-mapped vertex colours (false colour mode) or flat shaded
- Bounding box wireframe and voxel edge wireframe toggles
- Colour pickers for voxels, edges, bounds, and trails
- Gradient bar showing the density-to-colour mapping

### Baking (Output)
- **Bake** — add voxel mesh to document with vertex colours
- **Bake Brep** — convert each voxel to a NURBS polysurface (no colour)
- **Bake Trails** — add trail polylines and pipe mesh to document
- **Bake Trails Brep** — convert pipe mesh to NURBS breps or trails to NURBS curves
- **Bake Melt** — add the melted/blended mesh to document

## Performance Notes
- The debounced timer prevents recompute on every slider pixel — parameters are batched at 0.12s intervals
- Two dirty flags: `_compute_dirty` (full noise recompute, heavy) vs `_display_dirty` (mesh rebuild only, cheap)
- Perlin noise uses inlined fade/lerp/grad for speed
- Voxel mesh builds batch vertex/face additions to minimise .NET interop overhead
- Laplacian smoothing pre-builds adjacency into flat Python arrays
- Large grids (>50x50x50) will be slow — this is IronPython, not C

## Ideas to Explore
- [ ] Multi-material / multi-colour voxels based on density ranges
- [ ] Export to STL or OBJ for 3D printing
- [ ] Space colonisation algorithm as alternative to random-walk boids
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
