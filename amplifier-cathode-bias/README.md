# Triode Cathode-Bias Amplifier (Blender) — self-biasing 6SN7 stage

> Lessons 7–9 and 11 of the repo's guided course use this bench:
> **[LESSONS.md](../LESSONS.md)**.

The [fixed-bias amplifier](../amplifier/README.md) rebuilt the way real
circuits are actually built: **no bias supply anywhere**. A cathode resistor
does it.

```
  B+ (150–500 V) ──[ R_L 20k–500k ]──► plate
  generator (amplitude + DC offset, default 0) ──► grid
  cathode ──[ R_k 0.1k–10k ]──► COMMON      (+ bypass cap Ck, checkbox)
```

Plate current through R_k lifts the cathode a few volts; the grid (referenced
to common through the generator) then sits *negative of the cathode* by
exactly `Vk = Ip·R_k`. **The stage finds its own operating point** — watch
the scope's green Vgk trace settle below zero with the DC offset slider at 0.

## The lessons

1. **Self-bias emerges**: at defaults the sim settles to Vk ≈ 3.1 V →
   Vgk ≈ −3.1 V, Ip ≈ 1.7 mA, with `Vk = Ip·R_k` holding on the meter.
2. **It self-regulates**: push the DC offset hotter and Vk rises to fight
   you (small on purpose — the 100k plate load eats most of the swing;
   loaded gm ≈ gain/R_L).
3. **The bypass capacitor**: bypassed, the signal rides a frozen cathode —
   gain ≈ 15.8×. Uncheck **Cathode bypass capacitor** and Vk follows the
   signal: series negative feedback, gain drops to ≈ 11.8×, and to ≈ 9.3×
   at R_k = 5k. The green Vgk trace visibly shrinks — feedback eating the
   drive in real time.
4. **Asymmetric clipping**: overdrive (A = 8) slams the output *bottom*
   hard (< 40 V) while the top only compresses (~260 V) — a self-biased
   μ=20 triode can't reach true cutoff, because as Ip falls, Vp rises and
   the Vp/μ term pulls the tube back into conduction.

## Files & running

- `cathode_bias_amp_sim.blend` — open, then Text Editor → Run Script once
- `cathode_bias_amp_sim.py` — or `blender -P cathode_bias_amp_sim.py`
- Sidebar (N) → **Cathode-Bias Amp** tab → Run / Pause, drag sliders live
- `shots/` — rendered stills of the key states

Bench: the tube, scope (green **Vgk** at 5 V/div — note it plots
grid-to-cathode, so the bias offset is visible; amber plate at auto-ranged
60/100 V/div), B+ supply, banded R_L, generator, and the new **COMMON ground
bar** with the banded **R_k** and blue **Ck** hanging off the cathode.
GAIN is measured from the generator terminal (stage gain), so the feedback
effect shows in the number as well as the trace.

Engine notes: same verified electron simulation as the parent project
(~6,000 particles); one unknown (Ip) closes the whole circuit each frame by
bisection against a live-calibrated perveance model. Calibration is anchored
to the DC operating-point solve — pairing the time-averaged electron current
with the instantaneous drive would bias it upward under signal (found the
hard way, documented in PLAN.md). Stateful sim: Reset, don't scrub; one tube
project per Blender session.
