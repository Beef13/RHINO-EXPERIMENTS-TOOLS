# Voxel Field Tool v01
# Perlin noise driven voxel carving with real-time Eto UI
# Environment: Rhino 8 Python
# Inputs: Grid dimensions, noise parameters, threshold, attractor points, base geometry
# Outputs: Voxel box geometry previewed live via display conduit

import Rhino
import Rhino.Geometry as rg
import Rhino.Display as rd
import scriptcontext as sc
import System
import System.Drawing
import math
import random

try:
    import Eto.Forms as forms
    import Eto.Drawing as drawing
except:
    import Rhino.UI
    forms = Rhino.UI.EtoExtensions


# ---------------------------------------------------------------------------
# Perlin Noise
# Deterministic 3D gradient noise generator. Produces smooth, continuous
# pseudorandom values in [-1, 1] that tile naturally. Used as the primary
# density field for voxel generation.
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
# Rhino DisplayConduit subclass that draws preview geometry (voxel mesh,
# bounding box) directly into the viewport without baking to the document.
# Toggled on/off via .Enabled.
# ---------------------------------------------------------------------------
class VoxelConduit(rd.DisplayConduit):
    def __init__(self):
        super(VoxelConduit, self).__init__()
        self.mesh = None
        self.edge_mesh = None
        self.bbox = rg.BoundingBox.Empty
        self.bound_lines = []
        self.bound_color = System.Drawing.Color.FromArgb(80, 80, 80)
        self.edge_color = System.Drawing.Color.FromArgb(40, 40, 40)
        self.edge_opacity = 255
        self.show_bounds = True
        self.show_edges = True
        self.show_voxels = True
        self.use_vertex_colors = True
        self.shaded_material = rd.DisplayMaterial()
        self.voxel_opacity = 255
        self._cached_trans_mat = None
        self._cached_trans_opacity = -1
        self.wander_trails = []
        self.wander_color = System.Drawing.Color.FromArgb(255, 200, 50)
        self.wander_opacity = 255
        self.wander_thickness = 2
        self.show_wander = True

        self.slime_trails = []
        self.slime_color = System.Drawing.Color.FromArgb(50, 220, 120)
        self.slime_opacity = 255
        self.slime_thickness = 2
        self.show_slime = True

        self.path_points = []
        self.path_point_color = System.Drawing.Color.FromArgb(255, 80, 80)
        self.path_point_size = 8
        self.show_path_points = True
        self._cached_edge_color = None
        self._cached_eo = -1

        self.influence_trails = []
        self.influence_color = System.Drawing.Color.FromArgb(255, 130, 50)
        self.influence_thickness = 2
        self.show_influence = True

    def CalculateBoundingBox(self, e):
        if self.bbox.IsValid:
            e.IncludeBoundingBox(self.bbox)

    def PostDrawObjects(self, e):
        disp = e.Display
        if self.show_voxels and self.mesh and self.mesh.Vertices.Count > 0:
            if self.voxel_opacity >= 255:
                if self.use_vertex_colors:
                    disp.DrawMeshFalseColors(self.mesh)
                else:
                    disp.DrawMeshShaded(self.mesh, self.shaded_material)
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
                eo = self.edge_opacity
                ec = self.edge_color
                if eo < 255:
                    if self._cached_edge_color is None or eo != self._cached_eo:
                        self._cached_edge_color = System.Drawing.Color.FromArgb(
                            eo, ec.R, ec.G, ec.B)
                        self._cached_eo = eo
                    ec = self._cached_edge_color
                disp.DrawMeshWires(wire, ec)
        if self.show_bounds and self.bound_lines:
            bc = self.bound_color
            _dl = disp.DrawLine
            for ln in self.bound_lines:
                _dl(ln, bc, 1)

    def DrawForeground(self, e):
        disp = e.Display
        if self.show_wander and self.wander_trails:
            wc = self.wander_color
            if self.wander_opacity < 255:
                wc = System.Drawing.Color.FromArgb(
                    self.wander_opacity, wc.R, wc.G, wc.B)
            wt = self.wander_thickness
            _dp = disp.DrawPolyline
            for trail in self.wander_trails:
                if len(trail) > 1:
                    _dp(trail, wc, wt)
        if self.show_slime and self.slime_trails:
            sc_col = self.slime_color
            if self.slime_opacity < 255:
                sc_col = System.Drawing.Color.FromArgb(
                    self.slime_opacity, sc_col.R, sc_col.G, sc_col.B)
            st = self.slime_thickness
            _dp = disp.DrawPolyline
            for trail in self.slime_trails:
                if len(trail) > 1:
                    _dp(trail, sc_col, st)
        if self.show_influence and self.influence_trails:
            ic = self.influence_color
            it = self.influence_thickness
            _dp = disp.DrawPolyline
            for trail in self.influence_trails:
                if len(trail) > 1:
                    _dp(trail, ic, it)
        if self.show_path_points and self.path_points:
            _dppt = disp.DrawPoint
            _style = rd.PointStyle.RoundControlPoint
            ps = self.path_point_size
            pc = self.path_point_color
            for pt in self.path_points:
                _dppt(pt, _style, ps, pc)


# ---------------------------------------------------------------------------
# Voxel System
# Core engine: generates voxel fields from Perlin noise and builds meshes
# for display.
# ---------------------------------------------------------------------------
class VoxelSystem(object):
    def __init__(self):
        self.conduit = VoxelConduit()
        self.conduit.Enabled = True
        self.perlin = PerlinNoise(0)
        self.voxels = []
        self.custom_base_mesh = None
        self.custom_base_edges = []

    def _closest_dist(self, pt, geo):
        """Return shortest distance from pt to any Rhino geometry type (Curve,
        Mesh, Brep, Surface). Returns infinity on failure."""
        try:
            if isinstance(geo, rg.Curve):
                rc, t = geo.ClosestPoint(pt)
                if rc:
                    return pt.DistanceTo(geo.PointAt(t))
            elif isinstance(geo, rg.Mesh):
                cp = geo.ClosestPoint(pt)
                return pt.DistanceTo(cp)
            elif isinstance(geo, rg.Brep):
                cp = geo.ClosestPoint(pt)
                return pt.DistanceTo(cp)
            elif isinstance(geo, rg.Surface):
                rc, u, v = geo.ClosestPoint(pt)
                if rc:
                    return pt.DistanceTo(geo.PointAt(u, v))
        except:
            pass
        return float('inf')

    def _build_influence_field(self, path_keys, cell_radius, is_bcc):
        """Pre-expand path keys into an influence dict.
        Maps (fx, fy, fz) -> min_squared_cell_distance for every grid
        position within cell_radius of any path key.  O(1) lookup per voxel."""
        influence = {}
        R = cell_radius
        R_sq = float(R * R)
        _get = influence.get
        _range = range(-R, R + 1)
        for pk in path_keys:
            px, py, pz = pk
            for dx in _range:
                dx_sq = dx * dx
                if dx_sq > R_sq:
                    continue
                for dy in _range:
                    dxy_sq = dx_sq + dy * dy
                    if dxy_sq > R_sq:
                        continue
                    for dz in _range:
                        dsq = dxy_sq + dz * dz
                        if dsq <= R_sq:
                            k = (px + dx, py + dy, pz + dz)
                            old = _get(k)
                            if old is None or dsq < old:
                                influence[k] = dsq
                        if is_bcc:
                            fx = dx + 0.5; fy = dy + 0.5; fz = dz + 0.5
                            dsq2 = fx * fx + fy * fy + fz * fz
                            if dsq2 <= R_sq:
                                k2 = (px + fx, py + fy, pz + fz)
                                old2 = _get(k2)
                                if old2 is None or dsq2 < old2:
                                    influence[k2] = dsq2
        return influence

    def generate(self, grid_x, grid_y, grid_z, cell_w, cell_l, cell_h,
                 noise_scale, threshold, octaves, seed,
                 use_paths, path_keys, path_cell_radius, path_strength,
                 path_carve,
                 use_bounds, bounds_meshes, bounds_aabb, bounds_strict,
                 grid_type, grid_origin):
        """Generate voxel field.  Without paths the grid is filled solid.
        When paths are supplied they act as attractors (concentrate) or
        subtractors (carve) with Perlin noise providing organic variation.
        Uses pre-expanded influence field keyed by grid indices for O(1)
        detection of whether a voxel is near a path."""
        self.perlin = PerlinNoise(seed)
        oct_noise = self.perlin.octave_noise
        voxels = []
        _append = voxels.append
        ox = grid_origin.X; oy = grid_origin.Y; oz = grid_origin.Z
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        half_ps = path_strength * 0.5
        _has_paths = use_paths and bool(path_keys)
        _Point3d = rg.Point3d
        _sqrt = math.sqrt

        if _has_paths:
            influence = self._build_influence_field(
                path_keys, path_cell_radius, grid_type == 1)
            _inf_get = influence.get
            _cr = float(path_cell_radius) if path_cell_radius > 0 else 1.0
        else:
            influence = None; _inf_get = None; _cr = 1.0

        if use_bounds and bounds_meshes and bounds_aabb and bounds_aabb.IsValid:
            _bb_min = bounds_aabb.Min; _bb_max = bounds_aabb.Max
            bb_min_x = _bb_min.X; bb_min_y = _bb_min.Y; bb_min_z = _bb_min.Z
            bb_max_x = _bb_max.X; bb_max_y = _bb_max.Y; bb_max_z = _bb_max.Z
            _do_bounds = True
            _bounds_meshes = bounds_meshes
            _bounds_strict = bounds_strict
        else:
            _do_bounds = False
            _bounds_meshes = None; _bounds_strict = False
            bb_min_x = bb_min_y = bb_min_z = 0.0
            bb_max_x = bb_max_y = bb_max_z = 0.0

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

        if _has_paths:
            _carve = path_carve
            _ps = path_strength
            for (fx, fy, fz) in positions:
                cx_b = ox + fx * cell_w + hw
                cy_b = oy + fy * cell_l + hl
                cz_b = oz + fz * cell_h + hh

                val = oct_noise(fx * noise_scale, fy * noise_scale,
                                fz * noise_scale, octaves)
                val = (val + 1.0) * 0.5

                inf_dsq = _inf_get((fx, fy, fz))
                if inf_dsq is not None:
                    d_norm = _sqrt(inf_dsq) / _cr
                    if _carve:
                        val -= (1.0 - d_norm) * _ps
                    else:
                        val += (1.0 - d_norm) * _ps
                else:
                    if not _carve:
                        val -= half_ps

                if val < 0.0:
                    val = 0.0
                elif val > 1.0:
                    val = 1.0

                if val > threshold:
                    if _do_bounds:
                        if (cx_b < bb_min_x or cx_b > bb_max_x or
                            cy_b < bb_min_y or cy_b > bb_max_y or
                            cz_b < bb_min_z or cz_b > bb_max_z):
                            continue
                        if _bounds_strict:
                            _corners_ok = True
                            for cdx in (0.0, cell_w):
                                for cdy in (0.0, cell_l):
                                    for cdz in (0.0, cell_h):
                                        cp = _Point3d(
                                            ox + fx * cell_w + cdx,
                                            oy + fy * cell_l + cdy,
                                            oz + fz * cell_h + cdz)
                                        _in = False
                                        for bm in _bounds_meshes:
                                            if bm.IsPointInside(
                                                    cp, 0.001, False):
                                                _in = True
                                                break
                                        if not _in:
                                            _corners_ok = False
                                            break
                                    if not _corners_ok:
                                        break
                                if not _corners_ok:
                                    break
                            if not _corners_ok:
                                continue
                        else:
                            pt = _Point3d(cx_b, cy_b, cz_b)
                            _in = False
                            for bm in _bounds_meshes:
                                if bm.IsPointInside(pt, 0.001, False):
                                    _in = True
                                    break
                            if not _in:
                                continue
                    _append((fx, fy, fz, val))
        else:
            for (fx, fy, fz) in positions:
                if _do_bounds:
                    cx_b = ox + fx * cell_w + hw
                    cy_b = oy + fy * cell_l + hl
                    cz_b = oz + fz * cell_h + hh
                    if (cx_b < bb_min_x or cx_b > bb_max_x or
                        cy_b < bb_min_y or cy_b > bb_max_y or
                        cz_b < bb_min_z or cz_b > bb_max_z):
                        continue
                    if _bounds_strict:
                        _corners_ok = True
                        for cdx in (0.0, cell_w):
                            for cdy in (0.0, cell_l):
                                for cdz in (0.0, cell_h):
                                    cp = _Point3d(
                                        ox + fx * cell_w + cdx,
                                        oy + fy * cell_l + cdy,
                                        oz + fz * cell_h + cdz)
                                    _in = False
                                    for bm in _bounds_meshes:
                                        if bm.IsPointInside(
                                                cp, 0.001, False):
                                            _in = True
                                            break
                                    if not _in:
                                        _corners_ok = False
                                        break
                                if not _corners_ok:
                                    break
                            if not _corners_ok:
                                break
                        if not _corners_ok:
                            continue
                    else:
                        pt = _Point3d(cx_b, cy_b, cz_b)
                        _in = False
                        for bm in _bounds_meshes:
                            if bm.IsPointInside(pt, 0.001, False):
                                _in = True
                                break
                        if not _in:
                            continue
                _append((fx, fy, fz, 1.0))

        self.voxels = voxels
        return voxels

    def set_custom_geometry(self, meshes):
        """Combine user-selected meshes, center at origin, normalise to unit size.
        Stores as the template shape replicated at each voxel position."""
        if not meshes:
            self.custom_base_mesh = None
            self.custom_base_edges = []
            return
        combined = rg.Mesh()
        for m in meshes:
            combined.Append(m)
        bb = combined.GetBoundingBox(True)
        if not bb.IsValid:
            self.custom_base_mesh = None
            self.custom_base_edges = []
            return
        center = bb.Center
        dims = [bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, bb.Max.Z - bb.Min.Z]
        max_dim = max(dims) if max(dims) > 0 else 1.0
        scale_factor = 1.0 / max_dim
        xform = rg.Transform.Translation(-center.X, -center.Y, -center.Z)
        combined.Transform(xform)
        xform = rg.Transform.Scale(rg.Point3d.Origin, scale_factor)
        combined.Transform(xform)
        self.custom_base_mesh = combined
        self.custom_base_edges = self._extract_feature_edges(combined)

    def build_mesh_custom(self, voxels, cell_w, cell_l, cell_h, color,
                          grid_origin, custom_scale):
        """Build display mesh using custom shape. Cached method refs."""
        if not self.custom_base_mesh:
            return self.build_mesh(voxels, cell_w, cell_l, cell_h, color,
                                   grid_origin)
        mesh = rg.Mesh()
        _va = mesh.Vertices.Add
        _fa = mesh.Faces.AddFace
        _ca = mesh.VertexColors.Add
        base = self.custom_base_mesh
        bv = base.Vertices; bf = base.Faces
        base_vcount = bv.Count; base_fcount = bf.Count
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        cr = color.R; cg = color.G; cb = color.B
        _FromArgb = System.Drawing.Color.FromArgb
        _int = int

        bv_cache = tuple((bv[i].X, bv[i].Y, bv[i].Z) for i in range(base_vcount))
        bf_quad = []
        bf_tri = []
        for fi in range(base_fcount):
            f = bf[fi]
            if f.IsQuad:
                bf_quad.append((f.A, f.B, f.C, f.D))
            else:
                bf_tri.append((f.A, f.B, f.C))
        bf_quad = tuple(bf_quad)
        bf_tri = tuple(bf_tri)

        sx = cell_w * custom_scale
        sy = cell_l * custom_scale
        sz = cell_h * custom_scale
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5

        b = 0
        for (fx, fy, fz, val) in voxels:
            cx = ox0 + fx * cell_w + hw
            cy = oy0 + fy * cell_l + hl
            cz = oz0 + fz * cell_h + hh
            for (bx, by, bz) in bv_cache:
                _va(bx * sx + cx, by * sy + cy, bz * sz + cz)
            for (a, b2, c, d) in bf_quad:
                _fa(a+b, b2+b, c+b, d+b)
            for (a, b2, c) in bf_tri:
                _fa(a+b, b2+b, c+b)
            rv = _int(cr * val); gv = _int(cg * val); bv_c = _int(cb * val)
            if rv < 30: rv = 30
            elif rv > 255: rv = 255
            if gv < 30: gv = 30
            elif gv > 255: gv = 255
            if bv_c < 30: bv_c = 30
            elif bv_c > 255: bv_c = 255
            vc = _FromArgb(rv, gv, bv_c)
            for _ in range(base_vcount):
                _ca(vc)
            b += base_vcount
        mesh.Normals.ComputeNormals()
        return mesh

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
        """Build degenerate-triangle edge mesh with cached method refs."""
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

    def build_mesh(self, voxels, cell_w, cell_l, cell_h, color, grid_origin):
        """Build combined box mesh. All method refs cached as locals to
        eliminate attribute lookup overhead in the tight loop."""
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
            rv = _int(cr * val); gv = _int(cg * val); bv_c = _int(cb * val)
            if rv < 30: rv = 30
            elif rv > 255: rv = 255
            if gv < 30: gv = 30
            elif gv > 255: gv = 255
            if bv_c < 30: bv_c = 30
            elif bv_c > 255: bv_c = 255
            vc = _FromArgb(rv, gv, bv_c)
            _ca(vc);_ca(vc);_ca(vc);_ca(vc)
            _ca(vc);_ca(vc);_ca(vc);_ca(vc)
            b += 8
        mesh.Normals.ComputeNormals()
        return mesh

    def _extract_feature_edges(self, mesh, angle_deg=20.0):
        """Find sharp edges (dihedral angle > angle_deg) and naked edges on a mesh.
        Used to generate wireframe overlay for custom voxel geometry."""
        if not mesh or mesh.Faces.Count == 0:
            return []
        mesh.FaceNormals.ComputeFaceNormals()
        topo = mesh.TopologyEdges
        cos_thresh = math.cos(angle_deg * math.pi / 180.0)
        lines = []
        for ei in range(topo.Count):
            faces = topo.GetConnectedFaces(ei)
            if faces.Length == 1:
                lines.append(topo.EdgeLine(ei))
            elif faces.Length == 2:
                n0 = mesh.FaceNormals[faces[0]]
                n1 = mesh.FaceNormals[faces[1]]
                dot = n0.X * n1.X + n0.Y * n1.Y + n0.Z * n1.Z
                if dot < cos_thresh:
                    lines.append(topo.EdgeLine(ei))
        return lines

    def _build_edge_mesh(self, voxels, cell_w, cell_l, cell_h, grid_origin,
                         custom_scale):
        """Build custom edge mesh with cached method refs and pre-extracted
        edge endpoint coordinates."""
        if not self.custom_base_edges:
            return None
        em = rg.Mesh()
        _va = em.Vertices.Add
        _fa = em.Faces.AddFace
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        sx = cell_w * custom_scale
        sy = cell_l * custom_scale
        sz = cell_h * custom_scale
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        edge_data = tuple(
            (be.From.X, be.From.Y, be.From.Z, be.To.X, be.To.Y, be.To.Z)
            for be in self.custom_base_edges)
        b = 0
        for (ix, iy, iz, val) in voxels:
            cx = ox0 + ix * cell_w + hw
            cy = oy0 + iy * cell_l + hl
            cz = oz0 + iz * cell_h + hh
            for (fx, fy, fz, tx, ty, tz) in edge_data:
                _va(fx * sx + cx, fy * sy + cy, fz * sz + cz)
                _va(tx * sx + cx, ty * sy + cy, tz * sz + cz)
                _va(tx * sx + cx, ty * sy + cy, tz * sz + cz)
                _fa(b, b + 1, b + 2)
                b += 3
        return em

    def update_display(self, voxels, cell_w, cell_l, cell_h, color,
                       show_bounds, bounds_color,
                       show_edges, edge_color,
                       grid_x, grid_y, grid_z, grid_origin,
                       grid_type=0, use_custom=False, custom_scale=1.0):
        """Rebuild the conduit's display mesh and bounding box from current
        parameters. grid_type 0=cube, 1=truncated octahedron. Chooses custom,
        TO, or default box mesh and triggers a viewport redraw."""
        if use_custom and self.custom_base_mesh:
            self.conduit.mesh = self.build_mesh_custom(
                voxels, cell_w, cell_l, cell_h, color, grid_origin,
                custom_scale)
            if show_edges:
                self.conduit.edge_mesh = self._build_edge_mesh(
                    voxels, cell_w, cell_l, cell_h, grid_origin, custom_scale)
            else:
                self.conduit.edge_mesh = None
        elif grid_type == 1:
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

        ox = grid_origin.X
        oy = grid_origin.Y
        oz = grid_origin.Z
        bx = grid_x * cell_w
        by = grid_y * cell_l
        bz = grid_z * cell_h

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
        """Add voxel mesh to the Rhino document. With vertex colours: density-
        shaded mesh. Without: plain mesh with no colour attributes."""
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

    def dispose(self):
        """Disable the display conduit so preview geometry disappears."""
        self.conduit.Enabled = False
        sc.doc.Views.Redraw()


# ---------------------------------------------------------------------------
# Voxel Pathfinder
# Builds a traversal graph from the voxel field (either voxel-centre
# adjacency or wireframe-edge adjacency) and runs scored greedy walks
# from user-assigned or auto-generated start points, optionally pulled
# toward attractor geometry. Supports branching for tree-like networks.
# ---------------------------------------------------------------------------
_CUBE_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)

_CENTRE_6 = ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
_CENTRE_14 = _CENTRE_6 + (
    (1,1,1),(1,1,-1),(1,-1,1),(1,-1,-1),
    (-1,1,1),(-1,1,-1),(-1,-1,1),(-1,-1,-1))


def _closest_dist_static(pt, geo):
    """Shortest distance from pt to Curve/Mesh/Brep/Surface."""
    try:
        if isinstance(geo, rg.Curve):
            rc, t = geo.ClosestPoint(pt)
            if rc:
                return pt.DistanceTo(geo.PointAt(t))
        elif isinstance(geo, rg.Mesh):
            cp = geo.ClosestPoint(pt)
            return pt.DistanceTo(cp)
        elif isinstance(geo, rg.Brep):
            cp = geo.ClosestPoint(pt)
            return pt.DistanceTo(cp)
        elif isinstance(geo, rg.Surface):
            rc, u, v = geo.ClosestPoint(pt)
            if rc:
                return pt.DistanceTo(geo.PointAt(u, v))
    except:
        pass
    return float('inf')


def _closest_point_on_geo(geo, pt):
    """Return the closest Point3d on geo to pt, or None on failure."""
    try:
        if isinstance(geo, rg.Curve):
            rc, t = geo.ClosestPoint(pt)
            if rc:
                return geo.PointAt(t)
        elif isinstance(geo, rg.Mesh):
            return geo.ClosestPoint(pt)
        elif isinstance(geo, rg.Brep):
            return geo.ClosestPoint(pt)
        elif isinstance(geo, rg.Surface):
            rc, u, v = geo.ClosestPoint(pt)
            if rc:
                return geo.PointAt(u, v)
    except:
        pass
    return None


class VoxelPathfinder(object):
    def __init__(self):
        self.graph = {}
        self.node_positions = {}
        self.node_density = {}
        self.trails = []
        self.trail_keys = []
        self.start_points = []
        self.target_points = []
        self.target_curves = []
        self.target_geos = []

    @staticmethod
    def _node_key(x, y, z):
        """Quantise coordinates to 0.01 precision for vertex merging."""
        return (int(round(x * 100)), int(round(y * 100)), int(round(z * 100)))

    def _snap_to_nearest(self, pt):
        """Return the graph node key closest to the given world point."""
        best_k = None
        best_d = float('inf')
        for k, p in self.node_positions.items():
            d = pt.DistanceTo(p)
            if d < best_d:
                best_d = d
                best_k = k
        return best_k

    # -- Centre graph (cell-to-cell) ----------------------------------------
    def build_centre_graph(self, voxels, cell_w, cell_l, cell_h,
                           grid_origin, grid_type):
        """Build adjacency graph where nodes are voxel centres and edges
        connect face-adjacent (cubes: 6-connected) or face+body-adjacent
        (BCC/TO: 14-connected) occupied voxels."""
        self.graph = {}
        self.node_positions = {}
        self.node_density = {}
        ox = grid_origin.X; oy = grid_origin.Y; oz = grid_origin.Z
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5

        voxel_set = {}
        for (fx, fy, fz, val) in voxels:
            voxel_set[(fx, fy, fz)] = val

        offsets = _CENTRE_14 if grid_type == 1 else _CENTRE_6
        bcc_offsets = ((0.5, 0.5, 0.5), (-0.5, -0.5, -0.5),
                       (0.5, 0.5, -0.5), (0.5, -0.5, 0.5),
                       (-0.5, 0.5, 0.5), (0.5, -0.5, -0.5),
                       (-0.5, 0.5, -0.5), (-0.5, -0.5, 0.5))

        graph = self.graph
        positions = self.node_positions
        density = self.node_density

        for (fx, fy, fz, val) in voxels:
            k = (fx, fy, fz)
            cx = ox + fx * cell_w + hw
            cy = oy + fy * cell_l + hl
            cz = oz + fz * cell_h + hh
            if k not in graph:
                graph[k] = set()
                positions[k] = rg.Point3d(cx, cy, cz)
                density[k] = val

            for (dx, dy, dz) in offsets:
                nk = (fx + dx, fy + dy, fz + dz)
                if nk in voxel_set:
                    nval = voxel_set[nk]
                    if nk not in graph:
                        ncx = ox + nk[0] * cell_w + hw
                        ncy = oy + nk[1] * cell_l + hl
                        ncz = oz + nk[2] * cell_h + hh
                        graph[nk] = set()
                        positions[nk] = rg.Point3d(ncx, ncy, ncz)
                        density[nk] = nval
                    graph[k].add(nk)
                    graph[nk].add(k)

            if grid_type == 1:
                for (dx, dy, dz) in bcc_offsets:
                    nk = (fx + dx, fy + dy, fz + dz)
                    if nk in voxel_set:
                        nval = voxel_set[nk]
                        if nk not in graph:
                            ncx = ox + nk[0] * cell_w + hw
                            ncy = oy + nk[1] * cell_l + hl
                            ncz = oz + nk[2] * cell_h + hh
                            graph[nk] = set()
                            positions[nk] = rg.Point3d(ncx, ncy, ncz)
                            density[nk] = nval
                        graph[k].add(nk)
                        graph[nk].add(k)

    # -- Edge graph (wireframe) ---------------------------------------------
    def build_edge_graph(self, voxels, cell_w, cell_l, cell_h,
                         grid_origin, grid_type):
        """Build adjacency graph from all voxel edge segments.
        Shared vertices between adjacent voxels are merged via _node_key."""
        self.graph = {}
        self.node_positions = {}
        self.node_density = {}
        ox = grid_origin.X; oy = grid_origin.Y; oz = grid_origin.Z
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        _nk = self._node_key

        if grid_type == 1:
            sw = cell_w * 0.25; sl = cell_l * 0.25; sh = cell_h * 0.25
            scaled_verts = tuple(
                (vx * sw, vy * sl, vz * sh)
                for (vx, vy, vz) in VoxelSystem._TO_VERTS)
            edges = VoxelSystem._TO_EDGES
        else:
            scaled_verts = (
                (-hw, -hl, -hh), ( hw, -hl, -hh),
                ( hw,  hl, -hh), (-hw,  hl, -hh),
                (-hw, -hl,  hh), ( hw, -hl,  hh),
                ( hw,  hl,  hh), (-hw,  hl,  hh))
            edges = _CUBE_EDGES

        graph = self.graph
        positions = self.node_positions
        density = self.node_density

        for (fx, fy, fz, val) in voxels:
            cx = ox + fx * cell_w + hw
            cy = oy + fy * cell_l + hl
            cz = oz + fz * cell_h + hh
            for (ei, ej) in edges:
                dx0, dy0, dz0 = scaled_verts[ei]
                dx1, dy1, dz1 = scaled_verts[ej]
                x0 = cx + dx0; y0 = cy + dy0; z0 = cz + dz0
                x1 = cx + dx1; y1 = cy + dy1; z1 = cz + dz1
                k0 = _nk(x0, y0, z0)
                k1 = _nk(x1, y1, z1)
                if k0 not in graph:
                    graph[k0] = set()
                    positions[k0] = rg.Point3d(x0, y0, z0)
                if k1 not in graph:
                    graph[k1] = set()
                    positions[k1] = rg.Point3d(x1, y1, z1)
                graph[k0].add(k1)
                graph[k1].add(k0)
                if k0 not in density or val > density[k0]:
                    density[k0] = val
                if k1 not in density or val > density[k1]:
                    density[k1] = val

    # -- Random start generation --------------------------------------------
    def generate_random_starts(self, count, seed):
        """Pick random graph nodes evenly distributed across the volume.

        Uses stratified sampling: divides the bounding box into a grid of
        cells and picks one random node per cell, cycling through cells
        until count is reached. This prevents clustering on one side.
        """
        random.seed(seed)
        if not self.graph:
            self.start_points = []
            return
        nodes = list(self.graph.keys())
        if not nodes:
            self.start_points = []
            return
        positions = self.node_positions

        xs = [positions[k].X for k in nodes]
        ys = [positions[k].Y for k in nodes]
        zs = [positions[k].Z for k in nodes]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        z_min, z_max = min(zs), max(zs)

        n_div = max(2, int(round(count ** (1.0 / 3.0))))
        dx = (x_max - x_min + 0.001) / n_div
        dy = (y_max - y_min + 0.001) / n_div
        dz = (z_max - z_min + 0.001) / n_div

        buckets = {}
        for k in nodes:
            p = positions[k]
            bx = int((p.X - x_min) / dx)
            by = int((p.Y - y_min) / dy)
            bz = int((p.Z - z_min) / dz)
            cell = (bx, by, bz)
            if cell not in buckets:
                buckets[cell] = []
            buckets[cell].append(k)

        cells = list(buckets.keys())
        random.shuffle(cells)

        self.start_points = []
        idx = 0
        while len(self.start_points) < count and cells:
            cell = cells[idx % len(cells)]
            pool = buckets[cell]
            pick = pool[random.randint(0, len(pool) - 1)]
            self.start_points.append(positions[pick])
            idx += 1
            if idx >= len(cells):
                random.shuffle(cells)
                idx = 0

    # -- Attractor distance helper ------------------------------------------
    def _attractor_score(self, nb_pos, curr_pos, attr_strength, attr_radius,
                         repulsion_radius):
        """Compute attractor pull and repulsion score for a candidate neighbour.

        Within attr_radius the neighbour is pulled toward attractors.
        Within repulsion_radius the neighbour is strongly pushed away,
        keeping paths from intersecting with the attractor geometry.
        Repulsion is independent of attr_strength and uses a quadratic
        falloff so it dominates all other forces at close range.
        """
        if attr_strength <= 0 and repulsion_radius <= 0:
            return 0.0
        score = 0.0
        min_dist = float('inf')

        if self.target_points:
            best_d = float('inf')
            best_pt = None
            for tp in self.target_points:
                d = nb_pos.DistanceTo(tp)
                if d < best_d:
                    best_d = d
                    best_pt = tp
            if best_d < min_dist:
                min_dist = best_d
            if attr_strength > 0 and best_d < attr_radius:
                score += attr_strength * (1.0 - best_d / attr_radius)
            if best_pt is not None and attr_strength > 0:
                dx_t = best_pt.X - curr_pos.X
                dy_t = best_pt.Y - curr_pos.Y
                dz_t = best_pt.Z - curr_pos.Z
                dx_n = nb_pos.X - curr_pos.X
                dy_n = nb_pos.Y - curr_pos.Y
                dz_n = nb_pos.Z - curr_pos.Z
                ln_t = math.sqrt(dx_t*dx_t + dy_t*dy_t + dz_t*dz_t)
                ln_n = math.sqrt(dx_n*dx_n + dy_n*dy_n + dz_n*dz_n)
                if ln_t > 1e-9 and ln_n > 1e-9:
                    dot = (dx_t*dx_n + dy_t*dy_n + dz_t*dz_n) / (ln_t * ln_n)
                    score += dot * attr_strength * 0.5

        all_geos = list(self.target_curves) + list(self.target_geos)
        if all_geos:
            best_d = float('inf')
            best_geo = None
            for geo in all_geos:
                d = _closest_dist_static(nb_pos, geo)
                if d < best_d:
                    best_d = d
                    best_geo = geo
            if best_d < min_dist:
                min_dist = best_d
            if attr_strength > 0 and best_d < attr_radius:
                score += attr_strength * (1.0 - best_d / attr_radius)
            if best_geo is not None and attr_strength > 0:
                cp = _closest_point_on_geo(best_geo, curr_pos)
                if cp is not None:
                    dx_t = cp.X - curr_pos.X
                    dy_t = cp.Y - curr_pos.Y
                    dz_t = cp.Z - curr_pos.Z
                    dx_n = nb_pos.X - curr_pos.X
                    dy_n = nb_pos.Y - curr_pos.Y
                    dz_n = nb_pos.Z - curr_pos.Z
                    ln_t = math.sqrt(dx_t*dx_t + dy_t*dy_t + dz_t*dz_t)
                    ln_n = math.sqrt(dx_n*dx_n + dy_n*dy_n + dz_n*dz_n)
                    if ln_t > 1e-9 and ln_n > 1e-9:
                        dot = (dx_t*dx_n + dy_t*dy_n + dz_t*dz_n) / (ln_t * ln_n)
                        score += dot * attr_strength * 0.5

        if repulsion_radius > 0 and min_dist < repulsion_radius:
            ratio = 1.0 - min_dist / repulsion_radius
            score -= 100.0 * ratio * ratio

        return score

    # -- Pathfinding --------------------------------------------------------
    def find_paths(self, max_steps, branch_prob, max_branches,
                   density_strength, attractor_strength, attractor_radius,
                   repulsion_radius, momentum_strength, separation_strength,
                   wander_strength, seed):
        """Run scored greedy walks from each start point through the graph.

        At every step each agent scores its neighbours by:
          density pull     -- prefer high-density nodes
          attractor pull   -- pull toward assigned target pts/curves/geos
          repulsion field  -- push away within repulsion_radius of targets
          momentum         -- prefer continuing in the same direction
          separation       -- penalise previously visited nodes
          wander           -- random noise for organic variation

        Returns list of trails (each trail is a list of Point3d).
        """
        random.seed(seed)
        self.trails = []
        if not self.graph or not self.start_points:
            return []

        positions = self.node_positions
        density = self.node_density
        graph = self.graph

        visit_counts = {}
        total_branches = 0

        agents = []
        for sp in self.start_points:
            sk = self._snap_to_nearest(sp)
            if sk is None:
                continue
            agents.append({
                'pos': sk,
                'trail': [sk],
                'prev': None,
                'alive': True
            })

        for step in range(max_steps):
            new_agents = []
            any_alive = False
            for agent in agents:
                if not agent['alive']:
                    continue
                any_alive = True
                current = agent['pos']
                neighbors = list(graph.get(current, set()))
                if not neighbors:
                    agent['alive'] = False
                    continue

                curr_pos = positions[current]
                scores = []
                for nb in neighbors:
                    score = density.get(nb, 0) * density_strength
                    nb_pos = positions[nb]

                    score += self._attractor_score(
                        nb_pos, curr_pos, attractor_strength, attractor_radius,
                        repulsion_radius)

                    if agent['prev'] is not None and momentum_strength > 0:
                        prev_pos = positions[agent['prev']]
                        dx0 = curr_pos.X - prev_pos.X
                        dy0 = curr_pos.Y - prev_pos.Y
                        dz0 = curr_pos.Z - prev_pos.Z
                        dx1 = nb_pos.X - curr_pos.X
                        dy1 = nb_pos.Y - curr_pos.Y
                        dz1 = nb_pos.Z - curr_pos.Z
                        dot = dx0 * dx1 + dy0 * dy1 + dz0 * dz1
                        score += dot * momentum_strength

                    vc = visit_counts.get(nb, 0)
                    if vc > 0:
                        score -= vc * separation_strength

                    score += random.random() * wander_strength
                    scores.append((score, nb))

                scores.sort(key=lambda x: x[0], reverse=True)
                chosen = scores[0][1]

                agent['prev'] = current
                agent['pos'] = chosen
                agent['trail'].append(chosen)
                visit_counts[chosen] = visit_counts.get(chosen, 0) + 1

                if (branch_prob > 0 and total_branches < max_branches
                        and len(scores) > 1
                        and random.random() < branch_prob):
                    branch_target = scores[1][1]
                    new_agents.append({
                        'pos': branch_target,
                        'trail': [current, branch_target],
                        'prev': current,
                        'alive': True
                    })
                    total_branches += 1

            agents.extend(new_agents)
            if not any_alive:
                break

        self.trails = []
        self.trail_keys = []
        for agent in agents:
            if len(agent['trail']) > 1:
                pts = [positions[k] for k in agent['trail']]
                self.trails.append(pts)
                self.trail_keys.append(list(agent['trail']))

        return self.trails

    # -- Slime Mould mode ---------------------------------------------------
    def _collect_anchors(self):
        """Gather world-space anchor points from all target geometry.

        Points are used directly. Curves contribute their midpoint.
        Meshes/breps/surfaces contribute their bounding-box centre.
        Each anchor is snapped to the nearest graph node.
        Returns list of (graph_key, Point3d) tuples.
        """
        raw = []
        for pt in self.target_points:
            raw.append(pt)
        for crv in self.target_curves:
            t = crv.Domain.Mid
            raw.append(crv.PointAt(t))
        for geo in self.target_geos:
            bb = geo.GetBoundingBox(False)
            if bb.IsValid:
                raw.append(bb.Center)
        anchors = []
        seen = set()
        for pt in raw:
            k = self._snap_to_nearest(pt)
            if k is not None and k not in seen:
                seen.add(k)
                anchors.append((k, self.node_positions[k]))
        return anchors

    def _min_dist_to_targets(self, pt):
        """Shortest distance from pt to any assigned target geometry."""
        min_d = float('inf')
        for tp in self.target_points:
            d = pt.DistanceTo(tp)
            if d < min_d:
                min_d = d
        for crv in self.target_curves:
            d = _closest_dist_static(pt, crv)
            if d < min_d:
                min_d = d
        for geo in self.target_geos:
            d = _closest_dist_static(pt, geo)
            if d < min_d:
                min_d = d
        return min_d

    def find_slime_paths(self, max_steps, density_strength,
                         momentum_strength, separation_strength,
                         wander_strength, repulsion_radius,
                         mould_density, reinforcement,
                         direction_strength, branch_prob,
                         max_branches, seed):
        """Simulate Physarum-style slime mould growth.

        Growth happens in waves. Each wave spawns agents from all anchor
        nodes AND from high-traffic nodes in the existing network, letting
        the mould expand outward and fill the volume over multiple
        iterations.

        mould_density:      agents per anchor per wave (1-500)
        reinforcement:      bonus for already-visited nodes (tube thickening)
        direction_strength: how strongly agents aim at their target (0=wander, 3=direct)
        branch_prob:        chance of branching per step
        max_branches:       cap on total branch agents
        """
        random.seed(seed)
        self.trails = []
        anchors = self._collect_anchors()
        if len(anchors) < 2:
            return []

        positions = self.node_positions
        graph = self.graph
        dens = self.node_density
        n = len(anchors)

        anchor_keys = set(a[0] for a in anchors)
        anchor_positions = [a[1] for a in anchors]

        visit_counts = {}
        total_branches = 0

        spawn_keys = [a[0] for a in anchors]

        agents = []
        for src_idx in range(n):
            src_key = anchors[src_idx][0]
            src_pos = anchors[src_idx][1]
            other_dists = []
            for j in range(n):
                if j == src_idx:
                    continue
                other_dists.append(
                    (src_pos.DistanceTo(anchor_positions[j]), j))
            if not other_dists:
                continue
            avg_d = sum(od[0] for od in other_dists) / len(other_dists)

            for _ in range(mould_density):
                best_d = float('inf')
                tgt_idx = -1
                for (base_d, j) in other_dists:
                    d = base_d + random.random() * avg_d * 0.4
                    if d < best_d:
                        best_d = d
                        tgt_idx = j
                if tgt_idx < 0:
                    continue
                agents.append({
                    'pos': src_key,
                    'target': anchor_positions[tgt_idx],
                    'target_key': anchors[tgt_idx][0],
                    'trail': [src_key],
                    'prev': None,
                    'alive': True
                })

        for step in range(max_steps):
            new_agents = []
            any_alive = False
            for agent in agents:
                if not agent['alive']:
                    continue
                any_alive = True
                current = agent['pos']
                target_pos = agent['target']

                if current == agent['target_key']:
                    agent['alive'] = False
                    continue
                if (current in anchor_keys and current != agent['trail'][0]
                        and len(agent['trail']) > 3):
                    agent['alive'] = False
                    continue

                neighbors = list(graph.get(current, set()))
                if not neighbors:
                    agent['alive'] = False
                    continue

                curr_pos = positions[current]
                scores = []
                for nb in neighbors:
                    nb_pos = positions[nb]
                    score = dens.get(nb, 0) * density_strength

                    if direction_strength > 0:
                        dx_t = target_pos.X - curr_pos.X
                        dy_t = target_pos.Y - curr_pos.Y
                        dz_t = target_pos.Z - curr_pos.Z
                        dx_n = nb_pos.X - curr_pos.X
                        dy_n = nb_pos.Y - curr_pos.Y
                        dz_n = nb_pos.Z - curr_pos.Z
                        ln_t = math.sqrt(dx_t*dx_t + dy_t*dy_t + dz_t*dz_t)
                        ln_n = math.sqrt(dx_n*dx_n + dy_n*dy_n + dz_n*dz_n)
                        if ln_t > 1e-9 and ln_n > 1e-9:
                            dot = (dx_t*dx_n + dy_t*dy_n + dz_t*dz_n)
                            score += (dot / (ln_t * ln_n)) * direction_strength
                        dist_nb = nb_pos.DistanceTo(target_pos)
                        score += direction_strength * 0.5 / (dist_nb + 0.01)

                    if repulsion_radius > 0:
                        min_d = self._min_dist_to_targets(nb_pos)
                        if min_d < repulsion_radius:
                            d_cur = curr_pos.DistanceTo(target_pos)
                            if d_cur > repulsion_radius * 1.5:
                                ratio = 1.0 - min_d / repulsion_radius
                                score -= 100.0 * ratio * ratio

                    if agent['prev'] is not None and momentum_strength > 0:
                        prev_pos = positions[agent['prev']]
                        dx0 = curr_pos.X - prev_pos.X
                        dy0 = curr_pos.Y - prev_pos.Y
                        dz0 = curr_pos.Z - prev_pos.Z
                        dx1 = nb_pos.X - curr_pos.X
                        dy1 = nb_pos.Y - curr_pos.Y
                        dz1 = nb_pos.Z - curr_pos.Z
                        score += (dx0*dx1 + dy0*dy1 + dz0*dz1) * momentum_strength

                    vc = visit_counts.get(nb, 0)
                    if vc > 0:
                        score += vc * reinforcement
                        score -= vc * separation_strength

                    score += random.random() * wander_strength
                    scores.append((score, nb))

                scores.sort(key=lambda x: x[0], reverse=True)
                chosen = scores[0][1]

                agent['prev'] = current
                agent['pos'] = chosen
                agent['trail'].append(chosen)
                visit_counts[chosen] = visit_counts.get(chosen, 0) + 1

                if (branch_prob > 0 and total_branches < max_branches
                        and len(scores) > 1
                        and random.random() < branch_prob):
                    br_key = scores[1][1]
                    br_tgt_idx = random.randint(0, n - 1)
                    new_agents.append({
                        'pos': br_key,
                        'target': anchor_positions[br_tgt_idx],
                        'target_key': anchors[br_tgt_idx][0],
                        'trail': [current, br_key],
                        'prev': current,
                        'alive': True
                    })
                    total_branches += 1

            agents.extend(new_agents)
            if not any_alive:
                break

        self.trails = []
        self.trail_keys = []
        for agent in agents:
            if len(agent['trail']) > 1:
                pts = [positions[k] for k in agent['trail']]
                self.trails.append(pts)
                self.trail_keys.append(list(agent['trail']))

        return self.trails


# ---------------------------------------------------------------------------
# UI Dialog
# Eto.Forms window with all sliders, checkboxes and buttons. Uses a debounced
# timer (UITimer at 0.12s) so slider drags don't trigger a full recompute on
# every pixel of movement. Two dirty flags separate heavy work (noise
# recompute) from cheap work (mesh rebuild with different rotation/scale).
# ---------------------------------------------------------------------------
class VoxelDialog(forms.Form):
    def __init__(self):
        super(VoxelDialog, self).__init__()
        self.Title = "Voxel Field Tool v01"
        self.Padding = drawing.Padding(6)
        self.Resizable = True
        self.MinimumSize = drawing.Size(420, 700)
        self.Size = drawing.Size(420, 800)

        self.system = VoxelSystem()
        self.bounds_geometries = []
        self.bounds_meshes = []
        self.bounds_aabb = None
        self.voxel_color = System.Drawing.Color.FromArgb(100, 180, 255)
        self.system.conduit.shaded_material = rd.DisplayMaterial(
            System.Drawing.Color.FromArgb(100, 180, 255))
        self.edge_color = System.Drawing.Color.FromArgb(40, 40, 40)
        self.bounds_color = System.Drawing.Color.FromArgb(80, 80, 80)
        self.pathfinder = VoxelPathfinder()

        self._compute_dirty = False
        self._display_dirty = False

        self._anim_wander_trails = []
        self._anim_wander_points = []
        self._anim_wander_frame = 0
        self._anim_wander_max_frame = 0
        self._anim_wander_playing = False

        self._anim_slime_trails = []
        self._anim_slime_points = []
        self._anim_slime_frame = 0
        self._anim_slime_max_frame = 0
        self._anim_slime_playing = False

        self._build_ui()

        self._timer = forms.UITimer()
        self._timer.Interval = 0.06
        self._timer.Elapsed += self._on_timer_tick
        self._timer.Start()

        self._anim_wander_timer = forms.UITimer()
        self._anim_wander_timer.Interval = 0.05
        self._anim_wander_timer.Elapsed += self._on_anim_wander_tick

        self._anim_slime_timer = forms.UITimer()
        self._anim_slime_timer.Interval = 0.05
        self._anim_slime_timer.Elapsed += self._on_anim_slime_tick

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

        self._link_guard = False

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

        # -- custom voxel geometry -----------------------------------------
        inner, _sec_finish = self._section(layout, "Custom Voxel Geometry", False)

        btn_pick_custom = forms.Button()
        btn_pick_custom.Text = "Assign Custom Geo"
        btn_pick_custom.Click += self._on_pick_custom
        btn_clr_custom = forms.Button()
        btn_clr_custom.Text = "Clear Custom Geo"
        btn_clr_custom.Click += self._on_clear_custom
        inner.AddRow(btn_pick_custom, btn_clr_custom)

        self.lbl_custom = forms.Label()
        self.lbl_custom.Text = "Custom: None"
        inner.AddRow(self.lbl_custom)

        self.chk_use_custom = forms.CheckBox()
        self.chk_use_custom.Text = "Show Custom Voxels"
        self.chk_use_custom.Checked = False
        self.chk_use_custom.CheckedChanged += lambda s, e: self._mark_display()
        inner.AddRow(self.chk_use_custom)

        self.sld_custom_s, self.txt_custom_s = self._float_slider(
            inner, "Custom Scale", 0.1, 2.0, 1.0, self._mark_display)

        _sec_finish()

        # -- pathfinding -------------------------------------------------------
        inner, _sec_finish = self._section(layout, "Pathfinding", False)

        lbl_gm = forms.Label()
        lbl_gm.Text = "Graph Mode"
        lbl_gm.Width = 105
        self.dd_graph_mode = forms.DropDown()
        self.dd_graph_mode.Items.Add("Voxel Centres")
        self.dd_graph_mode.Items.Add("Voxel Edges")
        self.dd_graph_mode.SelectedIndex = 0
        self.dd_graph_mode.Width = 150
        inner.AddRow(lbl_gm, self.dd_graph_mode)

        inner.AddRow(None)

        lbl_sp = forms.Label()
        lbl_sp.Text = "Start Points (Wander)"
        lbl_sp.Font = drawing.Font(lbl_sp.Font.Family, lbl_sp.Font.Size,
                                   drawing.FontStyle.Bold)
        inner.AddRow(lbl_sp)

        self.sld_pf_agents, self.txt_pf_agents = self._int_slider(
            inner, "Agent Count", 1, 50, 5, self._noop)

        btn_pick_starts = forms.Button()
        btn_pick_starts.Text = "Assign"
        btn_pick_starts.Width = 80
        btn_pick_starts.Click += self._on_pick_start_pts
        btn_clr_starts = forms.Button()
        btn_clr_starts.Text = "Clear"
        btn_clr_starts.Width = 80
        btn_clr_starts.Click += self._on_clear_start_pts
        btn_rand_starts = forms.Button()
        btn_rand_starts.Text = "Random"
        btn_rand_starts.Width = 80
        btn_rand_starts.Click += self._on_generate_random_starts
        self.lbl_start_count = forms.Label()
        self.lbl_start_count.Text = "0"
        self.lbl_start_count.Width = 40
        inner.AddRow(btn_pick_starts, btn_clr_starts, btn_rand_starts,
                     self.lbl_start_count)

        inner.AddRow(None)

        lbl_tgt = forms.Label()
        lbl_tgt.Text = "Targets (Wander attractors / Slime Mould nodes)"
        lbl_tgt.Font = drawing.Font(lbl_tgt.Font.Family, lbl_tgt.Font.Size,
                                    drawing.FontStyle.Bold)
        inner.AddRow(lbl_tgt)

        btn_pick_tgt_pts = forms.Button()
        btn_pick_tgt_pts.Text = "Points"
        btn_pick_tgt_pts.Width = 80
        btn_pick_tgt_pts.Click += self._on_pick_target_pts
        btn_clr_tgt_pts = forms.Button()
        btn_clr_tgt_pts.Text = "Clear"
        btn_clr_tgt_pts.Width = 50
        btn_clr_tgt_pts.Click += self._on_clear_target_pts
        self.lbl_tgt_pt_count = forms.Label()
        self.lbl_tgt_pt_count.Text = "0"
        self.lbl_tgt_pt_count.Width = 30

        btn_pick_tgt_crv = forms.Button()
        btn_pick_tgt_crv.Text = "Curves"
        btn_pick_tgt_crv.Width = 80
        btn_pick_tgt_crv.Click += self._on_pick_target_curves
        btn_clr_tgt_crv = forms.Button()
        btn_clr_tgt_crv.Text = "Clear"
        btn_clr_tgt_crv.Width = 50
        btn_clr_tgt_crv.Click += self._on_clear_target_curves
        self.lbl_tgt_crv_count = forms.Label()
        self.lbl_tgt_crv_count.Text = "0"
        self.lbl_tgt_crv_count.Width = 30

        btn_pick_tgt_geo = forms.Button()
        btn_pick_tgt_geo.Text = "Geos"
        btn_pick_tgt_geo.Width = 80
        btn_pick_tgt_geo.Click += self._on_pick_target_geos
        btn_clr_tgt_geo = forms.Button()
        btn_clr_tgt_geo.Text = "Clear"
        btn_clr_tgt_geo.Width = 50
        btn_clr_tgt_geo.Click += self._on_clear_target_geos
        self.lbl_tgt_geo_count = forms.Label()
        self.lbl_tgt_geo_count.Text = "0"
        self.lbl_tgt_geo_count.Width = 30

        inner.AddRow(btn_pick_tgt_pts, btn_clr_tgt_pts, self.lbl_tgt_pt_count)
        inner.AddRow(btn_pick_tgt_crv, btn_clr_tgt_crv, self.lbl_tgt_crv_count)
        inner.AddRow(btn_pick_tgt_geo, btn_clr_tgt_geo, self.lbl_tgt_geo_count)

        inner.AddRow(None)

        lbl_shared = forms.Label()
        lbl_shared.Text = "Shared Parameters"
        lbl_shared.Font = drawing.Font(lbl_shared.Font.Family,
                                       lbl_shared.Font.Size,
                                       drawing.FontStyle.Bold)
        inner.AddRow(lbl_shared)

        self.sld_pf_steps, self.txt_pf_steps = self._int_slider(
            inner, "Max Steps", 10, 1000, 200, self._noop)
        self.sld_pf_density, self.txt_pf_density = self._float_slider(
            inner, "Density Pull", 0.0, 2.0, 1.0, self._noop)
        self.sld_pf_momentum, self.txt_pf_momentum = self._float_slider(
            inner, "Momentum", 0.0, 2.0, 0.8, self._noop)
        self.sld_pf_sep, self.txt_pf_sep = self._float_slider(
            inner, "Separation", 0.0, 2.0, 0.3, self._noop)
        self.sld_pf_wander, self.txt_pf_wander = self._float_slider(
            inner, "Wander", 0.0, 2.0, 0.3, self._noop)
        self.sld_pf_repulse, self.txt_pf_repulse = self._float_slider(
            inner, "Repulsion Dist", 0.0, 50.0, 0.0, self._noop)
        self.sld_pf_branch, self.txt_pf_branch = self._float_slider(
            inner, "Branch Prob", 0.0, 0.5, 0.05, self._noop)
        self.sld_pf_max_br, self.txt_pf_max_br = self._int_slider(
            inner, "Max Branches", 0, 500, 50, self._noop)
        self.sld_pf_seed, self.txt_pf_seed = self._int_slider(
            inner, "Seed", 0, 100, 42, self._noop)

        inner.AddRow(None)

        lbl_w = forms.Label()
        lbl_w.Text = "Wander Only"
        lbl_w.Font = drawing.Font(lbl_w.Font.Family, lbl_w.Font.Size,
                                  drawing.FontStyle.Bold)
        inner.AddRow(lbl_w)

        self.sld_pf_attr, self.txt_pf_attr = self._float_slider(
            inner, "Attractor Pull", 0.0, 3.0, 1.5, self._noop)
        self.sld_pf_attr_r, self.txt_pf_attr_r = self._float_slider(
            inner, "Attr Radius", 1.0, 200.0, 50.0, self._noop)

        inner.AddRow(None)

        lbl_sm = forms.Label()
        lbl_sm.Text = "Slime Mould Only"
        lbl_sm.Font = drawing.Font(lbl_sm.Font.Family, lbl_sm.Font.Size,
                                   drawing.FontStyle.Bold)
        inner.AddRow(lbl_sm)

        self.sld_mould_density, self.txt_mould_density = self._int_slider(
            inner, "Mould Density", 1, 500, 5, self._noop)
        self.sld_reinforce, self.txt_reinforce = self._float_slider(
            inner, "Reinforcement", 0.0, 3.0, 0.8, self._noop)
        self.sld_direction, self.txt_direction = self._float_slider(
            inner, "Direction", 0.0, 3.0, 1.0, self._noop)

        inner.AddRow(None)

        lbl_wact = forms.Label()
        lbl_wact.Text = "Wander"
        lbl_wact.Font = drawing.Font(lbl_wact.Font.Family, lbl_wact.Font.Size,
                                     drawing.FontStyle.Bold)
        inner.AddRow(lbl_wact)

        btn_gen_wander = forms.Button()
        btn_gen_wander.Text = "Generate Wander"
        btn_gen_wander.Click += self._on_generate_wander
        btn_clr_wander = forms.Button()
        btn_clr_wander.Text = "Clear Wander"
        btn_clr_wander.Click += self._on_clear_wander
        inner.AddRow(btn_gen_wander, btn_clr_wander)

        self.lbl_wander_status = forms.Label()
        self.lbl_wander_status.Text = "Wander: 0"
        inner.AddRow(self.lbl_wander_status)

        self.chk_animate_wander = forms.CheckBox()
        self.chk_animate_wander.Text = "Animate Wander"
        self.chk_animate_wander.Checked = False
        self.chk_animate_wander.CheckedChanged += self._on_toggle_animate_wander
        inner.AddRow(self.chk_animate_wander)

        self._anim_wander_panel = forms.DynamicLayout()
        self._anim_wander_panel.DefaultSpacing = drawing.Size(4, 4)
        self._anim_wander_panel.Padding = drawing.Padding(0)
        self._anim_wander_panel.Visible = False

        self.btn_anim_w_play = forms.Button()
        self.btn_anim_w_play.Text = u"\u25B6 Play"
        self.btn_anim_w_play.Width = 80
        self.btn_anim_w_play.Click += self._on_anim_wander_play
        self.btn_anim_w_pause = forms.Button()
        self.btn_anim_w_pause.Text = u"\u23F8 Pause"
        self.btn_anim_w_pause.Width = 80
        self.btn_anim_w_pause.Enabled = False
        self.btn_anim_w_pause.Click += self._on_anim_wander_pause
        self.btn_anim_w_reset = forms.Button()
        self.btn_anim_w_reset.Text = u"\u21BA Reset"
        self.btn_anim_w_reset.Width = 80
        self.btn_anim_w_reset.Click += self._on_anim_wander_reset
        self._anim_wander_panel.AddRow(self.btn_anim_w_play, self.btn_anim_w_pause,
                                       self.btn_anim_w_reset)

        self.sld_anim_w_speed, self.txt_anim_w_speed = self._int_slider(
            self._anim_wander_panel, "Speed", 1, 20, 5, self._on_anim_wander_speed_change)
        self.lbl_anim_w_frame = forms.Label()
        self.lbl_anim_w_frame.Text = "Frame: 0 / 0"
        self._anim_wander_panel.AddRow(self.lbl_anim_w_frame)

        inner.AddRow(self._anim_wander_panel)

        inner.AddRow(None)

        lbl_sact = forms.Label()
        lbl_sact.Text = "Slime Mould"
        lbl_sact.Font = drawing.Font(lbl_sact.Font.Family, lbl_sact.Font.Size,
                                     drawing.FontStyle.Bold)
        inner.AddRow(lbl_sact)

        btn_wander_to_tgt = forms.Button()
        btn_wander_to_tgt.Text = "Wander \u2192 Slime Targets"
        btn_wander_to_tgt.Click += self._on_wander_to_targets
        inner.AddRow(btn_wander_to_tgt)

        btn_gen_slime = forms.Button()
        btn_gen_slime.Text = "Generate Slime"
        btn_gen_slime.Click += self._on_generate_slime
        btn_clr_slime = forms.Button()
        btn_clr_slime.Text = "Clear Slime"
        btn_clr_slime.Click += self._on_clear_slime
        inner.AddRow(btn_gen_slime, btn_clr_slime)

        self.lbl_slime_status = forms.Label()
        self.lbl_slime_status.Text = "Slime: 0"
        inner.AddRow(self.lbl_slime_status)

        self.chk_animate_slime = forms.CheckBox()
        self.chk_animate_slime.Text = "Animate Slime"
        self.chk_animate_slime.Checked = False
        self.chk_animate_slime.CheckedChanged += self._on_toggle_animate_slime
        inner.AddRow(self.chk_animate_slime)

        self._anim_slime_panel = forms.DynamicLayout()
        self._anim_slime_panel.DefaultSpacing = drawing.Size(4, 4)
        self._anim_slime_panel.Padding = drawing.Padding(0)
        self._anim_slime_panel.Visible = False

        self.btn_anim_s_play = forms.Button()
        self.btn_anim_s_play.Text = u"\u25B6 Play"
        self.btn_anim_s_play.Width = 80
        self.btn_anim_s_play.Click += self._on_anim_slime_play
        self.btn_anim_s_pause = forms.Button()
        self.btn_anim_s_pause.Text = u"\u23F8 Pause"
        self.btn_anim_s_pause.Width = 80
        self.btn_anim_s_pause.Enabled = False
        self.btn_anim_s_pause.Click += self._on_anim_slime_pause
        self.btn_anim_s_reset = forms.Button()
        self.btn_anim_s_reset.Text = u"\u21BA Reset"
        self.btn_anim_s_reset.Width = 80
        self.btn_anim_s_reset.Click += self._on_anim_slime_reset
        self._anim_slime_panel.AddRow(self.btn_anim_s_play, self.btn_anim_s_pause,
                                      self.btn_anim_s_reset)

        self.sld_anim_s_speed, self.txt_anim_s_speed = self._int_slider(
            self._anim_slime_panel, "Speed", 1, 20, 5, self._on_anim_slime_speed_change)
        self.lbl_anim_s_frame = forms.Label()
        self.lbl_anim_s_frame.Text = "Frame: 0 / 0"
        self._anim_slime_panel.AddRow(self.lbl_anim_s_frame)

        inner.AddRow(self._anim_slime_panel)

        inner.AddRow(None)

        lbl_bake = forms.Label()
        lbl_bake.Text = "Bake"
        lbl_bake.Font = drawing.Font(lbl_bake.Font.Family, lbl_bake.Font.Size,
                                     drawing.FontStyle.Bold)
        inner.AddRow(lbl_bake)

        lbl_bm = forms.Label()
        lbl_bm.Text = "Bake Mode"
        lbl_bm.Width = 105
        self.dd_bake_mode = forms.DropDown()
        self.dd_bake_mode.Width = 150
        self.dd_bake_mode.Items.Add("All Together")
        self.dd_bake_mode.Items.Add("Group by Type")
        self.dd_bake_mode.Items.Add("Group by Agent")
        self.dd_bake_mode.SelectedIndex = 1
        inner.AddRow(lbl_bm, self.dd_bake_mode)

        btn_bake_w = forms.Button()
        btn_bake_w.Text = "Bake Wander"
        btn_bake_w.Width = 100
        btn_bake_w.Click += self._on_bake_wander
        btn_bake_s = forms.Button()
        btn_bake_s.Text = "Bake Slime"
        btn_bake_s.Width = 100
        btn_bake_s.Click += self._on_bake_slime
        btn_bake_all = forms.Button()
        btn_bake_all.Text = "Bake All"
        btn_bake_all.Width = 80
        btn_bake_all.Click += self._on_bake_all
        inner.AddRow(btn_bake_w, btn_bake_s, btn_bake_all)

        inner.AddRow(None)

        lbl_wd = forms.Label()
        lbl_wd.Text = "Wander Display"
        lbl_wd.Font = drawing.Font(lbl_wd.Font.Family, lbl_wd.Font.Size,
                                   drawing.FontStyle.Bold)
        inner.AddRow(lbl_wd)

        self.chk_show_wander = forms.CheckBox()
        self.chk_show_wander.Text = "Show Wander"
        self.chk_show_wander.Checked = True
        self.chk_show_wander.CheckedChanged += lambda s, e: self._update_path_display()
        inner.AddRow(self.chk_show_wander)

        self.sld_wander_width, self.txt_wander_width = self._int_slider(
            inner, "Width", 1, 10, 2, self._update_path_display)
        self.sld_wander_opacity, self.txt_wander_opacity = self._int_slider(
            inner, "Opacity", 0, 255, 255, self._update_path_display)

        self.btn_wander_col = forms.Button()
        self.btn_wander_col.Text = "Wander Colour"
        self.btn_wander_col.Width = 120
        self.btn_wander_col.BackgroundColor = drawing.Color.FromArgb(255, 200, 50)
        self.btn_wander_col.Click += self._on_pick_wander_color
        inner.AddRow(self.btn_wander_col)

        inner.AddRow(None)

        lbl_sd = forms.Label()
        lbl_sd.Text = "Slime Mould Display"
        lbl_sd.Font = drawing.Font(lbl_sd.Font.Family, lbl_sd.Font.Size,
                                   drawing.FontStyle.Bold)
        inner.AddRow(lbl_sd)

        self.chk_show_slime = forms.CheckBox()
        self.chk_show_slime.Text = "Show Slime"
        self.chk_show_slime.Checked = True
        self.chk_show_slime.CheckedChanged += lambda s, e: self._update_path_display()
        inner.AddRow(self.chk_show_slime)

        self.sld_slime_width, self.txt_slime_width = self._int_slider(
            inner, "Width", 1, 10, 2, self._update_path_display)
        self.sld_slime_opacity, self.txt_slime_opacity = self._int_slider(
            inner, "Opacity", 0, 255, 255, self._update_path_display)

        self.btn_slime_col = forms.Button()
        self.btn_slime_col.Text = "Slime Colour"
        self.btn_slime_col.Width = 120
        self.btn_slime_col.BackgroundColor = drawing.Color.FromArgb(50, 220, 120)
        self.btn_slime_col.Click += self._on_pick_slime_color
        inner.AddRow(self.btn_slime_col)

        inner.AddRow(None)

        lbl_ptd = forms.Label()
        lbl_ptd.Text = "Points"
        lbl_ptd.Font = drawing.Font(lbl_ptd.Font.Family, lbl_ptd.Font.Size,
                                    drawing.FontStyle.Bold)
        inner.AddRow(lbl_ptd)

        self.chk_show_path_pts = forms.CheckBox()
        self.chk_show_path_pts.Text = "Show Points"
        self.chk_show_path_pts.Checked = True
        self.chk_show_path_pts.CheckedChanged += lambda s, e: self._update_path_display()
        inner.AddRow(self.chk_show_path_pts)

        self.sld_pt_size, self.txt_pt_size = self._int_slider(
            inner, "Point Size", 2, 20, 8, self._update_path_display)

        self.btn_pt_col = forms.Button()
        self.btn_pt_col.Text = "Point Colour"
        self.btn_pt_col.Width = 120
        self.btn_pt_col.BackgroundColor = drawing.Color.FromArgb(255, 80, 80)
        self.btn_pt_col.Click += self._on_pick_point_color
        inner.AddRow(self.btn_pt_col)

        _sec_finish()

        # -- path influence ------------------------------------------------
        inner, _sec_finish = self._section(layout, "Path Influence", True)

        self.chk_use_paths = forms.CheckBox()
        self.chk_use_paths.Text = "Use Paths as Attractors"
        self.chk_use_paths.Checked = False
        self.chk_use_paths.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_use_paths)

        self.chk_path_carve = forms.CheckBox()
        self.chk_path_carve.Text = "Carve Mode (remove voxels near paths)"
        self.chk_path_carve.Checked = False
        self.chk_path_carve.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_path_carve)

        self.sld_path_r, self.txt_path_r = self._int_slider(
            inner, "Influence Radius (cells)", 0, 30, 3, self._mark_compute)
        self.sld_path_s, self.txt_path_s = self._float_slider(
            inner, "Path Strength", 0.0, 3.0, 1.0, self._mark_compute)

        inner.AddRow(None)

        self.chk_show_influence = forms.CheckBox()
        self.chk_show_influence.Text = "Show Influence Paths"
        self.chk_show_influence.Checked = True
        self.chk_show_influence.CheckedChanged += lambda s, e: self._update_influence_display()
        inner.AddRow(self.chk_show_influence)

        self.sld_inf_width, self.txt_inf_width = self._int_slider(
            inner, "Line Width", 1, 10, 2, self._update_influence_display)

        self.btn_inf_col = forms.Button()
        self.btn_inf_col.Text = "Path Colour"
        self.btn_inf_col.Width = 120
        self.btn_inf_col.BackgroundColor = drawing.Color.FromArgb(255, 130, 50)
        self.btn_inf_col.Click += self._on_pick_influence_color
        btn_clr_inf = forms.Button()
        btn_clr_inf.Text = "Clear Paths"
        btn_clr_inf.Width = 100
        btn_clr_inf.Click += self._on_clear_influence
        inner.AddRow(self.btn_inf_col, btn_clr_inf)

        inner.AddRow(None)
        inner.AddRow(self._bold("Noise Variation"))

        self.sld_scale, self.txt_scale = self._float_slider(
            inner, "Noise Scale", 0.01, 1.0, 0.15, self._mark_compute)
        self.sld_thresh, self.txt_thresh = self._float_slider(
            inner, "Threshold", 0.0, 1.0, 0.45, self._mark_compute)
        self.sld_oct, self.txt_oct = self._int_slider(
            inner, "Octaves", 1, 6, 3, self._mark_compute)
        self.sld_seed, self.txt_seed = self._int_slider(
            inner, "Seed", 0, 100, 0, self._mark_compute)

        _sec_finish()

        # -- display -------------------------------------------------------
        inner, _sec_finish = self._section(layout, "Display", False)

        self.chk_show_voxels = forms.CheckBox()
        self.chk_show_voxels.Text = "Show Voxels"
        self.chk_show_voxels.Checked = True
        self.chk_show_voxels.CheckedChanged += lambda s, e: self._update_voxel_visibility()

        self.chk_bounds = forms.CheckBox()
        self.chk_bounds.Text = "Show Bounding Box"
        self.chk_bounds.Checked = True
        self.chk_bounds.CheckedChanged += lambda s, e: self._mark_display()
        inner.AddRow(self.chk_show_voxels, self.chk_bounds)

        self.chk_edges = forms.CheckBox()
        self.chk_edges.Text = "Show Voxel Edges"
        self.chk_edges.Checked = True
        self.chk_edges.CheckedChanged += lambda s, e: self._mark_display()

        self.chk_vcol = forms.CheckBox()
        self.chk_vcol.Text = "Vertex Colours"
        self.chk_vcol.Checked = True
        self.chk_vcol.CheckedChanged += lambda s, e: self._toggle_vertex_colors()
        inner.AddRow(self.chk_edges, self.chk_vcol)

        self.sld_opacity, self.txt_opacity = self._int_slider(
            inner, "Voxel Opacity", 0, 255, 255, self._update_opacity)
        self.sld_edge_opacity, self.txt_edge_opacity = self._int_slider(
            inner, "Edge Opacity", 0, 255, 255, self._update_edge_opacity)

        self.btn_vcol = forms.Button()
        self.btn_vcol.Text = "Voxel Colour"
        self.btn_vcol.BackgroundColor = drawing.Color.FromArgb(100, 180, 255)
        self.btn_vcol.Click += self._on_pick_voxel_color

        self.btn_ecol = forms.Button()
        self.btn_ecol.Text = "Edge Colour"
        self.btn_ecol.BackgroundColor = drawing.Color.FromArgb(40, 40, 40)
        self.btn_ecol.Click += self._on_pick_edge_color

        self.btn_bcol = forms.Button()
        self.btn_bcol.Text = "Bounds Colour"
        self.btn_bcol.BackgroundColor = drawing.Color.FromArgb(80, 80, 80)
        self.btn_bcol.Click += self._on_pick_bounds_color
        inner.AddRow(self.btn_vcol, self.btn_ecol, self.btn_bcol)

        lbl_low = forms.Label()
        lbl_low.Text = "Low"
        lbl_low.Width = 30
        self.gradient_bar = forms.Drawable()
        self.gradient_bar.Size = drawing.Size(180, 18)
        self.gradient_bar.Paint += self._on_gradient_paint
        lbl_high = forms.Label()
        lbl_high.Text = "High"
        lbl_high.Width = 30
        inner.AddRow(lbl_low, self.gradient_bar, lbl_high)

        lbl_grad_desc = forms.Label()
        lbl_grad_desc.Text = "Colour = noise density (threshold \u2192 max)"
        inner.AddRow(lbl_grad_desc)

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
        """Create a bold label for section headers."""
        lbl = forms.Label()
        lbl.Text = text
        lbl.Font = drawing.Font(lbl.Font.Family, lbl.Font.Size, drawing.FontStyle.Bold)
        return lbl

    def _section(self, parent_layout, title, expanded=False):
        """Create a collapsible section with arrow indicator.
        Returns the inner DynamicLayout to add rows to.
        Call _section_end(parent_layout, ...) is not needed -- the section
        is self-contained and added to parent_layout immediately via the
        returned objects.  Usage:

            inner, finish = self._section(layout, "Title", expanded=True)
            inner.AddRow(...)
            finish()
        """
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
        """Create a label + slider + text box row for integer parameters.
        Slider and text box stay synced; on_change fires after either changes."""
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
            guard["u"] = True
            try:
                v = int(txt.Text)
                if v >= 1:
                    sld.Value = max(lo, min(hi, v))
            except:
                pass
            guard["u"] = False
            on_change()

        sld.ValueChanged += _sld
        txt.TextChanged += _txt
        layout.AddRow(lbl, sld, txt)
        return sld, txt

    def _float_slider(self, layout, name, lo, hi, default, on_change):
        """Create a label + slider + text box row for float parameters.
        Slider range 0-1000 is mapped to [lo, hi]. Text box accepts direct input."""
        lbl = forms.Label()
        lbl.Text = name
        lbl.Width = 105

        sld = forms.Slider()
        sld.MinValue = 0
        sld.MaxValue = 1000
        sld.Value = int((default - lo) / (hi - lo) * 1000)
        sld.Width = 150

        txt = forms.TextBox()
        txt.Text = "{:.3f}".format(default)
        txt.Width = 50

        guard = {"u": False}

        def _sld(s, e):
            if guard["u"]:
                return
            guard["u"] = True
            fv = lo + (sld.Value / 1000.0) * (hi - lo)
            txt.Text = "{:.3f}".format(fv)
            guard["u"] = False
            on_change()

        def _txt(s, e):
            if guard["u"]:
                return
            guard["u"] = True
            try:
                fv = float(txt.Text)
                if fv >= 0:
                    clamped = max(lo, min(hi, fv))
                    sld.Value = int((clamped - lo) / (hi - lo) * 1000)
            except:
                pass
            guard["u"] = False
            on_change()

        sld.ValueChanged += _sld
        txt.TextChanged += _txt
        layout.AddRow(lbl, sld, txt)
        return sld, txt

    def _fval(self, txt, sld, lo, hi):
        """Read a float from the text box, falling back to the slider position."""
        try:
            return float(txt.Text)
        except:
            return lo + (sld.Value / 1000.0) * (hi - lo)

    # -- dirty flags -------------------------------------------------------
    def _mark_compute(self):
        """Flag that noise field needs full recomputation (heavy)."""
        if self.chk_live.Checked == True:
            self._compute_dirty = True

    def _mark_display(self):
        """Flag that only mesh rebuild is needed (rotation, scale, colour)."""
        if self.chk_live.Checked == True:
            self._display_dirty = True

    # -- timer tick (debounce) ---------------------------------------------
    def _on_timer_tick(self, sender, e):
        """Fires every 0.12s. If compute dirty, do full regenerate (which also
        rebuilds display). If only display dirty, just rebuild mesh."""
        if self._compute_dirty:
            self._compute_dirty = False
            self._display_dirty = False
            self._full_regenerate()
        elif self._display_dirty:
            self._display_dirty = False
            self._display_only()

    # -- read params -------------------------------------------------------
    def _ival(self, txt, sld):
        """Read an integer from the text box, falling back to the slider value."""
        try:
            v = int(txt.Text)
            if v >= 1:
                return v
        except:
            pass
        return sld.Value

    def _read_params(self):
        """Collect all UI parameter values into a single tuple.
        Layout:  0-2  gx,gy,gz   3-5  cw,cl,ch   6-9  scale,thresh,octaves,seed
                10-13 use_paths,path_r,path_s,path_carve
                14-15 use_bounds,bounds_strict   16 grid_type"""
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
        use_paths = self.chk_use_paths.Checked == True
        path_r = self._ival(self.txt_path_r, self.sld_path_r)
        path_s = self._fval(self.txt_path_s, self.sld_path_s, 0.0, 3.0)
        path_carve = self.chk_path_carve.Checked == True
        use_bounds = self.chk_use_bounds.Checked == True
        bounds_strict = self.dd_clip_mode.SelectedIndex == 1
        grid_type = self.dd_grid_type.SelectedIndex
        return (gx, gy, gz, cw, cl, ch, scale, thresh, octaves, seed,
                use_paths, path_r, path_s, path_carve,
                use_bounds, bounds_strict, grid_type)

    # -- compute grid origin -----------------------------------------------
    def _grid_origin(self, gx, gy, gz, cw, cl, ch):
        """Return the world-space corner of the grid.  Centres on bounds
        geometry when Auto-Center on Bounds is active."""
        if (self.chk_bounds_center.Checked == True and
                self.bounds_aabb and self.bounds_aabb.IsValid and
                self.chk_use_bounds.Checked == True):
            c = self.bounds_aabb.Center
            return rg.Point3d(
                c.X - (gx * cw) * 0.5,
                c.Y - (gy * cl) * 0.5,
                c.Z - (gz * ch) * 0.5)
        return rg.Point3d.Origin

    # -- full regenerate ---------------------------------------------------
    def _full_regenerate(self):
        """Recompute voxel field, rebuild mesh, and update display.
        Captures existing path trails as curves before clearing them."""
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        scale, thresh, octaves, seed = p[6], p[7], p[8], p[9]
        use_paths, path_r, path_s, path_carve = p[10], p[11], p[12], p[13]
        use_bounds, bounds_strict = p[14], p[15]
        grid_type = p[16]

        path_keys = set()
        all_trails = (self.system.conduit.wander_trails +
                      self.system.conduit.slime_trails)
        if use_paths:
            for key_trail in self.pathfinder.trail_keys:
                for k in key_trail:
                    path_keys.add(k)

        if all_trails:
            self.system.conduit.influence_trails = [
                list(t) for t in all_trails if len(t) > 1]

        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        total = gx * gy * gz
        self.pathfinder.trails = []
        self.pathfinder.trail_keys = []
        self.pathfinder.graph = {}
        self.system.conduit.wander_trails = []
        self.system.conduit.slime_trails = []
        self.system.conduit.path_points = []
        self._anim_wander_trails = []
        self._anim_wander_max_frame = 0
        self._anim_slime_trails = []
        self._anim_slime_max_frame = 0
        if hasattr(self, '_anim_wander_timer'):
            self._anim_wander_stop()
        if hasattr(self, '_anim_slime_timer'):
            self._anim_slime_stop()
        if hasattr(self, 'lbl_anim_w_frame'):
            self.lbl_anim_w_frame.Text = "Frame: 0 / 0"
        if hasattr(self, 'lbl_anim_s_frame'):
            self.lbl_anim_s_frame.Text = "Frame: 0 / 0"
        if hasattr(self, 'lbl_wander_status'):
            self.lbl_wander_status.Text = "Wander: 0"
        if hasattr(self, 'lbl_slime_status'):
            self.lbl_slime_status.Text = "Slime: 0"
        self.lbl_status.Text = "Computing {} cells...".format(total)

        voxels = self.system.generate(
            gx, gy, gz, cw, cl, ch, scale, thresh, octaves, seed,
            use_paths, path_keys, path_r, path_s, path_carve,
            use_bounds, self.bounds_meshes, self.bounds_aabb, bounds_strict,
            grid_type, origin)

        show_bounds = self.chk_bounds.Checked == True
        show_edges = self.chk_edges.Checked == True
        use_custom = self.chk_use_custom.Checked == True
        custom_scale = self._fval(self.txt_custom_s, self.sld_custom_s, 0.1, 2.0)
        self.system.update_display(
            voxels, cw, cl, ch, self.voxel_color,
            show_bounds, self.bounds_color,
            show_edges, self.edge_color,
            gx, gy, gz, origin,
            grid_type, use_custom, custom_scale)

        self.lbl_status.Text = "Showing {} / {} voxels".format(len(voxels), total)
        self.gradient_bar.Invalidate()

    # -- display-only refresh ----------------------------------------------
    def _display_only(self):
        """Rebuild mesh from existing voxel data without recomputing noise.
        Triggered by colour or display toggle changes."""
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        grid_type = p[16]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        voxels = self.system.voxels
        show_bounds = self.chk_bounds.Checked == True
        show_edges = self.chk_edges.Checked == True
        use_custom = self.chk_use_custom.Checked == True
        custom_scale = self._fval(self.txt_custom_s, self.sld_custom_s, 0.1, 2.0)
        self.system.update_display(
            voxels, cw, cl, ch, self.voxel_color,
            show_bounds, self.bounds_color,
            show_edges, self.edge_color,
            gx, gy, gz, origin,
            grid_type, use_custom, custom_scale)
        self.gradient_bar.Invalidate()

    # -- button handlers ---------------------------------------------------
    def _on_refresh(self, sender, e):
        """Manual full recompute (ignores live-update toggle)."""
        self._full_regenerate()

    def _on_bake(self, sender, e):
        """Add the voxel mesh to the Rhino document as a mesh object."""
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        use_vc = self.chk_vcol.Checked == True
        self.system.bake(self.voxel_color, origin, use_vc)
        self.lbl_status.Text = "Baked {} voxels to document".format(len(self.system.voxels))

    def _on_bake_brep(self, sender, e):
        """Convert each voxel to a NURBS brep (polysurface) and add to document.
        Creates planar surfaces from mesh face corners, then joins per voxel.
        No colour or material attributes are applied."""
        mesh = self.system.conduit.mesh
        if not mesh or mesh.Faces.Count == 0:
            self.lbl_status.Text = "Nothing to bake"
            return
        self.lbl_status.Text = "Converting to Brep..."
        try:
            tol = sc.doc.ModelAbsoluteTolerance
            mverts = mesh.Vertices
            mfaces = mesh.Faces
            if self.system.custom_base_mesh:
                fpv = self.system.custom_base_mesh.Faces.Count
            elif self.dd_grid_type.SelectedIndex == 1:
                fpv = 38
            else:
                fpv = 6
            total = mfaces.Count
            num_groups = total // fpv
            count = 0
            _Pt3d = rg.Point3d
            _Corner = rg.Brep.CreateFromCornerPoints
            _Join = rg.Brep.JoinBreps
            for gi in range(num_groups):
                start = gi * fpv
                surfs = []
                for fi in range(start, start + fpv):
                    f = mfaces[fi]
                    if f.IsQuad:
                        srf = _Corner(
                            _Pt3d(mverts[f.A]), _Pt3d(mverts[f.B]),
                            _Pt3d(mverts[f.C]), _Pt3d(mverts[f.D]), tol)
                    else:
                        srf = _Corner(
                            _Pt3d(mverts[f.A]), _Pt3d(mverts[f.B]),
                            _Pt3d(mverts[f.C]), tol)
                    if srf:
                        surfs.append(srf)
                if surfs:
                    joined = _Join(surfs, tol)
                    if joined:
                        for b in joined:
                            sc.doc.Objects.AddBrep(b)
                            count += 1
                    else:
                        for s in surfs:
                            sc.doc.Objects.AddBrep(s)
                            count += 1
            sc.doc.Views.Redraw()
            self.lbl_status.Text = "Baked {} brep(s)".format(count)
        except Exception as ex:
            self.lbl_status.Text = "Brep failed: {}".format(str(ex))

    def _on_clear(self, sender, e):
        """Remove all preview geometry and reset state."""
        self._anim_wander_stop()
        self._anim_slime_stop()
        self._anim_wander_trails = []
        self._anim_wander_max_frame = 0
        self._anim_slime_trails = []
        self._anim_slime_max_frame = 0
        if hasattr(self, 'lbl_anim_w_frame'):
            self.lbl_anim_w_frame.Text = "Frame: 0 / 0"
        if hasattr(self, 'lbl_anim_s_frame'):
            self.lbl_anim_s_frame.Text = "Frame: 0 / 0"
        self.system.conduit.mesh = None
        self.system.conduit.edge_mesh = None
        self.system.conduit.bound_lines = []
        self.system.conduit.wander_trails = []
        self.system.conduit.slime_trails = []
        self.system.conduit.path_points = []
        self.system.voxels = []
        self.pathfinder.trails = []
        self.pathfinder.trail_keys = []
        self.pathfinder.graph = {}
        sc.doc.Views.Redraw()
        self.lbl_status.Text = "Cleared"
        if hasattr(self, 'lbl_wander_status'):
            self.lbl_wander_status.Text = "Wander: 0"
        if hasattr(self, 'lbl_slime_status'):
            self.lbl_slime_status.Text = "Slime: 0"

    def _on_closed(self, sender, e):
        """Clean up when the dialog window is closed."""
        self._timer.Stop()
        self._anim_wander_timer.Stop()
        self._anim_slime_timer.Stop()
        self.system.dispose()

    # -- bounding geometry -------------------------------------------------
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

    def _on_pick_bounds(self, sender, e):
        """Prompt user to select closed meshes or breps as bounding volume."""
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

    # -- custom voxel geometry ---------------------------------------------
    def _on_pick_custom(self, sender, e):
        """Prompt user to select geometry to use as the voxel shape template.
        Accepts mesh, brep, surface, or extrusion; converts all to mesh."""
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select geometry to use as voxel shape")
        go.GeometryFilter = (
            Rhino.DocObjects.ObjectType.Mesh |
            Rhino.DocObjects.ObjectType.Brep |
            Rhino.DocObjects.ObjectType.Surface |
            Rhino.DocObjects.ObjectType.Extrusion)
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            meshes = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if not geo:
                    continue
                geo = geo.Duplicate()
                if isinstance(geo, rg.Mesh):
                    meshes.append(geo)
                elif isinstance(geo, rg.Extrusion):
                    brep = geo.ToBrep()
                    if brep:
                        ms = rg.Mesh.CreateFromBrep(brep, rg.MeshingParameters())
                        if ms:
                            for m in ms:
                                meshes.append(m)
                elif isinstance(geo, rg.Brep):
                    ms = rg.Mesh.CreateFromBrep(geo, rg.MeshingParameters())
                    if ms:
                        for m in ms:
                            meshes.append(m)
                elif isinstance(geo, rg.Surface):
                    brep = geo.ToBrep()
                    if brep:
                        ms = rg.Mesh.CreateFromBrep(brep, rg.MeshingParameters())
                        if ms:
                            for m in ms:
                                meshes.append(m)
            if meshes:
                self.system.set_custom_geometry(meshes)
                self.lbl_custom.Text = "Custom: {} object(s)".format(go.ObjectCount)
                self.chk_use_custom.Checked = True
        self.Visible = True
        self._display_only()

    def _on_clear_custom(self, sender, e):
        self.system.set_custom_geometry(None)
        self.chk_use_custom.Checked = False
        self.lbl_custom.Text = "Custom: None"
        self._display_only()

    def _toggle_vertex_colors(self):
        """Switch between density-coloured and flat-shaded voxel rendering."""
        self.system.conduit.use_vertex_colors = self.chk_vcol.Checked == True
        sc.doc.Views.Redraw()

    # -- colour pickers ----------------------------------------------------
    def _on_pick_voxel_color(self, sender, e):
        """Open colour dialog for voxel face colour and update display."""
        cd = forms.ColorDialog()
        cd.Color = drawing.Color.FromArgb(self.voxel_color.R, self.voxel_color.G, self.voxel_color.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.voxel_color = System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb)
            self.btn_vcol.BackgroundColor = c
            self.system.conduit.shaded_material = rd.DisplayMaterial(
                System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb))
            self._display_only()

    def _on_pick_edge_color(self, sender, e):
        cd = forms.ColorDialog()
        cd.Color = drawing.Color.FromArgb(self.edge_color.R, self.edge_color.G, self.edge_color.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.edge_color = System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb)
            self.btn_ecol.BackgroundColor = c
            self._display_only()

    def _on_pick_bounds_color(self, sender, e):
        cd = forms.ColorDialog()
        cd.Color = drawing.Color.FromArgb(self.bounds_color.R, self.bounds_color.G, self.bounds_color.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.bounds_color = System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb)
            self.btn_bcol.BackgroundColor = c
            self._display_only()

    # -- gradient key ------------------------------------------------------
    def _on_gradient_paint(self, sender, e):
        """Paint the colour gradient bar showing density-to-colour mapping
        from threshold (dark) to 1.0 (brightest)."""
        g = e.Graphics
        w = self.gradient_bar.Width
        h = self.gradient_bar.Height
        if w <= 0 or h <= 0:
            return
        thresh = self._fval(self.txt_thresh, self.sld_thresh, 0.0, 1.0)
        steps = 50
        step_w = w / float(steps)
        cr = self.voxel_color.R
        cg = self.voxel_color.G
        cb = self.voxel_color.B
        for i in range(steps):
            t = i / float(steps - 1) if steps > 1 else 1.0
            val = thresh + t * (1.0 - thresh)
            r = max(30, min(255, int(cr * val)))
            gv = max(30, min(255, int(cg * val)))
            b = max(30, min(255, int(cb * val)))
            col = drawing.Color.FromArgb(r, gv, b)
            g.FillRectangle(col, float(i) * step_w, 0.0, step_w + 0.5, float(h))

    # -- pathfinding helpers ------------------------------------------------
    def _noop(self):
        """No-op callback for algorithm sliders (manual generate only)."""
        pass

    # -- opacity & voxel visibility ----------------------------------------
    def _update_opacity(self):
        """Push voxel opacity to conduit."""
        val = self._ival(self.txt_opacity, self.sld_opacity)
        self.system.conduit.voxel_opacity = val
        sc.doc.Views.Redraw()

    def _update_edge_opacity(self):
        """Push edge opacity to conduit."""
        val = self._ival(self.txt_edge_opacity, self.sld_edge_opacity)
        self.system.conduit.edge_opacity = val
        sc.doc.Views.Redraw()

    def _update_voxel_visibility(self):
        """Toggle voxel mesh visibility."""
        self.system.conduit.show_voxels = self.chk_show_voxels.Checked == True
        sc.doc.Views.Redraw()

    # -- path display ------------------------------------------------------
    def _update_path_display(self):
        """Push current path display settings to conduit and redraw."""
        c = self.system.conduit
        c.show_wander = self.chk_show_wander.Checked == True
        c.show_slime = self.chk_show_slime.Checked == True
        c.show_path_points = self.chk_show_path_pts.Checked == True
        c.wander_thickness = self._ival(
            self.txt_wander_width, self.sld_wander_width)
        c.slime_thickness = self._ival(
            self.txt_slime_width, self.sld_slime_width)
        c.wander_opacity = self._ival(
            self.txt_wander_opacity, self.sld_wander_opacity)
        c.slime_opacity = self._ival(
            self.txt_slime_opacity, self.sld_slime_opacity)
        c.path_point_size = self._ival(
            self.txt_pt_size, self.sld_pt_size)
        sc.doc.Views.Redraw()

    # -- start point handlers ----------------------------------------------
    def _on_pick_start_pts(self, sender, e):
        """Let user pick points in the viewport as path start locations."""
        self.Visible = False
        gp = Rhino.Input.Custom.GetPoint()
        gp.SetCommandPrompt("Pick start points (Enter when done)")
        pts = []
        while True:
            gp.Get()
            if gp.CommandResult() != Rhino.Commands.Result.Success:
                break
            pts.append(rg.Point3d(gp.Point()))
        if pts:
            self.pathfinder.start_points = pts
            self.lbl_start_count.Text = str(len(pts))
            self.system.conduit.path_points = list(pts)
            sc.doc.Views.Redraw()
        self.Visible = True

    def _on_clear_start_pts(self, sender, e):
        self.pathfinder.start_points = []
        self.lbl_start_count.Text = "0"
        self.system.conduit.path_points = []
        sc.doc.Views.Redraw()

    def _on_generate_random_starts(self, sender, e):
        """Auto-generate start points from graph nodes."""
        voxels = self.system.voxels
        if not voxels:
            self.lbl_start_count.Text = "err"
            return
        if not self.pathfinder.graph:
            p = self._read_params()
            gx, gy, gz = p[0], p[1], p[2]
            cw, cl, ch = p[3], p[4], p[5]
            grid_type = p[16]
            origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
            mode = self.dd_graph_mode.SelectedIndex
            if mode == 0:
                self.pathfinder.build_centre_graph(
                    voxels, cw, cl, ch, origin, grid_type)
            else:
                self.pathfinder.build_edge_graph(
                    voxels, cw, cl, ch, origin, grid_type)
        count = self._ival(self.txt_pf_agents, self.sld_pf_agents)
        seed = self._ival(self.txt_pf_seed, self.sld_pf_seed)
        self.pathfinder.generate_random_starts(count, seed)
        self.lbl_start_count.Text = str(len(self.pathfinder.start_points))
        self.system.conduit.path_points = list(self.pathfinder.start_points)
        sc.doc.Views.Redraw()

    # -- target pickers ----------------------------------------------------
    def _on_pick_target_pts(self, sender, e):
        """Pick target attractor points in the viewport."""
        self.Visible = False
        gp = Rhino.Input.Custom.GetPoint()
        gp.SetCommandPrompt("Pick target points (Enter when done)")
        pts = []
        while True:
            gp.Get()
            if gp.CommandResult() != Rhino.Commands.Result.Success:
                break
            pts.append(rg.Point3d(gp.Point()))
        if pts:
            self.pathfinder.target_points = pts
            self.lbl_tgt_pt_count.Text = str(len(pts))
        self.Visible = True

    def _on_clear_target_pts(self, sender, e):
        self.pathfinder.target_points = []
        self.lbl_tgt_pt_count.Text = "0"

    def _on_pick_target_curves(self, sender, e):
        """Select curves as pathfinding attractors."""
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select target curves")
        go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            self.pathfinder.target_curves = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if geo:
                    self.pathfinder.target_curves.append(geo.Duplicate())
            self.lbl_tgt_crv_count.Text = str(
                len(self.pathfinder.target_curves))
        self.Visible = True

    def _on_clear_target_curves(self, sender, e):
        self.pathfinder.target_curves = []
        self.lbl_tgt_crv_count.Text = "0"

    def _on_pick_target_geos(self, sender, e):
        """Select meshes/breps/surfaces as pathfinding attractors."""
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select target geometries (meshes, surfaces, breps)")
        go.GeometryFilter = (
            Rhino.DocObjects.ObjectType.Mesh |
            Rhino.DocObjects.ObjectType.Surface |
            Rhino.DocObjects.ObjectType.Brep |
            Rhino.DocObjects.ObjectType.Extrusion)
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            self.pathfinder.target_geos = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if geo:
                    dup = geo.Duplicate()
                    if isinstance(dup, rg.Extrusion):
                        brep = dup.ToBrep()
                        if brep:
                            dup = brep
                    self.pathfinder.target_geos.append(dup)
            self.lbl_tgt_geo_count.Text = str(
                len(self.pathfinder.target_geos))
        self.Visible = True

    def _on_clear_target_geos(self, sender, e):
        self.pathfinder.target_geos = []
        self.lbl_tgt_geo_count.Text = "0"

    # -- generate / clear / bake paths -------------------------------------
    def _ensure_graph(self):
        """Build graph from current voxels if needed."""
        voxels = self.system.voxels
        if not voxels:
            return False
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        grid_type = p[16]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        graph_mode = self.dd_graph_mode.SelectedIndex
        if graph_mode == 0:
            self.pathfinder.build_centre_graph(
                voxels, cw, cl, ch, origin, grid_type)
        else:
            self.pathfinder.build_edge_graph(
                voxels, cw, cl, ch, origin, grid_type)
        return True

    def _on_generate_wander(self, sender, e):
        """Run wander pathfinding from start points."""
        if not self._ensure_graph():
            self.lbl_wander_status.Text = "No voxels -- generate first"
            return
        max_steps = self._ival(self.txt_pf_steps, self.sld_pf_steps)
        density_str = self._fval(
            self.txt_pf_density, self.sld_pf_density, 0.0, 2.0)
        momentum = self._fval(
            self.txt_pf_momentum, self.sld_pf_momentum, 0.0, 2.0)
        separation = self._fval(
            self.txt_pf_sep, self.sld_pf_sep, 0.0, 2.0)
        wander = self._fval(
            self.txt_pf_wander, self.sld_pf_wander, 0.0, 2.0)
        repulse_r = self._fval(
            self.txt_pf_repulse, self.sld_pf_repulse, 0.0, 50.0)
        pf_seed = self._ival(self.txt_pf_seed, self.sld_pf_seed)
        branch_prob = self._fval(
            self.txt_pf_branch, self.sld_pf_branch, 0.0, 0.5)
        max_branches = self._ival(self.txt_pf_max_br, self.sld_pf_max_br)
        attr_str = self._fval(
            self.txt_pf_attr, self.sld_pf_attr, 0.0, 3.0)
        attr_r = self._fval(
            self.txt_pf_attr_r, self.sld_pf_attr_r, 1.0, 200.0)

        if not self.pathfinder.start_points:
            count = self._ival(self.txt_pf_agents, self.sld_pf_agents)
            self.pathfinder.generate_random_starts(count, pf_seed)
            self.lbl_start_count.Text = "{} auto".format(
                len(self.pathfinder.start_points))

        self.lbl_wander_status.Text = "Running wander..."
        trails = self.pathfinder.find_paths(
            max_steps, branch_prob, max_branches,
            density_str, attr_str, attr_r, repulse_r,
            momentum, separation, wander, pf_seed)
        self.system.conduit.wander_trails = trails
        self.system.conduit.path_points = list(self.pathfinder.start_points)
        self._anim_wander_stop()
        self._anim_wander_prepare()
        self._update_path_display()
        total_pts = sum(len(t) for t in trails)
        self.lbl_wander_status.Text = "{} paths, {} segs".format(
            len(trails), total_pts)

    def _on_generate_slime(self, sender, e):
        """Run slime mould pathfinding from targets."""
        if not self._ensure_graph():
            self.lbl_slime_status.Text = "No voxels -- generate first"
            return
        has_targets = (self.pathfinder.target_points or
                       self.pathfinder.target_curves or
                       self.pathfinder.target_geos)
        if not has_targets:
            self.lbl_slime_status.Text = "Slime needs targets -- assign pts/curves/geos"
            return
        max_steps = self._ival(self.txt_pf_steps, self.sld_pf_steps)
        density_str = self._fval(
            self.txt_pf_density, self.sld_pf_density, 0.0, 2.0)
        momentum = self._fval(
            self.txt_pf_momentum, self.sld_pf_momentum, 0.0, 2.0)
        separation = self._fval(
            self.txt_pf_sep, self.sld_pf_sep, 0.0, 2.0)
        wander = self._fval(
            self.txt_pf_wander, self.sld_pf_wander, 0.0, 2.0)
        repulse_r = self._fval(
            self.txt_pf_repulse, self.sld_pf_repulse, 0.0, 50.0)
        pf_seed = self._ival(self.txt_pf_seed, self.sld_pf_seed)
        branch_prob = self._fval(
            self.txt_pf_branch, self.sld_pf_branch, 0.0, 0.5)
        max_branches = self._ival(self.txt_pf_max_br, self.sld_pf_max_br)
        mould_d = self._ival(self.txt_mould_density, self.sld_mould_density)
        reinforce = self._fval(
            self.txt_reinforce, self.sld_reinforce, 0.0, 3.0)
        direction = self._fval(
            self.txt_direction, self.sld_direction, 0.0, 3.0)

        self.lbl_slime_status.Text = "Growing slime ({} agents)...".format(
            mould_d * len(self.pathfinder._collect_anchors()))
        trails = self.pathfinder.find_slime_paths(
            max_steps, density_str, momentum, separation,
            wander, repulse_r, mould_d, reinforce,
            direction, branch_prob, max_branches, pf_seed)
        anchors = self.pathfinder._collect_anchors()
        self.system.conduit.slime_trails = trails
        self.system.conduit.path_points = [a[1] for a in anchors]
        self._anim_slime_stop()
        self._anim_slime_prepare()
        self._update_path_display()
        total_pts = sum(len(t) for t in trails)
        self.lbl_slime_status.Text = "{} paths, {} segs".format(
            len(trails), total_pts)

    def _on_clear_wander(self, sender, e):
        self._anim_wander_stop()
        self._anim_wander_trails = []
        self._anim_wander_max_frame = 0
        self.lbl_anim_w_frame.Text = "Frame: 0 / 0"
        self.system.conduit.wander_trails = []
        if self.system.conduit.slime_trails:
            anchors = self.pathfinder._collect_anchors()
            self.system.conduit.path_points = [a[1] for a in anchors]
        else:
            self.system.conduit.path_points = []
        sc.doc.Views.Redraw()
        self.lbl_wander_status.Text = "Wander: 0"

    def _on_clear_slime(self, sender, e):
        self._anim_slime_stop()
        self._anim_slime_trails = []
        self._anim_slime_max_frame = 0
        self.lbl_anim_s_frame.Text = "Frame: 0 / 0"
        self.system.conduit.slime_trails = []
        if self.system.conduit.wander_trails:
            self.system.conduit.path_points = list(self.pathfinder.start_points)
        else:
            self.system.conduit.path_points = []
        sc.doc.Views.Redraw()
        self.lbl_slime_status.Text = "Slime: 0"

    def _on_wander_to_targets(self, sender, e):
        """Copy wander trails as target curves for slime mould mode."""
        trails = self.system.conduit.wander_trails
        if not trails:
            self.lbl_slime_status.Text = "No wander paths to use"
            return
        curves = []
        for trail in trails:
            if len(trail) > 1:
                curves.append(rg.PolylineCurve(trail))
        if curves:
            self.pathfinder.target_curves = (
                self.pathfinder.target_curves + curves)
            self.lbl_tgt_crv_count.Text = str(
                len(self.pathfinder.target_curves))
            self.lbl_slime_status.Text = "{} wander curves added as targets".format(
                len(curves))

    def _bake_trails(self, trails, layer_prefix, group_mode):
        """Bake a set of trails with grouping options.
        group_mode: 0=all together, 1=group by type, 2=group by agent."""
        if not trails:
            return 0
        attr = Rhino.DocObjects.ObjectAttributes()
        if not sc.doc.Layers.FindName(layer_prefix):
            sc.doc.Layers.Add(layer_prefix,
                              System.Drawing.Color.FromArgb(200, 200, 200))
        layer_idx = sc.doc.Layers.FindName(layer_prefix).Index
        attr.LayerIndex = layer_idx

        if group_mode == 0:
            grp = sc.doc.Groups.Add()
            count = 0
            for trail in trails:
                if len(trail) > 1:
                    plc = rg.PolylineCurve(trail)
                    oid = sc.doc.Objects.AddCurve(plc, attr)
                    sc.doc.Groups.AddToGroup(grp, oid)
                    count += 1
            return count
        elif group_mode == 1:
            grp = sc.doc.Groups.Add("{}_all".format(layer_prefix))
            count = 0
            for trail in trails:
                if len(trail) > 1:
                    plc = rg.PolylineCurve(trail)
                    oid = sc.doc.Objects.AddCurve(plc, attr)
                    sc.doc.Groups.AddToGroup(grp, oid)
                    count += 1
            return count
        else:
            count = 0
            for i, trail in enumerate(trails):
                if len(trail) > 1:
                    grp = sc.doc.Groups.Add(
                        "{}_agent_{}".format(layer_prefix, i))
                    plc = rg.PolylineCurve(trail)
                    oid = sc.doc.Objects.AddCurve(plc, attr)
                    sc.doc.Groups.AddToGroup(grp, oid)
                    count += 1
            return count

    def _on_bake_wander(self, sender, e):
        trails = self.system.conduit.wander_trails
        if not trails:
            self.lbl_wander_status.Text = "No wander paths to bake"
            return
        mode = self.dd_bake_mode.SelectedIndex
        count = self._bake_trails(trails, "Wander_Paths", mode)
        sc.doc.Views.Redraw()
        self.lbl_wander_status.Text = "Baked {} wander paths".format(count)

    def _on_bake_slime(self, sender, e):
        trails = self.system.conduit.slime_trails
        if not trails:
            self.lbl_slime_status.Text = "No slime paths to bake"
            return
        mode = self.dd_bake_mode.SelectedIndex
        count = self._bake_trails(trails, "Slime_Paths", mode)
        sc.doc.Views.Redraw()
        self.lbl_slime_status.Text = "Baked {} slime paths".format(count)

    def _on_bake_all(self, sender, e):
        mode = self.dd_bake_mode.SelectedIndex
        w = self._bake_trails(
            self.system.conduit.wander_trails, "Wander_Paths", mode)
        s = self._bake_trails(
            self.system.conduit.slime_trails, "Slime_Paths", mode)
        if w + s == 0:
            self.lbl_wander_status.Text = "No paths to bake"
            return
        for sp in self.pathfinder.start_points:
            sc.doc.Objects.AddPoint(sp)
        sc.doc.Views.Redraw()
        self.lbl_wander_status.Text = "Baked {} wander + {} slime".format(w, s)

    # -- animation controls -------------------------------------------------
    def _on_toggle_animate_wander(self, sender, e):
        self._anim_wander_panel.Visible = self.chk_animate_wander.Checked
        if not self.chk_animate_wander.Checked:
            self._anim_wander_stop()

    def _on_toggle_animate_slime(self, sender, e):
        self._anim_slime_panel.Visible = self.chk_animate_slime.Checked
        if not self.chk_animate_slime.Checked:
            self._anim_slime_stop()

    def _on_anim_wander_speed_change(self):
        speed = self._ival(self.txt_anim_w_speed, self.sld_anim_w_speed)
        self._anim_wander_timer.Interval = max(0.01, 0.2 / speed)

    def _on_anim_slime_speed_change(self):
        speed = self._ival(self.txt_anim_s_speed, self.sld_anim_s_speed)
        self._anim_slime_timer.Interval = max(0.01, 0.2 / speed)

    def _anim_wander_prepare(self):
        trails = self.system.conduit.wander_trails
        if not trails:
            return
        self._anim_wander_trails = [list(t) for t in trails]
        self._anim_wander_points = list(self.system.conduit.path_points)
        self._anim_wander_max_frame = max(len(t) for t in trails)
        self._anim_wander_frame = 0
        self.lbl_anim_w_frame.Text = "Frame: 0 / {}".format(
            self._anim_wander_max_frame)

    def _anim_slime_prepare(self):
        trails = self.system.conduit.slime_trails
        if not trails:
            return
        self._anim_slime_trails = [list(t) for t in trails]
        self._anim_slime_points = list(self.system.conduit.path_points)
        self._anim_slime_max_frame = max(len(t) for t in trails)
        self._anim_slime_frame = 0
        self.lbl_anim_s_frame.Text = "Frame: 0 / {}".format(
            self._anim_slime_max_frame)

    def _anim_wander_show_frame(self, frame):
        visible = []
        for trail in self._anim_wander_trails:
            n = min(frame + 1, len(trail))
            if n >= 2:
                visible.append(trail[:n])
        self.system.conduit.wander_trails = visible
        if frame == 0:
            self.system.conduit.path_points = list(self._anim_wander_points)
        sc.doc.Views.Redraw()

    def _anim_slime_show_frame(self, frame):
        visible = []
        for trail in self._anim_slime_trails:
            n = min(frame + 1, len(trail))
            if n >= 2:
                visible.append(trail[:n])
        self.system.conduit.slime_trails = visible
        if frame == 0:
            self.system.conduit.path_points = list(self._anim_slime_points)
        sc.doc.Views.Redraw()

    def _on_anim_wander_play(self, sender, e):
        trails = self.system.conduit.wander_trails
        if not trails:
            self.lbl_wander_status.Text = "Generate wander first"
            return
        if self._anim_wander_max_frame == 0:
            self._anim_wander_prepare()
        if self._anim_wander_frame >= self._anim_wander_max_frame:
            self._anim_wander_frame = 0
        self._anim_wander_playing = True
        self.btn_anim_w_play.Enabled = False
        self.btn_anim_w_pause.Enabled = True
        self._on_anim_wander_speed_change()
        self._anim_wander_timer.Start()

    def _on_anim_wander_pause(self, sender, e):
        self._anim_wander_playing = False
        self._anim_wander_timer.Stop()
        self.btn_anim_w_play.Enabled = True
        self.btn_anim_w_pause.Enabled = False

    def _on_anim_wander_reset(self, sender, e):
        self._anim_wander_stop()
        if self._anim_wander_trails:
            self.system.conduit.wander_trails = self._anim_wander_trails
            sc.doc.Views.Redraw()
            total = sum(len(t) for t in self._anim_wander_trails)
            self.lbl_wander_status.Text = "{} paths, {} segs".format(
                len(self._anim_wander_trails), total)
        self.lbl_anim_w_frame.Text = "Frame: 0 / {}".format(
            self._anim_wander_max_frame)

    def _anim_wander_stop(self):
        self._anim_wander_playing = False
        self._anim_wander_timer.Stop()
        self._anim_wander_frame = 0
        self.btn_anim_w_play.Enabled = True
        self.btn_anim_w_pause.Enabled = False

    def _on_anim_wander_tick(self, sender, e):
        if not self._anim_wander_playing:
            return
        self._anim_wander_frame += 1
        if self._anim_wander_frame > self._anim_wander_max_frame:
            self._anim_wander_frame = self._anim_wander_max_frame
            self._on_anim_wander_pause(None, None)
            return
        self._anim_wander_show_frame(self._anim_wander_frame)
        self.lbl_anim_w_frame.Text = "Frame: {} / {}".format(
            self._anim_wander_frame, self._anim_wander_max_frame)

    def _on_anim_slime_play(self, sender, e):
        trails = self.system.conduit.slime_trails
        if not trails:
            self.lbl_slime_status.Text = "Generate slime first"
            return
        if self._anim_slime_max_frame == 0:
            self._anim_slime_prepare()
        if self._anim_slime_frame >= self._anim_slime_max_frame:
            self._anim_slime_frame = 0
        self._anim_slime_playing = True
        self.btn_anim_s_play.Enabled = False
        self.btn_anim_s_pause.Enabled = True
        self._on_anim_slime_speed_change()
        self._anim_slime_timer.Start()

    def _on_anim_slime_pause(self, sender, e):
        self._anim_slime_playing = False
        self._anim_slime_timer.Stop()
        self.btn_anim_s_play.Enabled = True
        self.btn_anim_s_pause.Enabled = False

    def _on_anim_slime_reset(self, sender, e):
        self._anim_slime_stop()
        if self._anim_slime_trails:
            self.system.conduit.slime_trails = self._anim_slime_trails
            sc.doc.Views.Redraw()
            total = sum(len(t) for t in self._anim_slime_trails)
            self.lbl_slime_status.Text = "{} paths, {} segs".format(
                len(self._anim_slime_trails), total)
        self.lbl_anim_s_frame.Text = "Frame: 0 / {}".format(
            self._anim_slime_max_frame)

    def _anim_slime_stop(self):
        self._anim_slime_playing = False
        self._anim_slime_timer.Stop()
        self._anim_slime_frame = 0
        self.btn_anim_s_play.Enabled = True
        self.btn_anim_s_pause.Enabled = False

    def _on_anim_slime_tick(self, sender, e):
        if not self._anim_slime_playing:
            return
        self._anim_slime_frame += 1
        if self._anim_slime_frame > self._anim_slime_max_frame:
            self._anim_slime_frame = self._anim_slime_max_frame
            self._on_anim_slime_pause(None, None)
            return
        self._anim_slime_show_frame(self._anim_slime_frame)
        self.lbl_anim_s_frame.Text = "Frame: {} / {}".format(
            self._anim_slime_frame, self._anim_slime_max_frame)

    # -- colour pickers for paths and points --------------------------------
    def _on_pick_wander_color(self, sender, e):
        cd = forms.ColorDialog()
        wc = self.system.conduit.wander_color
        cd.Color = drawing.Color.FromArgb(wc.R, wc.G, wc.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.system.conduit.wander_color = System.Drawing.Color.FromArgb(
                c.Rb, c.Gb, c.Bb)
            self.btn_wander_col.BackgroundColor = c
            sc.doc.Views.Redraw()

    def _on_pick_slime_color(self, sender, e):
        cd = forms.ColorDialog()
        sc_col = self.system.conduit.slime_color
        cd.Color = drawing.Color.FromArgb(sc_col.R, sc_col.G, sc_col.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.system.conduit.slime_color = System.Drawing.Color.FromArgb(
                c.Rb, c.Gb, c.Bb)
            self.btn_slime_col.BackgroundColor = c
            sc.doc.Views.Redraw()

    def _on_pick_point_color(self, sender, e):
        cd = forms.ColorDialog()
        pc = self.system.conduit.path_point_color
        cd.Color = drawing.Color.FromArgb(pc.R, pc.G, pc.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.system.conduit.path_point_color = System.Drawing.Color.FromArgb(
                c.Rb, c.Gb, c.Bb)
            self.btn_pt_col.BackgroundColor = c
            sc.doc.Views.Redraw()

    # -- influence path display --------------------------------------------
    def _update_influence_display(self):
        cond = self.system.conduit
        cond.show_influence = self.chk_show_influence.Checked == True
        cond.influence_thickness = self._ival(self.txt_inf_width, self.sld_inf_width)
        sc.doc.Views.Redraw()

    def _on_pick_influence_color(self, sender, e):
        cd = forms.ColorDialog()
        ic = self.system.conduit.influence_color
        cd.Color = drawing.Color.FromArgb(ic.R, ic.G, ic.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.system.conduit.influence_color = System.Drawing.Color.FromArgb(
                c.Rb, c.Gb, c.Bb)
            self.btn_inf_col.BackgroundColor = c
            sc.doc.Views.Redraw()

    def _on_clear_influence(self, sender, e):
        self.system.conduit.influence_trails = []
        sc.doc.Views.Redraw()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    """Launch the Voxel Field Tool dialog as a modeless Eto window."""
    dlg = VoxelDialog()
    dlg.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    dlg.Show()

if __name__ == "__main__":
    main()
