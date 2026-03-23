# Voxel Curve Sculpt
# Curve-attractor-based voxel field sculpting with real-time Eto UI
# Environment: Rhino 8 Python (CPython 3 / PythonNet)

import Rhino
import Rhino.Geometry as rg
import Rhino.Display as rd
import scriptcontext as sc
import System
import System.Drawing
import math
import random
import sys
import os
import rhinoscriptsyntax as rs

try:
    import Eto.Forms as forms
    import Eto.Drawing as drawing
except:
    import Rhino.UI
    forms = Rhino.UI.EtoExtensions

_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)


# ---------------------------------------------------------------------------
# Perlin Noise
# ---------------------------------------------------------------------------
class PerlinNoise(object):
    _GRAD3 = (
        (1,1,0),(-1,1,0),(1,-1,0),(-1,-1,0),
        (1,0,1),(-1,0,1),(1,0,-1),(-1,0,-1),
        (0,1,1),(0,-1,1),(0,1,-1),(0,-1,-1),
        (1,1,0),(-1,1,0),(0,-1,1),(0,-1,-1),
    )
    def __init__(self, seed=0):
        random.seed(seed)
        p = list(range(256))
        random.shuffle(p)
        self.p = p + p
        g3 = self._GRAD3
        pp = self.p
        self._g12 = tuple(
            (g3[pp[i] & 15][0], g3[pp[i] & 15][1], g3[pp[i] & 15][2])
            for i in range(512))

    def noise3d(self, x, y, z):
        p = self.p
        g12 = self._g12
        xi = int(x) if x >= 0 else int(x) - (1 if x != int(x) else 0)
        yi = int(y) if y >= 0 else int(y) - (1 if y != int(y) else 0)
        zi = int(z) if z >= 0 else int(z) - (1 if z != int(z) else 0)
        X = xi & 255; Y = yi & 255; Z = zi & 255
        xf = x - xi; yf = y - yi; zf = z - zi
        u = xf * xf * xf * (xf * (xf * 6.0 - 15.0) + 10.0)
        v = yf * yf * yf * (yf * (yf * 6.0 - 15.0) + 10.0)
        w = zf * zf * zf * (zf * (zf * 6.0 - 15.0) + 10.0)
        A = p[X] + Y; AA = p[A] + Z; AB = p[A + 1] + Z
        B = p[X + 1] + Y; BA = p[B] + Z; BB = p[B + 1] + Z
        xf1 = xf - 1.0; yf1 = yf - 1.0; zf1 = zf - 1.0
        ga = g12[AA];  g0 = ga[0]*xf  + ga[1]*yf  + ga[2]*zf
        ga = g12[BA];  g1 = ga[0]*xf1 + ga[1]*yf  + ga[2]*zf
        ga = g12[AB];  g2 = ga[0]*xf  + ga[1]*yf1 + ga[2]*zf
        ga = g12[BB];  g3 = ga[0]*xf1 + ga[1]*yf1 + ga[2]*zf
        ga = g12[AA+1];g4 = ga[0]*xf  + ga[1]*yf  + ga[2]*zf1
        ga = g12[BA+1];g5 = ga[0]*xf1 + ga[1]*yf  + ga[2]*zf1
        ga = g12[AB+1];g6 = ga[0]*xf  + ga[1]*yf1 + ga[2]*zf1
        ga = g12[BB+1];g7 = ga[0]*xf1 + ga[1]*yf1 + ga[2]*zf1
        l0 = g0 + u * (g1 - g0); l1 = g2 + u * (g3 - g2)
        l2 = g4 + u * (g5 - g4); l3 = g6 + u * (g7 - g6)
        m0 = l0 + v * (l1 - l0); m1 = l2 + v * (l3 - l2)
        return m0 + w * (m1 - m0)

    def octave_noise(self, x, y, z, octaves=1):
        val = 0.0; freq = 1.0; amp = 1.0; max_amp = 0.0
        n3d = self.noise3d
        for _ in range(octaves):
            val += n3d(x * freq, y * freq, z * freq) * amp
            max_amp += amp; amp *= 0.5; freq *= 2.0
        return val / max_amp


# ---------------------------------------------------------------------------
# Display Conduit
# ---------------------------------------------------------------------------
class SculptConduit(rd.DisplayConduit):
    def __init__(self):
        super(SculptConduit, self).__init__()
        self.mesh = None
        self.edge_mesh = None
        self.bbox = rg.BoundingBox.Empty
        self.bound_lines = []
        self.bound_color = System.Drawing.Color.FromArgb(80, 80, 80)
        self.edge_color = System.Drawing.Color.FromArgb(40, 40, 40)
        self.show_bounds = True
        self.show_edges = True
        self.show_voxels = True
        self.voxel_opacity = 255
        self.shaded_material = rd.DisplayMaterial()
        self._cached_trans_mat = None
        self._cached_trans_opacity = -1
        self.attractor_curves = []
        self.curve_color = System.Drawing.Color.FromArgb(255, 100, 50)
        self.curve_thickness = 2
        self.show_curves = True

    def CalculateBoundingBox(self, e):
        if self.bbox.IsValid:
            e.IncludeBoundingBox(self.bbox)

    def PostDrawObjects(self, e):
        disp = e.Display
        if self.show_voxels and self.mesh and self.mesh.Vertices.Count > 0:
            if self.voxel_opacity >= 255:
                disp.DrawMeshFalseColors(self.mesh)
            else:
                op = self.voxel_opacity
                if op != self._cached_trans_opacity:
                    mat = rd.DisplayMaterial(self.shaded_material)
                    mat.Transparency = 1.0 - op / 255.0
                    self._cached_trans_mat = mat
                    self._cached_trans_opacity = op
                disp.DrawMeshShaded(self.mesh, self._cached_trans_mat)
            if self.show_edges:
                wire = self.edge_mesh if self.edge_mesh else self.mesh
                disp.DrawMeshWires(wire, self.edge_color)
        if self.show_bounds and self.bound_lines:
            bc = self.bound_color
            _dl = disp.DrawLine
            for ln in self.bound_lines:
                _dl(ln, bc, 1)

    def DrawForeground(self, e):
        if self.show_curves and self.attractor_curves:
            disp = e.Display
            cc = self.curve_color
            ct = self.curve_thickness
            for crv in self.attractor_curves:
                disp.DrawCurve(crv, cc, ct)


# ---------------------------------------------------------------------------
# Voxel System
# ---------------------------------------------------------------------------
class VoxelSystem(object):

    _TO_VERTS = (
        ( 0,  1,  2), ( 0,  1, -2), ( 0, -1,  2), ( 0, -1, -2),
        ( 0,  2,  1), ( 0,  2, -1), ( 0, -2,  1), ( 0, -2, -1),
        ( 1,  0,  2), ( 1,  0, -2), (-1,  0,  2), (-1,  0, -2),
        ( 1,  2,  0), ( 1, -2,  0), (-1,  2,  0), (-1, -2,  0),
        ( 2,  0,  1), ( 2,  0, -1), (-2,  0,  1), (-2,  0, -1),
        ( 2,  1,  0), ( 2, -1,  0), (-2,  1,  0), (-2, -1,  0),
    )
    _TO_QUADS = (
        (20, 16, 21, 17),
        (22, 19, 23, 18),
        (12,  4, 14,  5),
        (13,  7, 15,  6),
        ( 8,  0, 10,  2),
        ( 9,  3, 11,  1),
    )
    _TO_HEXES = (
        ( 0,  8, 16, 20, 12,  4),
        ( 1,  5, 12, 20, 17,  9),
        ( 2,  6, 13, 21, 16,  8),
        ( 3,  9, 17, 21, 13,  7),
        ( 0,  4, 14, 22, 18, 10),
        ( 1, 11, 19, 22, 14,  5),
        ( 2, 10, 18, 23, 15,  6),
        ( 3,  7, 15, 23, 19, 11),
    )
    _TO_EDGES = (
        ( 0,  4), ( 0,  8), ( 0, 10), ( 1,  5), ( 1,  9), ( 1, 11),
        ( 2,  6), ( 2,  8), ( 2, 10), ( 3,  7), ( 3,  9), ( 3, 11),
        ( 4, 12), ( 4, 14), ( 5, 12), ( 5, 14), ( 6, 13), ( 6, 15),
        ( 7, 13), ( 7, 15), ( 8, 16), ( 9, 17), (10, 18), (11, 19),
        (12, 20), (13, 21), (14, 22), (15, 23), (16, 20), (16, 21),
        (17, 20), (17, 21), (18, 22), (18, 23), (19, 22), (19, 23),
    )

    def __init__(self):
        self.conduit = SculptConduit()
        self.perlin = None
        self.voxels = []

    def generate(self, grid_x, grid_y, grid_z, cell_w, cell_l, cell_h,
                 noise_scale, threshold, octaves, seed,
                 solid_base, curves, curve_radius_cells, curve_strength,
                 curve_carve, falloff_type,
                 use_bounds, bounds_meshes, bounds_aabb, bounds_strict,
                 grid_type, grid_origin):
        """Generate voxel field with optional curve attractor influence.
        grid_type 0=cube, 1=truncated octahedron (BCC)."""
        self.perlin = PerlinNoise(seed)
        oct_noise = self.perlin.octave_noise
        voxels = []
        _append = voxels.append
        ox = grid_origin.X; oy = grid_origin.Y; oz = grid_origin.Z
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        _Point3d = rg.Point3d
        _has_curves = bool(curves)

        world_radius = curve_radius_cells * max(cell_w, cell_l, cell_h)
        inv_wr = 1.0 / world_radius if world_radius > 1e-10 else 0.0
        _ps = curve_strength

        if use_bounds and bounds_meshes and bounds_aabb and bounds_aabb.IsValid:
            _bb_min = bounds_aabb.Min; _bb_max = bounds_aabb.Max
            bb_x0 = _bb_min.X; bb_y0 = _bb_min.Y; bb_z0 = _bb_min.Z
            bb_x1 = _bb_max.X; bb_y1 = _bb_max.Y; bb_z1 = _bb_max.Z
            _do_bounds = True
            _bmeshes = bounds_meshes
            _bstrict = bounds_strict
        else:
            _do_bounds = False
            _bmeshes = None; _bstrict = False
            bb_x0 = bb_y0 = bb_z0 = 0.0
            bb_x1 = bb_y1 = bb_z1 = 0.0

        _curve_info = []
        if _has_curves:
            for crv in curves:
                bb = crv.GetBoundingBox(False)
                _curve_info.append((
                    crv.ClosestPoint, crv.PointAt,
                    bb.Min.X - world_radius, bb.Max.X + world_radius,
                    bb.Min.Y - world_radius, bb.Max.Y + world_radius,
                    bb.Min.Z - world_radius, bb.Max.Z + world_radius))

        positions = []
        _pos_append = positions.append
        if grid_type == 1:
            gxm1 = grid_x - 1; gym1 = grid_y - 1; gzm1 = grid_z - 1
            for ix in range(grid_x):
                for iy in range(grid_y):
                    for iz in range(grid_z):
                        _pos_append((ix, iy, iz))
                        if ix < gxm1 and iy < gym1 and iz < gzm1:
                            _pos_append((ix + 0.5, iy + 0.5, iz + 0.5))
        else:
            for ix in range(grid_x):
                for iy in range(grid_y):
                    for iz in range(grid_z):
                        _pos_append((ix, iy, iz))

        if _has_curves:
            _carve = curve_carve
            _ft = falloff_type
            _big = float('inf')
            for (fx, fy, fz) in positions:
                cx = ox + fx * cell_w + hw
                cy = oy + fy * cell_l + hl
                cz = oz + fz * cell_h + hh

                if _do_bounds:
                    if (cx < bb_x0 or cx > bb_x1 or
                        cy < bb_y0 or cy > bb_y1 or
                        cz < bb_z0 or cz > bb_z1):
                        continue
                    if _bstrict:
                        _ok = True
                        for cdx in (0.0, cell_w):
                            for cdy in (0.0, cell_l):
                                for cdz in (0.0, cell_h):
                                    cp = _Point3d(
                                        ox + fx * cell_w + cdx,
                                        oy + fy * cell_l + cdy,
                                        oz + fz * cell_h + cdz)
                                    _in = False
                                    for bm in _bmeshes:
                                        if bm.IsPointInside(cp, 0.001, False):
                                            _in = True
                                            break
                                    if not _in:
                                        _ok = False
                                        break
                                if not _ok:
                                    break
                            if not _ok:
                                break
                        if not _ok:
                            continue
                    else:
                        pt_b = _Point3d(cx, cy, cz)
                        _in = False
                        for bm in _bmeshes:
                            if bm.IsPointInside(pt_b, 0.001, False):
                                _in = True
                                break
                        if not _in:
                            continue

                if solid_base:
                    val = 1.0
                else:
                    val = oct_noise(
                        fx * noise_scale, fy * noise_scale,
                        fz * noise_scale, octaves)
                    val = (val + 1.0) * 0.5

                pt = _Point3d(cx, cy, cz)
                min_d = _big
                for (_cp, _pa, cx0, cx1, cy0, cy1, cz0, cz1) in _curve_info:
                    if cx < cx0 or cx > cx1 or cy < cy0 or cy > cy1 or cz < cz0 or cz > cz1:
                        continue
                    rc, t = _cp(pt)
                    if rc:
                        d = pt.DistanceTo(_pa(t))
                        if d < min_d:
                            min_d = d

                if min_d <= world_radius:
                    ratio = min_d * inv_wr
                    if _ft == 0:
                        f = 1.0 - ratio
                    elif _ft == 1:
                        f = (1.0 - ratio) * (1.0 - ratio)
                    else:
                        t_s = 1.0 - ratio
                        f = t_s * t_s * (3.0 - 2.0 * t_s)
                    if _carve:
                        val -= f * _ps
                    else:
                        val += f * _ps
                else:
                    if not _carve:
                        val -= _ps

                if val < 0.0:
                    val = 0.0
                elif val > 1.0:
                    val = 1.0

                if val > threshold:
                    _append((fx, fy, fz, val))
        else:
            for (fx, fy, fz) in positions:
                if _do_bounds:
                    cx = ox + fx * cell_w + hw
                    cy = oy + fy * cell_l + hl
                    cz = oz + fz * cell_h + hh
                    if (cx < bb_x0 or cx > bb_x1 or
                        cy < bb_y0 or cy > bb_y1 or
                        cz < bb_z0 or cz > bb_z1):
                        continue
                    if _bstrict:
                        _ok = True
                        for cdx in (0.0, cell_w):
                            for cdy in (0.0, cell_l):
                                for cdz in (0.0, cell_h):
                                    cp = _Point3d(
                                        ox + fx * cell_w + cdx,
                                        oy + fy * cell_l + cdy,
                                        oz + fz * cell_h + cdz)
                                    _in = False
                                    for bm in _bmeshes:
                                        if bm.IsPointInside(cp, 0.001, False):
                                            _in = True
                                            break
                                    if not _in:
                                        _ok = False
                                        break
                                if not _ok:
                                    break
                            if not _ok:
                                break
                        if not _ok:
                            continue
                    else:
                        pt_b = _Point3d(cx, cy, cz)
                        _in = False
                        for bm in _bmeshes:
                            if bm.IsPointInside(pt_b, 0.001, False):
                                _in = True
                                break
                        if not _in:
                            continue

                if solid_base:
                    val = 1.0
                else:
                    val = oct_noise(
                        fx * noise_scale, fy * noise_scale,
                        fz * noise_scale, octaves)
                    val = (val + 1.0) * 0.5
                if val > threshold:
                    _append((fx, fy, fz, val))

        self.voxels = voxels
        return voxels

    def build_mesh(self, voxels, cell_w, cell_l, cell_h, color, grid_origin):
        """Build combined cube mesh with vertex colours."""
        mesh = rg.Mesh()
        _va = mesh.Vertices.Add
        _fa = mesh.Faces.AddFace
        _ca = mesh.VertexColors.Add
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        cr = color.R; cg = color.G; cb = color.B
        _FromArgb = System.Drawing.Color.FromArgb
        _int = int

        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        o = ((-hw, -hl, -hh), ( hw, -hl, -hh), ( hw,  hl, -hh), (-hw,  hl, -hh),
             (-hw, -hl,  hh), ( hw, -hl,  hh), ( hw,  hl,  hh), (-hw,  hl,  hh))

        b = 0
        for (fx, fy, fz, val) in voxels:
            cx = ox0 + fx * cell_w + hw
            cy = oy0 + fy * cell_l + hl
            cz = oz0 + fz * cell_h + hh
            _va(cx+o[0][0], cy+o[0][1], cz+o[0][2])
            _va(cx+o[1][0], cy+o[1][1], cz+o[1][2])
            _va(cx+o[2][0], cy+o[2][1], cz+o[2][2])
            _va(cx+o[3][0], cy+o[3][1], cz+o[3][2])
            _va(cx+o[4][0], cy+o[4][1], cz+o[4][2])
            _va(cx+o[5][0], cy+o[5][1], cz+o[5][2])
            _va(cx+o[6][0], cy+o[6][1], cz+o[6][2])
            _va(cx+o[7][0], cy+o[7][1], cz+o[7][2])
            _fa(b, b+1, b+2, b+3)
            _fa(b+4, b+7, b+6, b+5)
            _fa(b, b+4, b+5, b+1)
            _fa(b+2, b+6, b+7, b+3)
            _fa(b, b+3, b+7, b+4)
            _fa(b+1, b+5, b+6, b+2)
            rv = _int(cr * val); gv = _int(cg * val); bv = _int(cb * val)
            if rv < 30: rv = 30
            elif rv > 255: rv = 255
            if gv < 30: gv = 30
            elif gv > 255: gv = 255
            if bv < 30: bv = 30
            elif bv > 255: bv = 255
            vc = _FromArgb(rv, gv, bv)
            _ca(vc);_ca(vc);_ca(vc);_ca(vc)
            _ca(vc);_ca(vc);_ca(vc);_ca(vc)
            b += 8
        mesh.Normals.ComputeNormals()
        return mesh

    def build_mesh_to(self, voxels, cell_w, cell_l, cell_h, color, grid_origin):
        """Build truncated octahedra mesh with cached method refs."""
        mesh = rg.Mesh()
        _va = mesh.Vertices.Add
        _fa = mesh.Faces.AddFace
        _ca = mesh.VertexColors.Add
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        cr = color.R; cg = color.G; cb = color.B
        _FromArgb = System.Drawing.Color.FromArgb
        _int = int

        sw = cell_w * 0.25; sl = cell_l * 0.25; sh = cell_h * 0.25
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        to_quads = self._TO_QUADS
        to_hexes = self._TO_HEXES
        scaled = tuple((vx * sw, vy * sl, vz * sh)
                        for (vx, vy, vz) in self._TO_VERTS)
        to_hex_flat = []
        for hex_f in to_hexes:
            v0 = hex_f[0]
            for ti in range(1, 5):
                to_hex_flat.append((v0, hex_f[ti], hex_f[ti + 1]))
        to_hex_flat = tuple(to_hex_flat)

        b = 0
        for (fx, fy, fz, val) in voxels:
            cx = ox0 + fx * cell_w + hw
            cy = oy0 + fy * cell_l + hl
            cz = oz0 + fz * cell_h + hh
            for (dx, dy, dz) in scaled:
                _va(cx + dx, cy + dy, cz + dz)
            for (a, b2, c, d) in to_quads:
                _fa(b + a, b + b2, b + c, b + d)
            for (ha, hb, hc) in to_hex_flat:
                _fa(b + ha, b + hb, b + hc)
            rv = _int(cr * val); gv = _int(cg * val); bv_c = _int(cb * val)
            if rv < 30: rv = 30
            elif rv > 255: rv = 255
            if gv < 30: gv = 30
            elif gv > 255: gv = 255
            if bv_c < 30: bv_c = 30
            elif bv_c > 255: bv_c = 255
            vc = _FromArgb(rv, gv, bv_c)
            _ca(vc);_ca(vc);_ca(vc);_ca(vc);_ca(vc);_ca(vc)
            _ca(vc);_ca(vc);_ca(vc);_ca(vc);_ca(vc);_ca(vc)
            _ca(vc);_ca(vc);_ca(vc);_ca(vc);_ca(vc);_ca(vc)
            _ca(vc);_ca(vc);_ca(vc);_ca(vc);_ca(vc);_ca(vc)
            b += 24
        mesh.Normals.ComputeNormals()
        return mesh

    def _build_to_edge_mesh(self, voxels, cell_w, cell_l, cell_h, grid_origin):
        """Build degenerate-triangle edge mesh for TO wireframe."""
        em = rg.Mesh()
        _va = em.Vertices.Add
        _fa = em.Faces.AddFace
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        sw = cell_w * 0.25; sl = cell_l * 0.25; sh = cell_h * 0.25
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        scaled = tuple((vx * sw, vy * sl, vz * sh)
                        for (vx, vy, vz) in self._TO_VERTS)
        to_edges = self._TO_EDGES
        b = 0
        for (fx, fy, fz, val) in voxels:
            cx = ox0 + fx * cell_w + hw
            cy = oy0 + fy * cell_l + hl
            cz = oz0 + fz * cell_h + hh
            for (ei, ej) in to_edges:
                dx0, dy0, dz0 = scaled[ei]
                dx1, dy1, dz1 = scaled[ej]
                _va(cx + dx0, cy + dy0, cz + dz0)
                _va(cx + dx1, cy + dy1, cz + dz1)
                _va(cx + dx1, cy + dy1, cz + dz1)
                _fa(b, b + 1, b + 2)
                b += 3
        return em

    def update_display(self, voxels, cell_w, cell_l, cell_h, color,
                       show_bounds, bounds_color, show_edges, edge_color,
                       grid_x, grid_y, grid_z, grid_origin, grid_type=0):
        """Rebuild conduit display mesh and bounding box.
        grid_type 0=cube, 1=truncated octahedron."""
        if grid_type == 1:
            self.conduit.mesh = self.build_mesh_to(
                voxels, cell_w, cell_l, cell_h, color, grid_origin)
            if show_edges:
                self.conduit.edge_mesh = self._build_to_edge_mesh(
                    voxels, cell_w, cell_l, cell_h, grid_origin)
            else:
                self.conduit.edge_mesh = None
        else:
            self.conduit.mesh = self.build_mesh(
                voxels, cell_w, cell_l, cell_h, color, grid_origin)
            self.conduit.edge_mesh = None
        self.conduit.show_bounds = show_bounds
        self.conduit.show_edges = show_edges
        self.conduit.edge_color = edge_color

        ox = grid_origin.X; oy = grid_origin.Y; oz = grid_origin.Z
        bx = grid_x * cell_w; by = grid_y * cell_l; bz = grid_z * cell_h
        if show_bounds:
            p = [rg.Point3d(ox,    oy,    oz),
                 rg.Point3d(ox+bx, oy,    oz),
                 rg.Point3d(ox+bx, oy+by, oz),
                 rg.Point3d(ox,    oy+by, oz),
                 rg.Point3d(ox,    oy,    oz+bz),
                 rg.Point3d(ox+bx, oy,    oz+bz),
                 rg.Point3d(ox+bx, oy+by, oz+bz),
                 rg.Point3d(ox,    oy+by, oz+bz)]
            edges = [(0,1),(1,2),(2,3),(3,0),
                     (4,5),(5,6),(6,7),(7,4),
                     (0,4),(1,5),(2,6),(3,7)]
            self.conduit.bound_lines = [rg.Line(p[a], p[b]) for a, b in edges]
        else:
            self.conduit.bound_lines = []
        self.conduit.bound_color = bounds_color
        self.conduit.bbox = rg.BoundingBox(
            rg.Point3d(ox, oy, oz),
            rg.Point3d(ox + bx, oy + by, oz + bz))
        sc.doc.Views.Redraw()

    def bake(self, color, grid_origin, use_vertex_colors=True):
        """Add voxel mesh to document."""
        if not self.conduit.mesh:
            return
        if use_vertex_colors:
            attr = Rhino.DocObjects.ObjectAttributes()
            attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
            attr.ObjectColor = color
            sc.doc.Objects.AddMesh(self.conduit.mesh, attr)
        else:
            clean = self.conduit.mesh.DuplicateMesh()
            clean.VertexColors.Clear()
            sc.doc.Objects.AddMesh(clean)
        sc.doc.Views.Redraw()

    def bake_brep(self, grid_origin):
        """Convert each voxel face cluster to a joined brep and add to document."""
        mesh = self.conduit.mesh
        if not mesh or mesh.Faces.Count == 0:
            return 0
        rs.EnableRedraw(False)
        count = 0
        fi = 0
        total = mesh.Faces.Count
        while fi < total:
            face = mesh.Faces[fi]
            nv = 4 if face.IsQuad else 3
            chunk_faces = 6
            if fi + chunk_faces > total:
                chunk_faces = total - fi
            sub = rg.Mesh()
            for fj in range(fi, fi + chunk_faces):
                f = mesh.Faces[fj]
                vs = []
                for vi in (f.A, f.B, f.C):
                    v = mesh.Vertices[vi]
                    vs.append(rg.Point3d(v.X, v.Y, v.Z))
                if f.IsQuad:
                    v = mesh.Vertices[f.D]
                    vs.append(rg.Point3d(v.X, v.Y, v.Z))
                base_i = sub.Vertices.Count
                for v in vs:
                    sub.Vertices.Add(v)
                if f.IsQuad:
                    sub.Faces.AddFace(base_i, base_i+1, base_i+2, base_i+3)
                else:
                    sub.Faces.AddFace(base_i, base_i+1, base_i+2)
            brep = rg.Brep.CreateFromMesh(sub, False)
            if brep:
                sc.doc.Objects.AddBrep(brep)
                count += 1
            fi += chunk_faces
        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()
        return count

    def bake_boxes(self, layer_name, cell_w, cell_l, cell_h, grid_origin):
        """Create individual box breps for each voxel."""
        voxels = self.voxels
        if not voxels:
            return 0
        if layer_name:
            if not rs.IsLayer(layer_name):
                rs.AddLayer(layer_name)
        rs.EnableRedraw(False)
        ox = grid_origin.X; oy = grid_origin.Y; oz = grid_origin.Z
        count = 0
        _add = sc.doc.Objects.AddBrep
        for (fx, fy, fz, val) in voxels:
            x = ox + fx * cell_w
            y = oy + fy * cell_l
            z = oz + fz * cell_h
            bb = rg.BoundingBox(
                rg.Point3d(x, y, z),
                rg.Point3d(x + cell_w, y + cell_l, z + cell_h))
            brep = rg.Brep.CreateFromBox(bb)
            if brep:
                guid = _add(brep)
                if guid and guid != System.Guid.Empty and layer_name:
                    rs.ObjectLayer(guid, layer_name)
                count += 1
        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()
        return count

    def dispose(self):
        self.conduit.Enabled = False
        sc.doc.Views.Redraw()


# ---------------------------------------------------------------------------
# Eto.Forms Dialog
# ---------------------------------------------------------------------------
class SculptDialog(forms.Form):

    def __init__(self):
        super(SculptDialog, self).__init__()
        self.Title = "Voxel Curve Sculpt"
        self.Padding = drawing.Padding(6)
        self.Resizable = True
        self.MinimumSize = drawing.Size(420, 700)
        self.Size = drawing.Size(420, 800)

        self.system = VoxelSystem()
        self.bounds_geometries = []
        self.bounds_meshes = []
        self.bounds_aabb = None
        self.attractor_curves = []
        self.voxel_color = System.Drawing.Color.FromArgb(100, 180, 255)
        self.system.conduit.shaded_material = rd.DisplayMaterial(
            System.Drawing.Color.FromArgb(100, 180, 255))
        self.edge_color = System.Drawing.Color.FromArgb(40, 40, 40)
        self.bounds_color = System.Drawing.Color.FromArgb(80, 80, 80)

        self._compute_dirty = False
        self._display_dirty = False
        self._link_guard = False

        self._build_ui()

        self.system.conduit.Enabled = True

        self._timer = forms.UITimer()
        self._timer.Interval = 0.06
        self._timer.Elapsed += self._on_timer_tick
        self._timer.Start()

        self._full_regenerate()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self):
        layout = forms.DynamicLayout()
        layout.DefaultSpacing = drawing.Size(4, 2)
        layout.DefaultPadding = drawing.Padding(4)

        self.chk_live = forms.CheckBox()
        self.chk_live.Text = "Live Update"
        self.chk_live.Checked = True
        layout.AddRow(self.chk_live)

        # -- bounding geometry (first section) -----------------------------
        inner, _sec_finish = self._section(layout, "Bounding Geometry", True)

        btn_pick_bounds = forms.Button()
        btn_pick_bounds.Text = "Assign Bounds"
        btn_pick_bounds.Click += self._on_pick_bounds
        btn_clr_bounds = forms.Button()
        btn_clr_bounds.Text = "Clear Bounds"
        btn_clr_bounds.Click += self._on_clear_bounds
        inner.AddRow(btn_pick_bounds, btn_clr_bounds)

        self.lbl_bounds = forms.Label()
        self.lbl_bounds.Text = "Bounds: None"
        inner.AddRow(self.lbl_bounds)

        self.chk_use_bounds = forms.CheckBox()
        self.chk_use_bounds.Text = "Use Bounds"
        self.chk_use_bounds.Checked = False
        self.chk_use_bounds.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_use_bounds)

        self.chk_bounds_center = forms.CheckBox()
        self.chk_bounds_center.Text = "Auto-Center on Bounds"
        self.chk_bounds_center.Checked = True
        self.chk_bounds_center.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_bounds_center)

        lbl_clip = forms.Label()
        lbl_clip.Text = "Clip Mode"
        lbl_clip.Width = 105
        self.dd_clip_mode = forms.DropDown()
        self.dd_clip_mode.Width = 150
        self.dd_clip_mode.Items.Add("Center Point")
        self.dd_clip_mode.Items.Add("All Corners")
        self.dd_clip_mode.SelectedIndex = 0
        self.dd_clip_mode.SelectedIndexChanged += lambda s, e: self._mark_compute()
        inner.AddRow(lbl_clip, self.dd_clip_mode)

        _sec_finish()

        # -- grid dimensions -----------------------------------------------
        inner, _sec_finish = self._section(layout, "Grid Dimensions", True)

        lbl_gt = forms.Label()
        lbl_gt.Text = "Grid Type"
        lbl_gt.Width = 105
        self.dd_grid_type = forms.DropDown()
        self.dd_grid_type.Width = 150
        self.dd_grid_type.Items.Add("Cube")
        self.dd_grid_type.Items.Add("Truncated Octahedron")
        self.dd_grid_type.SelectedIndex = 0
        self.dd_grid_type.SelectedIndexChanged += lambda s, e: self._mark_compute()
        inner.AddRow(lbl_gt, self.dd_grid_type)

        self.chk_link_grid = forms.CheckBox()
        self.chk_link_grid.Text = "Link Grid XYZ"
        self.chk_link_grid.Checked = False
        inner.AddRow(self.chk_link_grid)

        self.sld_gx, self.txt_gx = self._int_slider(inner, "Grid X", 1, 200, 10, self._mark_compute)
        self.sld_gy, self.txt_gy = self._int_slider(inner, "Grid Y", 1, 200, 10, self._mark_compute)
        self.sld_gz, self.txt_gz = self._int_slider(inner, "Grid Z", 1, 200, 10, self._mark_compute)

        def _sync_grid_x(s, e):
            if self._link_guard or not self.chk_link_grid.Checked:
                return
            self._link_guard = True
            self.sld_gy.Value = self.sld_gx.Value
            self.sld_gz.Value = self.sld_gx.Value
            self._link_guard = False
        def _sync_grid_y(s, e):
            if self._link_guard or not self.chk_link_grid.Checked:
                return
            self._link_guard = True
            self.sld_gx.Value = self.sld_gy.Value
            self.sld_gz.Value = self.sld_gy.Value
            self._link_guard = False
        def _sync_grid_z(s, e):
            if self._link_guard or not self.chk_link_grid.Checked:
                return
            self._link_guard = True
            self.sld_gx.Value = self.sld_gz.Value
            self.sld_gy.Value = self.sld_gz.Value
            self._link_guard = False
        self.sld_gx.ValueChanged += _sync_grid_x
        self.sld_gy.ValueChanged += _sync_grid_y
        self.sld_gz.ValueChanged += _sync_grid_z

        self.chk_link_voxel = forms.CheckBox()
        self.chk_link_voxel.Text = "Link Voxel Size"
        self.chk_link_voxel.Checked = False
        inner.AddRow(self.chk_link_voxel)

        self.sld_cw, self.txt_cw = self._float_slider(inner, "Voxel Width (X)", 1.0, 5000.0, 1000.0, self._mark_compute)
        self.sld_cl, self.txt_cl = self._float_slider(inner, "Voxel Length (Y)", 1.0, 5000.0, 1000.0, self._mark_compute)
        self.sld_ch, self.txt_ch = self._float_slider(inner, "Voxel Height (Z)", 1.0, 5000.0, 1000.0, self._mark_compute)

        def _sync_voxel_w(s, e):
            if self._link_guard or not self.chk_link_voxel.Checked:
                return
            self._link_guard = True
            self.sld_cl.Value = self.sld_cw.Value
            self.sld_ch.Value = self.sld_cw.Value
            self._link_guard = False
        def _sync_voxel_l(s, e):
            if self._link_guard or not self.chk_link_voxel.Checked:
                return
            self._link_guard = True
            self.sld_cw.Value = self.sld_cl.Value
            self.sld_ch.Value = self.sld_cl.Value
            self._link_guard = False
        def _sync_voxel_h(s, e):
            if self._link_guard or not self.chk_link_voxel.Checked:
                return
            self._link_guard = True
            self.sld_cw.Value = self.sld_ch.Value
            self.sld_cl.Value = self.sld_ch.Value
            self._link_guard = False
        self.sld_cw.ValueChanged += _sync_voxel_w
        self.sld_cl.ValueChanged += _sync_voxel_l
        self.sld_ch.ValueChanged += _sync_voxel_h

        _sec_finish()

        # -- curve attractors -----------------------------------------------
        inner, _sec_finish = self._section(layout, "Curve Attractors", True)

        btn_pick = forms.Button()
        btn_pick.Text = "Pick Curves"
        btn_pick.Click += self._on_pick_curves
        btn_clear = forms.Button()
        btn_clear.Text = "Clear Curves"
        btn_clear.Click += self._on_clear_curves
        inner.AddRow(btn_pick, btn_clear)

        self.lbl_curves = forms.Label()
        self.lbl_curves.Text = "Curves: 0"
        inner.AddRow(self.lbl_curves)

        self.chk_show_curves = forms.CheckBox()
        self.chk_show_curves.Text = "Show Curves"
        self.chk_show_curves.Checked = True
        self.chk_show_curves.CheckedChanged += self._on_toggle_curves

        self.btn_curve_col = forms.Button()
        self.btn_curve_col.Text = "Curve Colour"
        self.btn_curve_col.Width = 110
        self.btn_curve_col.BackgroundColor = drawing.Color.FromArgb(255, 100, 50)
        self.btn_curve_col.Click += self._on_pick_curve_color
        inner.AddRow(self.chk_show_curves, self.btn_curve_col)

        self.sld_crv_thick, self.txt_crv_thick = self._int_slider(
            inner, "Curve Thickness", 1, 10, 2, self._on_curve_display)

        _sec_finish()

        # -- influence ------------------------------------------------------
        inner, _sec_finish = self._section(layout, "Influence", True)

        self.chk_carve = forms.CheckBox()
        self.chk_carve.Text = "Carve Mode (remove voxels near curves)"
        self.chk_carve.Checked = False
        self.chk_carve.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_carve)

        self.chk_solid = forms.CheckBox()
        self.chk_solid.Text = "Solid Base (start grid filled)"
        self.chk_solid.Checked = True
        self.chk_solid.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_solid)

        self.sld_radius, self.txt_radius = self._int_slider(
            inner, "Influence Radius", 0, 30, 5, self._mark_compute)
        self.sld_strength, self.txt_strength = self._float_slider(
            inner, "Strength", 0.0, 3.0, 1.0, self._mark_compute)

        lbl_fo = forms.Label()
        lbl_fo.Text = "Falloff"
        lbl_fo.Width = 105
        self.dd_falloff = forms.DropDown()
        self.dd_falloff.Width = 150
        self.dd_falloff.Items.Add("Linear")
        self.dd_falloff.Items.Add("Quadratic")
        self.dd_falloff.Items.Add("Smooth")
        self.dd_falloff.SelectedIndex = 0
        self.dd_falloff.SelectedIndexChanged += lambda s, e: self._mark_compute()
        inner.AddRow(lbl_fo, self.dd_falloff)

        _sec_finish()

        # -- noise ----------------------------------------------------------
        inner, _sec_finish = self._section(layout, "Noise Variation", False)

        self.sld_scale, self.txt_scale = self._float_slider(
            inner, "Noise Scale", 0.01, 1.0, 0.15, self._mark_compute)
        self.sld_thresh, self.txt_thresh = self._float_slider(
            inner, "Threshold", 0.0, 1.0, 0.45, self._mark_compute)
        self.sld_oct, self.txt_oct = self._int_slider(
            inner, "Octaves", 1, 6, 3, self._mark_compute)
        self.sld_seed, self.txt_seed = self._int_slider(
            inner, "Seed", 0, 100, 0, self._mark_compute)

        _sec_finish()

        # -- display --------------------------------------------------------
        inner, _sec_finish = self._section(layout, "Display", False)

        self.chk_voxels = forms.CheckBox()
        self.chk_voxels.Text = "Show Voxels"
        self.chk_voxels.Checked = True
        self.chk_voxels.CheckedChanged += lambda s, e: self._mark_display()

        self.chk_edges = forms.CheckBox()
        self.chk_edges.Text = "Show Edges"
        self.chk_edges.Checked = True
        self.chk_edges.CheckedChanged += lambda s, e: self._mark_display()
        inner.AddRow(self.chk_voxels, self.chk_edges)

        self.chk_bounds_vis = forms.CheckBox()
        self.chk_bounds_vis.Text = "Show Bounds"
        self.chk_bounds_vis.Checked = True
        self.chk_bounds_vis.CheckedChanged += lambda s, e: self._mark_display()
        inner.AddRow(self.chk_bounds_vis)

        self.sld_opacity, self.txt_opacity = self._int_slider(
            inner, "Opacity", 0, 255, 255, self._on_display_update)

        self.btn_vox_col = forms.Button()
        self.btn_vox_col.Text = "Voxel Colour"
        self.btn_vox_col.Width = 110
        self.btn_vox_col.BackgroundColor = drawing.Color.FromArgb(100, 180, 255)
        self.btn_vox_col.Click += self._on_pick_voxel_color

        self.btn_edge_col = forms.Button()
        self.btn_edge_col.Text = "Edge Colour"
        self.btn_edge_col.Width = 110
        self.btn_edge_col.BackgroundColor = drawing.Color.FromArgb(40, 40, 40)
        self.btn_edge_col.Click += self._on_pick_edge_color
        inner.AddRow(self.btn_vox_col, self.btn_edge_col)

        self.btn_bounds_col = forms.Button()
        self.btn_bounds_col.Text = "Bounds Colour"
        self.btn_bounds_col.Width = 110
        self.btn_bounds_col.BackgroundColor = drawing.Color.FromArgb(80, 80, 80)
        self.btn_bounds_col.Click += self._on_pick_bounds_color
        inner.AddRow(self.btn_bounds_col)

        _sec_finish()

        # -- controls ------------------------------------------------------
        inner, _sec_finish = self._section(layout, "Controls", True)

        btn_refresh = forms.Button()
        btn_refresh.Text = "Refresh"
        btn_refresh.Click += self._on_refresh

        btn_bake = forms.Button()
        btn_bake.Text = "Bake"
        btn_bake.Click += self._on_bake

        btn_bake_brep = forms.Button()
        btn_bake_brep.Text = "Bake Brep"
        btn_bake_brep.Click += self._on_bake_brep

        btn_clear = forms.Button()
        btn_clear.Text = "Clear"
        btn_clear.Click += self._on_clear
        inner.AddRow(btn_refresh, btn_bake, btn_bake_brep, btn_clear)

        self.lbl_status = forms.Label()
        self.lbl_status.Text = "Ready"
        inner.AddRow(self.lbl_status)

        _sec_finish()

        scrollable = forms.Scrollable()
        scrollable.ExpandContentWidth = True
        scrollable.Content = layout
        self.Content = scrollable
        self.Closed += self._on_closed

    # -- widget factories --------------------------------------------------
    def _bold(self, text):
        lbl = forms.Label()
        lbl.Text = text
        lbl.Font = drawing.Font(lbl.Font.Family, lbl.Font.Size,
                                drawing.FontStyle.Bold)
        return lbl

    def _section(self, parent_layout, title, expanded=False):
        """Create a collapsible section with arrow indicator."""
        arrow_open = u"\u25BC "
        arrow_closed = u"\u25B6 "

        header = forms.Label()
        header.Text = (arrow_open if expanded else arrow_closed) + title
        header.Font = drawing.Font(header.Font.Family,
                                   header.Font.Size + 1,
                                   drawing.FontStyle.Bold)
        header.Cursor = forms.Cursors.Pointer

        panel = forms.DynamicLayout()
        panel.DefaultSpacing = drawing.Size(4, 4)
        panel.Padding = drawing.Padding(8, 4, 4, 4)
        panel.Visible = expanded

        def toggle(sender, e):
            panel.Visible = not panel.Visible
            if panel.Visible:
                header.Text = arrow_open + title
            else:
                header.Text = arrow_closed + title

        header.MouseDown += toggle

        sep = forms.Label()
        sep.Text = ""
        sep.Height = 2

        def finish():
            parent_layout.AddRow(sep)
            parent_layout.AddRow(header)
            parent_layout.AddRow(panel)

        return panel, finish

    def _int_slider(self, layout, name, lo, hi, default, on_change):
        lbl = forms.Label()
        lbl.Text = name
        lbl.Width = 105

        sld = forms.Slider()
        sld.MinValue = lo
        sld.MaxValue = hi
        sld.Value = default
        sld.Width = 150

        txt = forms.TextBox()
        txt.Text = str(default)
        txt.Width = 50

        guard = {"u": False}

        def _sld(s, e):
            if guard["u"]:
                return
            guard["u"] = True
            txt.Text = str(sld.Value)
            guard["u"] = False
            on_change()

        def _txt(s, e):
            if guard["u"]:
                return
            try:
                v = int(txt.Text)
                if v < lo:
                    v = lo
                elif v > hi:
                    v = hi
                guard["u"] = True
                sld.Value = v
                guard["u"] = False
                on_change()
            except:
                pass

        sld.ValueChanged += _sld
        txt.TextChanged += _txt
        layout.AddRow(lbl, sld, txt)
        return sld, txt

    def _float_slider(self, layout, name, lo, hi, default, on_change):
        lbl = forms.Label()
        lbl.Text = name
        lbl.Width = 105

        steps = 200
        sld = forms.Slider()
        sld.MinValue = 0
        sld.MaxValue = steps
        sld.Value = int((default - lo) / (hi - lo) * steps)
        sld.Width = 150

        txt = forms.TextBox()
        txt.Text = "{:.3f}".format(default)
        txt.Width = 50

        guard = {"u": False}

        def _sld(s, e):
            if guard["u"]:
                return
            guard["u"] = True
            v = lo + (hi - lo) * sld.Value / float(steps)
            txt.Text = "{:.3f}".format(v)
            guard["u"] = False
            on_change()

        def _txt(s, e):
            if guard["u"]:
                return
            try:
                v = float(txt.Text)
                if v < lo:
                    v = lo
                elif v > hi:
                    v = hi
                guard["u"] = True
                sld.Value = int((v - lo) / (hi - lo) * steps)
                guard["u"] = False
                on_change()
            except:
                pass

        sld.ValueChanged += _sld
        txt.TextChanged += _txt
        layout.AddRow(lbl, sld, txt)
        return sld, txt

    def _fval(self, txt, sld, lo, hi):
        try:
            v = float(txt.Text)
            if lo <= v <= hi:
                return v
        except:
            pass
        return lo + (hi - lo) * sld.Value / 200.0

    def _ival(self, txt, sld):
        try:
            v = int(txt.Text)
            if v >= 1:
                return v
        except:
            pass
        return sld.Value

    # -- read params -------------------------------------------------------
    def _read_params(self):
        gx = self._ival(self.txt_gx, self.sld_gx)
        gy = self._ival(self.txt_gy, self.sld_gy)
        gz = self._ival(self.txt_gz, self.sld_gz)
        cw = self._fval(self.txt_cw, self.sld_cw, 1.0, 5000.0)
        cl = self._fval(self.txt_cl, self.sld_cl, 1.0, 5000.0)
        ch = self._fval(self.txt_ch, self.sld_ch, 1.0, 5000.0)
        scale = self._fval(self.txt_scale, self.sld_scale, 0.01, 1.0)
        thresh = self._fval(self.txt_thresh, self.sld_thresh, 0.0, 1.0)
        octaves = self._ival(self.txt_oct, self.sld_oct)
        seed = self._ival(self.txt_seed, self.sld_seed)
        solid = self.chk_solid.Checked == True
        radius = self._ival(self.txt_radius, self.sld_radius)
        strength = self._fval(self.txt_strength, self.sld_strength, 0.0, 3.0)
        carve = self.chk_carve.Checked == True
        falloff = self.dd_falloff.SelectedIndex
        use_bounds = self.chk_use_bounds.Checked == True
        bounds_strict = self.dd_clip_mode.SelectedIndex == 1
        grid_type = self.dd_grid_type.SelectedIndex
        return (gx, gy, gz, cw, cl, ch, scale, thresh, octaves, seed,
                solid, radius, strength, carve, falloff,
                use_bounds, bounds_strict, grid_type)

    # -- compute grid origin -----------------------------------------------
    def _grid_origin(self, gx, gy, gz, cw, cl, ch):
        if (self.chk_bounds_center.Checked == True and
                self.bounds_aabb and self.bounds_aabb.IsValid and
                self.chk_use_bounds.Checked == True):
            c = self.bounds_aabb.Center
            return rg.Point3d(
                c.X - (gx * cw) * 0.5,
                c.Y - (gy * cl) * 0.5,
                c.Z - (gz * ch) * 0.5)
        return rg.Point3d.Origin

    # -- dirty flags -------------------------------------------------------
    def _mark_compute(self):
        if self.chk_live.Checked == True:
            self._compute_dirty = True

    def _mark_display(self):
        if self.chk_live.Checked == True:
            self._display_dirty = True

    def _on_timer_tick(self, sender, e):
        if self._compute_dirty:
            self._compute_dirty = False
            self._display_dirty = False
            self._full_regenerate()
        elif self._display_dirty:
            self._display_dirty = False
            self._display_only()

    # -- full regenerate ---------------------------------------------------
    def _full_regenerate(self):
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        scale, thresh, octaves, seed = p[6], p[7], p[8], p[9]
        solid = p[10]
        radius, strength, carve, falloff = p[11], p[12], p[13], p[14]
        use_bounds, bounds_strict = p[15], p[16]
        grid_type = p[17]

        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        total = gx * gy * gz
        self.lbl_status.Text = "Computing {} cells...".format(total)

        voxels = self.system.generate(
            gx, gy, gz, cw, cl, ch, scale, thresh, octaves, seed,
            solid, self.attractor_curves, radius, strength, carve, falloff,
            use_bounds, self.bounds_meshes, self.bounds_aabb, bounds_strict,
            grid_type, origin)

        show_bounds = self.chk_bounds_vis.Checked == True
        show_edges = self.chk_edges.Checked == True
        self.system.update_display(
            voxels, cw, cl, ch, self.voxel_color,
            show_bounds, self.bounds_color, show_edges, self.edge_color,
            gx, gy, gz, origin, grid_type)

        self.system.conduit.show_voxels = self.chk_voxels.Checked == True
        self.system.conduit.voxel_opacity = self._ival(
            self.txt_opacity, self.sld_opacity)
        self.lbl_status.Text = "Showing {} / {} voxels".format(
            len(voxels), total)

    # -- display-only refresh ----------------------------------------------
    def _display_only(self):
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        grid_type = p[17]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        voxels = self.system.voxels
        show_bounds = self.chk_bounds_vis.Checked == True
        show_edges = self.chk_edges.Checked == True
        self.system.update_display(
            voxels, cw, cl, ch, self.voxel_color,
            show_bounds, self.bounds_color, show_edges, self.edge_color,
            gx, gy, gz, origin, grid_type)
        self.system.conduit.show_voxels = self.chk_voxels.Checked == True
        self.system.conduit.voxel_opacity = self._ival(
            self.txt_opacity, self.sld_opacity)

    # -- button handlers ---------------------------------------------------
    def _on_refresh(self, sender, e):
        self._full_regenerate()

    def _on_bake(self, sender, e):
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        self.system.bake(self.voxel_color, origin, True)
        self.lbl_status.Text = "Baked {} voxels to document".format(
            len(self.system.voxels))

    def _on_bake_brep(self, sender, e):
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        n = len(self.system.voxels)
        if n > 5000:
            self.lbl_status.Text = "Baking {} breps...".format(n)
        layer = "Voxel_Sculpt"
        count = self.system.bake_boxes(layer, cw, cl, ch, origin)
        if count:
            self.lbl_status.Text = "Baked {} breps".format(count)
        else:
            self.lbl_status.Text = "Nothing to bake"

    def _on_clear(self, sender, e):
        self.system.voxels = []
        self.system.conduit.mesh = None
        self.system.conduit.edge_mesh = None
        self.system.conduit.bound_lines = []
        sc.doc.Views.Redraw()
        self.lbl_status.Text = "Cleared"

    # -- bounds handlers ---------------------------------------------------
    def _on_pick_bounds(self, sender, e):
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select closed mesh or brep for bounding volume")
        go.GeometryFilter = (
            Rhino.DocObjects.ObjectType.Mesh |
            Rhino.DocObjects.ObjectType.Brep |
            Rhino.DocObjects.ObjectType.Extrusion)
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            self.bounds_geometries = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if geo:
                    dup = geo.Duplicate()
                    if isinstance(dup, rg.Extrusion):
                        brep = dup.ToBrep()
                        if brep:
                            dup = brep
                    self.bounds_geometries.append(dup)
            self._preprocess_bounds()
            self.lbl_bounds.Text = "Bounds: {} object(s)".format(
                len(self.bounds_geometries))
            self.chk_use_bounds.Checked = True
        self.Visible = True
        self._full_regenerate()

    def _on_clear_bounds(self, sender, e):
        self.bounds_geometries = []
        self.bounds_meshes = []
        self.bounds_aabb = None
        self.chk_use_bounds.Checked = False
        self.lbl_bounds.Text = "Bounds: None"
        self._full_regenerate()

    def _preprocess_bounds(self):
        """Convert assigned bounds geometry to closed meshes for fast
        IsPointInside checks and pre-compute the combined AABB."""
        self.bounds_meshes = []
        aabb = rg.BoundingBox.Empty
        for geo in self.bounds_geometries:
            if isinstance(geo, rg.Mesh):
                if geo.IsClosed:
                    self.bounds_meshes.append(geo)
                    aabb.Union(geo.GetBoundingBox(True))
            elif isinstance(geo, rg.Brep):
                meshes = rg.Mesh.CreateFromBrep(
                    geo, rg.MeshingParameters.FastRenderMesh)
                if meshes:
                    combined = rg.Mesh()
                    for m in meshes:
                        combined.Append(m)
                    if combined.IsClosed:
                        self.bounds_meshes.append(combined)
                        aabb.Union(combined.GetBoundingBox(True))
        self.bounds_aabb = aabb if aabb.IsValid else None

    # -- curve handlers ----------------------------------------------------
    def _on_pick_curves(self, sender, e):
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select attractor curves")
        go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            curves = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if geo:
                    curves.append(geo.Duplicate())
            self.attractor_curves = curves
            self.system.conduit.attractor_curves = list(curves)
            self.lbl_curves.Text = "Curves: {}".format(len(curves))
        self.Visible = True
        self._full_regenerate()

    def _on_clear_curves(self, sender, e):
        self.attractor_curves = []
        self.system.conduit.attractor_curves = []
        self.lbl_curves.Text = "Curves: 0"
        self._full_regenerate()

    def _on_toggle_curves(self, sender, e):
        self.system.conduit.show_curves = self.chk_show_curves.Checked == True
        sc.doc.Views.Redraw()

    def _on_curve_display(self):
        self.system.conduit.curve_thickness = self._ival(
            self.txt_crv_thick, self.sld_crv_thick)
        sc.doc.Views.Redraw()

    # -- display handlers --------------------------------------------------
    def _on_display_update(self):
        self._mark_display()

    def _on_pick_voxel_color(self, sender, e):
        cd = forms.ColorDialog()
        c = self.voxel_color
        cd.Color = drawing.Color.FromArgb(c.R, c.G, c.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.voxel_color = System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb)
            self.system.conduit.shaded_material = rd.DisplayMaterial(
                System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb))
            self.btn_vox_col.BackgroundColor = c
            self._mark_compute()

    def _on_pick_edge_color(self, sender, e):
        cd = forms.ColorDialog()
        c = self.edge_color
        cd.Color = drawing.Color.FromArgb(c.R, c.G, c.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.edge_color = System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb)
            self.btn_edge_col.BackgroundColor = c
            self._mark_display()

    def _on_pick_bounds_color(self, sender, e):
        cd = forms.ColorDialog()
        c = self.bounds_color
        cd.Color = drawing.Color.FromArgb(c.R, c.G, c.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.bounds_color = System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb)
            self.btn_bounds_col.BackgroundColor = c
            self._mark_display()

    def _on_pick_curve_color(self, sender, e):
        cd = forms.ColorDialog()
        c = self.system.conduit.curve_color
        cd.Color = drawing.Color.FromArgb(c.R, c.G, c.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.system.conduit.curve_color = System.Drawing.Color.FromArgb(
                c.Rb, c.Gb, c.Bb)
            self.btn_curve_col.BackgroundColor = c
            sc.doc.Views.Redraw()

    # -- cleanup -----------------------------------------------------------
    def _on_closed(self, sender, e):
        if hasattr(self, '_timer'):
            self._timer.Stop()
        self.system.dispose()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    dlg = SculptDialog()
    dlg.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    dlg.Show()

if __name__ == "__main__":
    main()
else:
    main()
