# Coding Agent Prompt — Use Virtual Outer-Sensor Positions for All Peak-Location Calculations

## Objective

Update the pressure-map peak-location model so that the configured outer-sensor offset affects **all inferred peak-location calculations**, not only the isolated-outer-sensor case.

The current physical sensor geometry must remain unchanged.

Use the latest `pressure_map_generator.py` as the source of truth.

---

## Core design rule

Each outer sensor must have two distinct positions:

1. **Physical sensor position**
   - Used for sensor markers and background graphics.
   - Used as the measured-value anchor location.
   - Used by normal-force geometry.
   - Used by package and array geometry.
   - Used by exact sensor-value constraints.

2. **Virtual peak-position location**
   - Used only when calculating the inferred pressure-peak location.
   - Located farther outward from the package center by the configured offset.

Let:

- `s = sensor_spacing_mm`
- `o = peak_position_outer_offset_mm`
- `s_virtual = s + o`

The physical outer sensors remain at distance `s`.

The virtual outer positions used for peak-location inference are at distance `s_virtual`.

The background image, sensor squares, sensor labels, package outlines, Mid Boundary, Outer Boundary, and array package locations must not move.

---

## 1. Introduce shared virtual outer-position geometry

Add one shared geometry concept:

```text
virtual_outer_spacing_mm = sensor_spacing_mm + peak_position_outer_offset_mm
```

Add a helper that returns the virtual outer position for each sensor:

```text
Left:   (-virtual_outer_spacing_mm, 0)
Right:  (+virtual_outer_spacing_mm, 0)
Top:    (0, +virtual_outer_spacing_mm)
Bottom: (0, -virtual_outer_spacing_mm)
```

Do not modify the existing physical `sensor_positions` dictionary.

It must continue to contain:

```text
Center: (0, 0)
Left:   (-sensor_spacing_mm, 0)
Right:  (+sensor_spacing_mm, 0)
Top:    (0, +sensor_spacing_mm)
Bottom: (0, -sensor_spacing_mm)
```

Avoid duplicating `sensor_spacing_mm + offset` calculations across different modes. All peak-position calculations must use the same shared helper or property.

---

## 2. Rename and migrate the setting

The setting is no longer specific to an isolated outer sensor.

Recommended public name:

```text
Peak-position outer offset
```

Recommended internal name:

```text
peak_position_outer_offset_mm
```

Recommended tooltip:

> For inferred peak-location calculations, treat each outer sensor as if it were this distance farther from the package center. Physical sensor markers and measured sensor anchors remain at their actual positions.

Maintain backward compatibility with existing saved settings:

1. Load `peak_position_outer_offset_mm` when present.
2. Otherwise load the legacy `near_outer_peak_offset_mm`.
3. Use the existing default when neither is present.
4. Save only the new key in newly written settings files, unless preserving the old key is required by broader application compatibility.

Update constants, settings serialization, settings loading, generator construction, result/model metadata, tests, and diagnostics accordingly.

---

## 3. Preserve the isolated-outer behavior

The isolated-outer case already places its peak at:

```text
sensor_spacing_mm + offset
```

Keep this behavior unchanged.

Refactor the isolated mode to use the new shared virtual-spacing helper rather than calculating the position independently.

The isolated field must continue to preserve:

- the real outer-sensor measurement at the physical sensor location;
- center value exactly zero;
- the circular outward blob;
- strict Outer Boundary zero;
- current gain-cap and fallback behavior.

---

## 4. Update center-plus-one peak location

For same-sign center-plus-one input, the current square-root weighted peak position uses the real outer-sensor spacing.

Change it to use virtual outer spacing.

Let:

- `C` be the center signal;
- `O` be the active outer signal;
- `wC = sqrt(abs(C))`;
- `wO = sqrt(abs(O))`.

The new peak-axis coordinate is:

```text
peak_axis =
    virtual_outer_spacing_mm
    * wO
    / max(epsilon, wC + wO)
```

Example:

```text
sensor spacing = 2 mm
offset = 1 mm
center = 9
outer = 4
```

The old position is:

```text
2 × 2 / (3 + 2) = 0.8 mm
```

The new position is:

```text
3 × 2 / (3 + 2) = 1.2 mm
```

The real outer sensor remains at `2 mm`.

Opposite-sign center-plus-one input must retain the existing signed-transition behavior. Do not apply the same-sign circular-peak model to a zero-crossing case.

---

## 5. Generalize the center-plus-one circular profile

The current circular-profile implementation assumes:

```text
0 < peak_axis < physical_sensor_spacing
```

After this change, the inferred peak may lie either:

- between the center and the real outer sensor; or
- beyond the real outer sensor.

Support both geometries.

Use real anchor distances:

```text
distance_to_center = abs(peak_axis)
distance_to_outer = abs(peak_axis - sensor_spacing_mm)
```

Do not use:

```text
sensor_spacing_mm - peak_axis
```

without taking the absolute value or handling point order explicitly.

The final field must still preserve:

```text
F(center) = measured center value
F(real outer sensor) = measured outer value
F(peak) = inferred peak value
```

### Generalize the axial scale

The existing evaluator assumes this point order:

```text
center → peak → real outer sensor
```

Replace it with an ordered-knot interpolation that supports both cases.

When the peak is inside the real outer sensor:

```text
(center, center_scale)
→ (peak, 1.0)
→ (real outer sensor, outer_scale)
```

When the peak is beyond the real outer sensor:

```text
(center, center_scale)
→ (real outer sensor, outer_scale)
→ (peak, 1.0)
```

Use smooth cubic interpolation between adjacent knots.

Requirements:

- exact center anchor;
- exact real outer anchor;
- exact peak;
- continuous field;
- zero derivative at the inferred peak;
- no negative interpolation denominator;
- locally circular contours near the peak;
- no seam when crossing the real outer-sensor location.

Update circular-radius feasibility calculations so the circle:

- contains both real active anchors;
- remains inside package support;
- excludes inactive outer sensors when required;
- retains strict Outer Boundary zero.

---

## 6. Update three-sensor quadrant peak location

For a same-sign quadrant with:

- center signal `C`;
- horizontal outer signal `H`;
- vertical outer signal `V`;

use virtual outer spacing independently on each axis.

Let:

```text
wC = sqrt(abs(C))
wH = sqrt(abs(H))
wV = sqrt(abs(V))
```

Calculate:

```text
peak_x =
    horizontal_direction
    * virtual_outer_spacing_mm
    * wH
    / max(epsilon, wH + wC)

peak_y =
    vertical_direction
    * virtual_outer_spacing_mm
    * wV
    / max(epsilon, wV + wC)
```

Do not normalize all three values together. Each axis remains weighted relative to the center.

Example:

```text
sensor spacing = 2 mm
offset = 1 mm
center = 9
right = 4
top = 16
```

The new peak is:

```text
x = 3 × 2 / (3 + 2) = 1.2 mm
y = 3 × 4 / (3 + 4) ≈ 1.714 mm
```

The physical right and top sensors remain at:

```text
Right = (2, 0)
Top   = (0, 2)
```

Mixed-sign quadrants must retain their existing signed-transition behavior.

---

## 7. Generalize quadrant geometry for outboard peaks

Changing only `_pressure_point()` is not sufficient.

The current quadrant implementation assumes the inferred peak lies strictly inside the physical sensor square:

```text
0 < abs(peak_x) < sensor_spacing_mm
0 < abs(peak_y) < sensor_spacing_mm
```

The new virtual positions can produce:

1. both coordinates inside the physical sensor square;
2. horizontal coordinate outside and vertical inside;
3. vertical coordinate outside and horizontal inside;
4. both coordinates outside the physical sensor square.

Do not allow `_is_peaked_pressure_point()` to silently reject a valid virtual target and convert the quadrant to peakless mode.

Introduce separate concepts:

```text
target_peak_point
final_peak_point
```

- `target_peak_point` is the unconstrained peak calculated from virtual outer positions.
- `final_peak_point` is the feasible peak actually used by field construction.

Preferred implementation:

- support outboard peak locations with a valid non-overlapping interpolation or triangulation scheme;
- preserve all real measured sensor anchors exactly;
- keep the field continuous;
- avoid uncovered and multiply-covered regions.

If the target peak is not geometrically feasible:

1. move it toward the package center only as much as required;
2. preserve the direction and relative x/y displacement where possible;
3. record that geometry limiting occurred;
4. use the existing bounded fallback only if no feasible peaked solution exists.

Projection must be a safety fallback, not the normal behavior.

---

## 8. Keep real positions for peak-height extrapolation

Virtual outer positions determine **where** the peak is inferred.

Real physical sensor positions determine the distance from each measurement to that inferred peak.

Therefore, keep `_pressure_point_height()` based on:

```text
distance from real sensor position to final inferred peak
```

Do not substitute virtual outer positions in the peak-height weighting or peak-gain-slope calculation.

The intended rule is:

```text
virtual positions determine peak location;
real positions determine measurement-to-peak distance.
```

This applies to:

- inverse-distance weighting;
- `peak_gain_slope_per_mm`;
- `maximum_peak_gain`.

---

## 9. Preserve physical sensor interpolation and anchors

The offset must not change:

- `_build_sensor_positions()`;
- displayed sensor-square positions;
- center and outer anchor coordinates;
- normal-force sensor geometry;
- physical plane coefficients through measured sensors;
- package-center spacing;
- array package placement;
- facing-sensor gap;
- Mid Boundary;
- Outer Boundary;
- exact sensor-value tests.

Do not globally replace `sensor_spacing_mm` with virtual spacing.

Use virtual spacing only in inferred peak-location calculations.

---

## 10. Decay-origin behavior

For modes with a valid inferred peak:

- use `final_peak_point` as the decay origin.

This includes:

- isolated outer;
- same-sign center-plus-one;
- same-sign peaked quadrants.

For modes without an inferred peak:

- keep the current real-sensor weighted decay origin;
- do not apply the virtual offset to peakless or signed-transition decay origins.

Opposite-sign center-plus-one and mixed-sign quadrant modes must remain unchanged.

---

## 11. Geometry feasibility and boundary handling

Validate that virtual outer spacing is compatible with package support.

At minimum:

```text
virtual_outer_spacing_mm < outer_boundary_half_width_mm
```

with an appropriate geometry margin.

For circular profiles, verify that a feasible radius can:

- include all required real active anchors;
- exclude inactive outer sensors;
- remain inside package support;
- retain strict zero at and beyond the Outer Boundary.

When the target peak is too far outward:

1. limit the peak toward the center;
2. preserve real measured anchors exactly;
3. preserve inactive-sensor zeros;
4. preserve strict Outer Boundary zero;
5. record why limiting was required;
6. use the existing non-circular fallback only when no feasible circular solution exists.

Do not move physical sensor markers to solve a field-geometry problem.

---

## 12. Center-only mode

Center-only behavior must remain unchanged.

When only the center sensor is active:

- package mode remains `center-only`;
- the peak remains at `(0, 0)`;
- the blob remains circular;
- the center value remains exact;
- the four outer sensors remain zero;
- the outer-position offset has no effect.

---

## 13. Display behavior

Do not move:

- center or outer sensor markers;
- small sensor squares in the background image;
- sensor labels;
- package outlines;
- Mid Boundary;
- Outer Boundary;
- array package centers.

The calculated peak marker must move to the final inferred peak location.

The visual interpretation must be:

- background markers show physical sensor locations;
- heatmap and peak marker show inferred contact location.

---

## 14. Diagnostics

Add or update diagnostics to expose:

```text
physical_outer_spacing_mm
virtual_outer_spacing_mm
peak_position_outer_offset_mm
target_peak_point
final_peak_point
peak_position_geometry_limited
peak_position_limit_reason
```

For center-plus-one mode, also retain:

```text
distance_to_real_center_anchor
distance_to_real_outer_anchor
circular_radius
center_factor
outer_factor
actual_peak_gain
gain_cap_satisfied
used_fallback
```

Do not report a target peak as the actual rendered peak when geometry limiting or fallback changed it.

---

## 15. Tests

### Shared geometry

Verify:

- physical outer positions remain at `sensor_spacing_mm`;
- virtual positions are at `sensor_spacing_mm + offset`;
- changing the offset does not move display markers or physical anchors.

### Isolated outer

Verify:

- peak remains at `sensor_spacing_mm + offset`;
- center remains zero;
- real active outer anchor remains exact;
- all four directions are rotationally equivalent;
- positive and negative signals preserve sign.

### Center plus one

Test:

- equal center and outer values;
- center greater than outer;
- outer greater than center;
- peak between center and real outer sensor;
- peak beyond the real outer sensor;
- all four outer directions;
- positive and negative same-sign values;
- exact center anchor;
- exact real outer anchor;
- exact inferred peak;
- circular symmetry near the peak;
- continuity through the real outer-sensor location;
- no fallback under normal geometry;
- geometry-limited behavior under extreme ratios.

### Three-sensor quadrant

Test:

- equal three signals;
- unequal horizontal and vertical signals;
- both coordinates inside the real sensor square;
- one coordinate outside;
- both coordinates outside;
- all four quadrants;
- exact center anchor;
- exact horizontal real sensor anchor;
- exact vertical real sensor anchor;
- final peak marker matches the rendered peak;
- no uncovered interpolation regions;
- no overlapping interpolation regions;
- continuity across region boundaries.

### Unchanged modes

Verify:

- center-only remains centered and circular;
- opposite-sign center-plus-one remains a signed transition;
- mixed-sign quadrant remains a signed transition;
- real sensor markers are unchanged;
- normal-force geometry is unchanged;
- array package positions are unchanged;
- strict Outer Boundary zero is unchanged.

### Offset regression

With `offset = 0`, all peak locations and rendered fields must match the previous implementation within floating-point and raster tolerance.

---

## Recommended implementation order

1. Add the new setting name and backward-compatible migration.
2. Add shared physical and virtual outer-position helpers.
3. Refactor isolated mode to use the shared helper without changing behavior.
4. Update center-plus-one target peak calculation.
5. Generalize center-plus-one circular geometry and axial interpolation.
6. Update three-sensor quadrant target peak calculation.
7. Generalize quadrant interpolation for outboard peaks.
8. Add geometry limiting and fallback diagnostics.
9. Update the peak marker and settings tooltip.
10. Add regression, symmetry, anchor, boundary, and compatibility tests.

---

## Acceptance criteria

The change is complete when:

1. All inferred outer-dependent peak locations use `sensor_spacing_mm + peak_position_outer_offset_mm`.
2. Physical sensor positions remain unchanged everywhere.
3. Isolated-outer behavior remains visually and mathematically unchanged.
4. Same-sign center-plus-one peaks may lie between or beyond the real outer sensor.
5. Same-sign quadrant peaks support coordinates outside the physical sensor square.
6. Real center and outer measured anchors remain exact.
7. Peak-height extrapolation still uses distance from real sensor locations.
8. Center-only and signed-transition modes remain unchanged.
9. Outer Boundary remains exactly zero.
10. Array and package geometry remain unchanged.
11. Offset `0` reproduces the previous behavior.
12. Existing and new tests pass.

---

## Delivery report

Provide:

- files changed;
- setting rename and migration behavior;
- shared virtual-position helper;
- formulas changed;
- center-plus-one evaluator changes;
- quadrant evaluator changes;
- geometry-limiting behavior;
- diagnostics added;
- tests added;
- before/after peak locations for:
  - one isolated outer case;
  - one center-plus-one case;
  - one three-sensor quadrant case;
- confirmation that physical sensor markers and array geometry are unchanged.
