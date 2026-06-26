# Tests

This folder contains pytest-based regression tests for the Arduino ADC streamer desktop application. Tests cover configuration/connection state machines, serial parsing, ADC and force data processing, filtering, heatmap/pressure-map/shear computations, export, and settings persistence. Most tests build small fakes/harnesses around mixins rather than launching the full GUI, though a few (pressure map widget, shear visualization widget, sensor panel, signal integration panel) instantiate real PyQt6 widgets under an offscreen Qt platform.

Run the tests from the repository root with:

```bash
python -m pytest
```

Or:

```bash
uv run pytest
```

## Files

### test_adc_config_state.py
Tests the `ADCConfigurationState` dataclass-like mapping and its defaults.
- test_default_state_matches_expected_defaults() — verifies the default ADC config state values.
- test_mapping_compatibility_helpers_work_for_known_fields() — checks dict-style get/set/update on known fields.
- test_unknown_keys_are_rejected() — confirms unknown keys raise KeyError on read and write.

### test_adc_configuration_runner.py
Tests `ADCConfigurationRunner`, which retries ADC configuration sends in a background-style flow.
- test_runner_retries_until_success_and_returns_outcome() — verifies retry-until-success behavior and serial buffer resets between attempts.

### test_adc_configuration_service.py
Tests `ADCConfigurationService`, which builds and verifies the command sequence sent to the Arduino for ADC/555/PZT_RS configuration, including buffer-size capping and ground-sampling conflicts.
- test_apply_555_parameter_requires_connected_555_mode() — rejects 555 parameter changes when disconnected or in the wrong mode.
- test_apply_555_parameter_allows_pzt_rs_mode() — allows 555 parameters when PZT_RS mode is explicitly permitted.
- test_apply_555_parameter_switches_device_into_pzt_rs_mode_first() — switches device mode before applying the parameter.
- test_estimate_555_pair_timeout_ms_matches_pcb17_rs_defaults() — checks the 555 pair timeout estimate formula.
- test_send_adc_config_runs_expected_command_sequence() — verifies the full ADC config command order and echo verification.
- test_array_sensor_selection_accepts_unique_echo_verification() — verifies dedup of repeated channels for array sensor-selection mode.
- test_array_pzt_buffer_is_limited_by_mux_pair_capacity() — caps buffer size for paired-mux array PZT mode.
- test_array_dual_mux_overlap_disables_ground_sampling() — disables ground sampling when mux channel overlap occurs.
- test_array_pzt_rs_mode_command_stays_on_adc_config_path() — confirms PZT_RS config commands still resolve to "adc" device mode.
- test_array_pzt_rs_buffer_is_capped_for_startup_latency() — caps buffer size in PZT_RS mode for startup latency.

### test_adc_connection_state.py
Tests default/connected/disconnected view-state builders for ADC connection UI state.
- test_default_last_sent_config_has_expected_fields() — verifies default `LastSentConfig` fields are None.
- test_default_arduino_status_has_expected_fields() — verifies default `ArduinoStatus` fields are None.
- test_connected_and_disconnected_view_states_match_expected_ui_flags() — checks button text/enabled flags for both states.

### test_adc_connection_workflow.py
Tests `ADCConnectionWorkflow`, which sequences session connect and MCU detection.
- test_connect_runs_session_connect_then_mcu_detection() — verifies connect order and detection timeout pass-through.
- test_disconnect_collects_session_warnings() — verifies warnings from session disconnect are surfaced.

### test_adc_filter_engine.py
Tests `ADCFilterEngine`, the SciPy-backed digital filter engine used for live and full-view ADC filtering.
- test_default_filter_settings_shape() — checks default filter settings dict shape, including 3 notch filters.
- test_validate_settings_rejects_invalid_bandpass() — rejects bandpass settings where low cutoff exceeds high cutoff.
- test_build_runtime_plan_and_filter_block() — verifies a no-op filter plan passes data through unchanged (requires SciPy).
- test_estimate_channel_sample_rates_uses_sweep_timestamps() — estimates per-channel sample rates from sweep timestamps.
- test_filter_signal_preserves_constant_level_without_zero_drop() — confirms a lowpass filter does not introduce a leading zero drop (requires SciPy).

### test_adc_plotting.py
Tests buffer-window extraction and live-filter snapshot helpers in `ADCPlottingMixin`, including ring-buffer wraparound handling.
- test_extract_recent_buffer_window_without_wrap() — extracts a trailing window from an unwrapped ring buffer.
- test_extract_recent_buffer_window_with_wrap() — extracts a trailing window correctly when the ring buffer has wrapped.
- test_get_live_plot_filter_snapshot_includes_history_for_warmup() — includes extra history samples for filter warmup.
- test_get_live_plot_filter_snapshot_handles_wrapped_history() — handles filter warmup snapshot across a wrapped buffer.

### test_adc_serial_routing.py
Tests ACK-line parsing and command/response routing for the ADC serial mixin, including MCU detection.
- test_parse_ack_line() — parses `#OK`/`#NOT_OK` lines and ignores other lines.
- test_send_command_and_wait_ack_uses_routed_adc_lines() — verifies command-and-wait-for-ack round trip via routed serial lines.
- test_detect_mcu_uses_routed_adc_lines() — verifies MCU detection updates state from a routed serial response.

### test_archive_io.py
Tests the JSONL archive writer thread and archive loader, including timestamp reconstruction from embedded values, sidecar timing files, or index fallback.
- test_archive_writer_persists_metadata_and_sweeps() — verifies metadata and sweep rows are written and closed correctly.
- test_archive_writer_reports_open_failure() — reports a failed state when the archive path cannot be opened.
- test_archive_loader_prefers_embedded_timestamps() — loads sweeps using embedded per-row timestamps when present.
- test_archive_loader_reconstructs_timestamps_from_sidecar() — reconstructs timestamps from a block-timing CSV sidecar.
- test_archive_loader_falls_back_to_indices_without_timing_data() — falls back to integer index timestamps with no timing data.
- test_finalize_archive_logs_writer_failure() — logs and clears the archive writer reference on writer failure.

### test_array_dual_mode_pzt.py
Tests dual-mux/PZT_RS array sensor routing: channel/mux/RS-channel command building, per-sensor display spec mapping, and rosette (RS) scaling, including multi-sensor independence and PCB1.7 5-sensor layouts.
- test_dual_mode_pzt_is_treated_as_paired_mux_mode() — verifies paired-mux PZT1 mode channel and sweep-size calculations.
- test_dual_mode_pzt_display_specs_map_within_unique_channel_stream() — verifies per-sensor display specs map into a unique channel stream.
- test_pzt_rs_mode_uses_sensor_groups_with_five_pzt_and_two_rs_values() — verifies PZT_RS mode produces 5 PZT + 2 RS values per sensor.
- test_pzt_rs_routing_summary_reports_mux_adc_and_rs_channels() — verifies the human-readable PZT_RS routing summary string.
- test_pzt_rs_allows_duplicate_rs_channel_pair_for_one_sensor() — allows a duplicated RS channel pair for a single sensor.
- test_pzt_rs_preserves_mixed_rs_channel_15_pairs_for_display() — preserves display key ordering for mixed RS channel-15 pairs.
- test_pcb17_five_sensor_layout_uses_seven_values_per_sensor() — verifies the PCB1.7 5-sensor layout uses 7 values per sensor.
- test_pcb17_two_sensor_subset_rs_indices_are_independent() — regression test ensuring RS sample indices are independent per sensor (prevents flat/duplicate RS display).
- test_pzt_rs_rosette_scaling_only_touches_rs_columns() — verifies in-place RS scaling only modifies RS columns, not ADC columns.
- test_pzt_rs_rosette_scaling_handles_one_sweep_vector() — verifies RS scaling works on a single 1D sweep vector.
- test_pzt_rs_archive_unit_helper_supports_current_and_legacy_units() — verifies ohms-per-wire-unit lookup for current and legacy unit labels.
- test_array_pzt_pzr1_selects_pzt_rs_when_requested() — verifies Array_PZT_PZR1 can select PZT_RS as its operation mode.

### test_binary_status.py
Tests `BinaryProcessorMixin.process_binary_sweep`, including status-label formatting after ring-buffer wraparound and triggering of pressure-map/signal-integration refresh.
- test_runtime_status_uses_true_sweep_count_for_total_samples() — verifies the status label reports the true (wrapped) sweep and sample counts.
- test_pressure_map_refresh_is_queued_from_binary_handler() — verifies pressure-map/signal-integration update is triggered only when needed.

### test_capture_cache.py
Tests `CaptureCacheMixin.cleanup_capture_cache`, covering blocking deletion and non-blocking deferral while the archive writer is still alive.
- test_cleanup_capture_cache_blocking_deletes_files_and_resets_state() — blocking cleanup deletes archive/timing files and resets cache state.
- test_cleanup_capture_cache_nonblocking_defers_when_writer_alive() — non-blocking cleanup defers deletion while the writer thread is alive.

### test_capture_lifecycle.py
Tests `CaptureLifecycleMixin.set_controls_enabled`, which toggles acquisition-related UI controls during capture.
- test_set_controls_enabled_updates_acquisition_controls() — verifies controls are disabled/enabled together as a group.

### test_config_snapshot.py
Tests `config_snapshot` helpers that normalize UI widget values (vref, gain) into an ADC configuration snapshot.
- test_normalize_reference_uses_vref_map_when_control_is_active() — maps a vref combo label to its command string.
- test_normalize_gain_strips_multiplication_symbol() — strips the "×" suffix from gain labels.
- test_build_snapshot_applies_widget_values_and_fallbacks() — builds a full snapshot from widget values with fallbacks for unused controls.

### test_config_view_state.py
Tests builder functions for ADC configure/start button view states.
- test_configure_states_match_expected_ui_flags() — verifies enabled flags and status messages for configuring/success/failed states.
- test_start_states_match_expected_ui_flags() — verifies enabled flags and button text for ready/needs-config/unavailable states.

### test_data_exporter.py
Tests `DataExporterMixin.save_data`, covering CSV/metadata export, filtered-data export, save-notice UI feedback, and streaming export from an archive beyond the in-memory display buffer limit.
- test_export_prefers_fullest_available_source_over_short_archive_cache() — prefers the in-memory full-view dataset over a short archive cache.
- test_save_data_filters_csv_and_records_filter_metadata() — exports filtered CSV data and records filter metadata in the sidecar JSON.
- test_save_data_shows_and_hides_progress_notice() — verifies the save-progress notice is shown then hidden with status updates.
- test_save_data_streams_archive_beyond_display_buffer_limit() — streams export directly from the archive file when sweep count exceeds the buffer.

### test_filter_policy.py
Tests filter-buffer selection policy across device modes/tabs (`FilterProcessorMixin`) and spectrum-tab filter UI controls (`SpectrumPanelMixin`).
- test_processed_buffer_is_bypassed_in_555_mode() — uses the raw buffer and disables filtering in 555 mode.
- test_live_adc_filtering_uses_raw_buffer_for_timeseries_capture() — uses raw buffer for live time-series capture even with filtering enabled.
- test_full_view_snapshot_uses_filtered_dataset_when_enabled() — applies filtering to the full-view snapshot when enabled (requires SciPy).
- test_filter_block_bypasses_when_mode_not_supported() — bypasses block filtering when the device mode does not support it.
- test_spectrum_filter_controls_disable_outside_adc_mode() — disables spectrum filter controls outside ADC mode and logs why.
- test_apply_filter_auto_enables_master_when_notch_selected() — auto-enables the master filter switch when a notch is selected.
- test_turn_off_filter_button_disables_filter_but_preserves_settings() — turns filtering off via button while preserving filter settings.

### test_filter_worker_integration.py
Tests live ADC filtering integration with a background filter worker, including snapshot request/result caching, generation staleness, and spectrum-source buffer selection.
- test_live_timeseries_prefers_raw_buffer_while_capturing() — uses the raw buffer for the live time-series view during capture.
- test_request_live_timeseries_filter_snapshot_submits_latest_window() — submits a filter-window request payload to the worker.
- test_request_live_timeseries_filter_snapshot_keeps_history_for_warmup() — keeps extra history samples in the submitted payload for filter warmup.
- test_duplicate_live_timeseries_snapshot_request_is_skipped() — skips submitting a duplicate request for the same snapshot key.
- test_timeseries_worker_result_caches_window_and_requests_replot() — caches worker results and triggers a plot update.
- test_timeseries_worker_result_trims_history_to_visible_window() — trims cached filtered data down to the visible display window.
- test_stale_timeseries_worker_result_updates_cached_window() — accepts a stale (non-latest) worker result while keeping the newer pending key.
- test_live_timeseries_uses_latest_cached_filtered_window_while_newer_one_is_pending() — serves the latest cached filtered window while a newer one is still pending.
- test_first_live_timeseries_request_falls_back_to_raw_until_filter_result_arrives() — falls back to raw data until the first filtered result arrives.
- test_worker_error_disables_filtering() — disables filtering and records the error message on worker failure.
- test_spectrum_source_state_uses_raw_buffer_on_spectrum_tab() — uses the raw buffer (not filtered) as the spectrum tab's data source.
- test_worker_result_from_old_generation_is_ignored() — ignores filter worker results tagged with a stale generation number.

### test_force_baseline_capture_start.py
Tests automatic force-sensor re-zeroing when a capture starts.
- test_capture_start_rezeros_force_baseline_when_force_port_is_connected() — re-zeros force baseline at capture start when the force port is open.
- test_capture_start_skips_force_rezero_when_force_port_is_disconnected() — skips re-zeroing when the force port is not connected.

### test_force_calibration_panel.py
Tests force-calibration tab state objects: default state, live measurement window, per-sensor-family calibration rows, and the sensor-value-to-table-column mapping.
- test_default_state_is_initialized() — verifies default calibration state values.
- test_measurement_window_tracks_latest_sensor_values() — tracks latest 5-sensor values and their running total.
- test_measurement_window_reset() — resets the measurement window to empty state.
- test_calibration_row_supports_5_sensor_readings() — verifies a calibration row stores all 5 sensor readings and metadata.
- test_rows_are_separate_per_family() — verifies PZT/PZR/rosette calibration rows are stored in separate lists.
- test_sensor_order_mapping_matches_table_columns() — verifies live sensor values map to top/bottom/left/right/center table columns correctly.

### test_force_channel_checkboxes.py
Tests dynamic force X/Z channel checkbox creation and reset tied to force-port connection state.
- test_add_force_channel_checkboxes_only_when_force_port_is_connected() — only adds force checkboxes when the force serial port is connected.
- test_force_checkbox_selection_helper_toggles_both_widgets() — toggles both X and Z force checkboxes together.
- test_force_checkbox_refs_reset_when_layout_rebuilds() — clears checkbox references when the layout is rebuilt.

### test_force_connection_state.py
Tests connected/disconnected view-state builders for force-sensor connection UI.
- test_connected_and_disconnected_view_states_match_expected_ui_flags() — verifies button text and control-enabled flags for both states.

### test_force_connection_workflow.py
Tests `ForceConnectionWorkflow` connect/disconnect sequencing and calibration triggering.
- test_connect_runs_session_connect_and_requests_calibration() — verifies connect triggers calibration start.
- test_disconnect_collects_session_warnings() — verifies disconnect warnings are collected from the session.
- test_disconnect_with_missing_session_returns_empty_warnings() — returns empty warnings when no session is present.

### test_force_export_alignment.py
Tests force-data series building, nearest-timestamp lookup, and CSV export alignment between ADC sweeps and force samples by timestamp.
- test_build_force_export_series_sorts_by_timestamp() — sorts unordered force samples into a timestamp-ordered series.
- test_get_nearest_force_values_prefers_earlier_sample_on_tie() — prefers the earlier sample when two timestamps are equidistant.
- test_build_export_row_timestamps_uses_linear_fallback_when_needed() — falls back to a linear timestamp spacing when no real timestamps are available.
- test_save_data_aligns_force_columns_by_nearest_sweep_timestamp() — exports CSV rows with force columns aligned to the nearest ADC sweep timestamp.

### test_force_overlay.py
Tests the force-plot overlay target selection (main vs. rosette tab), trailing time-window calculation across capture states/ring-buffer wrap, and small-force jiggle thresholding.
- test_force_plot_target_uses_main_timeseries_by_default() — uses the main time-series viewbox/curves by default.
- test_force_plot_target_uses_rosette_overlay_on_rosette_tab() — switches overlay target to the rosette tab's viewbox/curves.
- test_time_window_uses_trailing_capture_window_before_wrap() — computes a trailing time window before the ring buffer wraps.
- test_time_window_uses_wrapped_ring_order_while_capturing() — computes the time window correctly after ring-buffer wraparound.
- test_time_window_uses_full_retained_span_after_capture() — uses the full retained span once capture has stopped.
- test_time_window_uses_full_view_timestamp_span() — uses the full-view timestamp span when in full-view mode.
- test_time_window_returns_none_without_adc_sweeps() — returns None when there are no ADC sweeps to align against.
- test_update_force_plot_returns_before_work_when_timeseries_hidden() — skips plot work when the time-series view is not visible.
- test_plot_zero_threshold_flattens_small_force_jiggle() — flattens small force values below a threshold to zero.

### test_force_processor.py
Tests `ForceProcessorMixin`: calibration completion logging, buffering gated by active capture, status-label updates, and load-cell baseline reset from recent raw samples.
- test_force_calibration_logs_ready_status_when_offsets_complete() — logs a ready message once calibration offsets are computed.
- test_force_samples_do_not_buffer_before_capture_starts() — does not buffer force samples before capture begins.
- test_force_samples_buffer_during_active_capture() — buffers calibrated, time-relative force samples during active capture.
- test_force_samples_buffer_without_redraw_when_timeseries_hidden() — buffers samples but skips plot redraw when time series is hidden.
- test_force_status_label_updates_on_interval_boundary() — updates the status label at the configured sample interval.
- test_force_reset_uses_recent_raw_samples_not_capture_buffered_values() — resets baseline using recent raw samples rather than capture-buffered values.

### test_force_reader_thread_parser.py
Tests `parse_force_sensor_line`, the line parser for various force-sensor serial line formats.
- test_parse_simple_x_z_csv_line() — parses a plain "x,z" CSV line.
- test_parse_timestamp_x_z_csv_line() — parses a "timestamp,x,z" CSV line.
- test_parse_labeled_numeric_line_uses_last_two_values() — parses a labeled line, using the last two numeric values as x/z.
- test_parse_returns_none_for_malformed_line() — returns None for an unparseable line.
- test_parse_returns_none_for_empty_line() — returns None for an empty line.

### test_force_serial.py
Tests `ForceSerialMixin` error-handling routing (debug vs. real read errors) and the load-cell reset command.
- test_debug_message_does_not_trigger_disconnect() — does not disconnect on benign debug log lines.
- test_read_error_schedules_disconnect() — schedules a disconnect on a genuine read error.
- test_reset_load_cell_uses_recent_samples_when_connected() — resets load cell baseline using recent samples when connected.
- test_reset_load_cell_warns_when_disconnected() — logs a warning instead of resetting when disconnected.

### test_force_session.py
Tests `ForceSessionController` connect/disconnect lifecycle: serial port opening, reader thread startup/shutdown, and warning collection on failures.
- test_connect_opens_port_clears_buffer_and_starts_reader_thread() — opens the serial port, clears its buffer, and starts the reader thread with signal wiring.
- test_disconnect_stops_thread_and_collects_warnings() — stops the reader thread and reports timeout/close warnings.
- test_connect_closes_port_if_reader_start_fails() — closes the port and cleans up state if the reader thread fails to start.

### test_force_state.py
Tests `ForceRuntimeState` defaults and the legacy adapter that maps state fields onto legacy object attribute names.
- test_default_force_runtime_state_has_expected_defaults() — verifies default values for a fresh force runtime state.
- test_legacy_force_runtime_adapter_reads_and_writes_legacy_fields() — verifies adapter reads/writes correctly map to legacy attribute names.

### test_heatmap_thresholds.py
Tests heatmap signal processing across 555 and piezo (PZT) processors: RMS computation (including positive-only RMS), Gaussian blob shape (circular vs. ellipse), per-sensor/global thresholding, array layout package-center geometry (including mirroring), array point-tracking selection, gap-aware display geometry, and row-major image rendering.
- test_remove_negatives_uses_half_wave_rms() — verifies positive-only RMS uses half-wave rectification.
- test_piezo_heatmap_blob_uses_columns_for_left_right_motion() — verifies left/right sensor signals shift the blob horizontally.
- test_piezo_circular_blob_mode_uses_equal_axis_spread() — verifies circular blob mode produces symmetric heatmap variance.
- test_piezo_ellipse_blob_mode_keeps_independent_axis_spread() — verifies ellipse mode keeps independent X/Y spread.
- test_555_circular_blob_mode_ignores_axis_adaptation() — verifies 555 circular mode ignores axis-adapt strength.
- test_heatmap_panel_uses_row_major_images_without_transpose() — verifies heatmap images are set without transposing (row-major).
- test_heatmap_array_package_centers_follow_sensor_layout() — verifies package center positions follow the configured array layout.
- test_heatmap_mirror_flips_array_package_centers() — verifies mirror toggle flips package center X coordinates.
- test_heatmap_mirror_flips_display_image_left_right() — verifies mirror toggle flips the rendered heatmap image left-right.
- test_heatmap_display_bounds_expand_to_viewport_aspect() — verifies display bounds expand to match the viewport aspect ratio.
- test_heatmap_gap_uses_sensor_diameter_plus_gap_mm() — verifies configured physical gap expands the display spacing based on sensor diameter plus edge-to-edge gap.
- test_point_tracking_uses_horizontal_gap_for_matching_edge_pair() — verifies point tracking can place the point between left/right neighboring sensors.
- test_point_tracking_uses_vertical_gap_for_matching_edge_pair() — verifies point tracking can place the point between upper/lower neighboring sensors.
- test_point_tracking_prefers_strongest_sensor_when_no_pair_exists() — verifies only the strongest valid tracked point is rendered across the array when no between-sensor pair wins.
- test_point_tracking_keeps_multi_channel_sensor_inside_sensor() — verifies multi-channel activity on one sensor resolves inside that sensor instead of in a gap.
- test_point_tracking_display_renders_single_tracking_blob() — verifies the combined display renders the single tracked point when point tracking is enabled.
- test_555_thresholds_use_package_sensor_id_and_per_channel_totals() — verifies per-sensor and global thresholds reduce 555 channel values correctly.
- test_piezo_thresholds_use_global_plus_package_channel_thresholds() — verifies piezo per-channel thresholding combines global and package thresholds.
- test_piezo_array_mux_mode_uses_display_spec_sample_indices() — verifies paired-mux mode reads intensities from the correct display sample indices.
- test_555_cop_respects_configured_channel_placement() — verifies center-of-pressure respects a custom channel-to-sensor-position mapping.
- test_555_uses_channel_baselines_for_heatmap_calculation() — verifies per-channel baselines are subtracted before heatmap calculation.

### test_legacy_constants.py
Static AST-based checks ensuring legacy visualization constants and archived modules remain isolated in the `Legacy/` package rather than leaking into the active `config_constants.py`.
- test_legacy_visualization_constants_live_in_legacy_config() — verifies legacy visualization constant names are defined in `Legacy/config_constants.py`.
- test_archived_visualization_modules_import_legacy_constants() — verifies archived modules import from `Legacy.config_constants`, never from the active `config_constants`.

### test_mcu_detector.py
Tests `MCUDetectorMixin` ground-pin locking for special array MCUs and re-arming of PZT_PZR1 defaults on MCU change.
- test_locked_ground_pin_mapping_for_special_mcus() — verifies fixed ground-pin assignment for known special MCU names.
- test_special_mcu_detection_includes_both_variants() — verifies detection covers both `Array_PZT_PZR1` and `Array_PZT_PZR1.7`.
- test_defaults_are_rearmed_when_mcu_name_changes() — verifies the "defaults applied" flag resets when the MCU name changes.

### test_mcu_profile.py
Tests `resolve_mcu_profile`, which derives device-mode and UI-control capability flags from an MCU name and selected array mode.
- test_resolves_array_dual_pzr_as_555_mode() — resolves a dual-PZR array MCU to 555 mode with hidden ground controls.
- test_resolves_teensy_as_adc_with_teensy_controls() — resolves Teensy to ADC mode with Teensy-specific controls.
- test_resolves_array_pzt1_as_adc_with_hidden_reference() — resolves Array_PZT1 to ADC mode with hidden reference control.
- test_resolves_array_pzt_pzr17_pzt_rs_capability() — resolves PCB1.7 dual array MCU with PZT_RS support enabled.
- test_array_pzt_pzr1_now_supports_pzt_rs() — confirms Array_PZT_PZR1 (non-1.7) also supports PZT_RS mode.

### test_mcu_state.py
Tests MCU state builder functions for detected/unknown/disconnected states.
- test_detected_state_populates_label_and_log() — verifies label text and log message for a detected MCU.
- test_unknown_state_resets_to_unknown_label() — verifies fallback to "Unknown" label with a timeout message.
- test_disconnected_state_resets_label_and_device_mode() — verifies reset to default label and ADC device mode on disconnect.

### test_mcu_view_state.py
Tests `build_mcu_view_state`, which maps an MCU profile to UI visibility/label flags.
- test_555_profile_maps_to_hidden_adc_controls() — verifies 555 profile hides ADC controls and shows 555 controls.
- test_teensy_profile_maps_to_teensy_controls_and_averaging_label() — verifies Teensy profile shows Teensy controls with "Averaging:" label.
- test_array_pzt_profile_keeps_reference_hidden_and_osr_visible() — verifies array PZT profile hides reference control but shows OSR.
- test_pzt_rs_profile_shows_555_controls_without_hiding_osr() — verifies PZT_RS profile shows 555 controls while keeping OSR visible.
- test_array_pzt_pzr1_pzt_rs_profile_shows_555_controls_without_hiding_osr() — same check for the non-1.7 PZT_PZR1 variant.

### test_normal_force_calculator.py
Tests `NormalForceCalculator`, which derives force type (compression/tension/none), total force, and centroid position from 5-sensor signals.
- test_symmetric_compression_centers_position_and_preserves_total() — verifies symmetric input yields centered position and correct total force.
- test_off_center_press_moves_toward_top_left() — verifies an off-center press shifts the computed centroid accordingly.
- test_all_negative_inputs_are_tension() — verifies all-negative input is classified as tension.
- test_all_zero_inputs_have_no_force() — verifies all-zero input yields zero force and centered position.
- test_center_zero_edge_press_infers_compression_from_outer_sensors() — infers compression direction from outer sensors when center is zero.
- test_center_zero_mixed_outer_tie_uses_larger_signed_magnitude() — resolves a tie between outer sensors using the larger signed magnitude.

### test_pressure_map_generator.py
Tests `PressureMapGenerator`, which interpolates a 2D pressure grid from 5-sensor signals across quadrant planes with peaked/peakless/single-axis-peaked modes.
- test_sensor_positions_reproduce_sensor_values_on_grid() — verifies each sensor's grid value matches its input signal.
- test_peak_height_is_reproduced_at_peak_location() — verifies the computed peak height matches the grid value at the peak location.
- test_default_mode_uses_positive_signals_for_pressure_point() — verifies default mode ignores negative signals for peak placement.
- test_show_negative_mode_uses_absolute_magnitude_for_pressure_point() — verifies show-negative mode uses absolute magnitude for peak placement.
- test_continuity_matches_on_shared_x_axis() — verifies adjacent quadrant planes agree along their shared boundary.
- test_only_center_nonzero_decays_monotonically_to_outer_zero_sensors() — verifies monotonic decay from center to zero-signal edges.
- test_compression_and_tension_clamping() — verifies grid values are clamped to non-negative (compression) or non-positive (tension).
- test_symmetric_inputs_produce_nearly_symmetric_map() — verifies symmetric inputs yield a symmetric pressure grid.
- test_all_zero_inputs_produce_empty_zero_map() — verifies all-zero input yields no active quadrants and an all-zero grid.
- test_only_one_outer_nonzero_produces_peakless_axis_ridge() — verifies a single nonzero outer sensor produces a peakless axis ridge.
- test_peakless_and_peaked_classification_for_zero_outer_axis() — verifies correct mode classification per quadrant for a zero outer axis.
- test_center_plus_one_side_creates_single_axis_peak_between_sensors() — verifies a single-axis peak forms between center and one side sensor.
- test_mixed_inputs_use_single_axis_peaks_when_one_outer_is_zero() — verifies mixed inputs select single-axis-peaked mode appropriately.
- test_center_zero_places_peak_at_corner_and_collapses_outer_triangles() — verifies peak placement at the grid corner when center is zero.
- test_opposing_sign_conflicts_leave_quadrants_inactive() — verifies quadrants with conflicting signs are left inactive.
- test_output_shape_includes_margin_cells() — verifies output grid shape includes the configured margin cells.
- test_active_quadrants_still_follow_standard_order() — verifies active quadrants are reported in the standard fixed order.

### test_pressure_map_widget.py
Tests `PressureMapWidget` (real PyQt6 widget, offscreen platform): readout text, sensor/peak markers, image upload caching, mirroring, intensity-level scaling, and multi-package (multi-sensor) display layout.
- test_no_data_clears_readout_and_markers() — clears the readout and markers when given no data.
- test_update_display_shows_force_readout_and_sensor_markers() — shows force readout text and renders sensor markers.
- test_update_display_skips_unchanged_image_upload() — skips re-uploading the heatmap image when unchanged.
- test_pressure_map_uses_combined_dark_axisless_overlay() — verifies dark background, hidden axes, and shear overlay styling.
- test_multiple_package_displays_use_grid_positions_and_distinct_colors() — verifies multi-package displays use grid positions and distinct colors.
- test_multiple_package_display_range_contains_full_circles() — verifies the view range contains all package circles fully.
- test_multiple_package_displays_skip_unchanged_image_uploads() — skips re-uploading unchanged images across multiple packages.
- test_grayscale_lookup_table_runs_from_black_to_white() — verifies the grayscale colormap LUT spans black to white.
- test_pressure_levels_use_fixed_max_intensity() — verifies a configured fixed max intensity is used for color levels.
- test_pressure_levels_use_fixed_max_intensity_for_tension() — verifies fixed max intensity also applies for tension (negative) data.
- test_pressure_levels_revert_to_normalized_when_max_intensity_is_zero() — verifies fallback to normalized levels when max intensity is zero.
- test_peak_markers_render_for_peaked_quadrants() — verifies peak markers render when quadrants are peaked.
- test_peak_markers_can_be_hidden() — verifies peak markers can be hidden via configuration.
- test_mirror_can_be_enabled_and_disabled() — verifies the mirror flag toggles correctly.
- test_mirror_flips_sensor_marker_positions() — verifies mirroring negates sensor marker X coordinates.
- test_mirror_flips_peak_marker_positions() — verifies mirroring negates peak marker X coordinates.
- test_configure_mirror_repaints_cached_single_display() — verifies toggling mirror repaints a cached single-sensor display.
- test_configure_mirror_repaints_cached_arrow_geometry() — verifies toggling mirror repaints cached shear arrow geometry.
- test_multi_package_mirror_flips_all_sensors() — verifies mirroring flips all package centers in multi-package mode.
- test_configure_mirror_repaints_cached_multi_package_display() — verifies toggling mirror repaints cached multi-package markers and centers.

### test_rosette_plotting.py
Tests rosette (RS) plot helpers: trailing moving average, per-channel baseline zeroing, and Y-axis range mode (adaptive vs. fixed).
- test_trailing_moving_average_preserves_length() — verifies the moving average output preserves input length.
- test_rosette_baseline_uses_latest_samples_per_channel() — verifies baseline capture averages the latest N samples per RS channel.
- test_rosette_y_axis_adaptive_uses_auto_range() — verifies adaptive mode enables plot auto-ranging.
- test_rosette_y_axis_fixed_uses_configured_min_max() — verifies fixed mode applies the configured min/max Y range.

### test_runtime_support.py
Tests vref voltage lookup, status-log trimming/scrolling, and Y-axis range application based on configuration.
- test_get_vref_voltage_maps_known_references() — verifies known reference labels map to correct voltages, with fallback for unknown.
- test_log_status_trims_to_max_lines_and_scrolls() — verifies status log trims to the max line count and scrolls to bottom.
- test_apply_y_axis_range_uses_configuration_voltage() — verifies Y-axis range uses the configured reference voltage.

### test_sensor_config.py
Tests sensor configuration mapping helpers, the `SensorConfigStore` (bundled + user overlay loading/saving), reverse-polarity backward compatibility, channel de-duplication, and mux-mapping RS-channel handling.
- test_position_channel_round_trip() — round-trips a position-to-channel mapping through conversion functions.
- test_position_channels_to_mapping_rejects_duplicates() — rejects a mapping with duplicate channel assignments.
- test_store_loads_bundled_and_local_configs() — loads and merges bundled and user-local sensor configuration files.
- test_reverse_polarity_is_backward_compatible_and_persisted() — verifies reverse-polarity flag defaults for legacy configs and persists correctly when set.
- test_unique_channels_in_order_preserves_first_occurrence() — verifies channel de-duplication preserves first-occurrence order (module-level function).
- test_mux_mapping_preserves_optional_rs_channels() — verifies RS channels are preserved through mux mapping normalization.
- test_mux_mapping_allows_duplicate_rs_channels() — verifies duplicate RS channel values are allowed through normalization.
- ChannelUtilsTests.test_unique_channels_in_order_preserves_first_occurrence_unittest() — same de-duplication check via a unittest.TestCase wrapper.

### test_sensor_panel.py
Tests `SensorPanelMixin` (real PyQt6 widget) syncing the array mux-mapping table editor back into the active sensor configuration and persisting it to disk.
- test_sync_active_sensor_config_from_editor_persists_pending_rs_mapping() — verifies edited RS-channel mapping is synced and saved to the user config file.
- test_sync_active_sensor_config_from_editor_allows_duplicate_rs_channels() — verifies duplicate RS-channel values entered in the editor are accepted and saved.

### test_serial_threads.py
Tests `SerialReaderThread.process_binary_data` resilience to corrupted binary packet headers and implausible timing fields, ensuring recovery to the next valid packet.
- test_false_large_header_does_not_block_following_valid_packet() — verifies an oversized false header is rejected and the following valid packet is still parsed.
- test_timing_sanity_rejection_recovers_to_following_valid_packet() — verifies a packet with implausible timing is rejected and parsing recovers on the next packet.

### test_settings_persistence.py
Tests save/load round trips for heatmap, shear, and spectrum tab settings files (JSON), including version fields, defaults, geometry/toggle restoration, and UI control restoration; also covers spectrum filter UI behaviors that don't require full reprocessing during capture.
- test_heatmap_save_last_and_load_last_round_trip() — verifies heatmap settings save and reload restores all control values, including `Sensor Size (mm)`, `Gap (mm)`, and `Point Tracking`.
- test_shear_save_last_and_load_last_round_trip() — verifies shear settings save and reload restores all control values.
- test_spectrum_save_last_and_load_last_round_trip() — verifies spectrum settings save and reload restores filter and display settings.
- test_spectrum_filter_cutoff_ui_matches_filter_type() — verifies cutoff label/visibility update correctly for lowpass/highpass/bandpass filter types.
- test_spectrum_live_filter_apply_skips_full_reprocess() — verifies applying a filter while capturing skips full reprocessing but still updates plots.

### test_shear_cop_processor.py
Tests `Legacy.data_processing.shear_cop_processor.ShearCoPProcessor`, the legacy shear center-of-pressure computation including shear-pair extraction and low-confidence quiet-signal detection.
- test_right_to_left_pair() — verifies shear pair extraction for a right-dominant signal pair.
- test_left_to_right_pair() — verifies shear pair extraction for a left-dominant signal pair.
- test_same_sign_pair_has_no_shear() — verifies same-sign sensor pairs produce zero shear.
- test_diagonal_combined_direction() — verifies a diagonal combined shear direction and angle from 4-sensor input.
- test_near_zero_is_low_confidence() — verifies near-zero/quiet input yields low confidence and zero center-of-pressure.

### test_shear_detector.py
Tests `ShearDetector`, the active shear detection and residual extraction logic used by the pressure-map/shear pipeline.
- test_pure_compression_has_no_shear() — verifies symmetric compression input has no detected shear.
- test_pure_horizontal_shear_points_right() — verifies a pure horizontal shear input points right with zero angle.
- test_pure_vertical_shear_points_up() — verifies a pure vertical shear input points up with a 90-degree angle.
- test_combined_shear_has_both_components() — verifies combined input produces nonzero horizontal and vertical shear components.
- test_horizontal_residual_pair_is_same_sign_or_zero() — verifies the left/right residual pair maintains consistent sign or zero.
- test_vertical_residual_pair_is_same_sign_or_zero() — verifies the top/bottom residual pair maintains consistent sign or zero.
- test_zero_inputs_have_zero_residuals() — verifies all-zero input yields zero residuals and no shear.

### test_shear_visualization_widget.py
Tests `ShearVisualizationWidget` (real PyQt6 widget, offscreen platform): arrow geometry visibility/direction/scaling/clamping, pen styling, and static sensor-position layout.
- test_zero_shear_hides_arrow() — verifies zero-shear input hides the arrow and shows "No Shear" readout.
- test_horizontal_shear_points_right() — verifies horizontal shear produces a rightward-pointing arrow.
- test_vertical_shear_points_up() — verifies vertical shear produces an upward-pointing arrow.
- test_diagonal_shear_points_upper_right() — verifies diagonal shear produces an equally-angled upper-right arrow.
- test_arrow_length_scales_with_magnitude() — verifies arrow length increases with shear magnitude.
- test_arrow_length_clamps_to_circle_radius() — verifies arrow length is clamped to the widget's circle radius.
- test_arrow_width_scales_with_magnitude() — verifies arrow width increases with shear magnitude.
- test_scaled_arrow_width_is_not_smaller_than_selected_base_width() — verifies scaled width never falls below the configured base width.
- test_arrow_shaft_pen_width_uses_scaled_width() — verifies the rendered pen width matches the scaled geometry width.
- test_arrow_width_does_not_scale_with_arrow_gain() — verifies arrow gain affects length but not width.
- test_arrow_shaft_ends_at_head_base_not_tip() — verifies the shaft line ends at the arrowhead base, not its tip.
- test_arrow_head_tip_points_away_from_body() — verifies the arrowhead polygon tip points away from its base.
- test_static_and_arrow_pens_are_cosmetic() — verifies pens are cosmetic (constant on-screen width regardless of zoom).
- test_static_layout_pen_widths_remain_visible() — verifies static layout pen widths meet the minimum visible width.
- test_sensor_positions_are_drawn_at_expected_coordinates() — verifies the 5 sensor markers are positioned at expected coordinates.

### test_signal_integration_panel.py
Tests the Signal Integration / Pressure Map tab (`PressureMapPanelMixin`, real PyQt6 widget): counts-to-voltage conversion, HPF/integration helper math, reverse-polarity handling, multi-package shear/force aggregation, settings save/load round trip, tooltips, and inner-tab (display vs. settings) refresh/pause behavior.
- test_counts_to_voltage_ignores_time_series_units() — verifies ADC counts convert to voltage independent of time-series unit settings.
- test_hpf_removes_constant_dc_bias_without_integration() — verifies the HPF removes a constant DC bias signal.
- test_integration_window_produces_moving_sum() — verifies the integration window produces the expected moving-sum sequence.
- test_prepare_integrated_series_applies_voltage_hpf_and_integration() — verifies the full prepare-series pipeline applies HPF then integration.
- test_prepare_integrated_series_applies_reverse_polarity_after_integration() — verifies reverse polarity is applied after integration, not before.
- test_prepare_integrated_series_uses_history_before_visible_start() — verifies history before the visible window start is used for correct integration continuity.
- test_shear_calibration_applies_threshold_then_gain() — verifies per-position calibration applies noise threshold before gain.
- test_package_specific_gains_override_default_processing_gains() — verifies package-specific sensor gains override the default gain table.
- test_array_package_plumbing_tracks_values_and_grid_positions() — verifies per-package values and array grid positions are tracked correctly.
- test_array_package_displays_are_built_per_complete_sensor_package() — verifies pressure-map package displays are built once each sensor package's values are complete.
- test_hidden_pressure_map_tab_skips_pressure_map_refresh() — verifies pressure-map computation is skipped while the tab/display is hidden.
- test_multi_package_force_mode_enabled_only_for_multiple_array_packages() — verifies multi-package force mode activates only with 2+ array packages.
- test_compute_package_total_force_series_returns_one_force_trace() — verifies a per-package total-force time series is computed correctly.
- test_compute_package_total_force_series_matches_pipeline_total_force() — verifies the batch total-force series matches per-sample pipeline computation.
- test_shear_settings_save_and_load_round_trip() — verifies shear/pressure-map tab settings save and reload restores all values, including package gains.
- test_pressure_map_tab_controls_expose_tooltips() — verifies key pressure-map tab controls expose descriptive tooltips.
- test_pressure_map_graph_toggle_defaults_off_and_hides_timeline() — verifies the timeline graph is hidden by default and shown when toggled.
- test_pressure_map_timeline_controls_follow_pzt_rs_mode() — verifies timeline controls show/hide RS-specific options based on PZT_RS mode.
- test_pressure_map_rosette_timeline_specs_filter_selected_rs_channels() — verifies RS1/RS2 checkboxes filter which rosette timeline specs are shown.
- test_pressure_map_rosette_axis_uses_fixed_min_max() — verifies the rosette timeline Y-axis uses the configured fixed min/max.
- test_pressure_map_settings_inner_tab_pauses_refresh_until_display_returns() — verifies plot refresh pauses while the settings inner-tab is active and resumes on return.
- test_pressure_map_inner_tabs_split_display_and_settings_content() — verifies the display and settings inner tabs contain the correct distinct widgets.
- test_settings_tab_activation_refreshes_package_gain_controls() — verifies switching to the settings inner-tab refreshes package gain controls.
- test_manual_single_package_shows_pressure_gain_controls() — verifies single (manual) package mode shows pressure gain controls keyed by position.
- test_switching_to_settings_stops_pending_signal_integration_timer() — verifies the update timer is stopped when switching to the settings inner-tab.

### test_signal_integration_processor.py
Tests `SignalIntegrationProcessorMixin`'s live display-buffer adapter: buffer capacity limiting, snapshot copying, high-rate decimation, and reverse-polarity sign flipping.
- test_signal_integration_refresh_rate_is_configured_for_pressure_map_tab() — verifies the configured refresh rate/interval constants for the pressure-map tab.
- test_display_buffers_are_limited_to_current_display_window_capacity() — verifies display buffers are capped to the configured display-window capacity.
- test_display_snapshot_can_copy_only_requested_visible_labels() — verifies snapshot retrieval can be limited to specific requested labels.
- test_high_rate_display_buffers_store_decimated_points_only() — verifies high-sample-rate input is decimated before storage.
- test_reverse_polarity_flips_display_buffer_values() — verifies reverse-polarity mode flips the sign of stored display values.

### test_signal_integrator.py
Tests `SignalIntegrator`: HPF-based DC rejection, AC-signal preservation above cutoff, moving-window integration behavior, streaming/batch equivalence, channel-to-position-label mapping, filter-state persistence across calls, and parameter updates.
- test_dc_removal_rejects_constant_bias_after_filter_settles() — verifies a constant DC bias is rejected to near zero after the HPF settles.
- test_ac_signal_above_cutoff_is_preserved() — verifies an AC signal above the cutoff frequency passes through with little attenuation.
- test_integration_window_keeps_single_impulse_for_exact_window_length() — verifies a single impulse remains nonzero for exactly the integration window length.
- test_integration_value_stabilizes_to_amplitude_times_window() — verifies a constant-amplitude signal's integrated value stabilizes to amplitude times window length.
- test_streaming_batches_match_single_call_output() — verifies processing in two streamed batches matches a single full-batch call.
- test_channel_map_routes_outputs_to_sensor_position_labels() — verifies a channel-to-position map routes outputs to the correct labeled keys.
- test_filter_state_persists_across_sequential_calls() — verifies HPF filter state persists correctly across sequential streamed calls.
- test_parameter_updates_rebuild_filter_and_resize_window() — verifies updating HPF cutoff/window size rebuilds the filter and resizes the integration window.
- test_multi_channel_histories_are_independent() — verifies per-channel integration histories do not interfere with each other.

### test_timing_display.py
Tests `TimingDisplayMixin`: human-readable time formatting and 555-mode charge/discharge time readout calculation from RC values.
- test_format_time_auto_uses_scaled_units() — verifies automatic time formatting picks µs/ms/s units appropriately.
- test_update_555_timing_readouts_formats_charge_and_discharge() — verifies charge/discharge time labels are computed and formatted per channel from RC values.
