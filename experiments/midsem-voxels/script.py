# Voxel Field Tool v01
# Perlin noise driven voxel carving with real-time Eto UI
# Environment: Rhino 8 Python
# Inputs: Grid dimensions, noise parameters, threshold, attractor points, base geometry
# Outputs: Voxel box geometry previewed live via display conduit

import Rhino
import Rhino.Geometry as rg
import Rhino.Display as rd
import scriptcontext as sc
import rhinoscriptsyntax as rs
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
    def __init__(self, seed=0):
        """Build a shuffled permutation table from the given seed."""
        random.seed(seed)
        self.p = list(range(256))
        random.shuffle(self.p)
        self.p *= 2

    def noise3d(self, x, y, z):
        """Single-octave 3D Perlin noise with inlined fade/lerp/grad for speed."""
        p = self.p
        _floor = math.floor
        xi = int(_floor(x)); yi = int(_floor(y)); zi = int(_floor(z))
        X = xi & 255; Y = yi & 255; Z = zi & 255
        x -= xi; y -= yi; z -= zi
        u = x * x * x * (x * (x * 6.0 - 15.0) + 10.0)
        v = y * y * y * (y * (y * 6.0 - 15.0) + 10.0)
        w = z * z * z * (z * (z * 6.0 - 15.0) + 10.0)
        A = p[X] + Y; AA = p[A] + Z; AB = p[A + 1] + Z
        B = p[X + 1] + Y; BA = p[B] + Z; BB = p[B + 1] + Z
        x1 = x - 1.0; y1 = y - 1.0; z1 = z - 1.0
        def _g(h, gx, gy, gz):
            h &= 15
            a = gx if h < 8 else gy
            b = gy if h < 4 else (gx if h == 12 or h == 14 else gz)
            return (a if (h & 1) == 0 else -a) + (b if (h & 2) == 0 else -b)
        g0 = _g(p[AA], x, y, z);     g1 = _g(p[BA], x1, y, z)
        g2 = _g(p[AB], x, y1, z);    g3 = _g(p[BB], x1, y1, z)
        g4 = _g(p[AA+1], x, y, z1);  g5 = _g(p[BA+1], x1, y, z1)
        g6 = _g(p[AB+1], x, y1, z1); g7 = _g(p[BB+1], x1, y1, z1)
        l0 = g0 + u * (g1 - g0); l1 = g2 + u * (g3 - g2)
        l2 = g4 + u * (g5 - g4); l3 = g6 + u * (g7 - g6)
        m0 = l0 + v * (l1 - l0); m1 = l2 + v * (l3 - l2)
        return m0 + w * (m1 - m0)

    def octave_noise(self, x, y, z, octaves=1):
        """Layer multiple noise frequencies (octaves) for richer detail.
        Each octave doubles frequency and halves amplitude."""
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
        self.show_bounds = True
        self.show_edges = True
        self.show_voxels = True
        self.use_vertex_colors = True
        self.shaded_material = rd.DisplayMaterial()
        self.voxel_opacity = 255
        self.path_trails = []
        self.path_color = System.Drawing.Color.FromArgb(255, 200, 50)
        self.path_thickness = 2
        self.show_paths = True
        self.path_points = []
        self.path_point_color = System.Drawing.Color.FromArgb(255, 80, 80)
        self.path_point_size = 8
        self.show_path_points = True

    def CalculateBoundingBox(self, e):
        """Expand the viewport clipping box to include all displayed geometry."""
        if self.bbox.IsValid:
            e.IncludeBoundingBox(self.bbox)

    def PostDrawObjects(self, e):
        """Draw voxel mesh (with opacity), edges, bounds, paths, and points."""
        if self.show_voxels and self.mesh and self.mesh.Vertices.Count > 0:
            if self.voxel_opacity >= 255:
                if self.use_vertex_colors:
                    e.Display.DrawMeshFalseColors(self.mesh)
                else:
                    e.Display.DrawMeshShaded(self.mesh, self.shaded_material)
            else:
                mat = rd.DisplayMaterial(self.shaded_material)
                mat.Transparency = 1.0 - self.voxel_opacity / 255.0
                e.Display.DrawMeshShaded(self.mesh, mat)
            if self.show_edges:
                wire = self.edge_mesh if self.edge_mesh else self.mesh
                e.Display.DrawMeshWires(wire, self.edge_color)
        if self.show_bounds and self.bound_lines:
            for ln in self.bound_lines:
                e.Display.DrawLine(ln, self.bound_color, 1)
        if self.show_paths and self.path_trails:
            for trail in self.path_trails:
                if len(trail) > 1:
                    e.Display.DrawPolyline(trail, self.path_color, self.path_thickness)
        if self.show_path_points and self.path_points:
            for pt in self.path_points:
                e.Display.DrawPoint(pt, rd.PointStyle.RoundControlPoint,
                                    self.path_point_size, self.path_point_color)


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

    def generate(self, grid_x, grid_y, grid_z, cell_w, cell_l, cell_h,
                 noise_scale, threshold, octaves, seed,
                 use_attractors, attractor_pts, attractor_curves, attractor_geos,
                 attr_radius, attr_strength,
                 use_base, base_geos, base_radius, base_strength, base_carve,
                 use_bounds, bounds_meshes, bounds_aabb, bounds_strict,
                 fill_grid, grid_type, grid_origin):
        """Sample Perlin noise across a 3D grid and collect voxels above threshold.
        grid_type 0 = cubic, 1 = BCC (truncated octahedron). BCC mode adds
        body-center positions at half-cell offsets. Returns list of
        (fx, fy, fz, val) where fx/fy/fz are float grid indices."""
        self.perlin = PerlinNoise(seed)
        oct_noise = self.perlin.octave_noise
        _closest = self._closest_dist
        voxels = []
        _append = voxels.append
        ox = grid_origin.X; oy = grid_origin.Y; oz = grid_origin.Z
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        inv_attr_r = 1.0 / attr_radius if attr_radius > 1e-10 else 0.0
        inv_base_r = 1.0 / base_radius if base_radius > 1e-10 else 0.0
        need_pt = ((use_base and base_geos) or
                   (use_attractors and (attractor_pts or attractor_curves or attractor_geos)) or
                   (use_bounds and bounds_meshes))
        half_bs = base_strength * 0.5
        _Point3d = rg.Point3d

        if use_bounds and bounds_meshes and bounds_aabb and bounds_aabb.IsValid:
            _bb_min = bounds_aabb.Min
            _bb_max = bounds_aabb.Max
            bb_min_x = _bb_min.X; bb_min_y = _bb_min.Y; bb_min_z = _bb_min.Z
            bb_max_x = _bb_max.X; bb_max_y = _bb_max.Y; bb_max_z = _bb_max.Z
            _do_bounds = True
            _bounds_meshes = bounds_meshes
            _bounds_strict = bounds_strict
        else:
            _do_bounds = False
            _bounds_meshes = None
            _bounds_strict = False
            bb_min_x = bb_min_y = bb_min_z = 0.0
            bb_max_x = bb_max_y = bb_max_z = 0.0

        positions = []
        for ix in range(grid_x):
            for iy in range(grid_y):
                for iz in range(grid_z):
                    positions.append((ix, iy, iz))
                    if grid_type == 1:
                        if ix < grid_x - 1 and iy < grid_y - 1 and iz < grid_z - 1:
                            positions.append((ix + 0.5, iy + 0.5, iz + 0.5))

        for (fx, fy, fz) in positions:
            cx_b = ox + fx * cell_w + hw
            cy_b = oy + fy * cell_l + hl
            cz_b = oz + fz * cell_h + hh

            if fill_grid:
                val = 1.0
            else:
                val = oct_noise(fx * noise_scale, fy * noise_scale,
                                fz * noise_scale, octaves)
                val = (val + 1.0) * 0.5

            if need_pt:
                pt = _Point3d(cx_b, cy_b, cz_b)

            if use_base and base_geos:
                min_d = float('inf')
                for geo in base_geos:
                    d = _closest(pt, geo)
                    if d < min_d:
                        min_d = d
                if base_carve:
                    if min_d < base_radius:
                        val -= (1.0 - min_d * inv_base_r) * base_strength
                else:
                    if min_d < base_radius:
                        val += (1.0 - min_d * inv_base_r) * base_strength
                    else:
                        val -= half_bs

            if use_attractors:
                if attractor_pts:
                    for apt in attractor_pts:
                        d = pt.DistanceTo(apt)
                        if d < attr_radius:
                            val += (1.0 - d * inv_attr_r) * attr_strength
                if attractor_curves:
                    for crv in attractor_curves:
                        d = _closest(pt, crv)
                        if d < attr_radius:
                            val += (1.0 - d * inv_attr_r) * attr_strength
                if attractor_geos:
                    for geo in attractor_geos:
                        d = _closest(pt, geo)
                        if d < attr_radius:
                            val += (1.0 - d * inv_attr_r) * attr_strength

            if val < 0.0:
                val = 0.0
            elif val > 1.0:
                val = 1.0

            if val > threshold:
                if _do_bounds:
                    if (pt.X < bb_min_x or pt.X > bb_max_x or
                        pt.Y < bb_min_y or pt.Y > bb_max_y or
                        pt.Z < bb_min_z or pt.Z > bb_max_z):
                        continue
                    if _bounds_strict:
                        _corners_ok = True
                        for cdx in (0.0, cell_w):
                            for cdy in (0.0, cell_l):
                                for cdz in (0.0, cell_h):
                                    cp = _Point3d(ox + fx * cell_w + cdx,
                                                  oy + fy * cell_l + cdy,
                                                  oz + fz * cell_h + cdz)
                                    _in = False
                                    for bm in _bounds_meshes:
                                        if bm.IsPointInside(cp, 0.001, False):
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
                        _in = False
                        for bm in _bounds_meshes:
                            if bm.IsPointInside(pt, 0.001, False):
                                _in = True
                                break
                        if not _in:
                            continue

                _append((fx, fy, fz, val))

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
        """Build display mesh using the user-assigned custom shape at each voxel.
        Falls back to build_mesh if no custom geo."""
        if not self.custom_base_mesh:
            return self.build_mesh(voxels, cell_w, cell_l, cell_h, color,
                                   grid_origin)
        mesh = rg.Mesh()
        verts = mesh.Vertices
        faces = mesh.Faces
        colors = mesh.VertexColors
        base = self.custom_base_mesh
        bv = base.Vertices; bf = base.Faces
        base_vcount = bv.Count; base_fcount = bf.Count
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        cr = color.R; cg = color.G; cb = color.B
        _FromArgb = System.Drawing.Color.FromArgb

        bv_cache = [(bv[i].X, bv[i].Y, bv[i].Z) for i in range(base_vcount)]
        bf_cache = []
        for fi in range(base_fcount):
            f = bf[fi]
            if f.IsQuad:
                bf_cache.append((f.A, f.B, f.C, f.D))
            else:
                bf_cache.append((f.A, f.B, f.C))

        sx = cell_w * custom_scale
        sy = cell_l * custom_scale
        sz = cell_h * custom_scale
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5

        for (fx, fy, fz, val) in voxels:
            cx = ox0 + fx * cell_w + hw
            cy = oy0 + fy * cell_l + hl
            cz = oz0 + fz * cell_h + hh
            base_idx = verts.Count
            for (bx, by, bz) in bv_cache:
                verts.Add(bx * sx + cx, by * sy + cy, bz * sz + cz)
            for fd in bf_cache:
                if len(fd) == 4:
                    faces.AddFace(fd[0]+base_idx, fd[1]+base_idx,
                                  fd[2]+base_idx, fd[3]+base_idx)
                else:
                    faces.AddFace(fd[0]+base_idx, fd[1]+base_idx, fd[2]+base_idx)
            rv = int(cr * val); gv = int(cg * val); bv_c = int(cb * val)
            if rv < 30: rv = 30
            elif rv > 255: rv = 255
            if gv < 30: gv = 30
            elif gv > 255: gv = 255
            if bv_c < 30: bv_c = 30
            elif bv_c > 255: bv_c = 255
            vc = _FromArgb(rv, gv, bv_c)
            for _ in range(base_vcount):
                colors.Add(vc)

        mesh.Normals.ComputeNormals()
        mesh.Compact()
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
        """Build a combined mesh of truncated octahedra (24 verts, 6 quad +
        8 hex faces each). Hex faces are fan-triangulated into 4 tris each.
        Total per TO: 6 quads + 32 triangles = 38 faces."""
        mesh = rg.Mesh()
        verts = mesh.Vertices
        faces = mesh.Faces
        colors = mesh.VertexColors
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        cr = color.R; cg = color.G; cb = color.B
        _FromArgb = System.Drawing.Color.FromArgb

        sw = cell_w * 0.25; sl = cell_l * 0.25; sh = cell_h * 0.25
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        to_verts = self._TO_VERTS
        to_quads = self._TO_QUADS
        to_hexes = self._TO_HEXES

        scaled = tuple((vx * sw, vy * sl, vz * sh) for (vx, vy, vz) in to_verts)

        for (fx, fy, fz, val) in voxels:
            cx = ox0 + fx * cell_w + hw
            cy = oy0 + fy * cell_l + hl
            cz = oz0 + fz * cell_h + hh
            b = verts.Count
            for (dx, dy, dz) in scaled:
                verts.Add(cx + dx, cy + dy, cz + dz)
            for (a, b2, c, d) in to_quads:
                faces.AddFace(b + a, b + b2, b + c, b + d)
            for hex_f in to_hexes:
                v0 = hex_f[0]
                for ti in range(1, 5):
                    faces.AddFace(b + v0, b + hex_f[ti], b + hex_f[ti + 1])
            rv = int(cr * val); gv = int(cg * val); bv_c = int(cb * val)
            if rv < 30: rv = 30
            elif rv > 255: rv = 255
            if gv < 30: gv = 30
            elif gv > 255: gv = 255
            if bv_c < 30: bv_c = 30
            elif bv_c > 255: bv_c = 255
            vc = _FromArgb(rv, gv, bv_c)
            for _ in range(24):
                colors.Add(vc)

        mesh.Normals.ComputeNormals()
        mesh.Compact()
        return mesh

    def _build_to_edge_mesh(self, voxels, cell_w, cell_l, cell_h, grid_origin):
        """Build a degenerate-triangle mesh containing only the 36 true edges
        of the truncated octahedron, excluding internal triangulation lines."""
        em = rg.Mesh()
        verts = em.Vertices
        faces = em.Faces
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        sw = cell_w * 0.25; sl = cell_l * 0.25; sh = cell_h * 0.25
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        scaled = tuple((vx * sw, vy * sl, vz * sh)
                        for (vx, vy, vz) in self._TO_VERTS)
        to_edges = self._TO_EDGES
        for (fx, fy, fz, val) in voxels:
            cx = ox0 + fx * cell_w + hw
            cy = oy0 + fy * cell_l + hl
            cz = oz0 + fz * cell_h + hh
            for (ei, ej) in to_edges:
                b = verts.Count
                dx0, dy0, dz0 = scaled[ei]
                dx1, dy1, dz1 = scaled[ej]
                verts.Add(cx + dx0, cy + dy0, cz + dz0)
                verts.Add(cx + dx1, cy + dy1, cz + dz1)
                verts.Add(cx + dx1, cy + dy1, cz + dz1)
                faces.AddFace(b, b + 1, b + 2)
        return em

    def build_mesh(self, voxels, cell_w, cell_l, cell_h, color, grid_origin):
        """Build a combined mesh of axis-aligned boxes (8 verts, 6 quad faces each).
        Vertex colours encode density (darker = lower val)."""
        mesh = rg.Mesh()
        verts = mesh.Vertices
        faces = mesh.Faces
        colors = mesh.VertexColors
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        cr = color.R; cg = color.G; cb = color.B
        _FromArgb = System.Drawing.Color.FromArgb

        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        default_offsets = (
            (-hw, -hl, -hh), ( hw, -hl, -hh), ( hw,  hl, -hh), (-hw,  hl, -hh),
            (-hw, -hl,  hh), ( hw, -hl,  hh), ( hw,  hl,  hh), (-hw,  hl,  hh))

        for (fx, fy, fz, val) in voxels:
            cx = ox0 + fx * cell_w + hw
            cy = oy0 + fy * cell_l + hl
            cz = oz0 + fz * cell_h + hh
            b = verts.Count
            for (dx, dy, dz) in default_offsets:
                verts.Add(cx + dx, cy + dy, cz + dz)
            faces.AddFace(b, b+1, b+2, b+3)
            faces.AddFace(b+4, b+7, b+6, b+5)
            faces.AddFace(b, b+4, b+5, b+1)
            faces.AddFace(b+2, b+6, b+7, b+3)
            faces.AddFace(b, b+3, b+7, b+4)
            faces.AddFace(b+1, b+5, b+6, b+2)
            rv = int(cr * val); gv = int(cg * val); bv_c = int(cb * val)
            if rv < 30: rv = 30
            elif rv > 255: rv = 255
            if gv < 30: gv = 30
            elif gv > 255: gv = 255
            if bv_c < 30: bv_c = 30
            elif bv_c > 255: bv_c = 255
            vc = _FromArgb(rv, gv, bv_c)
            for _ in range(8):
                colors.Add(vc)
        mesh.Normals.ComputeNormals()
        mesh.Compact()
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
        """Create a degenerate-triangle mesh from feature edge lines so they can
        be drawn as wireframe via DrawMeshWires for custom geometry voxels."""
        if not self.custom_base_edges:
            return None
        em = rg.Mesh()
        verts = em.Vertices
        faces = em.Faces
        ox0 = grid_origin.X
        oy0 = grid_origin.Y
        oz0 = grid_origin.Z
        sx = cell_w * custom_scale
        sy = cell_l * custom_scale
        sz = cell_h * custom_scale

        for (ix, iy, iz, val) in voxels:
            cx = ox0 + ix * cell_w + cell_w * 0.5
            cy = oy0 + iy * cell_l + cell_l * 0.5
            cz = oz0 + iz * cell_h + cell_h * 0.5

            for be in self.custom_base_edges:
                fr = be.From
                to = be.To
                b = verts.Count
                verts.Add(fr.X * sx + cx, fr.Y * sy + cy, fr.Z * sz + cz)
                verts.Add(to.X * sx + cx, to.Y * sy + cy, to.Z * sz + cz)
                verts.Add(to.X * sx + cx, to.Y * sy + cy, to.Z * sz + cz)
                faces.AddFace(b, b + 1, b + 2)
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


class VoxelPathfinder(object):
    def __init__(self):
        self.graph = {}
        self.node_positions = {}
        self.node_density = {}
        self.trails = []
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
        """Pick random graph nodes biased toward high density."""
        random.seed(seed)
        if not self.graph:
            self.start_points = []
            return
        nodes = list(self.graph.keys())
        sorted_nodes = sorted(
            nodes, key=lambda k: self.node_density.get(k, 0), reverse=True)
        pool = sorted_nodes[:max(1, len(sorted_nodes) // 3)]
        self.start_points = []
        for _ in range(min(count, len(pool))):
            k = pool[random.randint(0, len(pool) - 1)]
            self.start_points.append(self.node_positions[k])

    # -- Attractor distance helper ------------------------------------------
    def _attractor_score(self, nb_pos, curr_pos, attr_strength, attr_radius):
        """Compute attractor pull score for a candidate neighbour."""
        if attr_strength <= 0:
            return 0.0
        score = 0.0

        if self.target_points:
            best_d = float('inf')
            best_pt = None
            for tp in self.target_points:
                d = nb_pos.DistanceTo(tp)
                if d < best_d:
                    best_d = d
                    best_pt = tp
            if best_d < attr_radius:
                score += attr_strength * (1.0 - best_d / attr_radius)
            if best_pt is not None:
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
            for geo in all_geos:
                d = _closest_dist_static(nb_pos, geo)
                if d < best_d:
                    best_d = d
            if best_d < attr_radius:
                score += attr_strength * (1.0 - best_d / attr_radius)

        return score

    # -- Pathfinding --------------------------------------------------------
    def find_paths(self, max_steps, branch_prob, max_branches,
                   density_strength, attractor_strength, attractor_radius,
                   momentum_strength, separation_strength,
                   wander_strength, seed):
        """Run scored greedy walks from each start point through the graph.

        At every step each agent scores its neighbours by:
          density pull    -- prefer high-density nodes
          attractor pull  -- pull toward assigned target pts/curves/geos
          momentum        -- prefer continuing in the same direction
          separation      -- penalise previously visited nodes
          wander          -- random noise for organic variation

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
                        nb_pos, curr_pos, attractor_strength, attractor_radius)

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
        for agent in agents:
            if len(agent['trail']) > 1:
                pts = [positions[k] for k in agent['trail']]
                self.trails.append(pts)

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
        self.Padding = drawing.Padding(8)
        self.Resizable = True
        self.MinimumSize = drawing.Size(370, 700)

        self.system = VoxelSystem()
        self.attractor_pts = []
        self.attractor_curves = []
        self.attractor_geos = []
        self.base_geometries = []
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

        self._build_ui()

        self._timer = forms.UITimer()
        self._timer.Interval = 0.12
        self._timer.Elapsed += self._on_timer_tick
        self._timer.Start()

        self._full_regenerate()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self):
        layout = forms.DynamicLayout()
        layout.DefaultSpacing = drawing.Size(4, 4)
        layout.DefaultPadding = drawing.Padding(6)

        self.chk_live = forms.CheckBox()
        self.chk_live.Text = "Live Update"
        self.chk_live.Checked = True
        layout.AddRow(self.chk_live)

        self._link_guard = False

        # -- bounding geometry (first section) -----------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Bounding Geometry")
        exp.Expanded = True
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

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
        self.dd_clip_mode.Items.Add("Center Point")
        self.dd_clip_mode.Items.Add("All Corners")
        self.dd_clip_mode.SelectedIndex = 0
        self.dd_clip_mode.SelectedIndexChanged += lambda s, e: self._mark_compute()
        inner.AddRow(lbl_clip, self.dd_clip_mode)

        exp.Content = inner
        layout.AddRow(exp)

        # -- geometry input ------------------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Geometry Input")
        exp.Expanded = False
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

        btn_pick_base = forms.Button()
        btn_pick_base.Text = "Assign Base Geometry"
        btn_pick_base.Click += self._on_pick_base
        btn_clr_base = forms.Button()
        btn_clr_base.Text = "Clear Base"
        btn_clr_base.Click += self._on_clear_base
        inner.AddRow(btn_pick_base, btn_clr_base)

        self.lbl_base = forms.Label()
        self.lbl_base.Text = "Base: None"
        inner.AddRow(self.lbl_base)

        self.chk_use_base = forms.CheckBox()
        self.chk_use_base.Text = "Use Base Geometry"
        self.chk_use_base.Checked = False
        self.chk_use_base.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_use_base)

        self.chk_auto_center = forms.CheckBox()
        self.chk_auto_center.Text = "Auto-Center Grid on Base"
        self.chk_auto_center.Checked = True
        self.chk_auto_center.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_auto_center)

        self.chk_carve = forms.CheckBox()
        self.chk_carve.Text = "Carve Mode (invert base effect)"
        self.chk_carve.Checked = False
        self.chk_carve.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_carve)

        self.sld_base_r, self.txt_base_r = self._float_slider(inner, "Base Radius", 1.0, 80.0, 20.0, self._mark_compute)
        self.sld_base_s, self.txt_base_s = self._float_slider(inner, "Base Strength", 0.0, 1.0, 0.6, self._mark_compute)

        exp.Content = inner
        layout.AddRow(exp)

        # -- grid dimensions -----------------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Grid Dimensions")
        exp.Expanded = True
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

        lbl_gt = forms.Label()
        lbl_gt.Text = "Grid Type"
        lbl_gt.Width = 105
        self.dd_grid_type = forms.DropDown()
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

        exp.Content = inner
        layout.AddRow(exp)

        # -- noise parameters ----------------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Noise Parameters")
        exp.Expanded = True
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

        self.chk_fill_grid = forms.CheckBox()
        self.chk_fill_grid.Text = "Fill Grid (bypass noise)"
        self.chk_fill_grid.Checked = False
        self.chk_fill_grid.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_fill_grid)

        self.sld_scale, self.txt_scale = self._float_slider(inner, "Noise Scale", 0.01, 1.0, 0.15, self._mark_compute)
        self.sld_thresh, self.txt_thresh = self._float_slider(inner, "Threshold", 0.0, 1.0, 0.45, self._mark_compute)
        self.sld_oct, self.txt_oct = self._int_slider(inner, "Octaves", 1, 6, 3, self._mark_compute)
        self.sld_seed, self.txt_seed = self._int_slider(inner, "Seed", 0, 100, 0, self._mark_compute)

        exp.Content = inner
        layout.AddRow(exp)

        # -- attractor -----------------------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Attractor")
        exp.Expanded = False
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

        self.chk_attr = forms.CheckBox()
        self.chk_attr.Text = "Use Attractors"
        self.chk_attr.Checked = False
        self.chk_attr.CheckedChanged += lambda s, e: self._mark_compute()
        inner.AddRow(self.chk_attr)
        self.sld_attr_r, self.txt_attr_r = self._float_slider(inner, "Attr Radius", 1.0, 50.0, 15.0, self._mark_compute)
        self.sld_attr_s, self.txt_attr_s = self._float_slider(inner, "Attr Strength", 0.0, 1.0, 0.5, self._mark_compute)

        btn_pick = forms.Button()
        btn_pick.Text = "Assign Attr Pts"
        btn_pick.Click += self._on_pick_attractors
        btn_clr_attr = forms.Button()
        btn_clr_attr.Text = "Clear Pts"
        btn_clr_attr.Click += self._on_clear_attractors
        inner.AddRow(btn_pick, btn_clr_attr)

        self.lbl_attr_count = forms.Label()
        self.lbl_attr_count.Text = "Points: 0"
        inner.AddRow(self.lbl_attr_count)

        btn_pick_crv = forms.Button()
        btn_pick_crv.Text = "Assign Attr Curves"
        btn_pick_crv.Click += self._on_pick_attractor_curves
        btn_clr_crv = forms.Button()
        btn_clr_crv.Text = "Clear Curves"
        btn_clr_crv.Click += self._on_clear_attractor_curves
        inner.AddRow(btn_pick_crv, btn_clr_crv)

        self.lbl_attr_crv_count = forms.Label()
        self.lbl_attr_crv_count.Text = "Curves: 0"
        inner.AddRow(self.lbl_attr_crv_count)

        btn_pick_geo = forms.Button()
        btn_pick_geo.Text = "Assign Attr Geos"
        btn_pick_geo.Click += self._on_pick_attractor_geos
        btn_clr_geo = forms.Button()
        btn_clr_geo.Text = "Clear Geos"
        btn_clr_geo.Click += self._on_clear_attractor_geos
        inner.AddRow(btn_pick_geo, btn_clr_geo)

        self.lbl_attr_geo_count = forms.Label()
        self.lbl_attr_geo_count.Text = "Geometries: 0"
        inner.AddRow(self.lbl_attr_geo_count)

        exp.Content = inner
        layout.AddRow(exp)

        # -- custom voxel geometry -----------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Custom Voxel Geometry")
        exp.Expanded = False
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

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

        exp.Content = inner
        layout.AddRow(exp)

        # -- pathfinding -------------------------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Pathfinding")
        exp.Expanded = False
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

        lbl_gm = forms.Label()
        lbl_gm.Text = "Graph Mode"
        lbl_gm.Width = 105
        self.dd_graph_mode = forms.DropDown()
        self.dd_graph_mode.Items.Add("Voxel Centres")
        self.dd_graph_mode.Items.Add("Voxel Edges")
        self.dd_graph_mode.SelectedIndex = 0
        inner.AddRow(lbl_gm, self.dd_graph_mode)

        lbl_sp = forms.Label()
        lbl_sp.Text = "-- Start Points --"
        inner.AddRow(lbl_sp)

        self.sld_pf_agents, self.txt_pf_agents = self._int_slider(
            inner, "Agent Count", 1, 50, 5, self._noop)

        btn_pick_starts = forms.Button()
        btn_pick_starts.Text = "Assign Start Pts"
        btn_pick_starts.Click += self._on_pick_start_pts
        btn_clr_starts = forms.Button()
        btn_clr_starts.Text = "Clear"
        btn_clr_starts.Click += self._on_clear_start_pts
        btn_rand_starts = forms.Button()
        btn_rand_starts.Text = "Generate Random"
        btn_rand_starts.Click += self._on_generate_random_starts
        inner.AddRow(btn_pick_starts, btn_clr_starts, btn_rand_starts)

        self.lbl_start_count = forms.Label()
        self.lbl_start_count.Text = "Start Pts: 0"
        inner.AddRow(self.lbl_start_count)

        lbl_tgt = forms.Label()
        lbl_tgt.Text = "-- Targets --"
        inner.AddRow(lbl_tgt)

        btn_pick_tgt_pts = forms.Button()
        btn_pick_tgt_pts.Text = "Assign Target Pts"
        btn_pick_tgt_pts.Click += self._on_pick_target_pts
        btn_clr_tgt_pts = forms.Button()
        btn_clr_tgt_pts.Text = "Clear"
        btn_clr_tgt_pts.Click += self._on_clear_target_pts
        inner.AddRow(btn_pick_tgt_pts, btn_clr_tgt_pts)

        self.lbl_tgt_pt_count = forms.Label()
        self.lbl_tgt_pt_count.Text = "Target Pts: 0"
        inner.AddRow(self.lbl_tgt_pt_count)

        btn_pick_tgt_crv = forms.Button()
        btn_pick_tgt_crv.Text = "Assign Target Curves"
        btn_pick_tgt_crv.Click += self._on_pick_target_curves
        btn_clr_tgt_crv = forms.Button()
        btn_clr_tgt_crv.Text = "Clear"
        btn_clr_tgt_crv.Click += self._on_clear_target_curves
        inner.AddRow(btn_pick_tgt_crv, btn_clr_tgt_crv)

        self.lbl_tgt_crv_count = forms.Label()
        self.lbl_tgt_crv_count.Text = "Target Curves: 0"
        inner.AddRow(self.lbl_tgt_crv_count)

        btn_pick_tgt_geo = forms.Button()
        btn_pick_tgt_geo.Text = "Assign Target Geos"
        btn_pick_tgt_geo.Click += self._on_pick_target_geos
        btn_clr_tgt_geo = forms.Button()
        btn_clr_tgt_geo.Text = "Clear"
        btn_clr_tgt_geo.Click += self._on_clear_target_geos
        inner.AddRow(btn_pick_tgt_geo, btn_clr_tgt_geo)

        self.lbl_tgt_geo_count = forms.Label()
        self.lbl_tgt_geo_count.Text = "Target Geos: 0"
        inner.AddRow(self.lbl_tgt_geo_count)

        lbl_alg = forms.Label()
        lbl_alg.Text = "-- Algorithm --"
        inner.AddRow(lbl_alg)

        self.sld_pf_steps, self.txt_pf_steps = self._int_slider(
            inner, "Max Steps", 10, 500, 100, self._noop)
        self.sld_pf_branch, self.txt_pf_branch = self._float_slider(
            inner, "Branch Prob", 0.0, 0.3, 0.05, self._noop)
        self.sld_pf_max_br, self.txt_pf_max_br = self._int_slider(
            inner, "Max Branches", 0, 200, 50, self._noop)
        self.sld_pf_density, self.txt_pf_density = self._float_slider(
            inner, "Density Pull", 0.0, 2.0, 1.0, self._noop)
        self.sld_pf_attr, self.txt_pf_attr = self._float_slider(
            inner, "Attractor Pull", 0.0, 3.0, 1.5, self._noop)
        self.sld_pf_attr_r, self.txt_pf_attr_r = self._float_slider(
            inner, "Attr Radius", 1.0, 200.0, 50.0, self._noop)
        self.sld_pf_momentum, self.txt_pf_momentum = self._float_slider(
            inner, "Momentum", 0.0, 2.0, 0.8, self._noop)
        self.sld_pf_sep, self.txt_pf_sep = self._float_slider(
            inner, "Separation", 0.0, 2.0, 0.5, self._noop)
        self.sld_pf_wander, self.txt_pf_wander = self._float_slider(
            inner, "Wander", 0.0, 2.0, 0.3, self._noop)
        self.sld_pf_seed, self.txt_pf_seed = self._int_slider(
            inner, "Seed", 0, 100, 42, self._noop)

        btn_gen_paths = forms.Button()
        btn_gen_paths.Text = "Generate Paths"
        btn_gen_paths.Click += self._on_generate_paths
        btn_clr_paths = forms.Button()
        btn_clr_paths.Text = "Clear Paths"
        btn_clr_paths.Click += self._on_clear_paths
        btn_bake_paths = forms.Button()
        btn_bake_paths.Text = "Bake Paths"
        btn_bake_paths.Click += self._on_bake_paths
        inner.AddRow(btn_gen_paths, btn_clr_paths, btn_bake_paths)

        self.lbl_path_status = forms.Label()
        self.lbl_path_status.Text = "Paths: 0"
        inner.AddRow(self.lbl_path_status)

        lbl_pd = forms.Label()
        lbl_pd.Text = "-- Display --"
        inner.AddRow(lbl_pd)

        self.chk_show_paths = forms.CheckBox()
        self.chk_show_paths.Text = "Show Paths"
        self.chk_show_paths.Checked = True
        self.chk_show_paths.CheckedChanged += lambda s, e: self._update_path_display()

        self.chk_show_path_pts = forms.CheckBox()
        self.chk_show_path_pts.Text = "Show Points"
        self.chk_show_path_pts.Checked = True
        self.chk_show_path_pts.CheckedChanged += lambda s, e: self._update_path_display()
        inner.AddRow(self.chk_show_paths, self.chk_show_path_pts)

        self.sld_path_width, self.txt_path_width = self._int_slider(
            inner, "Path Width", 1, 10, 2, self._update_path_display)
        self.sld_pt_size, self.txt_pt_size = self._int_slider(
            inner, "Point Size", 2, 20, 8, self._update_path_display)

        self.btn_path_col = forms.Button()
        self.btn_path_col.Text = "Path Colour"
        self.btn_path_col.BackgroundColor = drawing.Color.FromArgb(255, 200, 50)
        self.btn_path_col.Click += self._on_pick_path_color

        self.btn_pt_col = forms.Button()
        self.btn_pt_col.Text = "Point Colour"
        self.btn_pt_col.BackgroundColor = drawing.Color.FromArgb(255, 80, 80)
        self.btn_pt_col.Click += self._on_pick_point_color
        inner.AddRow(self.btn_path_col, self.btn_pt_col)

        exp.Content = inner
        layout.AddRow(exp)

        # -- display -------------------------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Display")
        exp.Expanded = False
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

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
        self.gradient_bar.Size = drawing.Size(200, 18)
        self.gradient_bar.Paint += self._on_gradient_paint
        lbl_high = forms.Label()
        lbl_high.Text = "High"
        lbl_high.Width = 30
        inner.AddRow(lbl_low, self.gradient_bar, lbl_high)

        lbl_grad_desc = forms.Label()
        lbl_grad_desc.Text = "Colour = noise density (threshold \u2192 max)"
        inner.AddRow(lbl_grad_desc)

        exp.Content = inner
        layout.AddRow(exp)

        # -- controls ------------------------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Controls")
        exp.Expanded = True
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

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

        exp.Content = inner
        layout.AddRow(exp)

        scrollable = forms.Scrollable()
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
        """Collect all UI parameter values into a single tuple for passing
        to generate() and update_display()."""
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
        use_attr = self.chk_attr.Checked == True
        attr_r = self._fval(self.txt_attr_r, self.sld_attr_r, 1.0, 50.0)
        attr_s = self._fval(self.txt_attr_s, self.sld_attr_s, 0.0, 1.0)
        use_base = self.chk_use_base.Checked == True
        base_r = self._fval(self.txt_base_r, self.sld_base_r, 1.0, 80.0)
        base_s = self._fval(self.txt_base_s, self.sld_base_s, 0.0, 1.0)
        base_carve = self.chk_carve.Checked == True
        use_bounds = self.chk_use_bounds.Checked == True
        bounds_strict = self.dd_clip_mode.SelectedIndex == 1
        fill_grid = self.chk_fill_grid.Checked == True
        grid_type = self.dd_grid_type.SelectedIndex
        return (gx, gy, gz, cw, cl, ch, scale, thresh, octaves, seed,
                use_attr, attr_r, attr_s,
                use_base, base_r, base_s, base_carve,
                use_bounds, bounds_strict, fill_grid, grid_type)

    # -- compute grid origin -----------------------------------------------
    def _grid_origin(self, gx, gy, gz, cw, cl, ch):
        """Return the world-space corner of the grid. Bounds centering takes
        priority over base centering when both are active."""
        if (self.chk_bounds_center.Checked == True and
                self.bounds_aabb and self.bounds_aabb.IsValid and
                self.chk_use_bounds.Checked == True):
            c = self.bounds_aabb.Center
            return rg.Point3d(
                c.X - (gx * cw) * 0.5,
                c.Y - (gy * cl) * 0.5,
                c.Z - (gz * ch) * 0.5)
        if (self.chk_auto_center.Checked == True and
                self.base_geometries and
                self.chk_use_base.Checked == True):
            bbox = rg.BoundingBox.Empty
            for geo in self.base_geometries:
                gb = geo.GetBoundingBox(True)
                bbox.Union(gb)
            if bbox.IsValid:
                c = bbox.Center
                return rg.Point3d(
                    c.X - (gx * cw) * 0.5,
                    c.Y - (gy * cl) * 0.5,
                    c.Z - (gz * ch) * 0.5)
        return rg.Point3d.Origin

    # -- full regenerate ---------------------------------------------------
    def _full_regenerate(self):
        """Recompute noise field from scratch, rebuild mesh, and update display.
        Triggered by changes to grid size, noise params, or attractors."""
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        scale, thresh, octaves, seed = p[6], p[7], p[8], p[9]
        use_attr, attr_r, attr_s = p[10], p[11], p[12]
        use_base, base_r, base_s, base_carve = p[13], p[14], p[15], p[16]
        use_bounds, bounds_strict = p[17], p[18]
        fill_grid = p[19]
        grid_type = p[20]

        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        total = gx * gy * gz
        self.pathfinder.trails = []
        self.pathfinder.graph = {}
        self.system.conduit.path_trails = []
        self.system.conduit.path_points = []
        if hasattr(self, 'lbl_path_status'):
            self.lbl_path_status.Text = "Paths: 0"
        self.lbl_status.Text = "Computing {} cells...".format(total)

        voxels = self.system.generate(
            gx, gy, gz, cw, cl, ch, scale, thresh, octaves, seed,
            use_attr, self.attractor_pts, self.attractor_curves,
            self.attractor_geos, attr_r, attr_s,
            use_base, self.base_geometries, base_r, base_s, base_carve,
            use_bounds, self.bounds_meshes, self.bounds_aabb, bounds_strict,
            fill_grid, grid_type, origin)

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
        grid_type = p[20]
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
        self.system.conduit.mesh = None
        self.system.conduit.edge_mesh = None
        self.system.conduit.bound_lines = []
        self.system.conduit.path_trails = []
        self.system.conduit.path_points = []
        self.system.voxels = []
        self.pathfinder.trails = []
        self.pathfinder.graph = {}
        sc.doc.Views.Redraw()
        self.lbl_status.Text = "Cleared"
        self.lbl_path_status.Text = "Paths: 0"

    def _on_closed(self, sender, e):
        """Clean up when the dialog window is closed."""
        self._timer.Stop()
        self.system.dispose()

    # -- base geometry -----------------------------------------------------
    def _on_pick_base(self, sender, e):
        """Prompt user to select base geometry objects from the Rhino viewport."""
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select base geometry (curves, meshes, surfaces, breps)")
        go.GeometryFilter = (
            Rhino.DocObjects.ObjectType.Curve |
            Rhino.DocObjects.ObjectType.Mesh |
            Rhino.DocObjects.ObjectType.Surface |
            Rhino.DocObjects.ObjectType.Brep)
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            self.base_geometries = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if geo:
                    self.base_geometries.append(geo.Duplicate())
            self.lbl_base.Text = "Base: {} object(s)".format(len(self.base_geometries))
            self.chk_use_base.Checked = True
        self.Visible = True
        self._full_regenerate()

    def _on_clear_base(self, sender, e):
        self.base_geometries = []
        self.chk_use_base.Checked = False
        self.lbl_base.Text = "Base: None"
        self._full_regenerate()

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

    # -- attractors --------------------------------------------------------
    def _on_pick_attractors(self, sender, e):
        """Prompt user to select point objects as density attractors."""
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select attractor points")
        go.GeometryFilter = Rhino.DocObjects.ObjectType.Point
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            self.attractor_pts = []
            for i in range(go.ObjectCount):
                pt = go.Object(i).Point().Location
                self.attractor_pts.append(pt)
            self.lbl_attr_count.Text = "Points: {}".format(len(self.attractor_pts))
        self.Visible = True
        self._full_regenerate()

    def _on_clear_attractors(self, sender, e):
        self.attractor_pts = []
        self.lbl_attr_count.Text = "Points: 0"
        self._full_regenerate()

    # -- attractor curves --------------------------------------------------
    def _on_pick_attractor_curves(self, sender, e):
        """Prompt user to select curves as density attractors."""
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select attractor curves")
        go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            self.attractor_curves = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if geo:
                    self.attractor_curves.append(geo.Duplicate())
            self.lbl_attr_crv_count.Text = "Curves: {}".format(len(self.attractor_curves))
        self.Visible = True
        self._full_regenerate()

    def _on_clear_attractor_curves(self, sender, e):
        self.attractor_curves = []
        self.lbl_attr_crv_count.Text = "Curves: 0"
        self._full_regenerate()

    # -- attractor geometries ----------------------------------------------
    def _on_pick_attractor_geos(self, sender, e):
        """Prompt user to select meshes/breps/surfaces as density attractors."""
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select attractor geometries (meshes, surfaces, breps)")
        go.GeometryFilter = (
            Rhino.DocObjects.ObjectType.Mesh |
            Rhino.DocObjects.ObjectType.Surface |
            Rhino.DocObjects.ObjectType.Brep |
            Rhino.DocObjects.ObjectType.Extrusion)
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            self.attractor_geos = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if geo:
                    dup = geo.Duplicate()
                    if isinstance(dup, rg.Extrusion):
                        brep = dup.ToBrep()
                        if brep:
                            dup = brep
                    self.attractor_geos.append(dup)
            self.lbl_attr_geo_count.Text = "Geometries: {}".format(len(self.attractor_geos))
        self.Visible = True
        self._full_regenerate()

    def _on_clear_attractor_geos(self, sender, e):
        self.attractor_geos = []
        self.lbl_attr_geo_count.Text = "Geometries: 0"
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

    def _update_voxel_visibility(self):
        """Toggle voxel mesh visibility."""
        self.system.conduit.show_voxels = self.chk_show_voxels.Checked == True
        sc.doc.Views.Redraw()

    # -- path display ------------------------------------------------------
    def _update_path_display(self):
        """Push current path display settings to conduit and redraw."""
        self.system.conduit.show_paths = self.chk_show_paths.Checked == True
        self.system.conduit.show_path_points = self.chk_show_path_pts.Checked == True
        self.system.conduit.path_thickness = self._ival(
            self.txt_path_width, self.sld_path_width)
        self.system.conduit.path_point_size = self._ival(
            self.txt_pt_size, self.sld_pt_size)
        sc.doc.Views.Redraw()

    # -- start point handlers ----------------------------------------------
    def _on_pick_start_pts(self, sender, e):
        """Let user pick points in the viewport as path start locations."""
        pts = rs.GetPoints(True, message1="Pick start points (Enter to finish)")
        if pts:
            self.pathfinder.start_points = [rg.Point3d(p.X, p.Y, p.Z) for p in pts]
            self.lbl_start_count.Text = "Start Pts: {}".format(len(self.pathfinder.start_points))
            self.system.conduit.path_points = list(self.pathfinder.start_points)
            sc.doc.Views.Redraw()

    def _on_clear_start_pts(self, sender, e):
        self.pathfinder.start_points = []
        self.lbl_start_count.Text = "Start Pts: 0"
        self.system.conduit.path_points = []
        sc.doc.Views.Redraw()

    def _on_generate_random_starts(self, sender, e):
        """Auto-generate start points from graph nodes."""
        voxels = self.system.voxels
        if not voxels:
            self.lbl_start_count.Text = "No voxels"
            return
        if not self.pathfinder.graph:
            p = self._read_params()
            gx, gy, gz = p[0], p[1], p[2]
            cw, cl, ch = p[3], p[4], p[5]
            grid_type = p[20]
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
        self.lbl_start_count.Text = "Start Pts: {}".format(len(self.pathfinder.start_points))
        self.system.conduit.path_points = list(self.pathfinder.start_points)
        sc.doc.Views.Redraw()

    # -- target pickers ----------------------------------------------------
    def _on_pick_target_pts(self, sender, e):
        pts = rs.GetPoints(True, message1="Pick target points (Enter to finish)")
        if pts:
            self.pathfinder.target_points = [rg.Point3d(p.X, p.Y, p.Z) for p in pts]
            self.lbl_tgt_pt_count.Text = "Target Pts: {}".format(
                len(self.pathfinder.target_points))

    def _on_clear_target_pts(self, sender, e):
        self.pathfinder.target_points = []
        self.lbl_tgt_pt_count.Text = "Target Pts: 0"

    def _on_pick_target_curves(self, sender, e):
        ids = rs.GetObjects("Select target curves", rs.filter.curve)
        if ids:
            self.pathfinder.target_curves = [
                rs.coercecurve(cid) for cid in ids if rs.coercecurve(cid)]
            self.lbl_tgt_crv_count.Text = "Target Curves: {}".format(
                len(self.pathfinder.target_curves))

    def _on_clear_target_curves(self, sender, e):
        self.pathfinder.target_curves = []
        self.lbl_tgt_crv_count.Text = "Target Curves: 0"

    def _on_pick_target_geos(self, sender, e):
        ids = rs.GetObjects("Select target meshes/breps/surfaces",
                            rs.filter.mesh | rs.filter.polysurface | rs.filter.surface)
        if ids:
            geos = []
            for gid in ids:
                g = rs.coercemesh(gid) or rs.coercebrep(gid) or rs.coercesurface(gid)
                if g:
                    geos.append(g)
            self.pathfinder.target_geos = geos
            self.lbl_tgt_geo_count.Text = "Target Geos: {}".format(
                len(self.pathfinder.target_geos))

    def _on_clear_target_geos(self, sender, e):
        self.pathfinder.target_geos = []
        self.lbl_tgt_geo_count.Text = "Target Geos: 0"

    # -- generate / clear / bake paths -------------------------------------
    def _on_generate_paths(self, sender, e):
        """Build graph from current voxels and run pathfinding."""
        voxels = self.system.voxels
        if not voxels:
            self.lbl_path_status.Text = "No voxels -- generate first"
            return

        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        grid_type = p[20]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)

        mode = self.dd_graph_mode.SelectedIndex
        self.lbl_path_status.Text = "Building {} graph...".format(
            "centre" if mode == 0 else "edge")
        if mode == 0:
            self.pathfinder.build_centre_graph(
                voxels, cw, cl, ch, origin, grid_type)
        else:
            self.pathfinder.build_edge_graph(
                voxels, cw, cl, ch, origin, grid_type)

        if not self.pathfinder.start_points:
            count = self._ival(self.txt_pf_agents, self.sld_pf_agents)
            seed = self._ival(self.txt_pf_seed, self.sld_pf_seed)
            self.pathfinder.generate_random_starts(count, seed)
            self.lbl_start_count.Text = "Start Pts: {} (auto)".format(
                len(self.pathfinder.start_points))

        max_steps = self._ival(self.txt_pf_steps, self.sld_pf_steps)
        branch_prob = self._fval(
            self.txt_pf_branch, self.sld_pf_branch, 0.0, 0.3)
        max_branches = self._ival(self.txt_pf_max_br, self.sld_pf_max_br)
        density_str = self._fval(
            self.txt_pf_density, self.sld_pf_density, 0.0, 2.0)
        attr_str = self._fval(
            self.txt_pf_attr, self.sld_pf_attr, 0.0, 3.0)
        attr_r = self._fval(
            self.txt_pf_attr_r, self.sld_pf_attr_r, 1.0, 200.0)
        momentum = self._fval(
            self.txt_pf_momentum, self.sld_pf_momentum, 0.0, 2.0)
        separation = self._fval(
            self.txt_pf_sep, self.sld_pf_sep, 0.0, 2.0)
        wander = self._fval(
            self.txt_pf_wander, self.sld_pf_wander, 0.0, 2.0)
        pf_seed = self._ival(self.txt_pf_seed, self.sld_pf_seed)

        self.lbl_path_status.Text = "Running pathfinding..."
        trails = self.pathfinder.find_paths(
            max_steps, branch_prob, max_branches,
            density_str, attr_str, attr_r,
            momentum, separation, wander, pf_seed)

        self.system.conduit.path_trails = trails
        self.system.conduit.path_points = list(self.pathfinder.start_points)
        self._update_path_display()

        total_pts = sum(len(t) for t in trails)
        self.lbl_path_status.Text = "{} paths, {} segments".format(
            len(trails), total_pts)

    def _on_clear_paths(self, sender, e):
        """Clear all paths from display."""
        self.pathfinder.trails = []
        self.system.conduit.path_trails = []
        self.system.conduit.path_points = []
        sc.doc.Views.Redraw()
        self.lbl_path_status.Text = "Paths: 0"

    def _on_bake_paths(self, sender, e):
        """Bake path trails as polyline curves and start points to the document."""
        trails = self.pathfinder.trails
        if not trails:
            self.lbl_path_status.Text = "No paths to bake"
            return
        count = 0
        for trail in trails:
            if len(trail) > 1:
                plc = rg.PolylineCurve(trail)
                sc.doc.Objects.AddCurve(plc)
                count += 1
        for sp in self.pathfinder.start_points:
            sc.doc.Objects.AddPoint(sp)
        sc.doc.Views.Redraw()
        self.lbl_path_status.Text = "Baked {} paths + {} pts".format(
            count, len(self.pathfinder.start_points))

    # -- colour pickers for paths and points --------------------------------
    def _on_pick_path_color(self, sender, e):
        cd = forms.ColorDialog()
        pc = self.system.conduit.path_color
        cd.Color = drawing.Color.FromArgb(pc.R, pc.G, pc.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.system.conduit.path_color = System.Drawing.Color.FromArgb(
                c.Rb, c.Gb, c.Bb)
            self.btn_path_col.BackgroundColor = c
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
