# Voxel Curve Sculpt

## Goal
Curve-attractor-based voxel field sculpting — pick curves in Rhino and use them to attract or carve voxels within an optional bounding volume, with Perlin noise for organic edge variation. Supports both cube and truncated octahedron (BCC) grid types. Bake results as mesh or individual breps.

## How to Run
1. Open Rhino 8
2. `RunPythonScript` → select `script.py`
3. The Voxel Curve Sculpt dialog opens as a modeless window
4. Adjust sliders — the viewport updates in real time (when Live Update is on)

## Architecture

Single-file tool with four classes:

| Class | Role |
|-------|------|
| `PerlinNoise` | Deterministic 3D gradient noise with octave layering |
| `SculptConduit` | Rhino DisplayConduit — draws voxel mesh (with edge_mesh for TO wireframe), bounds wireframe, and attractor curves directly in the viewport |
| `VoxelSystem` | Core engine — generates voxel fields (cube or TO/BCC), builds display meshes, bakes to document |
| `SculptDialog` | Eto.Forms UI — collapsible arrow sections matching midsem-voxels style, debounced live updates |

## Workflow

1. Assign bounding geometry (first section) — optional closed mesh/brep/extrusion
2. Set grid dimensions, grid type, and cell sizes
3. Pick curves as attractors in the Rhino viewport
4. Adjust influence radius, strength, falloff, and attract/carve mode
5. Fine-tune noise parameters for organic edge variation
6. Bake result as mesh or brep

## Current Capabilities

### Bounding Geometry (first section)
- Uses `Rhino.Input.Custom.GetObject` with dialog hidden during selection
- Accepts closed meshes, breps, and extrusions (extrusions auto-converted to brep)
- `_preprocess_bounds()` converts all geometry to closed meshes for fast `IsPointInside` checks
- Combined AABB computed for fast pre-rejection
- **Use Bounds** checkbox to enable/disable volume clipping
- **Auto-Center on Bounds** — grid origin centres on bounding geometry AABB
- **Clip Mode** dropdown: Center Point (fast) or All Corners (stricter, checks all 8 cell corners)

### Grid Dimensions
- **Grid Type** dropdown: Cube or Truncated Octahedron (BCC lattice)
- **Link Grid XYZ** checkbox — syncs all three grid axis sliders
- Grid X/Y/Z sliders (1–200, default 10)
- **Link Voxel Size** checkbox — syncs all three cell dimension sliders
- Voxel Width/Length/Height sliders (1–5000, default 1000)

### Grid Types

**Cube** (grid_type 0):
- Standard cubic voxel grid
- 8 vertices, 6 quad faces per voxel
- Edges rendered via `DrawMeshWires`

**Truncated Octahedron** (grid_type 1):
- BCC (body-centred cubic) lattice — primary grid + half-offset interstitial cells
- 24 vertices per voxel: 6 square faces + 8 hexagonal faces
- Dedicated edge mesh via degenerate triangles for clean wireframe rendering
- Space-filling tessellation with no gaps

### Curve Attractors
- Pick one or more curves from the Rhino document (dialog hides during selection)
- Curves are duplicated internally (modifying originals doesn't affect attractors)
- Curves drawn in viewport with configurable colour and thickness
- Distance from each voxel to nearest curve computed via `Curve.ClosestPoint`
- Per-curve AABB pre-rejection skips distance checks for distant voxels

### Influence Modes

**Attract mode** (default):
- Near curves (within radius): density boosted by `falloff * strength`
- Far from curves (outside radius): density penalised by `strength`
- Net result: voxels cluster around curves, everything else disappears

**Carve mode**:
- Near curves: density reduced by `falloff * strength`
- Far from curves: no change
- Net result: tunnels/voids carved along curve paths

**Falloff types**:
- Linear: `f = 1 - d/r`
- Quadratic: `f = (1 - d/r)²`
- Smooth: smoothstep hermite interpolation

### Influence Parameters

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Carve Mode | checkbox | off | Subtract density near curves (default: attract/concentrate) |
| Solid Base | checkbox | on | Start with filled grid (off: start with noise field) |
| Influence Radius | 0–30 | 5 | Number of cells of influence, converted to world units via max(cell_w, cell_l, cell_h) |
| Strength | 0–3 | 1.0 | Effect intensity |
| Falloff | dropdown | Linear | Distance decay profile |

### Noise Variation

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Noise Scale | 0.01–1.0 | 0.15 | Perlin noise frequency |
| Threshold | 0–1 | 0.45 | Density cutoff for voxel visibility |
| Octaves | 1–6 | 3 | Noise detail layers |
| Seed | 0–100 | 0 | Random seed for noise variation |

### Display
- Show/hide voxels, edges, bounds independently
- Adjustable opacity (0–255)
- Configurable colours for voxels, edges, bounds, and curves
- TO grid uses separate edge mesh for clean wireframe; cube uses `DrawMeshWires`

### Bake
- **Bake**: adds the display mesh (with vertex colours) to the document
- **Bake Brep**: creates individual box breps for each voxel on `Voxel_Sculpt` layer
- **Clear**: removes all preview geometry

## UI Style
- Matches midsem-voxels exactly: arrow-based collapsible sections (▼/▶), label width 105, slider width 150, text box width 50
- Live Update checkbox at top level
- `DynamicLayout` throughout for CPython3/PythonNet compatibility
- Dialog hides during object selection (bounds and curves)

## Performance Notes
- Debounced UITimer at 60ms with two dirty flags (compute vs display-only)
- All mesh builders use cached method references for `.Add` / `.AddFace` / `.VertexColors.Add`
- Per-curve AABB pre-rejection avoids expensive `ClosestPoint` calls for distant voxels
- Bounds uses AABB pre-rejection before `Mesh.IsPointInside`
- TO edge mesh uses degenerate triangles (3 verts per edge) for GPU-efficient wireframe
- Bake Brep wraps batch creation in `rs.EnableRedraw(False/True)`

## Ideas to Explore
- [ ] Multiple falloff presets (gaussian, inverse, step)
- [ ] Surface attractors (not just curves)
- [ ] Point cloud attractors
- [ ] Boolean union of baked boxes into a single brep
- [ ] Gradient colour mapping based on density
- [ ] Export voxel data as CSV/JSON
- [ ] Custom voxel geometry (replace cubes with arbitrary mesh)
