# GUI

Tab construction and UI panels for the Arduino ADC streamer desktop application. Each file is a PyQt6 mixin (combined into the main GUI window class) or a standalone custom widget, together building the application's tabs: Time Series, Rosette (RS), Pressure Map, Heatmap, Force Calibration, Spectrum, Analysis, and Sensor, plus shared file/status/control panels and small utility widgets.

## Files

### `__init__.py`

Package init that re-exports all GUI mixins/widgets used by the main window (`ControlPanelsMixin`, `DisplayPanelsMixin`, `FilePanelsMixin`, `ForceCalibrationPanelMixin`, `HeatmapPanelMixin`, `AnalysisPanelMixin`, `PressureMapPanelMixin`, `PressureMapWidget`, `SensorPanelMixin`, `SignalIntegrationPanelMixin`, `SpectrumPanelMixin`, `StatusLoggingMixin`).

- No functions/classes of its own — only imports and `__all__`.

### `custom_widgets.py`

Small custom Qt spin-box widgets that ignore mouse-wheel scrolling, used throughout the other panels to prevent accidental value changes while scrolling the page.

- `NonScrollableSpinBox` (QSpinBox) — integer spin box that ignores wheel events.
  - `wheelEvent(event)` — overridden to ignore mouse wheel scrolling.
- `NonScrollableDoubleSpinBox` (QDoubleSpinBox) — float spin box that ignores wheel events.
  - `wheelEvent(event)` — overridden to ignore mouse wheel scrolling.

### `status_logging.py`

Mixin owning the status text log widget shown at the bottom of the app.

- `StatusLoggingMixin`
  - `log_status(message)` — appends a timestamped message to the status text widget, trims the log to `MAX_LOG_LINES`, and scrolls to the bottom.

### `file_panels.py`

Mixin for the data-export ("Data Export") and status-message GUI sections: output directory/filename/notes inputs, sweep-range save options, save buttons, and the status log display.

- `FilePanelsMixin`
  - `browse_directory()` — opens a directory picker and sets the chosen path into the directory input.
  - `create_file_management_section()` — builds the "Data Export" group box (directory, filename, notes, save-range controls, Save Data/Save Plot Image buttons).
  - `create_status_section()` — builds the "Status & Messages" group box containing the read-only status text widget.

### `control_panels.py`

Mixin for serial connection, ADC configuration, acquisition settings, and run-control GUI sections.

- `ControlPanelsMixin`
  - `create_serial_section()` — builds the "Serial Connection" group: ADC/Force port combos, connect buttons, MCU label, array-mode (PZT/PZR) selector.
  - `create_adc_config_section()` — builds the "ADC Configuration" group: voltage reference, OSR, gain, Teensy conversion/sampling speed and rate, and 555-analyzer Rb/Rk/Cf/Rxmax parameter controls (most hidden by default, shown per MCU/mode).
  - `create_acquisition_section()` — builds the "Acquisition Settings" group: channel sequence input, PZT/PZR array sensor sequence inputs, ground pin, repeat count, buffer size (sweeps per block).
  - `create_run_control_section()` — builds the "Run Control" group: Configure/Start/Stop buttons, timed-run checkbox/spinbox, Clear Data button.

### `display_panels.py`

Mixin building the tabbed visualization area (`QTabWidget`) and the Time Series / Rosette time-series tabs plus their visualization controls; also owns the dual-axis (ADC/Force) plot widgets and their viewbox synchronization.

- `DisplayPanelsMixin`
  - `create_plot_section()` — builds `self.visualization_tabs` and adds Time Series, Rosette, Pressure Map, Heatmap, Force Calibration, Spectrum, and Sensor tabs (delegating tab content to the other mixins).
  - `create_timeseries_tab()` — builds the main Time Series tab: dual Y-axis (ADC + Force) `pyqtgraph` plot with wheel-zoom guarded during capture, legends, info/charge/discharge labels, timing section, visualization controls.
  - `create_rosette_timeseries_tab()` — builds the Rosette (RS) time-series tab: resistance/force dual-axis plot (one-directional X-range sync to avoid autorange feedback), info label, Rosette visualization controls.
  - `create_rosette_visualization_controls()` — builds the "Rosette Visualization Controls" group: channel checkboxes, baseline-subtract/zero-signals, moving-average, adaptive/fixed Y-range controls, X/Z force display checkboxes.
  - `update_pzt_rs_timeseries_tabs_visibility()` — shows/hides the Rosette tab and relabels the Time Series tab depending on whether PZT_RS array mode is active.
  - `update_force_viewbox()` — resizes the Time Series force viewbox to match the main plot viewbox geometry.
  - `update_rosette_force_viewbox()` — resizes the Rosette force viewbox to match the Rosette plot viewbox geometry and re-syncs its X range.
  - `_sync_rosette_force_x_range(*_args)` — pushes the Rosette plot's X range into the force viewbox one-directionally (avoids feedback loops).
  - `on_rosette_yaxis_range_changed(_value=None)` — shows/hides the fixed Y-range min/max controls and triggers a redraw.
  - `create_visualization_controls()` — builds the Time Series "Visualization Controls" group: channel checkboxes, Y-range/units, window size, Reset View/Full View buttons, repeats display mode (All/Average), baseline subtract/zero.
  - `create_timing_section()` — builds the "Sampling Rate" group showing sample-interval and block-gap timing labels.

### `force_calibration_panel.py`

Mixin for the Force Calibration tab: lets the user select a sensor family/number and signal source (raw piezo, heatmap, or pressure/shear), capture a live measurement window from streamed data, commit rows to a results table, and save/load/autosave calibration data to JSON.

- `ForceCalibrationPanelMixin`
  - `create_force_calibration_tab()` — builds the tab widget (family/number/source selectors, start/stop, clear/save/load buttons, status label, results table).
  - `init_force_calibration_state()` — initializes `force_calibration_state` defaults and enables autosave.
  - `_normalize_force_calibration_signal_source(source_key)` — validates/normalizes a signal-source string to "raw"/"heatmap"/"pressure_shear".
  - `_get_selected_force_calibration_signal_source()` — returns the active signal source from the combo box or stored state.
  - `_set_force_calibration_table_headers()` — sets the results table's column headers.
  - `_get_force_calibration_rows_for_current_family()` — returns calibration rows for the selected sensor family.
  - `_get_force_calibration_rows_for_current_view()` — returns the rows to display in the table.
  - `_sensor_values_to_calibration_fields(sensor_values)` — converts T/B/R/L/C sensor values into calibration row fields, zero-padding missing values.
  - `_create_live_calibration_row()` — builds a new zeroed `CalibrationRow` for the current family/number/source.
  - `_sync_active_row_with_latest_values()` — updates the in-progress table row from the live measurement window while capturing.
  - `_get_force_calibration_selected_package_index()` — returns the zero-based package index for the selected sensor number.
  - `_select_force_calibration_package_values(package_values_by_id)` — picks one package's values dict by selected index.
  - `_resolve_force_calibration_heatmap_sensor_values()` — computes per-package heatmap channel intensities for the selected package.
  - `_resolve_force_calibration_raw_sensor_values()` — averages the latest raw ADC sweep into T/B/R/L/C values for the selected package.
  - `_resolve_force_calibration_pressure_shear_sensor_values()` — computes integrated pressure/shear values and shear T-B/L-R for the selected package.
  - `_resolve_force_calibration_live_sensor_values()` — dispatches to the resolver matching the selected signal source.
  - `update_force_calibration_live_reading_from_selected_source()` — resolves live values and feeds them into the live reading.
  - `update_force_calibration_live_reading(sensor_values, shear_tb=None, shear_lr=None)` — pushes new values into the active measurement window while capturing.
  - `enable_force_calibration_start_stop(enabled)` — enables/disables Start/Stop based on force-sensor connection state.
  - `_on_force_calib_family_changed(family)` — handles sensor-family selection change.
  - `_on_force_calib_source_changed(_index)` — handles signal-source selection change.
  - `_on_force_calib_start_stop_clicked()` — Start/Stop Measure button handler.
  - `_start_force_calibration_measurement()` — begins a new measurement window and disables family/source/number controls.
  - `_stop_force_calibration_measurement()` — finalizes or discards the in-progress row and re-enables controls.
  - `_on_force_calib_table_refresh()` — repopulates the table widget from current rows.
  - `_on_force_calib_clear_clicked()` — clears all rows for the current family.
  - `_on_force_calib_save_clicked()` / `_on_force_calib_load_clicked()` — save/load calibration data via file dialogs.
  - `save_force_calibration_to_path(file_path, log_message=True)` / `load_force_calibration_from_path(file_path, log_message=True)` — serialize/deserialize all sensor families' calibration rows to/from JSON.
  - `save_force_calibration_last_state()` / `load_last_force_calibration_state()` — autosave/restore the "last used" calibration file.

### `analysis_panel.py`

Mixin for the **Analysis** tab: offline, read-only inspection of the latest in-memory capture or an exported CSV plus metadata JSON pair. The tab has Display and Settings sub-tabs, synchronized raw/integrated/shear-normal/force plots, channel and force-trace checklists, zoom and marker controls, selected-plot PNG export, and persistent Analysis settings.

- `AnalysisPanelMixin`
  - `create_analysis_tab()` — builds the nested Display/Settings UI, source controls, plot export controls, channel/force trace lists, four synchronized plot widgets, PZT force settings, and status labels.
  - `init_analysis_state()` / `load_last_analysis_settings()` / `save_last_analysis_settings()` — initialize and persist source mode, axis/zoom modes, overlay toggles, marker state, channel visibility, file paths, plot image selections, and PZT force settings/calibration.
  - `on_analysis_source_changed(...)`, `browse_analysis_csv()`, `browse_analysis_metadata_json()`, `load_latest_analysis_capture()`, `load_analysis_csv_json()` — source/file event handlers.
  - `refresh_analysis_display()` / `_render_analysis_prepared(...)` — prepare data via `data_processing.analysis_workbench`, update channel/force trace controls, and render raw, integrated, shear/normal, and force plots with synchronized X ranges.
  - `calculate_analysis_pzt_baseline()` — estimates per-channel Vmid/noise from the configured quiet window and shows rounded calibration text.
  - `save_analysis_plot_images()` — exports the selected Analysis plot widgets as PNG files, suffixing filenames when multiple plots are selected.
  - `update_analysis_availability(...)`, `reset_analysis_view()`, `on_analysis_zoom_changed(...)`, marker/mouse helpers — keep the offline tab disabled during live capture, reset plot state, apply zoom modes, and report nearest visible trace values.

### `signal_integration_panel.py`

Mixin building the **Pressure Map** tab (`PressureMapPanelMixin`, aliased as `SignalIntegrationPanelMixin` for backward compatibility). Reads the recent ADC buffer window, converts to voltage, applies a display-only high-pass filter and moving-sum integrator, then feeds per-position values into shear detection, normal-force calculation, and pressure-map generation, rendering an integrated-voltage timeline plot plus the `PressureMapWidget` visualization. In array layouts, it can combine adjacent packages into one array-level pressure surface with configurable package gap, gap contrast, and gap fade width. The Settings tab also provides a Color Scale group with selectable schemes, optional custom units/endpoints, range-count control, and a vertical presentation legend. Also owns settings persistence for all Pressure Map/shear/integration controls. This is the largest file in the folder (~2,600 lines).

- `PressureMapPanelMixin`
  - Tab construction: `create_signal_integration_tab()`, `on_pressure_map_inner_tab_changed(index)`, `update_pressure_map_timeline_controls()`, `_create_tooltip_label(...)`, `_create_shear_visualization_settings_group()`, `_create_pressure_map_settings_group()`, `_create_pressure_map_color_scale_settings_group()`, `_create_pressure_package_gain_settings_group()`, `_refresh_pressure_package_gain_controls(...)`, `_on_pressure_package_gain_changed(...)`, `update_pressure_map_color_scale_legend()`.
  - Timeline/source helpers: `_get_signal_integration_timeline_mode()`, `_get_signal_integration_rosette_selection()`, `_get_signal_integration_rosette_y_range()`, `_get_signal_integration_timeline_specs()`.
  - Settings persistence: `_get_last_shear_settings_path()`, `_serialize_shear_settings()`, `get_shear_settings()`, `save_shear_settings_to_path(...)`, `load_shear_settings_from_path(...)`, `save_last_shear_settings()`, `load_last_shear_settings()`, `on_save_shear_settings_clicked()`, `on_load_shear_settings_clicked()`, `_apply_shear_settings(settings)`, plus generic widget read/write helpers (`_settings_section`, `_spin_float`, `_spin_int`, `_check_bool`, `_combo_text`, `_set_spin_value`, `_set_check_value`, `_set_combo_value`) and per-package gain helpers (`_normalize_pressure_package_id`, `_default_pressure_sensor_gains`, `_normalize_pressure_package_sensor_gains`, `_pressure_sensor_gains_for_package`).
  - Settings-changed handlers: `on_signal_integration_settings_changed(...)`, `on_signal_integration_timeline_settings_changed(...)`, `on_signal_integration_show_graph_changed(...)`, `on_shear_processing_settings_changed(...)`, `on_shear_visualization_settings_changed(...)`, `on_pressure_map_settings_changed(...)`, `on_signal_integration_reset_clicked()`.
  - Main pipeline: `update_signal_integration_plot()` — core per-frame refresh; helper gates `_should_refresh_signal_integration_plot()`, `_is_pressure_map_display_tab_active()`, `_is_pressure_map_settings_tab_active()`, `_should_refresh_pressure_map_display()`, `_get_signal_integration_show_graph()`, `_apply_signal_integration_graph_visibility()`, `_hide_all_signal_integration_curves()`, `_clear_shear_visualization()`.
  - Per-package force series: `_record_signal_integration_package_value(...)`, `_get_signal_integration_package_id_for_display_spec(...)`, `_first_complete_signal_integration_package_values(...)`, `_get_array_sensor_grid_positions()`, `_get_signal_integration_package_layout()`, `_is_multi_package_force_mode(...)`, `_plot_signal_integration_package_force_series(...)`, `_compute_package_total_force_series(...)`.
  - Shear/pressure-map computation: `_update_shear_visualization_from_latest()`, `_update_pressure_map_from_latest()`, `_build_pressure_map_package_displays()`, `_build_pressure_map_array_result(...)`, `_calibrate_signal_integration_values_for_shear(...)`, `_get_shear_position_for_display_spec(...)`.
  - Signal processing: `_get_signal_integration_raw_snapshot()`, `_get_signal_integration_window_sweeps(...)`, `_get_signal_integration_processing_sweeps(...)`, `_prepare_signal_integration_integrated_series(...)`, `_convert_signal_integration_counts_to_voltage(...)`, `_apply_signal_integration_sensor_polarity(...)`, `_remove_signal_integration_dc_bias(...)`, `_integrate_signal_integration_voltage_samples(...)`, `_build_signal_integration_hpf_settings(...)`, `_estimate_signal_integration_series_rate_hz(...)`, `_subtract_signal_integration_visible_mean(...)`, `_record_signal_integration_filter_warning(...)`.
  - Plot curve management: `_get_or_create_signal_integration_curve(...)`, `_set_signal_integration_curve_data(...)`, `_plot_signal_integration_rosette_series(...)`, `_plot_signal_integration_repeat_series(...)`, `_plot_signal_integration_single_or_average_series(...)`, `_apply_signal_integration_axis_settings(...)`.
- `SignalIntegrationPanelMixin` — module-level alias of `PressureMapPanelMixin` (not a distinct class), kept for backward compatibility.

### `heatmap_panel.py`

Mixin (`HeatmapPanelMixin`) building the **Heatmap** tab: 2D pressure heatmap display (per-package cards plus a combined "Display" view), the heatmap settings panel (signal processing, PZR-mode parameters, per-sensor calibration, color maps, overlays, and array point-tracking geometry), and settings save/load/autosave. Supports both PZT mode and PZR (555-analyzer) mode.

- `HeatmapPanelMixin`
  - Class attribute `HEATMAP_COLOR_MAPS` — named RGBA color-stop tables ("Thermal", "Grayscale", "Viridis", "Magma").
  - Color maps: `_get_heatmap_color_map(name=None)`, `_get_selected_heatmap_colormap_name()`, `_on_heatmap_colormap_changed(...)`.
  - Mirror/orientation: `_is_display_mirror_enabled()`, `_on_display_mirror_toggled(...)`, `_on_heatmap_mirror_toggled(...)`.
  - Mode/settings keys: `_get_heatmap_mode_key()`, `_get_heatmap_setting_keys_for_mode(...)`, `_filter_heatmap_settings_for_mode(...)`, `_coerce_heatmap_threshold_scalar(...)`, `_load_global_noise_threshold_from_settings(...)`.
  - Channel/sensor naming: `_get_channel_group_title(...)`, `_get_sensor_id_for_package(...)`, `_get_visible_sensor_ids()`.
  - Generic UI helpers: `_clear_layout_recursive(layout)`, `_create_numeric_line_edit(...)`, `_get_numeric_input_value(...)`, `_set_numeric_input_value(...)`.
  - Point-tracking geometry/helpers: `_get_sensor_diameter_mm()`, `_get_point_tracking_gap_mm()`, `_get_display_units_per_mm()`, `_get_display_circle_diameter_value()`, `_get_display_cell_spacing_value()`, `_get_display_heatmap_size_value()`, `_is_point_tracking_enabled()`, `_on_heatmap_geometry_changed(...)`, `_on_heatmap_point_tracking_toggled(...)`, `_build_point_tracking_heatmap(...)`, `_render_point_tracking_display(...)`.
  - Per-sensor calibration UI: `_build_per_sensor_calibration_ui()`.
  - Settings persistence: `enable_heatmap_settings_autosave()`, `_get_visualization_mode_suffix()`, `_get_last_heatmap_settings_path()`, `_serialize_heatmap_settings()`, `_apply_heatmap_settings(settings)`, `save_heatmap_settings_to_path(...)`, `load_heatmap_settings_from_path(...)`, `save_last_heatmap_settings()`, `load_last_heatmap_settings()`, `on_save_heatmap_settings_clicked()`, `on_load_heatmap_settings_clicked()`, `_connect_heatmap_settings_autosave()`. The autosave path now includes display geometry (`sensor_size`, `gap_mm`) and the `point_tracking_enabled` toggle in the live tab.
  - Toggle handlers: `_on_heatmap_circle_overlay_toggled(...)`, `_on_heatmap_position_labels_toggled(...)`, `_on_heatmap_ellipse_shape_toggled(...)`, `_on_heatmap_remove_negatives_toggled(...)`.
  - Image item helpers: `_create_heatmap_image_item()`, `_set_heatmap_image(image_item, heatmap)`.
  - Card/widget construction: `_create_heatmap_card(package_index)`, `create_heatmap_tab()`, `create_heatmap_display()`, `_relayout_heatmap_cards(...)`, `_get_array_sensor_position_map()`, `_get_display_package_positions(...)`, `_get_display_package_centers(...)`, `_is_heatmap_position_labels_enabled()`, `_aspect_correct_display_bounds(...)`, `_set_display_plot_range(...)`, `_update_display_plot_view()`, `update_visible_display_cards(...)`, `_refresh_display_item_overlays()`, `create_display_tab()` (an alternate/earlier standalone Display tab variant), `update_display_tab(package_results, shear_results=None)`. In array mode, the active display now scales circles from physical sensor diameter and inter-sensor gap while keeping the outermost circles close to the frame.
  - Background overlay: `_clear_heatmap_background_overlay()`, `_refresh_heatmap_background_overlay(force=False)`, `update_visible_heatmap_cards(visible_count)`.
  - Settings panel: `create_heatmap_settings()` — Signal Processing, PZR Parameters, Noise Threshold, per-sensor calibration, and Heatmap Parameters groups; `_on_dc_mode_changed(index)`, `get_heatmap_settings()`. Heatmap Parameters now include physical `Sensor Size (mm)`, `Gap (mm)`, and `Point Tracking`.
  - Mode switching / live update: `update_heatmap_ui_for_mode()`, `update_heatmap_plot()` (dispatches to PZR or PZT processing pipelines defined in other mixins), `update_heatmap_display(...)`, `show_heatmap_channel_warning(...)`, `clear_heatmap_channel_warning()`.

### `pressure_map_widget.py`

Custom `QWidget` (`PressureMapWidget`) rendering the backend pressure grid with selectable Thermal, Grayscale, Viridis, and Magma schemes, sensor markers, a dotted package-boundary circle/square/hidden outline, peak-pressure markers, a live shear-force arrow, and a numeric force/shear readout. The image scale supports a configurable lower floor and maximum intensity; the panel supplies the presentation legend. Shear-arrow color automatically contrasts with red-heavy palettes. Supports an "array" mode that can either lay out several sensor packages side-by-side or render one combined array-level image with adjacent gap pressure. Used by the Pressure Map tab (`signal_integration_panel.py`).

- `PressureMapPackageDisplay` (frozen dataclass) — bundles one array package's normal-force/pressure/shear results with grid position, color, and calibrated T/R/L/C/B values; no methods.
- `_PressureMapImageCache` (dataclass) — internal cache of the last-rendered grid/levels/rect to skip redundant redraws; no methods.
- `PressureMapWidget(QWidget)`
  - `__init__(parent=None)` — builds the plot, image item, marker/arrow graphics items, default settings.
  - `configure_arrow(...)`, `configure_markers(...)`, `configure_package_boundary(...)`, `configure_intensity(...)`, `configure_noise_floor(...)`, `configure_color_scale(...)`, `configure_mirror(...)` — update visualization settings and refresh if changed.
  - `_refresh_cached_display()` — re-renders from the last known result(s).
  - `update_display(normal_force_result, pressure_result, shear_result=None)` — main single-package refresh entry point.
  - `update_package_displays(packages)` — renders multiple array packages in their grid cells.
  - `update_array_display(array_result, packages)` — renders one array-level pressure image plus package overlays.
  - `_clear_dynamic_items()` / `_clear_package_items()` — reset single/multi-package display state.
  - `_update_image(...)`, `_update_cached_image_item(...)`, `_pressure_levels(...)`, `_normalized_pressure_levels(...)`, `_mirror_x(x)`, `_grayscale_lookup_table()`, `_active_sensor_count(...)`, `_level_scale_for_active_sensors(...)` — heatmap image rendering and intensity-level computation.
  - `_update_boundary(...)`, `_update_sensor_markers(...)`, `_update_peak_markers(...)`, `_peak_marker_spots(...)`, `_sensor_positions_from_result(...)` — boundary/marker overlays for single-package mode.
  - `_update_readout(...)`, `_shear_readout_text(...)` — text readout formatting.
  - `_ensure_package_item_count(count)`, `_hide_unused_package_items(used_count)`, `_package_centers(packages)` — multi-package graphics item pooling and layout.
  - `_update_package_image(...)`, `_update_package_boundary(...)`, `_update_package_sensor_markers(...)`, `_update_package_peak_markers(...)`, `_update_package_shear_arrow(...)`, `_update_package_label(...)` — per-package overlay updates.
  - `_apply_arrow_to_items(...)`, `_hide_package_arrow(index)` — per-package arrow drawing.
  - `_set_package_ranges(...)`, `_update_package_readout(packages)`, `package_color_for_index(index)` — multi-package view range and summary readout.
  - `_initialize_dynamic_arrow()`, `_update_shear_arrow(shear_result)`, `calculate_arrow_geometry(shear_result)`, `_apply_arrow_geometry(...)`, `_build_arrow_head_polygon(...)`, `_calculate_arrow_head_base(...)`, `_calculate_arrow_head_half_width(...)`, `_hide_arrow()`, `_hidden_arrow_geometry()`, `_calculate_arrow_width(magnitude)` — single-package shear arrow geometry and rendering.

### `shear_visualization_widget.py`

Custom `QWidget` (`ShearVisualizationWidget`) used in the Force Calibration tab context: renders the static five-sensor piezo package layout (boundary circle, sensor squares, labels) once, then redraws only a dynamic arrow and readout for the latest detected shear vector.

- `ShearArrowGeometry` (frozen dataclass) — immutable computed arrow geometry (visibility, origin, tip, length, width, angle); no methods.
- `ShearVisualizationWidget(QWidget)`
  - `__init__(parent=None)` — initializes default settings, builds the plot/readout label, static layout, and dynamic arrow items.
  - `configure(...)` — updates arrow visualization settings (gain, max length, threshold, width scaling, color).
  - `update_display(shear_result)` — updates the arrow/readout for a new shear result, or clears to "No Data" state.
  - `calculate_arrow_geometry(shear_result)` — computes arrow geometry (threshold, gain, clamp, angle, width) without mutating widget state.
  - `_build_sensor_positions()` — builds center/left/right/top/bottom sensor coordinates in mm.
  - `_initialize_static_layout()` — creates the boundary circle, sensor squares, and labels.
  - `_initialize_dynamic_arrow()` — creates and hides the arrow line/head graphics items.
  - `_apply_arrow_geometry(geometry)` — applies computed geometry to the arrow graphics items.
  - `_build_arrow_head_polygon(geometry)`, `_calculate_arrow_head_base(geometry)`, `_calculate_arrow_head_half_width(geometry)` — arrowhead triangle geometry.
  - `_hide_arrow()`, `_hidden_arrow_geometry()` — hide/reset arrow state.
  - `_calculate_arrow_width(magnitude, length=None)` — computes arrow shaft pixel width, optionally scaled by magnitude.
  - `_label_y_offset(position)` — vertical label offset (inverted for the bottom sensor).

### `sensor_panel.py`

Mixin (`SensorPanelMixin`) for the **Sensor** tab: lets the user select, create, rename, delete, and edit named sensor configurations, each defining either a "Channel Layout" (5 channels mapped to T/L/C/R/B positions) or an "Array Layout" (3x3 grid of PZT/PZR sensors with MUX/channel assignments), plus a reverse-polarity flag.

- `SensorPanelMixin`
  - State/data access: `init_sensor_config_state()`, `_load_sensor_configs_from_disk()`, `save_sensor_configurations(log_message=False)`, `get_active_sensor_configuration()`, `get_active_channel_sensor_map()`, `is_active_sensor_reverse_polarity()`, `get_active_array_layout()`, `get_active_array_sensors()`.
  - UI construction: `create_sensor_tab()`, `_create_channel_layout_editor()`, `_create_array_layout_editor()`.
  - UI refresh/load: `_refresh_sensor_tab_ui()`, `_load_active_sensor_into_editor()`, `_load_channel_layout_into_editor(config)`, `_load_array_layout_into_editor(config)`, `_refresh_mux_table(mux_mapping)`, `_sync_mux_table_from_cells()`, `_set_array_mux_warning(message)`, `_update_array_mux_warning_label()`, `_update_sensor_mapping_preview()`.
  - Data collection/validation: `_collect_array_layout_editor_data()`, `_current_position_channels()`, `_build_sensor_config_update(...)`, `_build_normalized_sensor_config_from_editor()`.
  - Persistence helpers: `_set_active_sensor_config_name(name)`, `_replace_active_sensor_config(updated_config)`, `_save_sensor_mapping_from_editor()`, `_save_channel_layout_from_editor()`, `sync_active_sensor_config_from_editor(...)`, `_save_full_sensor_config_from_editor()`, `_save_array_layout_from_editor()`.
  - Event handlers: `on_sensor_config_selected(index)`, `on_sensor_name_edited()`, `on_sensor_position_spin_changed(new_value)`, `on_add_sensor_config_clicked()`, `on_delete_sensor_config_clicked()`, `on_sensor_type_changed(index)`, `on_sensor_reverse_polarity_changed(checked)`, `on_sensor_editor_tab_changed(index)`, `on_save_sensor_config_clicked()`, `on_array_cell_edited()`, `on_array_mux_table_item_changed(item)`, `on_array_channels_per_sensor_changed(value)`.
  - Cross-cutting refresh: `refresh_sensor_mapping_usage()` — resets dependent runtime state (CoP/intensity smoothing, heatmap/shear processors) after a mapping change.

### `spectrum_panel.py`

Mixin (`SpectrumPanelMixin`) for the **Spectrum** tab: FFT/Welch PSD controls, filter/notch controls, channel toggles, spectrum plot rendering with mouse cursor/marker interaction, settings persistence, and CSV/PNG export.

- `SpectrumPanelMixin`
  - Settings persistence: `_get_last_spectrum_settings_path()`, `_serialize_spectrum_settings()`, `_apply_spectrum_settings(settings)`, `save_spectrum_settings_to_path(...)`, `load_spectrum_settings_from_path(...)`, `save_last_spectrum_settings()`, `load_last_spectrum_settings()`, `_connect_spectrum_settings_autosave()`.
  - Tab construction: `create_spectrum_tab()` — control group (window/NFFT/mode/averaging/frequency range/scale/update rate/channel toggles), filtering group (main filter, order, cutoffs, 3 notch filters), plot display group.
  - UI behavior: `_on_spectrum_range_preset_changed(text)`, `_on_spectrum_mode_changed(mode_text)`, `on_spectrum_update_rate_changed(update_rate_hz)`, `on_spectrum_freeze_toggled(checked)`.
  - Filter UI: `_filter_main_type_to_code(text)`, `_filter_main_code_to_text(code)`, `_update_filter_cutoff_ui(...)`, `refresh_spectrum_filter_availability(log_message=False)`, `refresh_filter_action_buttons()`, `get_filter_settings_from_ui()`, `_apply_filter_widgets(settings)`, `on_apply_filter_clicked()`, `on_turn_off_filter_clicked()`, `on_reset_filter_defaults_clicked()`.
  - Settings retrieval: `get_spectrum_settings()`.
  - Status display: `show_spectrum_status(message)`, `hide_spectrum_status()`.
  - Rendering: `_to_db(linear_vals, mode)`, `update_spectrum_display(result)` — main per-frame plot/stat update.
  - Cursor/marker interaction: `_get_reference_series_for_cursor()`, `_on_spectrum_mouse_moved(evt)`, `_find_marker_point(target_freq)`, `_on_spectrum_mouse_clicked(event)`.
  - Export: `_build_spectrum_export_rows()`, `export_spectrum_csv()`, `save_spectrum_image()`.

## Notes / Discrepancies vs. root README

- `heatmap_panel.py` contains two display-tab builders: `create_heatmap_display()` (used by `create_heatmap_tab()`, the active "Display" sub-tab) and `create_display_tab()`/`update_display_tab()` (an alternate/earlier standalone Display tab variant). Both are present and referenced, but only `create_heatmap_display()` is wired into the active Heatmap tab construction — `create_display_tab()` appears to be a leftover/alternate implementation worth checking for dead-code removal.
- Array-wide single-point selection for Heatmap point tracking is computed by `data_processing/heatmap_point_tracker.py`, which lets the GUI renderer stay focused on layout and display concerns.
- `signal_integration_panel.py` defines `PressureMapPanelMixin` as the real class and keeps `SignalIntegrationPanelMixin` only as a module-level alias for backward compatibility. The file name and several helper names still reflect the older "Signal Integration" terminology even though the active tab label is "Pressure Map", so the module is intentionally mixed-name for now rather than fully renamed.
- All panel mixins assume they are composed into a single main-window class alongside sibling mixins and other modules (e.g. `data_processing`, `file_operations`, `constants`) — most methods reference `self.<attr>` provided elsewhere, so no file here is independently runnable.
