"""Baking helpers — add geometry to the document on organised layers."""
import rhinoscriptsyntax as rs
import scriptcontext as sc


def bake_points(points, layer_name, color=None):
    """Add a list of points to the document on a specific layer.

    Args:
        points: list of (x, y, z) tuples
        layer_name: target layer
        color: optional (r, g, b) object colour

    Returns:
        list of created GUIDs
    """
    if not rs.IsLayer(layer_name):
        rs.AddLayer(layer_name)

    guids = []
    rs.EnableRedraw(False)
    try:
        for pt in points:
            g = rs.AddPoint(pt)
            if g:
                rs.ObjectLayer(g, layer_name)
                if color:
                    rs.ObjectColor(g, color)
                guids.append(g)
    finally:
        rs.EnableRedraw(True)
    return guids


def bake_curves(curve_data, layer_name, color=None):
    """Add polylines to the document.

    Args:
        curve_data: list of point lists, each defining a polyline
        layer_name: target layer
        color: optional (r, g, b) object colour

    Returns:
        list of created GUIDs
    """
    if not rs.IsLayer(layer_name):
        rs.AddLayer(layer_name)

    guids = []
    rs.EnableRedraw(False)
    try:
        for pts in curve_data:
            if len(pts) >= 2:
                g = rs.AddPolyline(pts)
                if g:
                    rs.ObjectLayer(g, layer_name)
                    if color:
                        rs.ObjectColor(g, color)
                    guids.append(g)
    finally:
        rs.EnableRedraw(True)
    return guids


def bake_meshes(meshes, layer_name):
    """Add RhinoCommon Mesh objects to the document.

    Args:
        meshes: list of Rhino.Geometry.Mesh objects
        layer_name: target layer

    Returns:
        list of created GUIDs
    """
    if not rs.IsLayer(layer_name):
        rs.AddLayer(layer_name)

    layer_index = sc.doc.Layers.FindByFullPath(layer_name, -1)
    attr = sc.doc.CreateDefaultAttributes()
    if layer_index >= 0:
        attr.LayerIndex = layer_index

    guids = []
    for mesh in meshes:
        guid = sc.doc.Objects.AddMesh(mesh, attr)
        if guid:
            guids.append(guid)

    sc.doc.Views.Redraw()
    return guids
