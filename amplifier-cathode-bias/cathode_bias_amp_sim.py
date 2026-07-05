"""Interactive triode CATHODE-BIASED amplifier for Blender 5.x.

Build standalone:   blender -P cathode_bias_amp_sim.py
Or from a console:  import cathode_bias_amp_sim; cathode_bias_amp_sim.build_all()

The 6SN7 common-cathode stage with SELF-BIAS: no fixed grid bias anywhere --
the tube finds its own operating point.

    B+ (150-500 V) --[ plate resistor R_L 20k-500k ]--> plate
    sine generator (amplitude + DC offset, default 0) --> grid
    cathode --[ CATHODE RESISTOR R_k 0.1k-10k ]--> common (ground)
              (with a bypass-capacitor checkbox)

Plate current through R_k lifts the cathode; the grid (returned to ground
through the generator) then sits NEGATIVE of the cathode by Vk = Ip*Rk:
the bias sets itself, and fights back if you try to move it. The scope's
green trace shows Vgk (grid-to-cathode) -- watch it settle below zero with
the generator's DC offset at 0. Uncheck "Cathode bypass capacitor" and the
un-bypassed Rk applies negative feedback: gain drops.

Solved per frame by bisection on Ip against a live-calibrated perveance
model (no measured-current servo loops -- they ring against the electron
transit delay). Meters are KVL-true.

Open the "Cathode-Bias Amp" tab (N key), Run / Pause, drag sliders live.
Stateful sim: use Reset, don't scrub the timeline.
"""
import math

import bpy
import bmesh
import numpy as np
from mathutils import Vector

# ------------- geometry (Blender units; gaps ~3x a real 6SN7 for visibility) -
PREFIX = "CBAMP_"
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
MA_PER_E = 0.02               # mA per electron/frame — real-tube range so V = I*R works

# ------------- circuit -------------------------------------------------------
FREQ = 0.25                   # generator frequency [Hz]; fixed for now
IP_LOOP_ALPHA = 0.05          # smoothed tube current, feeds the calibration
K_ALPHA = 0.03                # perveance calibration EMA - slow enough to stay
                              # out of the signal band (no servo dynamics)
VP_SMOOTH = 0.5               # light smoothing of the solved plate voltage
SCOPE_N = 192                 # scope buffer length (2 cycles at 0.25 Hz, 24 fps)
SCOPE_XS = np.linspace(-1.28, 1.28, SCOPE_N)   # trace x coords (scope-local)

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

    _build_scope()
    _build_bench()


# ------------- bench: scope, supply, resistor, generator, wires ---------------
def _box(name, scale, loc, mat=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    ob = _mesh_obj(name, bm)
    ob.scale = scale
    ob.location = loc
    if mat is not None:
        ob.data.materials.append(mat)
    return ob


def _text(name, body, size, loc, rot, mat, align='LEFT', parent=None):
    ob = _ob(name)
    if ob is None:
        fc = bpy.data.curves.new(PREFIX + name, 'FONT')
        ob = _link(bpy.data.objects.new(PREFIX + name, fc))
    ob.data.body = body
    ob.data.size = size
    ob.data.align_x = align
    ob.location = loc
    ob.rotation_euler = rot
    if not ob.data.materials:
        ob.data.materials.append(mat)
    if parent is not None:
        ob.parent = parent
    return ob


def _build_scope():
    root = _ob("ScopeRoot")
    if root is None:
        root = _link(bpy.data.objects.new(PREFIX + "ScopeRoot", None))
    root.location = (-3.9, 0.9, 1.15)
    root.rotation_euler = (0.0, 0.0, math.radians(48.0))  # face the bench camera

    body = _box("ScopeBody", (3.05, 0.24, 4.40), (0, 0.14, 0),
                _principled("MatScopeBody", (0.10, 0.10, 0.11), rough=0.55))
    body.parent = root
    screen = _pydata_obj("ScopeScreen",
                         [(-1.4, 0, -2.1), (1.4, 0, -2.1),
                          (1.4, 0, 2.1), (-1.4, 0, 2.1)],
                         [(0, 1, 2, 3)])
    screen.parent = root
    screen.data.materials.append(
        _principled("MatScreen", (0.008, 0.02, 0.012), rough=0.4))

    # graticule: 10 rows. Top 5 = input, -20..+5 V at 5 V/div; bottom 5 =
    # output, auto-ranged 0-300 or 0-500 V (see _push_traces/_upd_bplus).
    cu = bpy.data.curves.new(PREFIX + "Graticule", 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = 0.004
    lines = [((x, -0.01, -2.05), (x, -0.01, 2.05))
             for x in np.arange(-1.2, 1.21, 0.4)]
    lines += [((-1.35, -0.01, z), (1.35, -0.01, z))
              for z in np.arange(-2.0, 2.01, 0.4)]
    for a, b in lines:
        sp = cu.splines.new('POLY')
        sp.points.add(1)
        sp.points[0].co = (*a, 1.0)
        sp.points[1].co = (*b, 1.0)
    grat = _link(bpy.data.objects.new(PREFIX + "Graticule", cu))
    grat.parent = root
    grat.data.materials.append(_emission("MatGraticule", (0.1, 0.45, 0.18), 0.7))

    # the two traces: POLY curves rewritten every frame by _push_traces()
    for name, matname, color, bev in (
            ("TraceIn", "MatTraceIn", (0.2, 1.0, 0.3), 0.010),
            ("TraceOut", "MatTraceOut", (1.0, 0.6, 0.12), 0.012)):
        pts = [(x, -0.02, 0.0) for x in SCOPE_XS]
        tr = _poly_curve(name, pts, bev)
        tr.data.use_fill_caps = False
        tr.parent = root
        tr.data.materials.append(_emission(matname, color, 4.0))

    rot_txt = (math.radians(90), 0, 0)
    green = _emission("MatTraceIn", (0.2, 1.0, 0.3), 4.0)
    amber = _emission("MatTraceOut", (1.0, 0.6, 0.12), 4.0)
    _text("ScopeLblIn", "IN Vgk  5 V/div", 0.13, (-1.35, -0.03, 2.18), rot_txt,
          green, parent=root)
    _text("ScopeGain", "GAIN --", 0.15, (-0.42, -0.03, 2.18), rot_txt,
          amber, parent=root)
    _text("ScopeLblOut", "OUT Vp  100 V/div", 0.13, (0.42, -0.03, 2.18), rot_txt,
          amber, parent=root)
    # axis markers, left column (clear of the tube from the bench camera);
    # the shared center line is IN -20 V and OUT 500 V
    _text("ScopeMkInHi", "+5V", 0.10, (-1.36, -0.02, 1.84), rot_txt,
          green, parent=root)
    _text("ScopeMkInLo", "-20V", 0.10, (-1.36, -0.02, 0.06), rot_txt,
          green, parent=root)
    _text("ScopeMkOutHi", "500V", 0.10, (-1.36, -0.02, -0.20), rot_txt,
          amber, parent=root)
    _text("ScopeMkOutLo", "0V", 0.10, (-1.36, -0.02, -1.97), rot_txt,
          amber, parent=root)


# resistor color code, digits 0-9
_BAND_RGB = [(0.02, 0.02, 0.02), (0.28, 0.15, 0.06), (0.75, 0.05, 0.03),
             (0.90, 0.35, 0.02), (0.85, 0.70, 0.03), (0.05, 0.45, 0.08),
             (0.03, 0.15, 0.65), (0.45, 0.10, 0.55), (0.35, 0.35, 0.35),
             (0.90, 0.90, 0.90)]


def _recolor_bands(tag, kohms):
    """Recolor a resistor's bands to the nearest 2-digit code."""
    ohms = max(float(kohms), 0.001) * 1000.0
    exp = int(math.floor(math.log10(ohms))) - 1
    d = int(round(ohms / 10 ** exp))
    if d >= 100:
        d //= 10
        exp += 1
    for suffix, digit in ((tag + "A", d // 10), (tag + "B", d % 10),
                          (tag + "C", exp)):
        m = bpy.data.materials.get(PREFIX + "MatBand" + suffix)
        if m:
            bsdf = m.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = (*_BAND_RGB[digit], 1.0)


def _upd_rl(self, context):
    _recolor_bands("", self.cbamp_rl)


def _upd_rk(self, context):
    _recolor_bands("K", self.cbamp_rk)


def _upd_kbypass(self, context):
    show = self.cbamp_k_bypass
    for nm in ("BypCapK", "WireCapK1", "WireCapK2", "CapKLbl"):
        ob = _ob(nm)
        if ob:
            ob.hide_viewport = not show
            ob.hide_render = not show


def _upd_bplus(self, context):
    ob = _ob("PSUVal")
    if ob:
        ob.data.body = f"{self.cbamp_bplus:.0f} V"
    # OUT channel auto-range: 0-300 V below 300 V B+, 0-500 V above
    vmax = 300 if self.cbamp_bplus <= 300.0 else 500
    for name, want in (("ScopeLblOut", f"OUT Vp  {vmax // 5} V/div"),
                       ("ScopeMkOutHi", f"{vmax}V")):
        t = _ob(name)
        if t and t.data.body != want:
            t.data.body = want


def _build_bench():
    beige = _principled("MatResistor", (0.80, 0.68, 0.50), rough=0.6)
    wirem = _principled("MatWire", (0.65, 0.55, 0.40), metallic=1.0, rough=0.35)
    dark = _principled("MatPSU", (0.10, 0.12, 0.16), rough=0.5)
    red = _principled("MatPostR", (0.65, 0.05, 0.04), rough=0.4)
    blk = _principled("MatPostB", (0.02, 0.02, 0.02), rough=0.4)
    lbl = _emission("MatLabel", (0.85, 0.9, 1.0), 1.5)
    rot_txt = (math.radians(90), 0, 0)

    # --- B+ supply, right of the tube
    _box("PSU", (1.05, 0.75, 0.95), (3.2, 0.5, -1.32), dark)
    _cyl("PSUPostP", 0.05, 0.28, loc=(2.95, 0.35, -0.72), segs=12).data \
        .materials.append(red)
    _cyl("PSUPostN", 0.05, 0.28, loc=(3.45, 0.35, -0.72), segs=12).data \
        .materials.append(blk)
    _text("PSULbl", "B+", 0.30, (3.2, 0.115, -1.20), rot_txt, lbl, align='CENTER')
    _text("PSUVal", "300 V", 0.22, (3.2, 0.115, -1.62), rot_txt, lbl,
          align='CENTER')

    # --- plate load resistor with live color bands
    for nm, dx, r, dpt in (("ResLeadA", -0.42, 0.014, 0.24),
                           ("ResLeadB", 0.42, 0.014, 0.24),
                           ("ResBody", 0.0, 0.085, 0.62)):
        ob = _cyl(nm, r, dpt, loc=(2.0 + dx, 0.30, 1.95), segs=24)
        ob.rotation_euler = (0, math.radians(90), 0)
        ob.data.materials.append(wirem if "Lead" in nm else beige)
    for suffix, dx in (("A", -0.20), ("B", -0.10), ("C", 0.00), ("D", 0.22)):
        ob = _cyl("Band" + suffix, 0.092, 0.05,
                  loc=(2.0 + dx, 0.30, 1.95), segs=24)
        ob.rotation_euler = (0, math.radians(90), 0)
        base = (0.75, 0.60, 0.10) if suffix == "D" else (0.3, 0.3, 0.3)
        ob.data.materials.append(
            _principled("MatBand" + suffix, base, rough=0.45))

    # --- signal generator, front-left
    _box("Gen", (0.95, 0.60, 0.75), (-3.0, -0.8, -1.42), dark)
    _cyl("GenPostP", 0.045, 0.24, loc=(-2.78, -0.80, -0.95), segs=12).data \
        .materials.append(red)
    _cyl("GenPostN", 0.045, 0.24, loc=(-3.22, -0.80, -0.95), segs=12).data \
        .materials.append(blk)
    sine = [(-3.0 + (i / 16.0 - 0.5) * 0.55, -1.115,
             -1.40 + math.sin(2 * math.pi * i / 16.0) * 0.13)
            for i in range(17)]
    _poly_curve("GenSine", sine, 0.014).data.materials.append(
        _emission("MatSine", (0.3, 0.9, 1.0), 2.0))
    _text("GenLbl", "GEN 0.25 Hz", 0.16, (-3.0, -1.115, -1.72), rot_txt, lbl,
          align='CENTER')

    # --- wiring: plate -> R_L -> B+(+);  B+(-) -> cathode;  gen -> grid, cathode
    wires = {
        "WirePlate": [(0.97, 0.30, 1.30), (0.97, 0.30, 1.95), (1.56, 0.30, 1.95)],
        "WireRtoPSU": [(2.44, 0.30, 1.95), (2.95, 0.30, 1.95),
                       (2.95, 0.35, -0.60)],
        "WirePSUGnd": [(3.45, 0.35, -0.62), (3.45, 0.35, -2.62),
                       (2.30, -1.45, -2.62)],
        "WireGenGrid": [(-2.78, -0.80, -0.85), (-2.78, -0.80, -0.55),
                        (-1.55, -0.95, -0.55), (-1.55, -0.95, 1.75),
                        (-0.45, 0.0, 1.75), (-0.45, 0.0, 1.42)],
        "WireGenGnd": [(-3.22, -0.80, -0.85), (-3.22, -0.80, -2.62),
                       (-2.00, -1.45, -2.62)],
    }
    for nm, pts in wires.items():
        _poly_curve(nm, pts, 0.022).data.materials.append(wirem)

    # --- cathode-bias network: ground bar, Rk (vertical, live bands), cap
    _box("GndBar", (4.8, 0.12, 0.07), (0.15, -1.45, -2.64), dark)
    _text("GndLbl", "COMMON", 0.13, (-0.4, -1.53, -2.86), rot_txt, lbl)
    beige = _principled("MatResistor", (0.80, 0.68, 0.50), rough=0.6)
    for nm, dz, r, dpt in (("ResLeadKA", 0.42, 0.014, 0.24),
                           ("ResLeadKB", -0.42, 0.014, 0.24),
                           ("ResBodyK", 0.0, 0.085, 0.62)):
        ob = _cyl(nm, r, dpt, loc=(1.65, -1.45, -2.02 + dz), segs=24)
        ob.data.materials.append(wirem if "Lead" in nm else beige)
    for suffix, dz in (("KA", 0.20), ("KB", 0.10), ("KC", 0.00), ("KD", -0.22)):
        ob = _cyl("Band" + suffix, 0.092, 0.05, loc=(1.65, -1.45, -2.02 + dz),
                  segs=24)
        base = (0.75, 0.60, 0.10) if suffix == "KD" else (0.3, 0.3, 0.3)
        ob.data.materials.append(
            _principled("MatBand" + suffix, base, rough=0.45))
    _text("RkLbl", "Rk", 0.15, (1.85, -1.48, -2.06), rot_txt, lbl)
    _poly_curve("WireCathRk", [(1.30, -0.95, -1.90), (1.65, -1.45, -1.60),
                               (1.65, -1.45, -1.66)],
                0.022).data.materials.append(wirem)
    _poly_curve("WireRkGnd", [(1.65, -1.45, -2.38), (1.65, -1.45, -2.62)],
                0.022).data.materials.append(wirem)
    cap = _cyl("BypCapK", 0.10, 0.38, loc=(2.45, -1.45, -2.02), segs=24)
    cap.data.materials.append(_principled("MatCap", (0.15, 0.25, 0.55),
                                          rough=0.35))
    _text("CapKLbl", "Ck", 0.13, (2.60, -1.48, -2.06), rot_txt, lbl)
    _poly_curve("WireCapK1", [(1.65, -1.45, -1.62), (2.45, -1.45, -1.62),
                              (2.45, -1.45, -1.82)],
                0.020).data.materials.append(wirem)
    _poly_curve("WireCapK2", [(2.45, -1.45, -2.22), (2.45, -1.45, -2.62)],
                0.020).data.materials.append(wirem)


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
    T = getattr(sc, "cbamp_heater_t", T_REF)
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
    _S["t"] = 0.0
    _S["ip_loop"] = 0.0
    _S["khat"] = _S.get("khat", 0.0)    # calibration persists across resets
    _S["vp"] = float(getattr(_scene(), "cbamp_bplus", 300.0))  # tube off -> Vp = B+
    _S["vk"] = 0.0                       # no current -> no cathode lift
    _S["vg"] = float(getattr(_scene(), "cbamp_sig_dc", 0.0))
    _S["vg_buf"] = np.full(SCOPE_N, _S["vg"])
    _S["gen_buf"] = np.full(SCOPE_N, float(getattr(_scene(), "cbamp_sig_dc", 0.0)))
    _S["vp_buf"] = np.full(SCOPE_N, _S["vp"])
    _S["gain_txt"] = "--"
    _push_draw()
    _push_traces()


def _push_draw():
    ob = _ob("Electrons")
    if ob is None:
        return
    me = ob.data
    me.vertices.foreach_set("co", _S["draw"].ravel())
    me.update()
    me.update_tag()


def _push_traces():
    """Write the rolling Vg/Vp buffers into the two scope trace curves.

    Absolute scales on a 10-division screen (div = 0.4 units):
    IN  top half, 5 V/div, covering -20..+5 V (0 V ref on the +1.6 line);
    OUT bottom half auto-ranges with B+: 0-300 V (60 V/div) when B+ <= 300,
    else 0-500 V (100 V/div). 0 V is the bottom line; the bands meet at the
    center line. _upd_bplus() keeps the on-screen labels in step.
    """
    bp = float(getattr(_scene(), "cbamp_bplus", 300.0))
    out_vmax = 300.0 if bp <= 300.0 else 500.0
    for name, buf, z0, upv, lo, hi in (
            ("TraceIn", _S["vg_buf"], 1.6, 0.08, 0.0, 2.0),           # 5 V/div
            ("TraceOut", _S["vp_buf"], -2.0, 2.0 / out_vmax, -2.0, 0.0)):
        ob = _ob(name)
        if ob is None:
            continue
        arr = np.empty((SCOPE_N, 4), np.float32)
        arr[:, 0] = SCOPE_XS
        arr[:, 1] = -0.02
        arr[:, 2] = np.clip(z0 + buf * upv, lo, hi)
        arr[:, 3] = 1.0
        sp = ob.data.splines[0]
        sp.points.foreach_set("co", arr.ravel())
        ob.data.update_tag()


def _step(scene):
    S = _S
    if "pos" not in S:
        reset_electrons()
    rng = S["rng"]
    p, v, al = S["pos"], S["vel"], S["alive"]
    T = scene.cbamp_heater_t

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

    # --- the circuit. SELF-BIAS: plate current through Rk lifts the cathode,
    # so the tube sees Vg = Vgen - Vk and Vp = B+ - Ip*RL - Vk. One unknown
    # (Ip) closes everything -- solved by bisection against a live-calibrated,
    # emission-aware perveance model. No measured-current servo loops (they
    # ring against the ~15-frame electron transit delay).
    S["t"] += DT
    Vgen = scene.cbamp_sig_dc + scene.cbamp_sig_amp * math.sin(
        2 * math.pi * FREQ * S["t"])
    Bp = scene.cbamp_bplus
    RL = scene.cbamp_rl
    RK = scene.cbamp_rk
    emis = min(1.0, math.exp(-T_SLOPE * (1.0 / T - 1.0 / T_REF)))

    def _solve_ip(vgen_x, vk_fixed=None):
        """Bisect Ip [mA]; returns (ip, vk, vp). Monotone: more Ip -> more
        drop on RL and Rk -> less drive -> less model current."""
        lo, hi = 0.0, Bp / max(RL, 1e-6)
        for _ in range(26):
            x = 0.5 * (lo + hi)
            vk = vk_fixed if vk_fixed is not None else x * RK
            vp = max(Bp - x * RL - vk, 0.0)
            d = max(0.0, (vgen_x - vk) + vp / MU - V_SC * cf)
            if S["khat"] * emis * d ** 1.5 * MA_PER_E - x > 0.0:
                lo = x
            else:
                hi = x
        x = 0.5 * (lo + hi)
        vk = vk_fixed if vk_fixed is not None else x * RK
        return x, vk, max(Bp - x * RL - vk, 0.0)

    # DC operating point: freezes Vk when bypassed, and anchors the
    # calibration (pairing the time-averaged particle current with the
    # instantaneous drive would Jensen-bias K upward on every driven run)
    ip_dc, vk_dc, vp_dc = _solve_ip(scene.cbamp_sig_dc)
    d_dc = max(0.0, (scene.cbamp_sig_dc - vk_dc) + vp_dc / MU - V_SC * cf)
    # Down-corrections are always allowed: if khat is stuck too high after
    # a starved transient, the solver holds a starved op point, the healthy-
    # drive gate would stay closed, and the wrong khat could never heal.
    if emis > 0.2 and d_dc > 0.5:
        k_inst = S["ip_loop"] / (emis * d_dc ** 1.5)
        # down-corrections fire ONLY on the lockup signature (cloud pinned
        # at cap): during warmup ramps the current lags the drive through
        # the transit delay, so k_inst reads low and would wrongly hammer
        # khat down; a filling (sub-cap) cloud means warmup, not lockup
        down_ok = k_inst < S["khat"] and cloud >= CLOUD_CAP - 25
        if down_ok or (d_dc > 1.0 and S["ip_loop"] > 5.0):
            a = 0.15 if S["khat"] < 0.7 * k_inst else K_ALPHA
            S["khat"] += a * (k_inst - S["khat"])

    if scene.cbamp_k_bypass:
        # bypassed: the capacitor holds Vk at the DC operating point; the
        # signal rides on a frozen cathode (full gain)
        ip_sol, vk_sol, vp_sol = _solve_ip(Vgen, vk_fixed=vk_dc)
    else:
        # unbypassed: Vk follows the signal -> negative feedback, less gain
        ip_sol, vk_sol, vp_sol = _solve_ip(Vgen)

    S["vk"] += VP_SMOOTH * (vk_sol - S["vk"])
    S["vp"] += VP_SMOOTH * (vp_sol - S["vp"])
    Vp = S["vp"]
    Vk = S["vk"]
    Vg = Vgen - Vk          # grid-to-cathode: what the tube actually feels
    S["vg"] = Vg

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
    S["ip_loop"] = (1.0 - IP_LOOP_ALPHA) * S["ip_loop"] + IP_LOOP_ALPHA * hits
    S["cloud"] = cloud
    S["grid_hits"] = grid_hits

    # --- draw + meter
    S["draw"][:] = PARK
    aidx = np.flatnonzero(al)
    if aidx.size:
        S["draw"][aidx] = p[aidx].astype(np.float32)
    _push_draw()

    # --- scope + meter
    S["vg_buf"][:-1] = S["vg_buf"][1:]
    S["vg_buf"][-1] = Vg
    S["gen_buf"][:-1] = S["gen_buf"][1:]
    S["gen_buf"][-1] = Vgen
    S["vp_buf"][:-1] = S["vp_buf"][1:]
    S["vp_buf"][-1] = Vp + Vk    # scope probe reads plate-to-GROUND
    _push_traces()
    S["ip_show"] = (Bp - (Vp + Vk)) / max(RL, 1e-6)  # resistor current, KVL-true
    if scene.cbamp_sig_amp > 0.05:
        # stage gain is measured from the GENERATOR terminal; the scope's
        # green Vgk trace already shows how feedback shrinks the tube's drive
        g = float(np.std(S["vp_buf"]) / max(float(np.std(S["gen_buf"])), 1e-6))
        S["gain_txt"] = f"{g:.1f}x"
    else:
        S["gain_txt"] = "--"
    txt = (f"B+ {Bp:.0f}V   Vp {Vp + Vk:.0f}V\n"
           f"Ip {S['ip_show']:.2f}mA   Vk {Vk:.2f}V\n"
           f"Vgk {Vg:+.1f}V (self-bias)\n"
           f"Gain = {S['gain_txt']}")
    if txt != S["last_txt"]:
        mo = _ob("Meter")
        if mo:
            mo.data.body = txt
        go = _ob("ScopeGain")
        if go:
            go.data.body = f"GAIN {S['gain_txt']}"
        S["last_txt"] = txt
    if scene.frame_current % 4 == 0:
        for w in bpy.data.window_managers[0].windows:
            for a in w.screen.areas:
                if a.type == 'VIEW_3D':
                    a.tag_redraw()


def amp_cbias_frame_change(scene, depsgraph=None):
    try:
        _step(scene)
        _S["fails"] = 0
    except Exception:
        import traceback
        traceback.print_exc()
        _S["fails"] = _S.get("fails", 0) + 1
        if _S["fails"] > 5:
            _remove_handlers()
            print("cathode_bias_amp_sim: handler removed after repeated errors")


def _remove_handlers():
    # strip all three tube projects' handlers: one sim per Blender session
    for hnd in list(bpy.app.handlers.frame_change_pre):
        if getattr(hnd, "__name__", "").startswith(("tri_", "pen_", "amp_")):
            bpy.app.handlers.frame_change_pre.remove(hnd)


def register_sim():
    _remove_handlers()
    bpy.app.handlers.frame_change_pre.append(amp_cbias_frame_change)
    if "pos" not in _S:
        reset_electrons()


# ------------- UI ------------------------------------------------------------
def _upd_heat(self, context):
    _apply_heat(self)


def _upd_glass(self, context):
    g = _ob("Glass")
    if g:
        g.hide_viewport = not self.cbamp_show_glass
        g.hide_render = g.hide_viewport


class CBAMP_OT_reset(bpy.types.Operator):
    bl_idname = "cbamp.reset"
    bl_label = "Reset"
    bl_description = "Clear all electrons and restart the meter"

    def execute(self, context):
        reset_electrons()
        return {'FINISHED'}


class CBAMP_OT_play(bpy.types.Operator):
    bl_idname = "cbamp.play"
    bl_label = "Run / Pause"
    bl_description = "Toggle the simulation (animation playback)"

    def execute(self, context):
        bpy.ops.screen.animation_play()
        return {'FINISHED'}


class CBAMP_OT_view(bpy.types.Operator):
    bl_idname = "cbamp.view"
    bl_label = "View"
    bl_description = "Jump to a preset camera"
    which: bpy.props.StringProperty(default="OVER")

    def execute(self, context):
        set_view(self.which)
        return {'FINISHED'}


class CBAMP_PT_main(bpy.types.Panel):
    bl_label = "Cathode-Bias Amp"
    bl_idname = "CBAMP_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Cathode-Bias Amp"

    def draw(self, context):
        s = context.scene
        L = self.layout
        col = L.column(align=True)
        col.prop(s, "cbamp_heater_t", slider=True)
        col.prop(s, "cbamp_bplus", slider=True)
        col.prop(s, "cbamp_rl", slider=True)
        col.prop(s, "cbamp_rk", slider=True)
        col.separator()
        col.prop(s, "cbamp_sig_amp", slider=True)
        col.prop(s, "cbamp_sig_dc", slider=True)
        row = L.row(align=True)
        row.operator("cbamp.play", icon='PLAY')
        row.operator("cbamp.reset", icon='FILE_REFRESH')
        row = L.row(align=True)
        for label, key in (("Bench", "OVER"), ("Top", "TOP"), ("Inside", "INSIDE")):
            row.operator("cbamp.view", text=label).which = key
        L.prop(s, "cbamp_k_bypass")
        L.prop(s, "cbamp_show_glass")
        box = L.box()
        box.label(text=f"Vp: {_S.get('vp', 0.0) + _S.get('vk', 0.0):.0f} V   "
                       f"Ip: {_S.get('ip_show', 0.0):.2f} mA")
        box.label(text=f"Vk: {_S.get('vk', 0.0):.2f} V   "
                       f"Vgk: {_S.get('vg', 0.0):+.1f} V (self-bias)")
        box.label(text=f"Gain: {_S.get('gain_txt', '--')}")
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
    for name in ("cbamp_heater_t", "cbamp_bplus", "cbamp_rl", "cbamp_rk",
                 "cbamp_sig_amp", "cbamp_sig_dc", "cbamp_k_bypass",
                 "cbamp_show_glass"):
        if hasattr(Sc, name):
            try:
                delattr(Sc, name)
            except Exception:
                pass
    Sc.cbamp_heater_t = bpy.props.FloatProperty(
        name="Heater temp (K)", min=300.0, max=1300.0, default=1100.0,
        step=100, precision=0, update=_upd_heat,
        description="Cathode temperature: sets thermionic emission (cloud density)")
    Sc.cbamp_bplus = bpy.props.FloatProperty(
        name="B+ supply (V)", min=150.0, max=500.0, default=300.0,
        step=100, precision=0, update=_upd_bplus,
        description="HV supply feeding the plate through the load resistor")
    Sc.cbamp_rl = bpy.props.FloatProperty(
        name="Plate resistor (kOhm)", min=20.0, max=500.0, default=100.0,
        step=100, precision=0, update=_upd_rl,
        description="Load between B+ and plate; Vp = B+ - Ip*RL. Bands update live")
    Sc.cbamp_sig_amp = bpy.props.FloatProperty(
        name="Signal amplitude (Vpk)", min=0.0, max=8.0, default=1.0,
        step=10, precision=1,
        description="Sine amplitude on the grid; crank it to see clipping")
    Sc.cbamp_sig_dc = bpy.props.FloatProperty(
        name="Generator DC offset (V)", min=-10.0, max=5.0, default=0.0,
        step=10, precision=1,
        description="Leave at 0: the cathode resistor sets the bias by itself. "
                    "Nudge it and watch Vk fight back")
    Sc.cbamp_rk = bpy.props.FloatProperty(
        name="Cathode resistor (kOhm)", min=0.1, max=10.0, default=1.8,
        step=10, precision=1, update=_upd_rk,
        description="Self-bias resistor: Vk = Ip*Rk lifts the cathode, biasing "
                    "the grid negative. Bands update live")
    Sc.cbamp_k_bypass = bpy.props.BoolProperty(
        name="Cathode bypass capacitor", default=True, update=_upd_kbypass,
        description="Bypassed: full gain. Unbypassed: Rk applies negative "
                    "feedback and gain drops")
    Sc.cbamp_show_glass = bpy.props.BoolProperty(
        name="Show glass envelope", default=True, update=_upd_glass)

    for cls_name in ("CBAMP_OT_reset", "CBAMP_OT_play",
                     "CBAMP_OT_view", "CBAMP_PT_main"):
        old = getattr(bpy.types, cls_name, None)
        if old is not None:
            try:
                bpy.utils.unregister_class(old)
            except Exception:
                pass
    for cls in (CBAMP_OT_reset, CBAMP_OT_play, CBAMP_OT_view, CBAMP_PT_main):
        bpy.utils.register_class(cls)

    # top camera sits INSIDE the envelope just below the top mica, so the
    # view is a clean electrode cross-section instead of staring at the spacer
    _cam("Cam_Top", (0, 0, 1.30), ortho=2.7, clip=0.003)
    _cam("Cam_Inside", (0.52, 0.52, 0.05), target=(-0.1, -0.1, 0.0),
         lens=13.0, clip=0.004)
    _cam("Cam_Over", (6.6, -7.6, 3.6), target=(-0.25, 0.2, 0.25), lens=34.0)
    _scene().camera = _ob("Cam_Over")

    if not _ob("Meter"):
        fc = bpy.data.curves.new(PREFIX + "Meter", 'FONT')
        fc.body = "B+ 300V   Vp 300V\nIp 0.00mA   Vg -4.0V\nGain = --"
        fc.size = 0.22
        fc.align_x = 'CENTER'
        mo = _link(bpy.data.objects.new(PREFIX + "Meter", fc))
        mo.location = (0.0, -1.80, -1.45)
        mo.rotation_euler = (math.radians(90), 0, 0)
        mo.data.materials.append(_emission("MatMeter", (0.3, 1.0, 0.5), 3.0))

    _apply_heat()
    _upd_rl(_scene(), None)
    _upd_rk(_scene(), None)
    _upd_bplus(_scene(), None)
    _upd_kbypass(_scene(), None)


# ------------- entry points --------------------------------------------------
def build_all():
    wipe_scene()
    build_geometry()
    build_materials()
    register_ui()
    register_sim()
    reset_electrons()
    set_view("OVER")


def selfcheck():
    """The stage must behave like a self-biased class-A triode amplifier."""
    sc = _scene()

    def run(T, dc, A, bp, rl, rk, frames, byp=True):
        sc.cbamp_heater_t, sc.cbamp_sig_dc, sc.cbamp_sig_amp = T, dc, A
        sc.cbamp_bplus, sc.cbamp_rl, sc.cbamp_rk = bp, rl, rk
        sc.cbamp_k_bypass = byp
        reset_electrons()
        for _ in range(frames):
            _step(sc)
        return _S

    S = run(500, 0, 0, 300, 100, 1.8, 100)      # cold: Vp at B+, no cathode lift
    assert S["vp"] > 0.97 * 300 and S["vk"] < 0.2, (
        f"cold but Vp={S['vp']:.0f} Vk={S['vk']:.2f}")

    S = run(1100, 0, 0, 300, 100, 1.8, 400)     # bias finds ITSELF (dc = 0!)
    vp0, vk0 = S["vp"], S["vk"]
    ip0 = S["ip_loop"] * MA_PER_E
    assert 1.0 < vk0 < 5.0, f"self-bias out of range: Vk={vk0:.2f}"
    assert 0.25 * 300 < vp0 + vk0 < 0.85 * 300, f"bad op point Vp={vp0 + vk0:.0f}"
    kvl_p = abs(300.0 - (vp0 + vk0) - ip0 * 100.0)
    kvl_k = abs(vk0 - ip0 * 1.8)
    assert kvl_p < 25.0, f"plate load line off by {kvl_p:.1f} V"
    assert kvl_k < 1.0, f"cathode line off by {kvl_k:.2f} V"
    assert float(np.std(S["vp_buf"][-24:])) < 6.0, "loop ringing"

    vk_hot = run(1100, 2, 0, 300, 100, 1.8, 380)["vk"]   # push bias hotter...
    # loaded gm ~ gain/RL, so a +2 V push only lifts Vk by ~0.2-0.4 V here
    assert vk_hot > vk0 + 0.15, (                         # ...and Vk fights back
        f"self-regulation missing: Vk {vk0:.2f} -> {vk_hot:.2f}")
    vp_neg = run(1100, -3, 0, 300, 100, 1.8, 380)["vp"]
    vp_pos = run(1100, 2, 0, 300, 100, 1.8, 380)["vp"]
    assert vp_neg > vp0 > vp_pos, "not inverting"

    S = run(1100, 0, 1, 300, 100, 1.8, 460)     # bypassed gain
    g_byp = float(np.std(S["vp_buf"]) / max(float(np.std(S["gen_buf"])), 1e-6))
    corr = float(np.corrcoef(S["gen_buf"], S["vp_buf"])[0, 1])
    assert 5.0 < g_byp < 22.0, f"gain {g_byp:.1f} out of range"
    assert corr < -0.7, f"not inverted (corr={corr:.2f})"

    S = run(1100, 0, 1, 300, 100, 1.8, 460, byp=False)   # feedback cuts gain
    g_unbyp = float(np.std(S["vp_buf"]) / max(float(np.std(S["gen_buf"])), 1e-6))
    assert g_byp > 1.15 * g_unbyp, (
        f"unbypassed Rk should cut gain: {g_byp:.1f} !> 1.15x{g_unbyp:.1f}")

    S = run(1100, 0, 1, 300, 100, 5.0, 460, byp=False)   # more Rk, more feedback
    g_unbyp5 = float(np.std(S["vp_buf"]) / max(float(np.std(S["gen_buf"])), 1e-6))
    assert g_unbyp5 < g_unbyp, (
        f"feedback should grow with Rk: {g_unbyp5:.1f} !< {g_unbyp:.1f}")

    # overdrive. A self-biased mu=20 triode can't be driven to full cutoff
    # (as Ip falls, Vp rises and Vp/mu pulls the tube back on), so the RC
    # stage clips HARD at the bottom and only compresses at the top.
    S = run(1100, 0, 8, 300, 100, 1.8, 460)
    assert float(np.min(S["vp_buf"][-192:])) < 40.0, "no bottoming clip"
    assert float(np.max(S["vp_buf"][-192:])) > 0.80 * 300, "top not compressing high"

    S = run(1100, 0, 0, 300, 500, 1.8, 340)     # stability at max load
    assert float(np.std(S["vp_buf"][-24:])) < 20.0, "unstable at RL=500k"

    print(f"selfcheck OK  self-bias Vk={vk0:.2f}V (Vgk=-{vk0:.2f}V at dc=0) | "
          f"op Vp={vp0 + vk0:.0f}V Ip={ip0:.2f}mA | gain {g_byp:.1f}x byp, "
          f"{g_unbyp:.1f}x unbyp, {g_unbyp5:.1f}x @Rk=5k (corr {corr:.2f})")
    return True


if __name__ == "__main__":
    # Fresh scene (blender -P cathode_bias_amp_sim.py): full build.
    # Run Script inside a saved .blend: just re-register handler/UI.
    if _ob("Cathode") is None:
        build_all()
    else:
        register_ui()
        register_sim()
        reset_electrons()
