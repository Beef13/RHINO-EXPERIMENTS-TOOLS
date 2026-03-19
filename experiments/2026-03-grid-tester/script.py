"""Generate a point grid and deform it with an attractor point."""
import sys, os

_here = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.normpath(os.path.join(_here, "..", "..", "lib"))
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import rhinoscriptsyntax as rs
import scriptcontext as sc

from geometry.attractors import point_attractor_z
import math


def make_grid(origin, x_count, y_count, spacing):
    """Create a flat grid of Point3d tuples."""
    points = []
    ox, oy, oz = origin
    for i in range(x_count):
        for j in range(y_count):
            x = ox + i * spacing
            y = oy + j * spacing
            points.append((x, y, oz))
    return points


def run():
    attractor = rs.GetPoint("Pick attractor point")
    if attractor is None:
        return

    x_count = 20
    y_count = 20
    spacing = 2.0
    max_height = 10.0
    radius = 30.0

    origin = (0, 0, 0)
    grid = make_grid(origin, x_count, y_count, spacing)

    rs.EnableRedraw(False)
    try:
        for pt in grid:
            deformed = point_attractor_z(pt, attractor, radius, max_height)
            rs.AddPoint(deformed)
    finally:
        rs.EnableRedraw(True)

    print("Grid created: {}x{} = {} points".format(x_count, y_count, len(grid)))


if __name__ == "__main__":
    run()
