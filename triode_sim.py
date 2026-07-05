"""Interactive triode vacuum-tube simulation for Blender 5.x.

Build standalone:   blender -P triode_sim.py
Or from a console:  import triode_sim; triode_sim.build_all()

Open the "Triode" tab in the 3D-view sidebar (N key):
  Heater temp  -> thermionic emission rate, launch speed, heater/cathode glow
  Grid voltage -> retarding/accelerating field cathode->grid, wire focusing,
                  interception when positive (grid current)
  Plate voltage-> extraction field grid->plate
A mean-field space-charge term makes the cathode cloud saturate emission
(space-charge-limited vs emission-limited operation). Physics is pedagogical:
1-D radial fields + a local grid-wire term, exaggerated geometry, not TCAD.

The integrator is a frame_change_pre handler: press play (or the Run button)
and drag sliders live. It is stateful — scrubbing the timeline does not rewind
the electrons; use Reset instead.
"""
import math

import bpy
import bmesh
import numpy as np
from mathutils import Vector

# ------------- geometry (Blender units; gaps ~3x a real 6SN7 for visibility) -
PREFIX = "TRI_"
R_C = 0.15                    # cathode outer radius
R_G = 0.45                    # grid radius
R_P = 0.98                    # plate absorption radius (sleeve inradius 1.0)
PITCH = 0.115                 # grid helix pitch
N_TURNS = 19
WIRE_R = 0.012                # grid wire visual radius
GRID_HALF = N_TURNS * PITCH / 2.0
Z_HALF = 1.2                  # cathode half height = active region
PARK = (0.0, 0.0, -500.0)     # dead electrons live here, far off camera

# ------------- physics -------------------------------------------------------
POOL = 6000                   # electron pool size
MU = 20.0                     # amplification factor: cutoff at Vg = -Vp/MU
C1 = 0.5                      # accel per volt, cathode->grid  [u/s^2/V]
C2 = 0.04                     # accel per volt, grid->plate    [u/s^2/V]
V_SC = 1.5                    # space-charge depression at full cloud [V]
CLOUD_R = 0.32                # r below this counts as "cloud"
CLOUD_CAP = 2000.0
K_W = 0.002                   # grid-wire local force scale
EPS = 0.02                    # wire force softening
BAND = 0.10                   # wire force active band around R_G
WIRE_ABS = 0.015              # absorb radius at wires when grid positive
E0 = 150.0                    # electrons/frame emitted at T_REF
E_CLAMP = 400.0
T_REF = 1100.0
T_SLOPE = 13000.0             # Richardson-ish exponent scale [K]
DT = 1.0 / 24.0
SUBSTEPS = 4
GAMMA = 1.5                   # drag [1/s]
V_MAX = 6.0                   # speed cap [u/s]
IP_ALPHA = 0.15               # Ip meter smoothing
MA_PER_E = 0.2                # meter scale: mA per electron/frame

_S = {}                       # sim state; (re)filled by reset_electrons()


# ------------- small helpers -------------------------------------------------
def _scene():
    return bpy.data.scenes[0]


def _ob(name):
    return bpy.data.objects.get(PREFIX + name)


def _link(ob):
    _scene().collection.objects.link(ob)
    return ob


def _mesh_obj(name, bm):
    me = bpy.data.meshes.new(PREFIX + name)
    bm.to_mesh(me)
    bm.free()
    return _link(bpy.data.objects.new(PREFIX + name, me))


def _pydata_obj(name, verts, faces):
    me = bpy.data.meshes.new(PREFIX + name)
    me.from_pydata(verts, [], faces)
    me.update()
    return _link(bpy.data.objects.new(PREFIX + name, me))


def _cyl(name, r, depth, loc=(0, 0, 0), segs=48, smooth=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segs,
                          radius1=r, radius2=r, depth=depth)
    ob = _mesh_obj(name, bm)
    ob.location = loc
    if smooth:
        ob.data.polygons.foreach_set("use_smooth", [True] * len(ob.data.polygons))
    return ob


def _poly_curve(name, pts, bevel):
    cu = bpy.data.curves.new(PREFIX + name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = bevel
    cu.bevel_resolution = 4
    cu.use_fill_caps = True
    sp = cu.splines.new('POLY')
    sp.points.add(len(pts) - 1)
    for p, (x, y, z) in zip(sp.points, pts):
        p.co = (x, y, z, 1.0)
    return _link(bpy.data.objects.new(PREFIX + name, cu))


def _look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


# ------------- scene build ---------------------------------------------------
def wipe_scene():
    """Targeted wipe. Never read_factory_settings(): it would kill the MCP addon."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                 bpy.data.lights, bpy.data.cameras):
        for block in [b for b in coll if b.users == 0]:
            coll.remove(block)


def build_geometry():
    # --- cathode sleeve
    _cyl("Cathode", R_C, 2 * Z_HALF)

    # --- heater hairpin inside the cathode, tips poking out the top
    pts = [(0.05, 0.0, 1.34)]
    pts += [(0.05, 0.0, -1.02)]
    pts += [(0.05 * math.cos(a), 0.0, -1.02 - 0.05 * math.sin(a))
            for a in (math.pi * i / 6 for i in range(1, 6))]
    pts += [(-0.05, 0.0, -1.02), (-0.05, 0.0, 1.34)]
    _poly_curve("Heater", pts, 0.016)

    # --- grid helix + two support rods (like the 6SN7 photo)
    spt = 24  # samples per turn
    n = N_TURNS * spt
    pts = [(R_G * math.cos(2 * math.pi * i / spt),
            R_G * math.sin(2 * math.pi * i / spt),
            -GRID_HALF + PITCH * i / spt) for i in range(n + 1)]
    _poly_curve("Grid", pts, WIRE_R)
    _cyl("GridRodA", 0.028, 2.72, loc=(R_G, 0, 0.03), segs=16)
    _cyl("GridRodB", 0.028, 2.72, loc=(-R_G, 0, 0.03), segs=16)

    # --- plate: superellipse sleeve (rounded square, inradius 1.0) with a
    #     cutaway window on the -Y face so the inside is visible
    nz, na = 27, 96
    zs = np.linspace(-1.3, 1.3, nz)
    angs = [2 * math.pi * i / na for i in range(na)]

    def srad(th):
        c, s = abs(math.cos(th)), abs(math.sin(th))
        return (c ** 4 + s ** 4) ** -0.25

    verts = [(srad(a) * math.cos(a), srad(a) * math.sin(a), z)
             for z in zs for a in angs]
    faces = []
    for iz in range(nz - 1):
        zmid = 0.5 * (zs[iz] + zs[iz + 1])
        for ia in range(na):
            ja = (ia + 1) % na
            amid = angs[ia] + math.pi / na
            w = ((amid + math.pi) % (2 * math.pi)) - math.pi  # -> (-pi, pi]
            if abs(w + math.pi / 2) < math.pi / 5 and abs(zmid) < 0.92:
                continue  # the cutaway window
            faces.append((iz * na + ia, iz * na + ja,
                          (iz + 1) * na + ja, (iz + 1) * na + ia))
    plate = _pydata_obj("Plate", verts, faces)
    plate.data.polygons.foreach_set("use_smooth", [True] * len(plate.data.polygons))
    sol = plate.modifiers.new("Sol", 'SOLIDIFY')
    sol.thickness = 0.025

    # --- mica spacer rings top/bottom (annulus so the top view sees inside)
    def ring(name, z):
        segs, r0, r1 = 48, 0.50, 1.33
        vs = [(r0 * math.cos(2 * math.pi * i / segs),
               r0 * math.sin(2 * math.pi * i / segs), z) for i in range(segs)]
        vs += [(r1 * math.cos(2 * math.pi * i / segs),
                r1 * math.sin(2 * math.pi * i / segs), z) for i in range(segs)]
        fs = [(i, (i + 1) % segs, segs + (i + 1) % segs, segs + i)
              for i in range(segs)]
        _pydata_obj(name, vs, fs)

    ring("MicaTop", 1.34)
    ring("MicaBottom", -1.34)

    # --- glass envelope (lathe profile, dome top)
    prof = [(0.28, -1.78), (1.50, -1.62), (1.62, -0.80), (1.62, 1.60)]
    prof += [(1.62 * math.cos(a), 1.60 + 0.75 * math.sin(a))
             for a in (math.pi / 2 * i / 7 for i in range(1, 8))]
    bm = bmesh.new()
    prev = None
    for r, z in prof:
        v = bm.verts.new((r, 0.0, z))
        if prev is not None:
            bm.edges.new((prev, v))
        prev = v
    bmesh.ops.spin(bm, geom=bm.verts[:] + bm.edges[:], cent=(0, 0, 0),
                   axis=(0, 0, 1), angle=2 * math.pi, steps=48, use_merge=True)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    glass = _mesh_obj("Glass", bm)
    glass.data.polygons.foreach_set("use_smooth", [True] * len(glass.data.polygons))

    # --- base + pins
    _cyl("Base", 1.70, 0.50, loc=(0, 0, -2.03))
    for i in range(8):
        a = 2 * math.pi * (i + 0.5) / 8
        _cyl(f"Pin{i}", 0.055, 0.55,
             loc=(1.1 * math.cos(a), 1.1 * math.sin(a), -2.53), segs=12)
    _cyl("Key", 0.16, 0.60, loc=(0, 0, -2.55), segs=16)

    # --- electron pool: verts instanced with a small emissive sphere
    me = bpy.data.meshes.new(PREFIX + "ElectronsMesh")
    me.from_pydata([PARK] * POOL, [], [])
    me.update()
    eob = _link(bpy.data.objects.new(PREFIX + "Electrons", me))
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.009)
    sph = _mesh_obj("Electron", bm)
    sph.parent = eob
    eob.instance_type = 'VERTS'


# ------------- materials / look ----------------------------------------------
def _principled(name, color, metallic=0.0, rough=0.5, alpha=1.0, blended=False,
                spec=None):
    m = bpy.data.materials.get(PREFIX + name)
    if m is None:
        m = bpy.data.materials.new(PREFIX + name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Alpha"].default_value = alpha
    if spec is not None:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if blended:
        m.surface_render_method = 'BLENDED'
    return m


def _emission(name, color, strength):
    m = bpy.data.materials.get(PREFIX + name)
    if m is None:
        m = bpy.data.materials.new(PREFIX + name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1.0)
    em.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def _assign(obname, mat):
    ob = _ob(obname)
    if ob is None:
        return
    if ob.data.materials:
        ob.data.materials[0] = mat
    else:
        ob.data.materials.append(mat)


def _light(name, loc, energy, size, color=(1.0, 1.0, 1.0), kind='AREA',
           shadow=True):
    ob = _ob(name)
    if ob is None:
        ld = bpy.data.lights.new(PREFIX + name, kind)
        ob = _link(bpy.data.objects.new(PREFIX + name, ld))
    ob.data.energy = energy
    if kind == 'AREA':
        ob.data.size = size
    else:
        ob.data.shadow_soft_size = size
    ob.data.color = color
    if hasattr(ob.data, "use_shadow"):
        ob.data.use_shadow = shadow
    ob.location = loc
    _look_at(ob, (0, 0, 0))
    return ob


def _glow(T):
    """Thermal glow ramp for 300..1300 K (deep red -> orange)."""
    x = max(0.0, (T - 600.0) / 700.0)
    color = (1.0, 0.15 + 0.35 * x, 0.02 + 0.12 * x)
    return color, x


def _apply_heat(scene=None):
    sc = scene or _scene()
    T = getattr(sc, "tri_heater_t", T_REF)
    color, x = _glow(T)
    hm = bpy.data.materials.get(PREFIX + "MatHeater")
    if hm:
        em = hm.node_tree.nodes.get("Emission")
        if em:
            em.inputs["Color"].default_value = (*color, 1.0)
            em.inputs["Strength"].default_value = 16.0 * x ** 3
    cm = bpy.data.materials.get(PREFIX + "MatCathode")
    if cm:
        bsdf = cm.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
            bsdf.inputs["Emission Strength"].default_value = 2.5 * x ** 3
    cl = _ob("Cath_Light")  # hot cathode illuminates the plate interior
    if cl:
        cl.data.color = color
        cl.data.energy = 9.0 * x ** 3


def build_materials():
    _assign("Cathode", _principled("MatCathode", (0.75, 0.73, 0.68), rough=0.65))
    _assign("Heater", _emission("MatHeater", (1.0, 0.5, 0.2), 6.0))
    copper = _principled("MatCopper", (0.72, 0.43, 0.28), metallic=1.0, rough=0.32)
    for nm in ("Grid", "GridRodA", "GridRodB"):
        _assign(nm, copper)
    _assign("Plate", _principled("MatPlate", (0.055, 0.055, 0.062),
                                 metallic=0.35, rough=0.68))
    mica = _principled("MatMica", (0.82, 0.77, 0.62), rough=0.55,
                       alpha=0.45, blended=True)
    _assign("MicaTop", mica)
    _assign("MicaBottom", mica)
    glass = _principled("MatGlass", (0.9, 0.95, 1.0), rough=0.12,
                        alpha=0.055, blended=True, spec=0.15)
    _assign("Glass", glass)
    for m in (glass, mica):  # don't let see-through parts black out the inside
        if hasattr(m, "use_transparent_shadow"):
            m.use_transparent_shadow = True
    dark = _principled("MatBase", (0.03, 0.025, 0.022), rough=0.6)
    _assign("Base", dark)
    _assign("Key", dark)
    nickel = _principled("MatPin", (0.6, 0.6, 0.62), metallic=1.0, rough=0.35)
    for i in range(8):
        _assign(f"Pin{i}", nickel)
    _assign("Electron", _emission("MatElectron", (0.35, 0.85, 1.0), 9.0))

    # world + lights: near-black background, dim fill so a COLD tube still reads
    w = bpy.data.worlds[0] if bpy.data.worlds else bpy.data.worlds.new("World")
    _scene().world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.004, 0.005, 0.008, 1.0)
        bg.inputs["Strength"].default_value = 1.0
    _light("Key_Light", (-3.2, -4.2, 3.2), energy=80.0, size=2.5)
    _light("Rim_Light", (2.5, 3.2, 1.2), energy=40.0, size=3.0,
           color=(1.0, 0.85, 0.7))
    # shadow off: the light sits inside the cathode sleeve, which would
    # otherwise trap it; unshadowed it fakes the sleeve's own glow
    _light("Cath_Light", (0.0, 0.0, 0.3), energy=3.0, size=0.14, kind='POINT',
           shadow=False)

    sc = _scene()
    sc.render.engine = 'BLENDER_EEVEE'
    if hasattr(sc.eevee, "use_raytracing"):
        sc.eevee.use_raytracing = False  # perf: 6k emissive instances
    sc.render.fps = 24
    sc.frame_start = 1
    sc.frame_end = 1048574
    sc.render.resolution_x = 1440
    sc.render.resolution_y = 1080
    sc.sync_mode = 'FRAME_DROP'  # keep sim speed ~real-time on fast machines
    _setup_viewports()
    _apply_heat()


def _setup_viewports():
    for w in bpy.data.window_managers[0].windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                sp = a.spaces.active
                sp.shading.type = 'RENDERED'
                sp.overlay.show_overlays = False
                sp.clip_start = 0.005
                sp.clip_end = 300.0


# ------------- physics engine ------------------------------------------------
def reset_electrons():
    _S["pos"] = np.zeros((POOL, 3))
    _S["vel"] = np.zeros((POOL, 3))
    _S["alive"] = np.zeros(POOL, bool)
    _S["draw"] = np.empty((POOL, 3), np.float32)
    _S["draw"][:] = PARK
    _S["rng"] = np.random.default_rng(0)
    _S["ip"] = 0.0
    _S["cloud"] = 0
    _S["grid_hits"] = 0
    _S["fails"] = 0
    _S["last_txt"] = ""
    _push_draw()


def _push_draw():
    ob = _ob("Electrons")
    if ob is None:
        return
    me = ob.data
    me.vertices.foreach_set("co", _S["draw"].ravel())
    me.update()
    me.update_tag()


def _step(scene):
    S = _S
    if "pos" not in S:
        reset_electrons()
    rng = S["rng"]
    p, v, al = S["pos"], S["vel"], S["alive"]
    Vg = scene.tri_grid_v
    Vp = scene.tri_plate_v
    T = scene.tri_heater_t

    r_all = np.hypot(p[:, 0], p[:, 1])
    cloud = int(np.count_nonzero(al & (r_all < CLOUD_R)))
    if cloud > CLOUD_CAP and S["ip"] + S.get("ig2", 0.0) < 1.0:
        # TRUE space-charge lockup: cloud at cap with zero throughput means
        # emission stays gated (lam *= 1-cf) and the trapped electrons can
        # never drain past the grid-wire barrier -- the tube latches dead.
        # Reclaim them into the cathode to break the latch. A full cloud
        # WITH current flowing is normal space-charge-limited operation and
        # is deliberately left alone.
        idx = np.flatnonzero(al & (r_all < CLOUD_R))
        al[idx[:int(cloud - CLOUD_CAP) + 25]] = False
        cloud = int(CLOUD_CAP)
    cf = min(cloud / CLOUD_CAP, 1.2)

    # --- thermionic emission, throttled by space charge
    lam = min(E0 * math.exp(-T_SLOPE * (1.0 / T - 1.0 / T_REF)), E_CLAMP)
    lam *= max(0.0, 1.0 - cf)
    k = int(rng.poisson(lam)) if lam > 1e-6 else 0
    dead = np.flatnonzero(~al)
    k = min(k, dead.size)
    if k:
        idx = dead[:k]
        th = rng.uniform(0, 2 * np.pi, k)
        ct, st = np.cos(th), np.sin(th)
        rr = R_C + 0.006
        p[idx, 0] = rr * ct
        p[idx, 1] = rr * st
        p[idx, 2] = rng.uniform(-1.0, 1.0, k)
        vr = 0.2 * math.sqrt(T / T_REF) + np.abs(rng.normal(0, 0.06, k))
        vt = rng.normal(0, 0.06, k)
        v[idx, 0] = vr * ct - vt * st
        v[idx, 1] = vr * st + vt * ct
        v[idx, 2] = rng.normal(0, 0.06, k)
        al[idx] = True

    # --- integrate
    hits = 0
    grid_hits = 0
    h = DT / SUBSTEPS
    a1 = C1 * (Vg + Vp / MU - V_SC * cf)   # cathode->grid effective field
    a2 = C2 * (Vp - Vg)                    # grid->plate field
    for _ in range(SUBSTEPS):
        ii = np.flatnonzero(al)
        if ii.size == 0:
            break
        x, y, z = p[ii, 0], p[ii, 1], p[ii, 2]
        r = np.maximum(np.hypot(x, y), 1e-6)
        ux, uy = x / r, y / r
        ar = np.where(r < R_G, a1, a2)
        az = np.zeros_like(ar)
        if abs(Vg) > 1e-3:
            dr = r - R_G
            band = np.abs(dr) < BAND
            if band.any():
                dz = ((z[band] + PITCH / 2) % PITCH) - PITCH / 2
                d2 = dr[band] ** 2 + dz ** 2 + EPS * EPS
                d = np.sqrt(d2)
                f = K_W * (-Vg) / d2   # repels when Vg<0 (gap focusing)
                ar[band] += f * dr[band] / d
                az[band] += f * dz / d
        vx = v[ii, 0] + ar * ux * h
        vy = v[ii, 1] + ar * uy * h
        vz = v[ii, 2] + az * h
        damp = 1.0 - GAMMA * h
        vx *= damp
        vy *= damp
        vz *= damp
        sp = np.sqrt(vx * vx + vy * vy + vz * vz)
        fcl = np.minimum(1.0, V_MAX / np.maximum(sp, 1e-9))
        vx *= fcl
        vy *= fcl
        vz *= fcl
        nx, ny, nz2 = x + vx * h, y + vy * h, z + vz * h
        v[ii, 0], v[ii, 1], v[ii, 2] = vx, vy, vz
        p[ii, 0], p[ii, 1], p[ii, 2] = nx, ny, nz2

        nr = np.hypot(nx, ny)
        on_plate = nr >= R_P
        hits += int(np.count_nonzero(on_plate))
        reab = (nr <= R_C + 0.002) & (nx * vx + ny * vy < 0)
        zout = np.abs(nz2) > Z_HALF
        kill = on_plate | reab | zout
        if Vg > 0:  # grid interception -> grid current
            dzw = ((nz2 + PITCH / 2) % PITCH) - PITCH / 2
            wd2 = (nr - R_G) ** 2 + dzw ** 2
            on_wire = wd2 < WIRE_ABS ** 2
            grid_hits += int(np.count_nonzero(on_wire & ~kill))
            kill |= on_wire
        al[ii[kill]] = False

    S["ip"] = (1.0 - IP_ALPHA) * S["ip"] + IP_ALPHA * hits
    S["cloud"] = cloud
    S["grid_hits"] = grid_hits

    # --- draw + meter
    S["draw"][:] = PARK
    aidx = np.flatnonzero(al)
    if aidx.size:
        S["draw"][aidx] = p[aidx].astype(np.float32)
    _push_draw()
    txt = f"Ip = {S['ip'] * MA_PER_E:.1f} mA"
    if txt != S["last_txt"]:
        mo = _ob("Meter")
        if mo:
            mo.data.body = txt
        S["last_txt"] = txt
    if scene.frame_current % 4 == 0:
        for w in bpy.data.window_managers[0].windows:
            for a in w.screen.areas:
                if a.type == 'VIEW_3D':
                    a.tag_redraw()


def tri_frame_change(scene, depsgraph=None):
    try:
        _step(scene)
        _S["fails"] = 0
    except Exception:
        import traceback
        traceback.print_exc()
        _S["fails"] = _S.get("fails", 0) + 1
        if _S["fails"] > 5:
            _remove_handlers()
            print("triode_sim: handler removed after repeated errors")


def _remove_handlers():
    for hnd in list(bpy.app.handlers.frame_change_pre):
        if getattr(hnd, "__name__", "").startswith("tri_"):
            bpy.app.handlers.frame_change_pre.remove(hnd)


def register_sim():
    _remove_handlers()
    bpy.app.handlers.frame_change_pre.append(tri_frame_change)
    if "pos" not in _S:
        reset_electrons()


# ------------- UI ------------------------------------------------------------
def _upd_heat(self, context):
    _apply_heat(self)


def _upd_glass(self, context):
    g = _ob("Glass")
    if g:
        g.hide_viewport = not self.tri_show_glass
        g.hide_render = g.hide_viewport


class TRIODE_OT_reset(bpy.types.Operator):
    bl_idname = "triode.reset"
    bl_label = "Reset"
    bl_description = "Clear all electrons and restart the meter"

    def execute(self, context):
        reset_electrons()
        return {'FINISHED'}


class TRIODE_OT_play(bpy.types.Operator):
    bl_idname = "triode.play"
    bl_label = "Run / Pause"
    bl_description = "Toggle the simulation (animation playback)"

    def execute(self, context):
        bpy.ops.screen.animation_play()
        return {'FINISHED'}


class TRIODE_OT_view(bpy.types.Operator):
    bl_idname = "triode.view"
    bl_label = "View"
    bl_description = "Jump to a preset camera"
    which: bpy.props.StringProperty(default="OVER")

    def execute(self, context):
        set_view(self.which)
        return {'FINISHED'}


class TRIODE_PT_main(bpy.types.Panel):
    bl_label = "Triode"
    bl_idname = "TRIODE_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Triode"

    def draw(self, context):
        s = context.scene
        L = self.layout
        col = L.column(align=True)
        col.prop(s, "tri_heater_t", slider=True)
        col.prop(s, "tri_grid_v", slider=True)
        col.prop(s, "tri_plate_v", slider=True)
        row = L.row(align=True)
        row.operator("triode.play", icon='PLAY')
        row.operator("triode.reset", icon='FILE_REFRESH')
        row = L.row(align=True)
        for label, key in (("Top", "TOP"), ("Inside", "INSIDE"), ("Overview", "OVER")):
            row.operator("triode.view", text=label).which = key
        L.prop(s, "tri_show_glass")
        box = L.box()
        box.label(text=f"Plate current: {_S.get('ip', 0.0) * MA_PER_E:.1f} mA")
        box.label(text=f"Space-charge cloud: {_S.get('cloud', 0)} e-")
        if _S.get("grid_hits", 0):
            box.label(text=f"Grid interception: {_S['grid_hits']} e-/frame")


def _cam(name, loc, target=None, lens=50.0, clip=0.01, ortho=None):
    ob = _ob(name)
    if ob is None:
        cd = bpy.data.cameras.new(PREFIX + name)
        ob = _link(bpy.data.objects.new(PREFIX + name, cd))
    cd = ob.data
    if ortho is not None:
        cd.type = 'ORTHO'
        cd.ortho_scale = ortho
    else:
        cd.type = 'PERSP'
        cd.lens = lens
    cd.clip_start = clip
    cd.clip_end = 200.0
    cd.passepartout_alpha = 1.0
    ob.location = loc
    if target is not None:
        _look_at(ob, target)
    return ob


def set_view(which):
    names = {"TOP": "Cam_Top", "INSIDE": "Cam_Inside", "OVER": "Cam_Over"}
    ob = _ob(names.get(which, "Cam_Over"))
    if ob is None:
        return
    _scene().camera = ob
    for w in bpy.data.window_managers[0].windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                r3d = a.spaces.active.region_3d
                r3d.view_perspective = 'CAMERA'
                r3d.view_camera_zoom = 28.0  # frame fills the viewport
                r3d.view_camera_offset = (0.0, 0.0)


def register_ui():
    Sc = bpy.types.Scene
    for name in ("tri_heater_t", "tri_grid_v", "tri_plate_v", "tri_show_glass"):
        if hasattr(Sc, name):
            try:
                delattr(Sc, name)
            except Exception:
                pass
    Sc.tri_heater_t = bpy.props.FloatProperty(
        name="Heater temp (K)", min=300.0, max=1300.0, default=1100.0,
        step=100, precision=0, update=_upd_heat,
        description="Cathode temperature: sets thermionic emission (cloud density)")
    Sc.tri_grid_v = bpy.props.FloatProperty(
        name="Grid voltage (V)", min=-20.0, max=10.0, default=0.0,
        step=10, precision=1,
        description="Negative: repels electrons back toward the cathode (cutoff)")
    Sc.tri_plate_v = bpy.props.FloatProperty(
        name="Plate voltage (V)", min=0.0, max=300.0, default=150.0,
        step=100, precision=0,
        description="Positive: pulls electrons through the grid to the plate")
    Sc.tri_show_glass = bpy.props.BoolProperty(
        name="Show glass envelope", default=True, update=_upd_glass)

    for cls_name in ("TRIODE_OT_reset", "TRIODE_OT_play",
                     "TRIODE_OT_view", "TRIODE_PT_main"):
        old = getattr(bpy.types, cls_name, None)
        if old is not None:
            try:
                bpy.utils.unregister_class(old)
            except Exception:
                pass
    for cls in (TRIODE_OT_reset, TRIODE_OT_play, TRIODE_OT_view, TRIODE_PT_main):
        bpy.utils.register_class(cls)

    # top camera sits INSIDE the envelope just below the top mica, so the
    # view is a clean electrode cross-section instead of staring at the spacer
    _cam("Cam_Top", (0, 0, 1.30), ortho=2.7, clip=0.003)
    _cam("Cam_Inside", (0.52, 0.52, 0.05), target=(-0.1, -0.1, 0.0),
         lens=13.0, clip=0.004)
    _cam("Cam_Over", (4.0, -4.2, 2.6), target=(0, 0, -0.15), lens=31.0)
    _scene().camera = _ob("Cam_Over")

    if not _ob("Meter"):
        fc = bpy.data.curves.new(PREFIX + "Meter", 'FONT')
        fc.body = "Ip = 0.0 mA"
        fc.size = 0.30
        fc.align_x = 'CENTER'
        mo = _link(bpy.data.objects.new(PREFIX + "Meter", fc))
        mo.location = (0.0, -1.78, -1.60)
        mo.rotation_euler = (math.radians(90), 0, 0)
        mo.data.materials.append(_emission("MatMeter", (0.3, 1.0, 0.5), 3.0))

    _apply_heat()


# ------------- entry points --------------------------------------------------
def build_all():
    wipe_scene()
    build_geometry()
    build_materials()
    register_ui()
    register_sim()
    reset_electrons()
    set_view("OVER")


def selfcheck(frames=48):
    """Smallest runnable check: three operating points must behave like a triode."""
    sc = _scene()

    def run(T, Vg, Vp):
        sc.tri_heater_t, sc.tri_grid_v, sc.tri_plate_v = T, Vg, Vp
        reset_electrons()
        for _ in range(frames):
            _step(sc)
        return _S["ip"] * MA_PER_E, int(np.count_nonzero(_S["alive"]))

    ip, alive = run(500, 0, 250)
    assert alive < 20 and ip < 0.5, f"cold cathode leaks: Ip={ip:.2f} alive={alive}"
    ip, alive = run(1100, -12, 150)
    assert ip < 1.0, f"cutoff leaks: Ip={ip:.2f}"
    assert alive > 300, f"no space-charge cloud at cutoff: alive={alive}"
    ip_hi, _ = run(1100, 0, 250)
    assert ip_hi > 4.0, f"no conduction: Ip={ip_hi:.2f}"
    ip_lo, _ = run(1100, 0, 60)
    assert ip_lo < ip_hi, f"Ip not increasing with Vp: {ip_lo:.2f} !< {ip_hi:.2f}"
    print(f"selfcheck OK  (Ip @Vp=250: {ip_hi:.1f} mA, @Vp=60: {ip_lo:.1f} mA)")
    return True


if __name__ == "__main__":
    # Fresh scene (blender -P triode_sim.py): full build.
    # Run Script inside a saved .blend: just re-register handler/UI.
    if _ob("Cathode") is None:
        build_all()
    else:
        register_ui()
        register_sim()
        reset_electrons()
