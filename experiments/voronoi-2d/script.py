import rhinoscriptsyntax as rs
import Rhino.Geometry as rg
import Rhino.UI
import scriptcontext as sc
import math
import random

import Eto.Forms as ef
import Eto.Drawing as ed

# ─── DEFAULTS ─────────────────────────────────────────────────────────────────
DEFAULT_SEED         = 42
DEFAULT_NUM_RANDOM   = 40
DEFAULT_ADD_RANDOM   = True
DEFAULT_USE_CORNERS  = False
DEFAULT_SHOW_SEEDS   = True
DEFAULT_SUBDIVISIONS = 64   # Arc subdivisions for non-polyline footprint curves

LAYER_VORONOI        = "ALG_Voronoi_Footprint"
LAYER_SEEDS_USER     = "ALG_Voronoi_Seeds_User"      # magenta  — hand-picked points
LAYER_SEEDS_CORNER   = "ALG_Voronoi_Seeds_Corner"    # yellow   — footprint corners
LAYER_SEEDS_RANDOM   = "ALG_Voronoi_Seeds_Random"    # orange   — random fill
LAYER_BOUNDARY       = "ALG_Voronoi_Boundary"

# ─── UI ───────────────────────────────────────────────────────────────────────

class VoronoiDialog(ef.Dialog):
    """
    Settings dialog shown AFTER the user has already made selections.
    Receives selection context so it can display live counts.
    """

    def __init__(self, user_seed_count, corner_count):
        super(VoronoiDialog, self).__init__()

        self.Title     = "Voronoi Pattern Settings"
        self.Resizable = False
        self.Padding   = ed.Padding(16)

        # ── Status labels (read-only, show what was pre-selected) ─────────────
        self._status_label = ef.Label()
        self._status_label.Text = (
            "{0} seed point(s) selected   |   "
            "{1} footprint corner(s) available"
        ).format(user_seed_count, corner_count)
        self._status_label.TextColor = ed.Colors.Gray

        # ── Use corners ───────────────────────────────────────────────────────
        self._corners_check = ef.CheckBox()
        self._corners_check.Text    = "Use footprint corners as seeds"
        self._corners_check.Checked = DEFAULT_USE_CORNERS
        self._corners_check.Enabled = corner_count > 0

        # ── Random fill ───────────────────────────────────────────────────────
        self._add_random_check = ef.CheckBox()
        self._add_random_check.Text    = "Add random fill points"
        self._add_random_check.Checked = DEFAULT_ADD_RANDOM

        self._num_random_label = ef.Label()
        self._num_random_label.Text = "Random fill count"
        self._num_random_input = ef.NumericStepper()
        self._num_random_input.MinValue      = 0
        self._num_random_input.MaxValue      = 2000
        self._num_random_input.Value         = DEFAULT_NUM_RANDOM
        self._num_random_input.Increment     = 5
        self._num_random_input.DecimalPlaces = 0

        # ── Random seed ───────────────────────────────────────────────────────
        self._seed_label = ef.Label()
        self._seed_label.Text = "Random seed"
        self._seed_input = ef.NumericStepper()
        self._seed_input.MinValue      = 0
        self._seed_input.MaxValue      = 99999
        self._seed_input.Value         = DEFAULT_SEED
        self._seed_input.Increment     = 1
        self._seed_input.DecimalPlaces = 0

        # ── Show seeds ────────────────────────────────────────────────────────
        self._show_seeds_check = ef.CheckBox()
        self._show_seeds_check.Text    = "Show seed points"
        self._show_seeds_check.Checked = DEFAULT_SHOW_SEEDS

        # ── Buttons ───────────────────────────────────────────────────────────
        self._ok_btn = ef.Button()
        self._ok_btn.Text = "Run"
        self._ok_btn.Click += self._on_ok

        self._cancel_btn = ef.Button()
        self._cancel_btn.Text = "Cancel"
        self._cancel_btn.Click += self._on_cancel

        self._add_random_check.CheckedChanged += self._on_add_random_changed
        self._sync_random_enabled()

        # ── Layout ────────────────────────────────────────────────────────────
        layout = ef.DynamicLayout()
        layout.Spacing = ed.Size(8, 6)

        def divider():
            lbl = ef.Label()
            lbl.Text      = u"\u2500" * 34
            lbl.TextColor = ed.Colors.Silver
            return lbl

        def labeled_row(lbl_ctrl, input_ctrl):
            tbl = ef.TableLayout()
            tbl.Spacing = ed.Size(8, 0)
            lc = ef.TableCell()
            lc.Control = lbl_ctrl
            ic = ef.TableCell()
            ic.Control  = input_ctrl
            ic.ScaleWidth = True
            row = ef.TableRow()
            row.Cells.Add(lc)
            row.Cells.Add(ic)
            tbl.Rows.Add(row)
            return tbl

        layout.Add(self._status_label, True)
        layout.Add(divider(), True)

        layout.Add(self._corners_check, True)
        layout.Add(divider(), True)

        layout.Add(self._add_random_check, True)
        layout.Add(labeled_row(self._num_random_label, self._num_random_input), True)
        layout.Add(divider(), True)

        layout.Add(labeled_row(self._seed_label, self._seed_input), True)
        layout.Add(self._show_seeds_check, True)
        layout.Add(divider(), True)

        # Button row
        btn_tbl = ef.TableLayout()
        btn_tbl.Spacing = ed.Size(8, 0)
        spacer = ef.TableCell()
        spacer.ScaleWidth = True
        ok_cell = ef.TableCell()
        ok_cell.Control = self._ok_btn
        cancel_cell = ef.TableCell()
        cancel_cell.Control = self._cancel_btn
        btn_row = ef.TableRow()
        btn_row.Cells.Add(spacer)
        btn_row.Cells.Add(ok_cell)
        btn_row.Cells.Add(cancel_cell)
        btn_tbl.Rows.Add(btn_row)
        layout.Add(btn_tbl, True)

        self.Content       = layout
        self.DefaultButton = self._ok_btn
        self.AbortButton   = self._cancel_btn
        self.confirmed     = False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _sync_random_enabled(self):
        enabled = bool(self._add_random_check.Checked)
        self._num_random_input.Enabled = enabled
        self._num_random_label.Enabled = enabled

    def _on_add_random_changed(self, sender, e):
        self._sync_random_enabled()

    def _on_ok(self, sender, e):
        self.confirmed = True
        self.Close()

    def _on_cancel(self, sender, e):
        self.confirmed = False
        self.Close()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def seed(self):
        return int(self._seed_input.Value)

    @property
    def num_random_points(self):
        return int(self._num_random_input.Value)

    @property
    def add_random_to_fill(self):
        return bool(self._add_random_check.Checked)

    @property
    def use_corners(self):
        return bool(self._corners_check.Checked)

    @property
    def show_seeds(self):
        return bool(self._show_seeds_check.Checked)


# ─── LAYER HELPERS ────────────────────────────────────────────────────────────

def setup_layer(name, color=None):
    if not rs.IsLayer(name):
        rs.AddLayer(name)
    if color:
        rs.LayerColor(name, color)

def clear_layer(name):
    objs = rs.ObjectsByLayer(name)
    if objs:
        rs.DeleteObjects(objs)

# ─── GEOMETRY HELPERS ─────────────────────────────────────────────────────────

def curve_to_polygon(rg_crv, subdivisions=64):
    """
    Convert a closed RhinoCommon Curve to a list of (x, y) tuples.
    Uses actual polyline vertices when available; otherwise subdivides.
    """
    tol = sc.doc.ModelAbsoluteTolerance
    ok, polyline = rg_crv.TryGetPolyline()
    if ok and polyline is not None:
        pts = list(polyline)
        if len(pts) > 1 and pts[0].DistanceTo(pts[-1]) < tol:
            pts = pts[:-1]
        return [(p.X, p.Y) for p in pts]

    params = rg_crv.DivideByCount(subdivisions, False)
    if params is None:
        return []
    return [(rg_crv.PointAt(t).X, rg_crv.PointAt(t).Y) for t in params]

def extract_corners(rg_crv, subdivisions=64):
    """
    Return the genuine corner vertices of the footprint as (x, y) tuples.
    For polylines these are exact vertices; for curved footprints we use
    subdivision points (which approximate arc corners adequately).
    """
    return curve_to_polygon(rg_crv, subdivisions)

def polygon_bbox(polygon):
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)

def point_in_polygon(px, py, polygon):
    """Ray-casting containment test."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / float(yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def deduplicate_seeds(seeds, tol):
    """Remove duplicate or near-duplicate (x, y) seeds within tol distance."""
    unique = []
    for sx, sy in seeds:
        too_close = False
        for ux, uy in unique:
            if math.sqrt((sx - ux) ** 2 + (sy - uy) ** 2) < tol:
                too_close = True
                break
        if not too_close:
            unique.append((sx, sy))
    return unique

def polygon_to_rg_curve(polygon):
    if len(polygon) < 3:
        return None
    pts = [rg.Point3d(p[0], p[1], 0.0) for p in polygon]
    pts.append(pts[0])
    return rg.Polyline(pts).ToNurbsCurve()

# ─── SELECTION (RUNS BEFORE DIALOG) ───────────────────────────────────────────

def select_footprint():
    """
    Prompt for footprint curve. Supports pre-selection — if the user has
    already selected a curve before running the script it is accepted immediately.
    """
    obj_id = rs.GetObject(
        "Select building footprint (closed planar curve)",
        rs.filter.curve,
        preselect=True
    )
    if obj_id is None:
        return None
    if not rs.IsCurveClosed(obj_id):
        rs.MessageBox("Selected curve must be closed.")
        return None
    return obj_id

def select_seed_points():
    """
    Prompt for zero or more seed point objects. Supports pre-selection —
    points already selected before running the script are accepted.
    Press Enter with nothing selected to skip.
    """
    obj_ids = rs.GetObjects(
        "Select seed points (Enter to skip)",
        rs.filter.point,
        preselect=True
    )
    return obj_ids if obj_ids else []

def filter_seeds_inside(raw_point_ids, footprint_polygon):
    """Validate selected point objects; return list of (x,y) inside the footprint."""
    valid   = []
    skipped = 0
    for obj_id in raw_point_ids:
        pt = rs.PointCoordinates(obj_id)
        if pt is None:
            continue
        if point_in_polygon(pt.X, pt.Y, footprint_polygon):
            valid.append((pt.X, pt.Y))
        else:
            skipped += 1
    if skipped:
        print("Warning: {0} point(s) outside footprint skipped.".format(skipped))
    return valid

# ─── RANDOM SEED GENERATION ───────────────────────────────────────────────────

def generate_random_seeds(footprint_polygon, count, existing_seeds, tol):
    min_x, min_y, max_x, max_y = polygon_bbox(footprint_polygon)
    w = max_x - min_x
    h = max_y - min_y

    result      = []
    attempts    = 0
    max_attempts = count * 300

    while len(result) < count and attempts < max_attempts:
        x = min_x + random.random() * w
        y = min_y + random.random() * h

        if not point_in_polygon(x, y, footprint_polygon):
            attempts += 1
            continue

        too_close = False
        for ex, ey in existing_seeds + result:
            if math.sqrt((x - ex) ** 2 + (y - ey) ** 2) < tol:
                too_close = True
                break

        if not too_close:
            result.append((x, y))
        attempts += 1

    if len(result) < count:
        print("Warning: only generated {0} of {1} random seed points.".format(
            len(result), count))
    return result

# ─── VORONOI — HALF-PLANE INTERSECTION (SUTHERLAND-HODGMAN) ──────────────────

def clip_polygon_by_bisector(polygon, si, sj):
    """
    Clip polygon to the half-plane closer to si than sj.
    Keeps all points where dist(p, si) <= dist(p, sj).
    """
    if not polygon:
        return []

    mx = (si[0] + sj[0]) * 0.5
    my = (si[1] + sj[1]) * 0.5
    nx = sj[0] - si[0]
    ny = sj[1] - si[1]

    def inside(p):
        return nx * (p[0] - mx) + ny * (p[1] - my) <= 0

    def intersect(p1, p2):
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        denom = nx * dx + ny * dy
        if abs(denom) < 1e-14:
            return p1
        t = (nx * (mx - p1[0]) + ny * (my - p1[1])) / denom
        return (p1[0] + t * dx, p1[1] + t * dy)

    output = []
    n = len(polygon)
    for i in range(n):
        curr    = polygon[i]
        prev    = polygon[i - 1]
        curr_in = inside(curr)
        prev_in = inside(prev)
        if curr_in:
            if not prev_in:
                output.append(intersect(prev, curr))
            output.append(curr)
        elif prev_in:
            output.append(intersect(prev, curr))

    return output

def compute_voronoi_cells(seeds, footprint_polygon):
    cells = []
    n = len(seeds)
    for i in range(n):
        cell = list(footprint_polygon)
        si   = seeds[i]
        for j in range(n):
            if i == j or not cell:
                continue
            cell = clip_polygon_by_bisector(cell, si, seeds[j])
        cells.append(cell)
    return cells

# ─── OUTPUT ───────────────────────────────────────────────────────────────────

def draw(footprint_id, user_seeds, corner_seeds, random_seeds, cells, show_seeds):
    rs.CurrentLayer(LAYER_BOUNDARY)
    rs.CopyObject(footprint_id)

    rs.CurrentLayer(LAYER_VORONOI)
    for cell in cells:
        crv = polygon_to_rg_curve(cell)
        if crv is not None:
            sc.doc.Objects.AddCurve(crv)

    if show_seeds:
        if user_seeds:
            rs.CurrentLayer(LAYER_SEEDS_USER)
            for x, y in user_seeds:
                sc.doc.Objects.AddPoint(rg.Point3d(x, y, 0.0))
        if corner_seeds:
            rs.CurrentLayer(LAYER_SEEDS_CORNER)
            for x, y in corner_seeds:
                sc.doc.Objects.AddPoint(rg.Point3d(x, y, 0.0))
        if random_seeds:
            rs.CurrentLayer(LAYER_SEEDS_RANDOM)
            for x, y in random_seeds:
                sc.doc.Objects.AddPoint(rg.Point3d(x, y, 0.0))

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    tol = sc.doc.ModelAbsoluteTolerance

    # ── Phase 1: Selections (happen BEFORE dialog) ────────────────────────────

    footprint_id = select_footprint()
    if footprint_id is None:
        print("No footprint selected. Aborting.")
        return

    rg_footprint = rs.coercecurve(footprint_id)
    if rg_footprint is None:
        print("Could not read curve geometry. Aborting.")
        return

    footprint_polygon = curve_to_polygon(rg_footprint, DEFAULT_SUBDIVISIONS)
    if len(footprint_polygon) < 3:
        print("Could not extract footprint polygon. Aborting.")
        return

    all_corners = extract_corners(rg_footprint, DEFAULT_SUBDIVISIONS)

    raw_point_ids = select_seed_points()
    user_seeds    = filter_seeds_inside(raw_point_ids, footprint_polygon)

    print("{0} seed point(s) selected, {1} footprint corner(s) available.".format(
        len(user_seeds), len(all_corners)))

    # ── Phase 2: Dialog ───────────────────────────────────────────────────────

    dlg = VoronoiDialog(len(user_seeds), len(all_corners))
    Rhino.UI.EtoExtensions.ShowSemiModal(
        dlg,
        Rhino.RhinoDoc.ActiveDoc,
        Rhino.UI.RhinoEtoApp.MainWindow
    )
    if not dlg.confirmed:
        print("Cancelled.")
        return

    SEED              = dlg.seed
    NUM_RANDOM_POINTS = dlg.num_random_points
    ADD_RANDOM        = dlg.add_random_to_fill
    USE_CORNERS       = dlg.use_corners
    SHOW_SEEDS        = dlg.show_seeds

    random.seed(SEED)

    # ── Phase 3: Assemble seed list ───────────────────────────────────────────

    corner_seeds = all_corners if USE_CORNERS else []

    # All fixed seeds combined (user + corners), deduplicated
    fixed_seeds = deduplicate_seeds(user_seeds + corner_seeds, tol)

    random_seeds = []
    if ADD_RANDOM and NUM_RANDOM_POINTS > 0:
        print("Generating {0} random seed points...".format(NUM_RANDOM_POINTS))
        random_seeds = generate_random_seeds(
            footprint_polygon, NUM_RANDOM_POINTS, fixed_seeds, tol
        )

    all_seeds = fixed_seeds + random_seeds

    if len(all_seeds) < 2:
        print("Need at least 2 seed points to compute Voronoi. Aborting.")
        return

    print("Seeds: {0} user | {1} corner | {2} random = {3} total".format(
        len(user_seeds), len(corner_seeds), len(random_seeds), len(all_seeds)))

    # ── Phase 4: Layers ───────────────────────────────────────────────────────

    setup_layer(LAYER_VORONOI,      (80, 160, 220))
    setup_layer(LAYER_SEEDS_USER,   (220, 60, 180))
    setup_layer(LAYER_SEEDS_CORNER, (240, 210, 40))
    setup_layer(LAYER_SEEDS_RANDOM, (220, 140, 60))
    setup_layer(LAYER_BOUNDARY,     (200, 200, 200))
    clear_layer(LAYER_VORONOI)
    clear_layer(LAYER_SEEDS_USER)
    clear_layer(LAYER_SEEDS_CORNER)
    clear_layer(LAYER_SEEDS_RANDOM)
    clear_layer(LAYER_BOUNDARY)

    # ── Phase 5: Compute ──────────────────────────────────────────────────────

    print("Computing Voronoi cells...")
    cells     = compute_voronoi_cells(all_seeds, footprint_polygon)
    non_empty = [c for c in cells if len(c) >= 3]
    print("{0} cells computed.".format(len(non_empty)))

    # ── Phase 6: Draw ─────────────────────────────────────────────────────────

    draw(footprint_id, user_seeds, corner_seeds, random_seeds, non_empty, SHOW_SEEDS)

    sc.doc.Views.Redraw()
    print("Done. {0} user | {1} corner | {2} random | {3} cells.".format(
        len(user_seeds), len(corner_seeds), len(random_seeds), len(non_empty)))

main()