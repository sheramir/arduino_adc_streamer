from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout,
    QComboBox, QPushButton, QFileDialog, QCheckBox, QLineEdit,
    QScrollArea, QApplication, QSizePolicy, QTabWidget,
)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QDoubleValidator
import pyqtgraph as pg
import numpy as np
from pathlib import Path

from gui.custom_widgets import NonScrollableSpinBox as QSpinBox, NonScrollableDoubleSpinBox as QDoubleSpinBox

from constants.heatmap import (
    HEATMAP_WIDTH, HEATMAP_HEIGHT, HEATMAP_COORD_EXTENT, SENSOR_CALIBRATION, SENSOR_SIZE,
    POINT_TRACKING_ENABLED, POINT_TRACKING_GAP_MM,
    INTENSITY_SCALE, BLOB_SIGMA_X, BLOB_SIGMA_Y, SMOOTH_ALPHA,
    RMS_WINDOW_MS, SENSOR_NOISE_FLOOR, HEATMAP_DC_REMOVAL_MODE,
    HPF_CUTOFF_HZ, HEATMAP_CHANNEL_SENSOR_MAP, HEATMAP_THRESHOLD, ELLIPSE_SHAPE_ENABLED,
    HEATMAP_MIRROR_DISPLAY, REMOVE_NEGATIVES,
    CONFIDENCE_INTENSITY_REF, SIGMA_SPREAD_FACTOR,
    MAX_SENSOR_PACKAGES,
    R_HEATMAP_DELTA_THRESHOLD,
    R_HEATMAP_INTENSITY_MIN, R_HEATMAP_INTENSITY_MAX,
    R_HEATMAP_AXIS_ADAPT_STRENGTH, R_HEATMAP_MAP_SMOOTH_ALPHA,
    R_HEATMAP_COP_SMOOTH_ALPHA,
)
from file_operations.settings_persistence import load_settings_payload, save_settings_payload
from config.channel_utils import unique_channels_in_order
from data_processing.heatmap_point_tracker import resolve_point_tracking_target
from data_processing.heatmap_signal_processing import resolve_heatmap_blob_sigmas


class HeatmapPanelMixin:
    HEATMAP_COLOR_MAPS = {
        "Thermal": [
            (0, 0, 0, 0),
            (0, 32, 96, 255),
            (0, 180, 160, 255),
            (255, 220, 64, 255),
            (255, 48, 32, 255),
        ],
        "Grayscale": [
            (0, 0, 0, 0),
            (70, 70, 70, 255),
            (140, 140, 140, 255),
            (210, 210, 210, 255),
            (255, 255, 255, 255),
        ],
        "Viridis": [
            (0, 0, 0, 0),
            (68, 1, 84, 255),
            (59, 82, 139, 255),
            (33, 145, 140, 255),
            (253, 231, 37, 255),
        ],
        "Magma": [
            (0, 0, 0, 0),
            (80, 18, 123, 255),
            (182, 54, 121, 255),
            (251, 136, 97, 255),
            (252, 253, 191, 255),
        ],
    }

    def _get_heatmap_color_map(self, name: str | None = None):
        color_map_name = name or self._get_selected_heatmap_colormap_name()
        if color_map_name not in self.HEATMAP_COLOR_MAPS:
            color_map_name = "Thermal"
        if not hasattr(self, "_heatmap_color_maps"):
            self._heatmap_color_maps = {}
        if color_map_name not in self._heatmap_color_maps:
            self._heatmap_color_maps[color_map_name] = pg.ColorMap(
                [0.0, 0.18, 0.42, 0.72, 1.0],
                self.HEATMAP_COLOR_MAPS[color_map_name],
            )
        return self._heatmap_color_maps[color_map_name]

    def _get_selected_heatmap_colormap_name(self) -> str:
        combo = getattr(self, "heatmap_colormap_combo", None)
        if combo is None:
            return "Thermal"
        name = str(combo.currentText()).strip()
        return name if name in self.HEATMAP_COLOR_MAPS else "Thermal"

    def _on_heatmap_colormap_changed(self, _value=None):
        color_map = self._get_heatmap_color_map()
        for card in getattr(self, "heatmap_cards", []):
            card["image"].setColorMap(color_map)
        for item in getattr(self, "display_items", []):
            item["image"].setColorMap(color_map)
        if not getattr(self, "_heatmap_settings_loading", False):
            self.save_last_heatmap_settings()

    def _get_sensor_diameter_mm(self) -> float:
        widget = getattr(self, "sensor_size_spin", None)
        if widget is None:
            return max(1e-6, float(getattr(self, "display_circle_diameter", float(HEATMAP_WIDTH))))
        try:
            return max(1e-6, float(widget.value()))
        except (TypeError, ValueError, RuntimeError):
            return max(1e-6, float(SENSOR_SIZE))

    def _get_display_units_per_mm(self) -> float:
        sensor_diameter_mm = self._get_sensor_diameter_mm()
        reference_diameter = max(1e-6, float(getattr(self, "display_circle_diameter", float(HEATMAP_WIDTH))))
        return reference_diameter / sensor_diameter_mm

    def _get_point_tracking_gap_mm(self) -> float:
        widget = getattr(self, "heatmap_gap_spin", None)
        if widget is None:
            return 0.0
        try:
            return max(0.0, float(widget.value()))
        except (TypeError, ValueError, RuntimeError):
            return 0.0

    def _get_display_circle_diameter_value(self) -> float:
        if hasattr(self, "is_array_sensor_selection_mode") and self.is_array_sensor_selection_mode():
            return self._get_sensor_diameter_mm() * self._get_display_units_per_mm()
        return max(1e-6, float(getattr(self, "display_circle_diameter", float(HEATMAP_WIDTH))))

    def _get_display_cell_spacing_value(self) -> float:
        if hasattr(self, "is_array_sensor_selection_mode") and self.is_array_sensor_selection_mode():
            return (
                (self._get_sensor_diameter_mm() + self._get_point_tracking_gap_mm())
                * self._get_display_units_per_mm()
            )
        return max(1e-6, float(getattr(self, "display_cell_spacing", float(HEATMAP_WIDTH))))

    def _get_display_heatmap_size_value(self) -> float:
        if hasattr(self, "is_array_sensor_selection_mode") and self.is_array_sensor_selection_mode():
            return self._get_sensor_diameter_mm() * self._get_display_units_per_mm() * float(HEATMAP_COORD_EXTENT)
        return max(
            1e-6,
            float(getattr(self, "display_heatmap_size", float(HEATMAP_WIDTH) * float(HEATMAP_COORD_EXTENT))),
        )

    def _is_point_tracking_enabled(self) -> bool:
        checkbox = getattr(self, "heatmap_point_tracking_check", None)
        return bool(
            checkbox is not None
            and checkbox.isChecked()
            and hasattr(self, "is_array_sensor_selection_mode")
            and self.is_array_sensor_selection_mode()
        )

    def _on_heatmap_geometry_changed(self, _value=None):
        self._update_display_plot_view()
        self._refresh_display_item_overlays()
        if getattr(self, "_heatmap_settings_loading", False):
            return
        self.save_last_heatmap_settings()
        if hasattr(self, "trigger_heatmap_update"):
            self.trigger_heatmap_update()

    def _on_heatmap_point_tracking_toggled(self, _state=False):
        self._update_display_plot_view()
        self._refresh_display_item_overlays()
        if getattr(self, "_heatmap_settings_loading", False):
            return
        self.save_last_heatmap_settings()
        if hasattr(self, "trigger_heatmap_update"):
            self.trigger_heatmap_update()

    def _build_point_tracking_heatmap(self, intensity, settings):
        if not hasattr(self, "_tracking_heatmap_x_grid") or not hasattr(self, "_tracking_heatmap_y_grid"):
            y_coords = np.linspace(-HEATMAP_COORD_EXTENT, HEATMAP_COORD_EXTENT, HEATMAP_HEIGHT).reshape(-1, 1)
            x_coords = np.linspace(-HEATMAP_COORD_EXTENT, HEATMAP_COORD_EXTENT, HEATMAP_WIDTH).reshape(1, -1)
            self._tracking_heatmap_y_grid = np.tile(y_coords, (1, HEATMAP_WIDTH))
            self._tracking_heatmap_x_grid = np.tile(x_coords, (HEATMAP_HEIGHT, 1))

        sigma_x, sigma_y = resolve_heatmap_blob_sigmas(settings, BLOB_SIGMA_X, BLOB_SIGMA_Y)
        gaussian = np.exp(
            -(
                (self._tracking_heatmap_x_grid ** 2) / (2.0 * sigma_x ** 2)
                + (self._tracking_heatmap_y_grid ** 2) / (2.0 * sigma_y ** 2)
            )
        )
        amplitude = float(intensity) * float(settings.get("intensity_scale", INTENSITY_SCALE))
        return np.clip(gaussian * amplitude, 0.0, 1.0).astype(np.float32)

    def _is_display_mirror_enabled(self) -> bool:
        checkbox = getattr(self, "heatmap_mirror_check", None)
        if checkbox is None:
            checkbox = getattr(self, "display_mirror_check", None)
        return bool(checkbox is not None and checkbox.isChecked())

    def _on_display_mirror_toggled(self, _checked=False):
        self._update_display_plot_view()
        if hasattr(self, "trigger_plot_update"):
            self.trigger_plot_update()

    def _on_heatmap_mirror_toggled(self, _checked=False):
        self._update_display_plot_view()
        self._refresh_display_item_overlays()
        if not getattr(self, "_heatmap_settings_loading", False):
            self.save_last_heatmap_settings()
            if hasattr(self, "trigger_heatmap_update"):
                self.trigger_heatmap_update()

    def _get_heatmap_mode_key(self) -> str:
        is_pzr_mode = bool(hasattr(self, "is_555_analyzer_mode") and self.is_555_analyzer_mode())
        return "pzr" if is_pzr_mode else "pzt"

    def _get_heatmap_setting_keys_for_mode(self, mode_key: str | None = None) -> set[str]:
        mode = (mode_key or self._get_heatmap_mode_key()).lower()
        if mode == "pzr":
            return {
                "sensor_calibration",
                "sensor_size",
                "global_noise_threshold",
                "global_channel_thresholds",  # Backward compatibility for older settings files
                "intensity_scale",
                "blob_sigma_x",
                "blob_sigma_y",
                "ellipse_shape_enabled",
                "smooth_alpha",
                "delta_threshold",  # Backward compatibility for older settings files
                "cop_smooth_alpha",
                "intensity_min",
                "intensity_max",
                "axis_adapt_strength",
                "map_smooth_alpha",
                "sensor_calibration_dict",  # Per-sensor calibration indexed by sensor ID
                "show_circle_overlay",
                "show_position_labels",
                "mirror_display",
                "heatmap_colormap",
                "point_tracking_enabled",
                "gap_mm",
                "use_time_series_median_baseline",
            }
        return {
            "sensor_calibration",
            "sensor_noise_floor",
            "global_noise_threshold",
            "global_channel_thresholds",  # Backward compatibility for older settings files
            "sensor_size",
            "intensity_scale",
            "blob_sigma_x",
            "blob_sigma_y",
            "ellipse_shape_enabled",
            "smooth_alpha",
            "rms_window_ms",
            "dc_removal_mode",
            "hpf_cutoff_hz",
            "remove_negatives",
            "general_threshold",  # Changed from magnitude_threshold
            "sensor_calibration_dict",  # Per-sensor calibration indexed by sensor ID
            "show_circle_overlay",
            "show_position_labels",
            "mirror_display",
            "heatmap_colormap",
            "point_tracking_enabled",
            "gap_mm",
            "use_time_series_median_baseline",
        }

    def _filter_heatmap_settings_for_mode(self, settings: dict, mode_key: str | None = None) -> dict:
        allowed_keys = self._get_heatmap_setting_keys_for_mode(mode_key)
        return {key: value for key, value in settings.items() if key in allowed_keys}

    def _coerce_heatmap_threshold_scalar(self, values, default: float) -> float:
        try:
            if isinstance(values, (list, tuple, np.ndarray)):
                numeric_values = [float(value) for value in values]
                return float(np.mean(numeric_values)) if numeric_values else float(default)
            return float(values)
        except (TypeError, ValueError):
            return float(default)

    def _load_global_noise_threshold_from_settings(self, settings: dict, default: float) -> float:
        if "global_noise_threshold" in settings:
            return self._coerce_heatmap_threshold_scalar(settings["global_noise_threshold"], default)
        if "global_channel_thresholds" in settings:
            return self._coerce_heatmap_threshold_scalar(settings["global_channel_thresholds"], default)
        if "general_threshold" in settings:
            return self._coerce_heatmap_threshold_scalar(settings["general_threshold"], default)
        if "delta_threshold" in settings:
            return self._coerce_heatmap_threshold_scalar(settings["delta_threshold"], default)
        return float(default)
    
    def _get_channel_group_title(self, package_index):
        if self.is_array_sensor_selection_mode():
            selected = list(self.config.get('selected_array_sensors', [])) if hasattr(self, 'config') else []
            if package_index < len(selected):
                return str(selected[package_index])

        channels = self.config.get("channels", []) if hasattr(self, "config") else []
        unique_channels = unique_channels_in_order(channels)
        start = package_index * 5
        end = start + 5
        group_channels = unique_channels[start:end]
        if group_channels:
            return "CH " + ",".join(str(channel) for channel in group_channels)
        return f"CH Group {package_index + 1}"

    def _get_sensor_id_for_package(self, package_index: int) -> str:
        """Get the sensor ID for a given heatmap package index."""
        if self.is_array_sensor_selection_mode():
            selected = list(self.config.get('selected_array_sensors', [])) if hasattr(self, 'config') else []
            if package_index < len(selected):
                return str(selected[package_index])
        # Non-array mode: derive sensor ID from package index
        return f"Sensor{package_index + 1}"

    def _get_visible_sensor_ids(self) -> list[str]:
        """Get list of visible sensor IDs based on current heatmap display."""
        if self.is_array_sensor_selection_mode():
            return list(self.config.get('selected_array_sensors', [])) if hasattr(self, 'config') else []
        # Non-array: determine count from active heatmap cards
        count = getattr(self, 'active_sensor_package_count', 1)
        return [f"Sensor{i+1}" for i in range(count)]

    def _clear_layout_recursive(self, layout):
        """Recursively remove all items from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout_recursive(item.layout())

    def _create_numeric_line_edit(self, value, minimum, maximum, decimals=4):
        line_edit = QLineEdit(f"{float(value):.{decimals}f}")
        validator = QDoubleValidator(minimum, maximum, decimals, line_edit)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        line_edit.setValidator(validator)
        line_edit.setFixedWidth(84)
        line_edit.setMinimumHeight(28)
        line_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        line_edit.editingFinished.connect(self.save_last_heatmap_settings)
        return line_edit

    def _get_numeric_input_value(self, widget, default):
        try:
            if hasattr(widget, "value"):
                return float(widget.value())
            text = widget.text().strip()
            return float(text) if text else float(default)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return float(default)

    def _set_numeric_input_value(self, widget, value, decimals=4):
        if hasattr(widget, "setValue"):
            widget.setValue(float(value))
            return
        widget.setText(f"{float(value):.{decimals}f}")

    def _build_per_sensor_calibration_ui(self):
        """Dynamically build per-sensor calibration controls based on visible sensors."""
        # Disconnect old signals
        for sensor_id, spinboxes in self.sensor_calibration_spins.items():
            for spin_list in [spinboxes.get('threshold_spins', []), spinboxes.get('gain_spins', [])]:
                for spin in spin_list:
                    try:
                        signal = getattr(spin, "valueChanged", None) or getattr(spin, "editingFinished", None)
                        if signal is not None:
                            signal.disconnect()
                    except (TypeError, RuntimeError):
                        pass

        # Clear layout
        self._clear_layout_recursive(self.per_sensor_calibration_layout)

        self.sensor_calibration_spins = {}
        is_pzr_mode = self._get_heatmap_mode_key() == "pzr"
        sensor_ids = self._get_visible_sensor_ids()

        if not sensor_ids:
            label = QLabel("No sensors configured")
            self.per_sensor_calibration_layout.addWidget(label)
            return

        for sensor_id in sensor_ids:
            self.sensor_calibration_spins[sensor_id] = {'threshold_spins': [], 'gain_spins': []}

            # Sensor label
            self.per_sensor_calibration_layout.addWidget(QLabel(f"<b>{sensor_id}</b>"))

            # Threshold row - same pattern as Global Sensor Calibration
            threshold_row = QHBoxLayout()
            threshold_row.addWidget(QLabel(f"Extra Thresholds {'(%)' if is_pzr_mode else ''}  [T,B,R,L,C]:"))
            for name in ["T", "B", "R", "L", "C"]:
                spin = self._create_numeric_line_edit(0.0, 0.0, 1000.0 if is_pzr_mode else 1e6)
                self.sensor_calibration_spins[sensor_id]['threshold_spins'].append(spin)
                threshold_row.addWidget(QLabel(f"{name}:"))
                threshold_row.addWidget(spin)
            threshold_row.addStretch()
            self.per_sensor_calibration_layout.addLayout(threshold_row)

            # Gain row - same pattern as Global Sensor Calibration
            gain_row = QHBoxLayout()
            gain_row.addWidget(QLabel(f"Gains  [T,B,R,L,C]:"))
            for name in ["T", "B", "R", "L", "C"]:
                spin = self._create_numeric_line_edit(1.0, 0.0, 1000.0)
                self.sensor_calibration_spins[sensor_id]['gain_spins'].append(spin)
                gain_row.addWidget(QLabel(f"{name}:"))
                gain_row.addWidget(spin)
            gain_row.addStretch()
            self.per_sensor_calibration_layout.addLayout(gain_row)

        self.per_sensor_calibration_layout.addStretch()

    def enable_heatmap_settings_autosave(self):
        self._heatmap_autosave_enabled = True

    def _get_visualization_mode_suffix(self) -> str:
        return "PZR" if self._get_heatmap_mode_key() == "pzr" else "PZT"

    def _get_last_heatmap_settings_path(self):
        mode_suffix = self._get_visualization_mode_suffix()
        return Path.home() / ".adc_streamer" / "heatmap" / f"last_used_heatmap_settings_{mode_suffix}.json"

    def _serialize_heatmap_settings(self):
        mode_key = self._get_heatmap_mode_key()
        return {
            "version": 2,
            "mode": mode_key,
            "heatmap_settings": self._filter_heatmap_settings_for_mode(self.get_heatmap_settings(), mode_key),
        }

    def _apply_heatmap_settings(self, settings):
        if not settings:
            return False
        self._heatmap_settings_loading = True
        changed = False
        try:
            mode_settings = self._filter_heatmap_settings_for_mode(settings)
            if any(
                key in mode_settings
                for key in ("global_noise_threshold", "global_channel_thresholds", "general_threshold", "delta_threshold")
            ):
                default_threshold = (
                    R_HEATMAP_DELTA_THRESHOLD
                    if self._get_heatmap_mode_key() == "pzr"
                    else HEATMAP_THRESHOLD
                )
                self.global_noise_threshold_spin.setValue(
                    self._load_global_noise_threshold_from_settings(mode_settings, default_threshold)
                )
                changed = True
            
            # Load per-sensor calibration dict (indexed by sensor ID)
            if "sensor_calibration_dict" in mode_settings and isinstance(mode_settings["sensor_calibration_dict"], dict):
                calib_dict = mode_settings["sensor_calibration_dict"]
                for sensor_id, settings_data in calib_dict.items():
                    if sensor_id not in self.sensor_calibration_spins:
                        # Sensor not currently visible, skip
                        continue
                    
                    # Load thresholds
                    threshold_values = settings_data.get('thresholds', [])
                    for spin, value in zip(self.sensor_calibration_spins[sensor_id]['threshold_spins'], threshold_values):
                        try:
                            self._set_numeric_input_value(spin, value)
                        except (RuntimeError, AttributeError, TypeError):
                            pass  # Widget may have been deleted
                    
                    # Load gains
                    gain_values = settings_data.get('gains', [])
                    for spin, value in zip(self.sensor_calibration_spins[sensor_id]['gain_spins'], gain_values):
                        try:
                            self._set_numeric_input_value(spin, value)
                        except (RuntimeError, AttributeError, TypeError):
                            pass  # Widget may have been deleted
                    
                    changed = True
            
            scalar_map = [
                ("sensor_size", self.sensor_size_spin),
                ("gap_mm", getattr(self, "heatmap_gap_spin", None)),
                ("intensity_scale", self.intensity_scale_spin),
                ("blob_sigma_x", self.blob_sigma_x_spin),
                ("blob_sigma_y", self.blob_sigma_y_spin),
                ("smooth_alpha", self.smooth_alpha_spin),
                ("hpf_cutoff_hz", self.hpf_cutoff_spin),
                ("cop_smooth_alpha", getattr(self, "r555_cop_smooth_alpha_spin", None)),
                ("intensity_min", getattr(self, "r555_intensity_min_spin", None)),
                ("intensity_max", getattr(self, "r555_intensity_max_spin", None)),
                ("axis_adapt_strength", getattr(self, "r555_axis_adapt_spin", None)),
                ("map_smooth_alpha", getattr(self, "r555_map_smooth_alpha_spin", None)),
            ]
            for key, widget in scalar_map:
                if key in mode_settings and widget is not None:
                    widget.setValue(float(mode_settings[key]))
                    changed = True
            if "rms_window_ms" in mode_settings:
                self.rms_window_spin.setValue(int(round(float(mode_settings["rms_window_ms"]))))
                changed = True
            dc_mode = mode_settings.get("dc_removal_mode")
            if dc_mode == "bias":
                self.dc_removal_combo.setCurrentIndex(0)
                changed = True
            elif dc_mode == "highpass":
                self.dc_removal_combo.setCurrentIndex(1)
                changed = True
            if "use_time_series_median_baseline" in mode_settings and hasattr(self, "heatmap_use_median_baseline_check"):
                self.heatmap_use_median_baseline_check.setChecked(bool(mode_settings["use_time_series_median_baseline"]))
                changed = True
            if "show_circle_overlay" in mode_settings and hasattr(self, "show_heatmap_circle_check"):
                self.show_heatmap_circle_check.setChecked(bool(mode_settings["show_circle_overlay"]))
                changed = True
            if "ellipse_shape_enabled" in mode_settings and hasattr(self, "ellipse_shape_check"):
                self.ellipse_shape_check.setChecked(bool(mode_settings["ellipse_shape_enabled"]))
                changed = True
            if "remove_negatives" in mode_settings and hasattr(self, "remove_negatives_check"):
                self.remove_negatives_check.setChecked(bool(mode_settings["remove_negatives"]))
                changed = True
            if "show_position_labels" in mode_settings and hasattr(self, "show_heatmap_position_labels_check"):
                self.show_heatmap_position_labels_check.setChecked(bool(mode_settings["show_position_labels"]))
                changed = True
            if "mirror_display" in mode_settings and hasattr(self, "heatmap_mirror_check"):
                self.heatmap_mirror_check.setChecked(bool(mode_settings["mirror_display"]))
                changed = True
            if "heatmap_colormap" in mode_settings and hasattr(self, "heatmap_colormap_combo"):
                color_map_name = str(mode_settings["heatmap_colormap"]).strip()
                if color_map_name in self.HEATMAP_COLOR_MAPS:
                    self.heatmap_colormap_combo.setCurrentText(color_map_name)
                    changed = True
            if "point_tracking_enabled" in mode_settings and hasattr(self, "heatmap_point_tracking_check"):
                self.heatmap_point_tracking_check.setChecked(bool(mode_settings["point_tracking_enabled"]))
                changed = True
        finally:
            self._heatmap_settings_loading = False
        return changed

    def save_heatmap_settings_to_path(self, file_path, log_message=True):
        path = save_settings_payload(
            file_path,
            self._serialize_heatmap_settings(),
            log_callback=self.log_status if log_message else None,
            success_message="Saved heatmap settings: {path}",
        )
        return path

    def load_heatmap_settings_from_path(self, file_path, log_message=True):
        path, settings = load_settings_payload(file_path, payload_key="heatmap_settings")
        applied = self._apply_heatmap_settings(settings)
        if log_message:
            self.log_status(f"Loaded heatmap settings: {path}" if applied else f"Heatmap settings file loaded, no applicable fields: {path}")
        return applied

    def save_last_heatmap_settings(self):
        if not getattr(self, "_heatmap_autosave_enabled", False) or getattr(self, "_heatmap_settings_loading", False):
            return
        try:
            self.save_heatmap_settings_to_path(self._get_last_heatmap_settings_path(), log_message=False)
        except Exception as exc:
            self.log_status(f"Warning: could not save last heatmap settings: {exc}")

    def load_last_heatmap_settings(self):
        path = self._get_last_heatmap_settings_path()
        if not path.exists():
            return False
        try:
            return self.load_heatmap_settings_from_path(path, log_message=True)
        except Exception as exc:
            self.log_status(f"Warning: could not load last heatmap settings: {exc}")
            return False

    def on_save_heatmap_settings_clicked(self):
        default_dir = self._get_last_heatmap_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"heatmap_settings_{self._get_visualization_mode_suffix()}.json"
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Heatmap Settings", str(default_dir / default_name), "JSON Files (*.json);;All Files (*)")
        if file_path:
            self.save_heatmap_settings_to_path(file_path, log_message=True)

    def on_load_heatmap_settings_clicked(self):
        default_dir = self._get_last_heatmap_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Heatmap Settings", str(default_dir), "JSON Files (*.json);;All Files (*)")
        if file_path:
            self.load_heatmap_settings_from_path(file_path, log_message=True)
            self.save_last_heatmap_settings()

    def _connect_heatmap_settings_autosave(self):
        # Build list of widgets to connect, excluding those that might not exist
        widgets = [
            self.rms_window_spin, self.dc_removal_combo, self.hpf_cutoff_spin,
            self.sensor_size_spin, self.heatmap_gap_spin,
            self.intensity_scale_spin, self.blob_sigma_x_spin, self.blob_sigma_y_spin, self.smooth_alpha_spin,
            self.r555_cop_smooth_alpha_spin,
            self.r555_intensity_min_spin, self.r555_intensity_max_spin, self.r555_axis_adapt_spin,
            self.r555_map_smooth_alpha_spin,
            self.global_noise_threshold_spin,
        ]
        
        for widget in widgets:
            signal = getattr(widget, "valueChanged", None)
            if signal is not None:
                signal.connect(self.save_last_heatmap_settings)
        self.dc_removal_combo.currentIndexChanged.connect(self.save_last_heatmap_settings)
        self.heatmap_colormap_combo.currentTextChanged.connect(self._on_heatmap_colormap_changed)
        self.show_heatmap_position_labels_check.stateChanged.connect(self._on_heatmap_position_labels_toggled)
        self.ellipse_shape_check.stateChanged.connect(self._on_heatmap_ellipse_shape_toggled)
        self.heatmap_mirror_check.stateChanged.connect(self._on_heatmap_mirror_toggled)
        self.remove_negatives_check.stateChanged.connect(self._on_heatmap_remove_negatives_toggled)
        self.heatmap_use_median_baseline_check.stateChanged.connect(self._on_heatmap_median_baseline_toggled)
        self.sensor_size_spin.valueChanged.connect(self._on_heatmap_geometry_changed)
        self.heatmap_gap_spin.valueChanged.connect(self._on_heatmap_geometry_changed)
        self.heatmap_point_tracking_check.stateChanged.connect(self._on_heatmap_point_tracking_toggled)
        # Note: Per-sensor threshold and gain spinboxes are connected in _build_per_sensor_calibration_ui()

    def _on_heatmap_circle_overlay_toggled(self, _state=False):
        self._refresh_heatmap_background_overlay(force=True)
        if not getattr(self, "_heatmap_settings_loading", False):
            self.save_last_heatmap_settings()

    def _on_heatmap_position_labels_toggled(self, _state=False):
        self._refresh_display_item_overlays()
        if not getattr(self, "_heatmap_settings_loading", False):
            self.save_last_heatmap_settings()

    def _on_heatmap_ellipse_shape_toggled(self, _state=False):
        if getattr(self, "_heatmap_settings_loading", False):
            return
        self.save_last_heatmap_settings()
        if hasattr(self, "trigger_heatmap_update"):
            self.trigger_heatmap_update()

    def _on_heatmap_remove_negatives_toggled(self, _state=False):
        if getattr(self, "_heatmap_settings_loading", False):
            return
        self.save_last_heatmap_settings()
        if hasattr(self, "trigger_heatmap_update"):
            self.trigger_heatmap_update()

    def _on_heatmap_median_baseline_toggled(self, _state=False):
        if getattr(self, "_heatmap_settings_loading", False):
            return
        self.save_last_heatmap_settings()
        if hasattr(self, "trigger_heatmap_update"):
            self.trigger_heatmap_update()

    def _create_heatmap_image_item(self):
        return pg.ImageItem(axisOrder="row-major")

    def _set_heatmap_image(self, image_item, heatmap):
        image_item.setImage(heatmap, autoLevels=False, levels=(0, 1))

    def _create_heatmap_card(self, package_index):
        group = QGroupBox(self._get_channel_group_title(package_index))
        group.setStyleSheet("QGroupBox { background-color: black; color: white; } QLabel { color: white; }")
        layout = QVBoxLayout()
        plot_widget = pg.GraphicsLayoutWidget()
        plot_widget.setBackground("k")
        plot_widget.setMinimumSize(220, 220)
        plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plot = plot_widget.addPlot()
        plot.getViewBox().setBackgroundColor("k")
        plot.setAspectLocked(True, ratio=1.0)
        plot.invertY(True)
        plot.showAxis("left", False)
        plot.showAxis("bottom", False)
        plot.setMouseEnabled(x=False, y=False)
        image = self._create_heatmap_image_item()
        image.setColorMap(self._get_heatmap_color_map())
        self._set_heatmap_image(image, np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32))
        plot.addItem(image)
        row1 = QHBoxLayout()
        labels = {}
        for key, text in [("cop_x", "X: 0.000"), ("cop_y", "Y: 0.000"), ("intensity", "I: 0.0"), ("confidence", "Q: 0.00")]:
            label = QLabel(text)
            label.setStyleSheet("font-weight: bold; font-family: monospace;")
            labels[key] = label
            row1.addWidget(label)
        row1.addStretch()
        row2 = QHBoxLayout()
        sensor_labels = []
        for name in ["T", "B", "R", "L", "C"]:
            label = QLabel(f"{name}: 0")
            label.setStyleSheet("font-family: monospace;")
            sensor_labels.append(label)
            row2.addWidget(label)
        row2.addStretch()
        row3 = QHBoxLayout()
        debug_rd = QLabel("R/DR: -")
        debug_a = QLabel("A: -")
        debug_xyiq = QLabel("x/y/I/Q: -")
        for label in [debug_rd, debug_a, debug_xyiq]:
            label.setStyleSheet("font-family: monospace; font-size: 11px;")
            row3.addWidget(label)
        row3.addStretch()
        layout.addWidget(plot_widget)
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addLayout(row3)
        group.setLayout(layout)
        return {
            "group": group, "plot": plot, "image": image, "labels": labels, "sensor_labels": sensor_labels,
            "debug_rd": debug_rd, "debug_a": debug_a, "debug_xyiq": debug_xyiq, "circle": None, "markers": [], "marker_labels": [],
        }

    def create_heatmap_tab(self):
        heatmap_widget = QWidget()
        layout = QVBoxLayout(heatmap_widget)
        self.heatmap_inner_tabs = QTabWidget()
        self.heatmap_inner_tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.heatmap_inner_tabs)

        display_tab = QScrollArea()
        display_tab.setWidgetResizable(True)
        display_tab.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        display_tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        display_content = QWidget()
        display_content.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        display_content.setStyleSheet("background-color: black;")
        display_layout = QVBoxLayout(display_content)
        display = self.create_heatmap_display()
        screen = QApplication.primaryScreen()
        if screen is not None:
            height = screen.availableGeometry().height()
            display.setMinimumHeight(max(320, int(height * 0.48)))
            display.setMaximumHeight(max(320, int(height * 0.88)))
        display_layout.addWidget(display)
        display_tab.setWidget(display_content)
        self.heatmap_inner_tabs.addTab(display_tab, "Display")
        self.heatmap_display_tab_index = 0

        settings_tab = QScrollArea()
        settings_tab.setWidgetResizable(True)
        settings_tab.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        settings_tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        settings_panel = self.create_heatmap_settings()
        settings_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        settings_tab.setWidget(settings_panel)
        self.heatmap_inner_tabs.addTab(settings_tab, "Settings")
        self.heatmap_settings_tab_index = 1
        self.update_heatmap_ui_for_mode()
        return heatmap_widget

    def create_heatmap_display(self):
        group = QGroupBox("2D Pressure Heatmap")
        group.setStyleSheet("QGroupBox { background-color: black; color: white; } QLabel { color: white; }")
        layout = QVBoxLayout()
        self.heatmap_cards_grid = None
        self.heatmap_cards = []
        self.display_plot_widget = pg.GraphicsLayoutWidget()
        self.display_plot_widget.setBackground("k")
        self.display_plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.display_plot = self.display_plot_widget.addPlot()
        self.display_plot.getViewBox().setBackgroundColor("k")
        self.display_plot.setAspectLocked(True, ratio=1.0)
        self.display_plot.invertY(True)
        self.display_plot.showAxis("left", False)
        self.display_plot.showAxis("bottom", False)
        self.display_plot.setMouseEnabled(x=False, y=False)

        self.display_circle_diameter = 240.0
        self.display_cell_spacing = 240.0
        self.display_heatmap_size = self.display_circle_diameter * float(HEATMAP_COORD_EXTENT)
        self.display_canvas_extra_margin = 0.0
        self.display_items = []
        for _ in range(MAX_SENSOR_PACKAGES):
            image = self._create_heatmap_image_item()
            image.setColorMap(self._get_heatmap_color_map())
            self._set_heatmap_image(image, np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32))
            image.setVisible(False)
            self.display_plot.addItem(image)

            circle = pg.PlotDataItem([], [], pen=pg.mkPen((230, 230, 230, 190), width=2))
            circle.setZValue(5)
            circle.setVisible(False)
            self.display_plot.addItem(circle)

            label = pg.TextItem(anchor=(0.5, 0.5))
            label.setZValue(6)
            label.setVisible(False)
            self.display_plot.addItem(label)

            self.display_items.append({
                "image": image,
                "circle": circle,
                "label": label,
            })

        layout.addWidget(self.display_plot_widget)
        self.heatmap_status_label = QLabel("")
        self.heatmap_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.heatmap_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.heatmap_status_label)
        group.setLayout(layout)
        self.heatmap_overlay_mode = None
        self._refresh_heatmap_background_overlay(force=True)
        self.update_visible_heatmap_cards(1)
        return group

    def _relayout_heatmap_cards(self, visible_count):
        grid = getattr(self, "heatmap_cards_grid", None)
        cards = getattr(self, "heatmap_cards", [])
        if grid is None or not cards:
            return

        visible_count = max(0, min(int(visible_count), len(cards)))
        positions, _, _ = self._get_display_package_positions(visible_count)
        if not positions:
            positions = [(index // 2, index % 2) for index in range(visible_count)]

        if positions:
            min_row = min(row for row, _col in positions)
            min_col = min(col for _row, col in positions)
            positions = [(row - min_row, col - min_col) for row, col in positions]

        for index, card in enumerate(cards):
            grid.removeWidget(card["group"])
            if index < visible_count and index < len(positions):
                row, col = positions[index]
            else:
                row, col = index // 2, index % 2
            grid.addWidget(card["group"], int(row), int(col))

    def _get_array_sensor_position_map(self):
        if not (hasattr(self, "is_array_sensor_selection_mode") and self.is_array_sensor_selection_mode()):
            return {}
        if not hasattr(self, "get_active_sensor_configuration"):
            return {}

        config = self.get_active_sensor_configuration()
        if not isinstance(config, dict):
            return {}

        array_layout = config.get("array_layout", {})
        cells = array_layout.get("cells", []) if isinstance(array_layout, dict) else []
        if not isinstance(cells, list):
            return {}

        position_map = {}
        for row_idx, row in enumerate(cells):
            if not isinstance(row, list):
                continue
            for col_idx, value in enumerate(row):
                if value is None:
                    continue
                sensor_id = str(value).strip().upper()
                if sensor_id:
                    position_map[sensor_id] = (row_idx, col_idx)
        return position_map

    def _get_display_package_positions(self, visible_count):
        visible_count = max(0, int(visible_count))
        if visible_count == 0:
            return [], 1, 1

        if hasattr(self, "is_array_sensor_selection_mode") and self.is_array_sensor_selection_mode():
            selected = list(self.config.get("selected_array_sensors", [])) if hasattr(self, "config") else []
            position_map = self._get_array_sensor_position_map()
            positions = []
            max_row = 0
            max_col = 0
            for index in range(min(visible_count, len(selected))):
                sensor_id = str(selected[index]).strip().upper()
                if sensor_id in position_map:
                    row, col = position_map[sensor_id]
                else:
                    row, col = index // 2, index % 2
                positions.append((row, col))
                max_row = max(max_row, row)
                max_col = max(max_col, col)

            if positions and self._is_display_mirror_enabled():
                positions = [(row, max_col - col) for row, col in positions]

            if positions:
                return positions, max_row + 1, max_col + 1

        cols = min(2, visible_count)
        rows = int(np.ceil(visible_count / max(cols, 1)))
        positions = [(index // cols, index % cols) for index in range(visible_count)]
        if self._is_display_mirror_enabled() and cols > 0:
            positions = [(row, (cols - 1) - col) for row, col in positions]
        return positions, max(rows, 1), max(cols, 1)

    def _get_display_package_centers(self, visible_count):
        positions, _, _ = self._get_display_package_positions(visible_count)
        if not positions:
            return []

        spacing = self._get_display_cell_spacing_value()
        row_values = [row for row, _col in positions]
        col_values = [col for _row, col in positions]
        row_midpoint = (min(row_values) + max(row_values)) / 2.0
        col_midpoint = (min(col_values) + max(col_values)) / 2.0
        return [
            ((float(col) - col_midpoint) * spacing, (float(row) - row_midpoint) * spacing)
            for row, col in positions
        ]

    def _get_visible_array_display_context(self, visible_count):
        positions, _, _ = self._get_display_package_positions(visible_count)
        centers = self._get_display_package_centers(visible_count)
        limit = min(visible_count, len(positions), len(centers))
        sensor_ids = [self._get_sensor_id_for_package(index) for index in range(limit)]
        return sensor_ids, positions[:limit], centers[:limit]

    def _is_heatmap_position_labels_enabled(self):
        checkbox = getattr(self, "show_heatmap_position_labels_check", None)
        return bool(checkbox is not None and checkbox.isChecked())

    def _aspect_correct_display_bounds(
        self,
        x_min,
        x_max,
        y_min,
        y_max,
        viewport_width=None,
        viewport_height=None,
    ):
        x_min = float(x_min)
        x_max = float(x_max)
        y_min = float(y_min)
        y_max = float(y_max)
        x_span = max(1.0, x_max - x_min)
        y_span = max(1.0, y_max - y_min)

        width = float(viewport_width or 0.0)
        height = float(viewport_height or 0.0)
        if width <= 0.0 or height <= 0.0:
            return x_min, x_max, y_min, y_max

        target_aspect = width / height
        content_aspect = x_span / y_span
        center_x = (x_min + x_max) / 2.0
        center_y = (y_min + y_max) / 2.0

        if content_aspect < target_aspect:
            x_span = y_span * target_aspect
        else:
            y_span = x_span / target_aspect

        return (
            center_x - x_span / 2.0,
            center_x + x_span / 2.0,
            center_y - y_span / 2.0,
            center_y + y_span / 2.0,
        )

    def _set_display_plot_range(self, x_min, x_max, y_min, y_max):
        view_box = self.display_plot.getViewBox()
        view_box.setAspectLocked(True, ratio=1.0)
        self.display_plot.setAspectLocked(True, ratio=1.0)
        view_box.setLimits(xMin=-1e307, xMax=1e307, yMin=-1e307, yMax=1e307)

        x_min, x_max, y_min, y_max = self._aspect_correct_display_bounds(
            x_min,
            x_max,
            y_min,
            y_max,
            viewport_width=view_box.width(),
            viewport_height=view_box.height(),
        )
        view_box.setRange(
            xRange=(x_min, x_max),
            yRange=(y_min, y_max),
            padding=0.0,
            disableAutoRange=True,
        )

    def _update_display_plot_view(self):
        if not hasattr(self, "display_plot"):
            return

        visible_count = getattr(self, "display_visible_count", 1)
        centers = self._get_display_package_centers(visible_count)
        heatmap_size = self._get_display_heatmap_size_value()
        extra_margin = float(getattr(self, "display_canvas_extra_margin", 0.0))
        if not centers:
            half = heatmap_size * 0.5 + 40.0
            self._set_display_plot_range(-half, half, -half, half)
            return

        x_centers = [center_x for center_x, _center_y in centers]
        y_centers = [center_y for _center_x, center_y in centers]
        content_half = heatmap_size * 0.5

        if hasattr(self, "is_array_sensor_selection_mode") and self.is_array_sensor_selection_mode():
            margin = max(0.0, extra_margin)
        else:
            margin = max(8.0, heatmap_size * 0.04 + extra_margin)

        x_min = min(x_centers) - content_half - margin
        x_max = max(x_centers) + content_half + margin
        y_min = min(y_centers) - content_half - margin
        y_max = max(y_centers) + content_half + margin

        self._set_display_plot_range(x_min, x_max, y_min, y_max)

    def update_visible_display_cards(self, visible_count):
        self.display_visible_count = max(0, int(visible_count))
        self._update_display_plot_view()
        self._refresh_display_item_overlays()

    def _refresh_display_item_overlays(self):
        visible_count = max(0, int(getattr(self, "display_visible_count", 0)))
        centers = self._get_display_package_centers(visible_count)
        circle_diameter = self._get_display_circle_diameter_value()
        radius = circle_diameter * 0.5
        theta = np.linspace(0.0, 2.0 * np.pi, 240)
        show_circle = bool(
            hasattr(self, "show_heatmap_circle_check")
            and self.show_heatmap_circle_check.isChecked()
        )
        show_labels = self._is_heatmap_position_labels_enabled()

        for index, item in enumerate(getattr(self, "display_items", [])):
            circle = item.get("circle")
            label = item.get("label")
            if index >= visible_count or index >= len(centers):
                if circle is not None:
                    circle.setVisible(False)
                if label is not None:
                    label.setVisible(False)
                continue

            center_x, center_y = centers[index]
            if circle is not None:
                circle.setData(center_x + radius * np.cos(theta), center_y + radius * np.sin(theta))
                circle.setVisible(show_circle)
            if label is not None:
                label.setText(self._get_channel_group_title(index), color=(235, 235, 235))
                label.setPos(center_x, center_y + (radius * 0.72))
                label.setVisible(show_labels)

    def create_display_tab(self):
        display_widget = QWidget()
        main_layout = QVBoxLayout()

        controls_layout = QHBoxLayout()
        self.display_mirror_check = QCheckBox("Mirror")
        self.display_mirror_check.setToolTip("Mirror Display tab layout horizontally (left/right swapped)")
        self.display_mirror_check.setChecked(False)
        self.display_mirror_check.toggled.connect(self._on_display_mirror_toggled)
        controls_layout.addWidget(self.display_mirror_check)
        controls_layout.addStretch()
        main_layout.addLayout(controls_layout)

        display_group = QGroupBox("Display")
        group_layout = QVBoxLayout()
        self.display_plot_widget = pg.GraphicsLayoutWidget()
        self.display_plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.display_plot = self.display_plot_widget.addPlot()
        self.display_plot.setAspectLocked(True, ratio=1.0)
        self.display_plot.invertY(True)
        self.display_plot.showAxis("left", False)
        self.display_plot.showAxis("bottom", False)
        self.display_plot.setMouseEnabled(x=False, y=False)

        self.display_cell_spacing = 220.0
        self.display_heatmap_size = 280.0
        self.display_canvas_extra_margin = 24.0
        self.display_items = []
        for _ in range(MAX_SENSOR_PACKAGES):
            image = self._create_heatmap_image_item()
            image.setColorMap(self._get_heatmap_color_map())
            self._set_heatmap_image(image, np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32))
            image.setVisible(False)
            self.display_plot.addItem(image)

            self.display_items.append({
                "image": image,
            })

        group_layout.addWidget(self.display_plot_widget)
        display_group.setLayout(group_layout)
        main_layout.addWidget(display_group)
        display_widget.setLayout(main_layout)
        self.update_visible_display_cards(1)
        return display_widget

    def _render_point_tracking_display(self, package_results, settings):
        sensor_ids, sensor_positions, sensor_centers = self._get_visible_array_display_context(len(package_results))
        if not sensor_ids or not sensor_centers:
            return False

        target = resolve_point_tracking_target(
            package_results,
            sensor_ids,
            sensor_positions,
            sensor_centers,
            self._get_display_circle_diameter_value(),
        )
        if target is None:
            return False

        tracking_heatmap = self._build_point_tracking_heatmap(target.intensity, settings)
        display_heatmap = np.fliplr(tracking_heatmap) if self._is_display_mirror_enabled() else tracking_heatmap
        heatmap_size = self._get_display_heatmap_size_value()

        for item in getattr(self, "display_items", []):
            item["image"].setVisible(False)

        if not getattr(self, "display_items", []):
            return False

        item = self.display_items[0]
        self._set_heatmap_image(item["image"], display_heatmap)
        item["image"].setRect(
            QRectF(
                float(target.center_x) - (heatmap_size * 0.5),
                float(target.center_y) - (heatmap_size * 0.5),
                heatmap_size,
                heatmap_size,
            )
        )
        item["image"].setVisible(True)
        self._refresh_display_item_overlays()
        return True

    def update_display_tab(self, package_results, shear_results=None, settings=None):
        self.update_visible_display_cards(len(package_results))
        centers = self._get_display_package_centers(len(package_results))
        heatmap_size = self._get_display_heatmap_size_value()

        for item in getattr(self, "display_items", []):
            item["image"].setVisible(False)

        point_tracking_enabled = self._is_point_tracking_enabled()
        if point_tracking_enabled and settings is None:
            settings = self.get_heatmap_settings()

        if point_tracking_enabled and self._render_point_tracking_display(package_results, settings):
            return

        for index, result in enumerate(package_results):
            if index >= len(getattr(self, "display_items", [])) or index >= len(centers):
                break

            heatmap, _, _, _, _, _ = result
            item = self.display_items[index]
            center_x, center_y = centers[index]

            display_heatmap = np.fliplr(heatmap) if self._is_display_mirror_enabled() else heatmap
            self._set_heatmap_image(item["image"], display_heatmap)
            item["image"].setRect(QRectF(center_x - (heatmap_size * 0.5), center_y - (heatmap_size * 0.5), heatmap_size, heatmap_size))
            item["image"].setVisible(True)
        self._refresh_display_item_overlays()

    def _clear_heatmap_background_overlay(self):
        for card in getattr(self, "heatmap_cards", []):
            if card["circle"] is not None:
                card["plot"].removeItem(card["circle"])
            for item in card["markers"] + card["marker_labels"]:
                card["plot"].removeItem(item)
            card["circle"] = None
            card["markers"] = []
            card["marker_labels"] = []
        for item in getattr(self, "display_items", []):
            circle = item.get("circle")
            if circle is not None:
                circle.setVisible(False)

    def _refresh_heatmap_background_overlay(self, force=False):
        self._clear_heatmap_background_overlay()
        show_circle = bool(
            hasattr(self, "show_heatmap_circle_check")
            and self.show_heatmap_circle_check.isChecked()
        )
        if not show_circle:
            self.heatmap_overlay_mode = "heatmap_only"
            self._refresh_display_item_overlays()
            return

        center_x = (float(HEATMAP_WIDTH) - 1.0) / 2.0
        center_y = (float(HEATMAP_HEIGHT) - 1.0) / 2.0
        radius = min(float(HEATMAP_WIDTH), float(HEATMAP_HEIGHT)) * (0.48 / float(HEATMAP_COORD_EXTENT))
        theta = np.linspace(0.0, 2.0 * np.pi, 240)
        circle_x = center_x + radius * np.cos(theta)
        circle_y = center_y + radius * np.sin(theta)

        for card in getattr(self, "heatmap_cards", []):
            circle = pg.PlotDataItem(
                circle_x,
                circle_y,
                pen=pg.mkPen((230, 230, 230, 190), width=2),
            )
            circle.setZValue(5)
            card["plot"].addItem(circle)
            card["circle"] = circle

        self.heatmap_overlay_mode = "circle"
        self._refresh_display_item_overlays()

    def update_visible_heatmap_cards(self, visible_count):
        self._relayout_heatmap_cards(visible_count)
        for index, card in enumerate(getattr(self, "heatmap_cards", [])):
            card["group"].setTitle(self._get_channel_group_title(index))
            card["group"].setVisible(index < visible_count)

    def create_heatmap_settings(self):
        group = QGroupBox("Heatmap Settings")
        self.heatmap_settings_group = group
        main_layout = QVBoxLayout()
        actions = QHBoxLayout()
        self.save_heatmap_settings_btn = QPushButton("Save Settings...")
        self.save_heatmap_settings_btn.clicked.connect(self.on_save_heatmap_settings_clicked)
        actions.addWidget(self.save_heatmap_settings_btn)
        self.load_heatmap_settings_btn = QPushButton("Load Settings...")
        self.load_heatmap_settings_btn.clicked.connect(self.on_load_heatmap_settings_clicked)
        actions.addWidget(self.load_heatmap_settings_btn)
        self.zero_heatmap_signals_btn = QPushButton("Zero Signals")
        self.zero_heatmap_signals_btn.setToolTip("Recalculate the PZR baseline from the current live signals")
        self.zero_heatmap_signals_btn.clicked.connect(self.zero_plot_baselines)
        actions.addWidget(self.zero_heatmap_signals_btn)
        actions.addStretch()
        main_layout.addLayout(actions)

        signal_group = QGroupBox("Signal Processing")
        signal_layout = QGridLayout()
        signal_group.setMinimumHeight(96)
        signal_layout.setHorizontalSpacing(12)
        signal_layout.setVerticalSpacing(8)
        signal_layout.setContentsMargins(9, 9, 9, 9)
        signal_layout.setRowMinimumHeight(0, 30)
        signal_layout.setRowMinimumHeight(1, 30)
        signal_layout.setColumnStretch(1, 1)
        signal_layout.setColumnStretch(3, 1)
        signal_layout.addWidget(QLabel("RMS Window (ms):"), 0, 0)
        self.rms_window_spin = QSpinBox()
        self.rms_window_spin.setRange(2, 5000)
        self.rms_window_spin.setValue(RMS_WINDOW_MS)
        self.rms_window_spin.setMinimumHeight(28)
        signal_layout.addWidget(self.rms_window_spin, 0, 1)
        signal_layout.addWidget(QLabel("DC Removal:"), 0, 2)
        self.dc_removal_combo = QComboBox()
        self.dc_removal_combo.addItems(["Bias (2s)", "High-pass"])
        self.dc_removal_combo.setCurrentIndex(0 if HEATMAP_DC_REMOVAL_MODE == "bias" else 1)
        self.dc_removal_combo.setMinimumHeight(28)
        signal_layout.addWidget(self.dc_removal_combo, 0, 3)
        signal_layout.addWidget(QLabel("HPF Cutoff (Hz):"), 1, 0)
        self.hpf_cutoff_spin = QDoubleSpinBox()
        self.hpf_cutoff_spin.setRange(0.01, 50.0)
        self.hpf_cutoff_spin.setDecimals(3)
        self.hpf_cutoff_spin.setValue(HPF_CUTOFF_HZ)
        self.hpf_cutoff_spin.setMinimumHeight(28)
        signal_layout.addWidget(self.hpf_cutoff_spin, 1, 1)
        self.remove_negatives_check = QCheckBox("Remove negatives")
        self.remove_negatives_check.setChecked(REMOVE_NEGATIVES)
        self.remove_negatives_check.setToolTip(
            "Set negative samples to zero after DC removal before calculating RMS"
        )
        signal_layout.addWidget(self.remove_negatives_check, 1, 2, 1, 2)
        self.heatmap_use_median_baseline_check = QCheckBox("Use Time Series median baseline")
        self.heatmap_use_median_baseline_check.setChecked(False)
        self.heatmap_use_median_baseline_check.setToolTip(
            "Use the last Time Series median baseline (auto-captured or Zero Signals) instead of fixed bias initialization"
        )
        signal_layout.addWidget(self.heatmap_use_median_baseline_check, 1, 4, 1, 2)
        self.dc_removal_combo.currentIndexChanged.connect(self._on_dc_mode_changed)
        self._on_dc_mode_changed(self.dc_removal_combo.currentIndex())
        self.heatmap_signal_group = signal_group
        signal_group.setLayout(signal_layout)

        pzr_group = QGroupBox("PZR Parameters")
        pzr_group.setMinimumHeight(120)
        pzr_layout = QVBoxLayout()
        pzr_layout.setSpacing(6)
        
        # Row 1: CoP Smooth Alpha and Intensity Min
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("CoP Smooth Alpha (position):"), 0)
        self.r555_cop_smooth_alpha_spin = QDoubleSpinBox()
        self.r555_cop_smooth_alpha_spin.setRange(0.0, 1.0)
        self.r555_cop_smooth_alpha_spin.setDecimals(3)
        self.r555_cop_smooth_alpha_spin.setSingleStep(0.01)
        self.r555_cop_smooth_alpha_spin.setValue(R_HEATMAP_COP_SMOOTH_ALPHA)
        row1.addWidget(self.r555_cop_smooth_alpha_spin, 0)
        row1.addWidget(QLabel("Intensity Min (%):"), 0)
        self.r555_intensity_min_spin = QDoubleSpinBox()
        self.r555_intensity_min_spin.setRange(0.0, 1000.0)
        self.r555_intensity_min_spin.setDecimals(4)
        self.r555_intensity_min_spin.setValue(R_HEATMAP_INTENSITY_MIN)
        row1.addWidget(self.r555_intensity_min_spin, 0)
        row1.addStretch()
        pzr_layout.addLayout(row1)

        # Row 2: Intensity Max and Axis Adapt
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Intensity Max (%):"), 0)
        self.r555_intensity_max_spin = QDoubleSpinBox()
        self.r555_intensity_max_spin.setRange(0.0, 1000.0)
        self.r555_intensity_max_spin.setDecimals(4)
        self.r555_intensity_max_spin.setValue(R_HEATMAP_INTENSITY_MAX)
        row2.addWidget(self.r555_intensity_max_spin, 0)
        row2.addWidget(QLabel("Axis Adapt:"), 0)
        self.r555_axis_adapt_spin = QDoubleSpinBox()
        self.r555_axis_adapt_spin.setRange(0.0, 5.0)
        self.r555_axis_adapt_spin.setDecimals(3)
        self.r555_axis_adapt_spin.setValue(R_HEATMAP_AXIS_ADAPT_STRENGTH)
        row2.addWidget(self.r555_axis_adapt_spin, 0)
        row2.addStretch()
        pzr_layout.addLayout(row2)

        # Row 3: Map Smooth Alpha
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Map Smooth Alpha (image):"), 0)
        self.r555_map_smooth_alpha_spin = QDoubleSpinBox()
        self.r555_map_smooth_alpha_spin.setRange(0.0, 1.0)
        self.r555_map_smooth_alpha_spin.setDecimals(3)
        self.r555_map_smooth_alpha_spin.setSingleStep(0.01)
        self.r555_map_smooth_alpha_spin.setValue(R_HEATMAP_MAP_SMOOTH_ALPHA)
        row3.addWidget(self.r555_map_smooth_alpha_spin, 0)
        row3.addStretch()
        pzr_layout.addLayout(row3)
        
        pzr_group.setLayout(pzr_layout)
        self.heatmap_pzr_group = pzr_group

        calib_group = QGroupBox("Noise Threshold")
        calib_layout = QVBoxLayout()
        row = QHBoxLayout()
        self.global_noise_threshold_label = QLabel("Global Noise Threshold:")
        row.addWidget(self.global_noise_threshold_label)
        self.global_noise_threshold_spin = QDoubleSpinBox()
        self.global_noise_threshold_spin.setRange(0.0, 1e6)
        self.global_noise_threshold_spin.setDecimals(4)
        self.global_noise_threshold_spin.setValue(R_HEATMAP_DELTA_THRESHOLD)
        self.global_noise_threshold_spin.setMinimumHeight(28)
        row.addWidget(self.global_noise_threshold_spin)
        row.addStretch()
        calib_layout.addLayout(row)
        calib_group.setLayout(calib_layout)

        # Per-sensor calibration - will be populated dynamically
        self.per_sensor_calibration_group = QGroupBox("Per-Sensor Calibration (Mode-Specific)")
        self.per_sensor_calibration_layout = QVBoxLayout()
        self.per_sensor_calibration_group.setLayout(self.per_sensor_calibration_layout)
        
        # Dictionary to store spinboxes by sensor ID
        self.sensor_calibration_spins = {}  # {"PZR2": {"gain_spins": [...], "threshold_spins": [...]}}

        params_group = QGroupBox("Heatmap Parameters")
        params_layout = QVBoxLayout()

        display_layout = QGridLayout()
        display_layout.addWidget(QLabel("Sensor Size:"), 0, 0)
        self.sensor_size_spin = QDoubleSpinBox()
        self.sensor_size_spin.setRange(0.01, 10000.0)
        self.sensor_size_spin.setDecimals(2)
        self.sensor_size_spin.setValue(SENSOR_SIZE)
        display_layout.addWidget(self.sensor_size_spin, 0, 1)
        display_layout.addWidget(QLabel("Gap (mm):"), 0, 2)
        self.heatmap_gap_spin = QDoubleSpinBox()
        self.heatmap_gap_spin.setRange(0.0, 10000.0)
        self.heatmap_gap_spin.setDecimals(2)
        self.heatmap_gap_spin.setValue(POINT_TRACKING_GAP_MM)
        display_layout.addWidget(self.heatmap_gap_spin, 0, 3)
        display_layout.addWidget(QLabel("Intensity Scale:"), 1, 0)
        self.intensity_scale_spin = QDoubleSpinBox()
        self.intensity_scale_spin.setRange(0.0, 1.0)
        self.intensity_scale_spin.setDecimals(6)
        self.intensity_scale_spin.setSingleStep(0.0001)
        self.intensity_scale_spin.setValue(INTENSITY_SCALE)
        display_layout.addWidget(self.intensity_scale_spin, 1, 1)
        self.heatmap_point_tracking_check = QCheckBox("Point Tracking")
        self.heatmap_point_tracking_check.setChecked(POINT_TRACKING_ENABLED)
        self.heatmap_point_tracking_check.setToolTip(
            "Show only the strongest single point of pressure across the full array"
        )
        display_layout.addWidget(self.heatmap_point_tracking_check, 1, 2, 1, 2)
        display_layout.addWidget(QLabel("Blob Sigma X:"), 2, 0)
        self.blob_sigma_x_spin = QDoubleSpinBox()
        self.blob_sigma_x_spin.setRange(0.01, 5.0)
        self.blob_sigma_x_spin.setDecimals(4)
        self.blob_sigma_x_spin.setValue(BLOB_SIGMA_X)
        display_layout.addWidget(self.blob_sigma_x_spin, 2, 1)
        display_layout.addWidget(QLabel("Blob Sigma Y:"), 2, 2)
        self.blob_sigma_y_spin = QDoubleSpinBox()
        self.blob_sigma_y_spin.setRange(0.01, 5.0)
        self.blob_sigma_y_spin.setDecimals(4)
        self.blob_sigma_y_spin.setValue(BLOB_SIGMA_Y)
        display_layout.addWidget(self.blob_sigma_y_spin, 2, 3)
        self.ellipse_shape_check = QCheckBox("Ellipse Shape")
        self.ellipse_shape_check.setChecked(ELLIPSE_SHAPE_ENABLED)
        self.ellipse_shape_check.setToolTip(
            "Allow outer-sensor balance to stretch the blob; turn off for a circular blob"
        )
        display_layout.addWidget(self.ellipse_shape_check, 3, 2, 1, 2)
        display_layout.addWidget(QLabel("Signal Smooth Alpha (sensor):"), 3, 0)
        self.smooth_alpha_spin = QDoubleSpinBox()
        self.smooth_alpha_spin.setRange(0.0, 1.0)
        self.smooth_alpha_spin.setDecimals(3)
        self.smooth_alpha_spin.setSingleStep(0.01)
        self.smooth_alpha_spin.setValue(SMOOTH_ALPHA)
        display_layout.addWidget(self.smooth_alpha_spin, 3, 1)
        self.show_heatmap_circle_check = QCheckBox("Show Circle")
        self.show_heatmap_circle_check.setChecked(False)
        self.show_heatmap_circle_check.setToolTip("Draw the sensor boundary circle over each heatmap")
        self.show_heatmap_circle_check.stateChanged.connect(self._on_heatmap_circle_overlay_toggled)
        display_layout.addWidget(self.show_heatmap_circle_check, 4, 2, 1, 2)
        self.show_heatmap_position_labels_check = QCheckBox("Show Position Labels")
        self.show_heatmap_position_labels_check.setChecked(False)
        self.show_heatmap_position_labels_check.setToolTip("Show selected sensor IDs over the array heatmap display")
        display_layout.addWidget(self.show_heatmap_position_labels_check, 5, 2, 1, 2)
        self.heatmap_mirror_check = QCheckBox("Mirror")
        self.heatmap_mirror_check.setChecked(HEATMAP_MIRROR_DISPLAY)
        self.heatmap_mirror_check.setToolTip(
            "Mirror the heatmap display horizontally, swapping left/right packages and sensors"
        )
        display_layout.addWidget(self.heatmap_mirror_check, 5, 0, 1, 2)
        display_layout.addWidget(QLabel("Color Scale:"), 4, 0)
        self.heatmap_colormap_combo = QComboBox()
        self.heatmap_colormap_combo.addItems(list(self.HEATMAP_COLOR_MAPS.keys()))
        self.heatmap_colormap_combo.setCurrentText("Thermal")
        display_layout.addWidget(self.heatmap_colormap_combo, 4, 1)

        params_layout.addLayout(display_layout)
        params_layout.addWidget(signal_group)
        params_layout.addWidget(pzr_group)
        params_group.setLayout(params_layout)

        # Requested section order
        main_layout.addWidget(calib_group)
        main_layout.addWidget(self.per_sensor_calibration_group)
        main_layout.addWidget(params_group)

        self._connect_heatmap_settings_autosave()
        self.enable_heatmap_settings_autosave()
        self.update_heatmap_ui_for_mode()
        group.setLayout(main_layout)
        return group

    def _on_dc_mode_changed(self, index):
        self.hpf_cutoff_spin.setEnabled(index == 1)

    def get_heatmap_settings(self):
        use_time_series_median_baseline = bool(
            hasattr(self, "heatmap_use_median_baseline_check")
            and self.heatmap_use_median_baseline_check.isChecked()
        )
        if use_time_series_median_baseline and not getattr(self, 'channel_plot_baselines', {}):
            if hasattr(self, 'capture_current_plot_baselines'):
                self.capture_current_plot_baselines(
                    log_message=False,
                    min_elapsed_sec=getattr(self, 'PZR_AUTO_BASELINE_DELAY_SEC', 1.5),
                )

        channel_sensor_map = self.get_active_channel_sensor_map() if hasattr(self, "get_active_channel_sensor_map") else HEATMAP_CHANNEL_SENSOR_MAP
        calibration = list(SENSOR_CALIBRATION)
        sensor_noise_floor = list(SENSOR_NOISE_FLOOR)
        global_noise_threshold = float(self.global_noise_threshold_spin.value())
        
        # Build channel-to-baseline mapping from plot_baselines if available
        channel_to_baseline = {}
        if use_time_series_median_baseline and hasattr(self, 'channel_plot_baselines'):
            for channel, baseline in getattr(self, 'channel_plot_baselines', {}).items():
                channel_to_baseline[channel] = float(baseline)
        
        # Build per-sensor calibration dict from dynamic spinboxes
        sensor_calibration_dict = {}
        if hasattr(self, 'sensor_calibration_spins') and isinstance(self.sensor_calibration_spins, dict):
            for sensor_id, spinboxes in self.sensor_calibration_spins.items():
                threshold_values = []
                for spin in spinboxes.get('threshold_spins', []):
                    try:
                        threshold_values.append(self._get_numeric_input_value(spin, 0.0))
                    except (RuntimeError, AttributeError, TypeError):
                        # Widget may have been deleted
                        threshold_values.append(0.0)
                
                gain_values = []
                for spin in spinboxes.get('gain_spins', []):
                    try:
                        gain_values.append(self._get_numeric_input_value(spin, 1.0))
                    except (RuntimeError, AttributeError, TypeError):
                        # Widget may have been deleted
                        gain_values.append(1.0)
                
                sensor_calibration_dict[sensor_id] = {
                    'thresholds': threshold_values,
                    'gains': gain_values
                }
        
        return {
            "sensor_calibration": calibration,
            "sensor_noise_floor": sensor_noise_floor,
            "global_noise_threshold": global_noise_threshold,
            "sensor_size": self.sensor_size_spin.value(),
            "gap_mm": self.heatmap_gap_spin.value(),
            "intensity_scale": self.intensity_scale_spin.value(),
            "blob_sigma_x": self.blob_sigma_x_spin.value(),
            "blob_sigma_y": self.blob_sigma_y_spin.value(),
            "ellipse_shape_enabled": (
                self.ellipse_shape_check.isChecked()
                if hasattr(self, "ellipse_shape_check")
                else ELLIPSE_SHAPE_ENABLED
            ),
            "smooth_alpha": self.smooth_alpha_spin.value(),
            "rms_window_ms": self.rms_window_spin.value(),
            "dc_removal_mode": "bias" if self.dc_removal_combo.currentIndex() == 0 else "highpass",
            "hpf_cutoff_hz": self.hpf_cutoff_spin.value(),
            "remove_negatives": (
                self.remove_negatives_check.isChecked()
                if hasattr(self, "remove_negatives_check")
                else REMOVE_NEGATIVES
            ),
            "use_time_series_median_baseline": use_time_series_median_baseline,
            "channel_sensor_map": channel_sensor_map,
            "channel_to_baseline": channel_to_baseline,
            "confidence_intensity_ref": CONFIDENCE_INTENSITY_REF,
            "sigma_spread_factor": SIGMA_SPREAD_FACTOR,
            "cop_smooth_alpha": self.r555_cop_smooth_alpha_spin.value(),
            "intensity_min": self.r555_intensity_min_spin.value(),
            "intensity_max": self.r555_intensity_max_spin.value(),
            "axis_adapt_strength": self.r555_axis_adapt_spin.value(),
            "map_smooth_alpha": self.r555_map_smooth_alpha_spin.value(),
            "sensor_calibration_dict": sensor_calibration_dict,
            "show_circle_overlay": (
                self.show_heatmap_circle_check.isChecked()
                if hasattr(self, "show_heatmap_circle_check")
                else False
            ),
            "show_position_labels": (
                self.show_heatmap_position_labels_check.isChecked()
                if hasattr(self, "show_heatmap_position_labels_check")
                else False
            ),
            "mirror_display": (
                self.heatmap_mirror_check.isChecked()
                if hasattr(self, "heatmap_mirror_check")
                else HEATMAP_MIRROR_DISPLAY
            ),
            "heatmap_colormap": self._get_selected_heatmap_colormap_name(),
            "point_tracking_enabled": (
                self.heatmap_point_tracking_check.isChecked()
                if hasattr(self, "heatmap_point_tracking_check")
                else POINT_TRACKING_ENABLED
            ),
        }

    def update_heatmap_ui_for_mode(self):
        mode_key = self._get_heatmap_mode_key()
        is_pzr_mode = mode_key == "pzr"
        if hasattr(self, "heatmap_signal_group"):
            self.heatmap_signal_group.setVisible(not is_pzr_mode)
        if hasattr(self, "heatmap_pzr_group"):
            self.heatmap_pzr_group.setVisible(is_pzr_mode)
        if hasattr(self, "zero_heatmap_signals_btn"):
            self.zero_heatmap_signals_btn.setVisible(is_pzr_mode)
        if hasattr(self, "global_noise_threshold_label"):
            suffix = " (%):" if is_pzr_mode else ":"
            self.global_noise_threshold_label.setText(f"Global Noise Threshold{suffix}")

        current_sensor_ids = tuple(self._get_visible_sensor_ids())
        mode_changed = getattr(self, "_last_heatmap_mode_key", None) != mode_key
        sensors_changed = getattr(self, "_last_visible_heatmap_sensor_ids", None) != current_sensor_ids

        if hasattr(self, "per_sensor_calibration_group") and (mode_changed or sensors_changed):
            self._build_per_sensor_calibration_ui()
            self._last_heatmap_mode_key = mode_key
            self._last_visible_heatmap_sensor_ids = current_sensor_ids

        if mode_changed:
            self.load_last_heatmap_settings()
            if hasattr(self, "load_last_shear_settings"):
                self.load_last_shear_settings()

        if mode_changed or sensors_changed:
            self._refresh_heatmap_background_overlay(force=True)

    def update_heatmap_plot(self):
        if getattr(self, "_heatmap_updating_plot", False):
            return

        self._heatmap_updating_plot = True
        try:
            if not hasattr(self, "display_items"):
                return

            if self.raw_data_buffer is None or self.samples_per_sweep <= 0:
                self.show_heatmap_channel_warning(0)
                return

            self.update_heatmap_ui_for_mode()
            settings = self.get_heatmap_settings()
            mode_key = self._get_heatmap_mode_key()

            if mode_key == "pzr":
                package_results = self.process_555_displacement_heatmap(settings)
            else:
                package_sensor_values = self.compute_channel_intensities(settings)
                if not package_sensor_values:
                    package_results = None
                else:
                    package_results = [
                        self.process_sensor_data_for_heatmap(
                            sensor_values,
                            settings,
                            package_index=package_index,
                        )
                        for package_index, sensor_values in enumerate(package_sensor_values)
                    ]

            if not package_results:
                current_channels = len(self.config.get("channels", [])) if hasattr(self, "config") else 0
                self.show_heatmap_channel_warning(current_channels)
                return

            self.clear_heatmap_channel_warning()
            self.update_heatmap_display(package_results, settings=settings)
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"Heatmap update unavailable: {exc}")
        finally:
            self._heatmap_updating_plot = False

    def update_heatmap_display(self, package_results, shear_results=None, settings=None):
        self.update_display_tab(package_results, shear_results=shear_results, settings=settings)

    def show_heatmap_channel_warning(self, current_channels, required_channels="5"):
        self.heatmap_status_label.setText(f"Heatmap requires {required_channels} channels (currently {current_channels} selected)")

    def clear_heatmap_channel_warning(self):
        self.heatmap_status_label.setText("")
