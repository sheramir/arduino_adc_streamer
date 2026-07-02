# Pressure Map Tab - Sensor Shape And Adjacent Package Interpolation

**Owner:** Host Application (GUI / Data Processing)

**Version:** Draft 1

**Date:** 2026-07-02

---

## 1. Purpose

Upgrade the Pressure Map tab so the display can better represent both single
sensor packages and array configurations.

The upgrade has two parts:

- Let the user choose how the whole sensor-package footprint is outlined:
  circle, square, or hidden.
- In array configurations, render pressure continuously between adjacent sensor
  packages instead of showing each package as an isolated pressure surface.

The feature is display-only. It must not change acquisition, firmware protocol,
raw ADC storage, or exported raw data.

---

## 2. Current Behavior

The Pressure Map tab currently computes pressure independently for each
five-sensor package.

Each package contains the logical positions:

```text
T, R, L, C, B
```

The pressure-map generator builds one package-local pressure surface from those
five values. In array mode, the widget displays multiple package-local maps in
their configured grid cells, but the packages are still rendered as separate
surfaces.

Each package is currently drawn with a circular footprint/boundary around the
whole five-sensor package.

---

## 3. New Feature 1: Package Boundary Shape

### 3.1 User-Facing Behavior

Add a Pressure Map setting named:

```text
Package boundary shape
```

The setting shall have three options:

| Option | Behavior |
| --- | --- |
| Circle | Draw the whole package footprint boundary as a circle |
| Square | Draw the whole package footprint boundary as a square |
| None | Hide the whole package footprint boundary |

Circle and square package boundaries shall be drawn with dotted lines.

This setting applies to every Pressure Map configuration:

- single package
- manual channel layout
- array layout
- PZT/PZR combined modes where the Pressure Map tab is available

The setting controls only the whole-package footprint boundary. It does not control:

- the pressure-point peak marker
- shear arrows
- package labels
- the small internal T/R/L/C/B sensor markers
- the pressure heatmap itself

### 3.2 Persistence

The selected package boundary shape shall be stored in the existing Pressure Map settings
payload and restored on restart.

Default:

```text
Package boundary shape = Circle
```

Circle preserves the current visual style.

### 3.3 Implementation Notes

Add constants:

```text
DEFAULT_PRESSURE_PACKAGE_BOUNDARY_SHAPE = "circle"
PRESSURE_PACKAGE_BOUNDARY_SHAPES = ("circle", "square", "none")
```

Circle should use an ellipse graphics item. Square should use a rectangle
graphics item. None should hide the boundary item.

The setting belongs in:

- `constants/pressure_map.py` for defaults and accepted values
- `gui/signal_integration_panel.py` for the settings control and persistence
- `gui/pressure_map_widget.py` for rendering behavior

The widget should expose a method such as:

```python
configure_package_boundary(boundary_shape: str | None = None)
```

The existing `configure_markers(show_marker=...)` should continue to mean
pressure-point peak markers, not package boundaries.

---

## 4. New Feature 2: Physical Distance Between Adjacent Packages

### 4.1 User-Facing Behavior

Add a Pressure Map setting named:

```text
Package gap
```

Units:

```text
mm
```

Default:

```text
2 mm
```

This value is the physical edge-to-edge distance between neighboring sensor
packages in the array.

For vertical neighbors, it is the distance between:

```text
top edge of the lower package
bottom edge of the upper package
```

For horizontal neighbors, it is the distance between:

```text
left edge of the right package
right edge of the left package
```

The same package gap applies to all directly adjacent packages in the array.

Add two additional Pressure Map tuning settings:

| Setting | Default | Description |
| --- | --- | --- |
| Gap contrast | 0.33 | Controls how much an estimated inter-package pressure point may rise above the stronger facing sensor. A value of `0` disables extra peak lift. |
| Gap fade width | 0.5 | Controls the lateral half-width of gap pressure as a fraction of the package footprint diameter. Smaller values create a narrow bridge; larger values spread pressure wider. |

These tuning settings shall have hover/tool-tip explanations in the UI and
shall persist with the other Pressure Map settings.

### 4.2 Geometry Assumption

The existing `Circle diameter` setting represents the package pressure
footprint diameter. Therefore the center-to-center distance between adjacent
packages is:

```text
package_center_spacing_mm = circle_diameter_mm + package_gap_mm
```

Example:

```text
circle_diameter_mm = 4 mm
package_gap_mm = 2 mm
package_center_spacing_mm = 6 mm
```

If the implementation later introduces non-circular package footprints, this
formula should be renamed to use `package_width_mm` and `package_height_mm`.

---

## 5. New Feature 3: Pressure Between Adjacent Packages

### 5.1 User-Facing Behavior

In array configurations, the Pressure Map tab shall show pressure not only
inside each individual package footprint, but also in the physical space between
neighboring packages.

For example, if the selected array contains:

```text
PZT1, PZT3, PZT5, PZT6, PZT7
```

and `PZT6` is in the middle with `PZT1`, `PZT3`, `PZT5`, and `PZT7` around it,
then the Pressure Map should display continuous pressure in the gaps between
`PZT6` and each directly adjacent package.

When force is applied in the package gap:

- the map should not appear empty between packages
- the value should be weighted by nearby package edge sensors
- the displayed pressure should gradually fade toward the contributing sensors
- direct neighbors should influence the gap more than diagonal or distant
  packages

This behavior applies only when at least two complete adjacent packages are
available. In a single-package configuration, the existing per-package pressure
surface remains the active behavior.

### 5.2 Adjacency Rules

Two packages are adjacent when their array-layout grid positions differ by one
cell horizontally or vertically:

```text
same row, column differs by 1
same column, row differs by 1
```

Diagonal packages are not adjacent for the first implementation.

### 5.3 Sensors Used For Adjacent Pressure

For each adjacent package pair, use both the facing sensors and each package
center sensor.

| Relationship | First package sensor | Second package sensor |
| --- | --- | --- |
| left package to right package | R | L |
| right package to left package | L | R |
| upper package to lower package | B | T |
| lower package to upper package | T | B |

For a vertical pair where `PZT3` is below `PZT6`, the pressure-point decision
should consider:

```text
PZT3_C
PZT3_T
PZT6_B
PZT6_C
```

The center sensors are required because they distinguish pressure that belongs
inside an existing package from pressure that belongs in the gap between
packages.

### 5.4 Pressure-Point-Aware Gap Model

For each adjacent pair, define a rectangular gap region between the two package
footprints.

For a horizontal neighbor pair:

```text
gap x-range: right edge of left package -> left edge of right package
gap y-range: overlapping package footprint height
```

For a vertical neighbor pair:

```text
gap x-range: overlapping package footprint width
gap y-range: top edge of lower package -> bottom edge of upper package
```

The gap calculation must be pressure-point aware. It must not only average the
two facing sensors.

For each adjacent pair:

1. Read the source package center, source package facing sensor, neighbor
   package facing sensor, and neighbor package center.
2. Decide whether the pressure peak belongs inside a package or inside the
   inter-package gap.
3. Render the gap as a continuation of that pressure surface.

### 5.4.1 Case A - Peak Between Neighboring Facing Sensors

If the facing sensors are stronger than their package centers, or the package
centers do not dominate the local evidence, the pressure peak may be between
the two neighboring packages.

Example:

```text
PZT3_T = 5
PZT6_B = 2
```

Assume `PZT3_T` faces `PZT6_B`. Since `PZT3_T` is stronger, the peak should be
closer to `PZT3_T`.

Recommended peak-position estimate:

```text
fraction_from_PZT3_T_to_PZT6_B = PZT6_B / (PZT3_T + PZT6_B)
                               = 2 / (5 + 2)
                               = 0.286
```

So the pressure point is about `29%` of the way from `PZT3_T` toward `PZT6_B`.

Recommended peak-height estimate:

```text
peak = max(PZT3_T, PZT6_B) + contrast_gain * abs(PZT3_T - PZT6_B)
```

With:

```text
contrast_gain = 0.33
```

The example becomes:

```text
peak = 5 + 0.33 * abs(5 - 2)
     = 5.99
     ~= 6
```

The displayed pressure profile may look like:

```text
PZT3_T sensor value      = 5.0
near PZT3_T              = 5.5
estimated pressure point = 6.0
middle of gap            = 4.5
near PZT6_B              = 2.8
PZT6_B sensor value      = 2.0
```

This means the strongest displayed point is allowed to be extrapolated above
the measured sensor values when the surrounding evidence suggests a pressure
point between sensors.

### 5.4.2 Case B - Peak Inside A Package

If a package center sensor is stronger than its facing edge sensor, the pressure
peak belongs inside that package. The neighboring facing sensor should be
treated as seeing the same pressure surface after it decays through the package
edge and the inter-package gap.

Example:

```text
PZT3_C = 8
PZT3_T = 5
PZT6_B = 2
```

In this case, the peak is not in the gap. It is inside `PZT3`, between `PZT3_C`
and `PZT3_T`. The gap should extend that package pressure outward:

```text
PZT3_C center              = 8.0
between C and T            = 6.8
PZT3_T edge sensor         = 5.0
package edge               = 4.2
middle of gap              = 3.2
near PZT6_B                = 2.4
PZT6_B sensor              = 2.0
```

The implementation should not create a new gap peak near `6` in this case,
because the strongest evidence says the pressure peak is already inside `PZT3`.

The same rule applies symmetrically if the neighbor package center is strongest.

### 5.4.3 Decision Rules

Use the calibrated values after noise thresholding and package-specific gains.

For each adjacent pair:

- If one package center is stronger than its facing edge sensor and stronger
  than the neighbor facing sensor, treat the pressure as package-internal and
  decay it outward through the gap.
- If both package centers are weaker than the facing edge sensors, allow a gap
  pressure point between the packages.
- If one facing edge sensor is much stronger than the other, move the gap
  pressure point closer to the stronger facing sensor.
- If both facing edge sensors are similar, place the gap pressure point near the
  middle of the gap.
- If all relevant values are near zero after thresholding, leave the gap empty.

The first implementation may use these rules as deterministic heuristics. A
later implementation can replace the heuristics with a more formal surface-fit
model if needed.

### 5.4.4 Gap Surface Rendering

After the pressure point or package-internal source is selected, render a smooth
surface through the gap.

For a true gap peak, interpolate along the axis from one facing sensor to the
other with a peak at the estimated pressure point. Values should pass through or
near the measured facing sensor values.

For a package-internal peak, use the package-local pressure surface at the
facing edge as the source and decay toward the neighbor facing sensor.

Apply lateral fade away from the direct line between the two facing sensors:

```text
lateral_fade = clamp(1 - lateral_distance / fade_half_width, 0, 1)
gap_value = axial_value * lateral_fade
```

For horizontal pairs:

```text
lateral_distance = abs(y - pair_center_y)
```

For vertical pairs:

```text
lateral_distance = abs(x - pair_center_x)
```

Recommended default:

```text
fade_half_width = circle_diameter_mm / 2
```

Recommended initial constants:

```text
DEFAULT_PRESSURE_GAP_CONTRAST_GAIN = 0.33
PRESSURE_GAP_CONTRAST_GAIN_MIN = 0.0
PRESSURE_GAP_CONTRAST_GAIN_MAX = 10.0
PRESSURE_GAP_CONTRAST_GAIN_STEP = 0.05
PRESSURE_GAP_CONTRAST_GAIN_DECIMALS = 3
DEFAULT_PRESSURE_GAP_FADE_WIDTH_FRACTION = 0.5
PRESSURE_GAP_FADE_WIDTH_FRACTION_MIN = 0.01
PRESSURE_GAP_FADE_WIDTH_FRACTION_MAX = 10.0
PRESSURE_GAP_FADE_WIDTH_FRACTION_STEP = 0.05
PRESSURE_GAP_FADE_WIDTH_FRACTION_DECIMALS = 3
```

This creates a bridge of pressure through the gap that can either:

- rise to an extrapolated pressure point between sensors, or
- continue an internal package pressure outward through the gap.

### 5.5 Sign Handling

The current package pressure map supports both positive normal force and
optional negative release values.

Gap interpolation should follow the same sign policy:

- If `show_negative` is disabled, negative gap values are clamped to zero.
- If both facing sensors have the same sign, interpolate normally.
- If facing sensors have opposite signs, interpolate through zero rather than
  creating an artificial high magnitude between them.
- Center dominance uses magnitude for peak-location decisions, then the final
  rendered values are clamped according to the existing `show_negative` policy.

### 5.6 Interaction With Existing Package Maps

The array display should be built as one array-level pressure image:

1. Compute each package-local pressure map as today.
2. Place each package map into world coordinates using physical center spacing.
3. Compute gap regions for adjacent package pairs.
4. Blend gap regions into the same array-level grid.
5. Draw package boundaries, internal sensor markers, peak markers, shear arrows, and
   labels as overlays.

This avoids showing separate disconnected image items and makes the space
between packages part of the same heatmap.

For the first implementation, when package-local pressure and gap pressure
overlap, use the value with the larger absolute magnitude. Later versions can
replace this with smoother alpha blending if needed.

---

## 6. Proposed Data Model

Add an array-level result type in `data_processing/pressure_map_generator.py`
or a new dedicated module such as `data_processing/pressure_map_array_generator.py`.

Recommended new dataclasses:

```python
@dataclass(frozen=True, slots=True)
class PressureMapArrayPackage:
    sensor_id: str
    grid_position: tuple[int, int]
    normal_force_result: NormalForceResult
    pressure_result: PressureMapResult
    calibrated_values: dict[str, float]


@dataclass(frozen=True, slots=True)
class PressureMapArrayResult:
    pressure_grid: np.ndarray
    x_coordinates_mm: np.ndarray
    y_coordinates_mm: np.ndarray
    x_grid_mm: np.ndarray
    y_grid_mm: np.ndarray
    package_centers: dict[str, tuple[float, float]]
    package_results: dict[str, PressureMapResult]
    adjacent_pairs: tuple[tuple[str, str], ...]
    cell_size_mm: float
    total_extent_mm: float
```

The array generator should be GUI-independent and receive display-ready package
calculation inputs from `gui/signal_integration_panel.py`.

---

## 7. Implementation Plan

### Step 1 - Add Constants

Update `constants/pressure_map.py`:

- package boundary shape defaults and allowed values
- package gap default and spinbox range
- pressure-point extrapolation and gap fade defaults

Suggested constants:

```text
DEFAULT_PRESSURE_PACKAGE_BOUNDARY_SHAPE = "circle"
PRESSURE_PACKAGE_BOUNDARY_SHAPES = ("circle", "square", "none")

DEFAULT_PRESSURE_PACKAGE_GAP_MM = 2.0
PRESSURE_PACKAGE_GAP_MIN_MM = 0.0
PRESSURE_PACKAGE_GAP_MAX_MM = 1000.0
PRESSURE_PACKAGE_GAP_STEP_MM = 0.1
PRESSURE_PACKAGE_GAP_DECIMALS = 3

DEFAULT_PRESSURE_GAP_CONTRAST_GAIN = 0.33
PRESSURE_GAP_CONTRAST_GAIN_MIN = 0.0
PRESSURE_GAP_CONTRAST_GAIN_MAX = 10.0
PRESSURE_GAP_CONTRAST_GAIN_STEP = 0.05
PRESSURE_GAP_CONTRAST_GAIN_DECIMALS = 3
DEFAULT_PRESSURE_GAP_FADE_WIDTH_FRACTION = 0.5
PRESSURE_GAP_FADE_WIDTH_FRACTION_MIN = 0.01
PRESSURE_GAP_FADE_WIDTH_FRACTION_MAX = 10.0
PRESSURE_GAP_FADE_WIDTH_FRACTION_STEP = 0.05
PRESSURE_GAP_FADE_WIDTH_FRACTION_DECIMALS = 3
```

### Step 2 - Extend Pressure Map Settings UI

Update `gui/signal_integration_panel.py`:

- Add a `QComboBox` for package boundary shape in the Pressure Map settings group.
- Add a `QDoubleSpinBox` for package gap in millimeters.
- Add `QDoubleSpinBox` controls for gap contrast and gap fade width.
- Save the new settings in the existing `pressure_map` settings payload.
- Save and load all three gap settings from saved Pressure Map settings.
- Pass package boundary shape to `PressureMapWidget`.
- Rebuild the pressure-map generator or array generator when package gap,
  contrast, or fade width changes.

The package boundary shape setting applies always.

The package gap setting should be visible always, but its tooltip should state
that it only affects array layouts with adjacent packages.

Gap contrast and gap fade width should be visible always, with tooltips stating
that they only affect adjacent-package interpolation in array layouts.

### Step 3 - Update Physical Sensor Marker Rendering

Update `gui/pressure_map_widget.py`:

- Add widget state for `package_boundary_shape`.
- Hide whole-package boundary items when shape is `none`.
- Use an ellipse item for circle and a rectangle item for square.
- Apply the setting to both single-package and multi-package overlays.
- Preserve peak-marker behavior under the existing `show_marker` setting.

### Step 4 - Add Array-Level Geometry Helper

Add a GUI-independent helper, preferably in a new file:

```text
data_processing/pressure_map_array_generator.py
```

Responsibilities:

- Convert array grid positions to physical package centers.
- Use `circle_diameter_mm + package_gap_mm` for center spacing.
- Build an array-level output grid that covers all selected complete packages.
- Paste each package-local pressure grid into the array grid.
- Detect horizontal and vertical adjacent package pairs.
- Generate pressure-point-aware gap pressure for each adjacent pair.
- Use calibrated center and facing-edge values to decide whether the source is
  package-internal or inter-package.
- Allow a true inter-package pressure point to exceed the facing sensor values
  using the configured contrast gain.
- Treat neighbor-facing readings as decayed continuation when a package center
  dominates.
- Return one `PressureMapArrayResult`.

This keeps `PressureMapWidget` focused on drawing and avoids adding numeric
interpolation rules to GUI code.

### Step 5 - Route Array Mode Through The Array Generator

Update `gui/signal_integration_panel.py`:

- Keep the existing single-package path unchanged.
- In array mode, after `_build_pressure_map_package_displays()` produces
  complete package data, call the array generator when there are two or more
  packages.
- Pass the array-level result to the widget.
- Fall back to the existing package display behavior if array generation fails
  or if no adjacent pairs exist.

The current `PressureMapPackageDisplay` can either be extended to include
`calibrated_values`, or a separate data object can be built before display.

### Step 6 - Render The Array-Level Image

Update `gui/pressure_map_widget.py`:

- Add a method such as:

```python
update_array_display(array_result, package_displays)
```

- Draw one image item for the array-level pressure grid.
- Draw package boundaries at the array-result package centers.
- Draw internal T/R/L/C/B sensor markers using package center plus local sensor position.
- Draw peak markers and shear arrows per package using the same package center.
- Set the plot range from the array-result grid extents.
- Keep the readout format similar to the current array readout:

```text
Array packages: PZT1, PZT3, PZT5, PZT6, PZT7 | Total normal: ...
```

### Step 7 - Preserve Existing Behavior

The following behavior should remain unchanged:

- single-package pressure map generation
- shear detection
- normal force calculation
- integration controls
- timeline graph controls
- pressure-point peak marker setting
- mirror setting
- maximum intensity setting
- package labels in array mode
- saved settings import/export structure, except for the new keys

### Step 8 - Tests

Add or update tests:

- `tests/test_pressure_map_widget.py`
  - package boundary shape `circle` uses circular package outlines
  - package boundary shape `square` uses square package outlines
  - package boundary shape `none` hides package outlines without hiding internal sensor markers
  - array display draws one array-level image and still draws package overlays
  - mirror still flips package overlays in array display

- `tests/test_signal_integration_panel.py`
  - package boundary shape and package gap save/load round trip
  - gap contrast and gap fade width save/load round trip
  - package gap defaults to `2.0`
  - array generator is used only for multiple array packages
  - single-package path remains unchanged

- New `tests/test_pressure_map_array_generator.py`
  - package centers use `circle_diameter_mm + package_gap_mm`
  - horizontal adjacent packages produce a nonzero gap when facing sensors are active
  - vertical adjacent packages produce a nonzero gap when facing sensors are active
  - facing-sensor-dominant pairs can produce an extrapolated gap peak above the stronger facing sensor
  - center-dominant packages decay outward through the gap instead of creating a new gap peak
  - gap peak moves closer to the stronger facing sensor
  - diagonal packages do not create a gap bridge
  - opposite-sign facing sensors interpolate through zero
  - `show_negative=False` clamps negative gap values to zero

---

## 8. Acceptance Criteria

- User can choose whole-package boundary shape: circle, square, or none.
- Package boundary shape applies to every Pressure Map configuration.
- Package boundary shape persists across app restarts.
- User can configure package gap in millimeters.
- Package gap defaults to `2 mm`.
- Package gap persists across app restarts.
- Gap contrast and gap fade width are configurable in the UI, documented with
  tooltips, and persist across app restarts.
- In array mode, adjacent packages are positioned using physical package gap.
- Horizontally adjacent packages display pressure in the space between their
  facing sensors.
- Vertically adjacent packages display pressure in the space between their
  facing sensors.
- If facing sensors dominate, the gap can display an extrapolated pressure
  point above the stronger facing-sensor value.
- If a package center dominates, the gap displays a decayed continuation from
  that package instead of inventing a separate gap peak.
- Diagonal-only packages do not create a gap bridge.
- Single-package configurations preserve the existing pressure-map behavior.
- Existing shear arrows, pressure-point markers, package labels, mirror, and
  max-intensity behavior continue to work.
- Raw ADC data, acquisition behavior, and firmware protocol remain unchanged.

---

## 9. Open Questions

- Should package gap be stored only as a Pressure Map display setting, or should
  it eventually become part of the sensor-library physical layout?
- Should diagonal interpolation be added in a future version for corner contact
  between packages?
