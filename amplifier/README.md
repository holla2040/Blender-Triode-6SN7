# Triode Common-Cathode Amplifier (Blender)

The [triode simulation](../README.md) wired into a working **resistance-loaded,
grounded-cathode amplifier stage** — the classic first tube amplifier:

```
  B+ (150–500 V) ──[ R_L 20k–500k ]──► plate
  sine generator (amplitude + DC offset) ──► grid
  supply − and generator − ──► cathode (common)
```

There is **no plate-voltage slider** anymore. Each frame the plate finds
itself on the **load line**: `Vp = B+ − Ip·R_L`, solved self-consistently
against the tube's own electron current. Everything an amplifier does —
operating point, gain, phase inversion, cutoff and saturation clipping —
*emerges* from the same electron physics as the bare-tube demo.

## Files

- `amplifier_sim.blend` — ready to open (script embedded as a text block)
- `amplifier_sim.py`    — standalone builder: `blender -P amplifier_sim.py`
- `shots/`              — rendered stills of the key operating points

## Run it

1. Open `amplifier_sim.blend` (or `blender -P amplifier_sim.py`).
2. If opening the .blend: Text Editor → `amplifier_sim.py` → **Run Script**
   once (re-registers the physics handler Blender doesn't persist).
3. 3D view → **N** → **Amplifier** tab → **Run / Pause**, drag sliders live.

## Controls

| Control | Range | What it teaches |
|---|---|---|
| Heater temp | 300–1300 K | Cold tube → no current → Vp sits at B+ regardless of everything else. |
| B+ supply | 150–500 V | Moves the top of the load line; watch the operating point and headroom follow. |
| Plate resistor | 20k–500k | Load-line slope. Bigger R_L → more gain, lower operating current. The resistor's **color bands update live** to the slider value. |
| Signal amplitude | 0–8 Vpk | Small = clean amplification; large = clipping both ways. |
| Grid bias / DC offset | −15…+5 V | The operating point. −4 V ≈ class-A center; −12 V ≈ beyond cutoff (class-C-ish); 0 V+ → grid current. |

The **oscilloscope** shows the green input (8 V/div) and the amber output
(100 V/div, centered on B+/2) with the measured **GAIN** readout on the
bezel — note the output is **inverted** (common-cathode stage). The meter
under the tube shows B+, Vp, Ip, Vg, and gain, all KVL-consistent:
`B+ − Vp = Ip·R_L` always checks out.

## Experiments for students

1. **Dead tube**: heater to 300 K → Ip=0, Vp=B+. No emission, no amplifier.
2. **Find the operating point**: defaults (300 V, 100k, −4 V) → watch Vp
   glide onto ~140 V as the electron stream builds: the load line solving
   itself. Verify Ohm's law from the meter numbers.
3. **Gain**: amplitude 1 V → output ~13× bigger, inverted. Confirm with the
   graticule: input ~¼ div, output ~1.3 div at the posted V/div.
4. **Bias classes**: drag DC offset to −12 V (output only on positive input
   peaks) then toward 0 V (grid-current sparkle on the wires; top of the
   swing compresses).
5. **Clipping**: amplitude 8 V → trapezoid: flat top where the tube cuts
   off (Vp → B+), flat bottom where it bottoms out.
6. **Load line**: flip R_L 20k ↔ 470k at fixed drive. Gain, headroom, and
   operating current all move; the color bands follow.

## How the circuit is solved (honest summary)

The electron engine is the verified triode simulation (numpy in a
`frame_change_pre` handler, dupli-vert instanced electrons, exaggerated
geometry, μ=20, meter scaled to real ~1–2 mA currents so V=I·R works with
20k–500k). The circuit layer per frame:

- `Vg(t) = DC + A·sin(2πft)`, f = 0.25 Hz (a code constant for now).
- The load line is solved **algebraically** by bisection against a perveance
  model `Ip = K·(Vg + Vp/μ − Vsc)^1.5`, where **K is continuously calibrated
  from the measured electron current** (slow EMA). An earlier relaxation
  servo rang against the ~15-frame electron transit delay — a real circuit
  settles algebraically, so the sim does too; the calibration keeps the
  solved point honest against the particles.
- The displayed Ip is the resistor current `(B+ − Vp)/R_L`, so the meter
  always satisfies KVL exactly.
- `selfcheck()` asserts: cold→Vp=B+; load-line convergence; inverting
  monotonicity vs bias; gain 4–22× with negative in/out correlation;
  stability at 500k; cutoff clipping at 8 Vpk.

Same caveats as the tube demos: stateful sim (Reset, don't scrub), run one
tube project per Blender session.
