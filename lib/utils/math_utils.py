"""Math utilities that don't depend on Rhino — pure Python."""
import math


def clamp(value, min_val, max_val):
    """Clamp a value to a range."""
    return max(min_val, min(max_val, value))


def lerp(a, b, t):
    """Linear interpolation between two scalar values."""
    return a + t * (b - a)


def inverse_lerp(a, b, value):
    """Inverse linear interpolation — returns t such that lerp(a, b, t) == value."""
    if a == b:
        return 0.0
    return (value - a) / (b - a)


def remap(value, src_min, src_max, dst_min, dst_max):
    """Remap a value from one range to another."""
    t = inverse_lerp(src_min, src_max, value)
    return lerp(dst_min, dst_max, t)


def smooth_step(edge0, edge1, x):
    """Hermite interpolation (smooth step) between 0 and 1."""
    t = clamp((x - edge0) / (edge1 - edge0) if edge1 != edge0 else 0.0, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def degrees_to_radians(deg):
    """Convert degrees to radians."""
    return deg * math.pi / 180.0


def radians_to_degrees(rad):
    """Convert radians to degrees."""
    return rad * 180.0 / math.pi


def map_range_clamped(value, src_min, src_max, dst_min, dst_max):
    """Remap with clamping to the destination range."""
    t = clamp(inverse_lerp(src_min, src_max, value), 0.0, 1.0)
    return lerp(dst_min, dst_max, t)


def almost_equal(a, b, tolerance=1e-9):
    """Check if two floats are approximately equal."""
    return abs(a - b) <= tolerance


def weighted_average(values, weights):
    """Compute a weighted average of values.

    Args:
        values: list of numbers
        weights: list of weights (same length as values)

    Returns:
        weighted average, or 0.0 if total weight is zero
    """
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_weight
