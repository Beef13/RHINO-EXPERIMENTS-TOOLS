"""Rhino command UI for growth tools."""
import rhinoscriptsyntax as rs
from script import grow_random_walk, draw_growth


def run():
    start = rs.GetPoint("Pick growth start point")
    if start is None:
        return

    steps = rs.GetInteger("Number of growth steps", 50, 5, 500)
    if steps is None:
        return

    step_size = rs.GetReal("Step size", 1.0, 0.1, 10.0)
    if step_size is None:
        return

    root = grow_random_walk(
        (start[0], start[1], start[2]),
        steps,
        step_size,
        bias=(0, 0, 0.5),
    )
    draw_growth(root)


if __name__ == "__main__":
    run()
