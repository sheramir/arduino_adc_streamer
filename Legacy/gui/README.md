# gui (Legacy)

Archived PyQt6 GUI mixins for the older combined Display tab, 2D heatmap tab, and shear/CoP tab. These build the tabbed visualization UI (Time Series, 2D Heatmap, Shear, Display, Sensor, Spectrum), their settings panels, and the per-package visualization cards. Kept for reference and regression testing; the active application uses promoted copies of the heatmap GUI elsewhere in the repo (see root `README.md` and `Legacy/README.md`).

## Files

### display_panels.py

Mixin building the top-level tabbed visualization section (`visualization_tabs`) and the traditional time-series plotting tab, including the dual-axis (ADC/Force) plot widget, wheel-zoom guards during capture, and the visualization/display-mode controls (channel checkboxes, Y-axis range/units, window size, repeats display mode, baseline subtraction).

- `DisplayPanelsMixin.create_plot_section()` — builds the `QTabWidget` containing Time Series, 2D Heatmap, Shear, Display, Sensor, and Spectrum tabs.
- `DisplayPanelsMixin.create_timeseries_tab()` — builds the time-series tab: dual-axis plot widget, legends, timing section, and visualization controls.
- `DisplayPanelsMixin.update_force_viewbox()` — keeps the force-data right-axis viewbox geometry synced to the main plot viewbox.
- `DisplayPanelsMixin.create_visualization_controls()` — builds the "Visualization Controls" group: channel selection checkboxes, Y-axis range/units combos, window size spinner, reset/full view buttons, and repeats display mode (all repeats / average / subtract baseline / zero signals).
- `DisplayPanelsMixin.create_timing_section()` — builds the "Sampling Rate" group showing sample interval and block gap timing labels.

### heatmap_panel.py

Mixin building the 2D Heatmap tab and the combined Display tab (multi-package overlay of heatmaps and shear arrows), plus heatmap settings persistence (save/load/autosave JSON), per-sensor calibration UI, and PZT/PZR mode-specific settings filtering.

- `HeatmapPanelMixin._is_display_mirror_enabled()` — reports whether the Display tab "Mirror" checkbox is checked.
- `HeatmapPanelMixin._on_display_mirror_toggled(_checked=False)` — re-lays-out the Display tab and triggers a plot refresh when mirror mode is toggled.
- `HeatmapPanelMixin._get_heatmap_mode_key()` — returns `"pzr"` or `"pzt"` depending on whether 555-analyzer mode is active.
- `HeatmapPanelMixin._get_heatmap_setting_keys_for_mode(mode_key=None)` — returns the set of settings keys relevant to the given mode (PZT vs PZR have different parameter sets).
- `HeatmapPanelMixin._filter_heatmap_settings_for_mode(settings, mode_key=None)` — filters a settings dict down to only the keys valid for the current/given mode.
- `HeatmapPanelMixin._arrow_item_angle_from_vector(dx, dy)` — converts a 2D vector into a display angle in degrees for the shear arrow item.
- `HeatmapPanelMixin._arrow_head_tip_position(card, line_end_x, line_end_y, head_length_px)` — computes the pixel-accurate arrowhead tip position given the view's data/pixel scale.
- `HeatmapPanelMixin._get_channel_group_title(package_index)` — derives the heatmap card group-box title from array sensor selection or channel grouping.
- `HeatmapPanelMixin._get_sensor_id_for_package(package_index)` — resolves the sensor ID string for a heatmap package index.
- `HeatmapPanelMixin._get_visible_sensor_ids()` — lists the sensor IDs currently visible, from array selection or active package count.
- `HeatmapPanelMixin._clear_layout_recursive(layout)` — recursively removes and deletes all widgets/sublayouts from a layout.
- `HeatmapPanelMixin._create_numeric_line_edit(value, minimum, maximum, decimals=4)` — creates a validated numeric `QLineEdit` wired to autosave on edit.
- `HeatmapPanelMixin._get_numeric_input_value(widget, default)` — reads a float value from either a spin widget or a line edit, with fallback.
- `HeatmapPanelMixin._set_numeric_input_value(widget, value, decimals=4)` — writes a float value to either a spin widget or a line edit.
- `HeatmapPanelMixin._build_per_sensor_calibration_ui()` — dynamically rebuilds the per-sensor threshold/gain calibration rows based on currently visible sensors.
- `HeatmapPanelMixin.enable_heatmap_settings_autosave()` — turns on autosave-to-disk for heatmap settings changes.
- `HeatmapPanelMixin._get_visualization_mode_suffix()` — returns `"PZR"` or `"PZT"` for use in settings filenames.
- `HeatmapPanelMixin._get_last_heatmap_settings_path()` — returns the per-mode path under `~/.adc_streamer/heatmap/` for last-used settings.
- `HeatmapPanelMixin._serialize_heatmap_settings()` — packages current heatmap settings (mode-filtered) into a versioned dict for saving.
- `HeatmapPanelMixin._apply_heatmap_settings(settings)` — applies a loaded settings dict back onto the UI widgets (thresholds, calibration, scalar params, DC removal mode).
- `HeatmapPanelMixin.save_heatmap_settings_to_path(file_path, log_message=True)` — saves current heatmap settings as JSON to the given path.
- `HeatmapPanelMixin.load_heatmap_settings_from_path(file_path, log_message=True)` — loads and applies heatmap settings JSON from the given path.
- `HeatmapPanelMixin.save_last_heatmap_settings()` — autosaves current settings to the per-mode "last used" path if autosave is enabled.
- `HeatmapPanelMixin.load_last_heatmap_settings()` — loads the per-mode "last used" settings file if present.
- `HeatmapPanelMixin.on_save_heatmap_settings_clicked()` — handles the "Save Settings..." button, opening a file dialog.
- `HeatmapPanelMixin.on_load_heatmap_settings_clicked()` — handles the "Load Settings..." button, opening a file dialog.
- `HeatmapPanelMixin._connect_heatmap_settings_autosave()` — wires `valueChanged`/`currentIndexChanged` signals of settings widgets to autosave.
- `HeatmapPanelMixin._create_heatmap_card(package_index)` — builds one heatmap visualization card (plot, image item, shear arrow, CoP/intensity/confidence labels, debug labels).
- `HeatmapPanelMixin.create_heatmap_tab()` — assembles the full 2D Heatmap tab (capture button, display grid, settings panel scroll area).
- `HeatmapPanelMixin.create_heatmap_display()` — builds the "2D Pressure Heatmap" group containing one card per sensor package and the background overlay.
- `HeatmapPanelMixin._get_array_sensor_position_map()` — maps sensor IDs to (row, col) grid positions from the active array layout configuration.
- `HeatmapPanelMixin._get_display_package_positions(visible_count)` — computes card grid positions (with optional mirroring) for the Display tab, using array layout positions when available.
- `HeatmapPanelMixin._update_display_plot_view()` — recalculates and applies the Display tab plot's view range/limits based on current card positions.
- `HeatmapPanelMixin.update_visible_display_cards(visible_count)` — updates the Display tab's visible card count and refreshes the plot view.
- `HeatmapPanelMixin.create_display_tab()` — builds the combined Display tab: mirror checkbox, single shared plot with one image/arrow set per package.
- `HeatmapPanelMixin.update_display_tab(package_results, shear_results=None)` — updates the Display tab's images and shear arrows for each visible sensor package.
- `HeatmapPanelMixin._clear_heatmap_background_overlay()` — removes the sensor-position circle/marker overlay items from all heatmap cards.
- `HeatmapPanelMixin._refresh_heatmap_background_overlay(force=False)` — redraws the T/B/R/L/C sensor-position circle overlay on all heatmap cards.
- `HeatmapPanelMixin.update_visible_heatmap_cards(visible_count)` — shows/hides heatmap cards and updates their titles based on visible package count.
- `HeatmapPanelMixin.create_heatmap_settings()` — builds the full "Heatmap Settings" panel: save/load/zero actions, signal processing group, PZR parameters group, global/per-sensor calibration, and heatmap parameters.
- `HeatmapPanelMixin._on_dc_mode_changed(index)` — enables/disables the HPF cutoff spinner based on the selected DC removal mode.
- `HeatmapPanelMixin.get_heatmap_settings()` — reads all current heatmap settings widget values into a dict, including computed per-channel baselines and per-sensor calibration dict.
- `HeatmapPanelMixin.update_heatmap_ui_for_mode()` — shows/hides PZT vs PZR specific settings groups, rebuilds per-sensor calibration UI on mode/sensor changes, and reloads last-used settings on mode change.
- `HeatmapPanelMixin.update_heatmap_display(package_results, shear_results=None)` — updates each heatmap card's image, CoP/intensity/confidence/sensor-value labels, and shear arrow (PZT mode only).
- `HeatmapPanelMixin.show_heatmap_channel_warning(current_channels, required_channels="5")` — displays a warning label when the channel count doesn't match heatmap requirements.
- `HeatmapPanelMixin.clear_heatmap_channel_warning()` — clears the heatmap channel warning label.

### shear_panel.py

Mixin building the Shear/CoP visualization tab: per-package shear cards (arrow + CoP marker over a circular sensor layout), settings panel (integration window, conditioning/baseline alpha, deadband, per-sensor gain/baseline, Gaussian blob and arrow visualization parameters), and shear settings persistence.

- `ShearPanelMixin._get_shear_mode_suffix()` — returns `"PZR"`/`"PZT"` mode suffix, delegating to the heatmap panel's mode suffix when available.
- `ShearPanelMixin._get_channel_group_title(package_index)` — derives the shear card group-box title from array sensor selection or channel grouping (duplicate of the heatmap panel's helper, scoped to this mixin).
- `ShearPanelMixin.enable_shear_settings_autosave()` — turns on autosave-to-disk for shear settings changes.
- `ShearPanelMixin._get_last_shear_settings_path()` — returns the per-mode path under `~/.adc_streamer/shear/` for last-used settings.
- `ShearPanelMixin._serialize_shear_settings()` — packages current shear settings into a versioned dict for saving.
- `ShearPanelMixin._apply_shear_settings(settings)` — applies a loaded settings dict back onto the shear UI widgets (window, alphas, deadband, confidence ref, sigma, intensity/arrow scale, per-sensor gain/baseline).
- `ShearPanelMixin.save_shear_settings_to_path(file_path, log_message=True)` — saves current shear settings as JSON to the given path.
- `ShearPanelMixin.load_shear_settings_from_path(file_path, log_message=True)` — loads and applies shear settings JSON from the given path.
- `ShearPanelMixin.save_last_shear_settings()` — autosaves current settings to the per-mode "last used" path if autosave is enabled.
- `ShearPanelMixin.load_last_shear_settings()` — loads the per-mode "last used" settings file if present.
- `ShearPanelMixin.on_save_shear_settings_clicked()` — handles the "Save Settings..." button, opening a file dialog.
- `ShearPanelMixin.on_load_shear_settings_clicked()` — handles the "Load Settings..." button, opening a file dialog.
- `ShearPanelMixin._connect_shear_settings_autosave()` — wires `valueChanged` signals of shear settings widgets to autosave.
- `ShearPanelMixin._create_shear_card(package_index)` — builds one shear visualization card (plot, hidden heatmap image, arrow, CoP marker, magnitude/angle/CoP/confidence labels).
- `ShearPanelMixin.create_shear_tab()` — assembles the full Shear tab (capture button, display grid, settings panel scroll area).
- `ShearPanelMixin.create_shear_display()` — builds the "Shear / CoP Visualization" group containing one card per sensor package, the shared coordinate grid, and background overlay.
- `ShearPanelMixin._configure_shear_plot_view(card)` — sets a card's plot view range/limits to preserve aspect ratio around the shear view extent.
- `ShearPanelMixin._on_shear_view_resized(card_index)` — re-applies the plot view configuration when a card's view is resized.
- `ShearPanelMixin._arrow_item_angle_from_vector(dx, dy)` — converts a 2D vector into a display angle in degrees for the shear arrow item.
- `ShearPanelMixin._arrow_head_tip_position(card, line_end_x, line_end_y, head_length_px)` — computes the pixel-accurate arrowhead tip position given the view's data/pixel scale.
- `ShearPanelMixin._add_shear_background_overlay()` — draws the circular sensor-position overlay (T/B/R/L/C markers) on all shear cards.
- `ShearPanelMixin.refresh_shear_background_overlay()` — updates the overlay marker labels to reflect the current channel-to-sensor mapping.
- `ShearPanelMixin.update_visible_shear_cards(visible_count)` — shows/hides shear cards and updates their titles based on visible package count.
- `ShearPanelMixin.create_shear_settings()` — builds the full "Shear Settings" panel: save/load actions, signal processing group, per-sensor calibration (gain/baseline), and visualization group (sigma, intensity scale, arrow scale).
- `ShearPanelMixin.get_shear_settings()` — reads all current shear settings widget values into a dict, including per-sensor gain/baseline maps and the active channel-sensor map.
- `ShearPanelMixin.update_shear_display(package_results)` — updates each shear card's masked heatmap image, arrow, CoP marker, and magnitude/angle/CoP/confidence labels.
- `ShearPanelMixin.show_shear_channel_warning(current_channels, required_channels="5")` — displays a warning label when the channel count doesn't match shear requirements.
- `ShearPanelMixin.clear_shear_channel_warning()` — clears the shear channel warning label.

### __init__.py

Empty package marker file (no content).
