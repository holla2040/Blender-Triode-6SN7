# Triode Common-Cathode Amplifier Simulation (Blender)

## Context

Third build in the tube series. The user wants the verified triode simulation extended into a **resistance-loaded, grounded-cathode amplifier** as a teaching model, in a new subdirectory **`/home/holla/Blender-Triode-6SN7/amplifier/`** (user-chosen: inside the existing triode repo; commit only when asked). Blender 5.1.2 + MCP alive (pentode scene loaded — saved & pushed, safe to wipe).

Circuit (user spec): HV supply **B+ 150–500 V slider**; **plate resistor R_L 20k–500kΩ slider** between plate and B+; **plate-voltage slider REMOVED** — Vp is now set by the supply and the resistor drop; **sine generator on the grid** ("gate") with **AC amplitude and DC offset sliders** (frequency fixed for now); supply and generator negatives common to the **cathode**. User confirmed: include an **in-scene oscilloscope** (green Vg in, amber Vp out — gain, inversion, clipping) and **3D bench components** with a plate resistor whose **color bands live-update** to match R_L.

## What carries over

Copy `~/Blender-Triode-6SN7/triode_sim.py` → `amplifier/amplifier_sim.py` — all verified mechanisms (frame-handler numpy engine, dupli-vert electrons, idempotent registration, imperative material updates, cameras/passepartout, FRAME_DROP, targeted wipe, meter text, selfcheck, `__main__` guard). Renames: `TRI_`→`AMP_`, `tri_*`→`amp_*`, `TRIODE_*`→`AMPLIFIER_*`, `triode.*`→`amplifier.*`, tab "Amplifier". `_remove_handlers()` strips `tri_`/`pen_`/`amp_` prefixes so the three projects can't double-step one Blender session (README still advises one sim per session).

## What's new

### Circuit physics (the load line, solved live)

- **Scale fix**: `MA_PER_E` 0.2 → **0.02** so currents land at real 6SN7-class ~0.5–2.5 mA and `V = I(mA)·R(kΩ)` gives sane drops with 20–500 kΩ.
- Sliders: `amp_bplus` 150–500 V (default 300), `amp_rl` 20–500 kΩ (default 100), `amp_sig_amp` 0–8 Vpk (default 1.0), `amp_sig_dc` −15…+5 V (default −4.0), heater temp, glass toggle. **No plate or grid sliders** — grid bias is the generator's DC offset.
- Per frame in `_step`: `t += DT`; `Vg = dc + A·sin(2π·FREQ·t)` with `FREQ = 0.25 Hz` constant (96 frames/cycle — watchable; slider later). Then the plate follows the load line by relaxation: `Vp += LOOP_BETA·((B+ − Ip_ema·R_L) − Vp)`, clamped [0, B+], `LOOP_BETA ≈ 0.25` (stability tuned at checkpoint against R_L = 500k; fallbacks: smaller β, slower Ip EMA).
- Tube physics untouched — cutoff `−Vp/μ` now *moves with the operating point*, class-A/cutoff/grid-current clipping all emerge on their own.

### Oscilloscope (in-scene)

Dark screen plane (~2.6×1.6) on the bench, faint static graticule (thin emissive curves), two 192-point POLY-curve traces updated per frame from rolling buffers (same update pattern as the electron mesh): **green Vg** (fixed V/div) and **amber Vp** (0–B+ mapped to screen height) — two cycles visible; small "IN Vg / OUT Vp" labels. Gain readout = `std(Vp_buf)/std(Vg_buf)` when A > 0.05.

### 3D bench (stylized, reusing `_cyl`/`_poly_curve`/`_pydata_obj`)

- **B+ supply**: box right of tube, red +/black − posts, "B+" label + live voltage text.
- **Plate resistor**: axial body between plate wire and B+ post, **4 band rings recolored by the `amp_rl` update callback** (standard color code: e.g. 100k = brown-black-yellow + gold).
- **Generator**: box front-left with a sine symbol, output post.
- **Wires** (poly curves): plate→resistor→B+ +; gen→grid rod; B+ − and gen − → common bus → cathode base.
- Cameras: `Cam_Top`/`Cam_Inside` unchanged (tube interior); `Cam_Over` pulled back (~(7,−7.2,3.6), lens ~38) and its button renamed **Bench** to frame tube + scope + components; meter text shows `B+ / Vp / Ip / Vg / Gain`.

## Acceptance scenarios

| # | Settings | Expected |
|---|---|---|
| 1 | T=500 (cold) | Ip=0 → **Vp = B+** (no drop across R_L) |
| 2 | Defaults (300 V, 100k, dc −4, A=0) | Vp settles mid-supply; **KVL check: B+ − Vp − Ip·R_L ≈ 0**; loop stable (no ringing) |
| 3 | dc −12 → 0 sweep | Vp rises toward B+ / falls (inverting stage), electron stream visibly throttles |
| 4 | A=1 V | Scope: clean sine out, **inverted**, gain ≈ 5–20× (μ=20 bound), matches readout |
| 5 | A=8 V | **Clipping both ways**: flat top at Vp→B+ (cutoff) and bottoming near Vp→low / grid-current sparkle at Vg>0 |
| 6 | R_L 20k vs 470k | Operating point + gain shift sensibly; resistor bands recolor correctly; stable at 500k |

`selfcheck()` asserts: cold→Vp≈B+; KVL residual < ~5 V after settle; Vp monotonic vs dc bias; measured gain in [4, 20] at A=1; no instability (post-settle Vp variance small at A=0, R_L=500k); clipping at A=8 (cycle max Vp > 0.9·B+).

## Implementation sequence (chunked MCP, checkpoint screenshots each)

1. Write `amplifier/amplifier_sim.py` locally (copy + renames + deltas above). MCP: import, `wipe_scene()`, `build_geometry()` + `build_materials()` + `register_ui()` → screenshots: bench layout (Bench cam), scope graticule, resistor bands at 100k.
2. `register_sim()`; A=0 settle test: print per-frame Vp trace → verify convergence, tune `LOOP_BETA`; KVL residual print. Screenshot settled bench.
3. Sine on: scope traces form; screenshot gain view; flip R_L extremes; clipping run; `selfcheck()`; live-slider mid-run test.
4. Deliverables in `amplifier/`: `amplifier_sim.blend` (embed script), `shots/` stills (bench+scope gain, clipping, cutoff bias, inside-tube pulsing, resistor bands 20k vs 470k), `README.md` (load-line explanation, controls, experiments: biasing, gain vs R_L, clipping classes), `PROMPT.md` (verbatim from session JSONL), `PLAN.md` (this plan). **No commit/push unless requested** (it's inside the triode repo).

## Verification

Chunk gates: screenshots + printed Vp/Ip traces; `selfcheck()` green; final live playback test with mid-run slider changes (procedure proven twice on this Blender instance).
