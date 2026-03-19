# Voxel Tools

## What It Does
Creates axis-aligned voxel grids and fills them based on geometric conditions (e.g., sphere intersection). Draws filled voxels as boxes in Rhino.

## Usage
Run `ui.py` in Rhino:
1. Pick a sphere center
2. Set radius and voxel size
3. Voxels appear on the `VoxelSphere` layer

## Limitations
- Boxes are individual Rhino objects — gets slow above ~5000 voxels
- No mesh output yet (joining boxes into a single mesh would be faster)
- Only sphere fill implemented so far

## Ideas
- [ ] Fill from mesh boundary (inside/outside test)
- [ ] Fill from point cloud density
- [ ] Output as joined mesh instead of individual boxes
- [ ] Colour voxels by density or distance
