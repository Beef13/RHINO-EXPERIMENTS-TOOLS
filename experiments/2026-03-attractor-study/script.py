"""Compare attractor falloff functions on a point field."""
import sys, os

_here = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.normpath(os.path.join(_here, "..", "..", "lib"))
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import rhinoscriptsyntax as rs
import scriptcontext as sc

from geometry.attractors import distance_2d, falloff_linear, falloff_inverse, falloff_gaussian
import math


def make_point_field(center, radius, count):
    """Create a circular field of random points on the XY plane."""
    import random
    points = []
    cx, cy = center[0], center[1]
    for _ in range(count):
        angle = random.uniform(0, 2 * math.pi)
        r = radius * math.sqrt(random.uniform(0, 1))
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        points.append((x, y, 0))
    return points


def run():
    attractor = rs.GetPoint("Pick attractor point")
    if attractor is None:
        return

    falloff_name = rs.GetString(
        "Falloff type",
        "linear",
        ["linear", "inverse", "gaussian"]
    )
    if falloff_name is None:
        return

    falloff_funcs = {
        "linear": falloff_linear,
        "inverse": falloff_inverse,
        "gaussian": falloff_gaussian,
    }
    falloff_fn = falloff_funcs.get(falloff_name, falloff_linear)

    point_count = 500
    field_radius = 40.0
    influence_radius = 30.0
    max_height = 15.0

    field = make_point_field((0, 0, 0), field_radius, point_count)

    layer_name = "Attractor_{}".format(falloff_name)
    rs.AddLayer(layer_name)

    rs.EnableRedraw(False)
    try:
        for pt in field:
            dist = distance_2d(pt, attractor)
            t = falloff_fn(dist, influence_radius)
            z = t * max_height
            new_pt = (pt[0], pt[1], z)
            obj = rs.AddPoint(new_pt)
            rs.ObjectLayer(obj, layer_name)
    finally:
        rs.EnableRedraw(True)

    print("Created {} points with {} falloff".format(point_count, falloff_name))


if __name__ == "__main__":
    run()
