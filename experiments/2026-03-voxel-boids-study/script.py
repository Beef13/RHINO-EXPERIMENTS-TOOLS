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
# Rhino DisplayConduit subclass that draws all preview geometry (voxel mesh,
# pipe mesh, melt mesh, boid trails, bounding box) directly into the viewport
# without baking to the document. Toggled on/off via .Enabled.
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
        self.trail_polylines = []
        self.trail_color = System.Drawing.Color.FromArgb(255, 120, 50)
        self.trail_thickness = 2
        self.show_trails = False
        self.use_vertex_colors = True
        self.shaded_material = rd.DisplayMaterial()
        self.pipe_mesh = None
        self.pipe_material = rd.DisplayMaterial()
        self.show_pipes = False
        self.melt_mesh = None
        self.show_melt = False

    def CalculateBoundingBox(self, e):
        """Expand the viewport clipping box to include all displayed geometry."""
        if self.bbox.IsValid:
            e.IncludeBoundingBox(self.bbox)
        if self.pipe_mesh and self.pipe_mesh.Vertices.Count > 0:
            e.IncludeBoundingBox(self.pipe_mesh.GetBoundingBox(False))
        if self.melt_mesh and self.melt_mesh.Vertices.Count > 0:
            e.IncludeBoundingBox(self.melt_mesh.GetBoundingBox(False))

    def PostDrawObjects(self, e):
        """Draw geometry each frame. Priority: melt mesh > (voxel mesh + pipes) > trails > bounds.
        Voxel mesh rendered as false-colour (density) or shaded (flat) based on toggle."""
        if self.show_melt and self.melt_mesh and self.melt_mesh.Vertices.Count > 0:
            e.Display.DrawMeshShaded(self.melt_mesh, self.shaded_material)
            if self.show_edges:
                e.Display.DrawMeshWires(self.melt_mesh, self.edge_color)
        else:
            if self.mesh and self.mesh.Vertices.Count > 0:
                if self.use_vertex_colors:
                    e.Display.DrawMeshFalseColors(self.mesh)
                else:
                    e.Display.DrawMeshShaded(self.mesh, self.shaded_material)
                if self.show_edges:
                    wire = self.edge_mesh if self.edge_mesh else self.mesh
                    e.Display.DrawMeshWires(wire, self.edge_color)
            if self.show_pipes and self.pipe_mesh and self.pipe_mesh.Vertices.Count > 0:
                e.Display.DrawMeshShaded(self.pipe_mesh, self.pipe_material)
        if self.show_trails and self.trail_polylines:
            for pl in self.trail_polylines:
                e.Display.DrawPolyline(pl, self.trail_color, self.trail_thickness)
        if self.show_bounds and self.bound_lines:
            for ln in self.bound_lines:
                e.Display.DrawLine(ln, self.bound_color, 1)


# ---------------------------------------------------------------------------
# Voxel System
# Core engine: generates voxel fields from Perlin noise, builds meshes for
# display, runs boid pathfinding along exposed edges, creates pipe meshes,
# and applies Laplacian smoothing for the melt/blend effect.
# ---------------------------------------------------------------------------
class VoxelSystem(object):
    def __init__(self):
        self.conduit = VoxelConduit()
        self.conduit.Enabled = True
        self.perlin = PerlinNoise(0)
        self.voxels = []
        self.boid_graph = {}
        self.boid_vertex_normals = {}
        self.boid_trails = []
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
                 hollow, shell_thickness,
                 use_base, base_geos, base_radius, base_strength, base_carve,
                 grid_origin):
        """Sample Perlin noise across a 3D grid and collect voxels above threshold.
        Attractor pts/curves/geos boost density nearby. Base geometry either
        concentrates or carves the field. Hollow mode keeps only the outer shell
        by checking 6-neighbour connectivity. Returns list of (ix, iy, iz, val)."""
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
                   (use_attractors and (attractor_pts or attractor_curves or attractor_geos)))
        half_bs = base_strength * 0.5
        _Point3d = rg.Point3d
        face_dirs = ((-1,0,0),(1,0,0),(0,-1,0),(0,1,0),(0,0,-1),(0,0,1))

        if hollow:
            raw = [[[0.0] * grid_z for _ in range(grid_y)] for _ in range(grid_x)]
            for ix in range(grid_x):
                nx_b = ix * noise_scale
                for iy in range(grid_y):
                    ny_b = iy * noise_scale
                    for iz in range(grid_z):
                        v = oct_noise(nx_b, ny_b, iz * noise_scale, octaves)
                        raw[ix][iy][iz] = (v + 1.0) * 0.5

        for ix in range(grid_x):
            nx_b = ix * noise_scale
            cx_b = ox + ix * cell_w + hw
            for iy in range(grid_y):
                ny_b = iy * noise_scale
                cy_b = oy + iy * cell_l + hl
                for iz in range(grid_z):
                    if hollow:
                        val = raw[ix][iy][iz]
                    else:
                        val = oct_noise(nx_b, ny_b, iz * noise_scale, octaves)
                        val = (val + 1.0) * 0.5

                    if need_pt:
                        pt = _Point3d(cx_b, cy_b, oz + iz * cell_h + hh)

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
                        if hollow:
                            is_interior = True
                            for dx, dy, dz in face_dirs:
                                nix = ix + dx; niy = iy + dy; niz = iz + dz
                                if (nix < 0 or nix >= grid_x or
                                    niy < 0 or niy >= grid_y or
                                    niz < 0 or niz >= grid_z):
                                    is_interior = False
                                    break
                                if raw[nix][niy][niz] <= threshold:
                                    is_interior = False
                                    break
                            depth = 0
                            if is_interior:
                                depth = min(ix, grid_x-1-ix, iy, grid_y-1-iy, iz, grid_z-1-iz)
                            if not is_interior or depth <= shell_thickness:
                                _append((ix, iy, iz, val))
                        else:
                            _append((ix, iy, iz, val))

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
                          grid_origin, custom_scale,
                          rotate=False, rot_max_rad=0.0, rot_axis=2,
                          rotate2=False, rot_max_rad2=0.0, rot_axis2=0,
                          dscale=False, dscale_min=1.0):
        """Build display mesh using the user-assigned custom shape at each voxel.
        Each shape is scaled to cell dims * custom_scale, optionally rotated on
        two axes and density-scaled. Falls back to build_mesh if no custom geo."""
        if not self.custom_base_mesh:
            return self.build_mesh(voxels, cell_w, cell_l, cell_h, color,
                                   grid_origin, rotate, rot_max_rad, rot_axis,
                                   rotate2, rot_max_rad2, rot_axis2,
                                   dscale, dscale_min)
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
        _rotate = self._rotate_pt
        _cos = math.cos; _sin = math.sin

        bv_cache = [(bv[i].X, bv[i].Y, bv[i].Z) for i in range(base_vcount)]
        bf_cache = []
        for fi in range(base_fcount):
            f = bf[fi]
            if f.IsQuad:
                bf_cache.append((f.A, f.B, f.C, f.D))
            else:
                bf_cache.append((f.A, f.B, f.C))

        sx_base = cell_w * custom_scale
        sy_base = cell_l * custom_scale
        sz_base = cell_h * custom_scale
        do_rot = rotate and abs(rot_max_rad) > 1e-6
        do_rot2 = rotate2 and abs(rot_max_rad2) > 1e-6
        ds_range = 1.0 - dscale_min
        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5

        for (ix, iy, iz, val) in voxels:
            cx = ox0 + ix * cell_w + hw
            cy = oy0 + iy * cell_l + hl
            cz = oz0 + iz * cell_h + hh
            if dscale:
                ds = dscale_min + val * ds_range
                sx = sx_base * ds; sy = sy_base * ds; sz = sz_base * ds
            else:
                sx = sx_base; sy = sy_base; sz = sz_base
            if do_rot:
                ca = _cos(val * rot_max_rad); sa = _sin(val * rot_max_rad)
            if do_rot2:
                ca2 = _cos(val * rot_max_rad2); sa2 = _sin(val * rot_max_rad2)
            base_idx = verts.Count
            for (bx, by, bz) in bv_cache:
                dx = bx * sx; dy = by * sy; dz = bz * sz
                if do_rot:
                    dx, dy, dz = _rotate(dx, dy, dz, ca, sa, rot_axis)
                if do_rot2:
                    dx, dy, dz = _rotate(dx, dy, dz, ca2, sa2, rot_axis2)
                verts.Add(dx + cx, dy + cy, dz + cz)
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

    def _rotate_pt(self, dx, dy, dz, cos_a, sin_a, axis):
        """Rotate point (dx,dy,dz) around a single axis. axis: 0=X, 1=Y, 2=Z."""
        if axis == 0:
            return (dx,
                    dy * cos_a - dz * sin_a,
                    dy * sin_a + dz * cos_a)
        elif axis == 1:
            return (dx * cos_a + dz * sin_a,
                    dy,
                    -dx * sin_a + dz * cos_a)
        else:
            return (dx * cos_a - dy * sin_a,
                    dx * sin_a + dy * cos_a,
                    dz)

    def build_mesh(self, voxels, cell_w, cell_l, cell_h, color, grid_origin,
                   rotate=False, rot_max_rad=0.0, rot_axis=2,
                   rotate2=False, rot_max_rad2=0.0, rot_axis2=0,
                   dscale=False, dscale_min=1.0):
        """Build a combined mesh of axis-aligned boxes (8 verts, 6 quad faces each).
        Vertex colours encode density (darker = lower val). Density-based scaling
        is neighbour-aware: shared faces stay full-size to avoid gaps. Two
        independent rotations can be applied sequentially per voxel."""
        mesh = rg.Mesh()
        verts = mesh.Vertices
        faces = mesh.Faces
        colors = mesh.VertexColors
        ox0 = grid_origin.X; oy0 = grid_origin.Y; oz0 = grid_origin.Z
        cr = color.R; cg = color.G; cb = color.B
        _FromArgb = System.Drawing.Color.FromArgb
        _rotate = self._rotate_pt
        _cos = math.cos; _sin = math.sin

        hw = cell_w * 0.5; hl = cell_l * 0.5; hh = cell_h * 0.5
        default_offsets = (
            (-hw, -hl, -hh), ( hw, -hl, -hh), ( hw,  hl, -hh), (-hw,  hl, -hh),
            (-hw, -hl,  hh), ( hw, -hl,  hh), ( hw,  hl,  hh), (-hw,  hl,  hh))
        do_rot = rotate and abs(rot_max_rad) > 1e-6
        do_rot2 = rotate2 and abs(rot_max_rad2) > 1e-6
        ds_range = 1.0 - dscale_min
        voxel_set = set((v[0], v[1], v[2]) for v in voxels) if dscale else None

        for (ix, iy, iz, val) in voxels:
            cx = ox0 + ix * cell_w + hw
            cy = oy0 + iy * cell_l + hl
            cz = oz0 + iz * cell_h + hh
            if dscale:
                s = dscale_min + val * ds_range
                x0 = -hw if (ix-1,iy,iz) in voxel_set else -hw*s
                x1 =  hw if (ix+1,iy,iz) in voxel_set else  hw*s
                y0 = -hl if (ix,iy-1,iz) in voxel_set else -hl*s
                y1 =  hl if (ix,iy+1,iz) in voxel_set else  hl*s
                z0 = -hh if (ix,iy,iz-1) in voxel_set else -hh*s
                z1 =  hh if (ix,iy,iz+1) in voxel_set else  hh*s
                pts = ((x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
                       (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1))
            else:
                pts = default_offsets
            b = verts.Count
            if do_rot or do_rot2:
                if do_rot:
                    ca = _cos(val * rot_max_rad); sa = _sin(val * rot_max_rad)
                if do_rot2:
                    ca2 = _cos(val * rot_max_rad2); sa2 = _sin(val * rot_max_rad2)
                for (dx, dy, dz) in pts:
                    rx, ry, rz = dx, dy, dz
                    if do_rot:
                        rx, ry, rz = _rotate(rx, ry, rz, ca, sa, rot_axis)
                    if do_rot2:
                        rx, ry, rz = _rotate(rx, ry, rz, ca2, sa2, rot_axis2)
                    verts.Add(cx + rx, cy + ry, cz + rz)
            else:
                for (dx, dy, dz) in pts:
                    verts.Add(cx + dx, cy + dy, cz + dz)
            faces.AddFace(b, b+1, b+2, b+3)
            faces.AddFace(b+4, b+7, b+6, b+5)
            faces.AddFace(b, b+4, b+5, b+1)
            faces.AddFace(b+2, b+6, b+7, b+3)
            faces.AddFace(b, b+3, b+7, b+4)
            faces.AddFace(b+1, b+5, b+6, b+2)
            rv = int(cr * val); gv = int(cg * val); bv = int(cb * val)
            if rv < 30: rv = 30
            elif rv > 255: rv = 255
            if gv < 30: gv = 30
            elif gv > 255: gv = 255
            if bv < 30: bv = 30
            elif bv > 255: bv = 255
            vc = _FromArgb(rv, gv, bv)
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

    def build_edge_graph(self, voxels, diagonals=True):
        """Build a graph of vertices on exposed voxel faces for boid pathfinding.
        Each exposed quad face contributes 4 edge connections (+ 2 diagonals if
        enabled). Also accumulates per-vertex outward normals for trail offset."""
        voxel_set = set()
        for (ix, iy, iz, val) in voxels:
            voxel_set.add((ix, iy, iz))
        graph = {}
        normals = {}
        _sqrt = math.sqrt
        for (ix, iy, iz, val) in voxels:
            for (dx, dy, dz) in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                if (ix+dx, iy+dy, iz+dz) in voxel_set:
                    continue
                if dx == 1:
                    x = ix+1; fv = ((x,iy,iz),(x,iy+1,iz),(x,iy+1,iz+1),(x,iy,iz+1))
                elif dx == -1:
                    fv = ((ix,iy,iz),(ix,iy,iz+1),(ix,iy+1,iz+1),(ix,iy+1,iz))
                elif dy == 1:
                    y = iy+1; fv = ((ix,y,iz),(ix,y,iz+1),(ix+1,y,iz+1),(ix+1,y,iz))
                elif dy == -1:
                    fv = ((ix,iy,iz),(ix+1,iy,iz),(ix+1,iy,iz+1),(ix,iy,iz+1))
                elif dz == 1:
                    z = iz+1; fv = ((ix,iy,z),(ix+1,iy,z),(ix+1,iy+1,z),(ix,iy+1,z))
                else:
                    fv = ((ix,iy,iz),(ix,iy+1,iz),(ix+1,iy+1,iz),(ix+1,iy,iz))
                v0,v1,v2,v3 = fv
                for a, b in ((v0,v1),(v1,v2),(v2,v3),(v3,v0)):
                    if a not in graph: graph[a] = set()
                    if b not in graph: graph[b] = set()
                    graph[a].add(b); graph[b].add(a)
                if diagonals:
                    if v0 not in graph: graph[v0] = set()
                    if v2 not in graph: graph[v2] = set()
                    graph[v0].add(v2); graph[v2].add(v0)
                    if v1 not in graph: graph[v1] = set()
                    if v3 not in graph: graph[v3] = set()
                    graph[v1].add(v3); graph[v3].add(v1)
                for vert in fv:
                    if vert not in normals:
                        normals[vert] = [0.0, 0.0, 0.0]
                    n = normals[vert]
                    n[0] += dx; n[1] += dy; n[2] += dz
        for v in normals:
            n = normals[v]
            l = _sqrt(n[0]*n[0] + n[1]*n[1] + n[2]*n[2])
            if l > 1e-10:
                inv = 1.0 / l
                normals[v] = (n[0]*inv, n[1]*inv, n[2]*inv)
            else:
                normals[v] = (0.0, 0.0, 0.0)
        self.boid_graph = graph
        self.boid_vertex_normals = normals

    def run_edge_boids(self, count, steps, min_angle, max_angle,
                       turn_chance, seed, cell_w, cell_l, cell_h,
                       grid_origin, offset=0.0, offset_tightness=0,
                       straight_angle=5.0, overlap=0.0,
                       boid_attractors=None, boid_attr_strength=0.0):
        """Simulate boid agents walking along the exposed-face edge graph.
        Each boid picks a random start vertex, then at each step chooses between
        continuing straight or turning based on turn_chance and angle limits.
        Visited edges are tracked globally to reduce overlap (unless overlap > 0).
        Attractor curves bias direction. Offset pushes trails outward along
        surface normals, smoothed by tightness iterations."""
        graph = self.boid_graph
        if not graph:
            self.boid_trails = []
            return
        _sqrt = math.sqrt; _acos = math.acos; _pi = math.pi
        _min = min; _max = max
        _Point3d = rg.Point3d; _Polyline = rg.Polyline
        rng = random.Random(seed + 99)
        _random = rng.random; _randint = rng.randint
        vertices = list(graph.keys())
        vcount = len(vertices)
        vnormals = self.boid_vertex_normals
        ox = grid_origin.X; oy = grid_origin.Y; oz = grid_origin.Z
        deg2rad = _pi / 180.0
        min_rad = min_angle * deg2rad; max_rad = max_angle * deg2rad
        straight_thresh = straight_angle * deg2rad
        allow_overlap = overlap > 1e-6
        use_attr = (boid_attractors and len(boid_attractors) > 0
                    and boid_attr_strength > 1e-6)
        trails = []
        visited_global = set()

        for _ in range(count):
            start = vertices[_randint(0, vcount - 1)]
            nbs = graph.get(start)
            if not nbs:
                continue
            free_nbs = []
            for nb in nbs:
                ek = (start, nb) if start < nb else (nb, start)
                if ek not in visited_global:
                    free_nbs.append(nb)
                elif allow_overlap and _random() < overlap:
                    free_nbs.append(nb)
            if not free_nbs:
                continue
            first = free_nbs[_randint(0, len(free_nbs) - 1)]
            h0 = first[0]-start[0]; h1 = first[1]-start[1]; h2 = first[2]-start[2]
            trail_v = [start, first]
            current = first
            ek = (start, first) if start < first else (first, start)
            visited_global.add(ek)

            for _ in range(steps - 1):
                cur_nbs = graph.get(current)
                if not cur_nbs:
                    break
                straight = None; turns = []
                for nb in cur_nbs:
                    ek = (current, nb) if current < nb else (nb, current)
                    if ek in visited_global:
                        if not (allow_overlap and _random() < overlap):
                            continue
                    d0 = nb[0]-current[0]; d1 = nb[1]-current[1]; d2 = nb[2]-current[2]
                    l1sq = h0*h0+h1*h1+h2*h2; l2sq = d0*d0+d1*d1+d2*d2
                    if l1sq < 1e-20 or l2sq < 1e-20:
                        ang = _pi
                    else:
                        dot = (h0*d0+h1*d1+h2*d2) / _sqrt(l1sq * l2sq)
                        if dot > 1.0: dot = 1.0
                        elif dot < -1.0: dot = -1.0
                        ang = _acos(dot)
                    if ang < straight_thresh:
                        straight = (nb, (d0, d1, d2))
                    elif min_rad <= ang <= max_rad:
                        turns.append((nb, (d0, d1, d2)))

                chosen = None
                if use_attr:
                    all_cands = []
                    if straight:
                        all_cands.append(straight)
                    all_cands.extend(turns)
                    if all_cands and _random() < boid_attr_strength:
                        best = None; best_dist = float('inf')
                        for cand in all_cands:
                            cnb = cand[0]
                            nb_pt = _Point3d(ox+cnb[0]*cell_w, oy+cnb[1]*cell_l, oz+cnb[2]*cell_h)
                            for crv in boid_attractors:
                                try:
                                    rc, t = crv.ClosestPoint(nb_pt)
                                    if rc:
                                        dd = nb_pt.DistanceTo(crv.PointAt(t))
                                        if dd < best_dist:
                                            best_dist = dd; best = cand
                                except:
                                    pass
                        if best:
                            chosen = best
                if not chosen:
                    if straight and turns:
                        if _random() < turn_chance:
                            chosen = turns[_randint(0, len(turns) - 1)]
                        else:
                            chosen = straight
                    elif straight:
                        chosen = straight
                    elif turns:
                        chosen = turns[_randint(0, len(turns) - 1)]
                if not chosen:
                    break
                next_v = chosen[0]; h0, h1, h2 = chosen[1]
                trail_v.append(next_v)
                ek = (current, next_v) if current < next_v else (next_v, current)
                visited_global.add(ek)
                current = next_v

            if len(trail_v) > 1:
                pts = []
                do_offset = abs(offset) > 1e-6
                if do_offset:
                    tn = []
                    for v in trail_v:
                        if v in vnormals:
                            n = vnormals[v]
                            tn.append([n[0], n[1], n[2]])
                        else:
                            tn.append([0.0, 0.0, 0.0])
                    for _ in range(offset_tightness):
                        sm = [tn[0][:]]
                        tlen = len(tn)
                        for j in range(1, tlen - 1):
                            p = tn[j-1]; c = tn[j]; nx = tn[j+1]
                            sm.append([(p[0]+c[0]+nx[0])*0.333333,
                                       (p[1]+c[1]+nx[1])*0.333333,
                                       (p[2]+c[2]+nx[2])*0.333333])
                        sm.append(tn[-1][:])
                        for sn in sm:
                            sl = _sqrt(sn[0]*sn[0]+sn[1]*sn[1]+sn[2]*sn[2])
                            if sl > 1e-10:
                                inv = 1.0/sl
                                sn[0] *= inv; sn[1] *= inv; sn[2] *= inv
                        tn = sm
                    for j in range(len(trail_v)):
                        vx, vy, vz = trail_v[j]
                        pts.append(_Point3d(ox+vx*cell_w+tn[j][0]*offset,
                                            oy+vy*cell_l+tn[j][1]*offset,
                                            oz+vz*cell_h+tn[j][2]*offset))
                else:
                    for (vx, vy, vz) in trail_v:
                        pts.append(_Point3d(ox+vx*cell_w, oy+vy*cell_l, oz+vz*cell_h))
                trails.append(_Polyline(pts))

        self.boid_trails = trails

    def fillet_trails(self, trails, radius):
        """Round sharp corners of boid polylines using quadratic Bezier arcs.
        Radius is clamped to 45% of adjacent segment lengths to prevent overlap."""
        if radius < 1e-6 or not trails:
            return trails
        filleted = []
        arc_steps = 6
        for pl in trails:
            if pl.Count < 3:
                filleted.append(pl)
                continue
            new_pts = [pl[0]]
            for i in range(1, pl.Count - 1):
                p_prev = pl[i - 1]
                p_curr = pl[i]
                p_next = pl[i + 1]
                v1 = rg.Vector3d(p_prev - p_curr)
                v2 = rg.Vector3d(p_next - p_curr)
                l1 = v1.Length
                l2 = v2.Length
                if l1 < 1e-10 or l2 < 1e-10:
                    new_pts.append(p_curr)
                    continue
                r = min(radius, l1 * 0.45, l2 * 0.45)
                if r < 1e-6:
                    new_pts.append(p_curr)
                    continue
                v1.Unitize()
                v2.Unitize()
                f_start = p_curr + v1 * r
                f_end = p_curr + v2 * r
                for j in range(arc_steps + 1):
                    t = j / float(arc_steps)
                    u = 1.0 - t
                    new_pts.append(rg.Point3d(
                        u * u * f_start.X + 2.0 * u * t * p_curr.X + t * t * f_end.X,
                        u * u * f_start.Y + 2.0 * u * t * p_curr.Y + t * t * f_end.Y,
                        u * u * f_start.Z + 2.0 * u * t * p_curr.Z + t * t * f_end.Z))
            new_pts.append(pl[pl.Count - 1])
            filleted.append(rg.Polyline(new_pts))
        return filleted

    def build_pipe_mesh(self, trails, radius, segments=8):
        """Extrude circular cross-sections along each trail polyline to create
        tube meshes. Uses parallel transport to prevent twist. Each tube gets
        start/end cap faces for a watertight result."""
        if radius < 1e-6 or not trails:
            return None
        combined = rg.Mesh()
        cv = combined.Vertices; cf = combined.Faces
        segs = max(4, segments)
        two_pi = 2.0 * math.pi
        ring_cs = []
        for j in range(segs):
            a = two_pi * j / segs
            ring_cs.append((math.cos(a), math.sin(a)))
        _CrossProduct = rg.Vector3d.CrossProduct
        for pl in trails:
            n = pl.Count
            if n < 2:
                continue
            bv = cv.Count
            prev_x = None
            for i in range(n):
                pt = pl[i]
                ptx = pt.X; pty = pt.Y; ptz = pt.Z
                if i == 0:
                    tan = rg.Vector3d(pl[1] - pl[0])
                elif i == n - 1:
                    tan = rg.Vector3d(pl[n - 1] - pl[n - 2])
                else:
                    tan = rg.Vector3d(pl[i + 1] - pl[i - 1])
                tan.Unitize()
                if prev_x is None:
                    up = rg.Vector3d(0, 0, 1) if abs(tan.Z) < 0.9 else rg.Vector3d(1, 0, 0)
                    x_ax = _CrossProduct(tan, up)
                    x_ax.Unitize()
                else:
                    d = prev_x.X*tan.X + prev_x.Y*tan.Y + prev_x.Z*tan.Z
                    x_ax = rg.Vector3d(prev_x.X - tan.X*d,
                                       prev_x.Y - tan.Y*d,
                                       prev_x.Z - tan.Z*d)
                    if x_ax.Length < 1e-10:
                        x_ax = prev_x
                    else:
                        x_ax.Unitize()
                y_ax = _CrossProduct(tan, x_ax)
                y_ax.Unitize()
                prev_x = x_ax
                xx = x_ax.X; xy = x_ax.Y; xz = x_ax.Z
                yx = y_ax.X; yy = y_ax.Y; yz = y_ax.Z
                for ca, sa in ring_cs:
                    cv.Add(ptx + (xx*ca + yx*sa) * radius,
                           pty + (xy*ca + yy*sa) * radius,
                           ptz + (xz*ca + yz*sa) * radius)
            for i in range(n - 1):
                b = bv + i * segs; nb = b + segs
                for j in range(segs):
                    jn = (j + 1) % segs
                    cf.AddFace(b + j, b + jn, nb + jn, nb + j)
            ci = cv.Count
            cv.Add(pl[0])
            for j in range(segs):
                cf.AddFace(ci, bv + (j+1)%segs, bv + j)
            ci = cv.Count
            cv.Add(pl[n - 1])
            lb = bv + (n - 1) * segs
            for j in range(segs):
                cf.AddFace(ci, lb + j, lb + (j+1)%segs)
        combined.Normals.ComputeNormals()
        combined.Compact()
        return combined

    def _laplacian_smooth(self, mesh, factor, iterations):
        """Iterative Laplacian mesh smoothing: each vertex moves toward the
        average of its neighbours by factor per iteration. Pre-builds adjacency
        into flat Python arrays to avoid .NET interop overhead in tight loops."""
        topo = mesh.TopologyVertices
        verts = mesh.Vertices
        tv_count = topo.Count
        if tv_count == 0 or iterations < 1:
            return
        adj = [None] * tv_count
        t2m = [None] * tv_count
        px = [0.0] * tv_count
        py = [0.0] * tv_count
        pz = [0.0] * tv_count
        for ti in range(tv_count):
            adj[ti] = list(topo.ConnectedTopologyVertices(ti))
            t2m[ti] = list(topo.MeshVertexIndices(ti))
            v = verts[t2m[ti][0]]
            px[ti] = v.X
            py[ti] = v.Y
            pz[ti] = v.Z
        for _ in range(iterations):
            nx = [0.0] * tv_count
            ny = [0.0] * tv_count
            nz = [0.0] * tv_count
            for ti in range(tv_count):
                nbs = adj[ti]
                nc = len(nbs)
                if nc == 0:
                    nx[ti] = px[ti]; ny[ti] = py[ti]; nz[ti] = pz[ti]
                    continue
                ax = ay = az = 0.0
                for ci in nbs:
                    ax += px[ci]; ay += py[ci]; az += pz[ci]
                inv = 1.0 / nc
                ax *= inv; ay *= inv; az *= inv
                nx[ti] = px[ti] + (ax - px[ti]) * factor
                ny[ti] = py[ti] + (ay - py[ti]) * factor
                nz[ti] = pz[ti] + (az - pz[ti]) * factor
            px = nx; py = ny; pz = nz
        _set = verts.SetVertex
        for ti in range(tv_count):
            x, y, z = px[ti], py[ti], pz[ti]
            for vi in t2m[ti]:
                _set(vi, x, y, z)
        mesh.Normals.ComputeNormals()

    def melt(self, smooth_iters, smooth_factor):
        """Combine the voxel mesh and pipe mesh into one, then apply Laplacian
        smoothing to blend them together. More iterations = more melted."""
        vm = self.conduit.mesh
        pm = self.conduit.pipe_mesh
        if not vm or vm.Vertices.Count == 0:
            return None
        result = vm.DuplicateMesh()
        if pm and pm.Vertices.Count > 0:
            result.Append(pm)
        if smooth_iters > 0 and result.Vertices.Count > 0:
            self._laplacian_smooth(result, smooth_factor, smooth_iters)
        result.Compact()
        return result

    def update_display(self, voxels, cell_w, cell_l, cell_h, color,
                       show_bounds, bounds_color,
                       show_edges, edge_color,
                       grid_x, grid_y, grid_z, grid_origin,
                       use_custom=False, custom_scale=1.0,
                       rotate=False, rot_max_rad=0.0, rot_axis=2,
                       rotate2=False, rot_max_rad2=0.0, rot_axis2=0,
                       dscale=False, dscale_min=1.0):
        """Rebuild the conduit's display mesh and bounding box from current
        parameters. Chooses custom or default box mesh, sets edge/bound overlays,
        and triggers a viewport redraw."""
        if use_custom and self.custom_base_mesh:
            self.conduit.mesh = self.build_mesh_custom(
                voxels, cell_w, cell_l, cell_h, color, grid_origin,
                custom_scale, rotate, rot_max_rad, rot_axis,
                rotate2, rot_max_rad2, rot_axis2,
                dscale, dscale_min)
            if show_edges:
                self.conduit.edge_mesh = self._build_edge_mesh(
                    voxels, cell_w, cell_l, cell_h, grid_origin, custom_scale)
            else:
                self.conduit.edge_mesh = None
        else:
            self.conduit.mesh = self.build_mesh(
                voxels, cell_w, cell_l, cell_h, color, grid_origin,
                rotate, rot_max_rad, rot_axis,
                rotate2, rot_max_rad2, rot_axis2,
                dscale, dscale_min)
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
        self.boid_attractor_curves = []
        self.base_geometries = []
        self.voxel_color = System.Drawing.Color.FromArgb(100, 180, 255)
        self.system.conduit.shaded_material = rd.DisplayMaterial(
            System.Drawing.Color.FromArgb(100, 180, 255))
        self.edge_color = System.Drawing.Color.FromArgb(40, 40, 40)
        self.bounds_color = System.Drawing.Color.FromArgb(80, 80, 80)
        self.trail_color = System.Drawing.Color.FromArgb(255, 120, 50)

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

        # -- geometry input ------------------------------------------------
        # Base geometry drives where voxels concentrate or get carved away.
        # Supports curves, meshes, surfaces, breps. Auto-center offsets the
        # grid origin to the base geometry's bounding box center.
        layout.AddRow(self._bold("Geometry Input"))

        btn_pick_base = forms.Button()
        btn_pick_base.Text = "Assign Base Geometry"
        btn_pick_base.Click += self._on_pick_base
        btn_clr_base = forms.Button()
        btn_clr_base.Text = "Clear Base"
        btn_clr_base.Click += self._on_clear_base
        layout.AddRow(btn_pick_base, btn_clr_base)

        self.lbl_base = forms.Label()
        self.lbl_base.Text = "Base: None"
        layout.AddRow(self.lbl_base)

        self.chk_use_base = forms.CheckBox()
        self.chk_use_base.Text = "Use Base Geometry"
        self.chk_use_base.Checked = False
        self.chk_use_base.CheckedChanged += lambda s, e: self._mark_compute()
        layout.AddRow(self.chk_use_base)

        self.chk_auto_center = forms.CheckBox()
        self.chk_auto_center.Text = "Auto-Center Grid on Base"
        self.chk_auto_center.Checked = True
        self.chk_auto_center.CheckedChanged += lambda s, e: self._mark_compute()
        layout.AddRow(self.chk_auto_center)

        self.chk_carve = forms.CheckBox()
        self.chk_carve.Text = "Carve Mode (invert base effect)"
        self.chk_carve.Checked = False
        self.chk_carve.CheckedChanged += lambda s, e: self._mark_compute()
        layout.AddRow(self.chk_carve)

        self.sld_base_r, self.txt_base_r = self._float_slider(layout, "Base Radius", 1.0, 80.0, 20.0, self._mark_compute)
        self.sld_base_s, self.txt_base_s = self._float_slider(layout, "Base Strength", 0.0, 1.0, 0.6, self._mark_compute)

        # -- grid dimensions -----------------------------------------------
        # Number of cells along each axis and physical size of each cell.
        # Grid X/Y/Z = cell count.  Voxel Width/Length/Height = cell size.
        layout.AddRow(self._bold("Grid Dimensions"))
        self.sld_gx, self.txt_gx = self._int_slider(layout, "Grid X", 1, 200, 10, self._mark_compute)
        self.sld_gy, self.txt_gy = self._int_slider(layout, "Grid Y", 1, 200, 10, self._mark_compute)
        self.sld_gz, self.txt_gz = self._int_slider(layout, "Grid Z", 1, 200, 10, self._mark_compute)
        self.sld_cw, self.txt_cw = self._float_slider(layout, "Voxel Width (X)", 0.1, 50.0, 2.0, self._mark_compute)
        self.sld_cl, self.txt_cl = self._float_slider(layout, "Voxel Length (Y)", 0.1, 50.0, 2.0, self._mark_compute)
        self.sld_ch, self.txt_ch = self._float_slider(layout, "Voxel Height (Z)", 0.1, 50.0, 2.0, self._mark_compute)

        # -- voxel rotation ------------------------------------------------
        # Rotate each voxel around a chosen axis by an angle proportional to
        # its density value (val * max_angle). Two independent rotations can
        # be stacked (applied sequentially) for compound twist effects.
        layout.AddRow(self._bold("Voxel Rotation"))

        self.chk_rotate = forms.CheckBox()
        self.chk_rotate.Text = "Enable Density Rotation"
        self.chk_rotate.Checked = False
        self.chk_rotate.CheckedChanged += lambda s, e: self._mark_display()
        layout.AddRow(self.chk_rotate)

        self.sld_rot_angle, self.txt_rot_angle = self._float_slider(
            layout, "Max Angle", 0.0, 360.0, 10.0, self._mark_display)

        lbl_axis = forms.Label()
        lbl_axis.Text = "Rotation Axis 1"
        lbl_axis.Width = 105
        self.dd_rot_axis = forms.DropDown()
        self.dd_rot_axis.Items.Add("X Axis")
        self.dd_rot_axis.Items.Add("Y Axis")
        self.dd_rot_axis.Items.Add("Z Axis")
        self.dd_rot_axis.SelectedIndex = 2
        self.dd_rot_axis.SelectedIndexChanged += lambda s, e: self._mark_display()
        layout.AddRow(lbl_axis, self.dd_rot_axis)

        self.chk_rotate2 = forms.CheckBox()
        self.chk_rotate2.Text = "Enable 2nd Rotation"
        self.chk_rotate2.Checked = False
        self.chk_rotate2.CheckedChanged += lambda s, e: self._mark_display()
        layout.AddRow(self.chk_rotate2)

        self.sld_rot_angle2, self.txt_rot_angle2 = self._float_slider(
            layout, "Max Angle 2", 0.0, 360.0, 10.0, self._mark_display)

        lbl_axis2 = forms.Label()
        lbl_axis2.Text = "Rotation Axis 2"
        lbl_axis2.Width = 105
        self.dd_rot_axis2 = forms.DropDown()
        self.dd_rot_axis2.Items.Add("X Axis")
        self.dd_rot_axis2.Items.Add("Y Axis")
        self.dd_rot_axis2.Items.Add("Z Axis")
        self.dd_rot_axis2.SelectedIndex = 0
        self.dd_rot_axis2.SelectedIndexChanged += lambda s, e: self._mark_display()
        layout.AddRow(lbl_axis2, self.dd_rot_axis2)

        # -- voxel density scale -------------------------------------------
        # Scale each voxel's size by its density. Min Scale sets the size at
        # density 0; density 1 is always full-size. Neighbour-aware: faces
        # touching an adjacent voxel stay full-size to prevent gaps.
        layout.AddRow(self._bold("Voxel Density Scale"))

        self.chk_dscale = forms.CheckBox()
        self.chk_dscale.Text = "Enable Density Scale"
        self.chk_dscale.Checked = False
        self.chk_dscale.CheckedChanged += lambda s, e: self._mark_display()
        layout.AddRow(self.chk_dscale)

        self.sld_dscale_min, self.txt_dscale_min = self._float_slider(
            layout, "Min Scale", 0.01, 1.0, 0.5, self._mark_display)

        # -- noise parameters ----------------------------------------------
        # Noise Scale = frequency (small = large blobs, big = fine detail).
        # Threshold = density cutoff to keep/discard a voxel.
        # Octaves = layers of detail. Seed = reproducible random state.
        layout.AddRow(self._bold("Noise Parameters"))
        self.sld_scale, self.txt_scale = self._float_slider(layout, "Noise Scale", 0.01, 1.0, 0.15, self._mark_compute)
        self.sld_thresh, self.txt_thresh = self._float_slider(layout, "Threshold", 0.0, 1.0, 0.45, self._mark_compute)
        self.sld_oct, self.txt_oct = self._int_slider(layout, "Octaves", 1, 6, 3, self._mark_compute)
        self.sld_seed, self.txt_seed = self._int_slider(layout, "Seed", 0, 100, 0, self._mark_compute)

        # -- hollow shell --------------------------------------------------
        # Remove interior voxels that are fully surrounded. Shell Thickness
        # controls how many layers deep the shell extends from exposed faces.
        layout.AddRow(self._bold("Hollow Shell"))
        self.chk_hollow = forms.CheckBox()
        self.chk_hollow.Text = "Enable Hollow Mode"
        self.chk_hollow.Checked = False
        self.chk_hollow.CheckedChanged += lambda s, e: self._mark_compute()
        layout.AddRow(self.chk_hollow)
        self.sld_shell, self.txt_shell = self._int_slider(layout, "Shell Thickness", 1, 5, 1, self._mark_compute)

        # -- attractor -----------------------------------------------------
        # Points, curves, or meshes that boost voxel density within a radius.
        # Strength controls how much the density is increased. Multiple
        # attractor types can be combined simultaneously.
        layout.AddRow(self._bold("Attractor"))
        self.chk_attr = forms.CheckBox()
        self.chk_attr.Text = "Use Attractors"
        self.chk_attr.Checked = False
        self.chk_attr.CheckedChanged += lambda s, e: self._mark_compute()
        layout.AddRow(self.chk_attr)
        self.sld_attr_r, self.txt_attr_r = self._float_slider(layout, "Attr Radius", 1.0, 50.0, 15.0, self._mark_compute)
        self.sld_attr_s, self.txt_attr_s = self._float_slider(layout, "Attr Strength", 0.0, 1.0, 0.5, self._mark_compute)

        btn_pick = forms.Button()
        btn_pick.Text = "Assign Attr Pts"
        btn_pick.Click += self._on_pick_attractors
        btn_clr_attr = forms.Button()
        btn_clr_attr.Text = "Clear Pts"
        btn_clr_attr.Click += self._on_clear_attractors
        layout.AddRow(btn_pick, btn_clr_attr)

        self.lbl_attr_count = forms.Label()
        self.lbl_attr_count.Text = "Points: 0"
        layout.AddRow(self.lbl_attr_count)

        btn_pick_crv = forms.Button()
        btn_pick_crv.Text = "Assign Attr Curves"
        btn_pick_crv.Click += self._on_pick_attractor_curves
        btn_clr_crv = forms.Button()
        btn_clr_crv.Text = "Clear Curves"
        btn_clr_crv.Click += self._on_clear_attractor_curves
        layout.AddRow(btn_pick_crv, btn_clr_crv)

        self.lbl_attr_crv_count = forms.Label()
        self.lbl_attr_crv_count.Text = "Curves: 0"
        layout.AddRow(self.lbl_attr_crv_count)

        btn_pick_geo = forms.Button()
        btn_pick_geo.Text = "Assign Attr Geos"
        btn_pick_geo.Click += self._on_pick_attractor_geos
        btn_clr_geo = forms.Button()
        btn_clr_geo.Text = "Clear Geos"
        btn_clr_geo.Click += self._on_clear_attractor_geos
        layout.AddRow(btn_pick_geo, btn_clr_geo)

        self.lbl_attr_geo_count = forms.Label()
        self.lbl_attr_geo_count.Text = "Geometries: 0"
        layout.AddRow(self.lbl_attr_geo_count)

        # -- custom voxel geometry -----------------------------------------
        # Replace default box voxels with any mesh/brep shape. The shape is
        # normalised to unit size and replicated at each voxel position,
        # scaled by Custom Scale and the cell dimensions.
        layout.AddRow(self._bold("Custom Voxel Geometry"))

        btn_pick_custom = forms.Button()
        btn_pick_custom.Text = "Assign Custom Geo"
        btn_pick_custom.Click += self._on_pick_custom
        btn_clr_custom = forms.Button()
        btn_clr_custom.Text = "Clear Custom Geo"
        btn_clr_custom.Click += self._on_clear_custom
        layout.AddRow(btn_pick_custom, btn_clr_custom)

        self.lbl_custom = forms.Label()
        self.lbl_custom.Text = "Custom: None"
        layout.AddRow(self.lbl_custom)

        self.chk_use_custom = forms.CheckBox()
        self.chk_use_custom.Text = "Show Custom Voxels"
        self.chk_use_custom.Checked = False
        self.chk_use_custom.CheckedChanged += lambda s, e: self._mark_display()
        layout.AddRow(self.chk_use_custom)

        self.sld_custom_s, self.txt_custom_s = self._float_slider(
            layout, "Custom Scale", 0.1, 2.0, 1.0, self._mark_display)

        # -- edge boids ----------------------------------------------------
        # Agent-based pathfinding along exposed voxel edges. Agents walk the
        # surface graph choosing between straight and turning based on angle
        # thresholds and turn chance. Parameters control path count, length,
        # overlap behaviour, offset from surface, filleting, and pipe radius.
        layout.AddRow(self._bold("Edge Boids"))

        self.chk_boids = forms.CheckBox()
        self.chk_boids.Text = "Show Trails"
        self.chk_boids.Checked = False
        self.chk_boids.CheckedChanged += lambda s, e: self._toggle_trails()
        layout.AddRow(self.chk_boids)

        self.chk_diagonals = forms.CheckBox()
        self.chk_diagonals.Text = "Include Diagonal Edges (45\u00b0)"
        self.chk_diagonals.Checked = True
        layout.AddRow(self.chk_diagonals)

        noop = lambda: None
        self.sld_boid_count, self.txt_boid_count = self._int_slider(
            layout, "Agent Count", 1, 100, 20, noop)
        self.sld_boid_steps, self.txt_boid_steps = self._int_slider(
            layout, "Trail Steps", 10, 2000, 500, noop)
        self.sld_boid_turn, self.txt_boid_turn = self._float_slider(
            layout, "Turn Chance", 0.0, 1.0, 0.3, noop)
        self.sld_boid_straight, self.txt_boid_straight = self._float_slider(
            layout, "Straight Threshold", 0.0, 90.0, 5.0, noop)
        self.chk_boid_overlap = forms.CheckBox()
        self.chk_boid_overlap.Text = "Allow Path Overlap"
        self.chk_boid_overlap.Checked = False
        layout.AddRow(self.chk_boid_overlap)
        self.sld_boid_overlap, self.txt_boid_overlap = self._float_slider(
            layout, "Overlap Amount", 0.0, 1.0, 0.0, noop)
        self.sld_boid_min_a, self.txt_boid_min_a = self._float_slider(
            layout, "Min Turn Angle", 0.0, 180.0, 45.0, noop)
        self.sld_boid_max_a, self.txt_boid_max_a = self._float_slider(
            layout, "Max Turn Angle", 0.0, 180.0, 90.0, noop)
        self.sld_boid_thick, self.txt_boid_thick = self._int_slider(
            layout, "Trail Width", 1, 8, 2, noop)
        self.sld_pipe_rad, self.txt_pipe_rad = self._float_slider(
            layout, "Pipe Radius", 0.0, 5.0, 0.0, noop)
        self.sld_boid_offset, self.txt_boid_offset = self._float_slider(
            layout, "Offset Distance", 0.0, 10.0, 0.0, noop)
        self.sld_boid_tight, self.txt_boid_tight = self._int_slider(
            layout, "Offset Tightness", 0, 50, 10, noop)
        self.sld_boid_fillet, self.txt_boid_fillet = self._float_slider(
            layout, "Fillet Radius", 0.0, 10.0, 0.0, noop)

        layout.AddRow(self._bold("Boid Path Attractor"))

        btn_pick_battr = forms.Button()
        btn_pick_battr.Text = "Assign Boid Attr Curves"
        btn_pick_battr.Click += self._on_pick_boid_attractor
        btn_clr_battr = forms.Button()
        btn_clr_battr.Text = "Clear"
        btn_clr_battr.Click += self._on_clear_boid_attractor
        layout.AddRow(btn_pick_battr, btn_clr_battr)

        self.lbl_boid_attr = forms.Label()
        self.lbl_boid_attr.Text = "Boid Attractors: 0"
        layout.AddRow(self.lbl_boid_attr)

        self.sld_boid_attr_s, self.txt_boid_attr_s = self._float_slider(
            layout, "Boid Attr Strength", 0.0, 1.0, 0.5, noop)

        btn_run_boids = forms.Button()
        btn_run_boids.Text = "Run Boids"
        btn_run_boids.Click += self._on_run_boids
        btn_clr_trails = forms.Button()
        btn_clr_trails.Text = "Clear Trails"
        btn_clr_trails.Click += self._on_clear_trails
        btn_bake_trails = forms.Button()
        btn_bake_trails.Text = "Bake Trails"
        btn_bake_trails.Click += self._on_bake_trails
        btn_bake_trails_brep = forms.Button()
        btn_bake_trails_brep.Text = "Bake Trails Brep"
        btn_bake_trails_brep.Click += self._on_bake_trails_brep
        layout.AddRow(btn_run_boids, btn_clr_trails, btn_bake_trails)
        layout.AddRow(btn_bake_trails_brep)

        self.btn_trail_col = forms.Button()
        self.btn_trail_col.Text = "Trail Colour"
        self.btn_trail_col.BackgroundColor = drawing.Color.FromArgb(255, 120, 50)
        self.btn_trail_col.Click += self._on_pick_trail_color
        layout.AddRow(self.btn_trail_col)

        self.lbl_boid_status = forms.Label()
        self.lbl_boid_status.Text = "Boids: idle"
        layout.AddRow(self.lbl_boid_status)

        # -- melt / blend --------------------------------------------------
        # Combines voxel mesh + pipe mesh then applies Laplacian smoothing
        # to blend them into a single organic form. More iterations and higher
        # strength = more melted/rounded. Result replaces the preview until cleared.
        layout.AddRow(self._bold("Melt / Blend"))

        self.sld_melt_smooth, self.txt_melt_smooth = self._int_slider(
            layout, "Smooth Iterations", 0, 100, 10, noop)
        self.sld_melt_factor, self.txt_melt_factor = self._float_slider(
            layout, "Smooth Strength", 0.01, 1.0, 0.5, noop)

        btn_melt = forms.Button()
        btn_melt.Text = "Melt"
        btn_melt.Click += self._on_melt
        btn_clr_melt = forms.Button()
        btn_clr_melt.Text = "Clear Melt"
        btn_clr_melt.Click += self._on_clear_melt
        btn_bake_melt = forms.Button()
        btn_bake_melt.Text = "Bake Melt"
        btn_bake_melt.Click += self._on_bake_melt
        layout.AddRow(btn_melt, btn_clr_melt, btn_bake_melt)

        self.lbl_melt_status = forms.Label()
        self.lbl_melt_status.Text = "Melt: idle"
        layout.AddRow(self.lbl_melt_status)

        # -- display -------------------------------------------------------
        # Toggles for bounding box wireframe, voxel edge wireframe, and vertex
        # colour mode. Colour pickers for voxel faces, edges, and bounds.
        # Gradient bar previews the density-to-colour mapping.
        layout.AddRow(self._bold("Display"))
        self.chk_bounds = forms.CheckBox()
        self.chk_bounds.Text = "Show Bounding Box"
        self.chk_bounds.Checked = True
        self.chk_bounds.CheckedChanged += lambda s, e: self._mark_display()

        self.chk_edges = forms.CheckBox()
        self.chk_edges.Text = "Show Voxel Edges"
        self.chk_edges.Checked = True
        self.chk_edges.CheckedChanged += lambda s, e: self._mark_display()
        layout.AddRow(self.chk_bounds, self.chk_edges)

        self.chk_vcol = forms.CheckBox()
        self.chk_vcol.Text = "Vertex Colours"
        self.chk_vcol.Checked = True
        self.chk_vcol.CheckedChanged += lambda s, e: self._toggle_vertex_colors()
        layout.AddRow(self.chk_vcol)

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
        layout.AddRow(self.btn_vcol, self.btn_ecol, self.btn_bcol)

        lbl_low = forms.Label()
        lbl_low.Text = "Low"
        lbl_low.Width = 30
        self.gradient_bar = forms.Drawable()
        self.gradient_bar.Size = drawing.Size(200, 18)
        self.gradient_bar.Paint += self._on_gradient_paint
        lbl_high = forms.Label()
        lbl_high.Text = "High"
        lbl_high.Width = 30
        layout.AddRow(lbl_low, self.gradient_bar, lbl_high)

        lbl_grad_desc = forms.Label()
        lbl_grad_desc.Text = "Colour = noise density (threshold \u2192 max)"
        layout.AddRow(lbl_grad_desc)

        # -- controls ------------------------------------------------------
        # Refresh = full recompute of noise + mesh. Bake = add mesh to doc
        # with colours. Bake Brep = convert each voxel to a NURBS polysurface
        # with no colour. Clear = remove all preview geometry.
        layout.AddRow(self._bold("Controls"))

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
        layout.AddRow(btn_refresh, btn_bake, btn_bake_brep, btn_clear)

        self.lbl_status = forms.Label()
        self.lbl_status.Text = "Ready"
        layout.AddRow(self.lbl_status)

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
        cw = self._fval(self.txt_cw, self.sld_cw, 0.1, 50.0)
        cl = self._fval(self.txt_cl, self.sld_cl, 0.1, 50.0)
        ch = self._fval(self.txt_ch, self.sld_ch, 0.1, 50.0)
        scale = self._fval(self.txt_scale, self.sld_scale, 0.01, 1.0)
        thresh = self._fval(self.txt_thresh, self.sld_thresh, 0.0, 1.0)
        octaves = self._ival(self.txt_oct, self.sld_oct)
        seed = self._ival(self.txt_seed, self.sld_seed)
        hollow = self.chk_hollow.Checked == True
        shell = self._ival(self.txt_shell, self.sld_shell)
        use_attr = self.chk_attr.Checked == True
        attr_r = self._fval(self.txt_attr_r, self.sld_attr_r, 1.0, 50.0)
        attr_s = self._fval(self.txt_attr_s, self.sld_attr_s, 0.0, 1.0)
        use_base = self.chk_use_base.Checked == True
        base_r = self._fval(self.txt_base_r, self.sld_base_r, 1.0, 80.0)
        base_s = self._fval(self.txt_base_s, self.sld_base_s, 0.0, 1.0)
        base_carve = self.chk_carve.Checked == True
        return (gx, gy, gz, cw, cl, ch, scale, thresh, octaves, seed,
                hollow, shell, use_attr, attr_r, attr_s,
                use_base, base_r, base_s, base_carve)

    # -- compute grid origin -----------------------------------------------
    def _grid_origin(self, gx, gy, gz, cw, cl, ch):
        """Return the world-space corner of the grid. If auto-center is on and
        base geometry exists, centers the grid on the base's bounding box."""
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
        hollow, shell = p[10], p[11]
        use_attr, attr_r, attr_s = p[12], p[13], p[14]
        use_base, base_r, base_s, base_carve = p[15], p[16], p[17], p[18]

        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        total = gx * gy * gz
        self.lbl_status.Text = "Computing {} cells...".format(total)

        voxels = self.system.generate(
            gx, gy, gz, cw, cl, ch, scale, thresh, octaves, seed,
            use_attr, self.attractor_pts, self.attractor_curves,
            self.attractor_geos, attr_r, attr_s,
            hollow, shell,
            use_base, self.base_geometries, base_r, base_s, base_carve,
            origin)

        self.system.boid_trails = []
        self.system.boid_graph = {}
        self.system.conduit.trail_polylines = []

        show_bounds = self.chk_bounds.Checked == True
        show_edges = self.chk_edges.Checked == True
        use_custom = self.chk_use_custom.Checked == True
        custom_scale = self._fval(self.txt_custom_s, self.sld_custom_s, 0.1, 2.0)
        do_rot = self.chk_rotate.Checked == True
        rot_deg = self._fval(self.txt_rot_angle, self.sld_rot_angle, 0.0, 360.0)
        rot_rad = rot_deg * math.pi / 180.0
        rot_axis = self.dd_rot_axis.SelectedIndex
        do_rot2 = self.chk_rotate2.Checked == True
        rot_deg2 = self._fval(self.txt_rot_angle2, self.sld_rot_angle2, 0.0, 360.0)
        rot_rad2 = rot_deg2 * math.pi / 180.0
        rot_axis2 = self.dd_rot_axis2.SelectedIndex
        do_dscale = self.chk_dscale.Checked == True
        dscale_min = self._fval(self.txt_dscale_min, self.sld_dscale_min, 0.01, 1.0)
        self.system.update_display(
            voxels, cw, cl, ch, self.voxel_color,
            show_bounds, self.bounds_color,
            show_edges, self.edge_color,
            gx, gy, gz, origin,
            use_custom, custom_scale,
            do_rot, rot_rad, rot_axis,
            do_rot2, rot_rad2, rot_axis2,
            do_dscale, dscale_min)

        self.lbl_status.Text = "Showing {} / {} voxels".format(len(voxels), total)
        self.gradient_bar.Invalidate()

    # -- display-only refresh ----------------------------------------------
    def _display_only(self):
        """Rebuild mesh from existing voxel data without recomputing noise.
        Triggered by rotation, scale, colour, or display toggle changes."""
        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)
        voxels = self.system.voxels
        show_bounds = self.chk_bounds.Checked == True
        show_edges = self.chk_edges.Checked == True
        use_custom = self.chk_use_custom.Checked == True
        custom_scale = self._fval(self.txt_custom_s, self.sld_custom_s, 0.1, 2.0)
        do_rot = self.chk_rotate.Checked == True
        rot_deg = self._fval(self.txt_rot_angle, self.sld_rot_angle, 0.0, 360.0)
        rot_rad = rot_deg * math.pi / 180.0
        rot_axis = self.dd_rot_axis.SelectedIndex
        do_rot2 = self.chk_rotate2.Checked == True
        rot_deg2 = self._fval(self.txt_rot_angle2, self.sld_rot_angle2, 0.0, 360.0)
        rot_rad2 = rot_deg2 * math.pi / 180.0
        rot_axis2 = self.dd_rot_axis2.SelectedIndex
        do_dscale = self.chk_dscale.Checked == True
        dscale_min = self._fval(self.txt_dscale_min, self.sld_dscale_min, 0.01, 1.0)
        self.system.update_display(
            voxels, cw, cl, ch, self.voxel_color,
            show_bounds, self.bounds_color,
            show_edges, self.edge_color,
            gx, gy, gz, origin,
            use_custom, custom_scale,
            do_rot, rot_rad, rot_axis,
            do_rot2, rot_rad2, rot_axis2,
            do_dscale, dscale_min)
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
        self.system.conduit.trail_polylines = []
        self.system.conduit.pipe_mesh = None
        self.system.conduit.show_pipes = False
        self.system.conduit.melt_mesh = None
        self.system.conduit.show_melt = False
        self.system.voxels = []
        self.system.boid_trails = []
        self.system.boid_graph = {}
        sc.doc.Views.Redraw()
        self.lbl_status.Text = "Cleared"
        self.lbl_boid_status.Text = "Boids: idle"
        self.lbl_melt_status.Text = "Melt: idle"

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

    # -- edge boids --------------------------------------------------------
    def _toggle_trails(self):
        """Toggle trail polyline visibility in the conduit."""
        self.system.conduit.show_trails = self.chk_boids.Checked == True
        sc.doc.Views.Redraw()

    def _toggle_vertex_colors(self):
        """Switch between density-coloured and flat-shaded voxel rendering."""
        self.system.conduit.use_vertex_colors = self.chk_vcol.Checked == True
        sc.doc.Views.Redraw()

    def _on_pick_boid_attractor(self, sender, e):
        self.Visible = False
        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select attractor curves for boid paths")
        go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
        go.EnablePreSelect(False, True)
        go.GetMultiple(1, 0)
        if go.CommandResult() == Rhino.Commands.Result.Success:
            self.boid_attractor_curves = []
            for i in range(go.ObjectCount):
                geo = go.Object(i).Geometry()
                if geo:
                    self.boid_attractor_curves.append(geo.Duplicate())
            self.lbl_boid_attr.Text = "Boid Attractors: {}".format(
                len(self.boid_attractor_curves))
        self.Visible = True

    def _on_clear_boid_attractor(self, sender, e):
        self.boid_attractor_curves = []
        self.lbl_boid_attr.Text = "Boid Attractors: 0"

    def _on_run_boids(self, sender, e):
        """Build the edge graph and run boid simulation. Reads all boid params,
        generates trails, applies fillet and offset, builds pipe meshes if
        radius > 0, and updates the conduit display."""
        if not self.system.voxels:
            self.lbl_boid_status.Text = "Boids: no voxels"
            return

        p = self._read_params()
        gx, gy, gz = p[0], p[1], p[2]
        cw, cl, ch = p[3], p[4], p[5]
        seed = p[9]
        origin = self._grid_origin(gx, gy, gz, cw, cl, ch)

        diags = self.chk_diagonals.Checked == True
        count = self._ival(self.txt_boid_count, self.sld_boid_count)
        steps = self._ival(self.txt_boid_steps, self.sld_boid_steps)
        turn_c = self._fval(self.txt_boid_turn, self.sld_boid_turn, 0.0, 1.0)
        str_ang = self._fval(self.txt_boid_straight, self.sld_boid_straight, 0.0, 90.0)
        if self.chk_boid_overlap.Checked:
            ovlap = self._fval(self.txt_boid_overlap, self.sld_boid_overlap, 0.0, 1.0)
        else:
            ovlap = 0.0
        min_a = self._fval(self.txt_boid_min_a, self.sld_boid_min_a, 0.0, 180.0)
        max_a = self._fval(self.txt_boid_max_a, self.sld_boid_max_a, 0.0, 180.0)
        thick = self._ival(self.txt_boid_thick, self.sld_boid_thick)
        offset = self._fval(self.txt_boid_offset, self.sld_boid_offset, 0.0, 10.0)
        tightness = self._ival(self.txt_boid_tight, self.sld_boid_tight)
        fillet = self._fval(self.txt_boid_fillet, self.sld_boid_fillet, 0.0, 10.0)
        battr_s = self._fval(self.txt_boid_attr_s, self.sld_boid_attr_s, 0.0, 1.0)

        self.lbl_boid_status.Text = "Building graph..."
        self.system.build_edge_graph(self.system.voxels, diags)

        self.lbl_boid_status.Text = "Running {} boids...".format(count)
        self.system.run_edge_boids(count, steps, min_a, max_a, turn_c,
                                   seed, cw, cl, ch, origin, offset,
                                   tightness, str_ang, ovlap,
                                   self.boid_attractor_curves, battr_s)

        trails = self.system.boid_trails
        if fillet > 1e-6:
            trails = self.system.fillet_trails(trails, fillet)

        self.system.conduit.trail_polylines = trails
        self.system.conduit.trail_color = self.trail_color
        self.system.conduit.trail_thickness = thick
        self.system.conduit.show_trails = True
        self.chk_boids.Checked = True

        pipe_r = self._fval(self.txt_pipe_rad, self.sld_pipe_rad, 0.0, 5.0)
        if pipe_r > 1e-6 and trails:
            self.lbl_boid_status.Text = "Building pipes..."
            self.system.conduit.pipe_mesh = self.system.build_pipe_mesh(trails, pipe_r)
            self.system.conduit.pipe_material = rd.DisplayMaterial(self.trail_color)
            self.system.conduit.show_pipes = True
        else:
            self.system.conduit.pipe_mesh = None
            self.system.conduit.show_pipes = False

        sc.doc.Views.Redraw()

        total_segs = sum(pl.Count - 1 for pl in trails)
        self.lbl_boid_status.Text = "Boids: {} trails, {} segments".format(
            len(trails), total_segs)

    def _on_clear_trails(self, sender, e):
        self.system.boid_trails = []
        self.system.boid_graph = {}
        self.system.boid_vertex_normals = {}
        self.system.conduit.trail_polylines = []
        self.system.conduit.pipe_mesh = None
        self.system.conduit.show_pipes = False
        sc.doc.Views.Redraw()
        self.lbl_boid_status.Text = "Boids: cleared"

    def _on_bake_trails(self, sender, e):
        """Add trail polylines and pipe mesh (if present) to the document
        with the chosen trail colour."""
        if not self.system.boid_trails:
            return
        attr = Rhino.DocObjects.ObjectAttributes()
        attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
        attr.ObjectColor = self.trail_color
        for pl in self.system.boid_trails:
            if pl.Count > 1:
                sc.doc.Objects.AddPolyline(pl, attr)
        pm = self.system.conduit.pipe_mesh
        if pm and pm.Vertices.Count > 0:
            sc.doc.Objects.AddMesh(pm, attr)
        sc.doc.Views.Redraw()
        self.lbl_boid_status.Text = "Baked {} trails".format(
            len(self.system.boid_trails))

    def _on_bake_trails_brep(self, sender, e):
        """Convert pipe mesh to NURBS breps (one per pipe segment) or trails to
        NURBS curves, and add to document with no colour attributes."""
        has_trails = self.system.boid_trails and len(self.system.boid_trails) > 0
        has_pipes = (self.system.conduit.pipe_mesh and
                     self.system.conduit.pipe_mesh.Vertices.Count > 0)
        if not has_trails and not has_pipes:
            self.lbl_boid_status.Text = "No trails to bake"
            return
        self.lbl_boid_status.Text = "Converting to Brep..."
        try:
            count = 0
            tol = sc.doc.ModelAbsoluteTolerance
            _Pt3d = rg.Point3d
            _Corner = rg.Brep.CreateFromCornerPoints
            _Join = rg.Brep.JoinBreps
            if has_pipes:
                pm = self.system.conduit.pipe_mesh
                pieces = pm.SplitDisjointPieces()
                if not pieces or len(pieces) == 0:
                    pieces = [pm]
                for piece in pieces:
                    pverts = piece.Vertices
                    pfaces = piece.Faces
                    surfs = []
                    for fi in range(pfaces.Count):
                        f = pfaces[fi]
                        if f.IsQuad:
                            srf = _Corner(
                                _Pt3d(pverts[f.A]), _Pt3d(pverts[f.B]),
                                _Pt3d(pverts[f.C]), _Pt3d(pverts[f.D]), tol)
                        else:
                            srf = _Corner(
                                _Pt3d(pverts[f.A]), _Pt3d(pverts[f.B]),
                                _Pt3d(pverts[f.C]), tol)
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
            elif has_trails:
                for pl in self.system.boid_trails:
                    if pl.Count > 1:
                        crv = pl.ToNurbsCurve()
                        if crv:
                            sc.doc.Objects.AddCurve(crv)
                            count += 1
            sc.doc.Views.Redraw()
            self.lbl_boid_status.Text = "Baked {} brep(s)/curve(s)".format(count)
        except Exception as ex:
            self.lbl_boid_status.Text = "Brep failed: {}".format(str(ex))

    def _on_melt(self, sender, e):
        """Run the melt/blend operation and display the result."""
        iters = self._ival(self.txt_melt_smooth, self.sld_melt_smooth)
        factor = self._fval(self.txt_melt_factor, self.sld_melt_factor, 0.01, 1.0)
        self.lbl_melt_status.Text = "Melting..."
        result = self.system.melt(iters, factor)
        if result and result.Vertices.Count > 0:
            self.system.conduit.melt_mesh = result
            self.system.conduit.show_melt = True
            sc.doc.Views.Redraw()
            self.lbl_melt_status.Text = "Melt: {} vertices".format(
                result.Vertices.Count)
        else:
            self.lbl_melt_status.Text = "Melt: failed (no geometry)"

    def _on_clear_melt(self, sender, e):
        self.system.conduit.melt_mesh = None
        self.system.conduit.show_melt = False
        sc.doc.Views.Redraw()
        self.lbl_melt_status.Text = "Melt: cleared"

    def _on_bake_melt(self, sender, e):
        """Add the melted mesh to the Rhino document."""
        mm = self.system.conduit.melt_mesh
        if not mm or mm.Vertices.Count == 0:
            self.lbl_melt_status.Text = "Melt: nothing to bake"
            return
        attr = Rhino.DocObjects.ObjectAttributes()
        attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
        attr.ObjectColor = self.voxel_color
        sc.doc.Objects.AddMesh(mm, attr)
        sc.doc.Views.Redraw()
        self.lbl_melt_status.Text = "Melt: baked"

    def _on_pick_trail_color(self, sender, e):
        cd = forms.ColorDialog()
        cd.Color = drawing.Color.FromArgb(
            self.trail_color.R, self.trail_color.G, self.trail_color.B)
        if cd.ShowDialog(self) == forms.DialogResult.Ok:
            c = cd.Color
            self.trail_color = System.Drawing.Color.FromArgb(c.Rb, c.Gb, c.Bb)
            self.btn_trail_col.BackgroundColor = c
            self.system.conduit.trail_color = self.trail_color
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
