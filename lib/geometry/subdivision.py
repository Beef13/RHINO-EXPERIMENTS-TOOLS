"""Subdivision utilities for splitting geometry into smaller parts."""
import math


def subdivide_line(start, end, segments):
    """Divide a line into equal segments.

    Args:
        start: (x, y, z) start point
        end: (x, y, z) end point
        segments: number of segments

    Returns:
        list of (x, y, z) points including start and end
    """
    if segments < 1:
        return [start, end]
    points = []
    for i in range(segments + 1):
        t = float(i) / segments
        x = start[0] + t * (end[0] - start[0])
        y = start[1] + t * (end[1] - start[1])
        z = start[2] + t * (end[2] - start[2])
        points.append((x, y, z))
    return points


def midpoint(a, b):
    """Return the midpoint of two 3D points."""
    return (
        (a[0] + b[0]) / 2.0,
        (a[1] + b[1]) / 2.0,
        (a[2] + b[2]) / 2.0,
    )


def subdivide_triangle(v0, v1, v2):
    """Subdivide a triangle into 4 triangles at edge midpoints.

    Args:
        v0, v1, v2: triangle vertices as (x, y, z)

    Returns:
        list of 4 triangles, each a tuple of 3 vertices
    """
    m01 = midpoint(v0, v1)
    m12 = midpoint(v1, v2)
    m20 = midpoint(v2, v0)
    return [
        (v0, m01, m20),
        (m01, v1, m12),
        (m20, m12, v2),
        (m01, m12, m20),
    ]


def subdivide_mesh_triangles(triangles, iterations=1):
    """Recursively subdivide a list of triangles.

    Args:
        triangles: list of (v0, v1, v2) tuples
        iterations: number of subdivision passes

    Returns:
        list of subdivided triangles
    """
    current = list(triangles)
    for _ in range(iterations):
        subdivided = []
        for tri in current:
            subdivided.extend(subdivide_triangle(tri[0], tri[1], tri[2]))
        current = subdivided
    return current
