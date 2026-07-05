# Plan: Triode Cathode-Bias Amplifier

Extend `../amplifier/` (fixed-bias 6SN7 stage) with **self-bias**: a cathode
resistor R_k between cathode and the common rail, plus a bypass-capacitor
checkbox. Directory `amplifier-cathode-bias/`, module `cathode_bias_amp_sim.py`
(unique module name), prefix `CBAMP_`, handler `amp_cbias_frame_change`
(starts with `amp_` so every sim's `("tri_","pen_","amp_")` strip list
cleans it up).

## Circuit & solve

- `Vk = Ip·R_k`, `Vg(tube) = Vgen − Vk`, `Vp(tube) = B+ − Ip·R_L − Vk` —
  one unknown (Ip) closes everything → single bisection per frame against
  the calibrated emission-aware perveance model (ported from the pentode
  amp: K̂ persists across resets, bootstrap alpha, gating).
- Calibration anchored to the always-computed **DC operating-point solve**
  (pairing averaged current with instantaneous drive Jensen-biases K̂ upward
  under signal — found and fixed during verification).
- Bypassed: signal rides a Vk frozen at the DC solution (full gain).
  Unbypassed: Vk follows the signal → series negative feedback, gain drops,
  and drops further as R_k grows.
- Scope IN trace plots **Vgk** (grid-to-cathode) — the self-found bias is
  visible as the green trace sitting below zero with the generator at 0 DC.
  GAIN readout measured from the generator terminal (stage gain).

## Sliders / UI

Heater, B+ (300), R_L (100k), **R_k 0.1–10k (1.8k, live bands)**, amplitude
(1.0), DC offset (**default 0** — the point of self-bias), **Cathode bypass
capacitor** checkbox, glass. Meter: B+/Vp(gnd), Ip/Vk, Vgk (self-bias), gain.

## Bench additions

COMMON ground bar under the tube; PSU− and generator− rerouted to it;
vertical banded R_k and blue bypass can C_k from the cathode/base down to
the bar (cap + wires hide when unbypassed).

## Verified (selfcheck, all green)

Cold → Vp=B+, Vk=0 · self-bias emerges: Vk≈3.1 V at dc=0 · both KVLs
(plate < 25 V, cathode < 1 V) · self-regulation (Vk rises when bias pushed
hotter; small because loaded gm ≈ gain/R_L) · inverting · gain 15.8×
bypassed / 11.8× unbypassed / 9.3× at R_k=5k (feedback ladder) ·
corr −0.98 · asymmetric overdrive clipping (hard bottom < 40 V, compressed
top > 0.8·B+ — full cutoff unreachable because Vp/μ pulls the tube back
on) · stable at R_L=500k.
