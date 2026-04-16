from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout,
    QComboBox, QPushButton, QFileDialog, QCheckBox, QLineEdit,
    QScrollArea, QApplication, QSizePolicy,
)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QDoubleValidator
import pyqtgraph as pg
import numpy as np
from pathlib import Path

from gui.custom_widgets import NonScrollableSpinBox as QSpinBox, NonScrollableDoubleSpinBox as QDoubleSpinBox

from config_constants import (
    HEATMAP_WIDTH, HEATMAP_HEIGHT, SENSOR_CALIBRATION, SENSOR_SIZE,
    INTENSITY_SCALE, BLOB_SIGMA_X, BLOB_SIGMA_Y, SMOOTH_ALPHA,
    RMS_WINDOW_MS, SENSOR_NOISE_FLOOR, HEATMAP_DC_REMOVAL_MODE,
    HPF_CUTOFF_HZ, HEATMAP_CHANNEL_SENSOR_MAP, HEATMAP_THRESHOLD,
    CONFIDENCE_INTENSITY_REF, SIGMA_SPREAD_FACTOR,
    MAX_SENSOR_PACKAGES,
    R_HEATMAP_DELTA_THRESHOLD, R_HEATMAP_DELTA_RELEASE_THRESHOLD,
    R_HEATMAP_INTENSITY_MIN, R_HEATMAP_INTENSITY_MAX,
    R_HEATMAP_AXIS_ADAPT_STRENGTH, R_HEATMAP_MAP_SMOOTH_ALPHA,
    R_HEATMAP_COP_SMOOTH_ALPHA,
    SHEAR_ARROW_HEAD_LENGTH_AMPLIFIER, SHEAR_ARROW_HEAD_LENGTH_BASE_PX,
)
from file_operations.settings_persistence import load_settings_payload, save_settings_payload
from config.channel_utils import unique_channels_in_order


class HeatmapPanelMixin:
    HEATMAP_VIEW_EXTENT = 1.25  # Scaling factor for arrow visualization

    def _is_display_mirror_enabled(self) -> bool:
        checkbox = getattr(self, "display_mirror_check", None)
        return bool(checkbox is not None and checkbox.isChecked())

    def _on_display_mirror_toggled(self, _checked=False):
        self._update_display_plot_view()
        if hasattr(self, "trigger_plot_update"):
            self.trigger_plot_update()

    def _get_heatmap_mode_key(self) -> str:
        is_pzr_mode = bool(hasattr(self, "is_555_analyzer_mode") and self.is_555_analyzer_mode())
        return "pzr" if is_pzr_mode else "pzt"

    def _get_heatmap_setting_keys_for_mode(self, mode_key: str | None = None) -> set[str]:
        mode = (mode_key or self._get_heatmap_mode_key()).lower()
        if mode == "pzr":
            return {
                "sensor_calibration",
                "global_channel_thresholds",
                "global_channel_release_thresholds",
                "intensity_scale",
                "blob_sigma_x",
                "blob_sigma_y",
                "smooth_alpha",
                "delta_threshold",
                "delta_release_threshold",
                "cop_smooth_alpha",
                "intensity_min",
                "intensity_max",
                "axis_adapt_strength",
                "map_smooth_alpha",
                "sensor_calibration_dict",  # Per-sensor calibration indexed by sensor ID
            }
        return {
            "sensor_calibration",
            "sensor_noise_floor",
            "global_channel_thresholds",
            "global_channel_release_thresholds",
            "sensor_size",
            "intensity_scale",
            "blob_sigma_x",
            "blob_sigma_y",
            "smooth_alpha",
            "rms_window_ms",
            "dc_removal_mode",
            "hpf_cutoff_hz",
            "general_threshold",  # Changed from magnitude_threshold
            "sensor_calibration_dict",  # Per-sensor calibration indexed by sensor ID
        }

    def _filter_heatmap_settings_for_mode(self, settings: dict, mode_key: str | None = None) -> dict:
        allowed_keys = self._get_heatmap_setting_keys_for_mode(mode_key)
        return {key: value for key, value in settings.items() if key in allowed_keys}
    
    def _arrow_item_angle_from_vector(self, dx: float, dy: float) -> float:
        """Calculate angle in degrees for arrow from vector components."""
        import math
        return math.degrees(math.atan2(float(-dy), float(dx))) - 180.0
    
    def _arrow_head_tip_position(self, card, line_end_x: float, line_end_y: float, head_length_px: float):
        """Calculate arrow head tip position based on line endpoint and head length."""
        import math
        arrow_length = math.hypot(line_end_x, line_end_y)
        if arrow_length <= 1e-12:
            return line_end_x, line_end_y
        view_box = card["plot"].getViewBox()
        x_range, y_range = view_box.viewRange()
        rect = view_box.sceneBoundingRect()
        width = max(float(rect.width()), 1.0)
        height = max(float(rect.height()), 1.0)
        unit_x = line_end_x / arrow_length
        unit_y = line_end_y / arrow_length
        return (
            line_end_x + unit_x * ((x_range[1] - x_range[0]) / width) * head_length_px,
            line_end_y + unit_y * ((y_range[1] - y_range[0]) / height) * head_length_px,
        )

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
            threshold_row.addWidget(QLabel(f"Thresholds {'(%)' if is_pzr_mode else ''}  [T,B,R,L,C]:"))
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
            if "global_channel_thresholds" in mode_settings and isinstance(mode_settings["global_channel_thresholds"], list):
                for spin, value in zip(self.global_threshold_spins, mode_settings["global_channel_thresholds"]):
                    spin.setValue(float(value))
                    changed = True
            if "global_channel_release_thresholds" in mode_settings and isinstance(mode_settings["global_channel_release_thresholds"], list):
                for spin, value in zip(self.global_release_threshold_spins, mode_settings["global_channel_release_thresholds"]):
                    spin.setValue(float(value))
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
            
            # Load general threshold for PZT or PZR
            if "general_threshold" in mode_settings:
                value = float(mode_settings["general_threshold"])
                for spin in self.global_threshold_spins:
                    spin.setValue(value)
                changed = True
            
            scalar_map = [
                ("sensor_size", self.sensor_size_spin),
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
            if "delta_threshold" in mode_settings:
                value = float(mode_settings["delta_threshold"])
                for spin in self.global_threshold_spins:
                    spin.setValue(value)
                changed = True
            if "delta_release_threshold" in mode_settings:
                value = float(mode_settings["delta_release_threshold"])
                for spin in self.global_release_threshold_spins:
                    spin.setValue(value)
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
            self.rms_window_spin, self.dc_removal_combo, self.hpf_cutoff_spin, self.magnitude_threshold_spin,
            self.sensor_size_spin, self.intensity_scale_spin, self.blob_sigma_x_spin, self.blob_sigma_y_spin, self.smooth_alpha_spin,
            self.r555_cop_smooth_alpha_spin,
            self.r555_intensity_min_spin, self.r555_intensity_max_spin, self.r555_axis_adapt_spin,
            self.r555_map_smooth_alpha_spin,
        ]
        widgets.extend(self.global_threshold_spins)
        widgets.extend(self.global_release_threshold_spins)
        
        for widget in widgets:
            signal = getattr(widget, "valueChanged", None)
            if signal is not None:
                signal.connect(self.save_last_heatmap_settings)
        self.dc_removal_combo.currentIndexChanged.connect(self.save_last_heatmap_settings)
        # Note: Per-sensor threshold and gain spinboxes are connected in _build_per_sensor_calibration_ui()

    def _create_heatmap_card(self, package_index):
        group = QGroupBox(self._get_channel_group_title(package_index))
        layout = QVBoxLayout()
        plot_widget = pg.GraphicsLayoutWidget()
        plot_widget.setMinimumSize(220, 220)
        plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plot = plot_widget.addPlot()
        plot.setAspectLocked(True, ratio=1.0)
        plot.invertY(True)
        plot.showAxis("left", False)
        plot.showAxis("bottom", False)
        plot.setMouseEnabled(x=False, y=False)
        image = pg.ImageItem()
        image.setColorMap(pg.colormap.get("viridis"))
        image.setImage(np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32), autoLevels=False, levels=(0, 1))
        plot.addItem(image)
        # Add shear arrow visualization
        arrow_line = pg.PlotDataItem([], [], pen=pg.mkPen((235, 80, 60), width=3))
        arrow_line.setZValue(10)
        plot.addItem(arrow_line)
        arrow_head = pg.ArrowItem(angle=0.0, headLen=SHEAR_ARROW_HEAD_LENGTH_BASE_PX, tipAngle=28, baseAngle=20, brush=(235, 80, 60), pen=pg.mkPen((235, 80, 60)))
        arrow_head.setZValue(11)
        plot.addItem(arrow_head)
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
            "arrow_line": arrow_line, "arrow_head": arrow_head,
        }

    def create_heatmap_tab(self):
        heatmap_widget = QWidget()
        layout = QVBoxLayout()
        capture_row = QHBoxLayout()
        capture_row.addStretch()
        self.heatmap_capture_button = QPushButton("Capture Data")
        self.heatmap_capture_button.setCheckable(True)
        self.heatmap_capture_button.toggled.connect(self.set_visualization_capture_data_enabled)
        capture_row.addWidget(self.heatmap_capture_button)
        layout.addLayout(capture_row)
        display = self.create_heatmap_display()
        screen = QApplication.primaryScreen()
        if screen is not None:
            height = screen.availableGeometry().height()
            display.setMinimumHeight(max(320, int(height * 0.48)))
            display.setMaximumHeight(max(320, int(height * 0.88)))
        layout.addWidget(display, stretch=10)
        settings_panel = self.create_heatmap_settings()
        settings_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.heatmap_settings_scroll = QScrollArea()
        self.heatmap_settings_scroll.setWidgetResizable(False)
        self.heatmap_settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.heatmap_settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.heatmap_settings_scroll.setWidget(settings_panel)
        self.heatmap_settings_scroll.setMaximumHeight(260)
        layout.addWidget(self.heatmap_settings_scroll, stretch=2)
        self.update_heatmap_ui_for_mode()
        heatmap_widget.setLayout(layout)
        if hasattr(self, "sync_visualization_capture_buttons"):
            self.sync_visualization_capture_buttons()
        return heatmap_widget

    def create_heatmap_display(self):
        group = QGroupBox("2D Pressure Heatmap")
        layout = QVBoxLayout()
        grid = QGridLayout()
        self.heatmap_cards = []
        for package_index in range(MAX_SENSOR_PACKAGES):
            card = self._create_heatmap_card(package_index)
            self.heatmap_cards.append(card)
            grid.addWidget(card["group"], package_index // 2, package_index % 2)
        layout.addLayout(grid)
        self.heatmap_status_label = QLabel("")
        self.heatmap_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.heatmap_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.heatmap_status_label)
        group.setLayout(layout)
        self.heatmap_overlay_mode = None
        self._refresh_heatmap_background_overlay(force=True)
        self.update_visible_heatmap_cards(1)
        return group

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

    def _update_display_plot_view(self):
        if not hasattr(self, "display_plot"):
            return

        visible_count = getattr(self, "display_visible_count", 1)
        positions, _, _ = self._get_display_package_positions(visible_count)
        spacing = float(getattr(self, "display_cell_spacing", 220.0))
        heatmap_size = float(getattr(self, "display_heatmap_size", 250.0))
        extra_margin = float(getattr(self, "display_canvas_extra_margin", 0.0))
        if not positions:
            half = heatmap_size * 0.5 + 40.0
            self.display_plot.setXRange(-half, half, padding=0.0)
            self.display_plot.setYRange(-half, half, padding=0.0)
            self.display_plot.setLimits(xMin=-half, xMax=half, yMin=-half, yMax=half)
            return

        x_centers = [float(col) * spacing for row, col in positions]
        y_centers = [float(row) * spacing for row, col in positions]
        content_half = heatmap_size * 0.5

        arrow_scale_widget = getattr(self, "shear_arrow_scale_spin", None)
        arrow_scale = float(arrow_scale_widget.value()) if arrow_scale_widget is not None else 1.0
        # Keep additional room for long arrows and slightly spread blobs.
        overflow = (content_half * max(0.0, self.HEATMAP_VIEW_EXTENT - 1.0) * max(1.0, arrow_scale))
        margin = max(24.0, heatmap_size * 0.08 + overflow + extra_margin)

        x_min = min(x_centers) - content_half - margin
        x_max = max(x_centers) + content_half + margin
        y_min = min(y_centers) - content_half - margin
        y_max = max(y_centers) + content_half + margin

        self.display_plot.setXRange(x_min, x_max, padding=0.0)
        self.display_plot.setYRange(y_min, y_max, padding=0.0)
        self.display_plot.setLimits(xMin=x_min, xMax=x_max, yMin=y_min, yMax=y_max)

    def update_visible_display_cards(self, visible_count):
        self.display_visible_count = max(0, int(visible_count))
        self._update_display_plot_view()

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
            image = pg.ImageItem()
            image.setColorMap(pg.colormap.get("viridis"))
            image.setImage(np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32), autoLevels=False, levels=(0, 1))
            image.setVisible(False)
            self.display_plot.addItem(image)

            arrow_line = pg.PlotDataItem([], [], pen=pg.mkPen((235, 80, 60), width=3))
            arrow_line.setZValue(10)
            arrow_line.setVisible(False)
            self.display_plot.addItem(arrow_line)

            arrow_head = pg.ArrowItem(angle=0.0, headLen=SHEAR_ARROW_HEAD_LENGTH_BASE_PX, tipAngle=28, baseAngle=20, brush=(235, 80, 60), pen=pg.mkPen((235, 80, 60)))
            arrow_head.setZValue(11)
            arrow_head.setVisible(False)
            self.display_plot.addItem(arrow_head)

            self.display_items.append({
                "image": image,
                "arrow_line": arrow_line,
                "arrow_head": arrow_head,
            })

        group_layout.addWidget(self.display_plot_widget)
        display_group.setLayout(group_layout)
        main_layout.addWidget(display_group)
        display_widget.setLayout(main_layout)
        self.update_visible_display_cards(1)
        return display_widget

    def update_display_tab(self, package_results, shear_results=None):
        import math
        self.update_visible_display_cards(len(package_results))
        shear_results = shear_results or []
        positions, _, _ = self._get_display_package_positions(len(package_results))
        spacing = float(getattr(self, "display_cell_spacing", 220.0))
        heatmap_size = float(getattr(self, "display_heatmap_size", 250.0))
        local_radius = heatmap_size * 0.48

        for item in getattr(self, "display_items", []):
            item["image"].setVisible(False)
            item["arrow_line"].setData([], [])
            item["arrow_line"].setVisible(False)
            item["arrow_head"].setVisible(False)

        for index, result in enumerate(package_results):
            if index >= len(getattr(self, "display_items", [])) or index >= len(positions):
                break

            heatmap, _, _, _, _, _ = result
            item = self.display_items[index]
            row, col = positions[index]
            center_x = float(col) * spacing
            center_y = float(row) * spacing

            item["image"].setImage(heatmap.T, autoLevels=False, levels=(0, 1))
            item["image"].setRect(QRectF(center_x - (heatmap_size * 0.5), center_y - (heatmap_size * 0.5), heatmap_size, heatmap_size))
            item["image"].setVisible(True)

            if index < len(shear_results):
                _, shear_result = shear_results[index]
                arrow_scale_widget = getattr(self, "shear_arrow_scale_spin", None)
                arrow_scale = float(arrow_scale_widget.value()) if arrow_scale_widget is not None else 1.0
                arrow_end_x = float(shear_result.shear_x) * local_radius * arrow_scale
                arrow_end_y = float(shear_result.shear_y) * local_radius * arrow_scale
                arrow_length = math.hypot(arrow_end_x, arrow_end_y)
                rel = min(arrow_length / (self.HEATMAP_VIEW_EXTENT * local_radius), 1.0)
                has_arrow = float(shear_result.shear_magnitude) > 1e-6 and (abs(arrow_end_x) > 1e-6 or abs(arrow_end_y) > 1e-6)

                if has_arrow:
                    head_len = SHEAR_ARROW_HEAD_LENGTH_BASE_PX + rel * SHEAR_ARROW_HEAD_LENGTH_AMPLIFIER
                    item["arrow_line"].setPen(pg.mkPen((235, 80, 60), width=3.0))
                    item["arrow_line"].setData([center_x, center_x + arrow_end_x], [center_y, center_y + arrow_end_y])
                    item["arrow_head"].setPos(center_x + arrow_end_x, center_y + arrow_end_y)
                    item["arrow_head"].setStyle(angle=self._arrow_item_angle_from_vector(arrow_end_x, arrow_end_y), headLen=head_len)
                    item["arrow_line"].setVisible(True)
                    item["arrow_head"].setVisible(True)
                else:
                    item["arrow_line"].setData([], [])
                    item["arrow_line"].setVisible(False)
                    item["arrow_head"].setVisible(False)

    def _clear_heatmap_background_overlay(self):
        for card in getattr(self, "heatmap_cards", []):
            if card["circle"] is not None:
                card["plot"].removeItem(card["circle"])
            for item in card["markers"] + card["marker_labels"]:
                card["plot"].removeItem(item)
            card["circle"] = None
            card["markers"] = []
            card["marker_labels"] = []

    def _refresh_heatmap_background_overlay(self, force=False):
        if getattr(self, "heatmap_overlay_mode", None) == "unified" and not force:
            return
        self._clear_heatmap_background_overlay()
        center_x = (float(HEATMAP_WIDTH) - 1.0) / 2.0
        center_y = (float(HEATMAP_HEIGHT) - 1.0) / 2.0
        radius = min(float(HEATMAP_WIDTH), float(HEATMAP_HEIGHT)) * 0.48
        theta = np.linspace(0, 2 * np.pi, 200)
        circle_x = center_x + radius * np.cos(theta)
        circle_y = center_y + radius * np.sin(theta)
        mapping = self.get_active_channel_sensor_map() if hasattr(self, "get_active_channel_sensor_map") else HEATMAP_CHANNEL_SENSOR_MAP
        numbers = {label: str(index + 1) for index, label in enumerate(mapping)}
        marker_positions = [
            (center_x + radius, center_y, numbers.get("R", "")),
            (center_x, center_y + radius, numbers.get("B", "")),
            (center_x, center_y, numbers.get("C", "")),
            (center_x - radius, center_y, numbers.get("L", "")),
            (center_x, center_y - radius, numbers.get("T", "")),
        ]
        for card in getattr(self, "heatmap_cards", []):
            circle = pg.PlotDataItem(circle_x, circle_y, pen=pg.mkPen((200, 200, 200, 160), width=2))
            circle.setZValue(5)
            card["plot"].addItem(circle)
            card["circle"] = circle
            for x_pos, y_pos, label_text in marker_positions:
                marker = pg.ScatterPlotItem([x_pos], [y_pos], symbol="s", size=14, brush=pg.mkBrush(230, 230, 230, 200), pen=pg.mkPen(120, 120, 120, 200))
                marker.setZValue(6)
                card["plot"].addItem(marker)
                card["markers"].append(marker)
                text = pg.TextItem(label_text, color=(60, 60, 60))
                text.setAnchor((0.5, 0.5))
                text.setPos(x_pos, y_pos)
                text.setZValue(7)
                card["plot"].addItem(text)
                card["marker_labels"].append(text)
        self.heatmap_overlay_mode = "unified"

    def update_visible_heatmap_cards(self, visible_count):
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
        signal_layout.addWidget(QLabel("Threshold:"), 1, 2)
        self.magnitude_threshold_spin = QDoubleSpinBox()
        self.magnitude_threshold_spin.setRange(0.0, 1e6)
        self.magnitude_threshold_spin.setDecimals(4)
        self.magnitude_threshold_spin.setValue(HEATMAP_THRESHOLD)
        self.magnitude_threshold_spin.setMinimumHeight(28)
        signal_layout.addWidget(self.magnitude_threshold_spin, 1, 3)
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

        calib_group = QGroupBox("Global Sensor Calibration")
        calib_layout = QVBoxLayout()
        self.global_threshold_spins = []
        row = QHBoxLayout()
        row.addWidget(QLabel("Global Threshold (%) [T,B,R,L,C]:"))
        for idx, name in enumerate(["T", "B", "R", "L", "C"]):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(4)
            spin.setValue(R_HEATMAP_DELTA_THRESHOLD)
            spin.setPrefix(f"{name}: ")
            self.global_threshold_spins.append(spin)
            row.addWidget(spin)
        row.addStretch()
        calib_layout.addLayout(row)

        self.global_release_threshold_spins = []
        row = QHBoxLayout()
        row.addWidget(QLabel("Global Release Threshold (%) [T,B,R,L,C]:"))
        for idx, name in enumerate(["T", "B", "R", "L", "C"]):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(4)
            spin.setValue(R_HEATMAP_DELTA_RELEASE_THRESHOLD)
            spin.setPrefix(f"{name}: ")
            self.global_release_threshold_spins.append(spin)
            row.addWidget(spin)
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
        display_layout.addWidget(QLabel("Intensity Scale:"), 0, 2)
        self.intensity_scale_spin = QDoubleSpinBox()
        self.intensity_scale_spin.setRange(0.0, 1.0)
        self.intensity_scale_spin.setDecimals(6)
        self.intensity_scale_spin.setSingleStep(0.0001)
        self.intensity_scale_spin.setValue(INTENSITY_SCALE)
        display_layout.addWidget(self.intensity_scale_spin, 0, 3)
        display_layout.addWidget(QLabel("Blob Sigma X:"), 1, 0)
        self.blob_sigma_x_spin = QDoubleSpinBox()
        self.blob_sigma_x_spin.setRange(0.01, 5.0)
        self.blob_sigma_x_spin.setDecimals(4)
        self.blob_sigma_x_spin.setValue(BLOB_SIGMA_X)
        display_layout.addWidget(self.blob_sigma_x_spin, 1, 1)
        display_layout.addWidget(QLabel("Blob Sigma Y:"), 1, 2)
        self.blob_sigma_y_spin = QDoubleSpinBox()
        self.blob_sigma_y_spin.setRange(0.01, 5.0)
        self.blob_sigma_y_spin.setDecimals(4)
        self.blob_sigma_y_spin.setValue(BLOB_SIGMA_Y)
        display_layout.addWidget(self.blob_sigma_y_spin, 1, 3)
        display_layout.addWidget(QLabel("Signal Smooth Alpha (sensor):"), 2, 0)
        self.smooth_alpha_spin = QDoubleSpinBox()
        self.smooth_alpha_spin.setRange(0.0, 1.0)
        self.smooth_alpha_spin.setDecimals(3)
        self.smooth_alpha_spin.setSingleStep(0.01)
        self.smooth_alpha_spin.setValue(SMOOTH_ALPHA)
        display_layout.addWidget(self.smooth_alpha_spin, 2, 1)

        params_layout.addLayout(display_layout)
        params_layout.addWidget(signal_group)
        params_layout.addWidget(pzr_group)
        params_group.setLayout(params_layout)

        # Requested section order
        main_layout.addWidget(calib_group)
        main_layout.addWidget(self.per_sensor_calibration_group)
        main_layout.addWidget(params_group)

        self._connect_heatmap_settings_autosave()
        self.update_heatmap_ui_for_mode()
        group.setLayout(main_layout)
        return group

    def _on_dc_mode_changed(self, index):
        self.hpf_cutoff_spin.setEnabled(index == 1)

    def get_heatmap_settings(self):
        if self._get_heatmap_mode_key() == "pzr" and not getattr(self, 'plot_baselines', {}):
            if hasattr(self, 'capture_current_plot_baselines'):
                self.capture_current_plot_baselines(
                    log_message=False,
                    min_elapsed_sec=getattr(self, 'PZR_AUTO_BASELINE_DELAY_SEC', 1.5),
                )

        channel_sensor_map = self.get_active_channel_sensor_map() if hasattr(self, "get_active_channel_sensor_map") else HEATMAP_CHANNEL_SENSOR_MAP
        calibration = list(SENSOR_CALIBRATION)
        sensor_noise_floor = list(SENSOR_NOISE_FLOOR)
        global_thresholds = [spin.value() for spin in self.global_threshold_spins]
        global_release_thresholds = [spin.value() for spin in self.global_release_threshold_spins]
        avg_global_threshold = float(np.mean(global_thresholds)) if global_thresholds else float(R_HEATMAP_DELTA_THRESHOLD)
        avg_global_release = float(np.mean(global_release_thresholds)) if global_release_thresholds else float(R_HEATMAP_DELTA_RELEASE_THRESHOLD)
        
        # Build channel-to-baseline mapping from plot_baselines if available
        channel_to_baseline = {}
        if hasattr(self, 'plot_baselines') and hasattr(self, 'get_display_channel_specs'):
            display_specs = self.get_display_channel_specs()
            for spec in display_specs:
                spec_key = spec.get('key')
                if spec_key in self.plot_baselines:
                    # Extract channel from spec key
                    # Key format: ('adc', channel) or ('mux', mux_num, channel) or ('sensor', sensor_id, placement, channel, mux_num)
                    if isinstance(spec_key, tuple) and len(spec_key) >= 2:
                        channel = spec_key[-2] if len(spec_key) >= 3 and isinstance(spec_key[-1], int) and spec_key[0] == 'sensor' else spec_key[-1]
                        channel_to_baseline[channel] = self.plot_baselines[spec_key]
        
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
        
        # Get general threshold based on mode
        general_threshold = avg_global_threshold
        
        return {
            "sensor_calibration": calibration,
            "sensor_noise_floor": sensor_noise_floor,
            "global_channel_thresholds": global_thresholds,
            "global_channel_release_thresholds": global_release_thresholds,
            "sensor_size": self.sensor_size_spin.value(),
            "intensity_scale": self.intensity_scale_spin.value(),
            "blob_sigma_x": self.blob_sigma_x_spin.value(),
            "blob_sigma_y": self.blob_sigma_y_spin.value(),
            "smooth_alpha": self.smooth_alpha_spin.value(),
            "rms_window_ms": self.rms_window_spin.value(),
            "dc_removal_mode": "bias" if self.dc_removal_combo.currentIndex() == 0 else "highpass",
            "hpf_cutoff_hz": self.hpf_cutoff_spin.value(),
            "general_threshold": general_threshold,
            "channel_sensor_map": channel_sensor_map,
            "channel_to_baseline": channel_to_baseline,
            "confidence_intensity_ref": CONFIDENCE_INTENSITY_REF,
            "sigma_spread_factor": SIGMA_SPREAD_FACTOR,
            "delta_threshold": avg_global_threshold,
            "delta_release_threshold": avg_global_release,
            "cop_smooth_alpha": self.r555_cop_smooth_alpha_spin.value(),
            "intensity_min": self.r555_intensity_min_spin.value(),
            "intensity_max": self.r555_intensity_max_spin.value(),
            "axis_adapt_strength": self.r555_axis_adapt_spin.value(),
            "map_smooth_alpha": self.r555_map_smooth_alpha_spin.value(),
            "sensor_calibration_dict": sensor_calibration_dict,
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

    def update_heatmap_display(self, package_results, shear_results=None):
        import math
        self.update_visible_heatmap_cards(len(package_results))
        shear_results = shear_results or []
        for index, result in enumerate(package_results):
            heatmap, cop_x, cop_y, intensity, confidence, sensor_values = result
            card = self.heatmap_cards[index]
            card["group"].setTitle(self._get_channel_group_title(index))
            card["image"].setImage(heatmap.T, autoLevels=False, levels=(0, 1))
            card["labels"]["cop_x"].setText(f"X: {cop_x:+.3f}")
            card["labels"]["cop_y"].setText(f"Y: {cop_y:+.3f}")
            card["labels"]["intensity"].setText(f"I: {intensity:.1f}")
            card["labels"]["confidence"].setText(f"Q: {confidence:.2f}")
            for idx, name in enumerate(["T", "B", "R", "L", "C"]):
                card["sensor_labels"][idx].setText(f"{name}: {sensor_values[idx]:.1f}" if idx < len(sensor_values) else f"{name}: -")
            card["debug_rd"].setText("R/DR: -")
            card["debug_a"].setText("A: -")
            card["debug_xyiq"].setText("x/y/I/Q: -")
            
            # Draw shear arrow if shear data is available (not drawn for PZR/555 mode)
            if index < len(shear_results) and getattr(self, 'device_mode', 'adc') != '555':
                heatmap_shear, shear_result = shear_results[index]
                # Scale shear coordinates to heatmap space
                center_x = (float(HEATMAP_WIDTH) - 1.0) / 2.0
                center_y = (float(HEATMAP_HEIGHT) - 1.0) / 2.0
                radius = min(float(HEATMAP_WIDTH), float(HEATMAP_HEIGHT)) * 0.48
                arrow_end_x = float(shear_result.shear_x) * radius * getattr(self, "shear_arrow_scale_spin", None).value() if hasattr(self, "shear_arrow_scale_spin") else float(shear_result.shear_x) * radius
                arrow_end_y = float(shear_result.shear_y) * radius * getattr(self, "shear_arrow_scale_spin", None).value() if hasattr(self, "shear_arrow_scale_spin") else float(shear_result.shear_y) * radius
                arrow_length = math.hypot(arrow_end_x, arrow_end_y)
                rel = min(arrow_length / (self.HEATMAP_VIEW_EXTENT * radius), 1.0)
                has_arrow = float(shear_result.shear_magnitude) > 1e-6 and (abs(arrow_end_x) > 1e-6 or abs(arrow_end_y) > 1e-6)
                if has_arrow:
                    head_len = SHEAR_ARROW_HEAD_LENGTH_BASE_PX + rel * SHEAR_ARROW_HEAD_LENGTH_AMPLIFIER
                    card["arrow_line"].setPen(pg.mkPen((235, 80, 60), width=3.0))
                    card["arrow_line"].setData([center_x, center_x + arrow_end_x], [center_y, center_y + arrow_end_y])
                    tip_x, tip_y = self._arrow_head_tip_position(card, arrow_end_x, arrow_end_y, head_len)
                    card["arrow_head"].setPos(center_x + tip_x, center_y + tip_y)
                    # Account for inverted Y-axis in heatmap by negating arrow_end_y
                    card["arrow_head"].setStyle(angle=self._arrow_item_angle_from_vector(arrow_end_x, -arrow_end_y), headLen=head_len)
                    card["arrow_line"].setVisible(True)
                    card["arrow_head"].setVisible(True)
                else:
                    card["arrow_line"].setData([], [])
                    card["arrow_line"].setVisible(False)
                    card["arrow_head"].setVisible(False)
            else:
                card["arrow_line"].setData([], [])
                card["arrow_line"].setVisible(False)
                card["arrow_head"].setVisible(False)

    def show_heatmap_channel_warning(self, current_channels, required_channels="5"):
        self.heatmap_status_label.setText(f"Heatmap requires {required_channels} channels (currently {current_channels} selected)")

    def clear_heatmap_channel_warning(self):
        self.heatmap_status_label.setText("")
