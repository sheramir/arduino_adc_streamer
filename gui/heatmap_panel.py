from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QFileDialog, QCheckBox,
    QScrollArea, QApplication, QSizePolicy,
)
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import numpy as np
import json
from pathlib import Path

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
    SHEAR_ARROW_SCALE, SHEAR_ARROW_THICKNESS_AMPLIFIER,
)


class HeatmapPanelMixin:
    HEATMAP_VIEW_EXTENT = 1.25  # Scaling factor for arrow visualization

    def _get_heatmap_mode_key(self) -> str:
        is_pzr_mode = bool(hasattr(self, "is_555_analyzer_mode") and self.is_555_analyzer_mode())
        return "pzr" if is_pzr_mode else "pzt"

    def _get_heatmap_setting_keys_for_mode(self, mode_key: str | None = None) -> set[str]:
        mode = (mode_key or self._get_heatmap_mode_key()).lower()
        if mode == "pzr":
            return {
                "sensor_calibration",
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
            }
        return {
            "sensor_calibration",
            "sensor_noise_floor",
            "sensor_size",
            "intensity_scale",
            "blob_sigma_x",
            "blob_sigma_y",
            "smooth_alpha",
            "rms_window_ms",
            "dc_removal_mode",
            "hpf_cutoff_hz",
            "magnitude_threshold",
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
        if hasattr(self, 'is_array_sensor_selection_mode') and self.is_array_sensor_selection_mode():
            selected = list(self.config.get('selected_array_sensors', [])) if hasattr(self, 'config') else []
            if package_index < len(selected):
                return str(selected[package_index])

        channels = self.config.get("channels", []) if hasattr(self, "config") else []
        unique_channels = []
        for channel in channels:
            if channel not in unique_channels:
                unique_channels.append(channel)
        start = package_index * 5
        end = start + 5
        group_channels = unique_channels[start:end]
        if group_channels:
            return "CH " + ",".join(str(channel) for channel in group_channels)
        return f"CH Group {package_index + 1}"

    def enable_heatmap_settings_autosave(self):
        self._heatmap_autosave_enabled = True

    def _get_last_heatmap_settings_path(self):
        mode_key = self._get_heatmap_mode_key()
        return Path.home() / ".adc_streamer" / "heatmap" / f"last_used_heatmap_settings_{mode_key}.json"

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
            if "sensor_calibration" in mode_settings and isinstance(mode_settings["sensor_calibration"], list):
                values = mode_settings["sensor_calibration"]
                is_555_mode = bool(hasattr(self, "is_555_analyzer_mode") and self.is_555_analyzer_mode())
                if is_555_mode and len(values) == 4 and len(self.sensor_gain_spins) >= 5:
                    values = [float(values[3]), float(values[1]), float(values[0]), float(values[2]), self.sensor_gain_spins[4].value()]
                for spin, value in zip(self.sensor_gain_spins, values):
                    spin.setValue(float(value))
                    changed = True
            if "sensor_noise_floor" in mode_settings and isinstance(mode_settings["sensor_noise_floor"], list):
                for spin, value in zip(self.sensor_noise_spins, mode_settings["sensor_noise_floor"]):
                    spin.setValue(float(value))
                    changed = True
            scalar_map = [
                ("sensor_size", self.sensor_size_spin),
                ("intensity_scale", self.intensity_scale_spin),
                ("blob_sigma_x", self.blob_sigma_x_spin),
                ("blob_sigma_y", self.blob_sigma_y_spin),
                ("smooth_alpha", self.smooth_alpha_spin),
                ("hpf_cutoff_hz", self.hpf_cutoff_spin),
                ("magnitude_threshold", self.magnitude_threshold_spin),
                ("delta_threshold", getattr(self, "r555_delta_threshold_spin", None)),
                ("delta_release_threshold", getattr(self, "r555_delta_release_spin", None)),
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
        finally:
            self._heatmap_settings_loading = False
        return changed

    def save_heatmap_settings_to_path(self, file_path, log_message=True):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(self._serialize_heatmap_settings(), handle, indent=2)
        if log_message:
            self.log_status(f"Saved heatmap settings: {path}")

    def load_heatmap_settings_from_path(self, file_path, log_message=True):
        path = Path(file_path)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        settings = payload.get("heatmap_settings", payload)
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
        default_name = f"heatmap_settings_{self._get_heatmap_mode_key()}.json"
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
        for widget in [
            self.rms_window_spin, self.dc_removal_combo, self.hpf_cutoff_spin, self.magnitude_threshold_spin,
            self.sensor_size_spin, self.intensity_scale_spin, self.blob_sigma_x_spin, self.blob_sigma_y_spin, self.smooth_alpha_spin,
            self.r555_delta_threshold_spin, self.r555_delta_release_spin, self.r555_cop_smooth_alpha_spin,
            self.r555_intensity_min_spin, self.r555_intensity_max_spin, self.r555_axis_adapt_spin,
            self.r555_map_smooth_alpha_spin,
        ]:
            signal = getattr(widget, "valueChanged", None)
            if signal is not None:
                signal.connect(self.save_last_heatmap_settings)
        self.dc_removal_combo.currentIndexChanged.connect(self.save_last_heatmap_settings)
        for spin in self.sensor_gain_spins + self.sensor_noise_spins:
            spin.valueChanged.connect(self.save_last_heatmap_settings)


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
        actions.addStretch()
        main_layout.addLayout(actions)

        signal_group = QGroupBox("Signal Processing")
        signal_layout = QGridLayout()
        signal_layout.addWidget(QLabel("RMS Window (ms):"), 0, 0)
        self.rms_window_spin = QSpinBox()
        self.rms_window_spin.setRange(2, 5000)
        self.rms_window_spin.setValue(RMS_WINDOW_MS)
        signal_layout.addWidget(self.rms_window_spin, 0, 1)
        signal_layout.addWidget(QLabel("DC Removal:"), 0, 2)
        self.dc_removal_combo = QComboBox()
        self.dc_removal_combo.addItems(["Bias (2s)", "High-pass"])
        self.dc_removal_combo.setCurrentIndex(0 if HEATMAP_DC_REMOVAL_MODE == "bias" else 1)
        signal_layout.addWidget(self.dc_removal_combo, 0, 3)
        signal_layout.addWidget(QLabel("HPF Cutoff (Hz):"), 1, 0)
        self.hpf_cutoff_spin = QDoubleSpinBox()
        self.hpf_cutoff_spin.setRange(0.01, 50.0)
        self.hpf_cutoff_spin.setDecimals(3)
        self.hpf_cutoff_spin.setValue(HPF_CUTOFF_HZ)
        signal_layout.addWidget(self.hpf_cutoff_spin, 1, 1)
        signal_layout.addWidget(QLabel("Threshold:"), 1, 2)
        self.magnitude_threshold_spin = QDoubleSpinBox()
        self.magnitude_threshold_spin.setRange(0.0, 1e6)
        self.magnitude_threshold_spin.setDecimals(4)
        self.magnitude_threshold_spin.setValue(HEATMAP_THRESHOLD)
        signal_layout.addWidget(self.magnitude_threshold_spin, 1, 3)
        self.dc_removal_combo.currentIndexChanged.connect(self._on_dc_mode_changed)
        self._on_dc_mode_changed(self.dc_removal_combo.currentIndex())
        self.heatmap_signal_group = signal_group
        signal_group.setLayout(signal_layout)
        main_layout.addWidget(signal_group)

        pzr_group = QGroupBox("PZR Heatmap Settings")
        pzr_layout = QGridLayout()
        pzr_layout.addWidget(QLabel("Noise Threshold (%):"), 0, 0)
        self.r555_delta_threshold_spin = QDoubleSpinBox()
        self.r555_delta_threshold_spin.setRange(0.0, 1000.0)
        self.r555_delta_threshold_spin.setDecimals(4)
        self.r555_delta_threshold_spin.setValue(R_HEATMAP_DELTA_THRESHOLD)
        pzr_layout.addWidget(self.r555_delta_threshold_spin, 0, 1)

        pzr_layout.addWidget(QLabel("Release Threshold (%):"), 0, 2)
        self.r555_delta_release_spin = QDoubleSpinBox()
        self.r555_delta_release_spin.setRange(0.0, 1000.0)
        self.r555_delta_release_spin.setDecimals(4)
        self.r555_delta_release_spin.setValue(R_HEATMAP_DELTA_RELEASE_THRESHOLD)
        pzr_layout.addWidget(self.r555_delta_release_spin, 0, 3)

        pzr_layout.addWidget(QLabel("CoP Smooth Alpha:"), 1, 0)
        self.r555_cop_smooth_alpha_spin = QDoubleSpinBox()
        self.r555_cop_smooth_alpha_spin.setRange(0.0, 1.0)
        self.r555_cop_smooth_alpha_spin.setDecimals(3)
        self.r555_cop_smooth_alpha_spin.setSingleStep(0.01)
        self.r555_cop_smooth_alpha_spin.setValue(R_HEATMAP_COP_SMOOTH_ALPHA)
        pzr_layout.addWidget(self.r555_cop_smooth_alpha_spin, 1, 1)

        pzr_layout.addWidget(QLabel("Intensity Min (%):"), 1, 2)
        self.r555_intensity_min_spin = QDoubleSpinBox()
        self.r555_intensity_min_spin.setRange(0.0, 1000.0)
        self.r555_intensity_min_spin.setDecimals(4)
        self.r555_intensity_min_spin.setValue(R_HEATMAP_INTENSITY_MIN)
        pzr_layout.addWidget(self.r555_intensity_min_spin, 1, 3)

        pzr_layout.addWidget(QLabel("Intensity Max (%):"), 2, 0)
        self.r555_intensity_max_spin = QDoubleSpinBox()
        self.r555_intensity_max_spin.setRange(0.0, 1000.0)
        self.r555_intensity_max_spin.setDecimals(4)
        self.r555_intensity_max_spin.setValue(R_HEATMAP_INTENSITY_MAX)
        pzr_layout.addWidget(self.r555_intensity_max_spin, 2, 1)

        pzr_layout.addWidget(QLabel("Axis Adapt:"), 2, 2)
        self.r555_axis_adapt_spin = QDoubleSpinBox()
        self.r555_axis_adapt_spin.setRange(0.0, 5.0)
        self.r555_axis_adapt_spin.setDecimals(3)
        self.r555_axis_adapt_spin.setValue(R_HEATMAP_AXIS_ADAPT_STRENGTH)
        pzr_layout.addWidget(self.r555_axis_adapt_spin, 2, 3)

        pzr_layout.addWidget(QLabel("Map Smooth Alpha:"), 3, 0)
        self.r555_map_smooth_alpha_spin = QDoubleSpinBox()
        self.r555_map_smooth_alpha_spin.setRange(0.0, 1.0)
        self.r555_map_smooth_alpha_spin.setDecimals(3)
        self.r555_map_smooth_alpha_spin.setSingleStep(0.01)
        self.r555_map_smooth_alpha_spin.setValue(R_HEATMAP_MAP_SMOOTH_ALPHA)
        pzr_layout.addWidget(self.r555_map_smooth_alpha_spin, 3, 1)
        pzr_group.setLayout(pzr_layout)
        self.heatmap_pzr_group = pzr_group
        main_layout.addWidget(pzr_group)

        calib_group = QGroupBox("Per-Sensor Calibration")
        calib_layout = QVBoxLayout()
        self.sensor_gain_spins = []
        row = QHBoxLayout()
        row.addWidget(QLabel("Gain [T,B,R,L,C]:"))
        for idx, name in enumerate(["T", "B", "R", "L", "C"]):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(4)
            spin.setValue(SENSOR_CALIBRATION[idx])
            spin.setPrefix(f"{name}: ")
            self.sensor_gain_spins.append(spin)
            row.addWidget(spin)
        row.addStretch()
        calib_layout.addLayout(row)
        self.sensor_noise_spins = []
        row = QHBoxLayout()
        row.addWidget(QLabel("Noise Floor [T,B,R,L,C]:"))
        for idx, name in enumerate(["T", "B", "R", "L", "C"]):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1e6)
            spin.setDecimals(4)
            spin.setValue(SENSOR_NOISE_FLOOR[idx])
            spin.setPrefix(f"{name}: ")
            self.sensor_noise_spins.append(spin)
            row.addWidget(spin)
        row.addStretch()
        self.sensor_noise_row_layout = row
        calib_layout.addLayout(row)
        calib_group.setLayout(calib_layout)
        main_layout.addWidget(calib_group)

        params_group = QGroupBox("Heatmap Parameters")
        params_layout = QGridLayout()
        params_layout.addWidget(QLabel("Sensor Size:"), 0, 0)
        self.sensor_size_spin = QDoubleSpinBox()
        self.sensor_size_spin.setRange(0.01, 10000.0)
        self.sensor_size_spin.setDecimals(2)
        self.sensor_size_spin.setValue(SENSOR_SIZE)
        params_layout.addWidget(self.sensor_size_spin, 0, 1)
        params_layout.addWidget(QLabel("Intensity Scale:"), 0, 2)
        self.intensity_scale_spin = QDoubleSpinBox()
        self.intensity_scale_spin.setRange(0.0, 1.0)
        self.intensity_scale_spin.setDecimals(6)
        self.intensity_scale_spin.setSingleStep(0.0001)
        self.intensity_scale_spin.setValue(INTENSITY_SCALE)
        params_layout.addWidget(self.intensity_scale_spin, 0, 3)
        params_layout.addWidget(QLabel("Blob Sigma X:"), 1, 0)
        self.blob_sigma_x_spin = QDoubleSpinBox()
        self.blob_sigma_x_spin.setRange(0.01, 5.0)
        self.blob_sigma_x_spin.setDecimals(4)
        self.blob_sigma_x_spin.setValue(BLOB_SIGMA_X)
        params_layout.addWidget(self.blob_sigma_x_spin, 1, 1)
        params_layout.addWidget(QLabel("Blob Sigma Y:"), 1, 2)
        self.blob_sigma_y_spin = QDoubleSpinBox()
        self.blob_sigma_y_spin.setRange(0.01, 5.0)
        self.blob_sigma_y_spin.setDecimals(4)
        self.blob_sigma_y_spin.setValue(BLOB_SIGMA_Y)
        params_layout.addWidget(self.blob_sigma_y_spin, 1, 3)
        params_layout.addWidget(QLabel("Smooth Alpha:"), 2, 0)
        self.smooth_alpha_spin = QDoubleSpinBox()
        self.smooth_alpha_spin.setRange(0.0, 1.0)
        self.smooth_alpha_spin.setDecimals(3)
        self.smooth_alpha_spin.setSingleStep(0.01)
        self.smooth_alpha_spin.setValue(SMOOTH_ALPHA)
        params_layout.addWidget(self.smooth_alpha_spin, 2, 1)
        params_group.setLayout(params_layout)
        main_layout.addWidget(params_group)

        self._connect_heatmap_settings_autosave()
        self.update_heatmap_ui_for_mode()
        group.setLayout(main_layout)
        return group

    def _on_dc_mode_changed(self, index):
        self.hpf_cutoff_spin.setEnabled(index == 1)

    def get_heatmap_settings(self):
        channel_sensor_map = self.get_active_channel_sensor_map() if hasattr(self, "get_active_channel_sensor_map") else HEATMAP_CHANNEL_SENSOR_MAP
        calibration = [spin.value() for spin in self.sensor_gain_spins]
        
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
        
        return {
            "sensor_calibration": calibration,
            "sensor_noise_floor": [spin.value() for spin in self.sensor_noise_spins],
            "sensor_size": self.sensor_size_spin.value(),
            "intensity_scale": self.intensity_scale_spin.value(),
            "blob_sigma_x": self.blob_sigma_x_spin.value(),
            "blob_sigma_y": self.blob_sigma_y_spin.value(),
            "smooth_alpha": self.smooth_alpha_spin.value(),
            "rms_window_ms": self.rms_window_spin.value(),
            "dc_removal_mode": "bias" if self.dc_removal_combo.currentIndex() == 0 else "highpass",
            "hpf_cutoff_hz": self.hpf_cutoff_spin.value(),
            "magnitude_threshold": self.magnitude_threshold_spin.value(),
            "channel_sensor_map": channel_sensor_map,
            "channel_to_baseline": channel_to_baseline,
            "confidence_intensity_ref": CONFIDENCE_INTENSITY_REF,
            "sigma_spread_factor": SIGMA_SPREAD_FACTOR,
            "delta_threshold": self.r555_delta_threshold_spin.value(),
            "delta_release_threshold": self.r555_delta_release_spin.value(),
            "cop_smooth_alpha": self.r555_cop_smooth_alpha_spin.value(),
            "intensity_min": self.r555_intensity_min_spin.value(),
            "intensity_max": self.r555_intensity_max_spin.value(),
            "axis_adapt_strength": self.r555_axis_adapt_spin.value(),
            "map_smooth_alpha": self.r555_map_smooth_alpha_spin.value(),
        }

    def update_heatmap_ui_for_mode(self):
        is_pzr_mode = self._get_heatmap_mode_key() == "pzr"
        if hasattr(self, "heatmap_signal_group"):
            self.heatmap_signal_group.setVisible(not is_pzr_mode)
        if hasattr(self, "heatmap_pzr_group"):
            self.heatmap_pzr_group.setVisible(is_pzr_mode)
        if hasattr(self, "sensor_noise_row_layout"):
            for idx in range(self.sensor_noise_row_layout.count()):
                widget = self.sensor_noise_row_layout.itemAt(idx).widget()
                if widget is not None:
                    widget.setVisible(not is_pzr_mode)
        mode_key = self._get_heatmap_mode_key()
        if getattr(self, "_last_heatmap_mode_key", None) != mode_key:
            self._last_heatmap_mode_key = mode_key
            self.load_last_heatmap_settings()
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
