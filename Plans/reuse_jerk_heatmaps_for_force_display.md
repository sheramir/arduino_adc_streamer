# Coding Agent Prompt — Rework Force Display to Reuse Jerk Heatmap Shapes

## Objective

Change the current **Pressure Map → Force Display** architecture so that Force Display does **not generate its own pressure-map/heatmap shapes**.

The Jerk Display already generates the desired spatial heatmap shape using the existing:

- `PressureMapGenerator`
- Pressure Map geometry
- activity classification
- peak positioning
- decay reach
- outer-boundary behavior
- package interactions

The Force Display should reuse those **already-generated Jerk package heatmaps** as spatial shapes and only accumulate reconstructed physical force onto those shapes.

The goals are:

1. Force Display must have the **same spatial heatmap shape and extent as Jerk Display**.
2. Do not run `PressureMapGenerator.generate()` separately for Force Display.
3. Avoid calculating full heatmap pixels for every acquired Force sample.
4. Keep Force reconstruction sample-accurate.
5. Make Force visualization smooth and computationally inexpensive.
6. Preserve signed Force internally, but render Force magnitude using absolute value.
7. Do not change Jerk Display numerical or visual behavior.

---

## Current Problem

The current Force engine reconstructs `ΔF` for every acquisition sample and then does something equivalent to:

```python
shear = shear_detector.detect(delta_force)
normal = normal_force_calculator.compute(shear.residual)

package.normal_force_n += normal.total_force

increment_map = pressure_map_generator.generate(normal.normalized)
package.accumulated_force_grid_n += increment_map.pressure_grid
```

This is wrong for the desired Force Display behavior because it makes Force spatial behavior depend on tiny per-sample Newton increments and performs unnecessary raster generation.

---

## Required New Architecture

Separate **Force amplitude** from **spatial shape**.

The physical Force engine determines how much force changes.

The Jerk Pressure Map determines where that force is spatially distributed.

```text
RAW PZT DATA
    │
    ├──────────────────────────────────────────────┐
    │                                              │
    ▼                                              ▼
Force reconstruction                       Existing Jerk pipeline
per acquisition sample                     normal map update rate
    │                                              │
    ▼                                              ▼
ΔNormal Force                              PressureMapGenerator
Normal Force                               already-generated package heatmap
Shear Force                                         │
    │                                               │
    │                                      normalize spatial shape
    │                                               │
    └──────── pending ΔNormal Force ────────×───────┘
                                                    │
                                                    ▼
                                      accumulated Force raster
                                                    │
                                                    ▼
                                          magnitude rendering
                                                    │
                                                    ▼
                                             Force Display
```

---

## P0 — Remove `PressureMapGenerator` from the live Force sample loop

The Force engine must no longer execute:

```python
pressure_map_generator.generate(...)
```

for every reconstructed Force sample.

The Force acquisition loop should contain only inexpensive scalar/vector calculations:

```text
PZT voltage → ΔF
shear separation
normal-force increment
package Normal Force
package Shear X/Y
quiet/reset state
```

No spatial raster generation belongs in this path.

---

## P0 — Add pending Normal Force accumulation

Add package state conceptually equivalent to:

```python
@dataclass
class ForcePackageState:
    channel_states: dict

    normal_force_n: float
    shear_x_n: float
    shear_y_n: float

    pending_normal_delta_n: float

    accumulated_force_grid_n: np.ndarray

    quiet_sample_count: int
    has_force_activity: bool
```

For every acquired synchronized Force observation:

```python
shear = shear_detector.detect(delta_force)
normal = normal_force_calculator.compute(shear.residual)

package.normal_force_n += normal.total_force
package.shear_x_n += shear.b_lr
package.shear_y_n += shear.b_tb
package.pending_normal_delta_n += normal.total_force
```

Do not generate a raster here.

---

## P0 — Reuse the exact Jerk package heatmap

The existing Jerk pipeline already creates package pressure results containing:

```python
package.pressure_result.pressure_grid
```

Use that exact already-generated grid as the Force spatial shape.

Do not reconstruct it.

Do not regenerate it.

Do not call `PressureMapGenerator` again for Force.

---

## P0 — Add a Force-engine method to consume Jerk shapes

Add an API conceptually similar to:

```python
pressure_force_engine.apply_jerk_shapes(package_displays)
```

For each package:

1. get the current already-generated Jerk `pressure_grid`;
2. convert it to a positive spatial shape;
3. normalize it;
4. multiply by pending signed Normal Force;
5. add to the accumulated Force raster;
6. clear pending Force after successful application.

Conceptually:

```python
jerk_grid = np.asarray(
    package_display.pressure_result.pressure_grid,
    dtype=np.float64,
)

shape = np.abs(jerk_grid)
peak = np.max(shape)

if peak > epsilon:
    shape = shape / peak

    package_state.accumulated_force_grid_n += (
        shape * package_state.pending_normal_delta_n
    )

    package_state.pending_normal_delta_n = 0.0
```

---

## Important — Jerk grid provides shape only

Do not directly accumulate Jerk pixel values.

Use:

```text
Jerk grid → normalized spatial shape
Force ΔN  → physical amplitude
```

Specifically:

```python
normalized_shape = abs(jerk_grid) / max(abs(jerk_grid))
force_grid += normalized_shape * pending_normal_delta_n
```

---

## Important — Preserve signed Force internally

Do not use:

```python
abs(pending_normal_delta_n)
```

for physical accumulation.

Correct:

```python
accumulated_force_grid_n += (
    normalized_shape * pending_normal_delta_n
)
```

This allows unloading/release increments to reduce previously accumulated Force.

---

## Force visualization remains magnitude-only

The stored Force raster remains signed.

The Force Display renders:

```python
display_grid = np.abs(accumulated_force_grid_n)
```

Therefore:

```text
+1 N → same heatmap intensity as -1 N
-1 N → same heatmap intensity as +1 N
```

Do not change the sign of:

- Normal Force numerical readout;
- Shear state;
- physical accumulated Force.

Only the displayed heatmap uses magnitude.

---

## P0 — Jerk shape generation must be shared, not duplicated

The Jerk package pressure maps must be calculated exactly once per map-update cycle.

```text
build package Jerk PressureMapResults ONCE
             │
             ├──> Jerk Display renderer
             │
             └──> Force engine shape consumer
```

Never generate an identical heatmap a second time for Force.

---

## P0 — Jerk shapes must continue updating when Force tab is selected

Jerk spatial-shape calculation must not depend on the Jerk tab being visible.

Refactor package-result creation away from rendering:

```python
package_results = build_pressure_map_package_results()

pressure_force_engine.apply_jerk_shapes(package_results)

if jerk_tab_visible:
    render_jerk(package_results)

if force_tab_visible:
    render_force()
```

When Force Display is selected:

- still calculate the shared Jerk package shapes;
- do not render Jerk unnecessarily;
- pass the shapes to Force;
- render only Force.

---

## P0 — Do not lose Force samples between Jerk-shape frames

Multiple Force samples may arrive before the next Jerk shape.

`pending_normal_delta_n` must accumulate all of them.

Example:

```text
+0.004 N
+0.006 N
+0.003 N
+0.007 N
```

becomes:

```text
pending_normal_delta_n = +0.020 N
```

The next valid Jerk shape consumes the entire `+0.020 N` once.

---

## P0 — Do not consume pending Force more than once

After successful shape application:

```python
pending_normal_delta_n = 0.0
```

Do not reapply pending Force on:

- repaint;
- resize;
- tab change;
- color-scale change;
- mask change;
- cached redraw.

Force accumulation belongs in data/update processing, not rendering callbacks.

---

## P0 — Handle missing or zero Jerk shapes safely

If:

```python
max(abs(jerk_grid)) <= epsilon
```

then:

```text
do not modify accumulated Force raster
do not clear pending_normal_delta_n
```

Keep pending Force until a valid spatial shape is available.

A package reset must clear pending Force so stale force cannot survive indefinitely.

---

## P0 — Package reset must clear pending Force

All reset mechanisms must clear:

```text
channel integrators
normal_force_n
shear_x_n
shear_y_n
pending_normal_delta_n
accumulated_force_grid_n
quiet_sample_count
has_force_activity
event state
```

This includes:

- bipolar/event reset;
- consecutive-quiet-sample reset;
- manual Reset Force Display.

The package remains visible in the configured array at zero Force.

---

## P1 — Do not add Force-specific spatial parameters

Do not add:

```text
Force map activity threshold
Force decay amplitude reference
Force spatial reach
Force peak gain parameters
```

The Jerk Pressure Map remains the single spatial model.

Force inherits the same shape behavior automatically.

---

## P1 — Preserve existing Pressure Map shape settings

Force should follow the same Jerk spatial settings:

```text
Sensor spacing
Package center spacing
Peak-position outer offset
Outer-Boundary Reach
Peak gain slope
Peak gain cap
Natural reach
Decay amplitude reference
Min decay reach
Max decay reach
Activity threshold
Pixels/mm
array overlap behavior
```

Changing a shape/geometry setting should reset existing accumulated Force history because previous pixels used a different spatial model.

Presentation-only changes should not reset Force.

---

## P1 — Keep current Force array composition

Each package remains authoritative in local package coordinates:

```python
accumulated_force_grid_n
```

At render time, compose all current local Force rasters into the world-space array.

Do not accumulate directly into one permanent world-space array raster.

Keep separate signed and magnitude array fields so opposite-signed overlapping package fields do not cancel before visualization.

---

## P1 — Performance target

### Every acquisition sample

```text
PZT force reconstruction
shear calculation
normal calculation
scalar/vector accumulation

NO raster generation
NO image creation
NO PressureMapGenerator
```

### Normal Pressure Map update rate

```text
generate Jerk package pressure maps once

for each package:
    reuse existing grid
    abs()
    max()
    normalize
    multiply by pending ΔNormal
    accumulated-grid add

render visible tab
```

Keep rendering decoupled from acquisition rate.

---

## P1 — Keep Force numerical readouts physical

Normal and Shear readouts must remain derived from Force reconstruction.

Do not derive them from Jerk maps or Force pixels.

Jerk heatmaps provide **shape only**.

---

# Tests

## Test 1 — Force uses exact Jerk shape

Given a deterministic Jerk `pressure_grid` and:

```text
pending ΔNormal = +0.5 N
```

verify:

```python
expected = (
    np.abs(jerk_grid)
    / np.max(np.abs(jerk_grid))
    * 0.5
)
```

and:

```python
force_grid == expected
```

within tolerance.

## Test 2 — Negative Force uses same shape

With:

```text
pending ΔNormal = -0.5 N
```

verify the signed Force raster is the negative of the positive case, while its absolute visualization is identical.

## Test 3 — No Force-side map generation

Patch/mock `PressureMapGenerator.generate()` in the Force sample path and verify thousands of Force samples perform zero Force-side map-generation calls.

## Test 4 — Multiple Force samples before one shape

Process:

```text
+0.01
+0.02
-0.005
+0.015 N
```

without applying a shape.

Verify:

```text
pending = +0.040 N
```

Then apply one Jerk shape and verify the full pending value is consumed once.

## Test 5 — Zero Jerk shape does not consume pending Force

With:

```text
pending = 0.1 N
jerk_grid = all zeros
```

verify pending Force remains `0.1 N`.

## Test 6 — Force shape matches Jerk extent

If Jerk extends near the outer package boundary, Force must inherit the same normalized support and must not shrink because `ΔF` is small.

## Test 7 — All packages

Provide different Jerk shapes for multiple packages and verify every package receives its own current Jerk shape.

The center package must receive no special treatment.

## Test 8 — Reset

After nonzero pending and accumulated Force, reset must clear both.

## Test 9 — Jerk hidden / Force visible

When Force Display is selected, verify shared Jerk package shapes continue to be generated without unnecessarily rendering Jerk.

## Test 10 — Jerk regression

Confirm unchanged:

```text
Jerk package pressure grids
Jerk array grid
Jerk activity threshold
Jerk decay reach
Jerk peak behavior
Jerk boundaries
Jerk masking
Jerk visual output
```

---

# Suggested Implementation Order

1. Add `pending_normal_delta_n` to package Force state.
2. Remove `PressureMapGenerator.generate()` from `PressureForceDisplayEngine.process_sample()`.
3. Keep sample-level Normal/Shear scalar accumulation.
4. Refactor Jerk package-result creation so it is independent of Jerk rendering.
5. Add `apply_jerk_shapes(...)` to the Force engine.
6. Feed already-generated Jerk package results to Force once per map update.
7. Normalize Jerk grids and multiply by pending signed Normal Force.
8. Clear pending Force only after successful shape application.
9. Preserve/reset pending Force correctly.
10. Keep Force array composition unchanged.
11. Add performance and regression tests.

---

# Acceptance Criteria

- [ ] Force sample processing never calls `PressureMapGenerator.generate()`.
- [ ] The expensive Jerk heatmap is calculated only once per map update.
- [ ] The exact same Jerk package heatmap shape is reused by Force.
- [ ] Force map spatial extent matches the current Jerk map shape.
- [ ] Force no longer has its own amplitude-dependent spatial decay behavior.
- [ ] Every package can show the same type of Force heatmap behavior as its Jerk map.
- [ ] `ΔNormal Force` is accumulated between Jerk map updates.
- [ ] Pending Force is consumed exactly once.
- [ ] Force raster remains signed internally.
- [ ] Force visualization always renders absolute magnitude.
- [ ] `+1 N` and `-1 N` have identical displayed color/intensity.
- [ ] Numerical Normal Force remains signed.
- [ ] Shear remains based on the physical Force calculation.
- [ ] Package reset clears pending and accumulated Force.
- [ ] Force Display continues to update while Jerk Display is hidden.
- [ ] No duplicate Jerk/Force heatmap calculation exists.
- [ ] Full static package array remains visible.
- [ ] Jerk Display behavior is unchanged.
- [ ] Acquisition performance is not degraded by Force raster generation.
