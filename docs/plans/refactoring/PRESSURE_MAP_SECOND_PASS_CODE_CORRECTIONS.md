# Pressure Map — Second-Pass Algorithm and Blending Corrections

**Purpose:** Correct the remaining artifacts in the current continuity-refactored implementation.  
**Basis:** Current `pressure_map_generator.py`, `pressure_map_array_generator.py`, `pressure_map_geometry.py`, and `pressure_map_widget.py`, plus the supplied array screenshots.  
**Scope:** Calculation, interpolation, decay, package interaction, raster geometry, and diagnostic rendering.  
**Do not solve these defects by blur, auto-scale, or arbitrary parameter changes.**

---

## Observed artifacts that this revision must fix

The screenshots show several repeatable mathematical artifacts:

1. A strong package in the middle of the array often stops near the Mid Boundary, while the same-strength outer package extends much farther.
2. The central package frequently produces a four-, six-, or eight-petal “flower/star” field.
3. Packages with strong signals produce large square, trapezoid, or L-shaped saturated regions that follow support geometry more than sensor geometry.
4. Inactive neighboring packages still alter the shape and reach of an active package.
5. Some weak packages appear as straight vertical or horizontal bars.
6. The field is visibly blocky and important physical positions do not always align with raster samples.
7. Saturated red regions hide whether the underlying field is smooth.
8. A zero Activity Threshold currently causes exact zero values to be classified as active.

The first four issues are algorithmic and have highest priority.

---

# Priority 1 — Fix zero-signal activity classification

## Current defect

The current activity test is equivalent to:

```python
abs(value) >= signal_activity_threshold
```

When the configured threshold is zero:

```text
is_signal_active(0.0) == True
```

This prevents correct selection of:

- `ALL_INACTIVE`;
- `ISOLATED_OUTER`;
- `CENTER_PLUS_ONE_OUTER`;

and can activate every quadrant for an exactly zero package.

## Required change

Use a strict comparison against an effective positive floor:

```python
def is_signal_active(self, value: float) -> bool:
    effective_threshold = max(
        float(self.signal_activity_threshold),
        PRESSURE_NUMERIC_EPSILON,
    )
    return abs(float(value)) > effective_threshold
```

Normalize exact and sub-threshold inputs to zero after classification.

Also validate that all input signals are finite.

## Required behavior

- An all-zero vector must always select `ALL_INACTIVE`.
- A zero user threshold must mean “no user noise rejection,” not “zero is active.”
- Tiny floating-point residue below `PRESSURE_NUMERIC_EPSILON` must not create a field.

---

# Priority 2 — Make array blending aware of package activity

## Root cause of the middle-package reach problem

The current array code creates pair blends from geometric support overlap even when one package has no active pressure field.

For a central active package next to an inactive package, the inactive package contributes a zero candidate, so the direct-neighbor pair blend becomes approximately:

```text
pair = geometric_weight_active * active_candidate
```

This applies a second geometric attenuation on top of the package’s natural decay.

An edge package extending away from the array has no neighbor on that side and therefore keeps its full candidate. This explains why outside packages appear to reach farther than the middle package.

## Required data model

Add package-level activity information to `PressureFieldModel` and `PressureMapResult`:

```python
raw_sensor_values: tuple[tuple[str, float], ...]
package_activity_confidence: float
```

Do not derive activity confidence from rendered pixels or the display alpha floor.

## Required activity confidence

Calculate a scalar from the raw package sensor vector:

```text
raw_strength = max(abs(C), abs(L), abs(R), abs(T), abs(B))
```

Use a smooth transition around the signal activity threshold:

```python
activity_low = max(signal_activity_threshold, PRESSURE_NUMERIC_EPSILON)
activity_high = max(
    activity_low * 2.0,
    activity_low + 0.02 * decay_amplitude_reference,
)

if raw_strength <= activity_low:
    activity_confidence = 0.0
elif raw_strength >= activity_high:
    activity_confidence = 1.0
else:
    t = (raw_strength - activity_low) / (activity_high - activity_low)
    activity_confidence = 3*t*t - 2*t*t*t
```

Store the value with the pressure result.

An exactly inactive package must have confidence zero.

## `_PackageCandidate` changes

Add:

```python
activity_confidence: float
```

Candidate fallback weight:

```python
candidate_weight = (
    candidate.support_confidence
    * candidate.activity_confidence
)
```

## Activity-normalized pair blend

Keep the existing geometric pair weights:

```text
g_first
g_second
```

Modify them using package activity:

```python
effective_first = g_first * first.activity_confidence
effective_second = g_second * second.activity_confidence
normalizer = effective_first + effective_second
```

Where `normalizer > epsilon`:

```python
pair_value = (
    effective_first * first.values
    + effective_second * second.values
) / normalizer
```

Required limiting behavior:

```text
first active, second inactive -> first.values
first inactive, second active -> second.values
both active -> original geometric blend
both inactive -> invalid/zero pair
```

## Pair aggregation confidence

Use:

```python
pair_confidence = (
    first.support_confidence
    * second.support_confidence
    * min(first.activity_confidence, second.activity_confidence)
)
```

or an equivalent smooth symmetric function that is:

- zero if either package is inactive;
- one when both are fully active;
- continuous between those states.

Do not use support confidence alone.

## Fallback behavior

Where no valid active pair exists, use the activity-weighted candidate fallback:

```python
combined = (
    sum(candidate_weight_i * candidate_value_i)
    / sum(candidate_weight_i)
)
```

This must reproduce the active package candidate exactly when all neighboring packages are inactive.

## Mandatory invariant

For any layout:

```text
one active package + any number of all-zero packages
```

the array result over the active package’s support must equal the standalone active candidate at the same physical coordinates, within numerical tolerance.

---

# Priority 3 — Replace extrapolated quadrant-corner values with a bounded estimate

## Current defect

The current unmeasured quadrant corner is:

```text
corner = horizontal + vertical - center
```

This is planar extrapolation, not interpolation.

It can:

- exceed every measured sensor;
- reverse sign even when all measured sensors have the same sign;
- create artificial high-valued package corners;
- generate the four-petal and star-shaped maps visible in the screenshots.

Example:

```text
C = 0
H = 1
V = 1
current corner = 2
```

The strongest value is invented at an unmeasured corner.

## Required corner estimator

Use a convex, bounded estimate. The recommended estimate is inverse-square-distance interpolation at the core corner.

Distances from the core corner are:

```text
distance to H = sensor_spacing
distance to V = sensor_spacing
distance to C = sqrt(2) * sensor_spacing
```

Therefore the relative inverse-square weights are:

```text
H: 1
V: 1
C: 0.5
```

Use:

```python
corner_value = (
    horizontal_value
    + vertical_value
    + 0.5 * center_value
) / 2.5
```

This guarantees:

```text
min(C, H, V) <= corner_value <= max(C, H, V)
```

and preserves a constant field:

```text
C = H = V = k -> corner = k
```

## Requirements

- Use the bounded corner for peakless, peaked, and signed-transition triangulations.
- Do not permit an unmeasured corner to exceed the convex hull of measured anchor values.
- Do not clamp the final signed surface after interpolation.
- Mixed-sign anchors may cross zero naturally.

## Tests

Add:

```text
C=0, H=1, V=1       -> corner=0.8, not 2
C=1, H=0, V=0       -> corner=0.2, not -1
C=1, H=-1, V=0      -> bounded signed corner
C=H=V=k             -> corner=k
```

---

# Priority 4 — Use a local decay origin for each quadrant

## Current defect

All general multi-sensor fields use:

```python
decay_origin = (0.0, 0.0)
```

even when a quadrant has a strong off-center inferred peak.

This causes:

- rays from unrelated quadrants to share the package center;
- star-like extensions;
- unnatural sectors aligned with quadrant corners;
- incorrect reach for localized pressure.

## Required model change

Add a decay origin to every `PressureQuadrantPlane` or introduce an immutable `PressureQuadrantModel`:

```python
decay_origin: tuple[float, float]
```

Use:

### Peaked quadrant

```text
decay_origin = inferred peak point
```

### Peakless or signed-transition quadrant

Use the magnitude-weighted centroid of the measured quadrant anchors:

```python
positions = [C_position, H_position, V_position]
weights = [abs(C), abs(H), abs(V)]

origin = sum(weight_i * position_i) / sum(weight_i)
```

Fallback to package center when the weight sum is zero.

Clamp the result to the quadrant core.

## Extension evaluation

For each pixel outside the core:

1. Assign it to its physical quadrant by the signs of X and Y.
2. Select that quadrant’s model and decay origin.
3. Intersect the ray from that local origin with:
   - the core square;
   - the Outer Boundary square.
4. Evaluate the anchor using that quadrant model.
5. Apply the outward decay for that quadrant only.

Shared X/Y axes must use explicit axis models rather than arbitrary quadrant ownership.

Do not use one global origin for all general-field extension pixels.

---

# Priority 5 — Stop rescaling the entire natural fade to the square boundary

## Current defect

The current extension uses:

```text
effective_reach = min(natural_reach, available_distance_to_outer_square)
value = anchor * smoothstep(outward_distance / effective_reach)
```

When `natural_reach` exceeds the available distance, the entire fade is remapped to end exactly at the square Outer Boundary.

For strong signals, this makes most contours follow the square support and produces the large square, trapezoid, and L-shaped regions visible in the screenshots.

## Required decay composition

Preserve the natural decay distance independently from the boundary.

### Natural factor

```python
natural_factor = smoothstep_fade(
    outward_distance,
    natural_reach,
)
```

Do not shorten `natural_reach` merely because the boundary is closer.

### Boundary guard

The Outer Boundary remains a hard maximum support. Apply a separate guard only in a thin terminal zone when the natural field would otherwise remain nonzero at the boundary.

```text
available_distance = distance(anchor, outer_boundary_on_same_ray)
remaining_distance = available_distance - outward_distance
```

Choose a physical terminal guard width:

```python
guard_width = min(
    available_distance,
    max(
        0.20 * available_distance,
        geometry_epsilon,
    ),
)
```

Then:

```python
guard_start = available_distance - guard_width
boundary_factor = smoothstep_fade(
    max(0, outward_distance - guard_start),
    guard_width,
)
```

Final extension:

```python
value = anchor_value * natural_factor * boundary_factor
```

The boundary factor must be exactly 1 before the terminal guard zone and exactly 0 on/outside the Outer Boundary.

## Important distinction

This is not the previous double-decay defect:

- the natural factor models pressure spread;
- the boundary guard only enforces maximum support in the final outer strip;
- the natural field is not globally rescaled to match the square.

## Expected result

- Natural contours remain primarily controlled by pressure origin and natural reach.
- Only the weak terminal region follows the square Outer Boundary.
- Strong packages no longer become large uniformly square fields merely because their natural reach exceeds support.

---

# Priority 6 — Keep package support confidence separate from pressure decay

The current support confidence is useful for overlap participation:

```text
1 inside Mid Boundary
smooth fade from Mid to Outer Boundary
0 on/outside Outer Boundary
```

Keep this field for blending ownership only.

Do not multiply the package pressure candidate by support confidence before pair blending if the package candidate already includes its own physical decay and terminal support guard.

The pressure candidate and support confidence have different meanings:

```text
candidate field      = inferred signed pressure intensity
support confidence   = package ownership in overlap blending
```

Add tests proving that changing overlap layout does not change the standalone package candidate.

---

# Priority 7 — Correct multi-package pair aggregation

After activity-aware pairs are added, keep the requested pair semantics:

- direct neighbors: linear pair weighting;
- diagonal neighbors: regularized area-ratio weighting;
- three or more active packages: confidence-weighted average of valid pair blends.

## Required formula

For valid active pairs:

```python
pair_numerator += pair_confidence * pair_value
pair_denominator += pair_confidence
```

Then:

```python
pair_result = pair_numerator / pair_denominator
```

Use the candidate fallback only where no valid active pair has meaningful confidence.

## Do not

- branch on integer contributor count;
- count inactive packages as pair contributors;
- allow a zero package to halve an active package at the midpoint;
- let the number of configured packages change the amplitude of a single active package.

---

# Priority 8 — Preserve bounded diagonal regularization

The current smooth transition between area-ratio weights and inverse-distance weights is directionally correct.

Retain it, but apply package activity before final pair normalization.

For every diagonal pair verify:

```text
weight_first + weight_second = 1
weights are finite
zero-activity package receives zero effective weight
weights vary continuously around formerly singular corners
```

---

# Priority 9 — Build a geometry-aligned raster

## Current defect

With `3 px/mm`:

```text
sensor spacing        = 2.00 mm  -> 6 samples
package center spacing= 7.50 mm  -> 22.5 samples
Mid Boundary          = 3.75 mm  -> 11.25 samples
Outer Boundary        = 5.50 mm  -> 16.5 samples
```

Important package centers and boundaries fall between raster samples.

This increases asymmetry, blockiness, and apparent cropping.

## Required grid algorithm

Treat `pixels_per_mm` as a minimum requested density.

Compute a geometry quantum from the configurable physical values:

```text
sensor_spacing_mm
package_center_spacing_mm
outer_boundary_reach_mm
near_outer_peak_offset_mm
mid_boundary_half_width_mm
outer_boundary_half_width_mm
```

Use decimal/rational arithmetic with a bounded precision, for example 0.001 mm.

Recommended implementation:

1. Convert each geometry value to integer micrometers.
2. Compute their integer GCD.
3. Convert the GCD back to `geometry_quantum_mm`.
4. Calculate:

```python
requested_cell_size = 1.0 / pixels_per_mm
subdivisions = max(
    1,
    ceil(geometry_quantum_mm / requested_cell_size),
)
actual_cell_size = geometry_quantum_mm / subdivisions
```

5. Build local and array coordinates as integer multiples of `actual_cell_size`.
6. Anchor the world grid so every package center is on a grid sample.

## Safety

- Cap total pixel count.
- If arbitrary configured values produce an impractically tiny quantum, fall back to a rational approximation and emit a clear validation warning.
- Store the actual density and cell size in result metadata.

## Default geometry behavior

For the current default geometry, the quantum is `0.25 mm`.

A requested `3 px/mm` therefore becomes an actual aligned density of `4 px/mm`, placing all key default coordinates exactly on samples.

---

# Priority 10 — Separate calculation threshold, blend activity, and display alpha

These are three distinct concepts:

```text
signal_activity_threshold
package_activity_confidence
display_floor_low/high
```

Do not derive the display floor from the shear threshold.

Do not use display alpha to decide whether a package participates in blending.

Do not use package activity confidence to alter the local pressure candidate.

The panel must configure these paths independently.

---

# Priority 11 — Fix saturation diagnostics

## Current issue

The array image calculates saturation from the combined array grid, but the package readout can overwrite it using concatenated individual package grids.

The displayed `SAT` value may therefore not describe the visible image.

## Required change

When displaying a combined array:

```text
SAT percentage = saturation of array_result.pressure_grid
```

Do not overwrite it afterward with per-package values.

When displaying separate packages, use the concatenated package grids.

## Debugging support

Add optional display/debug overlays:

- contour at `max_intensity`;
- numeric backend maximum;
- saturated-pixel mask.

Keep fixed Max Intensity as the production behavior. Do not add automatic scaling as part of this correction.

---

# Priority 12 — Add diagnostic fields required to verify the corrections

When debug mode is enabled, expose:

```text
raw sensor values
thresholded sensor values
package mode
package activity confidence
quadrant corner values
quadrant decay origins
core surface
natural decay factor
boundary guard factor
final package candidate
support confidence per package
effective direct/diagonal pair weights
pair confidence denominator
candidate fallback denominator
final array field
saturation mask
```

The diagnostics must be optional and absent from the normal live path.

---

# Priority 13 — Remove or correct stale compatibility code

After tests pass:

- remove obsolete `decay_rate` and `decay_ref_distance_mm` from active calculations if they are only migration fields;
- mark retained compatibility fields explicitly;
- ensure `evaluate_pressure_map_result_at()` uses only the immutable field model;
- ensure local and array generators share the same `PressureMapGeometry`;
- remove any code path that reconstructs a generator manually;
- update comments and docstrings to match the new decay composition.

---

# Mandatory regression tests

## 1. Zero threshold

```text
threshold = 0
signals = all zero
```

Expected:

```text
package mode = ALL_INACTIVE
pressure field = exactly zero
activity confidence = 0
```

## 2. Translation invariance with inactive neighbors

Create the same active package signal vector in:

- the center position with four zero neighbors;
- an outer position with four zero neighbors;
- standalone mode.

After translating coordinates, all three fields must be equal.

This is the primary regression test for the reported reach problem.

## 3. Inactive neighbor pair

At every overlap coordinate:

```text
active candidate A
inactive package B
```

Expected pair output:

```text
pair = A
```

not:

```text
pair = geometric_weight_A * A
```

## 4. Both active pair

With both activity confidences equal to 1, pair output must exactly match the original direct/diagonal geometric formula.

## 5. Activity transition

As package B raw strength approaches zero, the pair result must converge continuously to package A.

## 6. Bounded corner

Verify the corner is always within the minimum and maximum of C/H/V.

## 7. Four-outer-sensor case

For:

```text
C = 0
L = R = T = B = equal positive value
```

Expected:

- no corner exceeds the outer sensor magnitude by extrapolation;
- no artificial red corner petals caused by `H + V - C`;
- rotational symmetry;
- center remains the measured value.

A ring-like or four-sided distribution may remain if the measured center is truly zero, but it must not contain invented corner maxima.

## 8. Center-only case

Expected:

- rotationally symmetric central field;
- no square plateau;
- no star rays;
- natural fade mostly independent of the Outer Boundary until the terminal guard.

## 9. Localized quadrant case

A strong C/H/V quadrant with an off-center peak must extend using that local peak origin, not the package center.

## 10. Boundary behavior

For natural reach smaller than available distance:

```text
field reaches zero before Outer Boundary
boundary guard has no visible effect
```

For natural reach larger than available distance:

```text
natural factor remains unrescaled
boundary guard acts only in terminal strip
field is exactly zero on Outer Boundary
```

## 11. Grid alignment

Verify that all package centers, sensor coordinates, Mid Boundaries, and Outer Boundaries lie on raster samples for the default geometry.

## 12. Grid-density invariance

Compare requested densities that resolve to different aligned grids. Sample at common physical coordinates and verify consistent field values.

## 13. Saturation readout

Combined-array SAT must equal the saturation percentage calculated from the displayed combined array grid.

---

# Acceptance criteria

The correction is complete only when:

1. A central active package with inactive neighbors reaches exactly as far as the same package placed on the array edge.
2. Inactive packages do not attenuate, crop, or reshape an active package.
3. Exact zero signals remain inactive even when Activity Threshold is configured as zero.
4. Unmeasured core corners never exceed or reverse beyond measured anchor bounds.
5. The flower/star artifacts caused by extrapolated quadrant corners are removed.
6. General multi-sensor decay uses local quadrant origins.
7. Strong fields retain natural contours and only conform to the square support in a weak terminal guard region.
8. Pair blending preserves the requested geometric formula when both packages are active.
9. Key physical coordinates align to grid samples.
10. The displayed SAT value describes the visible array.
11. All mandatory regression tests pass.

---

# Required files to update

At minimum:

- `pressure_map_generator.py`
- `pressure_map_array_generator.py`
- `pressure_map_geometry.py`
- `pressure_map_widget.py`
- `signal_integration_panel.py`
- pressure-map constants/settings migration
- pressure-map unit and integration tests

---

# Delivery report

Provide a concise implementation report containing:

- files changed;
- zero-threshold correction;
- package activity-confidence formula;
- pair-blending formula;
- bounded corner formula;
- per-quadrant decay-origin method;
- natural decay and boundary-guard formulas;
- aligned-grid method and actual density behavior;
- saturation diagnostic correction;
- regression tests added;
- compatibility fields retained or removed;
- measured live-refresh performance.
