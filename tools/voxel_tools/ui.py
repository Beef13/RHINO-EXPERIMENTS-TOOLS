"""Rhino command UI for voxel tools."""
import rhinoscriptsyntax as rs
from script import VoxelGrid, draw_voxels


def run():
    center = rs.GetPoint("Pick sphere center for voxel fill")
    if center is None:
        return

    radius = rs.GetReal("Sphere radius", 15.0, 1.0, 100.0)
    if radius is None:
        return

    voxel_size = rs.GetReal("Voxel size", 2.0, 0.1, 20.0)
    if voxel_size is None:
        return

    grid_extent = int(radius * 2.5 / voxel_size) + 1
    origin = (
        center[0] - radius * 1.25,
        center[1] - radius * 1.25,
        center[2] - radius * 1.25,
    )

    grid = VoxelGrid(origin, voxel_size, grid_extent, grid_extent, grid_extent)
    grid.fill_sphere(center, radius)
    draw_voxels(grid, "VoxelSphere")


if __name__ == "__main__":
    run()
