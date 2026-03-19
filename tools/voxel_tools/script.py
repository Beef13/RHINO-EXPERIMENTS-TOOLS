"""Voxel grid operations — create, fill, and visualise voxel grids."""
import sys, os

_here = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.normpath(os.path.join(_here, "..", "..", "lib"))
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import rhinoscriptsyntax as rs
import Rhino.Geometry as rg
import scriptcontext as sc

import math


class VoxelGrid(object):
    """A simple axis-aligned voxel grid stored as a set of (i,j,k) indices."""

    def __init__(self, origin, voxel_size, nx, ny, nz):
        self.origin = origin
        self.voxel_size = voxel_size
        self.nx = nx
        self.ny = ny
        self.nz = nz
        self.filled = set()

    def fill(self, i, j, k):
        if 0 <= i < self.nx and 0 <= j < self.ny and 0 <= k < self.nz:
            self.filled.add((i, j, k))

    def clear(self, i, j, k):
        self.filled.discard((i, j, k))

    def voxel_center(self, i, j, k):
        s = self.voxel_size
        ox, oy, oz = self.origin
        return (
            ox + (i + 0.5) * s,
            oy + (j + 0.5) * s,
            oz + (k + 0.5) * s,
        )

    def fill_sphere(self, center, radius):
        """Fill all voxels whose centres fall within a sphere."""
        s = self.voxel_size
        for i in range(self.nx):
            for j in range(self.ny):
                for k in range(self.nz):
                    vc = self.voxel_center(i, j, k)
                    dx = vc[0] - center[0]
                    dy = vc[1] - center[1]
                    dz = vc[2] - center[2]
                    if math.sqrt(dx*dx + dy*dy + dz*dz) <= radius:
                        self.filled.add((i, j, k))


def draw_voxels(grid, layer_name="Voxels"):
    """Add a box for each filled voxel to the Rhino document."""
    rs.AddLayer(layer_name)
    s = grid.voxel_size

    rs.EnableRedraw(False)
    try:
        for (i, j, k) in grid.filled:
            if sc.escape_test(False):
                print("Cancelled by user")
                break
            cx, cy, cz = grid.voxel_center(i, j, k)
            corners = [
                (cx - s/2, cy - s/2, cz - s/2),
                (cx + s/2, cy + s/2, cz + s/2),
            ]
            box = rs.AddBox(rs.BoundingBox([corners[0], corners[1]]))
            if box:
                rs.ObjectLayer(box, layer_name)
    finally:
        rs.EnableRedraw(True)

    print("Drew {} voxels".format(len(grid.filled)))
