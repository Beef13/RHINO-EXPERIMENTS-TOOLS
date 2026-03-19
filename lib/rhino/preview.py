"""Preview helpers — draw temporary geometry for visualisation."""
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino.Geometry as rg


PREVIEW_LAYER = "_Preview"


def preview_points(points, layer=None):
    """Add points to a preview layer. Returns list of GUIDs.

    Args:
        points: list of (x, y, z) tuples
        layer: layer name (default: _Preview)
    """
    layer = layer or PREVIEW_LAYER
    if not rs.IsLayer(layer):
        rs.AddLayer(layer, color=(255, 100, 0))

    guids = []
    rs.EnableRedraw(False)
    try:
        for pt in points:
            g = rs.AddPoint(pt)
            if g:
                rs.ObjectLayer(g, layer)
                guids.append(g)
    finally:
        rs.EnableRedraw(True)
    return guids


def preview_lines(line_pairs, layer=None):
    """Add lines to a preview layer. Returns list of GUIDs.

    Args:
        line_pairs: list of (start, end) tuples, each point is (x, y, z)
        layer: layer name (default: _Preview)
    """
    layer = layer or PREVIEW_LAYER
    if not rs.IsLayer(layer):
        rs.AddLayer(layer, color=(255, 100, 0))

    guids = []
    rs.EnableRedraw(False)
    try:
        for start, end in line_pairs:
            g = rs.AddLine(start, end)
            if g:
                rs.ObjectLayer(g, layer)
                guids.append(g)
    finally:
        rs.EnableRedraw(True)
    return guids


def clear_preview(layer=None):
    """Delete all objects on the preview layer."""
    layer = layer or PREVIEW_LAYER
    if rs.IsLayer(layer):
        objects = rs.ObjectsByLayer(layer)
        if objects:
            rs.DeleteObjects(objects)
