"""Data conversion between Rhino types, tuples, and common formats."""


def point3d_to_tuple(pt):
    """Convert a RhinoCommon Point3d to a plain (x, y, z) tuple."""
    return (pt.X, pt.Y, pt.Z)


def tuple_to_point3d(t):
    """Convert an (x, y, z) tuple to a RhinoCommon Point3d.
    Import Rhino.Geometry lazily to avoid errors outside Rhino.
    """
    import Rhino.Geometry as rg
    return rg.Point3d(t[0], t[1], t[2])


def points_to_csv(points, filepath):
    """Write a list of (x, y, z) points to a CSV file.

    Args:
        points: list of (x, y, z) tuples
        filepath: output file path
    """
    with open(filepath, "w") as f:
        f.write("x,y,z\n")
        for pt in points:
            f.write("{},{},{}\n".format(pt[0], pt[1], pt[2]))


def csv_to_points(filepath):
    """Read points from a CSV file with x,y,z columns.

    Returns:
        list of (float, float, float) tuples
    """
    points = []
    with open(filepath, "r") as f:
        lines = f.readlines()
    for line in lines[1:]:  # skip header
        parts = line.strip().split(",")
        if len(parts) >= 3:
            points.append((float(parts[0]), float(parts[1]), float(parts[2])))
    return points


def flatten_nested_list(nested):
    """Flatten a list of lists into a single list."""
    result = []
    for item in nested:
        if isinstance(item, (list, tuple)):
            result.extend(flatten_nested_list(item))
        else:
            result.append(item)
    return result
