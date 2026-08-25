# Pressure Map Continuity and Blending Refactor — Coding Agent Instructions

**Status:** Required implementation revision  
**Scope:** Pressure-map calculation, package-field evaluation, array blending, and heatmap rendering  
**Priority:** Correct mathematical discontinuities before changing tuning values or increasing resolution

## Objective

Refactor the current Pressure Map implementation so that:

- every active sensor value is reconstructed exactly at its physical sensor coordinate;
- pressure surfaces are continuous across package axes, quadrant boundaries, sensor-square boundaries, package overlaps, and Outer Boundaries;
- signed signals cross through zero continuously instead of creating missing quadrants or hard holes;
- natural decay may reach zero before the Outer Boundary, but never extends past it;
- no pressure field is cropped by binary masks except that it is exactly zero outside its maximum support;
- array blending does not change formulas abruptly when the number of overlapping packages changes;
- display mapping does not introduce a second hard cutoff that hides a mathematically smooth decay.

The screenshots show rectangular plateaus, straight cuts at sensor coordinates, duplicated two-lobe fields, L-shaped holes, diagonal wedges, and rectangular bridges between packages. These match hard branches and incomplete coverage in the current code. Do not try to hide these defects with blur, higher `pixels_per_mm`, or palette changes.

---

# Required invariants

These invariants apply to all revisions below.

1. **Exact sensor anchors**

   For every package result:

   ```text
   field(0, 0) = C
   field(-sensor_spacing_mm, 0) = L
   field(+sensor_spacing_mm, 0) = R
   field(0, +sensor_spacing_mm) = T
   field(0, -sensor_spacing_mm) = B
   ```

   Values below the signal-activity threshold may first be normalized to exactly zero. After that normalization, the field must reproduce those thresholded values exactly.

2. **Signed backend**

   The backend field remains signed. Magnitude rendering is applied only by the widget after package generation and array blending.

3. **No hard internal masks**

   Do not use binary `np.where(...)` branches that change a nonzero field directly to zero on an internal axis, at the sensor square, at a quadrant boundary, or when contributor count changes.

4. **One compact-support decay**

   A field is extended from a continuous inner surface using one compact-support decay. Do not multiply independent X, Y, axial, lateral, natural, and terminal decay factors that describe the same outward attenuation.

5. **Maximum support**

   The Outer Boundary is a maximum support limit. The field may naturally become zero earlier. It must be zero on and outside its effective end.

6. **Grid-density invariance**

   Changing `pixels_per_mm` may change raster resolution, but it must not materially move peaks, sensor anchors, seams, decay endpoints, or overlap transitions.

---

# Priority 1 — Replace package-local hard cuts with a continuous package-level field

## Current defects to remove

Remove the behavior created by patterns equivalent to:

```python
values = np.where(local_axis >= 0.0, values, 0.0)
```

and:

```python
contact_region = (
    (abs(x) <= sensor_spacing_mm)
    & (abs(y) <= sensor_spacing_mm)
)
factor = np.where(contact_region, 1.0, radial_factor)
```

These operations create the straight horizontal and vertical cuts visible in the screenshots.

Also stop creating a single-axis response independently in two neighboring quadrants. That produces duplicated rectangular lobes and an axis seam.

## Required architecture

Classify the package once, before quadrant evaluation, and select a package-level model:

```text
ALL_INACTIVE
ISOLATED_OUTER
CENTER_PLUS_ONE_OUTER
GENERAL_MULTI_SENSOR
```

Suggested classification:

```python
active_outer = [p for p in (L, R, T, B) if is_signal_active(signal[p])]
center_active = is_signal_active(signal[C])

if not center_active and not active_outer:
    mode = ALL_INACTIVE
elif not center_active and len(active_outer) == 1:
    mode = ISOLATED_OUTER
elif center_active and len(active_outer) == 1:
    mode = CENTER_PLUS_ONE_OUTER
else:
    mode = GENERAL_MULTI_SENSOR
```

Do not encode `CENTER_PLUS_ONE_OUTER` separately in two quadrant objects. Evaluate it once over the package grid.

## Required code changes

Refactor `PressureMapGenerator.generate()` so it builds one immutable package field model and evaluates that model on the local grid.

Recommended structure:

```python
model = self._build_package_field_model(signals)
pressure_grid = model.evaluate(
    self.x_grid_mm,
    self.y_grid_mm,
    support_bounds=self.support_bounds_mm,
)
```

The same model must later be reused by array evaluation.

Add an immutable model/result representation containing:

- thresholded signed sensor values;
- package mode;
- geometry;
- inferred peaks and peak heights;
- complete core interpolation data;
- decay configuration;
- support bounds.

Do not make quadrant iteration order part of the mathematical result.

---

# Priority 2 — Implement a continuous core-to-Outer-Boundary extension

## Problem

The current implementation evaluates an inner surface and then suddenly enables radial decay outside the `±sensor_spacing_mm` square. The decay factor is already below 1 at that location, so the field jumps.

## Required algorithm

Separate each package field into:

1. **Core surface** defined over the sensor square:

   ```text
   -sensor_spacing_mm <= x <= +sensor_spacing_mm
   -sensor_spacing_mm <= y <= +sensor_spacing_mm
   ```

2. **Outward extension** from the core-square boundary to the Outer Boundary.

For any pixel outside the core square:

1. Select the field origin `O` appropriate for the local model:
   - inferred peak for a peaked model;
   - center or another explicit contact origin for a peakless model.
2. Form the ray from `O` through pixel `P`.
3. Find `A`, the first intersection of that ray with the core square when traveling outward from `O`.
4. Find `B`, the intersection of the same ray with the package Outer Boundary square.
5. Evaluate the signed core surface at `A`:

   ```text
   anchor_value = core(A)
   ```

6. Compute:

   ```text
   outward_distance = distance(A, P)
   available_distance = distance(A, B)
   natural_reach = natural_decay_reach(abs(anchor_value) or model_strength)
   effective_reach = min(natural_reach, available_distance)
   ```

7. Apply one smoothstep compact-support factor:

   ```text
   t = clamp(outward_distance / effective_reach, 0, 1)
   fade = 1 - 3*t^2 + 2*t^3
   value(P) = anchor_value * fade
   ```

8. Return zero when:

   ```text
   outward_distance >= effective_reach
   ```

## Important continuity requirement

At the core boundary:

```text
outward_distance = 0
fade = 1
value(outside at A) = core(A)
```

Therefore, the field is value-continuous across the core boundary.

Do not:

- calculate radial decay from the peak and then disable it inside a square;
- multiply this fade by a second terminal envelope;
- multiply separate X and Y fades;
- use a binary `contact_region`.

## Geometry helpers to add

Implement tested pure helpers:

```python
ray_square_exit_distance(
    origin_x,
    origin_y,
    direction_x,
    direction_y,
    square_bounds,
) -> float
```

```python
ray_square_intersection_point(
    origin,
    target,
    square_bounds,
) -> tuple[float, float]
```

```python
smoothstep_fade(
    distance,
    reach,
) -> ndarray
```

Handle zero-length direction vectors and origins on an edge without NaN or infinity.

---

# Priority 3 — Replace single-axis half-fields with one continuous 2D lobe

## Problem

The current single-axis implementation:

- is generated independently in adjacent quadrants;
- sets the opposite half-plane to exactly zero;
- uses very narrow Gaussian widths that may occupy only one or two grid cells;
- does not provide a smooth field around the center;
- creates the repeated two-block appearance visible in the screenshots.

## Required package-level algorithm

For `CENTER_PLUS_ONE_OUTER`, define local coordinates:

```text
u = signed coordinate along the active sensor axis
v = perpendicular coordinate
```

Orient `u > 0` toward the active outer sensor.

Known longitudinal anchors:

```text
u = 0                         -> center_value
u = inferred_peak_position    -> peak_value
u = sensor_spacing_mm         -> outer_sensor_value
```

Use exact piecewise interpolation for `0 <= u <= sensor_spacing_mm`:

```text
center_value -> peak_value -> outer_sensor_value
```

For `u < 0`, do not set the field to zero immediately. Extend continuously from the center toward the opposite core edge:

```text
u = 0                  -> center_value
u = -sensor_spacing_mm -> 0 or the value required by another active anchor
```

Use smooth interpolation, not a hard branch.

For `u > sensor_spacing_mm`, the package-wide core-to-boundary extension handles outward decay. Do not apply another longitudinal natural decay inside the single-axis evaluator.

## Lateral profile

Replace the unbounded Gaussian with a compact, smooth lateral profile so inactive perpendicular sensors can remain exactly zero.

Recommended form:

```text
q = clamp(abs(v) / width(u), 0, 1)
lateral_factor = 1 - 3*q^2 + 2*q^3
lateral_factor = 0 for abs(v) >= width(u)
```

Make `width(u)` continuous:

```text
center_width -> peak_width -> outer_width
```

Enforce a numerical minimum:

```text
width(u) >= 3 * max(cell_size_x_mm, cell_size_y_mm)
```

This is an algorithmic anti-aliasing constraint, not a substitute for calibration.

## Anchor tests

Verify exact values at:

- center sensor;
- active outer sensor;
- all inactive perpendicular outer sensors;
- inferred peak.

Verify there is no jump at `u = 0`, `u = peak`, or `u = sensor_spacing_mm`.

---

# Priority 4 — Support signed interpolation and continuous zero crossings

## Current defects

Remove same-sign-only quadrant activation:

```python
all(sign(value) == reference_sign ...)
```

Remove sign clamping:

```python
np.maximum(0.0, values)
np.minimum(0.0, values)
```

These operations create missing quadrants, notches, and L-shaped holes when neighboring sensors have different signs.

## Required behavior

A quadrant is eligible for interpolation whenever at least one of its three sensor anchors is active after thresholding.

For mixed-sign anchors:

- do not infer a same-sign pressure peak;
- build a signed peakless core surface;
- allow the interpolated surface to cross smoothly through zero;
- preserve all signed sensor anchors.

For same-sign anchors:

- peak inference may still be used;
- peak height must retain the common sign;
- the complete signed surface is still not clamped afterward.

Suggested mode logic per quadrant:

```python
active_values = [C, H, V values above threshold]

if no active_values:
    quadrant inactive
elif active_values contain both positive and negative:
    mode = SIGNED_TRANSITION
elif inferred_peak is valid:
    mode = PEAKED
else:
    mode = PEAKLESS
```

Replace `_clamp_values()` with only a numerical cleanup:

```python
values[abs(values) < tiny_numeric_epsilon] = 0
```

The cleanup epsilon must be much smaller than the signal-activity threshold and must not change meaningful values.

Magnitude mode must execute:

```python
display_grid = abs(signed_backend_grid)
```

only after package generation and array blending.

---

# Priority 5 — Replace incomplete triangulation and eliminate fallback wedges

## Problem

The current four triangles do not cover the full quadrant square. Unmatched pixels are evaluated with another plane, producing diagonal wedges and visible slope/value seams.

## Required core triangulation

Restrict piecewise-linear triangulation to the core sensor square.

For each quadrant, use the signed local vertices:

```text
C = package center
H = horizontal outer sensor
V = vertical outer sensor
K = core-square corner
```

Derive the corner value from the base signed plane passing through C, H, and V:

```text
K_value = H_value + V_value - C_value
```

This is equivalent to evaluating the three-anchor plane at the quadrant corner and preserves the unpeaked planar case.

### Peakless or signed-transition quadrant

Use a complete deterministic split:

```text
triangle 1: C, H, K
triangle 2: C, K, V
```

### Peaked quadrant

When a valid inferred peak `P` lies inside the quadrant core square, use a complete fan:

```text
P, C, H
P, H, K
P, K, V
P, V, C
```

This fan must cover the complete quadrant exactly.

## Degenerate peaks

If `P` is on or within geometry tolerance of an edge or vertex:

- use an edge-aware deterministic split; or
- fall back to the complete peakless triangulation.

Do not drop degenerate triangles and then fill uncovered pixels with a nearest or base-plane fallback.

## Evaluation rules

- Use barycentric or signed-area membership.
- Assign every interior pixel to exactly one triangle.
- Define a deterministic shared-edge rule.
- Add a debug assertion in tests that the union of triangle masks equals the complete quadrant mask.
- Remove `_nearest_triangle()` and normal unmatched-pixel fallback behavior.

## Optional future improvement

After physical calibration data exists, a constrained smooth interpolator may replace the piecewise-linear core. Do not add RBF/thin-plate interpolation in this revision.

---

# Priority 6 — Calculate shared axes explicitly

## Problem

The current quadrant masks include both sides of every axis and use `filled_mask`, so whichever quadrant is processed first owns the shared axis.

## Required masks

Use strict masks for interiors:

```text
TR: x > 0 and y > 0
TL: x < 0 and y > 0
BL: x < 0 and y < 0
BR: x > 0 and y < 0
```

Evaluate separately:

- positive X axis;
- negative X axis;
- positive Y axis;
- negative Y axis;
- center point.

For an axis shared by two active quadrants:

1. evaluate both adjacent core models;
2. verify they reproduce the same sensor anchors;
3. average the two estimates, or use one dedicated 1D signed interpolation defined from the same anchors.

The final axis result must not depend on `PRESSURE_ACTIVE_QUADRANTS` ordering.

Add tests that randomize quadrant iteration order and obtain identical output.

---

# Priority 7 — Fix isolated-outer evaluation and remove double decay

## Current defect

The isolated-outer path applies:

1. an axial compact decay after the peak; and
2. another radial compact decay from the same peak.

This makes the field fade too quickly and appear cropped.

## Required isolated-outer core

For an isolated active outer sensor:

```text
center value = 0
outer sensor value = measured signed value
inferred peak position = sensor position + near_outer_peak_offset
inferred peak value = extrapolated signed peak value
```

Build one package-level anisotropic lobe:

```text
center -> outer sensor -> inferred peak
```

Use the same smooth compact lateral profile described for the single-axis model.

After the inferred peak, do not apply any axial natural fade inside the isolated evaluator. The one package-wide core-to-boundary extension must provide the only outward compact-support decay.

Remove unused lateral-bound calculations and contradictory comments.

Add tests proving:

- exact zero at center;
- exact measured value at the outer sensor;
- true local maximum at the inferred peak;
- monotonic decay after the peak;
- no double attenuation.

---

# Priority 8 — Make array overlap blending continuous as packages enter and leave

## Current defect

The current array code uses binary `support_mask` contributor counts and switches between:

```text
one candidate
one pair blend
average of three pair blends
average of six pair blends
```

Those formulas are not equal at 1→2, 2→3, or 3→4 contributor transitions. This creates rectangular bridges and seams aligned with package support squares.

## Preserve existing pair semantics

Continue to use:

- direct-neighbor linear pair weights;
- diagonal area-ratio pair weights;
- pairwise combination for three or more packages.

But replace unweighted pair counting with continuous pair confidence.

## Add continuous package support confidence

For each package candidate, compute a support-confidence field independent of pressure magnitude.

Use square/Chebyshev radius:

```text
r_square = max(abs(local_x), abs(local_y))
mid = mid_boundary_half_width_mm
outer = outer_boundary_half_width_mm
```

Then:

```text
support_confidence = 1                       when r_square <= mid
t = (r_square - mid) / (outer - mid)        when mid < r_square < outer
support_confidence = 1 - 3*t^2 + 2*t^3
support_confidence = 0                       when r_square >= outer
```

The candidate pressure itself must not be multiplied by this confidence a second time unless explicitly required by the package decay model. The confidence is for blending ownership/participation.

Add `support_confidence` to `_PackageCandidate`.

Keep `support_mask` only as an evaluation/allocation optimization. Do not use it to select different mathematical formulas.

## Weighted pair aggregation

For every overlapping package pair `(i, j)`:

```text
pair_value_ij = existing direct or diagonal pair blend
pair_confidence_ij = support_confidence_i * support_confidence_j
```

Aggregate:

```text
pair_numerator += pair_confidence_ij * pair_value_ij
pair_denominator += pair_confidence_ij
```

Where:

```text
pair_denominator > epsilon
```

use:

```text
combined = pair_numerator / pair_denominator
```

When no pair has meaningful confidence, use a continuous weighted candidate fallback:

```text
candidate_numerator =
    sum(support_confidence_i * candidate_value_i)

candidate_denominator =
    sum(support_confidence_i)

combined =
    candidate_numerator / candidate_denominator
```

Return zero where both denominators are zero.

Do not branch on integer contributor count.

## Expected continuity

When package `k` approaches its Outer Boundary:

```text
support_confidence_k -> 0
```

All pairs containing `k` smoothly vanish. The result converges to the combination of the remaining packages without a formula jump.

## Completely inactive candidates

Do not let a package with all thresholded sensor values equal to zero change pair counts abruptly. It may still act as a zero-valued physical anchor in an overlap, but its influence must enter and leave through the same continuous support confidence. Do not add a binary active/inactive package mask in the blend.

---

# Priority 9 — Regularize diagonal pair weights continuously

## Problem

For diagonal packages, both area-ratio raw weights can be zero at specific overlap corners. A fixed `0.5/0.5` fallback creates a singular corner and rapid weight changes nearby.

## Required regularization

Calculate:

```text
area_weight_first
area_weight_second
```

and a continuous distance-based fallback:

```text
distance_weight_first
distance_weight_second
```

Normalize the distance weights from inverse distance to package centers or another smooth ownership metric.

Blend between the two methods based on the area denominator:

```text
area_sum = area_first + area_second
blend_fraction = smoothstep(
    clamp(area_sum / regularization_scale, 0, 1)
)

final_first =
    blend_fraction * normalized_area_first
    + (1 - blend_fraction) * distance_weight_first

final_second = 1 - final_first
```

This must remain continuous at all four overlap corners.

Do not use an abrupt denominator test that leaves initialized `0.5/0.5` values.

Add tests at:

- four overlap corners;
- four edge midpoints;
- overlap center;
- points immediately around each formerly singular corner.

---

# Priority 10 — Use one shared geometry and one reusable field evaluator

## Current defects

The panel constructs the local and array generators independently. The array geometry may keep a default `near_outer_peak_offset_mm` while the local generator uses the configured value.

`PressureMapGenerator` also accepts both scalar geometry arguments and a geometry object but retains scalar members even when a different geometry object is supplied.

`evaluate_pressure_map_result_at()` manually creates an uninitialized generator with `object.__new__` and copies fields. This is brittle and can omit state as the algorithm evolves.

## Required changes

### One geometry instance

In the panel:

```python
geometry = PressureMapGeometry(
    sensor_spacing_mm=...,
    package_center_spacing_mm=...,
    outer_boundary_reach_mm=...,
    near_outer_peak_offset_mm=...,
    pixels_per_mm=...,
)

self.pressure_map_generator = PressureMapGenerator(
    geometry=geometry,
    shape_config=...,
)

self.pressure_map_array_generator = PressureMapArrayGenerator(
    geometry=geometry,
)
```

Store this object as the active pressure-map geometry.

### Constructor consistency

When `geometry` is provided:

- derive all geometry scalar members from it;
- reject conflicting scalar geometry arguments, or remove those scalar arguments from the primary constructor;
- use compatibility factory/class methods for legacy callers.

### Reusable evaluator

Replace the `object.__new__(PressureMapGenerator)` evaluator reconstruction with one of:

1. an immutable `PressureFieldModel.evaluate(x, y, support_bounds)` method; or
2. a pure function receiving all immutable model data explicitly.

Recommended:

```python
@dataclass(frozen=True)
class PressureFieldModel:
    geometry: PressureMapGeometry
    mode: str
    sensor_values: ...
    quadrant_models: ...
    decay_model: ...

    def evaluate(self, x, y, support_bounds) -> np.ndarray:
        ...
```

`PressureMapResult` should retain the field model or a serializable equivalent. Local and array evaluation must call the same evaluator.

---

# Priority 11 — Correct heatmap coordinate mapping

## Problem

Grid coordinate arrays represent pixel centers. The widget currently maps the image rectangle from the first center to the last center, effectively compressing/clipping half a pixel at each edge.

## Required rectangle helper

Add one helper based on coordinate centers:

```python
def image_rect_from_centers(
    x_coordinates,
    y_coordinates,
    *,
    mirror_x=False,
    offset_x=0.0,
    offset_y=0.0,
) -> QRectF:
```

For non-mirrored data:

```text
dx = x[1] - x[0]
dy = y[1] - y[0]

left = x[0] - dx/2
bottom = y[0] - dy/2
width = x[-1] - x[0] + dx
height = y[-1] - y[0] + dy
```

For mirrored data after `fliplr`:

```text
left = -x[-1] - dx/2
width unchanged
```

Apply offsets after calculating local edges.

Use this helper for:

- single-package image;
- separate package images;
- combined array image.

Do not derive image rectangles only from `total_extent_mm`.

Add alignment tests comparing:

- sensor marker coordinates;
- boundary lines;
- grid-cell centers;
- image rectangle edges.

---

# Priority 12 — Remove display-level hard cropping

## Current defect

Magnitude rendering uses the noise floor as the lower image level. Because the first palette color is transparent/black, all values below that floor disappear abruptly even when the backend field decays smoothly.

The panel may also couple this display floor to a signal-processing/shear threshold.

## Required rendering pipeline

Keep the configured fixed Max Intensity behavior.

Do not use the processing activity/noise threshold as a hard heatmap lower level.

For Magnitude mode:

```text
numeric color range = 0 to max_intensity
display magnitude = abs(signed_grid)
```

For Signed mode:

```text
numeric color range = -max_intensity to +max_intensity
```

Add a separate display-only alpha fade:

```text
magnitude = abs(value)
alpha = 0 when magnitude <= display_floor_low
alpha = smoothstep between display_floor_low and display_floor_high
alpha = 1 when magnitude >= display_floor_high
```

The backend pressure grid must remain unchanged.

Implementation options:

- generate an RGBA image from the selected LUT and alpha factor; or
- generate a dynamic LUT only if it correctly applies alpha by absolute magnitude in both signed and magnitude modes.

Do not use a single abrupt transparent color stop.

## Fixed scale consistency

Use the same configured fixed scale for:

- all separate packages;
- the combined array image;
- all frames.

Remove the active-sensor-count brightness multiplier from the production fixed-scale path.

Keep auto-scale only as a documented future option, not part of this revision.

## Saturation visibility

Add a lightweight display/debug indication when:

```text
abs(grid) >= max_intensity
```

Report either:

- saturated pixel percentage; or
- a small “SAT” indicator.

This is not a replacement for fixed scaling; it prevents uniform red/white plateaus from being misread as constant backend fields.

---

# Priority 13 — Improve raster display without hiding algorithm defects

After Priorities 1–12 pass continuity tests:

- allow higher `pixels_per_mm` if performance permits; and/or
- use display-only bilinear interpolation when scaling the raster to screen size.

Requirements:

- do not blur or resample the backend array before blending;
- do not use smoothing to hide a failing continuity test;
- sensor anchors and peak locations must remain in physical coordinates;
- display interpolation must be optional and must not change saved numeric data.

Enforce a minimum feature width in field-generation algorithms:

```text
minimum_feature_width >= 3 grid cells
```

This applies particularly to compact lateral profiles.

---

# Priority 14 — Fix cache/update correctness

## Current risk

A cache key based on `id(grid)` can miss in-place grid changes and can also be reused by Python after object destruction.

## Required change

Add a monotonic `frame_id` or `revision_id` to generated pressure results.

Use cache keys such as:

```text
(result.frame_id, display_mode, mirror, levels, alpha settings)
```

Do not compare full arrays with `np.array_equal()` every frame.

If grid sizes remain modest, unconditional image upload is acceptable if profiling shows it is faster and simpler.

Static geometry, coordinate arrays, triangle definitions, and overlay objects should be cached independently from frame data.

---

# Priority 15 — Add diagnostics before removing legacy paths

Add an optional debug mode that can export or display:

1. thresholded C/L/R/T/B values per package;
2. selected package mode;
3. selected quadrant modes;
4. inferred peak positions and heights;
5. core interpolation surface;
6. core-boundary anchor map;
7. natural reach map;
8. final package candidate field;
9. support-confidence field per package;
10. direct/diagonal pair weight fields;
11. pair-confidence denominator;
12. final array field;
13. saturation mask.

The debug mode must not run in the normal 30 FPS path unless enabled.

Use this mode to verify that visible seams do not align with:

- `x = 0` or `y = 0`;
- `x = ±sensor_spacing_mm`;
- `y = ±sensor_spacing_mm`;
- Mid Boundary lines;
- package Outer Boundary lines;
- changes in overlap topology.

---

# Priority 16 — Cleanup after the new algorithm is verified

After migration and tests pass:

- remove `contact_region`;
- remove half-plane zeroing;
- remove `_clamp_values()` sign clipping;
- remove nearest-triangle fallback;
- remove duplicated quadrant-level single-axis mode;
- remove isolated-outer axial decay duplication;
- remove binary contributor-count blending;
- remove obsolete `circle_mask` if no caller uses it;
- remove legacy `show_negative` from backend calculations;
- rename `adjacent_pairs` to `overlap_pairs`, retaining only a temporary compatibility alias;
- remove manually reconstructed generator state in `evaluate_pressure_map_result_at`;
- update comments that claim one decay is applied when two are applied;
- update result metadata to describe the new field model.

Do not remove legacy settings loading until migration tests pass.

---

# Required implementation sequence

Implement in this order and keep each stage testable:

1. Add regression tests and debug fixtures for the current visible artifacts.
2. Introduce shared `PressureMapGeometry` use and immutable `PressureFieldModel`.
3. Implement package-level mode classification.
4. Implement complete signed core interpolation.
5. Implement explicit shared-axis evaluation.
6. Implement package-level single-axis and isolated-outer fields.
7. Implement continuous core-to-Outer-Boundary extension.
8. Remove sign clamp and hard internal masks.
9. Add continuous package support confidence.
10. Replace contributor-count pair averaging with confidence-weighted pair aggregation.
11. Regularize diagonal weighting.
12. Correct image rectangles.
13. Add display-only alpha fade and saturation indication.
14. Update cache keys and performance paths.
15. Remove obsolete code only after all tests pass.

---

# Required automated tests

## A. Sensor reconstruction

For positive, negative, and mixed-sign vectors:

- exact C/L/R/T/B values at sensor coordinates;
- exact zero for thresholded inactive sensors;
- tolerance based on floating-point computation, not one grid cell.

## B. Package-level continuity

Sample values immediately on both sides of:

- `x = 0`;
- `y = 0`;
- `x = ±sensor_spacing_mm`;
- `y = ±sensor_spacing_mm`;
- every triangle edge;
- the core-to-extension transition;
- natural decay endpoint;
- Outer Boundary.

Required:

```text
abs(value_left - value_right) <= continuity_tolerance
```

Do not expect derivative continuity everywhere for piecewise-linear cores, but value continuity is mandatory.

## C. Single-axis cases

Test C+R, C+L, C+T, C+B with rotations and mirrors:

- one continuous lobe;
- no duplicated halves;
- no zero jump across center;
- exact center and outer values;
- inactive perpendicular sensors remain zero;
- continuous longitudinal and lateral profiles.

## D. Isolated-outer cases

Test R-only, L-only, T-only, B-only:

- center zero;
- exact outer sensor;
- peak beyond sensor;
- peak greater in magnitude than sensor, subject to gain cap;
- one outward decay;
- no plateau and no double decay.

## E. Signed transitions

Use vectors such as:

```text
C > 0, R > 0, T < 0
C < 0, L > 0, B < 0
```

Verify:

- quadrant is not deleted;
- field crosses zero continuously;
- no L-shaped or rectangular hole;
- Magnitude mode equals `abs(Signed backend)` after blending.

## F. Triangulation coverage

For every quadrant and inferred-peak location:

- every core pixel assigned exactly once;
- no unmatched fallback;
- shared edges deterministic;
- random quadrant iteration order produces identical output.

## G. Natural decay

For several amplitudes:

- weak signal reaches zero before the Outer Boundary;
- stronger signal may extend farther;
- zero occurs no later than the Outer Boundary;
- decay is monotonic along representative outward rays;
- only one compact-support factor is applied.

## H. Rotation and reflection symmetry

Rotate sensor vectors by 90°, 180°, and 270° and verify the output rotates equivalently.

Mirror left/right and top/bottom and verify reflected equivalence.

## I. Array blend continuity

For 1, 2, 3, 4, and 5-package layouts:

- no jump when a package support confidence approaches zero;
- no rectangular seam at contributor topology changes;
- direct pair midpoint remains the expected 50/50 blend;
- three-package result converges continuously to the remaining pair as the third confidence goes to zero;
- four-package result converges continuously to three and two packages.

## J. Diagonal regularization

Test exact and near-corner points for diagonal overlap:

- weights finite;
- weights sum to 1;
- no abrupt 0.5 fallback;
- small coordinate perturbations produce small weight perturbations.

## K. Grid-density invariance

Compare multiple `pixels_per_mm` values:

- sensor anchors unchanged;
- peak positions unchanged;
- decay endpoints unchanged within one finest-grid cell;
- no new seams;
- coarse and fine fields agree after sampling at the same physical coordinates.

## L. Rendering tests

Verify:

- half-cell rectangle expansion;
- mirrored rectangle placement;
- sensor markers align with image coordinates;
- fixed scale common across packages;
- alpha fade is smooth;
- backend grid unchanged by display mode;
- saturation indication appears when expected.

## M. Cache tests

Verify:

- a new frame with reused array storage refreshes the image;
- changing display mode, mirror, levels, or alpha settings invalidates display cache;
- unchanged static overlays are not rebuilt unnecessarily.

---

# Acceptance criteria

The revision is complete only when all of the following are true:

1. The rectangular plateaus and straight cuts seen at sensor lines are absent.
2. Single-axis inputs produce one continuous lobe rather than two joined blocks.
3. Mixed-sign inputs produce smooth zero crossings rather than missing quadrants.
4. No diagonal wedge is created by unmatched triangulation pixels.
5. Isolated-outer fields use one decay and do not show a plateau or abrupt cutoff.
6. Package overlap transitions are continuous when the number of geometrically overlapping packages changes.
7. Inactive/zero-valued packages do not create abrupt rectangular boundaries in neighboring active fields.
8. The visible fade is not hard-clipped by the display noise floor.
9. Image pixels, sensor markers, and physical boundary overlays are aligned.
10. Increasing `pixels_per_mm` improves raster detail without revealing mathematical seams.
11. All tests above pass.
12. The implementation summary identifies every removed legacy branch and every compatibility path retained.

---

# Delivery requirements

Update at least:

- `pressure_map_generator.py`;
- `pressure_map_array_generator.py`;
- `pressure_map_geometry.py`;
- `pressure_map_widget.py`;
- `signal_integration_panel.py`;
- pressure-map constants and persistence migration;
- unit and integration tests;
- pressure-map specification/docstrings.

Provide a final implementation report containing:

- files changed;
- package-field architecture;
- exact mode classification;
- core interpolation method;
- decay extension method;
- array confidence/blending formulas;
- signed-display behavior;
- rendering-coordinate corrections;
- legacy fields removed or retained;
- tests added;
- performance measurements for the normal live refresh path;
- any calibration-dependent values intentionally left unchanged.
