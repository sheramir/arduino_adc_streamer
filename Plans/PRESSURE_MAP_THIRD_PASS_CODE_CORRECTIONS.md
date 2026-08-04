# Pressure Map — Local Activity and Remaining Core Corrections

**Status:** Coding-agent implementation instructions  
**Basis:** Current package generator, array generator, shared geometry, and widget.  
**Goal:** Fix the remaining array-interaction and field-shape issues without adding expensive per-pixel floating confidence models.

Preserve:

- signed backend pressure fields;
- exact sensor anchors;
- geometry-aligned raster generation;
- fixed Outer Boundary support;
- exact zero on and beyond the Outer Boundary;
- direct-neighbor linear blending;
- diagonal regularized blending;
- fixed display scaling;
- Magnitude and Signed display modes.

Do not add a second smooth floating `local_presence` field. Use a lightweight active-sensor bitmask plus a Boolean per-pixel local-presence mask derived from the already-calculated candidate field.

---

# Priority 1 — Fix local package participation and make pair blending scalable

Priorities 1–6 from the earlier draft are one combined issue: determine whether each package is actually relevant in a given overlap, then avoid unnecessary pair work.

## 1.1 Add active-sensor bitmasks

Add:

```python
ACTIVE_CENTER = 1 << 0
ACTIVE_LEFT   = 1 << 1
ACTIVE_RIGHT  = 1 << 2
ACTIVE_TOP    = 1 << 3
ACTIVE_BOTTOM = 1 << 4
```

Add to `PressureFieldModel` and `PressureMapResult`:

```python
active_sensor_mask: int
```

Build it from the already-thresholded sensor values:

```python
def build_active_sensor_mask(sensor_values: Mapping[str, float]) -> int:
    mask = 0

    if sensor_values[SHEAR_POSITION_CENTER] != 0.0:
        mask |= ACTIVE_CENTER
    if sensor_values[SHEAR_POSITION_LEFT] != 0.0:
        mask |= ACTIVE_LEFT
    if sensor_values[SHEAR_POSITION_RIGHT] != 0.0:
        mask |= ACTIVE_RIGHT
    if sensor_values[SHEAR_POSITION_TOP] != 0.0:
        mask |= ACTIVE_TOP
    if sensor_values[SHEAR_POSITION_BOTTOM] != 0.0:
        mask |= ACTIVE_BOTTOM

    return mask
```

Exact zero is appropriate because the package generator already applies signal thresholding.

## 1.2 Add Boolean local presence

Add to `_PackageCandidate`:

```python
local_present: np.ndarray  # dtype=bool
```

In `_evaluate_candidate()`:

```python
local_present = (
    support_mask
    & (np.abs(values) > PRESSURE_ARRAY_BLEND_EPSILON)
)
```

Do not create a floating smoothstep local-confidence field.

Update candidate fallback:

```python
candidate_weight = (
    candidate.support_confidence
    * candidate.activity_confidence
    * candidate.local_present
)
```

This prevents a globally active package from affecting an overlap where its own candidate field is already zero.

## 1.3 Pass through a single locally present candidate

Inside each pair overlap:

```python
first_present = first.local_present[region]
second_present = second.local_present[region]

only_first = first_present & ~second_present
only_second = second_present & ~first_present
both_present = first_present & second_present
```

Calculate:

```python
signed_pair = np.zeros_like(first.values[region], dtype=np.float64)

signed_pair[only_first] = first.values[region][only_first]
signed_pair[only_second] = second.values[region][only_second]

signed_pair[both_present] = (
    first_weight[both_present] * first.values[region][both_present]
    + second_weight[both_present] * second.values[region][both_present]
)
```

Required behavior:

```text
Only first candidate exists  -> first candidate unchanged
Only second candidate exists -> second candidate unchanged
Both candidates exist        -> geometric blend
Neither exists                -> zero
```

Use:

```python
pair_present = first_present | second_present
```

for pair participation. Do not multiply a single locally present candidate by its geometric pair weight.

## 1.4 Use active sensors as a cheap pair prefilter

Use facing-sensor activity to skip pairs that cannot contribute meaningfully.

### Horizontal neighbors

First left of second:

```text
first relevant sensor  = RIGHT
second relevant sensor = LEFT
```

First right of second:

```text
first relevant sensor  = LEFT
second relevant sensor = RIGHT
```

### Vertical neighbors

First below second:

```text
first relevant sensor  = TOP
second relevant sensor = BOTTOM
```

First above second:

```text
first relevant sensor  = BOTTOM
second relevant sensor = TOP
```

### Diagonal neighbors

Use the two sensors facing the shared corner.

Example: first is bottom-left of second:

```text
first relevant sensors  = RIGHT or TOP
second relevant sensors = LEFT or BOTTOM
```

Define the equivalent mapping for the other diagonal orientations.

Skip a pair only when neither package has:

- a relevant facing outer sensor; nor
- an active center sensor.

The bitmask is a prefilter only. Boolean `local_present` remains the final local participation rule.

## 1.5 Evaluate only true neighboring packages

Precompute eligible package pairs from grid positions:

```python
row_delta = abs(row_a - row_b)
col_delta = abs(col_a - col_b)

eligible = (
    row_delta <= 1
    and col_delta <= 1
    and not (row_delta == 0 and col_delta == 0)
)
```

Do not test non-neighbor packages.

This changes pair enumeration from approximately `O(N²)` to `O(N)` for regular arrays.

## 1.6 Restrict pair calculations to overlap slices

Add:

```python
def overlap_bounds_to_slice(
    overlap: tuple[float, float, float, float],
    x_coordinates_mm: np.ndarray,
    y_coordinates_mm: np.ndarray,
) -> tuple[slice, slice]:
    x0, x1, y0, y1 = overlap

    x_start = int(np.searchsorted(x_coordinates_mm, x0, side="left"))
    x_end = int(np.searchsorted(x_coordinates_mm, x1, side="right"))

    y_start = int(np.searchsorted(y_coordinates_mm, y0, side="left"))
    y_end = int(np.searchsorted(y_coordinates_mm, y1, side="right"))

    return slice(y_start, y_end), slice(x_start, x_end)
```

Evaluate pair weights only inside:

```python
region = np.s_[y_slice, x_slice]
```

Use sliced arrays:

```python
first.values[region]
second.values[region]
first.local_present[region]
second.local_present[region]
first.support_confidence[region]
second.support_confidence[region]
x_grid_mm[region]
y_grid_mm[region]
```

Accumulate pair numerator and denominator only in that region.

Do not allocate full-array temporary pair grids.

---

# Priority 2 — Add a separately blended magnitude field

## Problem

Current Magnitude mode applies:

```python
abs(final_signed_array_field)
```

after signed blending.

Opposite-sign candidates can cancel first:

```text
+0.8 blended with -0.8 -> 0
abs(0) -> 0
```

For a pressure-intensity view, Magnitude mode should preserve both magnitudes.

## Result change

Add:

```python
pressure_grid: np.ndarray              # signed field
magnitude_pressure_grid: np.ndarray    # blended absolute field
```

## Pair calculation

Where both candidates are present:

```python
signed_pair = (
    first_weight * first.values
    + second_weight * second.values
)

magnitude_pair = (
    first_weight * np.abs(first.values)
    + second_weight * np.abs(second.values)
)
```

Where only one candidate is present:

```python
signed_pair = candidate
magnitude_pair = abs(candidate)
```

Aggregate signed and magnitude fields using the same pair and fallback confidences.

## Widget behavior

For array display:

```python
if display_mode == PRESSURE_DISPLAY_MODE_MAGNITUDE:
    grid = array_result.magnitude_pressure_grid
else:
    grid = array_result.pressure_grid
```

For a single package:

```python
Magnitude -> abs(package.pressure_result.pressure_grid)
Signed    -> package.pressure_result.pressure_grid
```

Do not replace or remove the signed backend.

---

# Priority 3 — Add an explicit center-only package mode

## Problem

A center-active package with no active outer sensors currently falls into the general multi-sensor mode, creating an unnecessary square/diamond-like field.

## Required mode

Add:

```python
PRESSURE_PACKAGE_MODE_CENTER_ONLY = "center-only"
```

Classification:

```python
if center_active and not active_outer:
    return PRESSURE_PACKAGE_MODE_CENTER_ONLY, active_outer
```

## Center-only field

Use:

```python
radius = np.hypot(x_mm, y_mm)

value = center_value * smoothstep_fade(
    radius,
    sensor_spacing_mm,
)
```

Required properties:

- exact center value;
- exact zero at all four outer sensor coordinates;
- rotational symmetry;
- no quadrant corners;
- no square or diamond plateau;
- no extension beyond the outer-sensor radius unless later calibration explicitly requires it.

Update diagnostics and tests for this mode.

---

# Priority 4 — Correct the natural-decay reach mapping

## Problem

The current formula does not reach the configured maximum decay reach exactly.

## Required mapping

Use:

```python
normalized = (
    np.abs(strength)
    / decay_amplitude_reference
)
```

For `normalized <= 1`:

```python
reach = (
    minimum_decay_reach_mm
    + normalized
    * (
        natural_decay_reference_distance_mm
        - minimum_decay_reach_mm
    )
)
```

For `normalized > 1`:

```python
high_t = np.clip(normalized - 1.0, 0.0, 1.0)

reach = (
    natural_decay_reference_distance_mm
    + high_t
    * (
        maximum_decay_reach_mm
        - natural_decay_reference_distance_mm
    )
)
```

Meaning:

```text
zero strength             -> minimum decay reach
amplitude reference       -> natural reference reach
2 × amplitude reference   -> maximum decay reach
```

Clamp the result to:

```python
[
    minimum_decay_reach_mm,
    maximum_decay_reach_mm,
]
```

The returned field must remain exactly zero at and beyond the Outer Boundary.

---

# Required implementation sequence

1. Add active-sensor bitmask metadata.
2. Add Boolean `local_present`.
3. Fix candidate fallback.
4. Fix single-present pass-through and both-present geometric blending.
5. Add active-sensor pair prefiltering.
6. Precompute true neighbor pairs.
7. Restrict pair calculations to overlap slices.
8. Add `magnitude_pressure_grid`.
9. Add `CENTER_ONLY`.
10. Correct natural-reach mapping.
11. Add regression and performance tests.

---

# Required regression tests

## A. Inactive-neighbor invariance

Create one active package with any number of zero packages around it.

Expected:

```text
array field == standalone package field
```

after coordinate translation.

Test both signed and magnitude fields.

## B. Locally absent active package

Use two globally active packages where one candidate is zero in part of the overlap.

Expected:

```text
pair result == locally present candidate unchanged
```

## C. Both locally present

Expected:

```text
pair result == requested geometric blend
```

## D. Active-sensor prefilter

Verify irrelevant package pairs are skipped, but center-active packages are not skipped incorrectly.

## E. Neighbor-pair complexity

For a regular array of `N` packages, verify eligible pair count grows linearly rather than quadratically.

## F. Overlap-slice equivalence

Compare full-grid and overlap-slice pair calculations on a small fixture.

Expected:

```text
identical numerical result
```

## G. Magnitude cancellation

Use:

```text
first candidate  = +0.8
second candidate = -0.8
weights          = 0.5 / 0.5
```

Expected:

```text
signed field    = 0.0
magnitude field = 0.8
```

## H. Center-only mode

Verify:

- exact center value;
- exact zero at all four outer sensors;
- rotational symmetry;
- no square-quadrant artifact.

## I. Natural reach mapping

Verify:

```text
strength = 0 × reference -> minimum reach
strength = 1 × reference -> natural reference reach
strength = 2 × reference -> maximum reach
strength > 2 × reference -> maximum reach
```

## J. Outer Boundary

Verify exact zero on and outside all four boundary lines for:

```text
package candidate
signed array field
magnitude array field
```

## K. Performance

Benchmark a representative larger array and record:

```text
package count
neighbor pair count
array grid shape
average generation time
95th-percentile generation time
temporary memory allocation
```

The pair workload must scale with neighboring overlaps, not all package pairs multiplied by the full array grid.

---

# Acceptance criteria

The implementation is complete when:

1. An inactive or locally absent neighbor does not attenuate an active package.
2. Geometric blending occurs only where both candidate fields are locally present.
3. Pair evaluation is limited to neighboring packages and overlap slices.
4. Magnitude mode does not lose equal opposite-sign pressure through cancellation.
5. Center-only pressure is rotationally symmetric.
6. Natural reach reaches the configured minimum, reference, and maximum values exactly.
7. Pressure is exactly zero on and beyond every Outer Boundary.
8. All required tests pass.
9. Live update performance remains responsive for the target larger-array size.

---

# Files to update

At minimum:

- `pressure_map_generator.py`
- `pressure_map_array_generator.py`
- `pressure_map_widget.py`
- pressure-map constants
- pressure-map unit and integration tests

Update `pressure_map_geometry.py` only if new metadata requires it.

---

# Delivery report

Provide:

- files changed;
- active-sensor bitmask implementation;
- Boolean local-presence implementation;
- pair-prefilter rules;
- overlap-slice implementation;
- signed and magnitude aggregation formulas;
- center-only field formula;
- natural-reach formula;
- regression tests added;
- before/after performance measurements.
