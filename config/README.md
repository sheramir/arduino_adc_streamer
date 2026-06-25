# Config

This package holds the GUI's MCU-detection, ADC/555 configuration protocol, sensor-library
persistence, and channel-selection logic for the Arduino ADC Streamer application. The main
window mixes in `MCUDetectorMixin` and `ConfigurationMixin` from here to detect the connected
MCU, build and send the serial configuration handshake, resolve which channels map to which
display columns, and keep configure/start button state in sync with the live `ADCConfigurationState`.

## Files

### __init__.py

Package entry point that re-exports the public classes and helper functions from every module
in this folder so other packages can `from config import ...` without knowing internal file
layout.

- No functions/classes of its own; re-exports `MCUDetectorMixin`, `ConfigurationMixin`,
  `SensorConfigStore`, `ADCConfigurationService`, `ADCConfigurationRunner`, `MCUProfile`,
  `resolve_mcu_profile`, `MCUState` builders, `ConfigureButtonState`/`StartButtonState` builders,
  `ADCConfigurationSnapshot` helpers, `MCUViewState` builder, and `ADCConfigurationState`.

### adc_config_state.py

Defines the typed dataclass that holds the live ADC/555 configuration owned by the GUI
(channels, gain, reference, repeat, 555 RC component values, etc.) plus dict-like accessors used
throughout the codebase.

- `ADCConfigurationState` (dataclass) — typed container for channel selection, gain/reference/OSR,
  555 RC values, and array operation mode.
  - `copy()` — return a deep-ish copy with independent list fields.
  - `get(key, default)` — dict-style attribute getter with a default.
  - `__getitem__(key)` / `__setitem__(key, value)` — dict-style item access mapped to attributes.
  - `update(values)` — bulk-set attributes from a dict.
- `build_default_adc_config_state()` — construct an `ADCConfigurationState` with default values.

### adc_configuration_runner.py

Runs the ADC configuration retry loop on a background thread so the GUI thread never blocks on
serial I/O during `Configure`.

- `ADCConfigurationRunOutcome` (dataclass) — result of one configuration run, with a `success` property.
- `ADCConfigurationRunner` — owns the background worker thread.
  - `start(serial_port, request, max_attempts=3)` — launch a daemon thread that retries
    `send_config_with_verification` up to `max_attempts` times; returns False if already running.
  - `take_outcome()` — pop and return the completed outcome once the worker thread has finished, else None.
  - `is_running` (property) — whether a configuration attempt is currently in progress.

### adc_configuration_service.py

Owns the actual ADC/555 serial protocol sequencing (sending `channels`, `osr`, `gain`, `repeat`,
`ground`, `buffer`, PZT_RS routing commands, etc.) and verifying the Arduino's echoed status
against the request, independent of any GUI widget state.

- `ADCConfigurationRequest` (dataclass) — plain-data snapshot of everything needed to run one
  configuration attempt (MCU name, device mode, channels, 555 RC values, array mode, etc.).
- `ADCCommandResult` (dataclass) — result of a single command/parameter apply, with success flag,
  received echo value, and log messages.
- `ADCConfigurationResult` (dataclass) — overall result of `send_config_with_verification`,
  including resolved device mode, `ArduinoStatus`, normalized buffer size, and messages.
- `ADCConfigurationService` — runs protocol commands via an injected `send_command_and_wait_ack` callback.
  - `apply_555_parameter(command_name, value, ...)` — send one 555 RC parameter (rb/rk/cf/rxmax),
    optionally switching the device into PZT_RS mode first.
  - `estimate_555_pair_timeout_ms(...)` (static) — estimate a safe RC-charge/discharge timeout in
    ms from rb/rk/cf/rxmax values.
  - `send_config_with_verification(request)` — run the full ADC or 555 config sequence then verify
    the resulting Arduino status.
  - `verify_configuration_state(request, arduino_status, resolved_device_mode=None)` — re-check an
    already-applied configuration against the current `ArduinoStatus` without resending commands.
  - `_send_adc_config(request, arduino_status)` — send ADC-mode commands (ref/osr/gain/conv/samp/
    rate/channels/pztmuxes/rschannels/rb/rk/cf/rxmax/repeat/ground/buffer).
  - `_send_555_config(request, arduino_status, messages)` — send 555-mode commands (channels/
    repeat/buffer/rb/rk/cf/rxmax).
  - `_verify_configuration(request, arduino_status, resolved_device_mode)` — compare expected vs.
    actual channels/repeat and produce MISMATCH/match messages.
  - `_normalize_adc_buffer_size(request)` — clamp requested buffer size to firmware/protocol
    capacity limits based on channel count, repeat, and array mode.

### buffer_utils.py

Buffer-sizing helpers that compute how many ADC sweeps can be packed per serial block given baud
rate, USB packet size, and a target latency, and that clamp user-entered buffer sizes to what the
firmware buffer can hold.

- `calculate_optimal_sweeps_per_block(channel_count, repeat_count, baud_rate=BAUD_RATE, target_latency=TARGET_LATENCY_SEC, max_candidates=5)`
  — search and score candidate sweeps-per-block values by USB packet efficiency, latency
  utilization, and block size; return the top candidates.
- `validate_and_limit_sweeps_per_block(sweeps_per_block, channel_count, repeat_count)` — clamp a
  requested sweeps-per-block value to the maximum the firmware sample buffer can hold.

### channel_utils.py

Tiny shared helper for de-duplicating channel lists while preserving order.

- `unique_channels_in_order(channels)` — return the first-occurrence-unique version of a channel list.

### config_handlers.py

The largest module in the package: a mixin providing every `on_*_changed` GUI event handler,
the Arduino configure/verify workflow (`configure_arduino`, `check_config_completion`,
`verify_configuration`), array/PZT_RS channel-selection and routing resolution, display-channel
spec generation for the time-series and Rosette (RS) plots, channel checkbox list management, and
plot-update debouncing.

- `get_vref_voltage()` — map the configured reference string to a numeric voltage.
- `get_estimated_555_pair_timeout_ms()` / `get_estimated_pzt_rs_channel_timeout_ms()` — derive
  RC-based 555/PZT_RS timing estimates from current config.
- `uses_generic_555_tuning_defaults()` — True when rb/rk/cf/rxmax still match the stock defaults.
- `_apply_configure_button_state(state)` / `_apply_start_button_state(state)` — push a view-state
  dataclass onto the actual Configure/Start buttons.
- `is_array_mcu_mode()` / `is_array_pzt1_mode()` / `is_array_pzt_pzr_mode()` / `is_array_pzt_rs_mode()`
  — MCU-profile-derived mode queries.
- `get_allowed_channel_max()` — max manual channel index allowed for the current MCU.
- `get_supported_array_operation_modes()` / `get_selected_array_operation_mode()` /
  `update_array_mode_options()` — resolve and sync the PZT/PZR/PZT_RS mode combo box.
- `update_array_acquisition_inputs_visibility()` — show/hide PZT/PZR sequence inputs for Array MCUs.
- `_parse_sensor_numbers(text, prefix)` — parse a comma-separated sensor number list into IDs
  like `PZT1`.
- `get_effective_channels_selection(require_non_empty=False)` — resolve the active channel list
  from either the manual Channels Sequence box or PZT/PZR sensor selectors via the active sensor
  mux mapping.
- `get_rs_mux_channels_for_arduino_command()` / `get_pzt_muxes_for_arduino_command()` /
  `get_pzt_rs_sensor_routing_summary()` — resolve PZT_RS RS_MUX channel pairs, MG24 MUX sides, and
  a host-side routing summary string.
- `get_effective_channel_multiplier()` — physical samples produced per requested channel.
- `is_array_sensor_selection_mode()` — True when channel selection currently comes from Array sensor IDs.
- `get_array_selected_sensor_groups()` — ordered per-sensor channel groups with sequence positions.
- `get_sensor_package_groups(required_channels, channels=None)` — normalize channels into per-sensor-package groups.
- `get_channels_for_arduino_command()` — final channel list to send to firmware.
- `get_effective_samples_per_sweep(channels=None, repeat_count=None)` — physical sample width of one sweep.
- `_get_unique_channels_in_order(channels)` (static) — thin wrapper over `channel_utils.unique_channels_in_order`.
- `_get_grouped_manual_channel_labels(channels)` — build `Ch{n}-{placement}` labels when manual
  channels form complete sensor groups.
- `get_display_channel_specs(channels=None, repeat_count=None)` — build per-channel display specs
  (label, sample indices, color slot) for time-series plotting across manual/array/PZT1/PZT_RS modes.
- `get_rosette_display_channel_specs(channels=None, repeat_count=None)` — build RS-wire display
  specs for PZT_RS mode.
- `get_pzt_rs_rosette_value_scale()` — host-side ohms-per-wire-unit scale for PZT_RS payloads.
- `get_pzt_rs_rosette_sample_indices(channels=None, repeat_count=None)` — sorted sample-column
  indices that hold RS values.
- `scale_pzt_rs_rosette_samples_inplace(sample_matrix, channels=None, repeat_count=None, scale_override=None)`
  — convert RS payload words from wire units to ohms in place.
- `on_vref_changed` / `on_osr_changed` / `on_gain_changed` / `on_channels_changed` /
  `on_array_sensor_selection_changed` / `on_array_operation_mode_changed` / `on_ground_pin_changed`
  / `on_use_ground_changed` / `on_repeat_changed` / `on_conv_speed_changed` /
  `on_samp_speed_changed` / `on_sample_rate_changed` / `on_rb_changed` / `on_rk_changed` /
  `on_cf_changed` / `on_rxmax_changed` / `on_buffer_size_changed` / `on_yaxis_range_changed` /
  `on_yaxis_units_changed` / `on_use_range_changed` — GUI widget change handlers that update
  `self.config` and invalidate configuration validity.
- `_get_cf_farads_from_controls()` — read the Cf spinner+unit combo into farads.
- `on_apply_rb_clicked` / `on_apply_rk_clicked` / `on_apply_cf_clicked` / `on_apply_rxmax_clicked`
  — apply a single 555 RC parameter immediately via the configuration service.
- `_build_adc_configuration_request()` — assemble an `ADCConfigurationRequest` from current widget/config state.
- `_apply_configuration_result(result)` — apply a completed `ADCConfigurationResult` back onto GUI state.
- `_apply_555_parameter(command_name, value)` — shared helper used by the `on_apply_*_clicked` handlers.
- `configure_arduino()` — validate channel selection, build a request, and start the background
  `ADCConfigurationRunner`.
- `check_config_completion()` — timer callback that polls the runner for a finished outcome.
- `on_configuration_success()` / `on_configuration_failed()` — finalize Configure button state after a run.
- `verify_configuration()` — re-verify current `ArduinoStatus` against the active config without resending commands.
- `update_start_button_state()` — refresh Start button enabled/style/text from connection and config validity.
- `_reset_force_channel_checkbox_refs()` / `_should_show_force_channel_checkboxes()` /
  `_add_force_channel_checkboxes(start_index)` / `_set_force_channel_checkboxes_checked(checked)`
  — manage the optional Force X/Z overlay checkboxes appended after channel checkboxes.
- `update_channel_list()` — rebuild the channel checkbox grid from current display specs.
- `update_rosette_channel_list()` — rebuild the Rosette (RS) checkbox grid, preserving prior checked state.
- `select_all_channels()` / `deselect_all_channels()` / `select_all_rosette_channels()` /
  `deselect_all_rosette_channels()` — bulk checkbox toggles.
- `trigger_plot_update()` — restart the debounce timer that schedules a plot redraw.
- `reset_graph_view()` — leave full-view mode and return to the normal windowed plot view.

### config_snapshot.py

Normalizes the current widget values (or fallbacks from `self.config`) into a plain, immutable
`ADCConfigurationSnapshot` used to build the configuration request and to write values back to
`self.config`.

- `VREF_LABEL_TO_COMMAND` — dict mapping UI reference labels to firmware command strings.
- `ADCConfigurationSnapshot` (frozen dataclass) — normalized snapshot of all ADC/555 config fields.
  - `as_config_updates()` — return the snapshot as a plain dict suitable for `config.update(...)`.
  - `apply_to_config(config)` — apply the snapshot directly onto an `ADCConfigurationState`.
- `normalize_reference(current_reference, vref_label, use_vref_control)` — resolve the effective
  voltage reference command string.
- `normalize_gain(current_gain, gain_label)` — resolve gain from a combo label like `"2×"`.
- `build_adc_configuration_snapshot(...)` — build a full `ADCConfigurationSnapshot` from current
  vs. widget-provided values for every configurable field.

### config_view_state.py

Plain dataclasses and builder functions describing how the Configure/Start buttons should look
and behave for each lifecycle state, decoupled from the actual Qt widgets.

- `ConfigureButtonState` (frozen dataclass) — enabled flag, stylesheet, optional status bar message/timeout.
- `StartButtonState` (frozen dataclass) — enabled flag, stylesheet, button text.
- `build_configuring_state()` — state while a configuration attempt is in progress.
- `build_configuration_success_state()` — state after a configuration succeeds.
- `build_configuration_failed_state()` — state after a configuration fails.
- `build_start_ready_state()` — Start button state when ready to capture.
- `build_start_needs_config_state()` — Start button state when configuration is required first.
- `build_start_unavailable_state()` — Start button state when disconnected or already capturing.

### mcu_detector.py

Mixin that runs MCU auto-detection over the serial link and adapts every MCU-dependent GUI
control (ground pin, 555 controls, OSR options, Y-axis units, buffer max, etc.) based on the
resolved `MCUProfile`.

- `MCUDetectorMixin` — mixin class for MCU detection and GUI adaptation.
  - `_get_locked_ground_pin_for_mcu_name(mcu_name)` (static) — return the fixed ground pin for
    `Array_PZT_PZR1`/`Array_PZT_PZR1.7` boards, else None.
  - `_is_ground_default_mcu_name(mcu_name)` (classmethod) — True when the MCU has a locked
    default ground pin.
  - `is_555_analyzer_mode()` — True when `device_mode` is `'555'`.
  - `_maybe_apply_pzt_rs_tuning_defaults(profile)` — one-time application of PZT_RS-specific
    rb/rk/cf/rxmax defaults when still using generic 555 defaults.
  - `_apply_mcu_state(state)` — apply a resolved `MCUState` to `current_mcu`, the MCU label, and
    log it; reset PZT_PZR1 one-time defaults flag when the MCU identity changes.
  - `detect_mcu()` — send the `mcu` command over the session and apply the detected/unknown state.
  - `_apply_mcu_view_state(view_state)` — push an `MCUViewState` onto every dependent widget
    (ground controls, OSR combo, 555 controls, Y-axis lock, buffer max, Teensy controls, etc.).
  - `update_gui_for_mcu()` — resolve the current `MCUProfile`/`MCUViewState` and refresh all
    dependent GUI sections (array mode options, heatmap UI, acquisition inputs, PZT_RS tabs,
    pressure-map timeline controls, spectrum filter availability).

### mcu_profile.py

Pure-data resolution of MCU capability flags (array/dual/Teensy/555, supported array operation
modes, which controls to show, OSR options, buffer max, etc.) from the detected MCU name string.

- `MCUProfile` (frozen dataclass) — every resolved capability/visibility flag and UI default for
  a given MCU.
- `resolve_mcu_profile(mcu_name, selected_array_mode="PZT")` — classify the MCU name (array/dual/
  PZT_RS/Teensy/555) and return the matching `MCUProfile`.

### mcu_state.py

Plain MCU connection/detection state used to update the MCU label and log message after
detection, disconnection, or timeout.

- `MCUState` (frozen dataclass) — current MCU name, label text, log message, optional device mode.
- `build_detected_mcu_state(mcu_name)` — state for a successfully detected MCU.
- `build_unknown_mcu_state()` — state for a detection timeout/failure.
- `build_disconnected_mcu_state()` — state for a disconnected device.

### mcu_view_state.py

Translates a resolved `MCUProfile` into the flat `MCUViewState` consumed by `_apply_mcu_view_state`.

- `MCUViewState` (frozen dataclass) — visibility/label/option flags for every MCU-dependent widget.
- `build_mcu_view_state(profile)` — copy the relevant fields off an `MCUProfile` into an `MCUViewState`.

### sensor_config.py

Sensor-library schema, normalization, and persistence. Defines the on-disk JSON schema for named
5-channel sensor packages and optional 3x3 array-layout/MUX-mapping attachments, validates and
normalizes loaded/saved configs, and merges the bundled library with the user's local library
under `~/.adc_streamer/sensors/`.

- `SENSOR_POSITION_ORDER` / `SENSOR_POSITION_LABELS` — canonical T/R/C/L/B ordering and display labels.
- `ARRAY_ROWS` / `ARRAY_COLS` / `ARRAY_CELL_CHANNELS_MAX` — backward-compatible aliases for the
  array-layout constants in `constants.sensor_config`.
- `default_sensor_configuration()` — default channel-layout sensor config dict.
- `default_array_configuration()` — default empty array-layout attachment dict.
- `normalize_channel_sensor_map(channel_sensor_map)` — validate a 5-element T/R/C/L/B map.
- `normalize_sensor_config(config)` — validate/normalize a channel-layout-only sensor config.
- `_project_root()` / `_bundled_sensor_library_dir()` / `_default_bundled_sensor_configs_path()`
  — resolve the bundled `sensors_library/sensor_configurations.json` path with legacy fallbacks.
- `_read_sensor_configs_file(file_path)` — load and normalize all configs from a JSON file.
- `mapping_to_position_channels(channel_sensor_map)` / `position_channels_to_mapping(position_channels)`
  — convert between the list-of-labels map and a position->channel-number dict.
- `validate_sensor_id(sensor_id)` — validate `PZT<n>`/`PZR<n>` sensor ID format.
- `normalize_array_cell(cell_value)` — normalize/validate one array grid cell value.
- `normalize_array_layout(array_layout)` — validate the 3x3 cell grid structure.
- `normalize_mux_mapping(mux_mapping, allowed_sensors=None)` — validate per-sensor MUX/channel/RS-channel mappings.
- `get_sensors_from_array_layout(array_layout)` — collect all sensor IDs placed in the grid.
- `normalize_array_config(config)` — validate a full standalone array-layout config (requires MUX
  mapping for every placed sensor).
- `normalize_optional_array_config(config)` — validate an array attachment that may be empty.
- `normalize_combined_sensor_config(config)` — validate a sensor config combining channel map and
  optional array attachment; this is the canonical normalizer used for load/save.
- `SensorConfigStore` — load/save sensor configs merging bundled and user libraries.
  - `load()` — merge bundled (`sensors_library/sensor_configurations.json`) and user
    (`~/.adc_streamer/sensors/sensor_configurations.json`) configs, respecting deleted names and
    selection; returns `(configs, selected_name)`.
  - `save(configs, selected_name)` — write only the user's local overrides/additions plus
    deleted-bundled-names back to the user library file.

## Notes

- `config_handlers.py` is intentionally large because it is the single mixin that the main GUI
  class composes for nearly all configuration-related behavior; it depends heavily on `self`
  attributes (`self.config`, `self.channels_input`, etc.) defined by the host window class, not by
  this package.
- `mcu_detector.py`, `config_handlers.py`, and other mixins assume they are mixed into a class
  that also provides Qt widgets (`self.osr_combo`, `self.vref_label`, etc.); they are not usable standalone.
