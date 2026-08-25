# Plan: Pressure Map Force Display — Shear Arrow (Part A) and Ghost-Removal Baseline Fix (Part B)

Part A (sections 1–7): draw the force-derived shear arrow with unit-split
parameters. Part B (section 8): fix the exploding Normal force caused by
double baseline subtraction when PZT ghost removal is enabled.

## 1. Requirement (as stated)

On the Pressure Map Force Display, Normal and Shear force must be derived from
the per-channel *forces*, not from the Jerk display's shear/residual voltage
data:

1. Compute force for each of the five channels (C, L, R, T, B).
2. Extract the shear part per axis from opposite-sign outer pairs, the same
   rule the Jerk display uses: if T = 5 N and B = -3 N, the T/B axis carries
   shear of magnitude `min(|T|, |B|) = 3 N` directed toward the positive
   (larger-magnitude-sign) channel, here "up".
3. Normal force = total force with the shear parts subtracted.
4. Shear direction and magnitude combine both axes (vector sum).
5. Draw a shear arrow on the Force Display using the *same parameters and the
   same mechanism* as the Jerk display arrow, but fed from the force-derived
   shear vector.

## 2. Verified current behavior (with sources)

These claims were verified by reading the code in this session, not assumed.

### 2.1 The N/S numbers are already computed from per-channel forces

The premise that the Force Display currently derives Normal/Shear from the
Jerk display's shear-voltage/residual-voltage data is **not what the current
code does**:

- The force engine receives the **raw baseline-centred per-channel volts**,
  before any Jerk transform — `gui/signal_integration_panel.py:1049-1057`
  (comment there: "The force engine receives volts before every Jerk
  transform").
- Each of the five channels is integrated to newtons independently by
  `PztForceChannelIntegrator` — `data_processing/pressure_force_display.py:173-182`.
- Shear is then extracted **from those per-channel forces** with the exact
  min-of-opposite-sign-pair rule (`ShearDetector.detect`, shared with Jerk) —
  `data_processing/pressure_force_display.py:210-221`:

  ```python
  current_forces = {position: channel accumulated force × calibration ...}
  shear = self.shear_detector.detect(current_forces)
  normal = self.normal_force_calculator.compute(shear.residual)
  package.normal_force_n = normal.total_force
  package.shear_x_n = shear.b_lr
  package.shear_y_n = shear.b_tb
  ```

- `ShearDetector` implements exactly the requested pair rule: opposite-sign
  pair → magnitude `min(|a|, |b|)`, sign of the positive-direction channel
  (`data_processing/shear_detector.py:98-108, 152-156`), vector combination
  via `hypot`/`atan2` (`:104-109`).
- `normal.total_force` equals the sum of the shear-removed residuals (the
  baseline shift cancels in the total, `data_processing/normal_force_calculator.py:105-110`),
  i.e. "the total force with the shear parts subtracted" — the requested
  definition. (Numerically it equals the plain channel sum because the two
  shear parts of a pair are equal-and-opposite, but the pipeline is
  structured exactly as requested: force → shear extraction → normal from
  residual.)

What the Jerk display *does* still contribute to the Force Display is only
the **spatial shape** of the raster (`apply_jerk_shapes`,
`pressure_force_display.py:226-286`) — deliberately, per
`Plans/reuse_jerk_heatmaps_for_force_display.md`. The Normal/Shear numbers do
not pass through Jerk data.

**Conclusion: steps 1–4 of the requirement are already implemented. The real
gap is step 5 — the arrow — plus settings plumbing.**

### 2.2 The Force Display draws no shear arrow (the actual gap)

- Single-package force view: `update_force_display` explicitly hides the
  dynamic arrow — `gui/pressure_map_widget.py:632` (`self._hide_arrow()`).
- Force-array view: `update_force_array_display` hides the dynamic arrow
  (`:707`) and every per-package arrow (`:754`,
  `self._hide_package_arrow(index)`).
- Only the text readouts exist: `"Normal Force: … | Shear Force: …"` (`:633-636`)
  and per-package callouts `"N: … / S: …"` (`:763-765`).

### 2.3 Arrow settings never reach the force widgets

- `on_shear_visualization_settings_changed` applies `configure_arrow(...)`
  **only** to the Jerk `pressure_map_widget` —
  `gui/signal_integration_panel.py:2727-2733`. The
  `force_pressure_map_widget` and the lazy per-package force widgets never
  receive arrow settings.
- `_configure_force_package_widget` (`signal_integration_panel.py:1180-1199`)
  clones every shared presentation setting *except* the arrow configuration.
- Arrow **color** is fine as-is: `configure_color_scale` sets `arrow_color`
  per widget (`pressure_map_widget.py:428-432`) and the force widgets already
  receive `configure_color_scale` (`signal_integration_panel.py:2785`).

### 2.4 Existing arrow mechanism to reuse

- Shared geometry/rendering: `ShearArrowRenderMixin`
  (`gui/shear_visualization_widget.py:108-205`), already mixed into
  `PressureMapWidget`.
- `PressureMapWidget.calculate_arrow_geometry(shear_result)` consumes a
  `ShearResult` (`has_shear`, `shear_magnitude`, `shear_angle_deg`) and the
  widget's `arrow_gain` / `arrow_min_threshold` / `arrow_max_length_fraction`
  / width settings — `gui/pressure_map_widget.py:2092-2120`.
- Jerk-array per-package arrows: `_update_package_shear_arrow(index, package,
  center_x, center_y)` sets `circle_radius_mm` from the package geometry and
  calls `_apply_arrow_to_items` — `pressure_map_widget.py:1776-1791`.
- In the single force view, `circle_radius_mm` is already set before the
  arrow call site: `_update_force_geometry` → `_update_boundary_geometry`
  (`pressure_map_widget.py:630, 1367`).

## 3. Design

Feed the already-computed force-derived shear vector into the existing arrow
mechanism. No new math; no change to any Normal/Shear number.

### 3.1 Engine: expose the force-derived `ShearResult`
`data_processing/pressure_force_display.py`

1. `_ForcePackageState`: add `shear_result: ShearResult | None = None`.
2. In `process_sample`, next to the existing assignments (`:219-221`), store
   the detector output: `package.shear_result = shear`.
3. `ForceMapPackageResult`: add field `shear_result: ShearResult | None`;
   populate it in `package_results()`. Keep `shear_x_n` / `shear_y_n` and the
   `shear_force_n` property unchanged (readouts/callouts keep using them).

Behavioral notes (all follow from existing code paths, no extra logic):
- Fresh or reset package (`_new_package_state`) → `shear_result is None` →
  arrow hidden. Package reset already zeroes the numbers atomically.
- During the stuck-force fail-safe decay, shear is recomputed each sample
  from the decayed channel forces (the `continue` at `:206-208` only skips
  on full reset), so the arrow shrinks with the decay and disappears on the
  coherent reset — consistent with the readout numbers.
- `ShearResult` is a frozen dataclass; storing the instance is safe.

### 3.2 Widget: draw the arrow in both force views
`gui/pressure_map_widget.py`

1. **Single force view** — in `update_force_display`, replace
   `self._hide_arrow()` (`:632`) with:

   ```python
   self._update_shear_arrow(getattr(force_result, "shear_result", None))
   ```

   `_update_shear_arrow` (`:2082-2090`) already handles `None` / hidden
   geometry by hiding the arrow. `circle_radius_mm` is already set by
   `_update_force_geometry` on the previous line, so the max-length clamp
   uses the force package's own boundary — same as Jerk.

2. **Force-array view** — in `_update_force_array_package_overlays`, replace
   `self._hide_package_arrow(index)` (`:754`) with a call to a new

   ```python
   def _update_force_package_shear_arrow(self, index, package, center_x, center_y) -> None:
       shear_result = getattr(package, "shear_result", None)
       if shear_result is None:
           self._hide_package_arrow(index)
           return
       self.circle_radius_mm = float(package.geometry.outer_boundary_half_width_mm)
       geometry = self.calculate_arrow_geometry(shear_result)
       if not geometry.visible:
           self._hide_package_arrow(index)
           return
       self._apply_arrow_to_items(index, geometry, center_x, center_y, self.arrow_color)
   ```

   This mirrors `_update_package_shear_arrow` (`:1776-1791`) exactly; the
   only difference is that a `ForceMapPackageResult` carries `geometry`
   instead of a `pressure_result`. The already-mirrored `center_x` is passed
   in, identical to the Jerk-array path, so mirroring behaves the same as
   Jerk (arrow anchored at the mirrored package center; the vector itself is
   not flipped — same mechanism, same behavior).

3. No change to `calculate_arrow_geometry`, the mixin, thresholds, gain,
   width scaling, or colors — "same parameters, same mechanism".

### 3.3 Parameter split: unit-carrying parameters are separate for Force

(Decision by the user 2026-08-11: "for units specific parameter use different
parameter for shear and jerk" — unit-carrying arrow parameters get their own
Force-side controls; unitless presentation parameters stay shared.)

On the Jerk display the shear magnitude is a **voltage-domain** quantity
(order ~0.1–2 V), while the force-derived shear magnitude is in **newtons**
(Force color range default 0.25 N, noise floor ~2.5 mN). The parameters
therefore split as:

| Parameter | Units | Force Display uses |
| --- | --- | --- |
| `arrow_gain` (magnitude → mm) | mm/V vs mm/N | **new force-specific spin** |
| `arrow_min_threshold` | V vs N | **new force-specific spin** |
| width-scaling reference magnitude | V vs N | **force-specific value** (see below) |
| `arrow_max_length_fraction` | unitless (× radius) | shared spin |
| `arrow_base_width_px` | pixels | shared spin |
| `arrow_width_scales` | bool | shared checkbox |
| `arrow_color` | — | already per-widget via color scale |

The Jerk and Force views live on **separate `PressureMapWidget` instances**
(`pressure_map_widget` vs `force_pressure_map_widget` + lazy per-package
widgets), so no widget-level view-mode switching is needed: the panel simply
configures each widget instance with its own gain/threshold values.

#### Widget addition: per-widget width-scaling reference

`_calculate_arrow_width` currently divides by the module constant
`SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE = 2.0` (volts) —
`gui/shear_visualization_widget.py:198-205`. In newtons that fraction is
always ≈ 0, so width scaling would never engage on the Force Display.

- Add a host attribute `arrow_width_reference_magnitude` (initialized to
  `SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE` in both `ShearVisualizationWidget`
  and `PressureMapWidget`) and use it in the mixin's
  `_calculate_arrow_width`. Jerk behavior is unchanged by construction.
- Accept it as a new optional kwarg in both `configure_arrow` /
  `configure` methods.
- For force widgets, set it to the current **Force color max**
  (`display_max_force_n` spin): the arrow reaches maximum width exactly when
  the shear magnitude reaches the top of the force color scale. No new
  constant or extra control needed.

#### New GUI controls (Force Display settings group)

Add two spins to `_create_pzt_force_settings_group`
(`gui/signal_integration_panel.py:847-877`), next to "Force color max:"
which is the precedent for a display-only force setting:

- `force_arrow_gain_spin` — "Force arrow gain:", suffix `" mm/N"`, default
  `PZT_FORCE_DEFAULT_SETTINGS["force_arrow_gain_mm_per_n"]` (see constants
  below). Tooltip mirrors the Jerk arrow-gain tooltip but names newtons.
- `force_arrow_threshold_spin` — "Force arrow threshold:", suffix `" N"`,
  default `PZT_FORCE_DEFAULT_SETTINGS["force_arrow_min_threshold_n"]`.
  Display-only: hides the arrow, never changes computed forces.

Both connect to `on_force_display_settings_changed` (`:913`), the existing
display-only handler (NOT `on_pzt_force_settings_changed`, which rebuilds the
engine and would reset accumulated force state on an arrow tweak).

#### Constants

`constants/pzt_force.py` — extend `PZT_FORCE_DEFAULT_SETTINGS` (display-only
keys, same precedent as `display_max_force_n`; the engine reads only its own
keys, so extra keys are inert there):

- `"force_arrow_gain_mm_per_n": 20.0` — with the default 0.25 N color max
  and a ~5 mm package radius, a full-scale shear draws a full-radius arrow.
- `"force_arrow_min_threshold_n": 0.0025` — matches the existing display
  noise floor (`force_alpha_floor_n` default 0.0025 N) so noise-level shear
  draws no arrow.

`constants/shear.py` — add spin range/step/decimals constants for the two new
spins following the existing `SHEAR_ARROW_GAIN_MIN/...` pattern (e.g.
`FORCE_ARROW_GAIN_*`, `FORCE_ARROW_MIN_THRESHOLD_*`; threshold decimals ≥ 4
so 2.5 mN is representable).

#### Panel plumbing

`gui/signal_integration_panel.py`

1. New helper `_apply_force_arrow_settings()` — configures every **force**
   widget (`force_pressure_map_widget` + `force_package_widgets.values()`)
   with the merged set:

   ```python
   widget.configure_arrow(
       arrow_gain=float(self.force_arrow_gain_spin.value()),
       arrow_min_threshold=float(self.force_arrow_threshold_spin.value()),
       arrow_max_length_fraction=float(self.shear_arrow_max_length_spin.value()),
       arrow_width_scales=bool(self.shear_arrow_width_scales_check.isChecked()),
       arrow_base_width_px=float(self.shear_arrow_base_width_spin.value()),
       arrow_width_reference_magnitude=float(self.force_display_max_n_spin.value()),
   )
   ```

   then queues a force re-render (`_queue_pressure_force_display_render()`)
   so changes are visible without waiting for the next sample.
2. `on_shear_visualization_settings_changed` (`:2724-2735`): unchanged for
   the Jerk widget (full set from the `shear_*` spins), plus a call to
   `_apply_force_arrow_settings()` so the shared unitless parameters
   propagate to the force widgets.
3. `on_force_display_settings_changed` (`:913`): also call
   `_apply_force_arrow_settings()` (covers the two new spins and the color
   max, which doubles as the width reference).
4. `_configure_force_package_widget` (`:1180`): clone arrow settings for
   lazily created per-package widgets — simplest is to call
   `_apply_force_arrow_settings()` after the widget is registered, or copy
   the source force widget's attributes directly.

#### Persistence

Add the two new values to `_pzt_force_settings()` (`:880-899`) so they ride
the existing `"pzt_force"` section of `save_last_shear_settings`
(`:1955`) — the same path `display_max_force_n` uses — and restore them in
the settings-load path next to `force_display_max_n_spin`
(`:2305`) via `_set_spin_value("force_arrow_gain_spin", pzt_force,
"force_arrow_gain_mm_per_n", float)` and likewise for the threshold.

## 4. Resolved: no shared gain/threshold compromise

Earlier drafts flagged the volts-vs-newtons collision as an open issue. It is
resolved by section 3.3: the Force Display gets its own gain (mm/N),
threshold (N), and width reference (N), while the geometric/pixel parameters
and the rendering mechanism remain the shared Jerk implementation.

## 5. Explicitly out of scope

- No change to the Normal/Shear computation itself — verified already
  force-based (section 2.1). The Python-only scope holds; no firmware or
  engine math changes.
- No change to Jerk display behavior; the Jerk arrow paths are untouched.
- No change to the Force raster (`apply_jerk_shapes` shape reuse stays).

## 6. Tests

`tests/test_pressure_force_display.py`
1. After a sample that produces an opposite-sign pair in accumulated channel
   forces, `package_results()[i].shear_result` is a `ShearResult` whose
   `b_lr`/`b_tb` equal `shear_x_n`/`shear_y_n`.
2. Fresh package and `reset_package` → `shear_result is None`.

`tests/test_pressure_map_widget.py`
3. `update_force_display` with a result whose `shear_result` has shear above
   the threshold → dynamic arrow items visible, geometry matches
   `calculate_arrow_geometry`; with `shear_result=None` or below threshold →
   hidden.
4. `update_force_array_display` → per-package arrow visible at the package
   center for a package with shear; hidden for a zero package. Existing tests
   asserting arrows hidden in force modes (if any) must be updated to the new
   intent.
5. Jerk views unchanged (existing tests keep passing).

`tests/test_signal_integration_panel.py`
6. `_apply_force_arrow_settings` gives the force widgets the force-specific
   gain/threshold (from `force_arrow_gain_spin` / `force_arrow_threshold_spin`)
   and the shared unitless parameters (from the `shear_*` controls); the Jerk
   widget keeps the volt-domain gain/threshold untouched.
7. `on_force_display_settings_changed` updates the force widgets' arrow
   gain/threshold and width reference (from Force color max) without
   rebuilding the engine (accumulated force state preserved).
8. `_configure_force_package_widget` / lazy widget creation yields per-package
   force widgets with the same arrow configuration as
   `force_pressure_map_widget`.
9. Settings save/restore round-trips `force_arrow_gain_mm_per_n` and
   `force_arrow_min_threshold_n` through the `pzt_force` section.

`tests/test_shear_visualization` / widget-level
10. `_calculate_arrow_width` uses the per-widget
    `arrow_width_reference_magnitude`; default equals
    `SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE` so existing Jerk width tests pass
    unchanged.

## 7. Implementation order

1. Engine field + result plumbing (3.1) with tests 1–2.
2. Widget arrow rendering (3.2) + per-widget width reference, with tests 3–5
   and 10.
3. Constants, new Force arrow spins, panel plumbing, persistence (3.3) with
   tests 6–9.
4. Full test-suite run.

Part B (section 8) is independent of Part A and should land **first**: the
runaway force makes every Force Display observation (including arrow
verification) meaningless while ghost removal is enabled.

## 8. Part B — Fix: exploding Normal force with PZT ghost removal enabled

### 8.1 Symptom

With no pressure applied (signals are ±3 mV noise, far below the 10 mV Noise
threshold), the Force Display Normal force grows monotonically without bound
(observed ≈ −3,000 N on every package, S = 0.000), while the Analysis bench's
calculated force for the same channels stays flat at zero. **User-verified
2026-08-11: disabling PZT ghost removal resolves the runaway** — confirming
the root cause below on live hardware.

### 8.2 Verified root cause: double baseline subtraction

Two representations collide when PZT ghost removal is enabled:

1. Ghost removal stores **net-space** data. `_apply_pzt_ghost_removal`
   computes `net = data − ghost_baselines` and writes the cleaned block back
   *without re-adding the baselines*
   (`data_processing/pzt_ghost_removal.py:210-234`). Both ring buffers and
   the block handed to `process_pressure_force_block` carry this net-space
   data (`data_processing/binary_processor.py:210-221, 235-242`).
2. `plot_baselines` are **raw-equivalent**. Baseline capture first runs
   `reconstruct_pzt_signal_for_baseline_capture`, which re-adds the ghost
   baselines (`pzt_ghost_removal.py:275`), so the captured medians are
   ≈ mid-scale ADC counts (~1.65 V), not ≈ 0.

Time Series handles this deliberately: it **skips** the `plot_baselines`
subtraction whenever `should_remove_pzt_ghost()` is true
(`data_processing/adc_plotting.py:380-388`). The Force Display path has no
such gate — it subtracts `plot_baselines` unconditionally
(`gui/signal_integration_panel.py:1048-1052`). Net-space (≈ 0) minus a raw
baseline (≈ 2048 counts) yields a standing **≈ −1.65 V** on every channel.

Consequences (mechanics verified in `pzt_force_calculation.py`):

- Every channel is permanently "active" (1.65 V ≫ 10 mV), so `quiet_since_s`
  never starts and **every** reset path — natural zero, quiet-hold release,
  channel and package stuck-force fail-safes — is unreachable (all are gated
  on a continuous quiet run: `pzt_force_calculation.py:297-301, 392-393`;
  `pressure_force_display.py:192-196, 414-437`).
- The RC leak model (τ = Rleak·C = 1 MΩ × 150 pF = 150 µs vs ≈ 22 µs
  connected exposure per observation) converts the standing offset into
  fabricated charge every step: ΔF ≈ (C/d33)·V·(1−α) ≈ 6 mN per observation
  per channel, one sign, forever (`pzt_force_calculation.py:310-320`).
- Common-mode equal-sign channels produce zero shear (no opposite-sign
  pairs), matching S = 0.000 — the shear extraction is *not* involved.
- The Analysis bench is immune because it centers each trace with its own
  median (`vmid`); the Jerk display has the same double subtraction but its
  HPF removes the DC. Only the deliberately unfiltered Force path sees it.

### 8.3 Design

Mirror the Time Series gate in the Force Display feed: when the incoming
block is ghost-cleaned (already net-centered), the baseline to subtract is
**zero**.

1. **Ghost mixin helper** (`data_processing/pzt_ghost_removal.py`) — add a
   small public predicate so consumers do not poke `_pzt_ghost_baselines`:

   ```python
   def is_pzt_ghost_block_net_centered(self) -> bool:
       """Whether ingest blocks/buffers currently carry net-space PZT data."""
       return self.should_remove_pzt_ghost() and self._pzt_ghost_baselines is not None
   ```

   The condition is exactly `prepare_pzt_ghost_block`'s cleaning condition
   (`:236-241`), so the predicate is true precisely when blocks are
   net-space.

2. **Force feed** (`gui/signal_integration_panel.py`,
   `process_pressure_force_block` `:1048-1052`): resolve the mode once per
   block, then per channel:

   ```python
   ghost_net_centered = bool(
       getattr(self, "is_pzt_ghost_block_net_centered", lambda: False)()
   )
   ...
   baseline = 0.0 if ghost_net_centered else float(
       getattr(self, "plot_baselines", {}).get(spec.get("key"), 0.0)
   )
   ```

   Everything downstream (voltage scale, polarity, engine) is unchanged.

3. **Waiting gate** (`:1013-1024`) stays as-is. Sequencing makes it correct
   in both modes: a new capture clears both `plot_baselines`
   (`capture_lifecycle.py:125-127`) and the ghost baselines
   (`begin_pzt_ghost_capture`, `pzt_ghost_removal.py:55-61`); while ghost
   calibration is pending, blocks are raw and `plot_baselines` are missing,
   so the Force Display waits; ghost calibration completes *via*
   `capture_current_plot_baselines` (`pzt_ghost_removal.py:197-201`), which
   both populates `plot_baselines` and switches subsequent blocks to
   net-space — from then on the predicate is true and the baseline used is
   0. The raw-block + raw-baseline combination therefore never feeds the
   engine while ghost removal is enabled.

4. **Toggle coherence**: enabling/disabling ghost removal mid-capture
   (`set_pzt_ghost_removal_settings`, `pzt_ghost_removal.py:43-53`) changes
   the buffer semantics under the accumulated force state. Call
   `reset_pressure_force_display_for_baseline_change()` (or a dedicated
   status text) from the settings handler that applies the toggle, mirroring
   the existing baseline-change reset (`adc_plotting.py:147-148`). Locate
   the handler that calls `set_pzt_ghost_removal_settings` and hook there so
   the reset fires exactly once per toggle.

Explicitly unchanged:

- The Jerk path's own `plot_baselines` subtraction
  (`signal_integration_panel.py:3636-3645`) also double-subtracts in ghost
  mode but is masked by the HPF; aligning it is a separate cleanup, out of
  scope here (behavior-affecting for Jerk; needs its own verification).
- The baseline-drift watchdog discussed earlier is **not** part of this fix.
  It remains a possible future hardening (mV-scale drift between Zero
  Signals presses), tracked separately if wanted.

### 8.4 Tests

`tests/test_signal_integration_panel.py`

1. Ghost-net mode: harness with `is_pzt_ghost_block_net_centered() → True`,
   `plot_baselines` ≈ mid-scale counts, block data ≈ 0 ± noise counts →
   engine channel voltages stay below the noise threshold and accumulated
   force stays 0 (this test fails before the fix with a huge standing
   offset).
2. Raw mode regression: `is_pzt_ghost_block_net_centered() → False` →
   `plot_baselines` subtraction still applied exactly as today.
3. Toggle: flipping ghost removal on/off resets the force engine and sets
   the status text.

`tests/test_pzt_ghost_removal.py`

- Predicate parity: `is_pzt_ghost_block_net_centered()` is true exactly
  when `prepare_pzt_ghost_block` returns cleaned (net-space) data, and
  false while calibration is pending or the feature is disabled.

### 8.5 Implementation order (Part B)

1. Mixin predicate + parity test (8.3.1).
2. Force-feed gate (8.3.2) with tests 1–2.
3. Toggle reset hook (8.3.4) with test 3.
4. Full test-suite run; live check with ghost removal re-enabled — Force
   Display must stay at zero with no touch, and the natural/fail-safe resets
   must work again on real presses.
