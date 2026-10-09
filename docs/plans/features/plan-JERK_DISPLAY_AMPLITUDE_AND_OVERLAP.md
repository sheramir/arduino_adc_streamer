# Jerk Display — wrong amplitudes on the pressed sensor, and cropped overlaps

## Objective

Fix two reported Jerk Display defects:

1. Pressing the **left sensor of the middle package** produces a large Time Series signal, but the
   Jerk Display shows a *small* lobe at the left sensor, immediately followed by *large* lobes on
   the sensors that were not touched.
2. Pressing near the **top sensor of the bottom package** produces a lobe whose top is cut off flat
   by the facing bottom sensor of the middle package, and the facing sensor's own lobe barely
   appears. Two overlapping fields must **superpose**, not crop each other.

Both are reproducible from the source; the root causes are identified and measured below.

---

## Root causes

### Cause 1 — the normal-force baseline shift injects a DC pedestal into the field (issue 1, dominant)

`NormalForceCalculator.compute()` subtracts a uniform baseline `U` from **all five** sensors and
returns it as `normalized`:

- `data_processing/normal_force_calculator.py:171` — `U = min(outer)` for compression,
  `U = max(outer)` for tension.
- `data_processing/normal_force_calculator.py:105` — `normalized[p] = residual[p] - U`.

`gui/signal_integration_panel.py:3311` and `:3262` feed exactly that `normalized` mapping into
`PressureMapGenerator.generate()`. The baseline shift was designed to stabilise the **centroid**
(see the module docstring), and it does remove a genuine common-mode lift when every outer sensor
is positive. It is destructive as a **field** input the moment the pressed sensor and the centre
sensor carry opposite signs — which is precisely what the bipolar jerk waveform in image 1 shows
(purple `PZT6_L` swings hard negative while the cyan centre trace is small and opposite).

Measured on the real pipeline (`ShearDetector → NormalForceCalculator → PressureMapGenerator`):

| calibrated input (C, L, R, T, B) | normalized fed to the map | package mode | peaks |
| --- | --- | --- | --- |
| `0.10, 1.00, 0, 0, 0` | `0.10, 1.00, 0, 0, 0` | `center-plus-one-outer` | one peak at `(-2.28, 0)`, height **3.00** |
| `0.05, -1.00, 0, 0, 0` | `1.05, **0.00**, 1.00, 1.00, 1.00` | `general-multi-sensor` | peaks at `(1.48, ±1.48)`, height **1.52** |

The second row is the reported bug, exactly:

- `U = min(outer) = -1.00`, so the **pressed sensor is forced to exactly zero** and every untouched
  sensor is lifted to **full amplitude**.
- the package reclassifies to `general-multi-sensor` with two peaks at `(±1.48)` on the side away
  from the press — matching the two red `x` markers and the large blob in image 3, including its
  concave "bite" on the left where `L` was blanked.
- the centroid is broken by the same shift: `x_mm = +0.97` (to the right) for a left-hand press.

No ghost signal is required to trigger this; opposite polarity between `C` and the pressed outer
sensor at the sampled instant is enough. The Jerk Display samples the *latest* integrated value at
~30 Hz from a ~670 Hz bipolar waveform (`gui/signal_integration_panel.py:2820`), so it lands on the
negative half regularly — hence "small lobe, then large lobes".

### Cause 2 — the package-mode switch changes peak amplitude ~3× (issue 1, secondary)

`isolated-outer` and `center-plus-one-outer` inflate the inferred peak up to
`maximum_peak_gain = 3.0` (`_isolated_circular_profile`, `_center_outer_circular_profile`).
`general-multi-sensor` instead uses `_pressure_point_height()`, an inverse-distance weighted average
that stays near the measured sensor value. `is_signal_active()` uses
`DEFAULT_PRESSURE_SIGNAL_ACTIVITY_THRESHOLD = 1e-9` — effectively "any non-zero value".

Measured: adding a 0.03–0.05 ghost on the untouched sensors of a `1.00` left press drops the
rendered peak from **3.00** to **1.04** with no change to the pressed sensor. The same physical
press therefore renders at wildly different amplitude from frame to frame depending on whether a
negligible ghost happened to clear the threshold.

### Cause 3 — the array compositor averages overlapping packages instead of superposing them (issue 2)

`PressureMapArrayGenerator._pair_blend()`
(`data_processing/pressure_map_array_generator.py:622`) computes, wherever both neighbours are
"present", a **convex** combination `w₁·v₁ + w₂·v₂` with `w₁ + w₂ = 1` ramping linearly across the
overlap band. Presence is a hard test, `|v| > 1e-12`
(`PRESSURE_ARRAY_BLEND_EPSILON`, line 440), so a pixel flips discontinuously from "full value" to
"convex-weighted" as soon as the neighbour's field becomes non-zero.

Measured on a vertical cut through `PZT6` (bottom sensor `0.12`) and `PZT3` (top sensor `1.00`),
matching images 4 and 5:

| world y (mm) | PZT6 alone | PZT3 alone | true sum | **current output** |
| --- | --- | --- | --- | --- |
| -1.25 | 0.0000 | 2.3224 | 2.3224 | 2.3224 |
| -1.00 | 0.0000 | 2.8034 | 2.8034 | 2.8034 |
| **-0.75** | 0.0067 | **2.9924** | 2.9991 | **2.1393** |
| -0.50 | 0.0500 | 2.8034 | 2.8534 | 1.8200 |
| 0.00 | 0.2014 | 1.6783 | 1.8797 | 0.9399 |

- The step from `2.8034` to `2.1393` across one 0.25 mm cell, while the true field is still
  *rising*, is the flat crop edge visible in image 5.
- `PZT3`'s actual peak is cut by 29 %, and the crop deepens toward the neighbour (each field is
  ramped to zero at the far edge of the band).
- The bridge between the two packages collapses to the **mean** (`0.94` instead of `1.88`) — the
  facing lobes suppress each other instead of adding.

The residual amplitude difference between the two lobes after this is fixed is physical, not an
artifact: image 4 shows `PZT3_T ≈ 280` counts against `PZT6_B ≈ 35` counts.

---

## Plan

Status: Steps 1, 2, 4 and 5 are implemented. Step 3 is deliberately **not** implemented — see
"Deferred: ghost handling" below.

### Step 1 — separate the field input from the centroid input (done)

The pressure map takes the post-shear residual; `NormalForceCalculator` keeps producing the
numerical force and centroid from its own baseline-shifted values:

- Both generator call sites (`gui/signal_integration_panel.py`, single-package and per-package
  paths) now pass `shear_result.residual`.
- No new `NormalForceResult` field was needed — `residual` is already the same data, so the change
  is confined to the two call sites.
- Force Display inherits the fix — it consumes Jerk shapes through
  `PressureForceDisplayEngine.apply_jerk_shapes()`.

### Step 2 — stop the baseline shift from ever *adding* to a sensor (done)

Even for the centroid readout, `U` only ever removes a common-mode lift now. In
`_baseline_offset()`:

- compression: `U = max(0.0, min(outer))`
- tension: `U = min(0.0, max(outer))`

This preserves the existing behaviour exactly in the case it was designed for (all outer sensors on
the same side of zero) and removes the sign inversion of the centroid for a left-hand press.
`total_force` is algebraically independent of `U`, so the readout is unaffected.

### Step 3 — relative activity gate (not implemented, by decision)

See "Deferred: ghost handling".

### Step 4 — replace convex pair blending with superposition (done)

`_blend_candidates()` and `_pair_blend()` are replaced by `_superpose_candidates()`:

```text
signed(x)    = Σᵢ cᵢ(x) · vᵢ(x)
magnitude(x) = |signed(x)|
```

`cᵢ` is the existing `_support_confidence()` smoothstep — 1.0 inside the Mid Boundary, falling to
0 at the Outer Boundary. It depends only on distance from that package's own centre, never on a
neighbour, so it enforces the support contract without letting any package attenuate another:

- two overlapping packages add at full strength wherever both are inside their Mid Boundary, which
  by construction tiles the whole inter-package region;
- every contribution reaches zero at its own Outer Boundary, so the sum is continuous;
- the old hard `|v| > 1e-12` presence test, which made a pixel jump the instant a neighbour became
  nonzero, is gone.

Two corrections were needed to get here, both found by testing against the live app:

1. **The fade is required, not cosmetic.** A first cut used a plain unweighted sum on the assumption
   that candidate fields already decay to zero at their own boundary. They do not: a
   `general-multi-sensor` field can still be at 82 % of its peak against the Outer Boundary, where
   the strict support mask then clips it to zero. That rendered as hard-edged rectangles.
2. **Magnitude must not accumulate separately.** Superposition produces one field, so the magnitude
   display shows that field's magnitude. Accumulating `Σ |cᵢvᵢ|` instead double-counts every
   package that measured the same press, roughly doubling the reading wherever two supports
   overlap — visible as saturated blocks whose shape is the support-overlap geometry, since
   `PressureMapWidget` renders `magnitude_pressure_grid` directly in Magnitude display mode. It was
   also inconsistent with the single-package path, which already takes `abs` of its own grid
   (`gui/pressure_map_widget.py:500` vs `:511`).

   Trade-off: equal and opposite package fields now cancel to zero instead of reading as the sum of
   their separate magnitudes. That is what superposition means, but it is a deliberate reversal of
   the previous compositor's contract and is easy to revert if a real capture argues against it.

Measured on the same vertical cut (both packages are inside their Mid Boundary here, so the fade is
1.0 and the composite is the exact sum):

| world y (mm) | before | after |
| --- | --- | --- |
| -0.75 | 2.1393 | **2.9991** |
| -0.50 | 1.8200 | **2.8534** |
| 0.00 | 0.9399 | **1.8797** |
| 0.50 | 0.3649 | **0.7527** |
| 1.00 | 0.3364 | **0.3364** |

`compose_force_grids()` adopts the identical rule, so Force Display and Jerk Display now composite
overlapping packages the same way. Removed as dead: `_pair_blend()`,
`PRESSURE_DIAGONAL_REGULARIZATION_SCALE`, and `_PackageCandidate.support_confidence` (support
confidence is now recomputed on demand for debug diagnostics only). `structural_pairs` is
unchanged; `active_overlap_pairs` keeps its previous meaning and is computed by a dedicated
`_active_overlap_pairs()` helper, since the widget cache key, the array-routing check, and existing
tests depend on both. The `pair_confidence_denominator` / `candidate_fallback_denominator` /
`effective_pair_weights` debug entries are replaced by `candidate_fields`.

### Step 5 — tests (done)

- `tests/test_normal_force_calculator.py`: a negative outer under compression (and a positive outer
  under tension) no longer blanks the pressed sensor or lifts the quiet ones; the centroid follows
  the press; a genuine common lift is still removed.
- `tests/test_signal_integration_panel.py`: the values reaching `PressureMapGenerator.generate()`
  are the post-shear residual, and the numerical normal force is still produced.
- `tests/test_pressure_map_array_generator.py`: horizontal, vertical, both diagonals, and the
  three-package case all assert exact signed and magnitude superposition; facing lobes add instead
  of cropping (same-sign neighbours may only increase a pixel); the composite stays continuous
  across a neighbour's support edge; order independence retained.
- `tests/test_pressure_force_display.py`: the opposite-sign magnitude expectation moves from the
  averaged `1.0` to the superposed `2.0`. The staggered-channel-reset test asserted a residual
  `6.9e-18` float; it now asserts the retained package state it was actually describing, because
  the clamp makes that cancellation exact.

Full suite: 622 passed.

---

## Known remaining issue: the near-zero centre plateau

The array fade stops this from clipping into a rectangle, but the underlying package field is still
wrong, and it is worth fixing at the source.

A centre reading of `-0.001` against an outer sensor of `2.0` — 0.05 % — is enough to move a package
out of `isolated-outer`, and the resulting field barely decays across the whole support:

| distance from package centre | 2.0 mm | 3.0 | 3.75 | 4.5 | 5.0 | 5.4 |
| --- | --- | --- | --- | --- | --- | --- |
| `C = 0.0` → isolated-outer | 2.000 | **3.086** | 2.420 | 1.086 | 0.321 | 0.010 |
| `C = -0.001` → multi-sensor | 2.000 | 1.944 | 1.838 | 1.688 | **1.257** | 0.057 |

The isolated mode caps its circular radius at the distance to the support boundary, so it always
fits. The peakless/multi-sensor extension path instead sizes itself from
`_natural_decay_reach(strength)`, which saturates at `maximum_decay_reach_mm` (10 mm) as soon as the
signal exceeds `decay_amplitude_reference` (1.0). Jerk values of ~2 therefore ask for a 10 mm decay
length inside a 5.5 mm support — hence the plateau.

Two existing Pressure Map settings already control this; raising the amplitude reference restores a
decaying field:

| `decay_amplitude_reference` | 2.0 mm | 3.0 | 3.75 | 4.5 | 5.0 |
| --- | --- | --- | --- | --- | --- |
| 1.0 (default) | 2.000 | 1.944 | 1.838 | 1.688 | 1.257 |
| 2.0 | 2.000 | 0.519 | 0.000 | 0.000 | 0.000 |
| 5.0 | 2.000 | 0.000 | 0.000 | 0.000 | 0.000 |

Options, none of them taken here because all three touch scoped-out code:

1. Calibrate `decay_amplitude_reference` / `maximum_decay_reach_mm` to the actual Jerk amplitude
   range (settings only, no code change).
2. Clamp the natural decay reach to the distance from the decay origin to the support boundary, the
   way `isolated-outer` already does — the principled fix, inside `PressureMapGenerator`.
3. The relative activity gate, so a 0.05 % centre reading cannot reclassify the package at all.

## Deferred: ghost handling

Step 3 (a relative activity fraction inside `PressureMapGenerator`) is intentionally **not**
implemented. Ghosting is to be removed upstream instead — in firmware, or by the existing PZT
ghost-removal helper selected on the Time Series tab. That helper already reaches this display:
`prepare_pzt_ghost_block()` is applied during binary ingest before the block is written to
`raw_data_buffer` (`data_processing/binary_processor.py:211`), which is the same buffer the Jerk
integrated values are derived from.

**Consequence to be aware of.** One measured symptom of issue 1 survives this work: the package
mode still switches on the *sign* of the centre ghost, and the peaked modes carry up to a 3× peak
gain that `signed-transition` does not:

| post-shear anchors | mode | \|field\| max |
| --- | --- | --- |
| `L=+1.00, C=+0.05` | center-plus-one-outer, peaked | **2.99** |
| `L=-1.00, C=+0.05` | center-plus-one-outer, signed-transition | **1.00**, no peak |

So a press whose centre ghost flips polarity between frames still renders at ~3× different
amplitude. If ghost removal upstream does not settle this in practice, the remaining options are
the relative activity gate above, or making the peak gain consistent across package modes.

## Open questions

1. **Step 1 scope.** Feeding the raw residual to the map also means a genuine uniform pressure on
   all five sensors now renders as a broad field instead of vanishing. That is believed correct,
   but it is a visible behaviour change worth confirming against a real capture.
2. **Intensity rescaling.** Superposition roughly doubles the field where two packages both respond
   to one press between them, so Max Intensity will likely need retuning. If the bridge reads too
   hot, lower `outer_boundary_reach_mm` rather than reintroducing averaging.
