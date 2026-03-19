"""Sandbox for quick throwaway tests. Paste code here and run in Rhino."""
import rhinoscriptsyntax as rs
import scriptcontext as sc

# Quick test area — write disposable code below this line.

pt = rs.GetPoint("Pick a point")
if pt:
    circle = rs.AddCircle(pt, 5.0)
    print("Circle created at ({}, {}, {})".format(pt[0], pt[1], pt[2]))
