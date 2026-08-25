# Heatmap Tab Specification

Owner: Host application GUI/heatmap-processing stack  
Status: Implemented  
Date: 2026-07-30

## Scope and Terminology

The **Heatmap** tab is a live visualization of a five-position sensor package:

| Position | Logical coordinate |
| --- | --- |
| `T` (top) | `(0, -1)` |
| `B` (bottom) | `(0, +1)` |
| `R` (right) | `(+1, 0)` |
| `L` (left) | `(-1, 0)` |
| `C` (centre) | `(0, 0)` |

Each package is rendered as a bounded, normalized 160 x 160 Gaussian intensity image. The image represents an estimated centre of pressure (CoP), not an interpolation of five independent peaks.

The tab has two processing modes:

- **PZT**: derives an RMS magnitude from a rolling sample window.
- **PZR / 555 analyzer**: derives a magnitude from the absolute percentage change from a baseline.

### Important: shear arrow ownership

The Heatmap tab does **not** calculate or draw a shear arrow. Its `update_heatmap_display()` call only supplies heatmap package results to the Heatmap display. The red/white vector arrow is part of the separate **Pressure Map** tab (`gui/pressure_map_widget.py`), which uses a different, signal-integration pipeline. The full arrow calculation is included in [Shear-arrow calculation](#shear-arrow-calculation-pressure-map-tab) to document the related display without incorrectly attributing it to this tab.

## User Interface and Refresh Rules

- The tab contains `Display` and `Settings` inner tabs.
- The app requests a refresh only while the outer Heatmap tab is selected. ADC arrivals are debounced to at most `HEATMAP_FPS = 30` redraws per second.
- Entering the tab refreshes mode-specific controls and immediately attempts a draw.
- A successful update clears the status label. A missing/invalid result shows `Heatmap requires 5 channels (currently N selected)`; the wording is also used when no usable raw buffer, timing value, package group, or valid PZR channel grouping is available.
- The tab reads the shared live ring buffer; it does not read archived files or generate simulated data.

The settings tab exposes signal conditioning (PZT only), PZR controls, global and per-package/per-position calibration, blob geometry, image palette, physical layout geometry, overlays, mirror, and point tracking. Last-used PZT and PZR settings are saved separately under the user's `.adc_streamer/heatmap/` directory. Explicit JSON save/load is also supported.

## Common Input and Package Resolution

1. The selected channel layout is resolved into packages of five labelled positions (`T`, `B`, `R`, `L`, `C`). `channel_sensor_map` maps the configured acquisition channels to those labels.
2. In an array/multiplexer configuration, the preferred route uses `get_display_channel_specs()`: each spec supplies the exact sample indices and package/sensor ID. This preserves the physical layout even when channel numbers repeat across multiplexers.
3. If display specs are unavailable, the app falls back to `get_sensor_package_groups(5)`, using each group's selected channels and acquisition positions.
4. At most `MAX_SENSOR_PACKAGES` (the configured array row count times column count) are processed.
5. If **Use Time Series median baseline** is enabled and a saved Time Series baseline exists, that baseline is subtracted from samples before the PZT RMS calculation or used as the PZR baseline. If needed, the app first attempts to capture a current Time Series baseline.

The processing result for each package is:

`(heatmap[160,160], cop_x, cop_y, intensity, confidence, [T, B, R, L, C])`.

## PZT Calculation

### 1. Select a rolling window

The PZT path copies the newest `rms_window_ms` of the raw ring buffer (default 20 ms) while holding the buffer lock. It derives the number of sweeps as:

```text
sweep_duration = samples_per_sweep * latest_arduino_sample_time_us / 1,000,000
window_sweeps = ceil((rms_window_ms / 1,000) / sweep_duration)
```

The count is clamped to at least one and to the number of available sweeps. The code correctly handles both a partially filled and wrapped ring buffer. A non-positive sample-time measurement, no samples, or no configured channels produces no heatmap result.

For each labelled position, all matching samples in the window are flattened into one channel series. The effective sample rate is based on the firmware sample time and adjusted for repeated acquisition positions.

### 2. Remove DC and calculate RMS

The user selects one of these mutually exclusive modes:

- **Bias (2s)**: each package/position accumulates its raw mean from startup until the latest timestamp reaches 2 seconds. The running bias is then frozen. For samples `x`, `u = x - bias` and `rms = sqrt(mean(u²))`.
- **High-pass**: a first-order high-pass filter is applied sample-by-sample:

  ```text
  dt = 1 / sample_rate
  RC = 1 / (2π * cutoff_hz)
  a = RC / (RC + dt)
  y[n] = a * (y[n-1] + x[n] - x[n-1])
  rms = sqrt(mean(y²))
  ```

  If either the rate or cutoff is non-positive, the fallback is `x - mean(x)` before RMS.

When **Remove negatives** is enabled, the conditioned signal is half-wave rectified (`max(value, 0)`) before the RMS calculation. It therefore changes the magnitude calculation, not only the image display.

### 3. Calibrate, threshold, and smooth each position

For each RMS result `r` the app calculates:

```text
v = max(0, r - fixed_noise_floor) * base_calibration_gain * package_position_gain
threshold = global_noise_threshold + package_position_threshold
w = v if v >= threshold else 0
```

The default fixed noise floors and base gains are per-position arrays. The package-position gain and threshold come from the dynamically built calibration controls for the selected sensor ID. If calibration is missing, gain is 1 and its extra threshold is 0.

`w` is then temporally smoothed per package/position:

```text
smoothed = alpha * w + (1 - alpha) * previous_smoothed
```

On the first update, or when `alpha` is 1, the current value becomes the state. With `alpha` 0, the code returns the current values without changing its stored EMA state.

### 4. Calculate CoP, intensity, confidence, and blob size

Let the non-negative five-position weights be `w_i`, and `S = sum(w_i)`.

```text
raw_cop_x = sum(x_i * w_i) / (S + 1e-6)
raw_cop_y = sum(y_i * w_i) / (S + 1e-6)
raw_intensity = S
```

CoP X, CoP Y, and intensity each use the same exponential smoother:

```text
state = smooth_alpha * raw + (1 - smooth_alpha) * previous_state
```

The confidence is informational; it does not scale the PZT image amplitude:

```text
q_intensity = min(1, S / confidence_intensity_ref)
concentration = max(w_i) / S
confidence = q_intensity * concentration
```

Diffuse load expands the blob. The common spread multiplier is:

```text
sigma_scale = 1 + (1 - concentration) * sigma_spread_factor
```

With ellipse mode enabled, the R/L versus T/B balance additionally changes the two axes. If `x_ratio = (R+L)/(R+L+T+B)` and `y_ratio = (T+B)/(R+L+T+B)`, then:

```text
sigma_scale_x = 1 + axis_sigma_factor * (2*x_ratio - 1)
sigma_scale_y = 1 + axis_sigma_factor * (2*y_ratio - 1)
```

If no outer weight exists, both factors are 1. With ellipse mode off, one circular sigma is used and these axis factors are ignored.

## PZR / 555 Calculation

The PZR path processes only sweeps not processed on the preceding update. For every unique configured channel it averages repeated positions within each new sweep. It requires a positive multiple of five unique channels and a five-entry channel map; otherwise it returns no result.

For each package:

1. On the first usable row, initialize the per-position baseline and previous values from that row. A configured Time Series baseline overrides the corresponding initialized baseline.
2. For every new row, calculate the baseline-relative percentage and its magnitude:

   ```text
   delta_percent_i = 100 * (current_i - baseline_i) / max(abs(baseline_i), 1e-9)
   magnitude_i = abs(delta_percent_i) * package_position_gain_i
   threshold_i = global_noise_threshold + package_position_threshold_i
   w_row_i = magnitude_i if magnitude_i >= threshold_i else 0
   ```

3. Average `w_row_i` across all newly received rows, then multiply by the base per-position calibration gain. This produces `w_i`; intensity and CoP are the same weighted sums as the PZT path.
4. Smooth CoP and intensity using `cop_smooth_alpha`.
5. Calculate confidence from smoothed intensity and concentration:

   ```text
   q_intensity = clamp((smoothed_intensity - intensity_min)
                       / (intensity_max - intensity_min), 0, 1)
   concentration = max(w_i) / (sum(w_i) + 1e-6)
   confidence = q_intensity * concentration
   ```

   If the configured maximum is not above the minimum, `q_intensity` is 1 only when the smoothed intensity reaches the minimum.

6. Build the Gaussian below, but multiply amplitude by confidence. When ellipse mode is enabled, the stronger outer axis can be expanded by `axis_adapt_strength`; circular mode disables that adaptation.
7. Apply a second image EMA using `map_smooth_alpha`, then clamp to `[0, 1]`.

The PZR-only **Zero Signals** action recalculates the common plot baselines from current live signals. It affects subsequent relative-change values; it does not retroactively change an already rendered frame.

## Heatmap Image Generation and Rendering

### Gaussian generation

The app precomputes a 160 by 160 coordinate grid spanning `[-1.5, +1.5]` in each direction. For smoothed CoP `(c_x, c_y)`, final sigmas `(s_x, s_y)`, and amplitude `A`, every pixel is:

```text
G(x,y) = exp(-((x-c_x)² / (2*s_x²) + (y-c_y)² / (2*s_y²)))
A = smoothed_intensity * intensity_scale
heatmap = clamp(A * G, 0, 1)
```

For PZR only, `A` is additionally multiplied by confidence. `blob_sigma_x` and `blob_sigma_y` are the configured base sigmas; circular mode replaces both with their mean. The 1.5 image extent is intentionally larger than the normalized sensor circle (radius 1), allowing a blob near an edge to fade beyond the boundary rather than be abruptly clipped.

### Per-package display

The PyQtGraph images use row-major data with fixed levels `(0, 1)`, so palette changes never rescale the numeric image. Available palettes are Thermal, Grayscale, Viridis, and Magma. The plot aspect ratio is locked, its axes are hidden, it has a black background, and its Y axis is inverted for display.

In non-array/channel-layout mode, packages occupy a compact two-column arrangement. In array mode, cards use the configured `array_layout.cells` rows and columns. Physical spacing is converted into the plot's display units:

```text
cell_spacing = sensor_diameter + gap_mm
```

The selected sensor IDs may optionally be drawn at their package centres and each package may show a circular boundary. **Mirror** flips both array column placement and each heatmap image left-to-right. It is a presentation transform; it does not alter sensor weights or CoP calculation.

### Array point tracking scenarios

Point Tracking is available only in array-selection mode. It replaces all individual package images with one strongest-pressure Gaussian at a physical array location. It uses the five final package weights, not raw samples.

1. A position is active when its weight is at least 25% of that package's maximum positive weight.
2. For two horizontally adjacent packages, an inter-package candidate exists only when the left package's `R` and right package's `L` are each positive and all other weights in their own package total at most 25% of that facing edge. Its centre is the facing sensor-edge positions weighted by their facing values.
3. For vertical neighbours, the analogous `B` (upper) / `T` (lower) test is used.
4. Any package participating in an eligible pair is excluded from single-package candidates. This prevents a clear between-sensor contact from being replaced by a stronger-looking local point.
5. A single-package candidate has score `sum(active_weights)`. Its local position is the weighted mean of the logical five-position coordinates, scaled by half the physical sensor diameter.
6. The app selects the highest score. Ties prefer a pair candidate, then the larger intensity. It renders exactly one centred Gaussian with that target's intensity.
7. If there is no eligible pair or active single-package candidate, the tracking renderer declines and the display falls back to the normal per-package images.

The configured gap changes package centre spacing. It does not become an inferred pressure field: the point tracker chooses one geometrically derived position in the gap only when the facing-edge rules above are satisfied.

## Display Scenarios and Outcomes

| Scenario | Result |
| --- | --- |
| PZT, valid recent buffer and one or more valid five-position packages | One Gaussian heatmap per package, based on RMS magnitudes. |
| PZR, valid new sweeps and a valid multiple of five unique channels | One confidence-weighted, image-smoothed Gaussian per package, based on percentage displacement from baseline. |
| Array mode, point tracking off | Individual package images positioned according to the configured array cells. |
| Array mode, point tracking on, valid strongest target | One image only, placed on the strongest sensor or qualifying horizontal/vertical pair. |
| Array mode, point tracking on, no active target | Normal per-package display. |
| Channel layout, point tracking checked | Normal per-package display; tracking is deliberately disabled outside array mode. |
| Circle and/or labels enabled | Boundary circles and selected package IDs overlay the rendered image(s). |
| Mirror enabled | Package columns and every image are horizontally flipped; calculation stays unchanged. |
| No raw samples, no timing measurement, invalid mapping/group, or invalid PZR grouping | No new useful package output and the five-channel status warning is shown. |
| Below calibration threshold | The affected position weight is zero; if all positions are zero, the image amplitude is zero. |
| No new PZR sweeps | The PZR processor returns no fresh result rather than reprocessing the same sweeps. |

## Shear-arrow Calculation (Pressure Map Tab)

This is the arrow shown by the separate Pressure Map display, not the Heatmap tab. It starts from that tab's calibrated latest integrated values `{C, L, R, T, B}`. Each calibrated value is first zeroed when its magnitude is below the shear noise threshold and then multiplied by the package/position shear gain.

The detector contributes horizontal shear only if L and R are both non-zero and have opposite signs, and vertical shear only if T and B meet the same condition:

```text
b_lr = sign(R) * min(abs(L), abs(R))    # otherwise 0
b_tb = sign(T) * min(abs(T), abs(B))    # otherwise 0
magnitude = hypot(b_lr, b_tb)
angle_deg = degrees(atan2(b_tb, b_lr))  # 0° right, +90° up
```

It removes the equal-and-opposite shear component from the outer positions before normal-force calculation:

```text
strain:   C=0, L=-b_lr, R=+b_lr, T=+b_tb, B=-b_tb
residual: calibrated - strain
```

Thus same-sign compression, a single outer signal, and a zero pair yield no arrow. An unequal opposite-sign pair uses only the smaller opposing magnitude as shear; the excess remains in the residual normal signal.

The Pressure Map widget hides the arrow when no opposite-sign pair exists or `magnitude <= arrow_min_threshold`. Otherwise it draws it from the package centre with:

```text
length = min(magnitude * arrow_gain,
             package_circle_radius * arrow_max_length_fraction)
tip = (length*cos(angle), length*sin(angle))
```

The shaft width is either the configured base width or a bounded magnitude-scaled width. A mirrored Pressure Map negates the rendered X tip and recomputes the display angle, so the visual vector matches the mirrored map. In array mode, every valid package receives its own arrow at that package's centre. Palette-dependent styling selects white on red-heavy Thermal/Magma maps and red on the neutral palettes; it does not affect the vector calculation.

## Verification Coverage

`tests/test_heatmap_thresholds.py` covers PZT/PZR thresholds, coordinate orientation, circular versus elliptical blobs, baseline handling, array geometry, mirroring, and point-tracking sensor/pair cases. `tests/test_shear_detector.py` and `tests/test_shear_visualization_widget.py` cover opposite-sign extraction, zero-shear behaviour, direction, geometry, length clipping, and visibility of the Pressure Map shear arrow.

## Out of Scope

- Pressure Map's integrated timeline, normal-force calculation, and combined inter-package pressure surface (other than the shear-arrow description above).
- Force-calibration table workflows.
- Offline CSV/JSON browsing and analysis.
