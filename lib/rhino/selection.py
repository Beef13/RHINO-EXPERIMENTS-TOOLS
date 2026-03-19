"""Helpers for selecting and filtering Rhino objects."""
import rhinoscriptsyntax as rs


def get_curves(prompt="Select curves"):
    """Prompt user to select one or more curves. Returns list of GUIDs or empty list."""
    ids = rs.GetObjects(prompt, rs.filter.curve)
    return list(ids) if ids else []


def get_points(prompt="Select points"):
    """Prompt user to select one or more point objects. Returns list of GUIDs or empty list."""
    ids = rs.GetObjects(prompt, rs.filter.point)
    return list(ids) if ids else []


def get_meshes(prompt="Select meshes"):
    """Prompt user to select one or more meshes. Returns list of GUIDs or empty list."""
    ids = rs.GetObjects(prompt, rs.filter.mesh)
    return list(ids) if ids else []


def get_surfaces(prompt="Select surfaces"):
    """Prompt user to select one or more surfaces. Returns list of GUIDs or empty list."""
    ids = rs.GetObjects(prompt, rs.filter.surface)
    return list(ids) if ids else []


def filter_by_layer(guids, layer_name):
    """Filter a list of GUIDs to only those on a specific layer."""
    return [g for g in guids if rs.ObjectLayer(g) == layer_name]


def filter_by_name(guids, name):
    """Filter a list of GUIDs to only those with a specific object name."""
    return [g for g in guids if rs.ObjectName(g) == name]
