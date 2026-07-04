# Interactive Triode Vacuum-Tube Simulation in Blender

## Context

The user (who just photographed a real 6SN7's internal electrode assembly) wants a **realistic, interactive teaching simulation of a triode** built in Blender, so students can see how heater temperature, grid voltage, and plate voltage together govern electron flow through the tube's internal electric field. Blender 5.1.2 + blender-mcp addon are running (verified live); scene is factory-default and will be wiped (targeted deletes only — never `read_factory_settings`, which would kill the MCP socket). `/home/holla/tube` is empty; all deliverables land there.

User decisions (confirmed via questions):
- **Realistic cylindrical geometry** like the 6SN7 photo — cylindrical cathode, helical grid on 2 support rods, rounded-box plate — with a **cutaway window** in the plate for outside viewing.
- **Exaggerated radial gaps (~3×)**, museum-cutaway style, so the cloud, grid focusing, and in-tube camera all read clearly.

Requirements: (1) full electrode structure — heater/cathode/grid/plate; (2) electron particle flow cathode→plate; (3) visible space-charge cloud around the hot cathode; (4) grid-voltage slider — negative grid repels electrons back toward the cathode, through cutoff; (5) positive plate pulls electrons through the grid gaps; (6) heater-temp slider controls emission/cloud density; (7) plate-voltage slider controls the extraction field; (8) top view + camera *inside the tube between grid and plate* + overview, free fly-around preserved.

## Architecture (verified against live Blender 5.1.2 by a design-review agent)

**A single Python module `/home/holla/tube/triode_sim.py` holds everything** (geometry builder, materials, physics, UI). Each MCP `execute_blender_code` call is then just `sys.path`-insert + `importlib.reload` + one phase-function call — exec namespaces don't persist across MCP calls, but `sys.modules` does, and the file is itself a deliverable (`blender -P triode_sim.py` reproduces the scene standalone).

- **Electron physics**: `frame_change_pre` handler (runs before depsgraph eval, so the frame picks up new coords) + numpy state (`pos`, `vel`, `alive` for a 6000-electron pool). Explicit Euler, **4 substeps/frame**, velocity cap, drag. Handler self-heals: re-fetches objects by name (undo-safe), auto-unregisters after ~5 consecutive exceptions. Idempotent `register()` strips old handlers by `__name__` prefix — no double-speed sim after reloads.
- **Electron rendering**: `Electrons` mesh vertices updated per frame via `foreach_set("co", …)` + `mesh.update()` + `update_tag()`; an emissive icosphere child instanced via `instance_type='VERTS'` (**enum verified present in 5.1**). Dead electrons parked at (0,0,−100). Fallback chain if instancing doesn't refresh per-frame (gated by an explicit checkpoint): write `mesh.attributes['position']` → minimal 5-node GN Instance-on-Points → GN point rendering.
- **Controls**: registered `bpy.props.FloatProperty` sliders on `Scene` — `grid_voltage` −20…+10 V (default 0), `plate_voltage` 0…300 V (default 150), `heater_temp` 300…1300 K (default 1100) — in a `TRIODE_PT` N-panel ("Triode" tab) with buttons: Run/Pause, Reset electrons, camera presets Top/Inside/Overview, glass show/hide, plus a live Ip readout row. **No drivers**: heater/cathode glow (Blackbody node temperature + emission strength) is set imperatively from prop `update=` callbacks — responds even while paused, avoids flaky driver refresh.
- **Plate-current meter**: in-scene text object + panel label, `Ip = EMA(plate hits) × 0.2 mA` (≈25 mA at Vg=0/Vp=150 — plausible 6SN7 territory). Text body written only when the rounded string changes (re-tessellation cost).
- **Rendering**: EEVEE (`BLENDER_EEVEE`), near-black world + dim fill light (tube stays readable when cold), strong emission (8–10) for electrons/heater — legacy bloom is gone in 5.x; viewport-compositor Glare is **optional last-chunk polish** (5.0 moved `scene.node_tree` → `scene.compositing_node_group` and Glare options into input sockets). Glass = alpha-blend fake (`surface_render_method='BLENDED'`), raytracing off for perf.

## Geometry spec (Blender units; tube ≈ 3 tall; z ∈ [−1.2, 1.2] active region; all objects prefixed `TRI_`)

| Part | Shape | Size | Material |
|---|---|---|---|
| Heater | hairpin wire inside cathode, tips out the top | r ≈ 0.05 | emissive, blackbody(T) |
| Cathode | cylinder | r_c = 0.15, h = 2.4 | oxide white-grey, thermal glow |
| Grid | helix ~20 turns + 2 support rods | r_g = 0.45, wire r = 0.012, pitch 0.12 | copper |
| Plate | rounded-square sleeve, **cutaway window** on front face | inradius 1.0, h = 2.6 | dark graphite |
| Mica spacers | discs with holes, top & bottom | r ≈ 1.3 | translucent beige |
| Glass envelope | cylinder + dome, toggleable | r ≈ 1.6 | clear alpha-blend |
| Base + pins | stub cylinder + 8 pins | — | bakelite / nickel |

Physics absorbs cylindrically at r = 0.98 (corner deviation of the square sleeve ≈ 0.15 u — visually unnoticeable, keeps physics 1-D radial).

## Physics model (pedagogical, cylindrical-radial; per substep h)

- **Emission (reqs 3, 6)**: `n(T) = 150·exp(−13000·(1/T − 1/1100))` e⁻/frame, clamped 400, × space-charge throttle `max(0, 1 − n_cloud/2000)`. n(700 K) ≈ 0.2/frame ≈ nothing; n(1100 K) = 150. Spawn on cathode surface, `v_r = 0.2·√(T/1100) + |N(0, 0.06)|`, tangential/z jitter.
- **Region 1, cathode→grid (req 4)**: `a_r = C1·(Vg + Vp/μ − V_sc·n_cloud/cap)` — the −V_sc term is mean-field space charge, giving true space-charge-limited vs emission-limited behavior (Ip–Vp saturation, the core pedagogy). Negative net → retarding field → electrons fall back → **cloud**; Vg below −Vp/μ → **cutoff**.
- **Region 2, grid→plate (reqs 5, 7)**: `a_r = C2·(Vp − Vg)` outward.
- **Grid-wire local term**: helix ≈ ring stack; in band |r−r_g| < 0.10, nearest-ring force `K_w·(−Vg)/d²` (softened, ε=0.02) — repulsion when Vg<0 (**visible gap focusing**), attraction when Vg>0 with absorption within 0.015 (**grid current**).
- **Integrate**: `v += a·h; v ×= (1−γh); |v| ≤ v_max; x += v·h`.
- **Absorb/recycle**: r ≥ 0.98 → plate hit (→ Ip EMA, α=0.15); r ≤ r_c inbound → reabsorb; |z| > 1.2 → recycle.

**Starting constants** (tuned so Vg=0/Vp=150 transit ≈ 0.66 s at 24 fps; Vg=−8/Vp=150 near cutoff by construction, μ·cutoff = Vp):
`μ=20, C1=0.5, C2=0.04, V_sc=1.5 V, cloud cap=2000 (cloud ≡ alive & r<0.32), K_w=0.002, ε=0.02, wire-absorb 0.015 (Vg>0 only), dt=1/24 s, substeps=4, γ=1.5/s, v_max=6 u/s, pool N=6000, rng=default_rng(0)`.
Sanity anchors: Vp=0 → pure cloud at any T; T=500 → nothing at any Vp; Vg=−8, Vp=150 → net −0.5 V → cloud only, Ip≈0.

## Views (req 8)

- `TRI_Cam_Top`: orthographic, down the axis (scale ≈ 2.4) — radial geometry, gap crossings, wire interception.
- `TRI_Cam_Inside`: at (0.72, 0, 0) mid-height **in the grid–plate gap**, ~12 mm lens, `clip_start=0.005`, looking at the axis — grid wires silhouetted against the glowing cathode, electrons flying past.
- `TRI_Cam_Overview`: three-quarter full assembly.
- Panel buttons set `scene.camera` + `view_perspective='CAMERA'`; README notes walk/fly mode for free roaming.

## Implementation sequence (MCP chunks = tiny import/call snippets; code lives in the file)

1. **Write `triode_sim.py`** (module functions: `wipe_scene, build_geometry, build_materials, register_ui, register_sim, reset_electrons, unregister` — all idempotent). MCP: import + `wipe_scene()` + `build_geometry()`. ✔ `get_scene_info` shows only `TRI_*` objects; overview screenshot: cathode, 20-turn helix + rods, cutaway plate, micas, envelope.
2. MCP: `build_materials()` — dark world, dim fill, blackbody cathode/heater, cyan electrons, fake glass. ✔ Screenshot: cathode glows orange at default 1100 K.
3. MCP: `register_ui()` — props/panel/cameras/meter. ✔ Introspect prop limits + `hasattr(bpy.types,'TRIODE_PT_main')`; screenshot each camera framing.
4. MCP: `register_sim()`; T=1100/Vp=150/Vg=0; step frames 1–48 with `frame_set`, print alive/cloud/hits/Ip; screenshots Inside+Top at f=24 vs f=48. ✔ Counters plausible; **screenshots differ** (gates instancing-refresh risk); time the loop (perf gate: if >~4 s, pool→3000, emission→100).
5. **Operating-point sweep** (each: set props → step 36–60 → screenshot → record Ip): (a) T=500, Vp=250 → nothing; (b) T=1100, Vp=20 → dense cloud, small Ip; (c) Vp=250 → fast beam, high Ip; (d) Vg=−8, Vp=150 → cutoff; (e) Vg=+6 → wire interception top-down. ✔ Ip monotonic in Vp and in Vg∈[−8,0]; change Vg mid-stepping to prove live slider pickup.
6. **Playback test**: `screen.animation_play` (context override), next MCP call ~5 s later reads frame + screenshot + live-sets Vg=−8 + reads Ip, stops playback. ✔ Frame advanced, Ip responded. (Addon source-verified: commands marshal to main-thread timers, compatible with playback; if it stalls anyway → README: pause before MCP ops.)
7. **Deliverables**: embed script as text block, save `.blend`, write `README.md` (controls, views incl. fly mode, the 5 student experiments, how to re-register on reopen). Optional polish: viewport-compositor Glare via `scene.compositing_node_group` (print `node.inputs.keys()` first — options are sockets in 5.x). ✔ `ls` both files; final screenshots to user.

## Top risks & fallbacks

1. **Instanced spheres not refreshing per frame** — gated at chunk 4; fallback: `attributes['position']` → 5-node GN instancing → GN points.
2. **MCP starvation during playback** — verification never depends on playback (`frame_set` stepping); tested once at the end; worst case documented in README.
3. **Stale/double registration across reloads** — idempotent register, handlers stripped by name-prefix, state on `sys.modules`, Reset re-inits arrays.
4. **EEVEE perf with 6 k emissive instances** — raytracing off, icosphere subdiv 1, measured at chunk 4; constants scale down trivially.
5. **1/d² slingshot at grid wires (Vg>0)** — ε-softening + v_max + 4 substeps; if interception misbehaves: substeps 6, absorb radius 0.02.

## Deliverables

- `/home/holla/tube/triode_sim.py` — standalone idempotent build+sim script (also embedded in the .blend)
- `/home/holla/tube/triode_sim.blend` — ready-to-open interactive scene
- `/home/holla/tube/README.md` — controls, camera views, physics summary, 5 suggested student experiments
- Acceptance-scenario screenshots (all three cameras, all five operating points) sent to the user
