"""Growth simulation — simple space colonisation and DLA-style growth."""
import sys, os

_here = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.normpath(os.path.join(_here, "..", "..", "lib"))
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import rhinoscriptsyntax as rs
import scriptcontext as sc
from utils.math_utils import clamp

import math
import random


class GrowthNode(object):
    """A single node in a branching growth structure."""

    def __init__(self, position, parent=None):
        self.position = position  # (x, y, z)
        self.parent = parent
        self.children = []

    def add_child(self, position):
        child = GrowthNode(position, parent=self)
        self.children.append(child)
        return child


def grow_random_walk(start, steps, step_size, bias=(0, 0, 1)):
    """Generate a branching structure using biased random walk.

    Args:
        start: starting position (x, y, z)
        steps: number of growth iterations
        step_size: distance per step
        bias: directional bias vector (will be normalised)

    Returns:
        root GrowthNode of the tree
    """
    root = GrowthNode(start)
    tips = [root]
    bias_mag = math.sqrt(bias[0]**2 + bias[1]**2 + bias[2]**2)
    if bias_mag > 0:
        bias = (bias[0]/bias_mag, bias[1]/bias_mag, bias[2]/bias_mag)

    for step in range(steps):
        if sc.escape_test(False):
            print("Growth cancelled at step {}".format(step))
            break

        new_tips = []
        for tip in tips:
            dx = random.gauss(0, 1) + bias[0]
            dy = random.gauss(0, 1) + bias[1]
            dz = random.gauss(0, 1) + bias[2]
            mag = math.sqrt(dx*dx + dy*dy + dz*dz)
            if mag > 0:
                dx, dy, dz = dx/mag * step_size, dy/mag * step_size, dz/mag * step_size

            new_pos = (
                tip.position[0] + dx,
                tip.position[1] + dy,
                tip.position[2] + dz,
            )
            child = tip.add_child(new_pos)
            new_tips.append(child)

            if random.random() < 0.1:
                new_tips.append(tip)

        tips = new_tips

    return root


def collect_branches(node):
    """Collect all branch segments as line pairs [(start, end), ...]."""
    segments = []
    for child in node.children:
        segments.append((node.position, child.position))
        segments.extend(collect_branches(child))
    return segments


def draw_growth(root, layer_name="Growth"):
    """Draw all branches as lines in Rhino."""
    segments = collect_branches(root)
    rs.AddLayer(layer_name)

    rs.EnableRedraw(False)
    try:
        for start, end in segments:
            line = rs.AddLine(start, end)
            if line:
                rs.ObjectLayer(line, layer_name)
    finally:
        rs.EnableRedraw(True)

    print("Drew {} branch segments".format(len(segments)))
