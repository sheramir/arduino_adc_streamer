# data_processing (Legacy)

Archived signal-processing implementations for the older heatmap and shear/center-of-pressure pipelines. These modules compute heatmap intensity, center-of-pressure (CoP), and shear vectors from raw ADC sweeps for the piezo (PZT) and 555-resistance (PZR) sensor packages. They are kept for reference and regression testing; the active application uses promoted copies elsewhere in the repo (see root `README.md` and `Legacy/README.md`).

## Files

### heatmap_555_processor.py

Mixin implementing the 555-resistance (PZR, 4-channel-per-sensor) displacement heatmap pipeline: extracts new sweep data, maps channels to T/B/R/L/C sensor labels, computes relative deltas against a baseline, applies thresholds/gains, derives center of pressure and intensity, and renders a smoothed Gaussian heatmap per sensor package.

- `Heatmap555ProcessorMixin._threshold_label_order()` — returns the fixed sensor label order `["T", "B", "R", "L", "C"]`.
- `Heatmap555ProcessorMixin._get_package_sensor_id(package_index)` — resolves the sensor ID string for a package index, using array-mode selection if active.
- `Heatmap555ProcessorMixin._build_r555_channel_value_array(label_order, values, default)` — builds a per-sensor-label numpy array from a flat values list, filling missing entries with a default.
- `Heatmap555ProcessorMixin.reset_555_heatmap_state()` — clears per-package PZR state and the last-processed-sweep counter.
- `Heatmap555ProcessorMixin._get_r555_package_state(package_index, sensor_count)` — lazily creates/returns the per-package state dict (previous values, baseline, smoothed CoP/intensity/heatmap).
- `Heatmap555ProcessorMixin._extract_new_sweeps_since(last_processed_sweep_count)` — pulls only the newly written sweep rows from the shared ring buffer since the last processed count.
- `Heatmap555ProcessorMixin._build_channel_matrix(sweeps_array, channels, repeat_count)` — averages repeats per channel and returns a sweep x channel matrix plus the unique channel list.
- `Heatmap555ProcessorMixin.process_555_displacement_heatmap(settings)` — full per-call pipeline: extract sweeps, map channels to sensors, compute deltas/weights/CoP/intensity/confidence, and update the smoothed heatmap for every sensor package.

### heatmap_piezo_processor.py

Mixin implementing the piezoelectric (PZT, 5-channel) heatmap pipeline: RMS-based channel intensity extraction with bias or high-pass DC removal, CoP/intensity smoothing, confidence scoring, and Gaussian blob rendering with axis-adaptive sigma.

- `PiezoHeatmapProcessorMixin._threshold_label_order()` — returns the fixed sensor label order `["T", "B", "R", "L", "C"]`.
- `PiezoHeatmapProcessorMixin._build_piezo_channel_value_array(values, default, size)` — builds a fixed-size list from supplied values, padding with a default.
- `PiezoHeatmapProcessorMixin.calculate_cop_and_intensity(sensor_values, settings, package_index=0)` — computes and EMA-smooths center of pressure (x, y) and total intensity from per-sensor weights.
- `PiezoHeatmapProcessorMixin.generate_heatmap(cop_x, cop_y, intensity, settings, package_index=0)` — renders a 2D Gaussian blob centered at the CoP into the package's heatmap buffer.
- `PiezoHeatmapProcessorMixin.process_sensor_data_for_heatmap(sensor_values, settings, package_index=0)` — full pipeline: CoP/intensity, confidence/concentration, axis-adaptive sigma scaling, then heatmap generation.
- `PiezoHeatmapProcessorMixin.calculate_confidence(weights, intensity, settings)` — derives a confidence score and concentration ratio from sensor weights and total intensity.
- `PiezoHeatmapProcessorMixin._extract_heatmap_window_data(window_ms)` — extracts the most recent sweep window (by elapsed time) from the ring buffer along with timestamps and average sample time.
- `PiezoHeatmapProcessorMixin.compute_channel_intensities(settings)` — converts a sweep window into per-sensor RMS magnitudes per package, applying baseline subtraction, calibration gains, and thresholds.

### heatmap_processor.py

Coordinator mixin combining the piezo and 555 heatmap mixins and initializing shared heatmap processing state (coordinate grids, buffers, signal processors) for the main GUI class.

- `HeatmapProcessorMixin` (class) — combines `PiezoHeatmapProcessorMixin` and `Heatmap555ProcessorMixin`.
- `HeatmapProcessorMixin.init_heatmap_processing_state()` — allocates smoothed CoP/intensity arrays, heatmap image buffers, coordinate grids, per-package `HeatmapSignalProcessor` instances, and resets 555 state.

### heatmap_signal_processing.py

Per-channel signal conditioning used by the piezo heatmap pipeline: bias-based or high-pass DC removal, RMS computation, and EMA smoothing with thresholding.

- `HeatmapSignalProcessor.__init__(channel_count, bias_duration_sec, hpf_cutoff_hz)` — stores configuration and resets internal state.
- `HeatmapSignalProcessor.reset()` — clears bias accumulators, high-pass filter state, and EMA state.
- `HeatmapSignalProcessor.update_channel_count(channel_count)` — resets internal arrays if the channel count changes.
- `HeatmapSignalProcessor.set_hpf_cutoff(cutoff_hz)` — updates the high-pass filter cutoff frequency.
- `HeatmapSignalProcessor._update_bias(channel_samples, window_end_time_sec)` — accumulates running mean per channel until the bias calibration duration elapses.
- `HeatmapSignalProcessor._high_pass_filter(samples, sample_rate_hz, idx)` — applies a single-pole RC high-pass filter to one channel's samples, retaining filter state across calls.
- `HeatmapSignalProcessor.compute_rms(channel_samples, dc_removal_mode, sample_rate_hz, window_end_time_sec)` — computes per-channel RMS after either bias subtraction or high-pass filtering.
- `HeatmapSignalProcessor.smooth_and_threshold(values, alpha, threshold)` — applies EMA smoothing and zeroes values below a threshold.

### shear_cop_processor.py

Stateless helper functions plus a stateful `ShearCoPProcessor` class implementing signed shear/center-of-pressure extraction from opposite-sign sensor pairs (R/L, T/B) for the 5-channel piezo package, including confidence scoring based on temporal stability.

- `ShearCoPResult` (dataclass) — holds conditioned/integrated/signed/residual sensor values, CoP, shear vector/magnitude/angle, confidence, and total weight.
- `condition_samples(samples, baseline_value, smoothing_alpha)` — subtracts a baseline and applies an optional EMA smoother to raw samples.
- `integrate_signed_signal(samples, sample_rate_hz)` — integrates a signed signal over the current window using the sample rate.
- `apply_signed_calibration(value, baseline, gain, deadband)` — applies a deadband and signed gain (gain may be negative to flip polarity) while preserving sign.
- `extract_shear_pair(positive_sensor_value, negative_sensor_value)` — extracts a signed shear value from an opposite-sign sensor pair and returns the residuals.
- `shift_residuals_to_positive(values)` — shifts a dict of values so the minimum is non-negative, for use as CoP weights.
- `estimate_cop(values)` — computes a weighted center of pressure from sensor values using fixed sensor coordinates.
- `angle_from_shear_vector(shear_x, shear_y)` — converts a shear vector to an angle in degrees (0 deg = +Y, +90 deg = +X).
- `generate_gaussian_blob(x_grid, y_grid, center_x, center_y, sigma_x, sigma_y, amplitude)` — renders a 2D Gaussian blob on a coordinate grid.
- `ShearCoPProcessor.__init__(sensor_order=None)` — sets the sensor order and resets state.
- `ShearCoPProcessor.reset()` — clears baseline trackers and shear/magnitude history.
- `ShearCoPProcessor._update_baseline(sensor_name, samples, baseline_alpha)` — EMA-updates the tracked baseline for one sensor.
- `ShearCoPProcessor._compute_temporal_stability(shear_x, shear_y, magnitude)` — scores directional alignment and magnitude stability of the shear vector over recent history.
- `ShearCoPProcessor._compute_confidence(signed_magnitudes, shear_x, shear_y, shear_magnitude, total_weight, signal_strength_ref)` — combines signal strength, weight quality, dominance, and temporal stability into a single confidence score.
- `ShearCoPProcessor.process(sensor_samples, sample_rate_hz, settings)` — full per-call pipeline: condition/integrate/calibrate each sensor, extract R/L and T/B shear pairs, compute CoP, shear vector, and confidence; returns a `ShearCoPResult`.
- `run_shear_debug_cases()` — generates a set of synthetic test cases exercising `extract_shear_pair` and `ShearCoPProcessor.process` for manual debugging.

### shear_processor.py

Mixin coordinating live extraction of 5-channel piezo data into shear/CoP visualization output, using `ShearCoPProcessor` and `shear_cop_processor` helpers per sensor package.

- `ShearProcessorMixin.init_shear_processing_state()` — allocates a `ShearCoPProcessor` and heatmap buffer per sensor package.
- `ShearProcessorMixin.reset_shear_processing_state()` — resets all shear processors and clears heatmap buffers.
- `ShearProcessorMixin._extract_shear_sensor_samples(settings)` — pulls a recent sweep window and splits it into per-sensor sample streams per package using the channel-to-sensor map.
- `ShearProcessorMixin.compute_shear_visualization(settings)` — runs `ShearCoPProcessor.process` per package, builds a clipped Gaussian blob for display, and returns heatmap buffer + result pairs.

### __init__.py

Empty package marker file (no content).
