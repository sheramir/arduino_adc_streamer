# Pressure Map Boundary and Package-Overlap Changes

Owner: Host application GUI/pressure-processing stack  
Status: Proposed change specification  
Date: 2026-07-31  
Scope: Change-only specification. This document defines the new behaviour that must replace or extend the current single-package boundary and array-gap logic. It is intended to be merged later into the full Pressure Map Tab specification.

## 1. Purpose

The pressure map must no longer assume that an isolated active outer sensor means the pressure peak is located directly on that sensor. It must also stop creating a separate synthetic pressure bridge between adjacent packages.

Instead:

1. an isolated outer-sensor response places the inferred peak just outside the package;
2. every package calculates its own pressure field beyond its sensor positions and up to a defined outer boundary;
3. each package field reaches zero at or before its outer boundary, which is a maximum support limit rather than a mandatory decay endpoint; and
4. overlapping package fields are combined using normalized spatial weights so transitions are smooth and do not create discontinuities, hard crops, dominant-value seams, or artificial inter-package peaks.

## 2. Terminology and Configurable Geometry

The following three geometric concepts must be exposed in Pressure Map settings.

### 2.1 Near-Outer Peak Offset

**Recommended UI name:** `Near-Outer Peak Offset (mm)`  
**Recommended code name:** `near_outer_peak_offset_mm`  
**Default:** `1.0 mm`

This is the distance `d` from an active outer sensor in the outward radial direction.

For outer sensor position `S` and outward unit vector `u`:

```text
near_outer_point = S + d * u
```

Examples:

```text
R: peak = (sensor_spacing + d, 0)
L: peak = (-sensor_spacing - d, 0)
T: peak = (0, sensor_spacing + d)
B: peak = (0, -sensor_spacing - d)
```

This point is the inferred peak location when exactly one outer sensor is active and all other package sensors are below the noise threshold.

The term **Near-Outer Peak Offset** is preferred over a generic “near outer boundary” name because the parameter directly controls an inferred peak anchor rather than the final zero-valued support boundary.

### 2.2 Mid Boundary

**Recommended UI name:** `Mid-Boundary Position`  
**Recommended code name:** `mid_boundary_fraction`  
**Default:** `0.5`

For two directly neighboring packages, the Mid Boundary is the divider between their facing physical package edges.

Let:

```text
E1 = facing physical edge of package 1
E2 = facing physical edge of package 2
```

Then:

```text
M = E1 + mid_boundary_fraction * (E2 - E1)
```

The default `0.5` places the boundary at the exact midpoint. The symmetric package model therefore uses the same Mid Boundary for both packages.

The setting may remain configurable for calibration or future asymmetric package layouts, but the normal/default configuration is `0.5`.

### 2.3 Outer-Boundary Reach

**Recommended UI name:** `Outer-Boundary Reach (mm)`  
**Recommended code name:** `outer_boundary_reach_mm`  
**Default:** automatic distance from the Mid Boundary to the facing edge of the neighboring package.

For package 1 extending toward package 2:

```text
O1 = M + outer_boundary_reach_mm * direction_toward_package_2
```

For package 2 extending toward package 1:

```text
O2 = M + outer_boundary_reach_mm * direction_toward_package_1
```

With the default automatic value:

```text
O1 = E2
O2 = E1
```

Therefore, each package field may extend across the inter-package region up to the near edge of its neighbor.

A package's calculated pressure must be zero **at or before** its own Outer Boundary. The Outer Boundary is the farthest permitted support limit; it is not a requirement to stretch or normalize every pressure lobe so that its last non-zero value occurs exactly on that line.

The existing/configured pressure-decay behaviour remains responsible for the natural decay distance. A smaller pressure value may decay to zero before the Outer Boundary and must then remain zero for the rest of the support. A stronger peak may still be non-zero near the boundary, in which case a terminal boundary constraint must make it approach zero continuously no later than the Outer Boundary. Positive pressure approaches zero from above and negative pressure approaches zero from below.

## 3. Noise and Active-Sensor Definition

The existing thresholded/calibrated package values remain the source for pressure-map classification.

A sensor is **off** when its thresholded value is zero. Equivalently:

```text
abs(raw_integrated_value) < noise_threshold
```

before the existing package gain is applied.

The new isolated-outer rule applies only when:

```text
exactly one of L/R/T/B is active
and C is off
and the other three outer sensors are off
```

No other input pattern uses the new isolated-outer peak rule.

## 4. Single-Package Isolated-Outer Behaviour

### 4.1 Peak location

When the isolated-outer condition is true, the peak must be moved from the physical outer-sensor coordinate to the Near-Outer point defined by `near_outer_peak_offset_mm`.

The inferred peak must lie on the same radial axis as the active sensor.

### 4.2 Peak value

The default peak value is the calibrated value of the active outer sensor. The new rule must not create additional gain or overshoot solely because the peak was moved outside the package.

```text
peak_value = active_outer_sensor_value
```

Any future peak-height extrapolation must be a separate setting and is not part of this change.

### 4.3 Surface construction

The pressure surface must be continuous from the center-side region, through the active outer sensor, to the inferred peak, and then toward the applicable Outer Boundary.

The map must not form a broad constant plateau around the active outer sensor.

For the active axis:

1. calculate the current/local surface up to the outer sensor;
2. continue or interpolate the surface to the inferred peak at `sensor + d`;
3. apply the configured natural pressure decay from the inferred peak; if that decay reaches zero before the Outer Boundary, keep the remaining region at zero; otherwise apply the terminal boundary constraint so the field reaches zero no later than the Outer Boundary.

The transverse direction must retain a smooth lateral decay so that the isolated response remains localized around the active sensor axis.

### 4.4 Symmetry

The implementation must be rotationally symmetric for R, L, T, and B. Mirroring or rotating the input pattern must produce the corresponding mirrored or rotated pressure field.

## 5. Package Support and Boundary Decay

### 5.1 No computational image cropping

The package-local pressure field must not be hard-cropped at the previous circular mask, package edge, or local image boundary.

The former mutually exclusive `Circle` / `Square` / `None` boundary selector is replaced by independent visualization toggles described in Section 13.1. These overlays are rendering-only and must never abruptly zero, clip, or otherwise modify the calculated field.

Each package must be evaluated over its complete world-space support region up to its configured Outer Boundaries.

### 5.2 Natural decay and maximum outer support

The configured pressure-decay model must be evaluated independently of the Outer Boundary. The boundary must not be used to rescale the decay rate or force every lobe to consume the complete available distance.

Define:

```text
P_natural(x, y) = pressure predicted by the local interpolation and configured decay model
D_natural_zero = distance at which that model reaches/clamps to zero, when finite
D_boundary = distance from the decay anchor to the applicable Outer Boundary
D_effective_end = min(D_natural_zero, D_boundary)
```

Behaviour: 

- When `D_natural_zero < D_boundary`, the field reaches zero naturally before the boundary and remains zero from that point outward.
- When `D_natural_zero >= D_boundary`, or the natural model would only approach zero asymptotically, a terminal boundary constraint must smoothly bring the remaining value to zero by the Outer Boundary.
- The implementation must not reduce the decay slope merely to make a small pressure value remain non-zero until the boundary.

A boundary envelope may be used as the terminal constraint. For an axis coordinate `q`, a decay anchor `A`, and Outer Boundary `O`:

```text
b(q) = clamp((O - q) / (O - A), 0, 1)       # positive-axis direction
b(q) = clamp((q - O) / (A - O), 0, 1)       # negative-axis direction
```

One acceptable implementation is:

```text
P_candidate(x, y) = P_natural(x, y) * b_x(x) * b_y(y)
```

provided that `P_natural` is allowed to reach/clamp to zero earlier and is not normalized to the boundary. Once the candidate reaches zero, it remains zero.

The required invariant is therefore:

```text
P_candidate = 0 at or before every applicable Outer Boundary
P_candidate = 0 on and outside every applicable Outer Boundary
```

For a corner region where two boundary constraints apply, use the product of the two envelopes or an equivalent continuous two-axis constraint.

## 6. Replacement of Current Array-Gap Behaviour

The current special gap-generation logic must be removed or bypassed.

The new array result must not:

- create a separate axial gap bridge;
- create an extrapolated inter-package peak from facing sensor contrast;
- apply a triangular lateral gap fade;
- let the candidate with the largest absolute value replace the other package in an overlap; or
- exclude diagonal neighbors from overlap processing.

The settings and code paths for `gap_contrast_gain` and `gap_fade_width_fraction` become obsolete for the new algorithm and should be removed from the UI, persistence payload, and calculation after a compatibility/migration period.

`package_gap_mm` remains valid because it defines physical package placement and therefore the Mid and Outer Boundary geometry.

## 7. Candidate-First Array Calculation

For every complete package:

1. place the package in world coordinates;
2. calculate its candidate pressure value at every world-grid pixel inside its support region;
3. preserve its natural decay and guarantee that its candidate value reaches zero at or before its Outer Boundary; and
4. retain the candidate field separately until overlap blending is complete.

Do not merge package grids while they are being generated.

For world pixel `p`, define the set of contributing packages:

```text
C(p) = { package i whose support contains p }
```

The final pixel is selected by the number and geometry of contributors.

## 8. Two-Package Overlap: Direct Neighbors

This section applies to horizontal or vertical neighbors.

### 8.1 Shared interval

The shared overlap is the intersection of the two package support regions.

For a horizontal pair, let the overlap span from `x0` to `x1`, left to right:

```text
u = clamp((x - x0) / (x1 - x0), 0, 1)
```

For a vertical pair, use the equivalent normalized `y` coordinate from the first package side to the second package side.

### 8.2 Linear weights

For package A on the first side and package B on the second side:

```text
w_A = 1 - u
w_B = u
P = w_A * P_A + w_B * P_B
```

Required values:

```text
first edge:  w_A = 1.0, w_B = 0.0
midpoint:    w_A = 0.5, w_B = 0.5
second edge: w_A = 0.0, w_B = 1.0
```

The weights must always satisfy:

```text
w_A >= 0
w_B >= 0
w_A + w_B = 1
```

The blend is a signed linear combination of the two package candidate values. No overshoot is allowed: the result must remain within the numerical range bounded by `P_A` and `P_B` at that pixel.

## 9. Two-Package Overlap: Diagonal Neighbors

Diagonal pairs are now valid contributors. This includes:

- Top-Left / Bottom-Right; and
- Top-Right / Bottom-Left.

Let the rectangular shared overlap span:

```text
x0 <= x <= x1
y0 <= y <= y1
```

Define normalized coordinates:

```text
u = clamp((x - x0) / (x1 - x0), 0, 1)
v = clamp((y - y0) / (y1 - y0), 0, 1)
```

The raw package weights are the opposite sub-areas associated with each package corner.

### 9.1 Bottom-Left and Top-Right pair

```text
r_BL = (1 - u) * (1 - v)
r_TR = u * v
```

### 9.2 Top-Left and Bottom-Right pair

```text
r_TL = (1 - u) * v
r_BR = u * (1 - v)
```

Normalize the selected pair:

```text
w_1 = r_1 / (r_1 + r_2)
w_2 = r_2 / (r_1 + r_2)
P = w_1 * P_1 + w_2 * P_2
```

This implements the required area-ratio weighting.

If `r_1 + r_2` is below the geometry epsilon, use equal weights `0.5/0.5`. This only occurs at degenerate corners where both diagonal area terms are zero.

## 10. Three-Package Shared Overlap

When three package supports contribute to the same pixel, calculate one weighted pair blend for each package pair.

For packages A, B, and C:

```text
P_AB = pair_blend(A, B, x, y)
P_AC = pair_blend(A, C, x, y)
P_BC = pair_blend(B, C, x, y)

P_final = (P_AB + P_AC + P_BC) / 3
```

Each `pair_blend` must use:

- the linear axis rule for horizontal/vertical pairs; or
- the area-ratio rule for diagonal pairs.

The three-pair average must be calculated from the original package candidate values, not from previously merged intermediate pixels.

This preserves symmetry and prevents calculation order from affecting the result.

## 11. Four-or-More Package Overlap

Four-package overlap is not defined by the required change and must not be implemented implicitly using iteration order or dominant-value replacement.

Recommended future-compatible extension:

```text
P_final = average of all unique pair_blend(i, j) values
```

For `N` packages this uses `N*(N-1)/2` pairs. This generalization produces the specified three-package formula when `N = 3`.

Until this extension is approved, a four-or-more contributor condition must be logged and handled by an explicitly documented fallback.

## 12. Sign, Zero, and Rendering Behaviour

Overlap blending must operate on the signed candidate pressure values.

The new overlap algorithm does not introduce a separate sign policy. Existing package-level negative-pressure and rendering settings remain in effect.

Important consequences:

- same-sign candidates blend smoothly;
- opposite-sign candidates may cross through zero naturally;
- the weighted result cannot exceed the candidate extrema because all weights are normalized and non-negative; and
- every package candidate is zero at or before its Outer Boundary and remains zero outside it, preventing a discontinuity where its support ends.

The widget may continue to render magnitude using the existing display policy after the signed world-grid calculation is complete. Boundary overlays are drawn afterward and must not participate in pressure calculation, support masking, blending, or image-level selection.

## 13. Settings, Boundary Visualization, and Persistence Changes

Add these geometry settings:

| UI label | Recommended key | Default | Validation |
| --- | --- | ---: | --- |
| Near-Outer Peak Offset (mm) | `near_outer_peak_offset_mm` | `1.0` | `>= 0`; must remain inside the applicable outer support |
| Mid-Boundary Position | `mid_boundary_fraction` | `0.5` | strictly between `0` and `1` |
| Outer-Boundary Reach (mm) | `outer_boundary_reach_mm` | `Auto: neighbor edge` | `> 0`; resulting support must remain non-degenerate |

### 13.1 Independent boundary-visualization toggles

The Settings GUI must provide three independent checkboxes/toggles. The user may enable any combination, including all three simultaneously:

| UI label | Recommended key | Visual geometry |
| --- | --- | --- |
| Show Near-Outer Peak Circle | `show_near_outer_peak_circle` | Circle centered on the package center and passing through the four Near-Outer peak locations |
| Show Mid Boundary | `show_mid_boundary` | Axis-aligned Mid square through the calculated Mid Boundaries |
| Show Outer Boundary | `show_outer_boundary` | Axis-aligned square through the calculated Outer Boundaries |

These controls replace the former mutually exclusive `Circle` / `Square` / `None` boundary-shape selector. They affect visualization only and must not change the pressure field.

#### Near-Outer Peak Circle

The circle visualizes the configured Near-Outer Peak Offset. It is centered on the package center. Its radius is the center-to-outer-sensor spacing plus the offset:

```text
near_outer_circle_radius = sensor_spacing_mm + near_outer_peak_offset_mm
near_outer_circle_diameter = 2 * (sensor_spacing_mm + near_outer_peak_offset_mm)
```

Therefore, the circle passes through the isolated-outer inferred peak positions for R, L, T, and B. It must update immediately when either sensor spacing or `near_outer_peak_offset_mm` changes.

#### Mid-Boundary square

The Mid square connects the four package-local Mid Boundary lines. Under the assumed symmetric geometry it is centered on the package center and axis-aligned.

Its stroke must use a dashed pattern whose dash spacing is visibly different from the Outer-Boundary square. The distinction must remain visible at normal zoom levels and in every supported color scheme.

#### Outer-Boundary square

The Outer-Boundary square connects the four effective Outer Boundary lines and therefore visualizes the maximum permitted support of that package. Under the assumed symmetric geometry it is centered on the package center and axis-aligned.

The square is only an overlay. A pressure lobe may already be zero inside this square because of natural decay; the visualization must not imply that pressure is required to remain non-zero up to the square.

#### Array display

In an array view, each enabled overlay is drawn independently for every visible package using that package's world-space center and effective geometry. Overlays may intersect or overlap. They must remain attached to their package when mirroring or repositioning the array.

### 13.2 Persistence and migration

Persist the three geometry settings and the three visualization toggles in the Pressure Map settings payload.

When loading an older payload:

- old `Boundary = Circle` maps to `show_near_outer_peak_circle = true`;
- old `Boundary = Square` maps to `show_outer_boundary = true`;
- old `Boundary = None` maps to all three visualization toggles being false; and
- `show_mid_boundary` defaults to false because no equivalent legacy overlay existed.

Deprecate these settings after migration:

| Existing setting | New status |
| --- | --- |
| Gap Contrast | Removed; no synthetic inter-package peak |
| Gap Fade Width | Removed; package fields provide their own boundary decay |

Loading an older payload must assign missing geometry defaults and perform the visualization migration above without failing.

## 14. Required Implementation Changes

### 14.1 Single-package generator

- Add the isolated-outer peak-offset parameter.
- Replace the current isolated-outer broad/radial-only behaviour with an explicit peak outside the active sensor.
- Evaluate package pressure beyond the previous circular computational mask.
- Preserve the configured natural decay, allow zero to occur before the boundary, and enforce a continuous zero-valued maximum support boundary.
- Keep all three optional boundary overlays independent from the numerical support.

### 14.2 Array generator

- Build and retain one candidate world grid per package.
- Replace in-place package pasting and absolute-dominant replacement.
- Remove the special direct-neighbor gap bridge.
- Include diagonal package pairs.
- Detect two-package and three-package shared support regions.
- Blend from original candidate grids using the formulas in this document.
- Make the result independent of package iteration order.

### 14.3 GUI and persistence

- Add the three geometry settings.
- Replace the single boundary-shape selector with three independent visualization toggles.
- Draw the Near-Outer circle, Mid square, and Outer square from the actual current geometry.
- Use distinct dash spacing for the Mid and Outer squares.
- Remove or deprecate Gap Contrast and Gap Fade Width.
- Show units and automatic/default behaviour clearly.
- Persist all geometry and visualization settings and migrate older saved settings safely.

## 15. Acceptance Criteria

### 15.1 Isolated outer sensor

For each of R/L/T/B:

1. only that outer sensor is above threshold;
2. C and the other outer sensors are off;
3. the inferred peak is exactly `near_outer_peak_offset_mm` outside the active sensor;
4. the peak is not placed directly on the sensor;
5. the field is localized around the active axis; and
6. the field reaches zero continuously at or before its Outer Boundary and remains zero afterward.

### 15.2 Direct-neighbor blend

For two overlapping horizontal or vertical packages:

- first overlap edge equals package A candidate;
- overlap midpoint is `0.5*A + 0.5*B`;
- second overlap edge equals package B candidate;
- no seam appears where dominance changes;
- no synthetic peak exceeds both candidates; and
- swapping package input order does not change the result.

### 15.3 Diagonal blend

For both diagonal orientations:

- weights follow the normalized area formulas;
- weights are non-negative and sum to one;
- the field transitions toward the geometrically closer package corner; and
- swapping package input order only swaps the labels, not the final value.

### 15.4 Three-package overlap

For every pixel shared by A/B/C:

```text
result == (pair_blend(A,B) + pair_blend(A,C) + pair_blend(B,C)) / 3
```

The result must be independent of package generation and pair-processing order.

### 15.5 Boundaries

- every package candidate is zero at or before its configured Outer Boundary;
- low-amplitude fields may reach zero earlier according to the configured decay factor and must not be stretched to the boundary;
- high-amplitude fields that would otherwise extend farther are brought continuously to zero no later than the boundary;
- no hard crop occurs at the Near-Outer circle, Mid square, or Outer square;
- no non-zero value exists on or outside a package's support; and
- overlap transitions remain continuous up to numerical grid tolerance.


### 15.6 Boundary visualization

- each of the three overlays can be enabled or disabled independently;
- enabling or disabling any overlay does not change any pressure-grid value;
- the Near-Outer circle is centered on the package and has diameter `2 * (sensor_spacing_mm + near_outer_peak_offset_mm)`;
- the Near-Outer circle passes through all four isolated-outer peak locations;
- the Mid square lies on the calculated Mid Boundaries;
- the Outer square lies on the calculated Outer Boundaries;
- the Mid and Outer squares use visibly different dash spacing;
- all selected overlays are drawn for every package in array mode; and
- mirror and array-position transforms move the overlays consistently with their package geometry.

## 16. Tests to Add or Replace

### Single-package tests

- isolated R/L/T/B peak offset;
- noise-threshold transition into and out of isolated-outer mode;
- center-active case does not use isolated-outer mode;
- two-outer-active case does not use isolated-outer mode;
- zero at or before each outer support boundary;
- no numerical crop at the visual circle;
- rotational and mirror symmetry; and
- Near-Outer circle radius/diameter and peak-intersection geometry.

### Array tests

- two-package horizontal weights at 0%, 50%, and 100%;
- two-package vertical weights at 0%, 50%, and 100%;
- both diagonal area-weight orientations;
- three-package pair-average rule;
- signed opposite-value transition through zero;
- output invariant under package-order permutations;
- no value overshoot from blending;
- no use of gap contrast or gap fade settings;
- no absolute-dominant replacement seam; and
- zero at or before each contributing package's outer support boundary, including tests where a low-amplitude field dies out earlier.

### Widget and settings tests

- each boundary overlay toggle works independently and in every combination;
- toggling overlays leaves the numeric pressure grid unchanged;
- Near-Outer circle diameter follows `2 * (sensor_spacing_mm + near_outer_peak_offset_mm)`;
- Mid and Outer squares match their computed boundary positions;
- Mid and Outer squares use different dash spacing;
- all enabled overlays repeat per package in array mode;
- overlays follow mirror and package-position transforms; and
- legacy Circle/Square/None settings migrate to the new toggles correctly.

## 17. Out of Scope for This Change-Only Specification

- changes to ADC acquisition, integration, calibration, shear extraction, or normal-force calculation;
- changes to package gains or noise-threshold order;
- a new physical pressure calibration model;
- a new colour palette or legend calculation;
- a final rule for four-or-more simultaneous package contributors, unless the recommended all-pairs extension is approved; and
- the complete rewrite of the original Pressure Map Tab specification, which will be performed after this change specification is reviewed.
