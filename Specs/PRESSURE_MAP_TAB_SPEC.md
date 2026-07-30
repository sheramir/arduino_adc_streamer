# Pressure Map Tab Specification

Owner: Host application GUI/pressure-processing stack  
Status: Implemented  
Date: 2026-07-30

## Purpose and Scope

The **Pressure Map** tab is the live pressure/shear interpretation view for a five-position PZT package. It turns recent ADC counts into integrated, signed values for:

- a per-position timeline (optional);
- shear vectors extracted from opposite-sign outer-sensor pairs;
- residual normal-force values and a normal-force location estimate;
- a piecewise-linear pressure surface; and
- an array-level surface that can bridge directly adjacent package gaps.

The logical positions are `C` (centre), `L`, `R`, `T`, and `B`. The pressure-map coordinate system places C at `(0, 0)`, L/R at `(-spacing, 0)`/`(+spacing, 0)`, and T/B at `(0, +spacing)`/`(0, -spacing)` in millimetres.

The tab is a live view of the raw acquisition ring buffer. It does not load an offline capture and it does not use the Heatmap tab's RMS/Gaussian algorithm. Its PZR selector changes the **timeline** to Rosette data when supported; the pressure, normal, and shear maps continue to use the integrated five-position PZT values.

## Tabs, Controls, and Refresh Rules

The outer tab contains `Display` and `Settings` inner tabs.

### Display

- Optional integrated-signal timeline. It is hidden by default; hiding it does not stop the pressure/shear map calculation.
- Status label for actionable input/timeline conditions.
- Pressure-map widget, including pressure image, package boundaries, five sensor markers, optional calculated peak markers, per-package labels, normal-force readout, and shear arrow(s).

### Settings

- Save/load actions for the complete Pressure Map and shear settings payload.
- Signal Integration controls: HPF cutoff, rectangular integration-window length, displayed-history duration, optional Time Series median baseline, graph visibility, and PZT/PZR timeline selection.
- Shear processing: a noise threshold and per-package, per-position gains.
- Shear visualization: length gain, minimum visible magnitude, maximum length as a radius fraction, shaft base width, and optional width scaling.
- Pressure-map geometry: sensor spacing, circular footprint diameter, resolution, outer margin, pressure-point height shaping, array gap, gap contrast, and gap fade width.
- Rendering: fixed maximum intensity, boundary shape (`Circle`, `Square`, or `None`), show negative, peak marker, horizontal mirror, colour scheme, and legend settings.

The outer Pressure Map tab refreshes only while it is visible. The inner **Display** tab must also be selected: entering Settings stops a pending update; returning to Display queues a refresh. The main window coalesces ADC-driven requests and the configured refresh rate is 30 frames/second.

## Input Resolution and Availability States

1. The tab obtains display-channel specifications from the active channel/sensor configuration. A spec defines its exact acquisition sample indices, package ID, and logical position. This makes multiplexed arrays safe even where numeric channel IDs repeat.
2. It copies a recent contiguous raw-buffer snapshot. The visible duration defaults to 1 second. Additional historical sweeps (at least 256, subject to the global cap) are copied before the visible window so the moving integration has a correct initial history.
3. A complete pressure package requires one latest value for every `C/L/R/T/B` position. In array mode, values are accumulated separately by sensor/package ID and attached to the configured `array_layout` cell.

| Condition | Display result |
| --- | --- |
| No configured channels | Timeline is cleared, map is cleared, status is `Configure channels first`. |
| No valid display specifications | Timeline is cleared, map is cleared, status is `No integrated channels available`. |
| No raw buffer/sweeps/timestamps | Timeline is cleared, map is cleared, status is `Waiting for raw ADC data`. |
| A package is incomplete | It is not made into a pressure package. If no complete package remains, the map displays `No Data`. |
| PZR timeline selected but neither RS1 nor RS2 is selected | Map can still update from PZT; timeline status requests a Rosette selection. |
| PZR timeline selected but the selected Rosette data is unavailable | Map can still update from PZT; timeline status reports no selected Rosette data. |
| Settings inner tab selected | Live redraw is paused; package-gain controls are refreshed. |
| Map generator/array interpolation raises an error | The map clears or falls back as described below, and the error is logged rather than crashing the GUI. |

## Signal Integration Calculation

For each selected channel specification, sample positions are flattened from the copied ADC sweeps. The per-sample timestamp is the sweep timestamp plus `sample_index * average_adc_sample_time`.

### 1. Optional baseline subtraction and ADC conversion

When **Use Time Series median baseline** is enabled, the stored per-spec Time Series baseline is subtracted in ADC-count space before voltage conversion. If a baseline is missing, the app tries to capture it from the current Time Series path.

For an `N`-bit ADC count `d` and active voltage reference `Vref`:

```text
voltage = d / (2^N - 1) * Vref
```

This conversion deliberately ignores Time Series display units; the derived pipeline operates on volts.

### 2. DC removal

With an HPF cutoff of 0, no DC-removal filter is applied. Otherwise the code estimates the channel's rate from the median positive timestamp interval. Provided the cutoff is below Nyquist and SciPy filtering is available, it applies the application's first-order high-pass filter to the complete processing snapshot.

If a rate cannot be estimated, the cutoff is at/above Nyquist, SciPy is unavailable, or filtering fails, it uses the safe fallback:

```text
filtered = voltage - mean(voltage over the copied snapshot)
```

The reason is logged once as a Signal Integration HPF fallback. Filtering occurs before integration and is display-only; it does not modify captured raw data.

### 3. Rectangular moving-sum integration

Let `f[n]` be the DC-removed voltage and `W` the configured integration window in samples (default 30). The displayed derived signal is a trailing rectangular sum:

```text
I[n] = sum(f[k] for k = max(0, n-W+1) through n)
```

The implementation uses a cumulative sum, so it is a sum in `V samples`, not a time-scaled physical integral. A window of one returns the filtered samples unchanged. The earlier copied history makes the first visible result include any appropriate pre-window samples.

### 4. Polarity and plotting

After integration, reverse-polarity sensor configurations multiply the result by -1. The latest point from each fully processed trace is the scalar forwarded to the shear/pressure calculation. Only after that is the timeline trimmed to the requested visible duration and decimated for drawing. Decimation therefore never changes the map's latest scalar value.

For PZT timeline mode, the plot can show individual/repeated/averaged position traces, or a one-total-force trace per package when multiple array packages are selected. For PZR timeline mode it draws the selected held RS1/RS2 channels in ohms with a fixed user Y range; those Rosette traces are not pressure-map inputs.

## Calibration, Shear, and Normal Force

### 1. Package calibration

Before shear detection, every latest integrated position `I_p` is independently calibrated:

```text
thresholded_p = 0                         if abs(I_p) < shear_noise_threshold
                I_p                       otherwise
calibrated_p = thresholded_p * package_gain[p]
```

The noise threshold is applied **before** the gain. Gains default to 1 and may be overridden for each currently selected package and each of C/L/R/T/B.

### 2. Shear extraction

Shear is the equal-and-opposite part of an outer pair. L/R contributes only when both values are non-zero and have opposite signs; T/B follows the same rule:

```text
b_lr = sign(R) * min(abs(L), abs(R))      # otherwise 0
b_tb = sign(T) * min(abs(T), abs(B))      # otherwise 0
shear_magnitude = hypot(b_lr, b_tb)
shear_angle_deg = degrees(atan2(b_tb, b_lr))
```

0 degrees points right; +90 degrees points up. The estimated lateral strain is:

```text
strain[C] = 0
strain[L] = -b_lr;  strain[R] = +b_lr
strain[T] = +b_tb;  strain[B] = -b_tb
residual[p] = calibrated[p] - strain[p]
```

Thus pure same-sign compression, a single active outer sensor, or an all-zero package has no shear arrow. In an unequal opposite-sign pair, only the common opposing magnitude becomes shear; the unbalanced remainder stays in the normal residual.

### 3. Normal-force classification and coordinates

The centre residual decides force type: positive is compression and negative is tension. If it is zero, the type is inferred from the majority sign of outer residuals, breaking a count tie by total signed magnitude. All-zero residuals are `none`.

To create a polarity-consistent normalized set, the code subtracts the minimum outer residual for compression or the maximum outer residual for tension:

```text
offset = min(L, R, T, B)    # compression
offset = max(L, R, T, B)    # tension
normalized[p] = residual[p] - offset
baseline_force = 5 * offset
total_force = sum(normalized[p]) + baseline_force
```

Algebraically, `total_force` equals the sum of residuals; the normalization exists to make pressure-surface values and the centroid consistent with the selected force polarity.

The reported normal-force position uses the centre plus the pair on that axis, clamped to `[-sensor_spacing, +sensor_spacing]`:

```text
x_mm = spacing * (normalized[R] - normalized[L])
       / (normalized[R] + normalized[L] + normalized[C])
y_mm = spacing * (normalized[T] - normalized[B])
       / (normalized[T] + normalized[B] + normalized[C])
```

A denominator with magnitude at most `1e-12` yields coordinate 0. The X calculation intentionally does not include T/B, and Y does not include L/R.

## Single-Package Pressure Surface

The map is a physical, piecewise-linear field—not a Gaussian blur. The configured circular footprint has diameter `D`, resolution `R`, and margin `M` cells per side:

```text
cell_size = D / (R - 1)
grid_side = R + 2*M
total_extent = D + 2*M*cell_size
```

The grid spans `[-total_extent/2, +total_extent/2]` in both axes. Only pixels inside the circular mask are assigned quadrant values; everything else starts at zero.

### Active quadrants and base plane

The four quadrants are TR `(C,R,T)`, TL `(C,L,T)`, BL `(C,L,B)`, and BR `(C,R,B)`. A quadrant is active only if it has at least one non-zero participant and every non-zero participant has the same sign. Zeros do not conflict with a quadrant's sign.

For an active quadrant, the base plane `z = a*x + b*y + c` goes through C, that quadrant's horizontal outer sensor, and vertical outer sensor. For example, in the top-right quadrant:

```text
a = (R - C) / spacing
b = (T - C) / spacing
c = C
```

The sign-adjusted equivalent is used in the other three quadrants. Values are clamped to the quadrant sign: non-negative in positive quadrants and non-positive in negative quadrants.

### Pressure-point modes

Each active quadrant selects one of these programmed rendering modes:

| Input pattern | Surface behaviour |
| --- | --- |
| No interior pressure point | Base three-sensor plane. |
| C and exactly one relevant outer sensor are materially non-zero | A **single-axis peaked** lobe from C toward that sensor. Its width is narrow at the edges and wider near the inferred peak. |
| C is approximately zero and exactly one relevant outer sensor is materially non-zero | Base plane plus radial decay away from that active outer sensor; prevents an artificial broad plateau. |
| An inferred peak has positive local X and Y within the quadrant | A **peaked** four-triangle fan: inner triangles connect C/horizontal/peak and C/vertical/peak; outer triangles connect each outer sensor through a zero-valued outer corner to the peak. |
| No active quadrant | All-zero pressure grid. |

The candidate peak location uses magnitude. With **Show negative** off, magnitude is `max(value, 0)`; with it on, magnitude is `abs(value)`:

```text
peak_x = horizontal_sign * spacing * |H| / (|H| + |C|)
peak_y = vertical_sign   * spacing * |V| / (|V| + |C|)
```

Here the bars mean the active magnitude policy above, not always absolute value. A peak requires both local axes to be greater than the geometry epsilon.

Its height is an inverse-square weighted estimate from C/H/V. For each sensor at distance `d` from the peak:

```text
sensor_estimate = sensor_value * (1 + decay_rate * d / decay_reference_distance)
weight = 1 / max(geometry_epsilon, d)^2
peak_height = sum(sensor_estimate * weight) / sum(weight)
```

The `decay_rate` and `decay_reference_distance` settings therefore shape inferred point height rather than applying a conventional image blur. For cells beyond an outer sensor, the value fades linearly to zero at the grid margin. The single-outer case also receives radial side decay.

**Show negative** affects peak-location magnitudes. It does not turn a negative same-sign quadrant into an empty one: active negative quadrants retain non-positive values before image rendering. The widget displays `abs(pressure_grid)`, so tension can be visible with the selected palette. Array gap values have an additional policy described below.

## Array Surface and Gap Interpolation

Every complete selected array package first gets the single-package calculation above. If there are two or more complete packages, all have a grid position, and the layout contains at least one direct horizontal or vertical neighbour, the app displays one combined array image. Otherwise it displays separate package images positioned in their grid cells.

Package centres are determined only from the configured row/column geometry:

```text
centre_spacing = circle_diameter + package_gap
centre_x = (column - mean_minmax_column) * centre_spacing
centre_y = (mean_minmax_row - row) * centre_spacing
```

Each local grid is pasted into the world grid. If fields overlap, the value with larger absolute magnitude wins.

Only direct neighbours receive a bridge: left/right uses facing `R`/`L`; upper/lower uses facing `B`/`T`. Diagonal packages do not create a bridge. Within the line between those facing sensor positions, the app computes axial values as follows:

1. If both facing values and both centres are zero, it writes no gap pressure.
2. If either package's centre is stronger than both facing values and wins over the other centre, interpolate monotonically from the first facing value to the second. This prevents a false inter-package peak caused by centre-dominant contact.
3. If the facing values have opposite signs, interpolate monotonically through zero.
4. Otherwise make a piecewise-linear peak. The peak moves toward the stronger facing sensor:

   ```text
   peak_fraction = abs(second_facing) / (abs(first_facing) + abs(second_facing))
   dominant = first_facing if abs(first) >= abs(second) else second_facing
   peak_value = dominant + sign(dominant) * abs(first_facing - second_facing) * gap_contrast_gain
   ```

5. Multiply the axial result by the lateral triangular fade:

   ```text
   fade = clamp(1 - abs(lateral - bridge_centre) / fade_half_width, 0, 1)
   fade_half_width = max(package_extent/4,
                         circle_diameter * gap_fade_width_fraction)
   ```

If Show negative is off, negative **gap** values are clamped to zero; if on, they remain. As with package grids, the strongest absolute candidate replaces the current world-grid value.

## Rendering, Readout, and Shear Arrow

The pressure widget uses a dark, axis-free, aspect-locked PyQtGraph view. It uploads `abs(pressure_grid).T` so visual brightness represents magnitude regardless of compression/tension sign. The following are rendering-only changes; they do not recompute calibrated signals, normal force, or the pressure field:

- **Boundary** adds a dotted circle, square, or nothing around each package.
- **Show marker** draws an `x` for every peaked quadrant's inferred pressure point.
- **Mirror** flips image data, X coordinates of sensor/peak markers, package centres, and the shear-arrow X direction.
- **Colour scale** chooses Thermal, Grayscale, Viridis, or Magma. Arrow colour becomes white for red-heavy Thermal/Magma and red for Grayscale/Viridis.

With a positive fixed Max Intensity, image levels are `(noise_floor, max_intensity)`. With Max Intensity set to zero, the widget uses the current maximum absolute grid value and scales it from 1x to 2x according to how many residual sensors are active. This prevents auto-level saturation from a single active sensor.

The legend is linear. When Unit is blank, its limits are the live shear noise threshold and fixed Max Intensity, labeled `V`; custom Minimum/Maximum values become active only when Unit is non-blank. It shows the upper endpoint, the configured number of evenly spaced ranges, and the lower endpoint.

For each package with detected shear and magnitude strictly above the arrow threshold:

```text
arrow_length = min(shear_magnitude * arrow_gain,
                   package_radius * arrow_max_length_fraction)
tip = (arrow_length*cos(angle), arrow_length*sin(angle))
```

The shaft has either the selected base width or an additional bounded width of up to 2 pixels based on `min(1, magnitude / 2)`. The shaft ends at the arrowhead base; the triangular head reaches the calculated tip. Zero/no-shear and threshold-equal shear hide the arrow. In a multi-package or combined-array display, each valid package has its own arrow at its world-space centre.

The readout shows single-package force type, signed normal total, calculated normal position, active-quadrant count, and shear magnitude/angle. In a multi-package display it instead lists package IDs and the sum of their normal totals.

## Display Scenarios

| Scenario | Image and overlays |
| --- | --- |
| One complete package | One local physical surface, its markers/boundary/peak markers, and its shear arrow if detected. |
| Several complete packages without adjacent grid cells | One local surface per package at its configured/fallback position; no combined image. |
| Several complete packages with at least one direct adjacent pair | One combined array surface with every package's boundary, sensor markers, peak markers, label, and arrow retained. |
| Adjacent packages with facing load and no centre dominance | A lateral-faded gap bridge, potentially with an extrapolated peak controlled by Gap Contrast. |
| Adjacent packages with centre dominance | A monotonic bridge; no invented central gap peak. |
| Opposite-sign facing values | A monotonic bridge through zero; negative values are subsequently hidden only in the gap when Show negative is off. |
| Same-sign negative package quadrant | A negative local pressure field can be generated and is rendered by magnitude. |
| No active same-sign quadrant | Empty (zero) local grid. |
| Arrow threshold not exceeded/no opposite-sign pair | Pressure map remains; arrow is hidden. |
| Mirror enabled | All visible horizontal geometry is flipped without changing the calculated values. |

## Persistence and Verification

The last-used payload is stored under the user's `.adc_streamer/shear/` directory and can also be explicitly saved/loaded as JSON. It includes integration/timeline settings, processing threshold and package gains, arrow settings, pressure geometry, array bridge controls, palette/legend settings, and display toggles.

Automated coverage is concentrated in:

- `tests/test_signal_integration_panel.py` for the conversion/filter/integration pipeline, baselines, polarity, package routing, settings persistence, tab-refresh rules, and array plumbing.
- `tests/test_shear_detector.py` and `tests/test_normal_force_calculator.py` for shear extraction, residuals, normal classification, totals, and coordinates.
- `tests/test_pressure_map_generator.py` for active quadrant, plane, peak, decay, sign, and marker behaviours.
- `tests/test_pressure_map_array_generator.py` for neighbour detection, gap peak/fade/contrast, centre dominance, signs, and diagonal exclusion.
- `tests/test_pressure_map_widget.py` for image levels, palette/mirror/boundary/marker/arrow rendering, package layout, and combined-array display.

## Out of Scope

- Offline capture analysis and file browsing.
- Editing the sensor library or array configuration.
- Heatmap-tab RMS/Gaussian/point-tracking calculations.
