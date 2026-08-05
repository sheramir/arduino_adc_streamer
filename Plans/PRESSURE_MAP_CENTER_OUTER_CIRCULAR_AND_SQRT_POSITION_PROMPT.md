# Coding Agent Prompt — Circular Center-plus-One Lobe and Square-Root Peak Positioning

Update the current `pressure_map_generator.py`.

The current isolated outer-sensor implementation is correct and must remain unchanged. It uses one circular radial field centered at the inferred outside peak, multiplied by a smooth axial gate, and retains the actual radius/peak diagnostics.

This task has two changes:

1. Replace the **same-sign center-plus-one-outer** stem-like field with one continuous circle-like field centered at the inferred peak between the two sensors.
2. Change inferred peak-position weighting from linear signal magnitude to **square-root magnitude weighting** wherever a peak position is inferred from sensor ratios.

Do not change unrelated package modes, array blending, display mapping, support geometry, thresholding, or the isolated outer-sensor circular model.

---

## Current behavior to replace

For `PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER`, same-sign center and outer signals currently use:

```python
longitudinal(u) * smoothstep_fade(abs(v), width(u))
```

through `_evaluate_axis_lobe()` and `_piecewise_width()`.

That produces an elongated or pinched shape rather than a rounded pressure region centered between the active center and outer sensor.

The peak position is also calculated more than once using linear weighting:

```python
peak_axis = spacing * abs(outer) / (abs(center) + abs(outer))
```

Eliminate this duplication.

---

# Part 1 — Square-root peak-position weighting

## Shared helper

Add:

```python
def _peak_position_weight(value: float) -> float:
    return float(np.sqrt(abs(float(value))))
```

Use this helper only for inferred **peak position** calculations.

Do not use it for measured field values, peak-height weights, activity confidence, thresholding, decay reach, or decay origins.

## Center plus one outer

Create one source-of-truth helper:

```python
def _center_outer_peak_axis(
    center: float,
    outer: float,
    spacing: float,
) -> float:
    center_weight = _peak_position_weight(center)
    outer_weight = _peak_position_weight(outer)
    return (
        spacing
        * outer_weight
        / max(
            PRESSURE_NUMERIC_EPSILON,
            center_weight + outer_weight,
        )
    )
```

Examples:

```text
center=9, outer=4  -> p = 2/(3+2) * spacing = 0.4 spacing
center=4, outer=9  -> p = 3/(2+3) * spacing = 0.6 spacing
center=4, outer=4  -> p = 0.5 spacing
```

Use this helper during model construction. The evaluator must read the retained position from `model.peak_point`; it must not recalculate it.

## General quadrant peak

Update `_pressure_point()`:

```python
center_weight = _peak_position_weight(
    signals[SHEAR_POSITION_CENTER]
)
horizontal_weight = _peak_position_weight(
    signals[quadrant.horizontal_sensor]
)
vertical_weight = _peak_position_weight(
    signals[quadrant.vertical_sensor]
)

peak_x = (
    quadrant.horizontal_sign
    * spacing
    * horizontal_weight
    / max(
        PRESSURE_NUMERIC_EPSILON,
        horizontal_weight + center_weight,
    )
)

peak_y = (
    quadrant.vertical_sign
    * spacing
    * vertical_weight
    / max(
        PRESSURE_NUMERIC_EPSILON,
        vertical_weight + center_weight,
    )
)
```

Do not change `_pressure_point_height()` except that it will receive the new peak coordinates.

Do not change `_axis_decay_origin()` or `_quadrant_decay_origin()` in this task.

---

# Part 2 — Circular same-sign center-plus-one field

## Scope

Apply the new circular model only when:

```python
package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER
and center * outer > 0.0
and model.peak_point is not None
```

For opposite-sign center/outer signals, retain the existing signed-transition behavior. A single same-sign circular peak cannot represent the required zero crossing.

Evaluate the new same-sign model over the complete strict package support, not as a core field followed by a separate extension formula.

---

## Canonical coordinates

Use `_axis_coordinates()`:

- `u`: coordinate along the active outer-sensor direction;
- `v`: perpendicular coordinate;
- center sensor: `u = 0`;
- active outer sensor: `u = spacing`;
- inferred peak: `u = peak_axis`, with `0 < peak_axis < spacing`.

Read `peak_axis` from `model.peak_point`. Add a helper if useful:

```python
def _axis_distance_from_peak_point(
    sensor: str,
    peak_point: tuple[float, float],
) -> float:
    ...
```

Do not recompute the peak from signal values inside the evaluator.

---

## Circular radial base

Use one radial distance:

```python
radial_distance = np.hypot(
    u - peak_axis,
    v,
)
```

and:

```python
radial_factor = smoothstep_fade(
    radial_distance,
    radius,
)
```

Equal axial and lateral distances from the inferred peak must receive the same radial factor.

The new same-sign path must not use `_piecewise_width()`.

---

# Radius selection

Add a shared helper such as:

```python
def _center_outer_circular_profile(
    model: PressureFieldModel,
    support_bounds: tuple[float, float, float, float],
) -> tuple[
    float,  # radius
    float,  # actual peak value
    float,  # center scale
    float,  # outer scale
    float,  # actual peak gain
    bool,   # gain cap satisfied
]:
    ...
```

## Required distances

Let:

```python
spacing = model.geometry.sensor_spacing_mm
p = peak_axis

distance_to_center = p
distance_to_outer = spacing - p
```

The radius must contain both active anchors:

```python
minimum_radius = (
    max(distance_to_center, distance_to_outer)
    + PRESSURE_NUMERIC_EPSILON
)
```

The circle should naturally exclude the other three outer sensors.

Their canonical distances from the peak are:

```python
distance_to_opposite_sensor = spacing + p

distance_to_each_perpendicular_sensor = np.hypot(
    p,
    spacing,
)
```

Use:

```python
inactive_sensor_limit = min(
    distance_to_opposite_sensor,
    distance_to_each_perpendicular_sensor,
) - geometry_tolerance
```

Also limit by the nearest Outer Boundary:

```python
peak_x, peak_y = model.peak_point
left, right, bottom, top = support_bounds

boundary_limit = min(
    peak_x - left,
    right - peak_x,
    peak_y - bottom,
    top - peak_y,
)

maximum_radius = min(
    inactive_sensor_limit,
    boundary_limit,
)
```

Validate:

```python
maximum_radius > minimum_radius
```

Raise a clear `ValueError` if the geometry cannot contain a circle that includes both active anchors while excluding the inactive outer sensors.

## Natural radius

Use:

```python
anchor_strength = max(
    abs(center),
    abs(outer),
)

natural_radius = float(
    _natural_decay_reach(
        np.asarray(anchor_strength, dtype=np.float64),
        model,
    )
)

radius = np.clip(
    natural_radius,
    minimum_radius,
    maximum_radius,
)
```

---

# Preserve both measured anchors

For a candidate radius:

```python
center_factor = float(
    smoothstep_fade(distance_to_center, radius)
)

outer_factor = float(
    smoothstep_fade(distance_to_outer, radius)
)
```

Both factors must be greater than numerical epsilon.

The minimum peak magnitude that can decay toward both measured anchors without either anchor exceeding the peak is:

```python
required_peak_magnitude = max(
    abs(center) / center_factor,
    abs(outer) / outer_factor,
)
```

Because the signals have the same sign:

```python
field_sign = 1.0 if center > 0.0 else -1.0
actual_peak_value = field_sign * required_peak_magnitude
```

Calculate:

```python
center_scale = center / (
    actual_peak_value * center_factor
)

outer_scale = outer / (
    actual_peak_value * outer_factor
)
```

Validate within tolerance:

```text
0 < center_scale <= 1
0 < outer_scale <= 1
```

This must guarantee:

```text
field(center sensor) = measured center value
field(active outer sensor) = measured outer value
field(inferred peak) = amplified peak value
```

Do not clip the peak value because that would violate one or both measured anchors.

---

# Peak-gain cap

Define gain relative to the stronger measured anchor:

```python
reference_magnitude = max(
    abs(center),
    abs(outer),
)

actual_peak_gain = (
    abs(actual_peak_value) / reference_magnitude
)
```

If the initial radius gives:

```python
actual_peak_gain > model.maximum_peak_gain
```

use scalar bisection over:

```python
low = radius
high = maximum_radius
```

Find the smallest radius for which:

```python
actual_peak_gain <= model.maximum_peak_gain
```

Use approximately 32 iterations.

If even `maximum_radius` cannot satisfy the cap:

- use `maximum_radius`;
- preserve the exact center and active-outer measurements;
- preserve zero at inactive sensors and the Outer Boundary;
- allow the peak gain to exceed the cap;
- set a diagnostic flag to false.

Anchor preservation has higher priority than the gain cap.

---

# Smooth axial anchor correction

A pure circle cannot generally reproduce two unequal measurements exactly. Multiply the circular radial base by a smooth axial scale.

The scale must equal:

```text
center_scale at u = 0
1.0          at u = peak_axis
outer_scale  at u = spacing
```

Use `_smooth_interpolate()`.

```python
before_t = np.clip(
    u / max(peak_axis, PRESSURE_NUMERIC_EPSILON),
    0.0,
    1.0,
)

before_scale = _smooth_interpolate(
    center_scale,
    1.0,
    before_t,
)
```

```python
after_t = np.clip(
    (u - peak_axis)
    / max(
        spacing - peak_axis,
        PRESSURE_NUMERIC_EPSILON,
    ),
    0.0,
    1.0,
)

after_scale = _smooth_interpolate(
    1.0,
    outer_scale,
    after_t,
)
```

Use constant endpoint scales outside the two anchors:

```python
axial_scale = np.where(
    u <= 0.0,
    center_scale,
    np.where(
        u < peak_axis,
        before_scale,
        np.where(
            u < spacing,
            after_scale,
            outer_scale,
        ),
    ),
)
```

Final field:

```python
values = (
    actual_peak_value
    * radial_factor
    * axial_scale
)
```

Then apply the strict support mask and `_numeric_cleanup()`.

This is intentionally **circle-like**, not perfectly circular everywhere, because the smooth axial correction is required to preserve two arbitrary measured anchors. Near the peak, the axial scale is `1` with zero smoothstep slope, so the visible peak neighborhood should remain close to circular.

---

# New evaluator

Add:

```python
def _evaluate_center_outer_circular_model(
    model: PressureFieldModel,
    x_values: np.ndarray,
    y_values: np.ndarray,
    support_bounds: tuple[float, float, float, float],
    inside: np.ndarray,
) -> np.ndarray:
    ...
```

Do not overload `_evaluate_isolated_model()`.

In `_evaluate_pressure_field_model()`, before the generic core/extension split, add:

```python
if (
    model.package_mode
    == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER
    and model.peak_point is not None
    and model.peak_height is not None
):
    values = _evaluate_center_outer_circular_model(
        model,
        x_values,
        y_values,
        support_bounds,
        inside,
    )
    values[~inside] = 0.0
    return _numeric_cleanup(values)
```

The existing old `_evaluate_axis_lobe()` path should remain only for opposite-sign/non-peaked signed-transition behavior.

---

# Retained metadata and one source of truth

Add fields such as:

```python
center_outer_circular_radius_mm: float | None = None
center_outer_center_scale: float | None = None
center_outer_outer_scale: float | None = None
center_outer_actual_peak_gain: float | None = None
center_outer_gain_cap_satisfied: bool | None = None
```

During `_build_package_field_model()` for same-sign center-plus-one:

1. Build the peak point using square-root weighting.
2. Build the initial immutable model.
3. Calculate the circular profile once.
4. Use `dataclasses.replace()` to retain the actual peak value, radius, scales, gain, and cap status.
5. Update the matching `PressureQuadrantPlane.peak_height` to the actual retained peak value.

The evaluator must consume this retained metadata.

There must be one source of truth for:

```text
peak position
radius
actual peak value
anchor scales
actual peak gain
gain-cap status
```

---

# Debug diagnostics

When `debug=True` and the same-sign center-plus-one circular path is active, include:

```python
"center_outer_peak_axis_mm": peak_axis
"center_outer_circular_radius_mm": radius
"center_outer_measured_center_value": center
"center_outer_measured_outer_value": outer
"center_outer_actual_peak_value": actual_peak_value
"center_outer_actual_peak_gain": actual_peak_gain
"center_outer_center_scale": center_scale
"center_outer_outer_scale": outer_scale
"center_outer_gain_cap_satisfied": cap_satisfied
```

Do not change isolated diagnostics.

---

# Cleanup

After the new path works:

- remove duplicate linear peak-axis calculations from `_evaluate_axis_lobe()`;
- have any remaining evaluator use `model.peak_point`;
- retain `_evaluate_axis_lobe()` only for signed-transition behavior if still needed;
- remove `_piecewise_width()` only if no remaining caller uses it;
- do not change public compatibility constants or unrelated helpers.

---

# Mandatory tests

## A. Square-root center-plus-one position

With `spacing = 2.0`:

```text
center=9, outer=4 -> peak_axis=0.8 mm
center=4, outer=9 -> peak_axis=1.2 mm
center=4, outer=4 -> peak_axis=1.0 mm
```

Verify model metadata, peak marker position, and evaluator all use the same retained location.

## B. Square-root general-quadrant position

Verify:

```python
x_fraction = sqrt(abs(horizontal)) / (
    sqrt(abs(horizontal)) + sqrt(abs(center))
)

y_fraction = sqrt(abs(vertical)) / (
    sqrt(abs(vertical)) + sqrt(abs(center))
)
```

with correct quadrant signs.

## C. Exact active anchors

For all four outer directions and positive/negative same-sign pairs:

```text
field(center sensor) == measured center
field(active outer sensor) == measured outer
```

Use `atol <= 1e-10`.

## D. Inactive outer sensors

For all four directions:

```text
field(opposite outer sensor) == 0
field(first perpendicular outer sensor) == 0
field(second perpendicular outer sensor) == 0
```

## E. Peak amplification

```text
abs(field at peak) > max(abs(center), abs(outer))
sign(field at peak) == sign(center) == sign(outer)
```

## F. Gain cap

When geometry permits:

```text
actual_peak_gain <= maximum_peak_gain + tolerance
```

Also test constrained geometry where the cap cannot be met and verify exact anchors, inactive-sensor zero, and a false cap-status flag.

## G. Axis symmetry

For TOP/BOTTOM active sensors:

```python
F(u, +v) == F(u, -v)
```

Use the corresponding rotated comparison for LEFT/RIGHT.

## H. Rotational equivalence

The four active directions must be rotations/reflections of the same canonical field for identical center/outer values.

## I. Smoothness

Sample immediately around:

```text
u = 0
u = peak_axis
u = spacing
```

Verify there is no jump, especially at the peak.

## J. Centerline shape

Along `v = 0`:

```text
center -> peak: magnitude is nondecreasing
peak -> outer: magnitude is nonincreasing
```

Allow numerical tolerance.

## K. Opposite signs

Verify opposite-sign center/outer values still use the signed-transition path and retain a zero crossing.

## L. Strict support

Verify exact zero on and beyond every Outer Boundary line.

## M. Existing isolated mode

Run all isolated outer-sensor tests unchanged. The isolated circular model and diagnostics must not regress.

---

# Acceptance criteria

The change is complete when:

1. Isolated outer-sensor circular behavior is unchanged.
2. Same-sign center-plus-one pressure produces a rounded, circle-like region centered between the two active sensors.
3. Center and active outer measurements are preserved exactly.
4. The three inactive outer sensors remain exactly zero.
5. The peak is amplified above both measured anchors.
6. Peak location uses square-root magnitude weighting.
7. General-quadrant peak coordinates also use square-root magnitude weighting.
8. No evaluator independently recomputes the old linear peak position.
9. Opposite-sign transitions still work.
10. Strict Outer Boundary zero remains intact.
11. Existing and new tests pass.

---

# Delivery report

Provide:

- files changed;
- old center-plus-one formula removed or retained only for signed transition;
- new circular center-plus-one formula;
- square-root peak-position helper and every changed call site;
- radius and gain-cap logic;
- metadata and diagnostics added;
- tests added;
- diagnostic images or grids for:
  - center=9, outer=4;
  - center=4, outer=9;
  - center=4, outer=4;
  - positive and negative same-sign examples;
  - one opposite-sign example proving the transition path remains active.
