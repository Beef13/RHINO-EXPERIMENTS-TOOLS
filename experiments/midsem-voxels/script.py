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
        self.use_vertex_colors = True
        self.shaded_material = rd.DisplayMaterial()

    def CalculateBoundingBox(self, e):
        """Expand the viewport clipping box to include all displayed geometry."""
        if self.bbox.IsValid:
            e.IncludeBoundingBox(self.bbox)

    def PostDrawObjects(self, e):
        """Draw geometry each frame. Voxel mesh rendered as false-colour or shaded."""
        if self.mesh and self.mesh.Vertices.Count > 0:
            if self.use_vertex_colors:
                e.Display.DrawMeshFalseColors(self.mesh)
            else:
                e.Display.DrawMeshShaded(self.mesh, self.shaded_material)
            if self.show_edges:
                wire = self.edge_mesh if self.edge_mesh else self.mesh
                e.Display.DrawMeshWires(wire, self.edge_color)
        if self.show_bounds and self.bound_lines:
            for ln in self.bound_lines:
                e.Display.DrawLine(ln, self.bound_color, 1)


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

        # -- display -------------------------------------------------------
        exp = forms.Expander()
        exp.Header = self._bold("Display")
        exp.Expanded = False
        inner = forms.DynamicLayout()
        inner.DefaultSpacing = drawing.Size(4, 4)

        self.chk_bounds = forms.CheckBox()
        self.chk_bounds.Text = "Show Bounding Box"
        self.chk_bounds.Checked = True
        self.chk_bounds.CheckedChanged += lambda s, e: self._mark_display()

        self.chk_edges = forms.CheckBox()
        self.chk_edges.Text = "Show Voxel Edges"
        self.chk_edges.Checked = True
        self.chk_edges.CheckedChanged += lambda s, e: self._mark_display()
        inner.AddRow(self.chk_bounds, self.chk_edges)

        self.chk_vcol = forms.CheckBox()
        self.chk_vcol.Text = "Vertex Colours"
        self.chk_vcol.Checked = True
        self.chk_vcol.CheckedChanged += lambda s, e: self._toggle_vertex_colors()
        inner.AddRow(self.chk_vcol)

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
        self.system.voxels = []
        sc.doc.Views.Redraw()
        self.lbl_status.Text = "Cleared"

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
