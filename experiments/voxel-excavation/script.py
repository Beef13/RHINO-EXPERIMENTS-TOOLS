import rhinoscriptsyntax as rs
import Rhino.Geometry as rg
import scriptcontext as sc
import math

# ─── PARAMETERS ──────────────────────────────────────────────────────────────
LAYER_BASE        = "EXCAVATE"
BOUNDARY_FRACTION = 0.3          # outer 30% of excavation radius = gradient zone
NUM_GRADIENT_BANDS = 5           # colour bands in boundary zone
FALLBACK_RADIUS   = 5.0          # used if no section curves map to a path
MAX_ASSOC_DIST    = 1e6          # max dist to associate a section curve with a path

# Gradient colours — inner boundary (near void) → outer boundary (near solid)
COLOR_INNER = (255, 80, 80)      # warm red
COLOR_OUTER = (255, 240, 100)    # warm yellow

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def setup_layer(name, color=None):
    if not rs.IsLayer(name):
        rs.AddLayer(name, color)
    elif color:
        rs.LayerColor(name, color)

def lerp_color(c1, c2, t):
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )

def get_centroid(obj_id):
    """Return Point3d centroid of a brep or mesh voxel."""
    if rs.IsMesh(obj_id):
        c = rs.MeshAreaCentroid(obj_id)
        if c:
            return rg.Point3d(c[0], c[1], c[2]) if not isinstance(c, rg.Point3d) else c
    if rs.IsBrep(obj_id) or rs.IsPolysurface(obj_id) or rs.IsSurface(obj_id):
        result = rs.SurfaceAreaCentroid(obj_id)
        if result:
            c = result[0]
            return rg.Point3d(c[0], c[1], c[2]) if not isinstance(c, rg.Point3d) else c
    # Fallback: bounding-box centre
    bb = rs.BoundingBox(obj_id)
    if bb and len(bb) == 8:
        cx = sum(p.X for p in bb) / 8.0
        cy = sum(p.Y for p in bb) / 8.0
        cz = sum(p.Z for p in bb) / 8.0
        return rg.Point3d(cx, cy, cz)
    return None

# ─── RADIUS PROFILE ALONG PATH ──────────────────────────────────────────────

def build_profiles(path_curves, section_curves):
    """For each path curve build a sorted list of (parameter, radius) from nearby
    closed section curves.  Radius = sqrt(area / pi)  (equivalent circle radius)."""

    profiles = {pc: [] for pc in path_curves}

    for sec in section_curves:
        area_data = rs.CurveArea(sec)
        if not area_data:
            continue
        radius = math.sqrt(area_data[0] / math.pi)

        centroid_data = rs.CurveAreaCentroid(sec)
        if not centroid_data:
            continue
        sec_pt = centroid_data[0]

        # Find the nearest path curve
        best_pc   = None
        best_dist = MAX_ASSOC_DIST
        best_t    = None
        for pc in path_curves:
            t = rs.CurveClosestPoint(pc, sec_pt)
            if t is None:
                continue
            cp   = rs.EvaluateCurve(pc, t)
            dist = rs.Distance(sec_pt, cp)
            if dist < best_dist:
                best_dist = dist
                best_pc   = pc
                best_t    = t

        if best_pc is not None:
            profiles[best_pc].append((best_t, radius))

    # Sort each profile by curve parameter
    for pc in profiles:
        profiles[pc].sort(key=lambda x: x[0])

    return profiles


def radius_at_param(profile, t):
    """Linearly interpolate the excavation radius at curve parameter *t*."""
    if not profile:
        return FALLBACK_RADIUS
    if len(profile) == 1:
        return profile[0][1]
    if t <= profile[0][0]:
        return profile[0][1]
    if t >= profile[-1][0]:
        return profile[-1][1]
    for i in range(len(profile) - 1):
        t0, r0 = profile[i]
        t1, r1 = profile[i + 1]
        if t0 <= t <= t1:
            denom = t1 - t0
            if denom < 1e-12:
                return r0
            frac = (t - t0) / denom
            return r0 + frac * (r1 - r0)
    return FALLBACK_RADIUS

# ─── CLASSIFICATION ──────────────────────────────────────────────────────────

def classify(centroid, path_curves, profiles):
    """Return normalised distance for a voxel centroid.
       0.0 = sitting on the path centreline
       1.0 = exactly at the excavation boundary
      >1.0 = outside excavation zone
    """
    best_norm = float("inf")
    for pc in path_curves:
        t = rs.CurveClosestPoint(pc, centroid)
        if t is None:
            continue
        cp   = rs.EvaluateCurve(pc, t)
        dist = rs.Distance(centroid, cp)
        local_r = radius_at_param(profiles[pc], t)
        if local_r < 1e-6:
            continue
        norm = dist / local_r
        if norm < best_norm:
            best_norm = norm
    return best_norm

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    # ── 1  Select inputs ────────────────────────────────────────────────────
    voxel_ids = rs.GetObjects(
        "Select voxel objects (breps / meshes)",
        8 | 16 | 32  # surface | polysurface | mesh
    )
    if not voxel_ids:
        print("No voxels selected — aborting.")
        return

    path_curves = rs.GetObjects("Select excavation path curve(s)", 4)
    if not path_curves:
        print("No path curves selected — aborting.")
        return

    section_curves = rs.GetObjects(
        "Select closed section curves (area → excavation radius)", 4
    )
    if not section_curves:
        print("No section curves selected — aborting.")
        return

    # Keep only closed curves
    valid_sections = [s for s in section_curves if rs.IsCurveClosed(s)]
    skipped = len(section_curves) - len(valid_sections)
    if skipped:
        print(f"Skipped {skipped} non-closed curve(s).")
    if not valid_sections:
        print("No valid closed section curves — aborting.")
        return

    # ── 2  Prepare layers ───────────────────────────────────────────────────
    setup_layer(LAYER_BASE, (100, 100, 100))
    band_layers = []
    for i in range(NUM_GRADIENT_BANDS):
        frac  = float(i) / max(1, NUM_GRADIENT_BANDS - 1)
        color = lerp_color(COLOR_INNER, COLOR_OUTER, frac)
        name  = f"{LAYER_BASE}_Band_{i}"
        setup_layer(name, color)
        band_layers.append(name)

    # ── 3  Build radius profiles ────────────────────────────────────────────
    pc_list  = list(path_curves)
    profiles = build_profiles(pc_list, valid_sections)

    for pc in pc_list:
        n = len(profiles[pc])
        if n:
            radii = [r for _, r in profiles[pc]]
            print(f"Path {pc}: {n} section(s), radius {min(radii):.2f}–{max(radii):.2f}")
        else:
            print(f"Path {pc}: no sections mapped → fallback radius {FALLBACK_RADIUS}")

    # ── 4  Classify every voxel ─────────────────────────────────────────────
    rs.EnableRedraw(False)
    removed = 0
    banded  = [0] * NUM_GRADIENT_BANDS
    kept    = 0
    total   = len(voxel_ids)

    for idx, vox in enumerate(voxel_ids):
        if idx % 200 == 0:
            print(f"  processing {idx}/{total} …")

        centroid = get_centroid(vox)
        if centroid is None:
            kept += 1
            continue

        norm_dist = classify(centroid, pc_list, profiles)
        boundary_start = 1.0 - BOUNDARY_FRACTION   # e.g. 0.7

        if norm_dist < boundary_start:
            # ── fully inside → remove
            rs.DeleteObject(vox)
            removed += 1

        elif norm_dist < 1.0:
            # ── boundary zone → colour-band layer
            band_frac = (norm_dist - boundary_start) / BOUNDARY_FRACTION
            band_idx  = int(band_frac * NUM_GRADIENT_BANDS)
            band_idx  = min(band_idx, NUM_GRADIENT_BANDS - 1)
            rs.ObjectLayer(vox, band_layers[band_idx])
            banded[band_idx] += 1

        else:
            kept += 1

    rs.EnableRedraw(True)
    sc.doc.Views.Redraw()

    # ── 5  Report ───────────────────────────────────────────────────────────
    print("─── Excavation Complete ───")
    print(f"  Removed (void):     {removed}")
    for i in range(NUM_GRADIENT_BANDS):
        print(f"  Boundary band {i}:    {banded[i]}")
    print(f"  Kept (solid):       {kept}")
    print(f"  Total processed:    {total}")

main()