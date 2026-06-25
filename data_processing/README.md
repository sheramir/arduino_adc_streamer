# Data Processing

This folder implements the data pipeline that sits between the serial/binary input stream and the GUI plots. It covers binary ADC block parsing into circular numpy buffers, the live and static IIR filter pipeline, ADC and Rosette (RS) curve rendering, force-sensor ingestion/calibration/overlay, spectrum (FFT/Welch) computation on a background thread, the piezo and 555-resistance heatmap pipelines (including shear detection, normal-force computation, and pressure-map surface generation), capture lifecycle/archival (JSONL archive writer plus block-timing CSV), capture-cache cleanup, and capture timing bookkeeping. Most files are PyQt6 mixins composed together in `processing_stack.py` into the single `DataProcessorMixin` consumed by the main GUI class; a smaller set of files (`shear_detector.py`, `normal_force_calculator.py`, `pressure_map_generator.py`, `signal_integrator.py`, `heatmap_signal_processing.py`) are GUI-independent, unit-testable signal-processing classes. `__init__.py` re-exports the mixins and key classes as the public surface of the package.

## Files

### __init__.py

Package entry point that imports and re-exports all mixins and standalone classes used by the rest of the app via `__all__`.

- No functions/classes defined directly; re-exports `DataProcessorMixin`, `ADCPlottingMixin`, `CaptureCacheMixin`, `CaptureLifecycleMixin`, `BinaryProcessorMixin`, `FilterProcessorMixin`, `ForceOverlayMixin`, `ForceProcessorMixin`, `HeatmapProcessorMixin`, `NormalForceCalculator`, `NormalForceResult`, `PressureMapGenerator`, `PressureMapResult`, `PressureQuadrantPlane`, `ShearDetector`, `ShearResult`, `SignalIntegrator`, `SignalIntegrationProcessorMixin`, `TimingDisplayMixin`, `SpectrumProcessorMixin`.

### adc_filter_engine.py

Pure-numpy/SciPy IIR filter design and block-filtering engine for ADC channels (notch + low/high/band-pass), independent of the GUI.

- build_default_filter_settings() — returns a default filter-settings dict from `constants.filtering_defaults`.
- ChannelFilterRuntime (dataclass) — holds per-channel sample indices, sample rate, SOS coefficients, and filter state (`zi`).
- ADCFilterEngine.build_channel_index_map(channels, repeat_count) — maps each unique channel to its flat sample indices within a sweep.
- ADCFilterEngine.estimate_channel_sample_rates(...) — estimates per-channel sample rate from sequence composition or sweep timestamps.
- ADCFilterEngine.validate_settings(settings, channel_fs_hz) — validates notch/cutoff settings against Nyquist.
- ADCFilterEngine.design_channel_sos(settings, channel_fs_hz) — builds combined notch + main-filter SOS coefficients.
- ADCFilterEngine.build_runtime_plan(...) — builds a per-channel `ChannelFilterRuntime` plan for a given configuration.
- ADCFilterEngine.reset_runtime_states(runtime_plan) — clears cached filter state (`zi`) for all channels.
- ADCFilterEngine.filter_block(runtime_plan, block_data) — applies SOS filtering in-place across a 2D sweep block.
- ADCFilterEngine.filter_signal(settings, samples, channel_fs_hz) — filters a flat 1D signal (used by spectrum filtering).

### adc_filter_worker.py

Background `QThread` that performs ADC filtering off the GUI thread using a single-slot latest-only queue.

- ADCFilterWorkerThread.submit(payload) — drops stale work and submits the newest filter request.
- ADCFilterWorkerThread.run() — worker loop: rebuilds the filter runtime plan when its signature changes and filters either a `timeseries_window` or `live_block` payload, emitting `result_ready`.
- ADCFilterWorkerThread.stop() — signals the worker loop to exit.

### adc_plotting.py

Mixin owning ADC/Rosette buffer snapshotting, baseline capture, and curve rendering on the time-series plots.

- ADCPlottingMixin._get_ordered_active_buffer_snapshot() — returns the active buffer's data/timestamps in chronological order.
- ADCPlottingMixin.capture_current_plot_baselines(...) — computes per-channel baseline values from a recent time window.
- ADCPlottingMixin.zero_plot_baselines() — captures baselines and triggers a redraw.
- ADCPlottingMixin.capture_current_rosette_plot_baselines(...) — computes RS baseline values from the latest N samples.
- ADCPlottingMixin.zero_rosette_plot_baselines() — captures RS baselines and triggers a redraw.
- ADCPlottingMixin._hide_all_adc_curves() / _hide_all_rosette_curves() — hides all ADC/RS plot curves.
- ADCPlottingMixin._get_selected_plot_channels() / _get_selected_rosette_plot_channels() — returns checked channel keys.
- ADCPlottingMixin._apply_trailing_moving_average(values, window_size) — vectorized trailing moving average.
- ADCPlottingMixin._extract_recent_buffer_window(...) — copies a trailing window from the circular sweep buffers.
- ADCPlottingMixin._get_plot_data_snapshot(active_data_buffer) — chooses full-view or live windowed data for plotting.
- ADCPlottingMixin._get_live_plot_window_snapshot(active_data_buffer) — returns the live display window plus a cache key.
- ADCPlottingMixin._get_live_plot_filter_snapshot(active_data_buffer) — returns a wider window including history for causal-filter warmup.
- ADCPlottingMixin._prepare_channel_plot_series(...) — builds flattened per-channel samples/timestamps, applying voltage conversion and baseline subtraction.
- ADCPlottingMixin._get_or_create_adc_curve / _get_or_create_rosette_curve — lazily creates pyqtgraph curve objects.
- ADCPlottingMixin._set_adc_curve_data / _set_rosette_curve_data — applies visibility/pen/data to a curve.
- ADCPlottingMixin._update_plot_axis_labels() — sets plot axis labels based on device mode/units.
- ADCPlottingMixin.apply_y_axis_range() — applies adaptive or full-scale Y range.
- ADCPlottingMixin._plot_repeat_series(...) — renders every repeat as its own curve.
- ADCPlottingMixin._plot_single_or_average_series(...) — renders a single curve or repeat-averaged curve.
- ADCPlottingMixin._update_rosette_timeseries_plot(...) — renders RS curves from the combined PZT_RS stream.
- ADCPlottingMixin.apply_rosette_y_axis_range() — applies adaptive or fixed Y range to the RS plot.
- ADCPlottingMixin.update_plot() — main entry point that refreshes the ADC/RS time-series plot each frame.

### archive_writer.py

Background daemon thread that drains a queue of sweep blocks and writes them as JSONL records without blocking ingestion.

- ArchiveWriterThread.__init__(archive_path, metadata) — opens state machine and queue for the writer.
- ArchiveWriterThread._transition_state(new_state, error=None) — thread-safe state machine transition.
- ArchiveWriterThread._record_failure(phase, exc) — marks the writer failed and stops it.
- ArchiveWriterThread.get_status_snapshot() — returns a dict snapshot of writer state/counters.
- ArchiveWriterThread.run() — thread body: writes metadata header then drains the queue to JSONL, yielding GIL time during live capture.
- ArchiveWriterThread.enqueue(sweep_timestamps, block_array) — non-blocking enqueue of one block of sweeps.
- ArchiveWriterThread.stop_nowait() — signals shutdown without blocking the caller.
- ArchiveWriterThread.stop(timeout=15.0) — signals shutdown and joins the thread.

### binary_processor.py

Mixin that processes incoming binary ADC blocks: buffer writes, timestamping, archive/timing logging, and rate-limited UI/plot updates.

- BinaryProcessorMixin.process_binary_sweep(samples, avg_sample_time_us, block_start_us, block_end_us) — main per-block ingestion path: initializes buffers, computes wrap-safe timestamps, writes to circular buffers, enqueues archive/timing writes, and rate-limits plot/heatmap/spectrum/status updates.
- BinaryProcessorMixin._maybe_log_slow_timeseries_redraw(...) — emits sparse diagnostics when a Time Series redraw is slow.

### capture_cache.py

Mixin owning the "clear data" UI flow and cleanup of on-disk capture cache files (archive + block-timing CSV).

- CaptureCacheMixin.clear_data() — confirms with the user, then resets all capture state/buffers/plots and triggers cache cleanup.
- CaptureCacheMixin._delete_capture_cache_files(...) — deletes archive/timing files and removes an empty cache directory.
- CaptureCacheMixin._defer_capture_cache_cleanup(...) — polls for the archive writer thread to finish before deleting files.
- CaptureCacheMixin._close_capture_cache_handles(block=True) — stops the archive writer and closes the timing file handle.
- CaptureCacheMixin.cleanup_capture_cache(block=True) — orchestrates closing handles then deleting cache files, optionally deferred.

### capture_lifecycle.py

Mixin owning capture start/stop/finish flow and the resets needed between captures.

- CaptureLifecycleMixin._reset_capture_buffer_state(...) — resets rolling buffers, sweep counters, and baselines.
- CaptureLifecycleMixin._reset_force_capture_state() — clears force sample history and start time.
- CaptureLifecycleMixin._restart_force_baseline_measurement_if_connected() — re-zeros force sensors at capture start if connected.
- CaptureLifecycleMixin._reset_timing_measurements(...) — clears timing state and optional UI labels.
- CaptureLifecycleMixin._reset_signal_processing_state(reset_shear=False) — resets the filter pipeline and optionally shear state.
- CaptureLifecycleMixin._reset_full_view_state(...) — exits full view and clears cached full-view arrays.
- CaptureLifecycleMixin.start_capture() — validates config, resets state, opens archive/timing files, sends the `run` command, and updates UI.
- CaptureLifecycleMixin.stop_capture() — sends `stop`, drains serial input, and calls `on_capture_finished`.
- CaptureLifecycleMixin.on_capture_finished() — finalizes timing logs, reprocesses the filtered buffer if needed, updates UI, and finalizes archive/timing files.
- CaptureLifecycleMixin.set_controls_enabled(enabled) — enables/disables configuration controls during capture.

### filter_processor.py

Mixin providing ADC filter state, static/live reprocessing, and live timeseries filtering integration with the worker thread.

- FilterProcessorMixin._init_filter_state() — initializes filter engine, worker thread, settings, and caches.
- FilterProcessorMixin.get_default_filter_settings() — returns default filter settings dict.
- FilterProcessorMixin.is_adc_filter_supported_mode() / should_filter_adc_data() / should_filter_live_timeseries_locally() — mode/eligibility checks for filtering.
- FilterProcessorMixin.get_active_data_buffer() — returns raw or processed buffer depending on filter/display state.
- FilterProcessorMixin._invalidate_timeseries_filter_cache() / _invalidate_full_view_filter_cache() — clears cached filtered snapshots.
- FilterProcessorMixin._copy_filter_settings_snapshot() — deep-copies current filter settings.
- FilterProcessorMixin.build_filter_metadata(...) — builds a metadata dict describing filter state for export.
- FilterProcessorMixin.filter_dataset_copy(data_array, sweep_timestamps_sec=None) — filters a full dataset copy (used for export/full view).
- FilterProcessorMixin.get_full_view_plot_snapshot() — returns cached or freshly filtered full-view data.
- FilterProcessorMixin._reset_live_filtered_tracking(preserve_existing=False) — resets live filtered-buffer tracking pointers.
- FilterProcessorMixin.prepare_timeseries_filter_resume() — bumps filter generation and invalidates caches when resuming.
- FilterProcessorMixin.maybe_get_live_timeseries_filtered_snapshot(...) — returns cached filtered window or requests a new one from the worker.
- FilterProcessorMixin.get_spectrum_source_state() — returns the buffer/range spectrum should read from.
- FilterProcessorMixin._get_filter_total_sample_rate_hz() — estimates total sample rate for filter design.
- FilterProcessorMixin._get_ordered_filter_sweep_timestamps() — returns chronologically ordered sweep timestamps.
- FilterProcessorMixin._estimate_filter_channel_rates(...) — estimates per-channel sample rates for filtering.
- FilterProcessorMixin._ensure_filter_runtime(...) — rebuilds the filter runtime plan only when signature changes.
- FilterProcessorMixin.reset_filter_states() — clears filter `zi` state.
- FilterProcessorMixin.apply_filter_settings(settings, reprocess_existing=True) — applies new filter settings, validates support, and optionally reprocesses the buffer.
- FilterProcessorMixin._build_live_filter_signature(...) — builds a hashable signature describing the current filter configuration.
- FilterProcessorMixin.request_live_timeseries_filter_snapshot(...) — submits a live timeseries-window filter job to the worker.
- FilterProcessorMixin.enqueue_live_adc_filter(...) — submits a live full-block filter job to the worker.
- FilterProcessorMixin.on_adc_filter_worker_result(result) — applies worker filter results to the timeseries cache or processed buffer.
- FilterProcessorMixin.on_adc_filter_worker_error(message) — disables filtering and logs the worker error.
- FilterProcessorMixin.shutdown_filter_worker() — stops and joins the filter worker thread.
- FilterProcessorMixin.filter_sweeps_block(block_data, total_fs_hz, sweep_timestamps_sec=None) — filters one block synchronously using the cached runtime.
- FilterProcessorMixin.reprocess_filtered_buffer() — rebuilds the entire processed buffer from raw data (used after capture or settings change).

### force_calibration_state.py

Typed dataclasses for the Force Calibration tab's persisted rows and active measurement window (separate from load-cell zero-offset state in `force_state.py`).

- CalibrationRow (dataclass) — one measured calibration entry (sensor family/number, signal source, per-sensor readings, max force/sensor values, timestamp).
- ForceCalibrationState (dataclass) — full Force Calibration tab state: per-family calibration rows, active measurement window, UI selections, autosave flag.
- ActiveMeasurementWindow (dataclass) — tracks live sensor/force peaks during an active measurement window.
- ActiveMeasurementWindow.update_live_sensor_values(sensor_values, total_value=None) — appends the latest live readings.
- ActiveMeasurementWindow.get_max_force_x() / get_max_force_z() / get_max_sensor_value() / get_min_sensor_value() — peak/extreme accessors.
- ActiveMeasurementWindow.reset() — clears all accumulated samples.
- build_default_force_calibration_state() — constructs a fresh `ForceCalibrationState`.
- get_calibration_rows_for_family(state, family) — returns the row list for PZT/PZR/Rosette.

### force_feedback.py

Free functions for user-facing force-processing log/status feedback, kept separate from ingestion/calibration logic.

- log_first_force_sample(owner, state, x_force, z_force) — logs the first raw force sample received.
- log_force_calibration_ready(owner, state) — logs final calibration offsets and readiness.
- maybe_update_force_capture_status(owner, force_sample_count) — refreshes the shared plot status label at a bounded interval.
- schedule_force_plot_refresh(owner) — debounces a force-only plot refresh via a QTimer.

### force_overlay.py

Mixin rendering the force-vs-time overlay (X/Z force curves) aligned to the ADC plot's visible time window.

- apply_force_plot_zero_threshold(force_values_newtons) — zeroes small calibrated force values for display only.
- ForceOverlayMixin._get_force_plot_target() — returns the active force viewbox/curve attributes for ADC or Rosette tab.
- ForceOverlayMixin._get_force_plot_time_window() — computes the ADC plot's visible time span to align force data against.
- ForceOverlayMixin.update_force_plot() — filters force samples to the visible window, downsamples, and updates X/Z force curves.

### force_processor.py

Mixin handling force sensor calibration and per-sample processing/storage.

- ForceProcessorMixin.calibrate_force_sensors() — starts baseline calibration sample collection.
- ForceProcessorMixin.reset_force_baseline_from_recent_samples() — recomputes baseline offset from recently buffered raw samples.
- ForceProcessorMixin._collect_force_calibration_sample(state, x_force, z_force) — accumulates calibration samples until enough are collected.
- ForceProcessorMixin._store_force_capture_sample(state, x_force, z_force) — appends a calibrated sample during active capture.
- ForceProcessorMixin.process_force_data(x_force, z_force) — main entry point: tracks raw samples, runs calibration or calibrates+stores a sample.

### force_state.py

Typed force runtime state plus a legacy-attribute adapter so older mixins can keep using scattered `self.force_*` attributes.

- ForceRuntimeState (dataclass) — force sample deque, start time, calibration offsets/samples, recent raw samples, disconnect flag, counters.
- build_default_force_runtime_state() — constructs a fresh `ForceRuntimeState`.
- LegacyForceRuntimeStateAdapter — property-based adapter mapping `ForceRuntimeState`-like access onto an owner's individual legacy attributes.
- get_force_runtime_state(owner) — returns `owner.force_state` if present, else wraps the owner in `LegacyForceRuntimeStateAdapter`.

### heatmap_555_processor.py

Mixin implementing the 555-resistance-mode (4-sensor-channel) displacement heatmap pipeline, including per-package baseline tracking and Gaussian blob smoothing.

- Heatmap555ProcessorMixin._threshold_label_order() — returns the fixed sensor label order `T, B, R, L, C`.
- Heatmap555ProcessorMixin._get_package_sensor_id(package_index) — resolves a sensor ID string for a package.
- Heatmap555ProcessorMixin._build_r555_channel_value_array(label_order, values, default) — maps threshold/gain arrays onto a label order.
- Heatmap555ProcessorMixin._get_r555_global_noise_threshold(settings) — resolves the global noise threshold from settings.
- Heatmap555ProcessorMixin.reset_555_heatmap_state() — clears per-package 555 state.
- Heatmap555ProcessorMixin._get_r555_package_state(package_index, sensor_count) — lazily creates/returns per-package state dict.
- Heatmap555ProcessorMixin._extract_new_sweeps_since(last_processed_sweep_count) — extracts only newly arrived sweeps from the circular buffer.
- Heatmap555ProcessorMixin._build_channel_matrix(sweeps_array, channels, repeat_count) — averages repeats into a per-unique-channel matrix.
- Heatmap555ProcessorMixin.process_555_displacement_heatmap(settings) — full pipeline: baseline delta, thresholding, weighted center-of-pressure, confidence, and smoothed Gaussian heatmap per sensor package.

### heatmap_piezo_processor.py

Mixin implementing the piezoelectric (5-sensor) heatmap pipeline: RMS magnitude extraction, center-of-pressure, confidence, and Gaussian blob generation.

- PiezoHeatmapProcessorMixin._threshold_label_order() — returns the fixed sensor label order.
- PiezoHeatmapProcessorMixin._get_heatmap_position_for_display_spec / _get_heatmap_package_id_for_display_spec / _get_heatmap_baseline_key_for_display_spec — resolve sensor position/package/baseline key from a display spec.
- PiezoHeatmapProcessorMixin._build_piezo_channel_value_array(values, default, size) — builds a fixed-size per-sensor value array.
- PiezoHeatmapProcessorMixin._get_piezo_global_noise_threshold(settings) — resolves the global noise threshold.
- PiezoHeatmapProcessorMixin._calibrate_heatmap_sensor_values(sensor_values, settings, sensor_id) — applies noise floor, gain, and per-sensor thresholding.
- PiezoHeatmapProcessorMixin.calculate_cop_and_intensity(sensor_values, settings, package_index=0) — computes smoothed center-of-pressure and intensity.
- PiezoHeatmapProcessorMixin.generate_heatmap(cop_x, cop_y, intensity, settings, package_index=0) — renders a Gaussian blob heatmap buffer.
- PiezoHeatmapProcessorMixin.process_sensor_data_for_heatmap(sensor_values, settings, package_index=0) — full per-package pipeline including anisotropic sigma scaling.
- PiezoHeatmapProcessorMixin.calculate_confidence(weights, intensity, settings) — computes confidence/concentration scores.
- PiezoHeatmapProcessorMixin._extract_heatmap_window_data(window_ms) — extracts a recent time window from the raw buffer.
- PiezoHeatmapProcessorMixin._compute_channel_intensities_from_display_specs(...) — computes per-sensor RMS using display-spec-based channel grouping.
- PiezoHeatmapProcessorMixin.compute_channel_intensities(settings) — entry point that prefers display-spec grouping, falling back to sensor package groups.

### heatmap_processor.py

Coordinator mixin combining the piezo and 555 heatmap mixins and owning shared heatmap state (grids, buffers, signal processors).

- HeatmapProcessorMixin (class) — combines `PiezoHeatmapProcessorMixin` and `Heatmap555ProcessorMixin`.
- HeatmapProcessorMixin.init_heatmap_processing_state() — initializes CoP/intensity smoothing state, heatmap buffers, coordinate grids, and per-package `HeatmapSignalProcessor` instances.

### heatmap_signal_processing.py

GUI-independent per-channel signal conditioning (bias removal, high-pass filtering, RMS, smoothing/thresholding) shared by both heatmap pipelines.

- resolve_heatmap_blob_sigmas(settings, default_x, default_y) — returns configured or circular-averaged blob sigmas.
- HeatmapSignalProcessor.__init__(channel_count, bias_duration_sec, hpf_cutoff_hz) — sets up per-channel state.
- HeatmapSignalProcessor.reset() — clears bias, HPF, and EMA state.
- HeatmapSignalProcessor.update_channel_count(channel_count) — resizes/reinitializes state if channel count changes.
- HeatmapSignalProcessor.set_hpf_cutoff(cutoff_hz) — updates the HPF cutoff.
- HeatmapSignalProcessor._update_bias(channel_samples, window_end_time_sec) — accumulates running mean bias until the calibration window elapses.
- HeatmapSignalProcessor._high_pass_filter(samples, sample_rate_hz, idx) — applies a streaming first-order RC high-pass filter.
- HeatmapSignalProcessor.compute_rms(channel_samples, dc_removal_mode, sample_rate_hz, window_end_time_sec, remove_negatives=False) — computes per-channel RMS after bias or HPF-based DC removal.
- HeatmapSignalProcessor.smooth_and_threshold(values, alpha, threshold) — applies EMA smoothing and a magnitude threshold.

### normal_force_calculator.py

GUI-independent computation of signed normal force, force type, and global centroid from shear-removed five-sensor signals (Step 5 of the Shear & Pressure Map pipeline).

- NormalForceResult (dataclass) — residual/normalized signals, force type, baseline offset/force, total force, centroid coordinates.
- NormalForceCalculator.__init__(sensor_spacing_mm=...) — sets center-to-outer sensor spacing.
- NormalForceCalculator.compute(residual_signals) — computes force type, baseline, normalized signals, signed total force, and x/y centroid.
- NormalForceCalculator._normalize_signals(residual_signals) — fills in missing sensor positions with zero.
- NormalForceCalculator._determine_force_type(residual) — classifies compression/tension/none from center then outer sensors.
- NormalForceCalculator._infer_force_type_from_outer_sensors(residual) — tie-breaks force type using outer sensor sign counts/magnitudes.
- NormalForceCalculator._baseline_offset(residual, force_type) — computes the uniform outer-sensor baseline to subtract.
- NormalForceCalculator._axis_position(positive_value, negative_value, center_value) — computes a clamped 1D centroid position.
- NormalForceCalculator._clamp_to_sensor_spacing(value) — clamps a centroid value to +/- sensor spacing.

### pressure_map_generator.py

GUI-independent generator that builds a piecewise-linear 2D pressure surface (per quadrant cross layout) from normalized five-sensor signals.

- PressureTrianglePlane / PressureQuadrantPlane / PressureMapResult (dataclasses) — geometry/plane metadata and the final grid result.
- PressureMapGenerator.__init__(...) — configures circle diameter, sensor spacing, grid resolution/margin, decay parameters; precomputes grids and quadrant masks.
- PressureMapGenerator.generate(normalized_signals) — builds active quadrant planes and renders the pressure grid for one sample.
- PressureMapGenerator._validate_parameters() — validates constructor parameters.
- PressureMapGenerator._build_sensor_positions() / _build_quadrant_definitions() / _build_quadrant_region_masks() — builds static sensor/quadrant geometry.
- PressureMapGenerator._normalize_signals(normalized_signals) — fills missing sensor positions with zero.
- PressureMapGenerator._build_active_quadrant_planes(signals) — determines and builds planes for each active quadrant.
- PressureMapGenerator._quadrant_is_active(signals, quadrant) — checks whether a quadrant's sensors share a consistent sign.
- PressureMapGenerator._build_quadrant_plane(signals, quadrant) — builds peakless, peaked, or single-axis-peaked plane for a quadrant.
- PressureMapGenerator._single_outer_decay_sensor / _single_axis_peak_sensor — detect single-sensor-active special cases.
- PressureMapGenerator._three_sensor_plane_coefficients(signals, quadrant) — solves the base 3-point plane.
- PressureMapGenerator._pressure_point(signals, quadrant) — computes the interior peak point location.
- PressureMapGenerator._pressure_magnitude(value) — magnitude helper respecting `show_negative`.
- PressureMapGenerator._is_peaked_pressure_point(peak_x, peak_y, quadrant) — checks whether the peak lies strictly inside the quadrant.
- PressureMapGenerator._pressure_point_height(signals, quadrant, peak_x, peak_y) — inverse-distance weighted estimate of peak height.
- PressureMapGenerator._build_triangle_planes(signals, quadrant, peak_x, peak_y, peak_height) — builds the four sub-triangle planes for a peaked quadrant.
- PressureMapGenerator._corner_value / _solve_triangle_plane — geometry helpers for triangle plane solving.
- PressureMapGenerator._quadrant_sign(*values) / _value_sign(value) — sign helpers for quadrant activation.
- PressureMapGenerator._build_pressure_grid(quadrant_planes) — fills the full output grid from per-quadrant evaluations.
- PressureMapGenerator._evaluate_quadrant_for_region(...) — dispatches to peaked/single-axis/plane evaluation plus margin decay and clamping.
- PressureMapGenerator._evaluate_single_axis_peaked_quadrant(...) — evaluates the special single-outer-sensor-active surface.
- PressureMapGenerator._apply_margin_decay(...) — decays values toward zero near the outer grid margin.
- PressureMapGenerator._evaluate_peaked_quadrant(...) / _points_in_triangle / _cross — evaluates a peaked quadrant via barycentric triangle membership.
- PressureMapGenerator._evaluate_unmatched_peak_points / _nearest_triangle — fallback assignment for points missed by triangle tests.
- PressureMapGenerator._evaluate_plane(a, b, c, x, y) — evaluates a linear plane.
- PressureMapGenerator._clamp_values(values, sign) — clamps grid values to the quadrant's dominant sign.

### processing_stack.py

Composition layer that combines all the focused mixins (plus the serial parser mixin) into the single `DataProcessorMixin` used by the GUI.

- DataProcessorMixin (class) — multiple inheritance of `ForceOverlayMixin`, `HeatmapProcessorMixin`, `SignalIntegrationProcessorMixin`, `CaptureCacheMixin`, `TimingDisplayMixin`, `ADCPlottingMixin`, `CaptureLifecycleMixin`, `FilterProcessorMixin`, `SerialParserMixin`, `BinaryProcessorMixin`, `ForceProcessorMixin`. No own logic; defines the MRO only.

### shear_detector.py

GUI-independent detector that extracts lateral shear from calibrated five-sensor signals and returns shear-removed residuals (Step 4 of the Shear & Pressure Map pipeline).

- ShearResult (dataclass) — calibrated/strain/residual signals, shear components/magnitude/angle, and pair-detection flags.
- ShearDetector.detect(calibrated_signals) — computes L/R and T/B shear components, magnitude/angle, and residual signals.
- ShearDetector._normalize_signals(calibrated_signals) — fills missing sensor positions with zero.
- ShearDetector._has_opposite_sign_pair(first_value, second_value) — checks whether a sensor pair has opposite signs.
- ShearDetector._horizontal_component(left, right) / _vertical_component(top, bottom) — computes the equal-and-opposite shear magnitude for a pair.

### signal_integration_processor.py

Mixin for a currently-dormant signal-integration pipeline (DC removal + moving-sum integration) for the first 5-channel sensor package; wired into state but not yet called by the live capture loop (per its own module docstring).

- SignalIntegrationProcessorMixin._init_signal_integration_state() — initializes integrator, display buffers, and capacity/decimation state.
- SignalIntegrationProcessorMixin.reset_signal_integration_state(clear_display=True) — rebuilds the `SignalIntegrator` for the current channel mapping.
- SignalIntegrationProcessorMixin.apply_signal_integration_settings(...) — applies HPF cutoff, integration window, and display window settings.
- SignalIntegrationProcessorMixin.process_signal_integration_block(block_samples_array, sweep_timestamps_sec, avg_sample_time_us) — processes one ADC block through the integrator and appends to display buffers.
- SignalIntegrationProcessorMixin.get_signal_integration_display_snapshot(labels=None) — returns a copy of rolling plot buffers.
- SignalIntegrationProcessorMixin.get_signal_integration_current_values() — returns the latest integrated scalar per channel.
- SignalIntegrationProcessorMixin._build_signal_integration_channel_map() — builds the channel-index-to-label map.
- SignalIntegrationProcessorMixin._clear_signal_integration_display_buffers / _ensure_signal_integration_display_buffer / _new_signal_integration_display_buffer — manage per-label rolling deque buffers.
- SignalIntegrationProcessorMixin._calculate_signal_integration_display_capacity / _calculate_signal_integration_display_decimation / _signal_integration_max_points_per_channel — sizing helpers for display buffers.
- SignalIntegrationProcessorMixin._refresh_signal_integration_display_buffer_shape / _refresh_signal_integration_display_buffer_capacity — resize buffers when sample rate/window changes.
- SignalIntegrationProcessorMixin._build_signal_integration_batch(...) — extracts per-channel samples/timestamps from a raw ADC block for the configured sensor group.
- SignalIntegrationProcessorMixin._get_first_signal_integration_group(channels) — resolves the first 5-channel sensor package group.
- SignalIntegrationProcessorMixin._build_signal_integration_sample_indices(...) — computes per-channel sample indices, with special handling for PZT1 MUX mode.
- SignalIntegrationProcessorMixin._estimate_signal_integration_sample_rate(...) — estimates effective per-channel sample rate from timestamps.
- SignalIntegrationProcessorMixin._is_signal_integration_pzt1_mode() / _is_signal_integration_reverse_polarity() — mode/polarity queries delegated to the owner GUI.
- SignalIntegrationProcessorMixin._apply_signal_integration_polarity(values) — applies normal/reversed polarity multiplier.
- SignalIntegrationProcessorMixin._append_signal_integration_outputs(...) — decimates and appends integrator output to display buffers.
- SignalIntegrationProcessorMixin._decimate_signal_integration_display_batch(label, values, times) — decimates a batch for display using a running counter.
- SignalIntegrationProcessorMixin._prune_signal_integration_display_buffers() — trims display buffers to the configured rolling window.
- SignalIntegrationProcessorMixin._maybe_update_signal_integration_plot() — rate-limits and triggers the Signal Integration plot update.

### signal_integrator.py

GUI-independent streaming integrator: per-channel DC-bias removal (SciPy Butterworth HPF or running-mean fallback) plus rectangular moving-sum integration.

- SignalIntegrator.__init__(channel_count, hpf_cutoff_hz, integration_window_samples, sample_rate_hz=None, channel_map=None, scale_by_dt=...) — configures and validates integrator parameters.
- SignalIntegrator.set_channel_map(channel_map) — sets or clears the channel-index-to-label map.
- SignalIntegrator.update_parameters(...) — updates HPF/window/sample-rate/channel-map/scale settings, resetting filter state as needed.
- SignalIntegrator.reset() — clears all per-channel filter and integration state.
- SignalIntegrator.process(samples_by_channel, sample_rate_hz=None) — filters and integrates one streaming batch per channel.
- SignalIntegrator.get_current_values() — returns the latest integrated scalar per channel/label.
- SignalIntegrator._validate_channel_count / _validate_window_size / _validate_optional_sample_rate / _validate_channel_index — input validation helpers.
- SignalIntegrator._normalize_samples(samples_by_channel) — normalizes dict/sequence input into a channel-indexed dict.
- SignalIntegrator._output_key(channel_index) — resolves the output dict key (index or mapped label).
- SignalIntegrator._is_hpf_enabled() — checks whether HPF cutoff is active.
- SignalIntegrator._ensure_filter_design() — (re)designs the Butterworth SOS filter when parameters change.
- SignalIntegrator._reset_filter_states() — clears per-channel IIR/fallback state.
- SignalIntegrator._remove_dc(channel_index, samples) — dispatches to SciPy or running-mean DC removal.
- SignalIntegrator._remove_dc_with_scipy(channel_index, samples) — streaming SOS high-pass filtering.
- SignalIntegrator._remove_dc_with_running_mean(channel_index, samples) — fallback running-mean-based DC removal.
- SignalIntegrator._integrate_filtered_samples(channel_index, filtered_samples) — rectangular moving-sum integration with optional dt scaling.
- SignalIntegrator._trim_integration_histories() — trims stored history after a window-size change.

### spectrum_processor.py

Mixin and background worker computing FFT/Welch PSD spectra off the GUI thread, with resampling, optional filtering, and EMA/N-average smoothing.

- SpectrumWorkerThread.submit(payload) / run() / stop() — latest-only background worker for spectrum computation.
- _next_power_of_two(value) — rounds up to the next power of two.
- _window_array(window_name, length) — returns a Hanning/Hamming/Blackman/rectangular window array.
- _compute_fft_magnitude(samples, fs_hz, nfft, window_name, remove_dc) — computes windowed single-sided FFT magnitude.
- _compute_welch_psd(samples, fs_hz, seg_len, overlap_percent, nfft, window_name, remove_dc) — computes Welch-averaged PSD.
- _compute_spectrum_payload(payload) — full per-channel pipeline: optional timestamp-based resampling, optional ADC filtering, FFT or Welch computation.
- SpectrumProcessorMixin._init_spectrum_state() — starts the spectrum worker and initializes averaging state.
- SpectrumProcessorMixin.shutdown_spectrum_worker() — stops and joins the spectrum worker.
- SpectrumProcessorMixin._extract_recent_sweeps(required_sweeps) — extracts a trailing window of sweeps from the active buffer.
- SpectrumProcessorMixin._get_total_sample_rate_hz() — estimates total sample rate from Arduino timing or sweep timestamps.
- SpectrumProcessorMixin._build_spectrum_payload(spectrum_settings) — builds the per-channel payload (samples, timestamps, fs) to send to the worker.
- SpectrumProcessorMixin.reset_spectrum_averaging() — clears EMA/N-average state.
- SpectrumProcessorMixin.update_spectrum() — builds and submits a spectrum payload if the Spectrum tab is active and not frozen/busy.
- SpectrumProcessorMixin.on_spectrum_worker_result(result) — applies EMA or N-average smoothing to worker results and updates the display.
- SpectrumProcessorMixin.on_spectrum_worker_error(message) — shows the spectrum error status.

### timing_display.py

Mixin owning capture timing state (`TimingState`), timing label updates, and 555-mode charge/discharge time readouts.

- TimingState (dataclass) — central store for timing metrics and bounded recent-history lists.
- TimingState.reset(empty_timing_data) — clears scalar fields and history lists while keeping object identity stable.
- TimingState.trim_recent(attr_name, max_items) — trims a history list to its most recent N items.
- TimingDisplayMixin._build_empty_timing_data() — returns a fresh empty timing-data dict.
- TimingDisplayMixin._create_timing_state() / _ensure_timing_state() — lazily create the `TimingState` instance.
- TimingDisplayMixin.timing_state (property) — accessor for the lazily created `TimingState`.
- TimingDisplayMixin.update_timing_display() — computes and writes per-channel/total rate and block-gap labels from timing history.
- TimingDisplayMixin._current_elapsed_since_first_sweep_seconds() — computes elapsed capture time from the latest sweep timestamp.
- TimingDisplayMixin.format_plot_info_label_text(...) — formats the shared ADC/force status line text.
- TimingDisplayMixin.update_plot_info_label(...) — updates the plot info QLabel, skipping no-op writes.
- TimingDisplayMixin._format_time_auto(seconds) — formats a duration in µs/ms/s as appropriate.
- TimingDisplayMixin.update_555_timing_readouts(latest_channel_values) — computes and displays 555-mode charge/discharge time labels.
