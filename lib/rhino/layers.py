"""Layer management helpers for Rhino."""
import rhinoscriptsyntax as rs
import System.Drawing


def ensure_layer(name, color=None, parent=None):
    """Create a layer if it doesn't exist. Optionally set colour and parent.

    Args:
        name: layer name
        color: (r, g, b) tuple or None
        parent: parent layer name or None

    Returns:
        layer name
    """
    full_name = "{}::{}".format(parent, name) if parent else name
    if not rs.IsLayer(full_name):
        rs.AddLayer(name, color=color, parent=parent)
    elif color:
        rs.LayerColor(full_name, color)
    return full_name


def clear_layer(name):
    """Delete all objects on a layer without deleting the layer itself."""
    if not rs.IsLayer(name):
        return
    objects = rs.ObjectsByLayer(name)
    if objects:
        rs.DeleteObjects(objects)


def set_layer_visible(name, visible=True):
    """Show or hide a layer."""
    if rs.IsLayer(name):
        rs.LayerVisible(name, visible)


def create_layer_tree(base_name, sub_layers, color_map=None):
    """Create a parent layer with multiple child layers.

    Args:
        base_name: parent layer name
        sub_layers: list of child layer names
        color_map: optional dict mapping child names to (r, g, b) colours

    Returns:
        dict mapping child names to full layer paths
    """
    ensure_layer(base_name)
    result = {}
    for sub in sub_layers:
        color = color_map.get(sub) if color_map else None
        full = ensure_layer(sub, color=color, parent=base_name)
        result[sub] = full
    return result
