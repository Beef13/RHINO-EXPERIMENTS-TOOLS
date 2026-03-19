"""Point and vector transformation utilities."""
import math


def translate(point, vector):
    """Translate a point by a vector."""
    return (
        point[0] + vector[0],
        point[1] + vector[1],
        point[2] + vector[2],
    )


def scale_from_origin(point, factor):
    """Scale a point relative to the world origin."""
    return (
        point[0] * factor,
        point[1] * factor,
        point[2] * factor,
    )


def scale_from_point(point, center, factor):
    """Scale a point relative to a center point."""
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    dz = point[2] - center[2]
    return (
        center[0] + dx * factor,
        center[1] + dy * factor,
        center[2] + dz * factor,
    )


def rotate_z(point, angle_radians, center=(0, 0, 0)):
    """Rotate a point around the Z axis through a center point.

    Args:
        point: (x, y, z)
        angle_radians: rotation angle in radians
        center: rotation center (x, y, z)

    Returns:
        rotated (x, y, z)
    """
    cos_a = math.cos(angle_radians)
    sin_a = math.sin(angle_radians)
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    return (
        center[0] + dx * cos_a - dy * sin_a,
        center[1] + dx * sin_a + dy * cos_a,
        point[2],
    )


def normalize(vector):
    """Normalize a 3D vector to unit length. Returns zero vector if magnitude is 0."""
    mag = math.sqrt(vector[0]**2 + vector[1]**2 + vector[2]**2)
    if mag == 0:
        return (0, 0, 0)
    return (vector[0] / mag, vector[1] / mag, vector[2] / mag)


def lerp_point(a, b, t):
    """Linear interpolation between two 3D points.

    Args:
        a, b: (x, y, z) points
        t: parameter (0.0 = a, 1.0 = b)

    Returns:
        interpolated (x, y, z)
    """
    return (
        a[0] + t * (b[0] - a[0]),
        a[1] + t * (b[1] - a[1]),
        a[2] + t * (b[2] - a[2]),
    )


def remap(value, src_min, src_max, dst_min, dst_max):
    """Remap a value from one range to another.

    Args:
        value: input value
        src_min, src_max: source range
        dst_min, dst_max: destination range

    Returns:
        remapped value (not clamped)
    """
    if src_max == src_min:
        return dst_min
    t = (value - src_min) / (src_max - src_min)
    return dst_min + t * (dst_max - dst_min)
