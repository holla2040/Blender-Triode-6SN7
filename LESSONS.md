# The Triode, From Electrons to Amplifiers — a Lesson Guide

A guided path through the three simulations in this repository. Followed
in order, it takes you from watching electrons leave a hot cathode to
choosing bias points and predicting distortion character in audio and
guitar amplifier stages — with every claim checkable on a meter or the
in-scene oscilloscope.

**The three laboratories:**

| Sim | Open | What it teaches |
|---|---|---|
| The naked tube | `triode_sim.blend` | electrons, the grid, why plate voltage matters in a triode |
| The RC amplifier | `amplifier/amplifier_sim.blend` | load lines, gain ≈ μ, phase inversion, clipping |
| The self-biased stage | `amplifier-cathode-bias/cathode_bias_amp_sim.blend` | how real stages bias themselves, cathode feedback |

Every sim: open the `.blend`, Text Editor → **Run Script** once, then
N-panel sidebar → the sim's tab → **Run / Pause**. Drag sliders live. Use
**Reset** rather than scrubbing the timeline, and give a fresh build its
first minute to settle.

The companion repository
[Blender-Pentode-6AU6](https://github.com/holla2040/Blender-Pentode-6AU6)
continues this course with the pentode (its own `LESSONS.md` there);
several lessons below set up contrasts that pay off in that repo.

---

## Part I — The tube itself (`triode_sim.blend`)

### Lesson 1 — Current is emission, and emission is temperature

**Set:** grid 0 V, plate 250 V. Drag **Heater temp** from minimum upward.

**Watch:** nothing conducts until the cathode glows. The space-charge
cloud forms first, hugging the cathode; only then does current cross to
the plate. Cool the heater and the current dies no matter how hard the
plate pulls.

**The point:** a tube is a *current valve*, and the current on offer is
set thermionically. The cloud is the reservoir every later lesson draws
from — and it is also a self-regulator: the cloud's own negative charge
throttles emission (space-charge-limited operation), which is why the
current is smooth and repeatable rather than a raw function of cathode
chemistry.

### Lesson 2 — The grid: volts in, milliamps out, no grid power

**Set:** heater 1100 K, plate 250 V. Sweep **Grid** from 0 V down to
−12 V and back, slowly.

**Watch:** plate current follows the grid smoothly down to cutoff, while
the negative grid collects essentially no electrons — watch them turn
back at the grid plane and rejoin the cloud instead of landing on the
wire.

**The point:** a few volts on a currentless electrode controls milliamps
at the plate: that asymmetry is amplification. Note the transfer curve is
*curved* — steeper near 0 V than near cutoff. Hold that thought; the
curvature becomes "tube warmth" in Lesson 9.

### Lesson 3 — The plate has a say: μ, and why triodes are self-limiting

**Set:** grid −4 V. Now sweep **Plate voltage** 100 → 400 V.

**Watch:** unlike a pentode, the plate current follows the plate voltage
strongly. Now find pairs of settings that give the *same* current —
e.g. raise the plate 100 V, then find how much more negative the grid
must go to undo it. That ratio (about 20 for the 6SN7) is **μ**, the
amplification factor.

**The point:** in a triode the plate's field reaches the cathode, so the
plate competes with the grid (at 1/μ strength) for control of the
current. Consequences that shape everything downstream: voltage gain can
never exceed μ (Lesson 5), the tube has a built-in negative feedback
(rising plate voltage on the cold half-cycle pulls current back up —
gentle, linearizing), and its output impedance is low. The pentode repo
exists because engineers wanted to *remove* this competition; here you
learn why it is also a feature.

---

## Part II — Wiring it into an amplifier (`amplifier/amplifier_sim.blend`)

### Lesson 4 — The load line: the resistor does the volts

**Set:** defaults (B+ 300 V, R_L 100k), amplitude 0. Sweep **DC offset**
slowly from −12 V to 0 V.

**Watch:** the meters obey `Vp = B+ − Ip·R_L` at every setting. Cold tube
or hard cutoff: no current, no drop, Vp = B+. Grid near 0: heavy current,
Vp sags low.

**The point:** there is no plate-voltage slider on this bench because the
circuit *solves* it — the operating point is wherever the tube's appetite
and the resistor's supply agree. "Choosing a bias point" (Lesson 7) means
choosing where along that line the stage idles: mid-line for symmetric
swing, high or low for deliberately asymmetric behavior.

### Lesson 5 — Gain is pinned near μ, no matter the resistor

**Set:** DC −4 V, amplitude 1 V. Read the scope's GAIN readout at
R_L = 100k. Slide R_L to 300k. Then 500k.

**Watch:** ~13× barely moves. The same experiment on the pentode bench
(other repo) goes 32× → 97×.

**The point:** the triode's plate feedback (Lesson 3) caps voltage gain
at μ·R_L/(R_L + r_p) < μ — more load resistance mostly just repositions
the operating point. This is the triode's signature: moderate,
*predictable*, distortion-gentle gain. When a design needs one clean,
stable stage (phase splitters, drivers, hi-fi line stages), this is why
a triode gets the job.

### Lesson 6 — Phase inversion, read off the scope

**Set:** DC −4 V, amplitude 1 V, any R_L.

**Watch:** the green input sine and the amber output are mirror images —
grid up, plate down, always.

**The point:** a common-cathode stage inverts: more grid → more current →
more resistor drop → less plate voltage. Trivial here, load-bearing in
real designs — push-pull output stages, feedback loops, and multi-stage
amps all depend on keeping track of who is upside-down.

---

## Part III — Bias: choosing where the stage lives
(`amplifier-cathode-bias/cathode_bias_amp_sim.blend`)

### Lesson 7 — Self-bias: the stage that finds its own operating point

**Set:** defaults (R_k 1.8k, bypass on, DC offset 0). Watch the Vk meter.
Then sweep **R_k** 0.5k → 5k.

**Watch:** with zero applied bias, the cathode lifts itself to
Vk ≈ 3 V — the grounded grid is now ≈ −3 V *relative to the cathode*.
Bigger R_k → more lift → colder bias, automatically.

**The point:** real stages don't ship with bias batteries. The cathode
resistor converts the tube's own current into its bias, and the loop
self-stabilizes: a hotter tube pulls more current → more lift → more
negative Vgk → current pulled back down. Tube-to-tube spread and aging
get absorbed silently. This is the biasing scheme in almost every classic
guitar-amp preamp channel.

### Lesson 8 — The stage that cannot cut itself off

**Set:** self-biased defaults. Now try to kill the tube: drag the DC
offset as negative as the slider allows.

**Watch:** current falls, but as it falls, Vk falls too — the bias
*retreats* — and the tube hangs on. A μ=20 triode with a cathode
resistor will throttle way down but not die.

**The point:** self-bias is negative feedback at DC. The same mechanism
that absorbs manufacturing spread also resists your attempts to slam the
stage shut — which matters for overdrive character (Lesson 9): a
self-biased triode's bias point *slides* under heavy drive (grid current
charges the coupling network, the cathode voltage moves), producing the
dynamic, program-dependent clipping guitarists know as "bias excursion."

### Lesson 9 — The cathode bypass capacitor: gain vs feedback, audibly

**Set:** amplitude 1 V, defaults. Note gain (~15.8×). Uncheck the
**cathode bypass**. Then sweep R_k with the bypass off.

**Watch:** gain drops to ~11.8× (and to ~9× at R_k = 5k) — and the green
trace shows why: the cathode now follows a copy of the signal, eating
part of the grid–cathode drive in real time.

**The point:** unbypassed, the cathode resistor applies series negative
feedback: gain falls, linearity improves, output impedance rises. The
bypass cap is therefore a *voicing component*: fully bypassed = maximum
gain and maximum tube coloration; unbypassed = cleaner, tighter, quieter.
(In real guitar amps a deliberately *small* cap bypasses only treble —
the classic "bright" cathode trick. Our cap is ideal, so you hear the
two endpoints of that spectrum.)

---

## Part IV — Amplitude and distortion: audio amps vs guitar amps

The scope is your distortion meter: clean means the output is a scaled,
inverted copy of the input; distortion is anything you can see diverging.

### Lesson 10 — The triode's distortion signature: asymmetric and gentle

**Sim:** the RC amplifier. **Set:** DC −4 V. Raise amplitude in steps:
1, 2, 3, 4 V.

**Watch:** the two halves of the output diverge long before anything
clips: the half where the grid swings positive (output bottom) is
*stretched*, the cutoff-side half is *compressed* — Lesson 2's curvature
made visible. Keep raising the drive and the extremes arrive: the output
flat-tops at B+ as the grid reaches cutoff, and on the far positive
swings the grid itself starts to conduct (grid current), clamping the
input's peaks.

**The point:** moderate triode overdrive is dominated by **second
harmonic** — the "warm," musically consonant coloration — because the
transfer curve bends one way. Push harder and two *different* hard limits
appear on the two halves (cutoff vs grid conduction), each with its own
sound. This asymmetric, progressive onset is precisely why the
common-cathode triode (12AX7 in the real world, 6SN7 here) is *the*
guitar preamp stage — and also why hi-fi triode stages are kept far below
these levels, where the same curvature is nearly inaudible.

### Lesson 11 — Voicing a stage: the recipe card

Dial these on the self-biased sim and compare by ear… of eye, on the
scope:

**A hi-fi line stage** — R_k for mid-line bias (Vk ≈ 3 V at the
defaults) · bypass cap **in** (or out, trading gain for even lower
distortion) · amplitude a small fraction of the swing · result: clean
~13–16×, gentle second-harmonic residue at worst, no surprises.

**A guitar preamp stage** — self-bias (always) · bypass cap in for
maximum drive into the next stage · run the *input* hot: 3–8 V peaks ·
cold-bias (big R_k) for earlier cutoff-edge break-up, or hot-bias (small
R_k) to lean on grid-conduction squash instead · result: asymmetric
clipping rich in even harmonics at the onset, hardening as both edges
engage — the classic cascaded-triode overdrive voice, one stage of it.

**Then go build the pentode versions:** the companion repo's
[LESSONS.md](https://github.com/holla2040/Blender-Pentode-6AU6/blob/main/LESSONS.md)
picks up exactly here — same benches, two more grids, gain that scales
with the load, a second bias-like control (the screen), and a whole extra
distortion mechanism (screen-sag compression) that triodes simply don't
have.

---

*Simulations are pedagogical: exaggerated geometry, companion-model
circuit solving calibrated live from the particle currents, KVL-true
meters. They demonstrate mechanisms and trends, not SPICE-accurate
numbers — every mechanism above, though, is the real one.*
