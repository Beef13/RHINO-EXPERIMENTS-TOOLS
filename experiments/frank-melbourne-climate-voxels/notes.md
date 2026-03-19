# Melbourne Climate Voxel Attractor — V5

## Goal
Generate climate-responsive 3D voxel massing for Melbourne using real EPW weather data, Perlin noise, and solar position modelling. The tool links building density to actual radiation and temperature profiles, producing architecturally-scaled voxel envelopes that respond to sun angle, season, and site geometry.

## How to Run
1. Open Rhino 8
2. `RunPythonScript` → select `script.py`
3. The script looks for a Melbourne EPW file at a hardcoded path; if not found it prompts for one (optional — defaults work without it)
4. The Eto dialog opens with live preview in the viewport
5. Optionally pick site geometry (brep or mesh) to constrain the voxel field
6. Adjust sliders, run the optimizer, then Bake to commit geometry to layers

## Architecture

Single-file script with the following components:

| Component | Role |
|-----------|------|
| `solar_position()` | Computes azimuth and altitude for Melbourne (lat -37.8°) at any month/hour using solar declination equations |
| `sun_vec_from_angles()` | Converts solar az/alt to a Rhino `Vector3d` pointing from sun toward scene (for dot-product exposure) |
| `PerlinNoise` | 3D gradient noise with permutation table and octave layering (4 octaves default) |
| `parse_epw()` / `normalise_profiles()` | Reads EPW weather files, extracts monthly GHR, DNR, DHR, and temperature, normalises to 0–1 |
| `get_climate_factors()` | Converts normalised climate data into noise modulation parameters (amplitude, smoothness, height_mult, dir_bias) |
| `compute_mask()` | Pre-computes containment mask for brep (point-inside test) or mesh (vertex density extraction) — cached between runs |
| `generate_voxels()` | Core generator — samples Perlin noise modulated by climate factors, solar exposure, and containment mask |
| `build_combined_mesh()` | Batches all voxels into a single vertex-coloured mesh (box per voxel, density-mapped colour) |
| `find_peaks()` | 26-neighbour local maxima detection for attractor peak markers |
| `bake_final()` | Commits geometry to organised sublayers under `CLIMATE_VOXEL` with metadata text dots |
| `SliderNumPair` | Synced slider + textbox widget for float parameters |
| `ArchInput` | Textbox widget for architectural dimensions in mm with auto mm→m conversion |
| `AttractorGUI` | Full Eto dialog — all controls, live preview loop, simulation runner, view navigation |

## Modes

| # | Mode | Behaviour |
|---|------|-----------|
| 1 | Standard Voxel Culling | Voxels below threshold are removed; above threshold kept at full scale |
| 2 | Site Boundary Envelope | Requires picked geometry; voxels constrained to brep/mesh interior |
| 3 | Adaptive Sizing (Porosity) | Voxels scale between 0.2–1.0 based on density; more voxels kept but vary in size |
| 4 | Custom Sun Vector | Pick a line in the scene to define a manual sun direction instead of auto-computed solar position |

## Parameters

### Architectural Grid (mm input)

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| X / Y voxel size | 100–30,000 mm | 3200 mm | Structural bay / module width |
| Floor height (Z) | 100–30,000 mm | 3200 mm | Floor-to-floor height per voxel layer |
| Floor count | 1+ (blank = auto) | auto | Number of Z layers; auto-derived from geometry height |
| XY Preset | dropdown | 3200 mm | Quick-set to common bays: 1600, 3200, 6000, 6400, 9000, 9600 mm |
| Z Preset | dropdown | 3200 mm | Quick-set to common heights: 1600, 2700, 3000, 3200, 4000, 4500, 6400 mm |

### Noise & Climate

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Climate Month | Annual / Jan–Dec | Annual | Selects which month's EPW profile modulates the noise |
| Climate Sensitivity | 0.0–1.0 | 0.60 | Blend between pure noise (0) and fully climate-driven amplitude/bias (1) |
| Noise Frequency | 0.01–0.30 | 0.08 | Blob size — low = large blobs, high = fine grain. At 3.2m voxels 0.08 ≈ ~13m blobs |
| Density Threshold | 0.10–0.80 | 0.40 | Cutoff — voxels below this are culled. 0.40 keeps ~50% |

### Solar Position

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Hour of day | 6–18 | 12 (noon) | Solar time for Melbourne position calculation |
| Sun Influence | 0.0–0.70 | 0.20 | How much solar exposure shifts density. 0 = none, 0.70 = strong sun-side clustering |
| Daily Avg Sun | button | — | Computes irradiance-weighted average vector across all daylight hours (sin(altitude) weighting) |

### Optimization (Seed Search)

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Hot target | 0–70% | 25% | Target proportion of high-density (>0.75) voxels |
| Mid target | 0–80% | 45% | Target proportion of mid-density (0.5–0.75) voxels |
| Cool | auto | 30% | Remainder — open/shaded zones |
| Max iterations | 1+ | 30 | Number of random seeds to test |
| Stop score | 0.60–1.0 | 0.85 | Early-stop threshold — simulation halts when score reaches this |
| Optimize time | checkbox | off | When on, also sweeps hours 6–18 per iteration to find best seed+time combo |

## Climate Data Integration

The EPW parser extracts four monthly metrics:
- **GHR** (Global Horizontal Radiation) — scales noise amplitude
- **DNR** (Direct Normal Radiation) — adds directional bias to noise sampling
- **DHR** (Diffuse Horizontal Radiation) — controls pattern smoothness
- **Temperature** — modulates height multiplier

Climate sensitivity blends between neutral (all factors = 1.0) and fully data-driven modulation. At sensitivity = 0, the EPW data is ignored entirely.

## Solar Model

Solar position is calculated analytically for Melbourne (lat -37.8136°):
- Declination from day-of-year (each month uses its mid-month representative day)
- Hour angle from solar time (15° per hour from noon)
- Altitude via spherical trigonometry
- Azimuth via inverse cosine with afternoon correction

The resulting sun vector is used for dot-product exposure: each voxel's position relative to the grid centre is dotted with the incoming sun direction. Positive dot = sunlit face, negative = shaded.

## Colour Gradient

Density is mapped to a blue → teal → orange → red gradient:
- 0.0–0.5: blue to teal (cool/shaded zones)
- 0.5–0.75: teal to orange (transitional)
- 0.75–1.0: orange to red (hot/solar-exposed zones)

## Bake Output

Geometry is organised under a `CLIMATE_VOXEL` parent layer:

| Sublayer | Content |
|----------|---------|
| `00_Site_Boundary` | Polyline outline of the grid footprint |
| `01_Voxel_Low` | Mesh of voxels with density 0.0–0.55 |
| `02_Voxel_Med` | Mesh of voxels with density 0.55–0.75 |
| `03_Voxel_High` | Mesh of voxels with density 0.75–1.0 |
| `04_Attractor_Peaks` | Point objects at local density maxima |
| `05_Metadata` | Text dot with month, voxel count, peak count, GHR, temperature, seed |
| `06_Heat_Legend` | Vertical colour gradient strip + plan heat map (max density per XY column) |

## Sticky Export

After baking, the following data is written to `sc.sticky` for downstream scripts:
- `climate_density_grid` — 2D max-density grid (plan projection)
- `climate_grid_size` — (nx, ny, nz)
- `climate_cell_size` — (sx, sy, sz)
- `climate_origin` — (x, y, z)
- `climate_attractor_pts` — list of peak Point3d objects
- `climate_voxels` — list of (ix, iy, iz, density) tuples
- `climate_factors` — dict of climate modulation values

## Mesh Mapping Modes

When site geometry is a mesh with vertex colours:
- **Replace with Climate** — containment only; density from noise + climate
- **Modulate Original** — multiplies noise density by the mesh's luminance values, preserving original colour intensity as a weighting factor

## Auto-Detection Features

- **Unit detection**: if picked geometry's bounding box width > 5000, assumes mm model; otherwise meters
- **Floor count suggestion**: auto-derived from geometry Z height / floor height
- **Voxel count guard**: warns if estimated grid cells exceed 8000 (MAX_VOXELS)

## View Navigation

Built-in viewport controls in the dialog:
- Orbit left/right (15°), tilt up/down (10°)
- Preset views: Top, Front, ISO (NE isometric)
- Frame: zoom to fit the current voxel preview

## Performance Notes
- Containment mask (brep point-inside / mesh density extraction) is cached between slider changes; only invalidated when voxel size or geometry changes
- Mesh vertex colour extraction samples up to 20 vertices to detect uniform-colour meshes (skips colour mapping if all same)
- Box meshes use 8 vertices / 6 quad faces per voxel, batched into a single mesh
- Simulation runs on main thread with `Rhino.RhinoApp.Wait()` to keep UI responsive (no background threads)
- MAX_VOXELS = 8000 soft limit — warns but does not hard-block

## Known Limitations
- EPW file path is hardcoded to a specific local directory; falls back to file picker
- Single-threaded — large grids or high iteration counts block the UI
- No undo for baked geometry beyond Rhino's built-in undo
- Dialog must be closed and reopened to pick new geometry (state is transferred to a fresh dialog instance)
- Solar model is simplified (no atmospheric refraction, equation of time, or longitude correction)
- Mesh mapping luminance uses BT.601 coefficients (0.299R + 0.587G + 0.114B)

## Ideas to Explore
- [ ] Multi-month comparison — bake side-by-side for summer vs winter
- [ ] Animated solar sweep — cycle through hours to visualise shadow response
- [ ] Gradient-based structural sizing — map density to column thickness or slab depth
- [ ] Export density grid to CSV for external analysis
- [ ] Marching cubes smooth isosurface as alternative to box voxels
- [ ] Wind data integration from EPW (wind speed/direction as additional attractor)
- [ ] Daylight autonomy proxy — combine GHR with obstruction from neighbouring voxels
- [ ] Save/load parameter presets to JSON
