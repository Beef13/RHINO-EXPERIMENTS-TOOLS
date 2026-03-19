# Voxel Field Tool v02 — Multi-Field + Environmental Edition

## Goal
Extend the voxel system with multiple pluggable field algorithms, selectable via a dropdown in the UI. The voxel grid responds to whichever field is active — Perlin noise, TPMS lattices, signed distance fields, curl noise, reaction-diffusion, composites, and **environmental fields** driven by architectural factors (pathways, sunlight, views, structural gravity).

## Based On
Duplicated from `experiments/2026-03-voxel-boids-study/` (v01). All original features (boids, pipes, melt, custom geometry, attractors, base geometry, hollow shell) are preserved.

## How to Run
1. Open Rhino 8
2. `RunPythonScript` → select `script.py`
3. The tool dialog opens with a **Field Source** dropdown at the top
4. Select a field algorithm from the dropdown
5. Adjust sliders — the viewport updates in real time

## Architecture

The script adds one new class (`FieldAlgorithms`) and modifies two existing classes:

```
PerlinNoise          — unchanged, provides 3D gradient noise
FieldAlgorithms      — NEW: collection of field evaluators + composite blending
VoxelConduit         — unchanged, draws preview geometry
VoxelSystem          — MODIFIED: dispatches to FieldAlgorithms via _eval_field()
VoxelDialog          — MODIFIED: adds Field Source dropdown + per-algorithm panels
```

### How Field Dispatch Works

The `generate()` method calls `_eval_field()` for every voxel cell. This method checks `field_mode` (an integer from the dropdown) and calls the appropriate evaluator:

```
field_mode  0 → eval_perlin()           noise scale, octaves, seed
field_mode  1 → eval_gyroid()           TPMS scale, wall thickness
field_mode  2 → eval_schwarzp()         TPMS scale, wall thickness
field_mode  3 → eval_diamond()          TPMS scale, wall thickness
field_mode  4 → eval_sdf()              SDF geometry, falloff, invert
field_mode  5 → eval_curl_magnitude()   noise scale, octaves, seed
field_mode  6 → eval_reaction_diffusion()  feed, kill, diffusion, iterations
field_mode  7 → composite(perlin, gyroid)  blend mode + weight
field_mode  8 → eval_pathway()          pathway curves, corridor width, falloff
field_mode  9 → eval_solar()            sun azimuth, sun elevation
field_mode 10 → eval_view_corridor()    viewer/target points, radius, falloff
field_mode 11 → eval_gravity()          profile mode, strength
field_mode 12 → multi-layer blend       picks two sub-fields, blend mode + weight
field_mode 13 → compute_dla()           particles, stickiness, bias, seed placement
field_mode 14 → compute_space_colon()   density, kill dist, influence, root, iterations
field_mode 15 → compute_eden()          birth/survival rules, seed density, noise bias
field_mode 16 → compute_physarum()      agents, sensor/turn angles, deposit, decay
field_mode 17 → compute_mycelium()      initial tips, branching, turn rate, anastomosis
```

Every evaluator returns a scalar in [0, 1]. The downstream pipeline (attractors, base geometry, threshold, hollow, mesh building, boids, melt) is identical regardless of which field produced the value.

---

## Field Algorithms Guide

### 0. Perlin Noise (default)
**What it does:** Smooth, continuous pseudorandom variation. Produces organic, cloud-like density fields.

**When to use:** General-purpose. Good starting point for any experiment.

**Key parameters:**
- **Noise Scale** — frequency of the noise. Small = large blobs, large = fine grain
- **Octaves** — layers of detail. More octaves = richer texture at the cost of speed
- **Seed** — different random variation

### 1. Gyroid (TPMS)
**What it does:** Generates a gyroid triply periodic minimal surface — a smooth, continuous lattice that divides space into two intertwined channels.

**Formula:** `sin(x)*cos(y) + sin(y)*cos(z) + sin(z)*cos(x)`

**When to use:** Lattice structures, porous infill, lightweight structural geometry, acoustic panels, heat exchangers.

**Key parameters:**
- **TPMS Scale** — size of the unit cell. Larger = bigger lattice openings
- **Wall Thickness** — how thick the surface shell is. Lower = thinner walls, more void

### 2. Schwarz-P (TPMS)
**What it does:** Schwarz Primitive surface — a cubic lattice with circular openings along each axis.

**Formula:** `cos(x) + cos(y) + cos(z)`

**When to use:** Regular grid-like porosity, structured ventilation patterns, cubic symmetry.

**Key parameters:** Same as Gyroid (TPMS Scale, Wall Thickness).

### 3. Diamond (TPMS)
**What it does:** Schwarz Diamond surface — a tetrahedral lattice with a more complex interlocking pattern than Gyroid.

**Formula:** `sin(x)*sin(y)*sin(z) + sin(x)*cos(y)*cos(z) + cos(x)*sin(y)*cos(z) + cos(x)*cos(y)*sin(z)`

**When to use:** Dense structural lattices, organic-looking infill, maximising surface area within a volume.

**Key parameters:** Same as Gyroid (TPMS Scale, Wall Thickness).

### 4. Signed Distance Field (SDF)
**What it does:** Measures distance from every voxel centre to assigned Rhino geometry (curves, meshes, surfaces, breps). Voxels near the geometry get high density; voxels far away get low density.

**When to use:** Making voxel volumes that follow existing geometry — thickened shells, offset envelopes, proximity-based patterns.

**Key parameters:**
- **Falloff Distance** — how far from the geometry the effect reaches
- **Invert SDF** — swap solid and void (fill far from geometry instead of near)
- **Assign SDF Geometry** — pick objects from the Rhino viewport

### 5. Curl Noise
**What it does:** Computes the curl (rotational component) of a 3D Perlin noise field. The result is divergence-free, producing swirling, fluid-like patterns.

**When to use:** Turbulent, flowing patterns. Wind-like effects. Organic directionality.

**Key parameters:** Uses the same Noise Scale, Octaves, and Seed as Perlin mode. The output is the magnitude of the curl vector.

### 6. Reaction-Diffusion (Gray-Scott)
**What it does:** Simulates two chemicals diffusing and reacting on the 3D voxel grid. Produces organic self-organising patterns — spots, stripes, worm-like channels, cellular structures.

**When to use:** Biologically inspired patterns, porous skins, cellular facades, acoustic texturing.

**Key parameters:**
- **Feed Rate** — rate at which chemical A is replenished. Higher = more spots
- **Kill Rate** — rate at which chemical B decays. Adjusting feed/kill together controls pattern type
- **Diffusion A** — how fast chemical A spreads
- **Diffusion B** — how fast chemical B spreads (usually lower than A)
- **RD Iterations** — number of simulation steps. More = more defined patterns

**Performance warning:** Reaction-diffusion is computed iteratively over the entire 3D grid. Keep the grid small (e.g., 10x10x10 to 20x20x20) or it will be very slow.

**Recommended feed/kill presets:**
| Pattern | Feed | Kill |
|---------|------|------|
| Spots | 0.055 | 0.062 |
| Stripes | 0.040 | 0.060 |
| Worms | 0.030 | 0.057 |
| Bubbles | 0.025 | 0.060 |
| Coral | 0.055 | 0.064 |

### 7. Perlin + Gyroid (Composite)
**What it does:** Blends Perlin noise and Gyroid fields together using a selectable blend operation.

**When to use:** Combining structured lattice geometry with organic noise variation. Creates lattices that vary in density or break down in regions.

**Key parameters:**
- **Blend Mode** — how the two fields are combined:
  - **Add** — weighted average (smooth blend)
  - **Multiply** — fields reinforce where both are high
  - **Max (Union)** — keeps whichever is higher
  - **Min (Intersect)** — keeps only where both are high
  - **Smooth Union** — union with rounded transitions
  - **Subtract** — carve one field out of the other
- **Blend Weight** — balance between the two fields (0 = all Perlin, 1 = all Gyroid)

---

## Environmental Field Algorithms

These modes generate density fields driven by architectural and environmental factors. They operate at human/building scale and can be combined with structural fields via Multi-Layer Blend.

### 8. Pathway Field
**What it does:** Generates density based on proximity to curves you pick from the Rhino viewport. Curves represent walkways, corridors, service routes, or any circulation path. The field creates a corridor of influence around each curve.

**When to use:** Carving pedestrian corridors through solid mass, building enclosing walls along pathways, defining circulation-driven structure.

**Key parameters:**
- **Corridor Width** — the radius of full-effect zone around the path centreline (units = Rhino document units)
- **Falloff Distance** — beyond the corridor width, how far the effect fades out
- **Invert** — checked (default): carve corridor through mass. Unchecked: build dense walls near the path
- **Pick Pathway Curves** — select existing Rhino curves. Any curve type works (line, polyline, arc, NURBS)
- **Clear** — remove assigned pathways

**Workflow example:** Draw polylines in Rhino representing ground-floor walkways. Select "Pathway Field", pick the curves, set corridor width to 3m (human width + clearance), falloff to 5m. The voxel field carves clear corridors with gradual densification at the walls.

### 9. Solar Exposure
**What it does:** Creates a gradient field based on simulated sun direction. Voxels facing the sun (projected along the sun vector) get higher density values. No ray casting — uses a fast projection heuristic suitable for real-time interaction.

**When to use:** Generating facades that respond to daylight orientation, creating solar shading patterns, thickening south-facing walls, opening up sun-facing voids.

**Key parameters:**
- **Sun Azimuth (deg)** — compass bearing of the sun (0°=East, 90°=North, 180°=West, 270°=South). Default 135° = NW (afternoon sun in southern hemisphere)
- **Sun Elevation (deg)** — angle above the horizon (0°=horizon, 90°=directly overhead). Default 45° = mid-afternoon

**How it works:** Every voxel's position is projected onto the sun direction vector. The projection distance, normalised by the grid diagonal, becomes the density value. Voxels on the sun-facing side get values near 1.0, those in shadow get values near 0.0.

**Tip:** Combine with Gyroid via Multi-Layer Blend to create a lattice that opens up on the sun-facing side and gets denser on the shaded side.

### 10. View Corridor
**What it does:** Carves a cylindrical void between two picked points — a viewer position and a target position. Preserves sight lines through voxel mass. Voxels on the view axis are removed; those beyond the radius remain solid, with a smooth falloff transition.

**When to use:** Preserving views through a building (ocean views, landmark views), creating light wells, defining visual connections between spaces.

**Key parameters:**
- **Corridor Radius** — radius of the carved cylinder (in document units)
- **Falloff** — distance over which the void transitions back to solid
- **Pick Viewer Point** — click a point in the viewport for the eye/camera position
- **Pick Target Point** — click a point for the look-at target

**Workflow example:** You have a building mass and want to preserve a view to the harbour. Pick a point at the balcony (viewer) and a point at the harbour (target). Set radius to 3–5m, falloff to 3m. The field carves a clean cylinder through the mass with gradual edges.

### 11. Gravity Gradient
**What it does:** Creates a vertical density gradient — heavier at the bottom, lighter at the top (or the reverse). Models structural load distribution through the height of the grid.

**When to use:** Making structures denser at the base (columns/foundations), creating canopy effects (dense at top), or concentrating material at a specific floor level.

**Profile modes:**
| Mode | Name | Effect |
|------|------|--------|
| 0 | Linear (dense base) | Density decreases linearly from bottom to top |
| 1 | Quadratic (heavy base) | Dense base with rapid thinning — like a column |
| 2 | Inverse (dense top) | Top-heavy — canopy or overhang expression |
| 3 | Bell (dense middle) | Concentrated band in the middle — floor plate emphasis |

**Key parameters:**
- **Profile** — dropdown selecting the gradient curve
- **Strength** — how aggressively the gradient deviates from uniform 0.5. At 0 the field is flat; at 2.0 it's strongly polarised

### 12. Multi-Layer Blend
**What it does:** Combines any two field algorithms (modes 0–11) using the same blend operations as the Composite mode. Lets you layer environmental fields with procedural ones.

**When to use:** Solar exposure + Gyroid lattice. Pathway corridors subtracted from Perlin mass. Gravity gradient multiplied with Diamond TPMS. Any combination of two sources.

**Key parameters:**
- **Field A** — dropdown selecting the first source algorithm (0–11)
- **Field B** — dropdown selecting the second source algorithm (0–11)
- **Blend Mode / Blend Weight** — from the Composite panel (shared)

**Example combinations:**
| Field A | Field B | Blend | Result |
|---------|---------|-------|--------|
| Perlin | Gravity | Multiply | Organic mass that's denser at the base |
| Gyroid | Solar | Multiply | Lattice that dissolves on the sun-facing side |
| Pathway | Perlin | Subtract | Noisy mass with clean carved corridors |
| Schwarz-P | View Corridor | Min | Lattice with preserved sight lines |
| Gravity | Diamond | Smooth Union | Structural lattice that merges with solid base |

---

## Growth Algorithms

Iterative agent-based and cellular growth algorithms. All four are pre-computed over the full 3D grid before voxel evaluation (same pattern as Reaction-Diffusion). They produce binary or continuous density fields from emergent processes rather than mathematical functions.

### 13. DLA Growth (Diffusion-Limited Aggregation)
**What it does:** Particles random-walk through the grid. When a particle touches an existing solid cell, it sticks. This produces branching, coral-like, fractal structures that grow outward from seed points.

**When to use:** Organic branching columns, root-like foundations, lightning-tree structures, dendritic facade patterns.

**Key parameters:**
- **Particles** (100–10000, default 2000) — total number of particles released. More = denser growth
- **Stickiness** (0.1–1.0, default 1.0) — probability of sticking on contact. Lower = particles penetrate deeper before sticking, producing sparser branches
- **Growth Bias Z** (-1.0–1.0, default 0.0) — biases random walk direction. Positive = upward growth tendency, negative = downward
- **Seed Placement** — where initial solid cells are placed:
  - Center — single seed at grid center
  - Bottom Center — single seed at bottom-center
  - Bottom Face — entire bottom layer is solid (produces upward forest)
  - Random — scattered random seeds

**Performance:** O(particles × walk_length). Walk length scales with grid size. Keep grid ≤20³ with ≤5000 particles for interactive speed.

### 14. Space Colonization
**What it does:** Scatters "nutrient" attractor points throughout the volume, then grows a branching network from root node(s) toward the nearest attractors. When a branch gets close enough, the attractor is consumed. Produces tree-like structures that efficiently fill a volume.

**When to use:** Structural branching columns, load-path networks, vascular circulation systems, canopy structures, organic space-filling branching.

**Key parameters:**
- **Attractor Density** (0.05–1.0, default 0.3) — fraction of grid cells that contain nutrient attractors. Higher = more targets to grow toward, denser branching
- **Kill Distance** (1–5, default 2) — how close a branch must get to consume an attractor (in cells). Smaller = finer branching
- **Influence Radius** (2–15, default 5) — how far an attractor can influence branch growth direction. Larger = smoother, more directed growth
- **Step Length** (1–3, default 1) — how far a branch grows per step (in cells)
- **Iterations** (10–500, default 200) — number of growth cycles
- **Root Position** — where the tree starts:
  - Bottom Center — single root at bottom-center (classic tree)
  - Center — root at grid center (radial growth)
  - Bottom Corners — root at bottom-center + four bottom corners (forest)
  - Random — single root at random position

**Performance:** O(attractors × frontier_nodes) per iteration. Slower than DLA for large grids. Keep grid ≤15³ with density ≤0.5 for reasonable speed.

### 15. Eden Growth (3D Cellular Automata)
**What it does:** Starts from seed cells and iteratively grows by activating neighbor cells based on birth/survival rules (like 3D Game of Life). Produces blobby organic masses, crystalline structures, or coral-like growth depending on the rule set.

**When to use:** Iterative massing studies, organic form-finding, erosion simulation, blob aggregation, living systems.

**Key parameters:**
- **Birth Threshold** (1–6, default 2) — minimum number of live face-neighbors needed for a dead cell to become alive. Lower = faster, more aggressive growth
- **Survival Min** (0–6, default 1) — minimum live neighbors for a live cell to survive. 0 = cells never die from isolation
- **Survival Max** (1–6, default 6) — maximum live neighbors before a cell dies (overcrowding). 6 = no overcrowding death
- **Iterations** (1–200, default 50) — number of growth cycles
- **Seed Density** (0.01–0.5, default 0.05) — fraction of grid cells initially alive. Higher = more starting points
- **Noise Bias** (0.0–1.0, default 0.0) — how much Perlin noise influences birth probability. At 0 growth is uniform; at 1.0 growth strongly favors noise-bright regions

**Recommended rule presets:**
| Pattern | Birth | Surv Min | Surv Max | Effect |
|---------|-------|----------|----------|--------|
| Blob growth | 2 | 1 | 6 | Organic blobs that expand steadily |
| Conservative | 3 | 2 | 5 | Slow, structured growth |
| Aggressive | 1 | 0 | 6 | Rapid fill, almost no death |
| Coral | 2 | 2 | 4 | Branching with some die-back |
| Crystal | 3 | 3 | 3 | Very constrained, geometric growth |

**Performance:** O(alive_cells × 6) per iteration. Fast for small grids, scales with living population.

### 16. Physarum (Slime Mold)
**What it does:** 3D slime mold simulation. Thousands of agents wander the grid, sensing trail concentration ahead, turning toward higher concentrations, and depositing more trail as they move. Trail decays over time. Produces efficient network structures — the organic analog of minimum spanning trees.

**When to use:** Optimal structural networks, circulation route-finding, efficient material distribution, connecting program nodes with minimum material, organic lattice generation.

**Key parameters:**
- **Agents** (100–10000, default 2000) — number of slime mold agents. More agents = denser network, slower computation
- **Sensor Angle** (10°–90°, default 45°) — angle between forward direction and left/right sensors. Wider = agents explore more broadly
- **Sensor Distance** (1–5, default 3) — how far ahead agents sense trail (in cells). Longer = smoother paths, less local detail
- **Turn Angle** (10°–90°, default 45°) — how sharply agents turn toward trail. Larger = more responsive, tighter curves
- **Deposit Rate** (0.1–5.0, default 1.0) — how much trail each agent deposits per step. Higher = stronger positive feedback, faster network formation
- **Decay Rate** (0.01–0.5, default 0.1) — fraction of trail that evaporates per step. Higher = only the strongest paths survive; lower = more diffuse networks
- **Iterations** (10–500, default 200) — number of simulation steps

**Tuning tips:**
- High deposit + low decay = dense, thick networks
- Low deposit + high decay = sparse, minimal networks
- Small sensor angle + small turn angle = long straight paths
- Large sensor angle + large turn angle = tight, winding networks
- More agents converge faster but produce thicker, less differentiated networks

**Performance:** O(agents × iterations) with per-agent sensing. Significantly slower than static fields. Keep grid ≤15³ with ≤3000 agents for interactive use.

### 17. Mycelium Growth
**What it does:** Simulates fungal hypha growth. Active tips extend forward with slight random deviation, branch probabilistically, and fuse when they meet existing hyphae (anastomosis). Produces dense, interconnected filament networks resembling real fungal mycelium.

**When to use:** Organic branching networks, material distribution systems, structural lattice generation, root-like foundations, facade perforations that connect and reconnect, adaptive circulation networks.

**Key parameters:**
- **Initial Tips** (1–50, default 10) — number of starting growth points. More = denser initial coverage
- **Branch Probability** (0.0–0.3, default 0.05) — chance of a tip splitting each step. Higher = bushier network
- **Branch Angle** (10°–90°, default 45°) — angle of branch from parent direction. Smaller = more parallel growth
- **Turn Rate** (1°–60°, default 15°) — random directional wobble per step. Higher = more winding paths
- **Anastomosis** (0.0–1.0, default 0.5) — probability of fusing when a tip hits existing structure. 1.0 = always fuse, creating loops; 0.0 = never fuse, tips try to find free space
- **Iterations** (10–1000, default 200) — number of growth steps per tip
- **Max Active Tips** (10–2000, default 500) — cap on total simultaneous growing tips. Prevents runaway branching

**Tuning tips:**
- High branch prob + high anastomosis = dense mesh-like network
- Low branch prob + low anastomosis = sparse, tree-like tendrils
- Low turn rate = straight, rigid-looking hyphae
- High turn rate = organic, meandering filaments
- Few initial tips + many iterations = long-range exploration

**Performance:** O(active_tips × iterations). Each tip does constant work per step. Branching increases the active tip count over time. Use Max Active Tips to bound computation.

### Growth Attractors & Repellents (shared across modes 13–17)

All growth algorithms respond to **attractor** and **repellent** geometries assigned via the Growth Display panel. These influence growth direction and probability.

**Controls:**
- **Assign Attractors** — pick one or more Rhino objects (curves, meshes, surfaces, breps, points) that attract growth toward them
- **Clear** — remove all attractor geometries
- **Assign Repellents** — pick objects that repel growth away from them
- **Clear** — remove all repellent geometries
- **Attract Radius** (1–100, default 10) — world-unit distance of influence around attractor geometry
- **Attract Strength** (0.1–3.0, default 1.0) — multiplier on attraction effect
- **Repel Radius** (1–100, default 10) — world-unit distance of influence around repellent geometry
- **Repel Strength** (0.1–3.0, default 1.0) — multiplier on repulsion effect

**How each algorithm uses attractors/repellents:**
| Algorithm | Attractor effect | Repellent effect |
|-----------|-----------------|-----------------|
| DLA | Biases random walk toward attractor | Biases walk away from repellent |
| Space Colonization | Concentrates nutrient points near attractor | Removes nutrients near repellent |
| Eden Growth | Increases birth probability near attractor | Decreases birth probability near repellent |
| Physarum | Seeds initial trail deposits near attractor | (no direct repulsion — agents avoid low trail) |
| Mycelium | Steers active tips toward attractor gradient | Steers tips away from repellent gradient |

**Implementation:** At the start of each compute method, a 3D influence grid is pre-computed by measuring closest-point distance from each grid cell to all attractor/repellent geometries. Values range from -1 (strong repulsion) to +1 (strong attraction). This grid is then sampled during the growth simulation to bias decisions.

### Growth Display & Playback (inside Field Source section, modes 13–17)

When any growth algorithm is selected (modes 13–17), a **Growth Display** sub-panel appears directly below the algorithm's parameter controls within the Field Source section. This keeps display settings co-located with the algorithm they apply to.

#### Display Controls

- **Show Growth Trails** — draw agent walk paths (DLA), branch edges (Space Colonization), or agent movement paths (Physarum) as polylines in the viewport
- **Show Agent Points** — draw stuck particles (DLA), branch nodes (Space Colonization), alive cells (Eden), or current agent positions (Physarum) as points
- **Hide Voxels (Curve Mode)** — suppress the voxel mesh when growth trails/points are visible, giving a clean wireframe view of the growth structure
- **Trail Thickness** (1–8, default 2) — line weight for growth trails
- **Point Size** (2–16, default 4) — dot size for agent/growth points
- **Trail Colour / Point Colour** — colour pickers for each

#### Playback Controls

Each growth algorithm pre-computes frame data during simulation, enabling animated playback of the growth process:

- **Play / Pause** — toggles animated playback. If at the last frame, pressing Play restarts from frame 0
- **Restart** — jumps back to frame 0 and stops playback
- **Speed** (1–10, default 1) — number of frames to advance per timer tick (0.12s)
- **Frame counter** — displays "Frame: N / Total" showing current playback position

**How frame data is stored per algorithm:**

| Algorithm | Mode | What changes per frame |
|-----------|------|----------------------|
| DLA | Cumulative | Particles stick one by one — each frame adds more trails & points |
| Space Colonization | Cumulative | Branches grow per iteration — each frame adds more edges & nodes |
| Eden Growth | Snapshot | Alive set changes each iteration (cells can die) — full state per frame |
| Physarum | Snapshot | Agent positions change each iteration — full state per frame; trails shown at final frame only |
| Mycelium | Cumulative | Tips extend and branch — trails and solid cells accumulate over time |

**Cumulative mode** stores all trails/points in order with per-frame index counts, then slices the list at playback time. Memory-efficient — no duplication.

**Snapshot mode** stores the complete point/trail set at each sampled iteration. Used when the data is not purely additive (cells can die or agents move). Frame count is capped at ~100 by sampling every N-th iteration.

**What each algorithm produces in curve mode:**
| Algorithm | Trails | Points |
|-----------|--------|--------|
| DLA | Random walk paths of particles that stuck | Stuck particle positions |
| Space Colonization | Branch edges (parent → child connections) | All branch node positions |
| Eden Growth | (none — no agents) | Alive cell positions |
| Physarum | Sampled agent movement paths over all iterations | Final agent positions |
| Mycelium | Hypha filament paths (one per branch) | All solid cell positions |

---

## Existing Features (Inherited from v01)

All features from the original voxel-boids tool are preserved:

- **Bounds Geometry** — assign a Rhino object whose bounding box defines the grid extent; cell sizes are auto-computed from bbox dimensions / grid counts. Overrides manual voxel size sliders and grid origin while active
- **Grid Dimensions** — cell count and cell size per axis
- **Voxel Rotation** — density-driven rotation on two independent axes
- **Voxel Density Scale** — shrink low-density voxels (neighbour-aware)
- **Noise Parameters** — scale, threshold, octaves, seed (used by Perlin, Curl, and Composite modes)
- **Hollow Shell** — remove interior voxels
- **Attractors** — point, curve, and geometry attractors that boost density
- **Base Geometry** — concentrate or carve voxels around assigned objects
- **Custom Voxel Geometry** — replace box voxels with any mesh/brep shape
- **Edge Boids** — agent-based pathfinding on exposed voxel surfaces
- **Pipe Mesh** — extrude tubes along boid trails
- **Melt / Blend** — Laplacian smoothing to merge voxels and pipes
- **Display** — vertex colours, edge wireframe, bounding box, colour pickers
- **Baking** — mesh, brep, trail, and melt output to the Rhino document

---

## Performance Notes

- TPMS fields (Gyroid, Schwarz-P, Diamond) are evaluated per-voxel with trig functions — comparable speed to Perlin
- SDF requires distance queries to geometry — scales with number of SDF objects and grid size
- Curl noise evaluates 18 Perlin noise samples per voxel (6 finite differences x 3 channels) — about 18x slower than plain Perlin
- Reaction-diffusion is iterative — O(grid_x * grid_y * grid_z * iterations). Keep grids small
- **Pathway** uses `ClosestPoint` on each curve per voxel — scales with number of curves. Keep pathway curve count low for large grids
- **Solar** is extremely fast — just a dot product per voxel, no geometry queries
- **View Corridor** is fast — one projection per voxel, no geometry queries
- **Gravity** is the fastest field — one height lookup per voxel
- **Multi-Layer** evaluates two fields per voxel then blends — roughly 2x the cost of either sub-field
- The dropdown triggers a full recompute when changed. Display-only parameters (rotation, scale, colour) remain cheap

## Ideas to Explore
- [ ] Animate sun azimuth over time to simulate daylight study
- [ ] Wind field from CFD data (import as point cloud with vectors)
- [ ] Program zones: assign different density/field to different spatial regions
- [ ] Acoustic field: distance from sound sources with frequency-based absorption
- [ ] Structural topology optimisation: iterative density redistribution based on load paths
- [ ] Terrain-responsive field: sample topography mesh height as a density modifier
- [ ] Blend 3+ fields simultaneously (weighted stack)
- [ ] Export environmental field values as a coloured point cloud for analysis
- [ ] Use the curl noise vector direction (not just magnitude) to orient custom voxel geometry
- [ ] Layer multiple TPMS types at different scales
- [ ] Use reaction-diffusion patterns to modulate wall thickness of a TPMS lattice
- [ ] Add Neovius and Lidinoid TPMS surfaces
