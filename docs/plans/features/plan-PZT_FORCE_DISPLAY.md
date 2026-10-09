# Coding Agent Instructions — Add `Force Display` to the Pressure Map Tab

## Objective

Implement a new **Force Display** inner tab under the existing **Pressure Map** tab.

The current inner tab named **Display** must be renamed to **Jerk Display**. Add a new **Force Display** tab beside it. The Pressure Map section should therefore contain:

1. **Jerk Display**
2. **Force Display**
3. **Settings**

The existing Jerk Display behavior must remain functionally unchanged.

The Force Display must reconstruct actual PZT force from the raw PZT voltage samples using leakage-compensated sample-by-sample integration, then use the existing pressure-map spatial model to display the accumulated normal-force distribution.

The Force Display must use the **same package geometry, array geometry, pressure-map interpolation/shaping behavior, mask behavior, display geometry, and existing Pressure Map settings** as the Jerk Display. Do not create a second independent set of pressure-map geometry/interpolation settings.

Only add new settings that are required for the PZT voltage-to-force reconstruction.

For every sensor package shown in Force Display, display:

- **Normal Force**
- **Shear Force**

Do **not** show peak markers on Force Display.

---

# Source Files Provided

Use these files as the primary reference for the current implementation:

- `pressure_map_geometry.py`
- `pressure_map_generator.py`
- `pressure_map_array_generator.py`
- `pzt_force_calculation.py`

Also inspect the complete project before editing, especially:

- the Pressure Map GUI/tab construction;
- the current `Display` tab;
- `PressureMapWidget`;
- the Pressure Map settings panel and persistence code;
- the existing signal-integration pipeline;
- the existing **time-series median baseline** implementation;
- ADC-count-to-voltage conversion;
- sample timestamps and timing metadata;
- normal-force calculation;
- shear-force calculation/detection;
- package/channel calibration;
- array/package layout handling;
- acquisition lifecycle and ring-buffer/history handling.

Do not assume names that are not present in the current project. Adapt these instructions to the existing architecture and naming conventions.

---

# Core Design Requirements

## 1. Preserve the current Jerk Display

Rename the visible tab:

```text
Display
```

to:

```text
Jerk Display
```

Do not change its numerical processing or visual behavior as part of this feature unless a small refactor is required to share code safely with Force Display.

Avoid broad rewrites of the existing pressure-map implementation.

Prefer extracting reusable helpers over duplicating large blocks of code.

Keep compatibility aliases for existing internal names when doing so reduces regression risk.

---

# 2. Add the Force Display tab

Add a new inner tab:

```text
Force Display
```

under the existing outer:

```text
Pressure Map
```

The Force Display should visually follow the current Pressure Map display:

- same physical sensor positions;
- same package geometry;
- same package spacing;
- same array geometry;
- same interpolation rules;
- same virtual outer-sensor/peak-position geometry used by the map generator;
- same decay/reach shaping;
- same array overlap/blending geometry;
- same mask, if Pressure Map masking is enabled;
- same orientation/mirroring;
- same boundaries and overlays where applicable;
- same color/display settings unless an existing setting is inherently tied only to Jerk Display.

Do not duplicate the existing pressure-map geometry settings.

A change to Pressure Map geometry/settings must affect both Jerk Display and Force Display.

---

# 3. Conceptual meaning of the two displays

## Jerk Display

The existing Jerk Display represents the current pressure-map behavior based on the app's existing processed/integrated signal.

Its processing must remain unchanged.

Conceptually:

```text
raw ADC data
    ↓
existing baseline / filtering / signal-integration path
    ↓
current five-sensor package values
    ↓
existing shear/normal-force processing
    ↓
PressureMapGenerator
    ↓
Jerk Display
```

Do not change this path unless required for code reuse.

## Force Display

Force Display is a **persistent force reconstruction**.

It must reconstruct the incremental force added by every new PZT sample and add the corresponding incremental spatial maps over time.

Conceptually:

```text
raw ADC data
    ↓
ADC → volts
    ↓
EXISTING time-series median-baseline mechanism
    ↓
baseline-centered PZT voltage
    ↓
PZT leakage compensation + voltage/charge → force
    ↓
per-sensor incremental force ΔF
    ↓
existing shear separation / normal-force calculation
    ↓
PressureMapGenerator(Δ normal force values)
    ↓
incremental normal-force map
    ↓
accumulate into Force Display map
```

The Force Display represents the accumulated force state, not merely the most recent voltage or moving-sum value.

---

# 4. Vmid / baseline handling — mandatory behavior

## Do not add Manual Vmid

Do **not** add:

- manual Vmid entry;
- a Vmid source selector;
- a Force Display-specific Vmid setting;
- a second independent baseline estimator.

Force Display must use the **same time-series median baseline mechanism that is already implemented in the app**.

Inspect the current project and find the exact existing code that calculates/subtracts the time-series median baseline.

Reuse that implementation.

The preferred architecture is:

```text
raw ADC
    ↓
ADC → voltage
    ↓
existing time-series median baseline stage
    ├──→ existing Jerk processing
    └──→ Force reconstruction
```

The Force Display should consume the baseline-centered voltage immediately after the existing median-baseline stage and **before any Jerk-specific HPF, DC-removal filter, moving-sum window, or other signal-integration transform**.

Do not apply an HPF to the Force Display input before PZT force reconstruction. The force algorithm explicitly models leakage in the decaying PZT voltage; an HPF would alter the signal that the leakage model is intended to reconstruct.

Do not reimplement the baseline as:

```python
vmid = np.median(force_trace)
```

inside Force Display if the app already has a central median-baseline implementation.

Instead, reuse the app's existing baseline result or baseline-centered voltage stream so Jerk and Force processing agree about the baseline.

Preserve the existing baseline mechanism's current lifecycle, windowing, channel handling, and settings behavior.

---

# 5. PZT force equation

Use `pzt_force_calculation.py` as the reference implementation.

The reconstruction is based on the PZT capacitance and leakage model.

For each interval:

```text
tau_on = Rleak_on × Cpzt
```

When only connected-time leakage is modeled:

```text
alpha = exp(-leak_dt / tau_on)
```

When the existing timing model supplies connected and disconnected exposure and optional off-MUX leakage is enabled:

```text
tau_off = Rleak_off × Cpzt

alpha =
    exp(
        -(leak_dt / tau_on)
        -((wall_dt - leak_dt) / tau_off)
    )
```

The generated charge increment is:

```text
dQ =
    Cpzt
    × pre_sample_correction
    × (v[n] - alpha × v[n-1])
```

where:

```text
pre_sample_correction =
    exp(pre_sample_decay_dt / tau_on)
```

when that timing correction is available/enabled.

Convert generated charge to incremental force:

```text
dF = dQ / d33
```

Use SI units internally:

- voltage: V
- time: s
- capacitance: F
- resistance: Ω
- d33: C/N
- force: N

If the UI stores `d33` in pC/N, convert it exactly as the existing `pzt_force_calculation.py` implementation does.

Do not create a competing formula.

---

# 6. Refactor force reconstruction for live streaming

The current `pzt_force_calculation.py` is designed primarily to reconstruct a complete trace.

Force Display needs a stateful, incremental live-processing path.

Refactor the force calculation so the **same low-level step calculation** is used by both:

1. the current/offline trace function; and
2. the new live Force Display.

Do not copy the mathematical logic into two independent implementations.

A suitable architecture is a reusable single-step helper or stateful integrator.

For example, adapt to project style with something conceptually equivalent to:

```python
@dataclass
class PztForceChannelState:
    previous_centered_voltage_v: float = 0.0
    accumulated_force_n: float = 0.0
    previous_timestamp_s: float | None = None
    event_polarity: int = 0
    saw_opposite_pair: bool = False
    initialized: bool = False
```

and a result such as:

```python
@dataclass(frozen=True)
class PztForceStepResult:
    delta_force_n: float
    accumulated_force_n: float
    centered_voltage_v: float
    active: bool
    reset_occurred: bool
```

The exact names are not important. Reuse existing project patterns.

Critical requirement:

> Every acquired sample must be integrated exactly once.

Do not repeatedly run the force reconstruction over the complete visible plot window during every GUI refresh.

That would re-integrate old samples and cause the force state to diverge.

---

# 7. Sample identity and streaming state

Maintain persistent force-processing state separately from the GUI frame rate.

For every physical PZT channel, track enough state to continue from the last processed sample.

Prefer a stable absolute acquisition sample/sweep counter if one already exists.

If not, use the most reliable monotonic identifier currently available, such as:

- absolute sample index;
- sweep index;
- absolute timestamp plus index;
- ring-buffer sequence number.

Do not use the GUI refresh number as the sample identity.

If the GUI refresh sees 20 newly acquired sweeps, process all 20 in chronological order.

Then render the final accumulated force state once.

Example:

```text
GUI refresh
    ↓
find samples newer than last_processed_sample
    ↓
process sample 101
process sample 102
...
process sample 120
    ↓
render one Force Display frame
```

---

# 8. Five-sensor package processing

For every synchronized package sample, reconstruct the incremental PZT force of the five logical positions:

```text
Center
Left
Right
Top
Bottom
```

Conceptually:

```python
delta_force = {
    "center": dF_center,
    "left": dF_left,
    "right": dF_right,
    "top": dF_top,
    "bottom": dF_bottom,
}
```

Use the project's actual sensor-position constants.

Apply the same channel/package orientation mapping used by the existing Pressure Map.

Do not create a separate package geometry definition.

---

# 9. Calibration

Inspect how the current application applies PZT/package/channel calibration.

Reuse existing physical calibration where appropriate.

Do not blindly apply a Jerk Display-only visualization multiplier after the PZT force has already been converted to physical newtons.

Determine whether each existing gain represents:

- physical sensor calibration;
- package calibration;
- display scaling;
- signal-integration scaling.

Only physical sensor/package calibration should modify the reconstructed force.

Keep this behavior consistent with the existing normal/shear force calculation path.

If the distinction is unclear in the current code, preserve existing physical calibration semantics rather than inventing a new calibration layer.

Do not add a new independent set of per-sensor force calibration controls unless the existing architecture requires it.

---

# 10. Shear and normal-force separation

After obtaining the five incremental sensor forces for one package, pass them through the same existing shear/normal-force logic used by the current application.

Do not implement a second shear algorithm.

Conceptually:

```text
five incremental PZT forces
    ↓
existing shear calculation / detector
    ↓
incremental shear contribution
    +
residual normal-force sensor values
    ↓
existing normal-force calculation
```

The incremental **normal-force residual values** are the inputs used to generate the incremental pressure/force map.

The incremental **shear result** is accumulated for the package's numerical Shear Force readout.

---

# 11. Force map accumulation — important

Do not simply calculate one pressure map from the five current cumulative sensor-force values.

Instead, create a pressure map from each synchronized **incremental normal-force sample**, then add that map to the package's persistent accumulated force grid.

Use:

```text
ForceMap[n] =
    ForceMap[n-1]
    + Map(ΔNormalForce[n])
```

Conceptually:

```python
delta_shear = existing_shear_calculation(delta_force)

delta_normal = existing_normal_force_calculation(
    delta_shear.normal_residual
)

delta_pressure_result = pressure_map_generator.generate(
    delta_normal.normalized_or_expected_map_input
)

force_state.accumulated_grid += delta_pressure_result.pressure_grid
```

Use the exact value representation expected by the current `PressureMapGenerator`; inspect the current Jerk pipeline and preserve its normalization/calibration contract.

Why this accumulation model is required:

The Pressure Map generator is nonlinear. Its:

- package classification;
- active sensor mask;
- inferred position;
- spatial lobe;
- decay reach;
- peak gain;
- overlap behavior;

can depend on the current five-sensor pattern.

Therefore:

```text
Map(sum of force increments)
```

is not generally equivalent to:

```text
sum(Map(each force increment))
```

Force Display is intended to show where force has been accumulated over the event, so accumulate the generated incremental maps.

---

# 12. Use the existing Pressure Map generator

Do not write a second spatial force-map generator.

Use the existing:

```text
PressureMapGeometry
PressureMapGenerator
PressureMapArrayGenerator
```

or refactor their reusable spatial portions carefully when necessary.

`PressureMapGeometry` already provides the shared physical geometry.

The local map generator already defines the package field.

The array generator already defines package positioning and overlap behavior.

The Force Display must follow those same physical rules.

---

# 13. Do not corrupt immutable `PressureMapResult` semantics

The existing `PressureMapResult` contains more than a grid. It also retains:

- field-model information;
- package mode;
- active sensor mask;
- quadrant information;
- geometry;
- frame metadata;
- diagnostics.

Do not create an accumulated force result by taking an old `PressureMapResult` and replacing only `pressure_grid`.

That would produce an internally inconsistent result.

Instead, add a small force-display-specific result/state type or a generic render-field type.

For example:

```python
@dataclass(frozen=True)
class ForceMapPackageResult:
    sensor_id: str
    force_grid_n: np.ndarray
    normal_force_n: float
    shear_force_n: float
    geometry: PressureMapGeometry
    x_coordinates_mm: np.ndarray
    y_coordinates_mm: np.ndarray
    sensor_positions: dict
    grid_position: tuple[int, int] | None
    frame_id: int
```

Adapt the exact fields to what the renderer actually needs.

Do not duplicate large immutable pressure-field models just to display an accumulated raster.

---

# 14. Numerical Normal Force display

For every package in Force Display, show:

```text
Normal Force: <value> N
```

The displayed normal-force value must be derived from the accumulated sensor-derived normal-force calculation, not from summing image pixels.

Do **not** estimate physical force by:

```python
np.sum(force_grid)
```

or by integrating image intensity.

The spatial map is a visualization/inference of the force distribution. Its pixel sum is not automatically a calibrated physical force.

Accumulate the package-level incremental normal-force result supplied by the existing normal-force calculation.

Conceptually:

```python
package_state.normal_force_n += delta_normal.total_force_n
```

Use the project's actual field/name and sign convention.

---

# 15. Numerical Shear Force display

For every package in Force Display, also show:

```text
Shear Force: <value> N
```

Reuse the existing shear-force calculation and its current force convention.

If shear is represented internally as X/Y components, accumulate the **components**, not the magnitudes.

Correct concept:

```text
shear_x_total += delta_shear_x
shear_y_total += delta_shear_y

display_shear =
    existing_project_shear_magnitude_or_display_convention(
        shear_x_total,
        shear_y_total
    )
```

Do not do:

```text
display_shear += abs(delta_shear)
```

because that would prevent opposite shear directions from cancelling.

If the current app represents shear differently, preserve that established representation and derive the Force Display readout from the accumulated signed/vector state.

The requirement is that the package's displayed Shear Force represents the current reconstructed shear force state, not the historical sum of absolute shear activity.

---

# 16. Package readout layout

For each package shown in Force Display, include at minimum:

```text
<PZT/package ID>
Normal Force: X.XXX N
Shear Force:  Y.YYY N
```

Use the application's existing precision and unit-formatting conventions where possible.

For a single-package display, show the same two values clearly near the map/status area.

For an array, each package must have its own Normal Force and Shear Force values.

If the application already provides package labels or per-package status areas, extend them rather than creating a completely different visual language.

Optional array-wide totals may be retained only if they fit naturally into the current UI, but the required output is the **per-package Normal Force and Shear Force**.

---

# 17. No peak markers in Force Display

Force Display must **not show peak markers**.

This includes:

- no current incremental-map peak;
- no accumulated-grid maximum marker;
- no centroid marker;
- no inferred virtual peak marker.

The pressure-map generator may internally calculate peak positions as part of its spatial interpolation. That internal math is allowed and should remain unchanged.

The requirement applies to **Force Display presentation**.

Do not display a graphical peak marker or numerical peak-location readout in Force Display.

Jerk Display peak behavior must remain unchanged.

---

# 18. Force state reset behavior

PZT force is expected to return to zero after a complete bipolar load/unload event.

The current `pzt_force_calculation.py` already contains event-polarity/reset logic intended to reduce integration drift.

Reuse/refactor that behavior rather than implementing unrelated reset logic.

However, Force Display has additional package-level state:

- accumulated normal-force map;
- accumulated package normal force;
- accumulated shear state.

These must remain mutually consistent.

When a completed event is determined to have returned to zero, reset the complete package Force Display state atomically.

Conceptually:

```python
package_state.accumulated_grid.fill(0.0)
package_state.normal_force_n = 0.0
package_state.shear_x_n = 0.0
package_state.shear_y_n = 0.0

reset five channel force accumulators/event states
```

Do not allow one sensor channel to visually reset while the accumulated map and package force remain stale.

Use the existing force event/reset semantics as the basis, but coordinate them at package level.

If necessary, define a package-reset condition such as:

- a force event has occurred;
- opposite polarity has been observed as expected;
- all five baseline-centered PZT voltages have returned below the configured noise threshold;
- existing force reconstruction says the event is complete.

Do not add aggressive auto-zero behavior that can erase a real static reconstructed force state during an event.

---

# 19. Manual Force Display reset

Add a button in the Pressure Map settings or Force Display controls:

```text
Reset Force Display
```

It should clear:

- all per-channel force integrator state;
- package accumulated normal force;
- package accumulated shear;
- package accumulated force grid;
- array force-display state;
- last event state as appropriate.

The button should not modify calibration, geometry, or force settings.

This is a **force-state reset**, not a Vmid control.

Do not add a Manual Vmid field.

---

# 20. When Force Display state must be invalidated

Automatically clear/reinitialize Force Display state when a change makes the accumulated force mathematically incompatible with future samples.

Examples:

- acquisition starts a new run;
- acquisition stops and restarts;
- active channel configuration changes;
- sensor/package mapping changes;
- package array layout changes;
- PZT capacitance changes;
- Rleak changes;
- d33 changes;
- noise-threshold force-processing settings change;
- timing parameters used by leakage compensation change;
- the median-baseline processing state is reset/reinitialized;
- pressure-map geometry changes;
- pressure-map interpolation/shaping settings change in a way that changes generated spatial fields;
- mask geometry changes if the accumulated raster is stored already masked;
- sample continuity is lost;
- the ring buffer overwrites unprocessed samples;
- a timestamp discontinuity makes the force integration invalid.

Changes that are purely presentation-only should not necessarily clear the physical force state.

Examples:

- color palette;
- legend visibility;
- GUI panel size.

If mirroring is only a renderer transform, do not clear force. If mirroring alters stored raster coordinates in the current implementation, handle it consistently.

---

# 21. Force calculation settings

Add a clearly named settings group under the existing Pressure Map settings, for example:

```text
PZT Force Calculation
```

Only add parameters needed for physical PZT force reconstruction.

At minimum include the parameters already supported by `pzt_force_calculation.py` / shared PZT force defaults:

### PZT capacitance

```text
Capacitance value
Capacitance unit
```

Use the existing supported units, currently including:

```text
pF
nF
F
```

### Connected leakage resistance

```text
Rleak (Ω)
```

This is the effective PZT leak resistance during the connected interval.

### d33

```text
d33 (pC/N)
```

Internally convert to C/N.

### Noise threshold

```text
Noise threshold (V)
```

Reuse the current threshold semantics from `pzt_force_calculation.py`.

Do not add Vmid.

Do not add a Vmid source selector.

Do not add quiet-window baseline settings if the app's existing time-series median-baseline mechanism already owns baseline behavior.

---

# 22. Timing inputs for leakage compensation

Inspect the existing acquisition/timing engine and reuse its timing outputs.

Force reconstruction should use the most physically correct timing already available in the application.

Where available, provide:

```text
wall_dt
leak_dt
pre_sample_decay_dt
```

with the same meanings already used by the PZT force/timing work.

The force calculation already supports:

```python
leak_dt_s
pre_sample_decay_dt_s
```

and optional off-MUX leakage.

Do not duplicate timing formulas inside the Pressure Map GUI if the project already has timing helpers.

Prefer:

```text
existing timing calculator
    ↓
force reconstruction
```

not:

```text
Pressure Map GUI
    ↓
new independent timing formulas
```

---

# 23. Optional off-MUX leakage

`pzt_force_calculation.py` supports optional off-MUX leakage using:

```text
off_mux_leak_enabled
off_mux_rleak_ohm
```

Preserve this capability if it is already exposed or intended to be exposed in the project's PZT force settings.

If the rest of the app does not currently support a reliable off-MUX leakage model, do not invent one merely for this feature.

Use the same shared PZT force defaults and validation.

---

# 24. Shared Pressure Map settings

Do not create duplicated settings such as:

```text
Force sensor spacing
Force package spacing
Force peak offset
Force outer boundary
Force decay reach
Force peak gain
Force pixels/mm
```

The existing Pressure Map settings are shared.

One setting should control both displays.

Examples:

```text
Sensor spacing
Package center spacing
Outer boundary reach
Peak-position outer offset
Pixels/mm
Peak gain behavior
Decay/reach behavior
Signal-map geometry
Array geometry
Mask selection/use
Display orientation
```

must remain central Pressure Map settings.

If an existing setting is physically expressed in the current Jerk signal's arbitrary units and cannot meaningfully be reused with inputs expressed in N, inspect its purpose carefully before changing anything.

Prefer preserving the exact existing map behavior requested by the feature.

If a unit-dependent threshold must be adapted for force inputs, implement the smallest explicit force-specific calculation threshold needed and document why. Do not silently reinterpret an existing Jerk setting.

---

# 25. Force Display units

All numerical Force Display force values must be shown in:

```text
N
```

unless the project already provides an automatic N/mN formatting helper.

Use existing unit-formatting conventions if available.

The map legend/intensity should be labeled as force rather than the existing Jerk signal unit.

Do not label accumulated Force Display values as voltage.

---

# 26. Rendering architecture

Prefer reusing/refactoring `PressureMapWidget` rather than copying the entire widget.

The widget should be able to render:

1. the existing Jerk/pressure result; and
2. an accumulated Force Display field.

A suitable refactor may separate:

```text
field raster
geometry metadata
package overlays
numerical readouts
display mode
```

Do not make the renderer depend on a fake or internally inconsistent `PressureMapResult`.

Add a Force Display mode or a generic raster/frame data object.

The Force Display renderer needs enough information for:

- accumulated force raster;
- x/y coordinates;
- package centers;
- sensor marker locations;
- pressure-map boundaries;
- mask;
- package labels;
- Normal Force readout;
- Shear Force readout.

It does **not** need peak-marker metadata.

---

# 27. Peak-marker suppression implementation

Implement explicit Force Display behavior such as:

```python
show_peak_markers = False
```

or an equivalent display-mode rule.

Do not remove peak-related code globally because Jerk Display may still use it.

Do not remove internal peak calculations from `PressureMapGenerator`; they affect spatial interpolation.

Only suppress Force Display's presentation of peak markers.

---

# 28. Array Force Display

Support the same sensor-package array arrangement as the existing Pressure Map.

Each package must preserve its own persistent accumulated local force field.

Conceptually:

```python
package_states = {
    "PZT1": ForcePackageState(...),
    "PZT2": ForcePackageState(...),
    ...
}
```

For every new synchronized sweep:

1. calculate the five incremental PZT forces for each package;
2. calculate incremental package shear;
3. calculate incremental normal residual;
4. generate that package's incremental pressure map;
5. add it to the package's persistent accumulated grid;
6. update the package's accumulated Normal Force;
7. update the package's accumulated shear state.

After processing all new sweeps, compose the package fields into the world-space Force Display array.

---

# 29. Array compositor refactor

The existing `PressureMapArrayGenerator` evaluates retained pressure field models in world coordinates and blends overlapping package supports.

An accumulated force raster is not automatically equivalent to a normal `PressureMapResult` field model.

Do not pretend an accumulated grid is a regular `PressureMapResult`.

Refactor/extract only the reusable array-composition logic needed to position and blend already-generated local fields.

For example, a generic internal compositor may accept:

```text
local raster
local x/y coordinates
package center
support bounds
activity/presence mask
geometry
```

and apply the same existing:

- package centers;
- structural neighbor logic;
- overlap bounds;
- confidence blending;
- support clipping.

Preserve existing array behavior for Jerk Display.

Add tests proving the refactor does not change current Jerk array output.

---

# 30. Important note about accumulated array fields

Prefer accumulating each package in its **local package coordinates**, then array-compose the current accumulated package fields for rendering.

Do not permanently accumulate only the already-blended array raster.

Why:

- package force state should remain independent;
- package Normal/Shear readouts are per package;
- layout changes should be detectable;
- array blend geometry may change;
- local package state is easier to reset/test;
- the display can be recomposed without corrupting physical accumulation.

---

# 31. Mask behavior

If the Pressure Map mask feature exists in the current branch, Force Display must use the same selected mask and mask geometry.

Do not maintain a separate Force Display mask configuration.

Prefer applying the mask as a presentation/composition operation rather than destroying accumulated physical package state, unless the current Pressure Map architecture defines masking earlier.

The screen outside the mask should behave exactly like the Jerk Display's mask behavior.

If the mask changes, the force state should not need to be physically reintegrated if the accumulated unmasked field is retained internally.

---

# 32. GUI refresh behavior

Separate acquisition processing from expensive rendering as much as practical.

The Force state must continue to receive/process new samples even when Force Display is not the currently visible inner tab, otherwise switching from Jerk to Force would show an incomplete force history.

Recommended behavior:

### Pressure Map outer tab active, Jerk Display selected

- continue existing Jerk rendering;
- process newly acquired samples through the lightweight Force reconstruction/state update;
- do not unnecessarily render Force Display every GUI frame.

### Pressure Map outer tab active, Force Display selected

- process all new force samples;
- render Force Display;
- avoid unnecessary full Jerk rendering if current architecture allows it.

### Settings selected

Do not lose Force samples merely because Settings is visible.

Either:

- continue force state processing without rendering; or
- safely process backlog from the acquisition buffer when returning.

### Pressure Map outer tab not visible

Do not modify acquisition behavior.

If the app already continues background data processing, keep Force state current.

If Force processing is intentionally deferred while hidden, guarantee that the complete unprocessed sample history remains available and process it exactly once when the Pressure Map tab is shown again.

If required samples have already been overwritten, reset Force state and report a clear diagnostic instead of integrating across a gap.

---

# 33. Do not tie integration to paint events

Never perform force integration inside:

```text
paintEvent
draw()
repaint()
```

or equivalent rendering callbacks.

Force reconstruction is data processing.

Painting is presentation.

A window expose/repaint must not change the physical force state.

---

# 34. Performance

The feature must not interfere with real-time acquisition.

Optimize in this order:

1. process only new samples;
2. avoid duplicate ADC→voltage conversion;
3. reuse baseline-centered data when available;
4. reuse existing timing results;
5. reuse pressure-map generator instances;
6. render only the visible display;
7. compose the array once after all new samples for the frame;
8. avoid recreating static geometry/masks every sample;
9. avoid unnecessary large array copies.

Do not prematurely replace the exact force calculation with a lossy approximation.

First implement correct sample-by-sample behavior, then benchmark.

---

# 35. Settings persistence

Persist the new PZT Force Calculation parameters through the existing application settings mechanism.

Use the project's current schema/version/migration style.

A suitable conceptual structure is:

```json
{
  "pzt_force": {
    "capacitance_value": 100.0,
    "capacitance_unit": "pF",
    "rleak_ohm": 1000000.0,
    "d33_pc_per_n": 300.0,
    "noise_threshold_v": 0.002,
    "off_mux_leak_enabled": false,
    "off_mux_rleak_ohm": null
  }
}
```

Use the actual existing default values from the project's PZT force constants.

Do not hard-code the example numbers above if they differ from project defaults.

Do not persist Manual Vmid because Manual Vmid must not exist.

Existing older settings files must continue to load.

Missing PZT Force settings must fall back to the shared defaults.

---

# 36. Validation

Reuse `validate_pzt_force_settings()` and existing project validation patterns.

Reject or safely handle invalid physical inputs:

```text
Cpzt <= 0
Rleak <= 0
d33 <= 0
off-MUX Rleak <= 0 when enabled
non-finite values
invalid capacitance unit
non-monotonic timestamps
```

Do not allow invalid settings to silently generate NaN/Inf force maps.

A settings validation error should leave acquisition stable and show an understandable UI/status error.

---

# 37. Timestamp handling

Force reconstruction needs true elapsed time.

Use the application's real per-sample/sweep timestamps.

Do not infer:

```text
dt = 1 / nominal GUI refresh rate
```

Do not infer force timing from the plotting FPS.

Where MUX-connected exposure differs from wall elapsed time, pass the existing calculated/measured leakage exposure separately using the force calculation's `leak_dt_s` support.

---

# 38. Discontinuity detection

Detect conditions where the force state cannot be continued reliably, including:

- timestamp goes backward;
- duplicate timestamp where strict monotonic timing is required;
- sequence counter jumps over unavailable samples;
- acquisition restarts;
- channel mapping changes;
- timing mode changes;
- ring-buffer overwrite causes missing samples.

On discontinuity:

1. do not integrate across the unknown interval;
2. reset/reinitialize Force Display state;
3. show/log a concise diagnostic;
4. continue cleanly from new data.

---

# 39. Thread safety

Follow the application's current acquisition/UI threading model.

Do not mutate acquisition buffers from the GUI.

When reading a live buffer:

- use the existing lock/snapshot mechanism;
- take a coherent snapshot of values + timestamps + sequence IDs;
- release the acquisition lock before expensive force/map calculations.

Keep Force Display state mutations in one well-defined owner/thread or protect them consistently.

---

# 40. Suggested state model

Use a centralized Force Display engine rather than scattering state across GUI widgets.

Conceptually:

```python
class PressureForceDisplayEngine:
    settings
    geometry

    channel_states
    package_states

    last_processed_sample_id

    def reset(...)
    def process_new_samples(...)
    def get_package_results(...)
    def get_array_result(...)
```

This engine should contain the physical live state.

The GUI should mainly:

```text
read controls/settings
    ↓
ask engine to process new data
    ↓
render returned display data
```

Do not store essential force integration state only inside plot widgets.

---

# 41. Suggested package state

A package state may conceptually contain:

```python
@dataclass
class ForcePackageState:
    channel_states: dict

    accumulated_force_grid_n: np.ndarray

    normal_force_n: float

    shear_x_n: float
    shear_y_n: float

    event_active: bool
    last_processed_sample_id: object | None
```

If the existing shear result is not represented as X/Y components, adapt this structure to the existing signed/vector representation.

Avoid accumulating shear magnitudes.

---

# 42. Relationship to `pzt_force_calculation.py`

Refactor `pzt_force_calculation.py` carefully so the established batch behavior remains valid.

The existing public functions should remain backward compatible where possible:

```python
calculate_pzt_force_from_settings(...)
calculate_pzt_force_from_voltage(...)
estimate_pzt_quiet_baseline(...)
pzt_capacitance_to_farads(...)
validate_pzt_force_settings(...)
```

Force Display does **not** need to use `estimate_pzt_quiet_baseline()` for Vmid because the requested behavior is to use the application's existing time-series median baseline.

Do not delete `estimate_pzt_quiet_baseline()` if other features use it.

The live Force Display may call the low-level force step with voltage that is **already centered around the existing median baseline**.

If the low-level API currently always subtracts Vmid internally, extend/refactor it cleanly so pre-centered voltage can be used without subtracting another median.

Avoid double baseline subtraction.

---

# 43. Avoid double baseline subtraction

This is critical.

If Force Display receives:

```text
centered_voltage = raw_voltage - existing_time_series_median
```

then the live force calculation must not again perform:

```python
centered_voltage -= np.median(centered_voltage)
```

or subtract another Vmid.

Create a clear API contract.

For example:

```python
process_centered_sample(...)
```

or:

```python
calculate_pzt_force_step(
    centered_voltage_v=...
)
```

The batch API may continue accepting raw voltage and optional Vmid for backward compatibility.

---

# 44. Noise threshold placement

Apply the PZT force noise threshold to the baseline-centered PZT voltage, consistent with the existing force calculation.

Conceptually:

```python
if abs(centered_voltage_v) < noise_threshold_v:
    active_voltage = 0.0
else:
    active_voltage = centered_voltage_v
```

Keep the existing exact threshold/reset semantics unless the live refactor requires a clearly justified consistency fix.

Do not reuse the Jerk Display's map-activity threshold as the PZT voltage noise threshold.

They are different concepts:

- PZT voltage noise threshold: force reconstruction input filtering;
- pressure-map activity threshold: spatial field generation/display behavior.

---

# 45. Existing Pressure Map spatial threshold

Continue using the existing Pressure Map generator's activity threshold when building each incremental normal-force map.

Do not remove its package classification behavior.

The PZT force noise threshold occurs earlier in the pipeline.

Pipeline:

```text
centered PZT voltage
    ↓
PZT voltage noise threshold
    ↓
Δforce
    ↓
shear/normal
    ↓
PressureMapGenerator's existing map threshold/shaping
```

---

# 46. Signed force

Preserve signed incremental force through the reconstruction and map-generation stages.

Do not take absolute value before integration.

PZT press/release is bipolar and the force reconstruction depends on signed increments.

The existing Pressure Map generator supports signed fields.

Use the existing display's signed/magnitude behavior as appropriate, but do not destroy sign in the underlying Force Display state.

---

# 47. Force returns to zero

The expected physical behavior is that a completed force event eventually returns the reconstructed force state to zero.

Do not add arbitrary clipping that hides integration drift.

Use:

- correct leakage compensation;
- correct baseline;
- correct timing;
- current event reset mechanism;
- noise threshold;
- atomic package reset.

If residual drift remains, log/display it during development and fix the physical/state logic rather than silently zeroing every small force value continuously.

---

# 48. No saturation through endless history

Force Display is an event-state reconstruction, not a lifetime integral.

Do not keep accumulating forever after a completed press/release pair.

Use the existing bipolar event completion behavior to return the package state to exact zero.

This is what prevents long-term saturation.

---

# 49. Tests — force math

Add unit tests verifying that the new live step calculation matches the existing batch reconstruction.

For the same input waveform and timing:

```text
batch_force_trace[n]
```

must match:

```text
live_integrator_state_after_sample_n
```

within floating-point tolerance.

Test:

1. no leakage;
2. connected leakage;
3. optional off-MUX leakage;
4. pre-sample decay correction;
5. positive event;
6. negative event;
7. bipolar event;
8. noise-threshold behavior;
9. return-to-zero/reset;
10. invalid timing.

---

# 50. Tests — baseline

Verify:

1. Force Display uses the existing time-series median baseline.
2. Force Display does not calculate a separate Manual Vmid.
3. Force Display does not subtract a second median after receiving centered data.
4. Jerk Display's existing baseline behavior remains unchanged.
5. Force reconstruction taps the stream before Jerk-specific HPF/moving-sum processing.

---

# 51. Tests — incremental map accumulation

Use deterministic five-sensor input patterns.

Verify:

```text
force_grid_after_two_steps
=
map(step_1) + map(step_2)
```

within floating-point tolerance.

Do not test against:

```text
map(step_1 + step_2)
```

as the primary expected behavior.

Test:

- center-only additions;
- isolated outer additions;
- center + outer additions;
- multi-sensor additions;
- positive and negative increments;
- force applied at different locations over time.

---

# 52. Tests — package force readouts

For each package verify:

```text
Normal Force
Shear Force
```

are updated correctly.

Normal Force must equal the accumulated package normal-force result from the sensor-processing path.

Shear Force must equal the accumulated signed/vector shear state using the current shear convention.

Do not derive either value from image-pixel intensity.

---

# 53. Tests — no peak markers

Force Display must render with no peak marker regardless of:

- center-only force;
- outer force;
- inferred outboard peak;
- multi-sensor force;
- positive/negative field;
- array mode.

Jerk Display must preserve its existing peak-marker behavior.

---

# 54. Tests — reset

Verify full package Force Display reset clears:

- all five force channel states;
- accumulated local force grid;
- Normal Force;
- Shear Force/components;
- event state;
- array/compositor cached result.

Test both:

- automatic completed-event reset;
- Reset Force Display button.

---

# 55. Tests — settings

Changing these should invalidate/reset force state:

```text
Cpzt
Rleak
d33
noise threshold
force-relevant timing
channel/package mapping
pressure-map geometry/interpolation
```

Pure presentation changes should not corrupt the force state.

Verify older settings files without the new `pzt_force` section still load.

---

# 56. Tests — Jerk regression

This feature must not change existing Jerk Display output.

Before refactoring shared map/array code, add or use deterministic regression fixtures.

After the implementation, verify for the same current Jerk inputs:

```text
old pressure_grid
≈
new pressure_grid
```

and, for arrays:

```text
old array pressure_grid
≈
new array pressure_grid
```

within the existing numerical tolerance.

Also verify:

- package modes;
- array positions;
- overlap blending;
- geometry;
- masking;
- display orientation.

---

# 57. Tests — sample exactly once

Simulate:

- GUI refresh with zero new samples;
- refresh with one new sample;
- refresh with many new samples;
- repeated repaint;
- tab switching;
- Settings tab open;
- Pressure Map hidden and shown again.

The accumulated physical force must depend only on newly acquired samples.

Repeated GUI redraws with no new data must leave the force state bit-for-bit or numerically unchanged.

---

# 58. Acceptance criteria

The implementation is complete only when all of the following are true.

## UI

- [ ] Current `Display` tab is renamed to `Jerk Display`.
- [ ] New `Force Display` tab exists.
- [ ] Existing `Settings` remains available.
- [ ] Force Display uses the same Pressure Map geometry/settings.
- [ ] Force Display shows no peak markers.
- [ ] Every package shows `Normal Force`.
- [ ] Every package shows `Shear Force`.
- [ ] Force values are displayed in N.

## Vmid/baseline

- [ ] No Manual Vmid field exists.
- [ ] No Vmid-source selector exists.
- [ ] Force Display reuses the existing time-series median-baseline mechanism.
- [ ] No second median subtraction occurs in Force Display.
- [ ] Force reconstruction uses baseline-centered voltage before Jerk-specific HPF/moving-sum processing.

## Force calculation

- [ ] PZT force uses the shared capacitance/leakage/d33 formula.
- [ ] New samples are integrated exactly once.
- [ ] Actual sample timing is used.
- [ ] Existing connected-time/pre-sample timing is reused where available.
- [ ] Existing optional off-MUX leakage support is preserved where applicable.
- [ ] PZT voltage noise threshold is applied consistently.
- [ ] Signed increments are preserved.
- [ ] Completed bipolar events return Force Display state to zero.

## Spatial map

- [ ] Every new synchronized package sample generates an incremental normal-force map.
- [ ] Force Display accumulates incremental maps over time.
- [ ] It does not simply map cumulative sensor values.
- [ ] Existing `PressureMapGenerator` spatial behavior is reused.
- [ ] Existing geometry is reused.
- [ ] Existing mask behavior is reused.
- [ ] Array layout and overlap behavior are preserved.

## Readouts

- [ ] Normal Force comes from accumulated sensor-derived normal force, not image pixels.
- [ ] Shear Force comes from accumulated signed/vector shear state, not summed absolute magnitudes.
- [ ] Each package has its own Normal Force and Shear Force readout.

## Stability/performance

- [ ] Jerk Display behavior is unchanged.
- [ ] Existing Pressure Map settings files remain compatible.
- [ ] Force state resets safely after discontinuity.
- [ ] No force integration occurs in paint events.
- [ ] Rendering does not process samples twice.
- [ ] Acquisition performance is not degraded by expensive GUI work.

---

# 59. Implementation order

Follow this order to minimize regression risk.

## Phase 1 — Inspect and document current data path

Before editing, identify and note in code comments/working notes:

1. raw ADC buffer;
2. ADC→voltage conversion;
3. exact time-series median-baseline implementation;
4. point where Jerk-specific HPF/filtering begins;
5. sample timestamp/sequence metadata;
6. current package mapping;
7. calibration path;
8. existing shear calculation;
9. existing normal-force calculation;
10. Pressure Map widget update path;
11. Pressure Map settings persistence;
12. array composition path.

Do not begin by rewriting GUI code.

## Phase 2 — Refactor reusable force step

Refactor `pzt_force_calculation.py` so:

- batch calculation still works;
- live centered-voltage sample calculation is reusable;
- there is one mathematical implementation;
- no second baseline is required for pre-centered live samples.

Add unit tests.

## Phase 3 — Build live package force engine

Implement:

- per-channel state;
- per-package state;
- exactly-once sample processing;
- timing input;
- incremental shear;
- incremental normal force;
- Normal/Shear accumulation;
- event reset.

Test without GUI first.

## Phase 4 — Incremental local force maps

For each synchronized package sample:

- create incremental normal-force map;
- add to accumulated package raster.

Test deterministic patterns.

## Phase 5 — GUI tabs/readouts

- rename `Display` → `Jerk Display`;
- add `Force Display`;
- reuse/refactor renderer;
- show Normal Force + Shear Force;
- explicitly disable peak markers.

## Phase 6 — Settings/persistence

Add PZT Force Calculation settings only.

Do not duplicate Pressure Map geometry settings.

Do not add Manual Vmid.

Add Reset Force Display.

## Phase 7 — Array support

Refactor reusable array raster composition without changing Jerk output.

Compose accumulated local force fields.

Display per-package Normal/Shear values.

## Phase 8 — Lifecycle/performance hardening

Handle:

- tab switching;
- hidden tab;
- Settings tab;
- acquisition restart;
- buffer discontinuity;
- settings invalidation;
- rendering performance.

Run complete regression tests.

---

# 60. Coding constraints

- Keep changes focused on this feature.
- Do not remove existing features.
- Do not change Jerk Display numerical behavior.
- Do not duplicate pressure-map geometry code.
- Do not duplicate the PZT force equation.
- Do not add Manual Vmid.
- Do not add Force Display peak markers.
- Do not calculate force from pressure-map pixel sums.
- Do not accumulate shear magnitudes.
- Do not integrate samples from GUI paint/repaint events.
- Do not process the same sample twice.
- Do not silently integrate across missing sample history.
- Prefer dataclasses and existing project patterns.
- Keep data processing independent of PyQt where practical.
- Add comments for non-obvious force-state/timing logic.
- Validate all new settings.
- Preserve backward-compatible settings loading.
- Add tests before or alongside risky refactors.

---

# 61. Final deliverables

After implementation, provide:

1. a concise summary of files changed;
2. a description of the final Force Display data path;
3. the exact location where the existing time-series median baseline is reused;
4. the exact force equation/timing inputs used;
5. how samples are guaranteed to be processed exactly once;
6. how package Normal Force is accumulated;
7. how package Shear Force is accumulated;
8. how automatic force reset works;
9. confirmation that Force Display has no peak markers;
10. confirmation that Jerk Display numerical output is unchanged;
11. tests added and their results;
12. any remaining limitations or assumptions.

If the current project architecture makes any instruction above impossible without a risky redesign, choose the smallest low-risk implementation that preserves the stated behavior and document the tradeoff instead of silently changing the feature semantics.
