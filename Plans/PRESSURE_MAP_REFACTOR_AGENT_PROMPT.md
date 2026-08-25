# Pressure Map Algorithm and Display Refactor — Coding Agent Prompt

## Objective

Refactor the current pressure-map generator, array generator, settings integration, persistence, tests, and display widget to correct interpolation and decay problems while preserving the recently implemented physical geometry and overlap behavior.

Preserve unless explicitly changed below:

- configurable `sensor_spacing_mm`, default and initial value `2.0 mm`;
- configurable `package_center_spacing_mm`, default and initial value `7.5 mm`;
- configurable `outer_boundary_reach_mm`, default and initial value `1.75 mm`;
- configurable `near_outer_peak_offset_mm`, default and initial value `1.0 mm`;
- configurable `pixels_per_mm`, default and initial value `10 pixels/mm`;
- fixed local support derived from the Outer Boundary;
- independent Near-Outer Circle, Mid-Boundary Square, and Outer-Boundary Square visibility controls;
- direct-neighbor, diagonal, and multi-package overlap support.

Treat the pressure field as an **inferred visualization**, not as calibrated pressure per unit area.

---

## 1. Fix sensor-value reconstruction

Every pressure-map mode must reproduce the measured value exactly at each active sensor coordinate:

- C at `(0, 0)`;
- L/R at `(-sensor_spacing_mm, 0)` and `(+sensor_spacing_mm, 0)`;
- T/B at `(0, +sensor_spacing_mm)` and `(0, -sensor_spacing_mm)`.

### Single-axis mode

Replace the current averaged endpoint behavior in `_evaluate_single_axis_peaked_quadrant()`.

Use exact piecewise interpolation:

```text
center sensor value
    → inferred peak value
    → active outer-sensor value
    → outward spatial decay
```

For the active axis:

```text
if axis <= peak_axis:
    interpolate center_value → peak_value
elif axis <= sensor_spacing_mm:
    interpolate peak_value → outer_value
else:
    apply outward spatial decay from outer_value
```

Do not assign `(center_value + outer_value) / 2` at both sensor endpoints.

Add tests proving exact reconstruction at the center and active outer sensor for positive and negative values, every axis, rotations, and mirror states.

---

## 2. Isolated-outer inferred peak

When exactly one outer sensor is active while C and all other outer sensors are below the signal-activity threshold:

1. Place the inferred pressure peak outside the active outer sensor by the configurable `near_outer_peak_offset_mm`.
2. Preserve the measured outer-sensor value exactly at the outer-sensor coordinate.
3. Calculate a true inferred peak height larger in magnitude than the measured outer value:

```text
peak_height =
    outer_sensor_value
    * (
        1
        + peak_height_decay_rate
          * near_outer_peak_offset_mm
          / peak_height_reference_distance_mm
      )
```

4. Preserve the original sign.
5. Interpolate from the outer-sensor value to the inferred peak height.
6. Apply outward spatial decay after the inferred peak.
7. Add a configurable maximum peak-gain limit to prevent unbounded extrapolation.

The inferred location must be a real local maximum rather than a constant plateau.

---

## 3. Separate peak-height shaping from spatial decay

Remove the dual-purpose use of `decay_ref_distance_mm`.

Add separate configurable parameters:

### Peak-height parameters

- `peak_height_reference_distance_mm`
- `peak_height_decay_rate`
- `maximum_peak_gain`

Use them only for inferred peak-height extrapolation.

### Spatial-decay parameters

- `natural_decay_reference_distance_mm`
  - configurable;
  - default and initial value: `2.5 mm`.
- `decay_amplitude_reference`
  - configurable;
  - represents the signal magnitude expected to receive the reference decay reach.
- `minimum_decay_reach_mm` or an equivalent configurable minimum reach.

Do not derive `decay_amplitude_reference` from the display Max Intensity setting.

The initial numeric value for `decay_amplitude_reference` must be chosen from representative integrated-signal data or an existing processing-domain reference. Do not silently invent a display-derived value. Put it in a named constant and make it visible in settings so it can be calibrated.

Provide settings migration from the old `decay_ref_distance_mm`:

- migrate its existing value to `natural_decay_reference_distance_mm`;
- initialize `peak_height_reference_distance_mm` from a named default constant;
- retain backward-compatible loading for old saved settings.

---

## 4. Amplitude-dependent natural decay reach

Replace:

```text
natural_reach =
    decay_ref_distance_mm
    * max(1, strength * decay_rate)
```

with an amplitude-normalized calculation.

Recommended form:

```text
normalized_strength =
    clamp(
        abs(strength) / decay_amplitude_reference,
        0,
        maximum_strength_ratio
    )

natural_reach =
    minimum_decay_reach_mm
    + normalized_strength
      * (
          natural_decay_reference_distance_mm
          - minimum_decay_reach_mm
        )
```

Signals above the amplitude reference may continue increasing reach using a documented extension rule and configurable cap, but the final reach must still be limited by the Outer Boundary.

Requirements:

- weak non-noise signals may reach zero before the Outer Boundary;
- stronger signals may extend farther;
- gain changes must not silently redefine spatial reach without going through `decay_amplitude_reference`;
- all units and parameter meanings must be documented.

---

## 5. Replace the current spatial-decay algorithm

Use **radial smoothstep compact-support decay**.

Remove:

- separate X and Y natural-decay factors;
- separate X and Y terminal envelopes;
- multiplication of natural and terminal envelopes;
- axis-dependent double attenuation.

For every evaluated pixel:

1. Select the relevant pressure origin:
   - inferred pressure peak where one exists;
   - otherwise the appropriate interpolated pressure/contact anchor.
2. Compute the Euclidean distance from that origin to the pixel.
3. Compute the ray from the origin through the pixel.
4. Compute the distance from the origin to the square Outer Boundary along that ray.
5. Compute the amplitude-dependent `natural_reach`.
6. Define:

```text
effective_end =
    min(natural_reach, ray_boundary_distance)
```

7. Apply smoothstep compact-support decay:

```text
t = clamp(distance / effective_end, 0, 1)
decay_factor = 1 - 3*t^2 + 2*t^3
```

8. Return zero at and beyond `effective_end`.

Behavioral requirements:

- pressure may naturally become zero before the Outer Boundary;
- strong pressure must become zero no later than the Outer Boundary;
- do not stretch every pressure field so it remains nonzero until the boundary;
- do not multiply a natural fade by a second terminal fade;
- decay must remain continuous.

Handle zero-length or near-zero `effective_end` safely.

---

## 6. Consistent activity thresholding

Add one signal-domain helper:

```text
is_signal_active(value) =
    abs(value) >= signal_activity_threshold
```

Use it consistently for:

- isolated-outer detection;
- active-quadrant detection;
- single-axis detection;
- active-sensor counting;
- any other mode selection.

Requirements:

- do not use exact `value != 0`;
- do not reuse `geometry_epsilon` as a signal threshold;
- keep geometry tolerance and signal/noise tolerance separate;
- use the same thresholded/calibrated signal domain throughout the pressure generator.

---

## 7. Sign handling and display modes

Backend calculation must be independent of display visibility settings.

For pressure-location and weight calculations:

```text
magnitude = abs(value)
```

Preserve the original sign in the generated backend field.

Add a configurable and persisted display mode:

### `Magnitude`

- default and initial mode;
- render `abs(pressure_grid)`;
- backward-compatible with the current visual appearance.

### `Signed`

- render positive and negative values with a zero-centered diverging color map;
- use a signed legend;
- keep zero visually neutral.

Remove any behavior where `show_negative` changes:

- pressure-point location;
- quadrant activation;
- peak creation;
- decay geometry.

Migrate the old negative-display setting into the new display-mode behavior where practical.

---

## 8. Complete piecewise-linear interpolation

Keep a piecewise-linear surface for this refactor.

Replace the nearest-triangle-centroid fallback with a complete deterministic triangulation that covers the full active quadrant.

Requirements:

- no unassigned points;
- no nearest-centroid fallback;
- exact interpolation at all sensor and inferred-peak anchors;
- explicit non-overlapping triangles, or shared boundaries handled deterministically;
- no dependence on quadrant processing order.

Handle shared X and Y axes explicitly:

- use half-open masks for quadrant interiors;
- calculate shared-axis values directly or average equivalent estimates;
- ensure adjacent quadrants agree at shared sensor anchors.

Permit inferred pressure points anywhere in the full square quadrant. Do not constrain them to the C/H/V sensor triangle. Document this because corner contact is physically plausible.

### Optional future improvement

After measured calibration data is available, consider replacing the piecewise-linear interpolation with a constrained smooth interpolator such as an RBF or thin-plate surface. Do not implement that in this refactor because it can overshoot, ring, or require additional constraints and dependencies.

---

## 9. Shared geometry object

Create one immutable shared geometry/configuration object used by both single-package and array generators.

Include at least:

- configurable `sensor_spacing_mm`, default and initial value `2.0 mm`;
- configurable `package_center_spacing_mm`, default and initial value `7.5 mm`;
- configurable `outer_boundary_reach_mm`, default and initial value `1.75 mm`;
- configurable `near_outer_peak_offset_mm`, default and initial value `1.0 mm`;
- configurable `pixels_per_mm`, default and initial value `10 pixels/mm`.

Derive from that object:

```text
facing_sensor_gap_mm =
    package_center_spacing_mm
    - 2 * sensor_spacing_mm

mid_boundary_half_width_mm =
    package_center_spacing_mm / 2

outer_boundary_half_width_mm =
    mid_boundary_half_width_mm
    + outer_boundary_reach_mm
```

Default derived values:

```text
facing_sensor_gap_mm = 3.5 mm
mid_boundary_half_width_mm = 3.75 mm
outer_boundary_half_width_mm = 5.5 mm
```

Requirements:

- both generators must use identical geometry;
- reject packages with incompatible geometry;
- reject duplicate `sensor_id` values;
- reject duplicate `grid_position` values;
- reject non-finite pressure data;
- reject invalid geometry before generation.

---

## 10. Array grid metadata

Build the common world grid directly from physical package support bounds and the configured `pixels_per_mm`.

Store actual generated spacing from the coordinate vectors:

```text
cell_size_x_mm = x_coordinates_mm[1] - x_coordinates_mm[0]
cell_size_y_mm = y_coordinates_mm[1] - y_coordinates_mm[0]
```

Do not report a nominal package cell size when the generated array grid uses a slightly different `linspace` spacing.

Requirements:

- metadata must exactly match coordinate differences;
- preserve exact physical world limits;
- preserve exact package-center locations;
- keep numerical padding removed;
- rendering/view padding must remain display-only.

---

## 11. Array overlap blending

Preserve:

- direct horizontal and vertical linear weighting;
- diagonal area-ratio weighting;
- all-pairs averaging for three or more contributors.

Improve diagonal corner handling:

- explicitly define expected weights at all four overlap corners;
- regularize cases where both raw area weights become zero;
- use a small area epsilon or another continuous normalization method;
- prevent abrupt `0.5/0.5` fallback discontinuities near those corners.

Optimize pair blending:

- evaluate and allocate only within each overlap slice or mask;
- do not create unnecessary full-grid pair arrays;
- do not emit repeated warnings for documented four-package overlap;
- log unusual conditions once per layout rather than once per frame.

Rename `adjacent_pairs` to `overlap_pairs` if it includes diagonal or non-adjacent support overlaps.

---

## 12. Fixed intensity display

Keep the current fixed Max Intensity behavior for this refactor.

Requirements:

- use one common intensity range for all packages in a multi-package display;
- the same color must represent the same magnitude across all visible packages;
- for a combined array image, use the configured fixed scale directly;
- do not derive scaling from only the first package;
- remove any active-sensor-count multiplier that changes brightness when sensors cross a threshold.

When Max Intensity is zero, retain only the current safe fallback needed for backward compatibility; do not make auto-scaling the main behavior in this refactor.

### Optional future improvement

Later, add an optional robust auto-scale mode based on a high percentile of the complete displayed grid with temporal smoothing. Keep it explicitly separate from the fixed scientific-comparison mode.

---

## 13. Shear-arrow scaling

Decouple maximum shear-arrow length from:

```text
sensor_spacing_mm + near_outer_peak_offset_mm
```

Changing the isolated-pressure peak offset must not change shear-arrow scaling.

Use either:

```text
outer_boundary_half_width_mm
    * arrow_max_length_fraction
```

or a configurable physical `arrow_max_length_mm`.

Preserve the existing arrow threshold, gain, width, mirror, and direction behavior.

---

## 14. Image cache and live performance

Fix cache behavior:

- remove identity-only checks that can miss in-place data changes;
- remove full `np.array_equal()` checks on every live frame;
- use a frame/version identifier, or unconditionally upload modest grids after profiling;
- reuse static coordinate grids, triangulation data, and overlay objects;
- rate-limit live warnings and logs.

Keep the 30 FPS live-refresh path responsive.

---

## 15. Cleanup

Remove or rename obsolete or misleading elements after migration support is complete:

- computational `circle_mask` if it is no longer used;
- unused array-level `show_negative`;
- unused `calibrated_values` in array input, unless another caller requires it;
- unused local `bounds` variables;
- legacy compatibility fields that are no longer needed;
- `adjacent_pairs` when its meaning is actually `overlap_pairs`.

Do not remove a compatibility field until saved-settings migration and existing callers are handled.

---

## 16. Quantitative interpretation

For this refactor, the pressure map remains an **inferred visualization**.

Clearly document in the UI/specification that:

- pixel values represent inferred relative signal intensity;
- the map is not calibrated pressure per unit area;
- the pixel-area integral is not required to equal `normal_force_result.total_force`;
- changing `pixels_per_mm` should not materially move the inferred peak or change the general field shape.

### Optional future improvement

After pressure/force calibration data exists, add an optional quantitative normalization mode:

```text
sum(
    pressure_grid
    * cell_size_x_mm
    * cell_size_y_mm
)
≈ calibrated_normal_force
```

Do not implement this normalization in the current refactor.

---

## 17. Required tests

Add or update automated tests for:

1. Exact reconstruction at all five sensor coordinates.
2. Exact reconstruction of inferred peak anchors.
3. Correct single-axis `center → peak → outer` interpolation.
4. A true isolated-outer peak rather than a plateau.
5. Weak pressure naturally reaching zero before the Outer Boundary.
6. Strong pressure reaching zero at or before the Outer Boundary.
7. No double attenuation from natural and terminal envelopes.
8. Monotonic outward decay along representative rays.
9. Smoothstep continuity at the origin and zero endpoint.
10. Rotation, reflection, and mirror symmetry.
11. Full-square-quadrant peak placement.
12. Continuity across every triangle edge.
13. Continuity and order independence on shared quadrant axes.
14. Consistent threshold behavior near the activity threshold.
15. Backend invariance under Magnitude versus Signed display selection.
16. Geometry compatibility validation.
17. Duplicate package ID and grid-position rejection.
18. Non-finite input rejection.
19. Array coordinate-spacing metadata correctness.
20. Direct-neighbor blend weights at both edges and midpoint.
21. Diagonal weights at four corners, four edge midpoints, center, and nearby regularization points.
22. Three- and four-package all-pairs averaging.
23. One common fixed intensity scale across separate packages.
24. Signed diverging display and Magnitude display.
25. Shear-arrow length independence from `near_outer_peak_offset_mm`.
26. No repeated live warnings for normal documented overlap.
27. No unnecessary full-grid allocation per overlap pair.
28. Grid-density invariance of inferred peak position and general field shape.

---

## 18. Delivery requirements

Update:

- pressure-map constants;
- settings GUI;
- settings validation;
- JSON persistence and migration;
- single-package generator;
- array generator;
- result metadata;
- pressure-map widget;
- specifications/docstrings;
- unit and integration tests.

Provide a concise implementation summary listing:

- files changed;
- old settings migrated;
- new settings added;
- algorithm changes;
- compatibility decisions;
- tests added or changed;
- any remaining calibration-dependent defaults, especially `decay_amplitude_reference`.
