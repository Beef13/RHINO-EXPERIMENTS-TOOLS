"""Attractor functions for deforming point fields based on distance."""
import math


def distance_2d(a, b):
    """Euclidean distance between two points in XY (ignores Z)."""
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)


def distance_3d(a, b):
    """Euclidean distance between two points in 3D."""
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def falloff_linear(distance, radius):
    """Linear falloff: 1 at distance=0, 0 at distance>=radius."""
    if radius <= 0:
        return 0.0
    t = 1.0 - distance / radius
    return max(0.0, t)


def falloff_inverse(distance, radius):
    """Inverse falloff: 1/(1 + distance/radius). Never reaches zero."""
    if radius <= 0:
        return 0.0
    return 1.0 / (1.0 + distance / radius)


def falloff_gaussian(distance, radius):
    """Gaussian (bell curve) falloff. Sigma is radius/3 so ~99% of
    influence is within the radius."""
    if radius <= 0:
        return 0.0
    sigma = radius / 3.0
    return math.exp(-(distance * distance) / (2.0 * sigma * sigma))


def point_attractor_z(point, attractor, radius, max_displacement):
    """Displace a point in Z based on distance to an attractor.

    Args:
        point: (x, y, z) tuple
        attractor: (x, y, z) attractor position
        radius: influence radius
        max_displacement: Z displacement at distance=0

    Returns:
        (x, y, z) tuple with modified Z
    """
    dist = distance_2d(point, attractor)
    t = falloff_linear(dist, radius)
    return (point[0], point[1], point[2] + t * max_displacement)


def multi_attractor_z(point, attractors, radius, max_displacement):
    """Displace a point in Z based on multiple attractors (additive).

    Args:
        point: (x, y, z) tuple
        attractors: list of (x, y, z) attractor positions
        radius: shared influence radius
        max_displacement: Z displacement per attractor at distance=0

    Returns:
        (x, y, z) tuple with accumulated Z displacement
    """
    total_z = point[2]
    for att in attractors:
        dist = distance_2d(point, att)
        t = falloff_linear(dist, radius)
        total_z += t * max_displacement
    return (point[0], point[1], total_z)
