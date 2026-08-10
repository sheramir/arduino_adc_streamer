# Plan: Force Display Layer Stack, Derived Package State, and Baseline Reset

## Objective

Fix the Force Display so that:

- the numerical Normal/Shear force stops running away to unrealistic values;
- the Force raster decreases when physical pressure decreases and returns to exact
  black when the force returns to zero;
- resetting/replacing the Time Series baseline immediately clears Force state;
- the Force Display keeps reusing already-generated Jerk heatmap shapes and adds no
  new pressure-map rasterization at acquisition rate.

This plan implements the proposal in
`force_display_layer_removal_reset_architecture.md` with three corrections
documented in "Deviations from the proposal" below.

---

## 1. Verified current-state facts

These were verified directly in the code (not taken from the proposal):

1. **Package Normal accumulation is mathematically equivalent to derived state.**
   `normal.total_force = sum(normalized) + 5*offset = sum(residual)`
   (`data_processing/normal_force_calculator.py:105-110`), and the shear strain
   vector sums to zero (`data_processing/shear_detector.py:114-120`), so
   `sum(residual) = sum(input deltas)`. Therefore the current
   `package.normal_force_n += normal.total_force`
   (`data_processing/pressure_force_display.py:168`) accumulates exactly the sum of
   the five channel deltas, which equals the sum of the channel accumulators
   (channels never self-reset: `reset_on_event_complete=False`,
   `pressure_force_display.py:245`). Switching to derived state does **not** change
   the Normal readout. It **does** change Shear (see fact 3).

2. **The Normal runaway mechanism is a non-decaying baseline offset, not double
   integration.** Each integrator step adds
   `(C/d33)·correction·(v − α·v_prev)`
   (`data_processing/pzt_force_calculation.py:173-175`). A real sustained press
   decays through the leak (`v ≈ α·v_prev` ⇒ increment → 0). A *non-decaying* DC
   offset above `noise_threshold_v` (wrong/stale/mid-press-captured baseline) adds
   `(C/d33)·(1−α)·offset` every sample, forever, and keeps the channel `active` so
   the quiet reset (`pressure_force_display.py:280-283`) never fires. At
   acquisition rate this ramps linearly to thousands of newtons. The fix is the
   baseline-reset hook (step 4), not the derived-state refactor.

3. **Per-delta shear detection is a noise rectifier.** `ShearDetector.detect` runs
   on per-sample deltas (`pressure_force_display.py:166`); opposite-sign noise
   deltas register as a shear pair every sample and integrate into a random walk
   via `package.shear_x_n += shear.b_lr` (`pressure_force_display.py:169-170`).
   Detecting on current accumulated channel forces removes this.

4. **The raster residue claim is real.**
   `accumulated_force_grid_n += (shape/peak) * pending` with signed `pending`
   (`pressure_force_display.py:207`) subtracts the *current* Jerk shape on
   release; load shape A minus release shape B leaves permanent residue.

5. **Baseline changes do not reset Force state.**
   - Missing baseline: `process_pressure_force_block` returns early leaving stale
     force values/raster on screen (`gui/signal_integration_panel.py:894-899`).
   - `capture_current_plot_baselines` rebuilds `plot_baselines` and already calls
     guarded hooks (`on_plot_baselines_captured`, `reset_555_heatmap_state`) but
     nothing force-related (`data_processing/adc_plotting.py:118-151`).
     `on_plot_baselines_captured` is already claimed by
     `data_processing/pzt_ghost_removal.py:128`, so a *new* guarded hook is needed.
   - `_reset_capture_buffer_state` clears `plot_baselines`
     (`data_processing/capture_lifecycle.py:44-46`) with no force reset.

6. **Manual reset already works.** `reset_pressure_force_display`
   (`gui/signal_integration_panel.py:846-850`) rebuilds the engine and re-renders
   immediately; wired to the button at `gui/signal_integration_panel.py:769`.
   Proposal §14 requires no code change.

7. **The Force widget renders magnitude-only.** "Force Display is always
   magnitude-only" (`gui/pressure_map_widget.py:504`), and the array path renders
   `magnitude_force_grid_n` (`gui/pressure_map_widget.py:682`).

8. **`channel_calibration` is currently always `{}`** in the only GUI call site
   (`gui/signal_integration_panel.py:988`).

9. **`apply_jerk_shapes` runs at render cadence, not acquisition rate** — from
   `_update_pressure_map_from_latest` (`gui/signal_integration_panel.py:3217`),
   throttled by a 100 ms coalescing timer
   (`gui/signal_integration_panel.py:1002-1011`). Layer bookkeeping cost lands
   there, not in the sample loop.

---

## 2. Deviations from the proposal (and why)

1. **Replace `pending_normal_delta_n` with "load at last apply"**
   (`applied_load_n`). The proposal keeps a delta accumulator and compares
   `previous_normal_force_n` per sample. Instead, `apply_jerk_shapes` compares
   `abs(package.normal_force_n)` (current, derived) against the magnitude last
   applied to the raster. This is self-healing (no pending value to leak when a
   Jerk shape is zero/mismatched — the difference simply persists until a usable
   shape arrives), and it makes the §11 invariant
   `sum(layer.remaining_force_n) == applied_load_n` hold by construction.
   `previous_normal_force_n` as a per-sample field is not needed.

2. **Unloading must not require a Jerk shape.** The old code blocked negative
   pending on a zero Jerk grid (`pressure_force_display.py:203-206`). Layer
   removal uses stored shapes only, so unload (and full return-to-black) proceeds
   even when the current Jerk grid is zero — which is exactly the end-of-event
   situation.

3. **Coalesce consecutive layers with an identical shape.** The proposal's stack
   is unbounded under slow monotonic loading (one layer per render frame). When
   the new normalized shape equals the top layer's shape (`np.array_equal`), add
   to the top layer instead of appending. Cost is one grid comparison per package
   per render frame (~10 Hz), negligible.

4. **Don't expect §2 to fix the Normal runaway** (fact 1). The refactor is still
   done — for state consistency and the Shear fix (fact 3) — but the runaway fix
   is the baseline hook (step 4). Test expectations are framed accordingly.

---

## 3. Step 1 — Engine: derived package state

File: `data_processing/pressure_force_display.py`

### `_ForcePackageState` changes

```python
@dataclass(slots=True)
class ForceLayer:
    shape: np.ndarray            # normalized |jerk| grid, peak == 1.0
    remaining_force_n: float     # magnitude, always >= 0


@dataclass(slots=True)
class _ForcePackageState:
    channel_states: dict[str, PztForceChannelIntegrator]
    accumulated_force_grid_n: np.ndarray      # == sum(layer.shape * layer.remaining_force_n), >= 0
    force_layers: list[ForceLayer] = field(default_factory=list)
    normal_force_n: float = 0.0               # signed, derived each sample
    shear_x_n: float = 0.0                    # derived each sample
    shear_y_n: float = 0.0                    # derived each sample
    applied_load_n: float = 0.0               # magnitude last applied to the raster
    applied_polarity: int = 0                 # sign of normal_force_n at last apply
    quiet_sample_count: int = 0
    has_force_activity: bool = False
```

Removed: `pending_normal_delta_n`.

### `process_sample` changes (lines 142-174)

Replace the delta pipeline with current-state derivation:

```python
current_forces: dict[str, float] = {}
for position in SHEAR_SENSOR_POSITIONS:
    state = package.channel_states[position]
    ...timestamp checks unchanged...
    state.process_centered_sample(...)   # step result no longer needed
    current_forces[position] = state.accumulated_force_n * float(calibration.get(position, 1.0))
```

Quiet/event-complete reset logic (lines 155-164) is unchanged. Then:

```python
shear = self.shear_detector.detect(current_forces)
normal = self.normal_force_calculator.compute(shear.residual)
package.normal_force_n = normal.total_force     # assignment, not +=
package.shear_x_n = shear.b_lr
package.shear_y_n = shear.b_tb
```

Notes:

- `channel_calibration` now multiplies accumulated force instead of deltas —
  numerically identical by linearity, and the GUI passes `{}` anyway (fact 8).
- Update the module/class docstrings that describe the pending-delta contract
  (lines 1, 64, 171-174).

## 4. Step 2 — Engine: layer stack in `apply_jerk_shapes`

Replace the body of `apply_jerk_shapes` (lines 186-208) per package:

```python
EPSILON_N = 1e-12  # module constant; far below the display floor (~2.5 mN default)

current_normal = float(package.normal_force_n)
polarity = 0 if current_normal == 0.0 else (1 if current_normal > 0.0 else -1)

# §9 polarity crossing: the old event's layers are removed first, using their
# stored shapes; requires no current Jerk shape.
if polarity and package.applied_polarity and polarity != package.applied_polarity:
    self._clear_layers(package)

delta_load = abs(current_normal) - package.applied_load_n

if delta_load > EPSILON_N:
    # Loading path: needs a usable current Jerk shape.
    jerk_grid = ...same extraction as now (lines 195-206: shape-mismatch guard,
                  abs, peak, zero/non-finite guard)...
    # On any guard failure: skip; delta_load persists to the next frame.
    shape = np.abs(jerk_grid) / peak
    top = package.force_layers[-1] if package.force_layers else None
    if top is not None and np.array_equal(top.shape, shape):
        top.remaining_force_n += delta_load          # coalesce (deviation 3)
    else:
        package.force_layers.append(ForceLayer(shape, delta_load))
    package.accumulated_force_grid_n += shape * delta_load
    package.applied_load_n += delta_load

elif delta_load < -EPSILON_N:
    # Unloading path: LIFO removal from stored shapes; no Jerk shape needed.
    remove = -delta_load
    while remove > EPSILON_N and package.force_layers:
        layer = package.force_layers[-1]
        take = min(layer.remaining_force_n, remove)
        package.accumulated_force_grid_n -= layer.shape * take
        layer.remaining_force_n -= take
        package.applied_load_n -= take
        remove -= take
        if layer.remaining_force_n <= EPSILON_N:
            package.force_layers.pop()
    if not package.force_layers:
        # §11: hard zero kills float residue; guarantees exact black.
        package.accumulated_force_grid_n = np.zeros_like(package.accumulated_force_grid_n)
        package.applied_load_n = 0.0

if polarity:
    package.applied_polarity = polarity
elif package.applied_load_n <= EPSILON_N:
    package.applied_polarity = 0
```

Helper:

```python
@staticmethod
def _clear_layers(package: _ForcePackageState) -> None:
    package.force_layers.clear()
    package.accumulated_force_grid_n = np.zeros_like(package.accumulated_force_grid_n)
    package.applied_load_n = 0.0
```

Invariants (assert in tests, not at runtime):

- `sum(l.remaining_force_n) == applied_load_n` after every apply;
- `accumulated_force_grid_n >= 0` everywhere;
- when Jerk shapes are available at apply time,
  `applied_load_n == abs(normal_force_n)` after apply.

`reset()`, `reset_package()`, `configure_layout()` need no change — they build
fresh `_ForcePackageState` instances whose defaults cover the new fields, so quiet
reset and event-complete reset yield immediate black on the next render, as today.

### Consequence for `array_result`

Layer grids are non-negative, so the signed composed grid equals the magnitude
grid. The widget already renders magnitude-only (fact 7), so no widget change is
needed. `ForceMapArrayResult` keeps both fields for API stability.

## 5. Step 3 — Numerical readout

`package_results()` is unchanged: `normal_force_n` stays signed (proposal §10);
the raster is magnitude-only by construction. `+1 N` and `-1 N` render
identically.

## 6. Step 4 — GUI: baseline-change reset hooks

This step fixes the runaway in practice (fact 2) and proposal §13.

### 6.1 New panel method — `gui/signal_integration_panel.py`

```python
def reset_pressure_force_display_for_baseline_change(self) -> None:
    """A Force integral is only meaningful against the baseline it started on."""
    if getattr(self, "pressure_force_engine", None) is None:
        return
    self._rebuild_pressure_force_engine()
    self._render_pressure_force_display()
    if hasattr(self, "force_display_status_label"):
        self.force_display_status_label.setText("Force Display reset: Time Series baseline changed")
```

`_render_pressure_force_display` (line 1013) renders regardless of active tab, so
the raster goes black immediately without waiting for another ADC block.

### 6.2 Hook: baseline captured/replaced — `data_processing/adc_plotting.py`

In `capture_current_plot_baselines`, next to the existing guarded
`reset_555_heatmap_state` call (lines 150-151):

```python
if hasattr(self, "reset_pressure_force_display_for_baseline_change"):
    self.reset_pressure_force_display_for_baseline_change()
```

Covers: Zero Signals (`zero_plot_baselines`), automatic capture at Time Series
startup, and any other caller. Do **not** reuse `on_plot_baselines_captured` — it
is already implemented by the ghost-removal mixin
(`data_processing/pzt_ghost_removal.py:128`) and a second definition would shadow
it in the MRO.

### 6.3 Hook: baseline cleared — `data_processing/capture_lifecycle.py`

In `_reset_capture_buffer_state`, after clearing `plot_baselines` (line 44-46),
add the same guarded call. Covers: new acquisition run, capture restart, cache
reset. The `hasattr` guard plus the engine-`None` guard keep app-init calls
(`adc_gui.py:175`) safe.

### 6.4 Defensive: missing-baseline branch — `gui/signal_integration_panel.py:894-899`

Baseline keys can also disappear partially (channel spec changes). When the
missing-baseline branch is taken, additionally reset once per transition:

```python
if not getattr(self, "_pressure_force_waiting_for_baseline", False):
    self._pressure_force_waiting_for_baseline = True
    self.reset_pressure_force_display_for_baseline_change()
# keep the existing status text after the reset call
```

Clear the flag (`= False`) on the normal path once baselines are present again.
Set the "Waiting for Time Series baseline…" status *after* the reset call so it
wins over the reset message.

## 7. Step 5 — Tests

File: `tests/test_pressure_force_display.py` unless stated.

### Update existing tests to the new semantics

| Test (verified name) | Change |
| --- | --- |
| `test_force_engine_applies_the_exact_normalized_jerk_shape_once` | Same intent: after one apply, grid == `shape * abs(normal)`; re-applying with unchanged normal changes nothing (applied-load idempotence). |
| `test_force_engine_preserves_negative_force_with_the_same_jerk_shape` | Negative normal now yields a *positive* magnitude grid of the same shape; numerical `normal_force_n` stays negative. |
| `test_force_engine_keeps_pending_force_until_a_nonzero_jerk_shape_arrives` | Rewrite: with a zero Jerk grid, `applied_load_n` stays 0 while `normal_force_n` is nonzero; the first nonzero shape applies the full difference. |
| `test_force_reset_clears_pending_and_accumulated_force` | Rename/extend: reset clears `force_layers`, `applied_load_n`, `applied_polarity`, grid. |
| Quiet-reset / event-complete / sample-identity tests | Should pass unchanged; keep as regression. |
| `test_force_samples_never_generate_force_side_pressure_maps` | Keep unchanged (proposal Test 11). |

### New engine tests (proposal §18 mapping)

1. **Derived state (Test 1):** after a voltage sequence, `normal_force_n ==
   sum(channel accumulated_force_n)`; explicitly assert it is *unchanged* from the
   pre-refactor formula (fact 1) so the verifying agent sees the equivalence.
2. **Loading adds a layer (Test 2):** normal 0.20 → 0.30 N ⇒ one layer gains
   0.10 N; grid increment == `shape * 0.10`.
3. **Unloading removes the stored shape (Test 3):** load 0.30 N with shape A;
   swap the Jerk display to shape B; unload 0.10 N ⇒ grid == `A * 0.20`, no trace
   of B.
4. **Full unload is exact black (Test 4):** several different shapes loaded, then
   normal → 0 ⇒ `force_layers == []` and `np.count_nonzero(grid) == 0` (exact,
   thanks to the hard zero).
5. **LIFO (Test 5):** A×0.10 then B×0.20, remove 0.15 ⇒ B remains 0.05, A remains
   0.10.
6. **Polarity crossing (Test 6):** −0.10 N → +0.15 N ⇒ old layers cleared (works
   with a zero current Jerk grid), then +0.15 N applied with the new shape.
7. **Invariant (Test 7):** after a randomized load/unload sequence,
   `sum(remaining) == applied_load_n` and, when shapes were available,
   `== abs(normal_force_n)`.
8. **Unload without a Jerk shape:** zero Jerk grid during release still drains
   layers to black (deviation 2 — this is the end-of-event case).
9. **Coalescing:** N monotonic load steps with an identical shape produce 1
   layer, not N (deviation 3).
10. **Shear noise-rectification regression (fact 3):** alternating ±delta noise
    on an L/R pair that sums to zero accumulated force ⇒ `shear_x_n` returns to
    ~0 instead of random-walking.
11. **DC-offset characterization (fact 2):** a constant above-threshold centered
    voltage ramps `normal_force_n` linearly (documents the mechanism), and
    engine rebuild (the baseline hook's action) zeroes it — the reason step 4
    exists.

### New GUI tests — `tests/test_signal_integration_panel.py` (and/or the
`tests/test_adc_plotting.py` harness)

12. **Baseline captured (Test 9a):** with nonzero engine state,
    `capture_current_plot_baselines` triggers
    `reset_pressure_force_display_for_baseline_change` ⇒ fresh engine, zero
    render, status text set.
13. **Baseline cleared (Test 9b):** `_reset_capture_buffer_state` does the same.
14. **Missing-baseline transition (defensive hook):** first force block without a
    baseline key resets once and sets "Waiting for Time Series baseline…";
    subsequent blocks do not re-reset; baseline restoration clears the flag.
15. **Manual reset (Test 10):** existing behavior — assert
    `reset_pressure_force_display` renders zero immediately (no ADC block
    needed).

## 8. Step 6 — Manual verification

1. Run the app with hardware (or playback), open Force Display.
2. Press and hold: raster grows, `N:` readout stabilizes (no linear ramp while
   the voltage decays).
3. Release slowly: raster decreases through the *loading* shapes; after release
   plus quiet period, raster is fully black and readouts are 0.
4. Press, then hit **Zero Signals** mid-press: Force display clears immediately
   and re-integrates against the new baseline (no thousands-of-N ramp afterward).
5. Stop/start capture: Force display clears immediately.
6. `Reset Force Display` button: immediate black, no ADC block required.
7. Jerk Display behavior unchanged throughout.

---

## 9. Behavior-affecting changes (explicit list for review)

1. **Shear readouts change value.** Derived-from-accumulated-state shear replaces
   integrated per-delta shear; less noise drift, different (more physical)
   numbers. Normal readout is *numerically identical* (fact 1, linearity).
2. **The Force raster is non-negative.** The signed composed array grid now
   equals the magnitude grid. The widget already renders magnitude-only (fact 7),
   so nothing visible changes for positive events; negative events render at the
   same intensity as positive (proposal §10).
3. **Release no longer paints with the current Jerk shape** — it removes stored
   loading shapes (the fix; proposal §3/§7).
4. **A zero Jerk shape no longer blocks unloading** (deviation 2). Previously a
   negative pending waited for a nonzero shape.
5. **Zero Signals / capture restart / baseline loss now immediately clears Force
   state** (was: stale values and raster persisted).
6. **`channel_calibration` multiplies accumulated force, not deltas** —
   equivalent by linearity; GUI currently passes `{}` (fact 8).
7. **Layer removal policy is LIFO** (proposal §8); revisit only if experiments
   argue for FIFO/proportional.

## 10. Out of scope

- Firmware changes (Python-only scope).
- Jerk Display pipeline, `PressureMapGenerator`, and the widget rendering path.
- Changing the channel integrator physics (`pzt_force_calculation.py`) — the
  DC-offset ramp is intended physics given its inputs; the fix is baseline
  hygiene, not integrator clamping. A stuck-active watchdog (very long
  continuously-active channel with monotone ramp ⇒ suspect baseline) is a
  possible follow-up, not part of this plan.

## 11. Suggested implementation order

1. Step 4 (baseline hooks) — smallest diff, kills the runaway path; independent
   of the engine refactor and can be verified alone (tests 12-15).
2. Steps 1-2 (engine refactor + layer stack) with engine tests 1-11 and existing
   test updates.
3. Step 6 manual verification.

## 12. Acceptance criteria

- [ ] Package Normal/Shear are assigned from current channel accumulators, never `+=`.
- [ ] Normal readout is bit-identical to before for the same input stream (fact 1); Shear changes are understood and intended.
- [ ] Loading appends/coalesces layers using the current Jerk shape; no Force-side `PressureMapGenerator.generate()` call exists.
- [ ] Unloading removes stored shapes LIFO and works without a current Jerk shape.
- [ ] Full unload gives `force_layers == []` and an exactly-zero grid.
- [ ] Polarity crossing clears old layers before starting the new event.
- [ ] `sum(remaining) == applied_load_n` after every apply; grid is non-negative.
- [ ] Quiet-sample and event-complete resets behave exactly as before.
- [ ] Zero Signals, capture restart, and baseline loss immediately zero the Force display without another ADC block.
- [ ] Manual reset unchanged (already immediate).
- [ ] Jerk Display unchanged.
- [ ] Full test suite passes.
