from __future__ import annotations

import math
import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config_constants import (
    HEATMAP_HEIGHT,
    HEATMAP_WIDTH,
    MAX_SENSOR_PACKAGES,
    SHEAR_ARROW_HEAD_LENGTH_AMPLIFIER,
    SHEAR_ARROW_HEAD_LENGTH_BASE_PX,
    SHEAR_ARROW_SCALE,
    SHEAR_ARROW_THICKNESS_AMPLIFIER,
    SHEAR_BASELINE_ALPHA,
    SHEAR_CHANNEL_BASELINES,
    SHEAR_CHANNEL_GAINS,
    SHEAR_CONFIDENCE_SIGNAL_REF,
    SHEAR_CONDITIONING_ALPHA,
    SHEAR_DEADBAND_THRESHOLD,
    SHEAR_GAUSSIAN_SIGMA_X,
    SHEAR_GAUSSIAN_SIGMA_Y,
    SHEAR_INTEGRATION_WINDOW_MS,
    SHEAR_INTENSITY_SCALE,
)


class ShearPanelMixin:
    SHEAR_VIEW_EXTENT = 1.25
    SHEAR_SENSOR_RADIUS = 0.72

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

    def enable_shear_settings_autosave(self):
        self._shear_autosave_enabled = True

    def _get_last_shear_settings_path(self):
        return Path.home() / ".adc_streamer" / "shear" / "last_used_shear_settings.json"

    def _serialize_shear_settings(self):
        return {"version": 1, "shear_settings": self.get_shear_settings()}

    def _apply_shear_settings(self, settings):
        if not settings:
            return False
        changed = False
        for key, widget in [
            ("integration_window_ms", getattr(self, "shear_window_spin", None)),
            ("conditioning_alpha", getattr(self, "shear_conditioning_alpha_spin", None)),
            ("baseline_alpha", getattr(self, "shear_baseline_alpha_spin", None)),
            ("deadband_threshold", getattr(self, "shear_deadband_spin", None)),
            ("confidence_signal_ref", getattr(self, "shear_confidence_ref_spin", None)),
            ("blob_sigma_x", getattr(self, "shear_sigma_x_spin", None)),
            ("blob_sigma_y", getattr(self, "shear_sigma_y_spin", None)),
            ("intensity_scale", getattr(self, "shear_intensity_scale_spin", None)),
            ("arrow_scale", getattr(self, "shear_arrow_scale_spin", None)),
        ]:
            if key in settings and widget is not None:
                widget.setValue(float(settings[key]))
                changed = True
        for label, spin in zip(["C", "R", "B", "L", "T"], getattr(self, "shear_gain_spins", [])):
            if label in settings.get("sensor_gains", {}):
                spin.setValue(float(settings["sensor_gains"][label]))
                changed = True
        for label, spin in zip(["C", "R", "B", "L", "T"], getattr(self, "shear_baseline_spins", [])):
            if label in settings.get("sensor_baselines", {}):
                spin.setValue(float(settings["sensor_baselines"][label]))
                changed = True
        return changed

    def save_shear_settings_to_path(self, file_path, log_message=True):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(self._serialize_shear_settings(), handle, indent=2)
        if log_message:
            self.log_status(f"Saved shear settings: {path}")

    def load_shear_settings_from_path(self, file_path, log_message=True):
        path = Path(file_path)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        settings = payload.get("shear_settings", payload)
        applied = self._apply_shear_settings(settings)
        if log_message:
            self.log_status(f"Loaded shear settings: {path}" if applied else f"Shear settings file loaded, no applicable fields: {path}")
        return applied

    def save_last_shear_settings(self):
        if not getattr(self, "_shear_autosave_enabled", False):
            return
        try:
            self.save_shear_settings_to_path(self._get_last_shear_settings_path(), log_message=False)
        except Exception as exc:
            self.log_status(f"Warning: could not save last shear settings: {exc}")

    def load_last_shear_settings(self):
        path = self._get_last_shear_settings_path()
        if not path.exists():
            return False
        try:
            return self.load_shear_settings_from_path(path, log_message=True)
        except Exception as exc:
            self.log_status(f"Warning: could not load last shear settings: {exc}")
            return False

    def on_save_shear_settings_clicked(self):
        default_dir = self._get_last_shear_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Shear Settings", str(default_dir / "shear_settings.json"), "JSON Files (*.json);;All Files (*)")
        if file_path:
            self.save_shear_settings_to_path(file_path, log_message=True)

    def on_load_shear_settings_clicked(self):
        default_dir = self._get_last_shear_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Shear Settings", str(default_dir), "JSON Files (*.json);;All Files (*)")
        if file_path:
            self.load_shear_settings_from_path(file_path, log_message=True)
            self.save_last_shear_settings()

    def _connect_shear_settings_autosave(self):
        widgets = [
            self.shear_window_spin, self.shear_conditioning_alpha_spin, self.shear_baseline_alpha_spin,
            self.shear_deadband_spin, self.shear_confidence_ref_spin, self.shear_sigma_x_spin,
            self.shear_sigma_y_spin, self.shear_intensity_scale_spin, self.shear_arrow_scale_spin,
        ]
        widgets.extend(getattr(self, "shear_gain_spins", []))
        widgets.extend(getattr(self, "shear_baseline_spins", []))
        for widget in widgets:
            widget.valueChanged.connect(self.save_last_shear_settings)

    def _create_shear_card(self, package_index):
        group = QGroupBox(self._get_channel_group_title(package_index))
        layout = QVBoxLayout()
        plot_widget = pg.GraphicsLayoutWidget()
        plot_widget.setMinimumSize(220, 220)
        plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plot_widget.setBackground("k")
        plot = plot_widget.addPlot()
        plot.setAspectLocked(True, ratio=1.0)
        plot.showAxis("left", False)
        plot.showAxis("bottom", False)
        plot.setMouseEnabled(x=False, y=False)
        plot.disableAutoRange()
        image = pg.ImageItem()
        image.setColorMap(pg.colormap.get("viridis"))
        image.setImage(np.full((HEATMAP_HEIGHT, HEATMAP_WIDTH), np.nan, dtype=np.float32), autoLevels=False, levels=(0, 1))
        image.setRect(QRectF(-self.SHEAR_VIEW_EXTENT, -self.SHEAR_VIEW_EXTENT, 2.0 * self.SHEAR_VIEW_EXTENT, 2.0 * self.SHEAR_VIEW_EXTENT))
        # plot.addItem(image)  # Removed heatmap visualization
        arrow_line = pg.PlotDataItem([], [], pen=pg.mkPen((235, 80, 60), width=3))
        arrow_line.setZValue(10)
        plot.addItem(arrow_line)
        arrow_head = pg.ArrowItem(angle=0.0, headLen=SHEAR_ARROW_HEAD_LENGTH_BASE_PX, tipAngle=28, baseAngle=20, brush=(235, 80, 60), pen=pg.mkPen((235, 80, 60)))
        arrow_head.setZValue(11)
        plot.addItem(arrow_head)
        cop_marker = pg.ScatterPlotItem([0.0], [0.0], symbol="o", size=1, brush=pg.mkBrush(255, 255, 255, 0), pen=pg.mkPen((255, 255, 255, 0), width=0))
        cop_marker.setZValue(12)
        plot.addItem(cop_marker)
        row1 = QHBoxLayout()
        mag = QLabel("Magnitude: 0.000")
        ang = QLabel("Angle: +0.0 deg")
        for label in [mag, ang]:
            label.setStyleSheet("font-weight: bold; font-family: monospace;")
            row1.addWidget(label)
        row1.addStretch()
        row2 = QHBoxLayout()
        cop_x = QLabel("X_CoP: +0.000")
        cop_y = QLabel("Y_CoP: +0.000")
        conf = QLabel("Conf: 0.00")
        vec = QLabel("V: (+0.000, +0.000)")
        for label in [cop_x, cop_y, conf]:
            label.setStyleSheet("font-weight: bold; font-family: monospace;")
        vec.setStyleSheet("font-family: monospace;")
        for label in [cop_x, cop_y, conf, vec]:
            row2.addWidget(label)
        row2.addStretch()
        layout.addWidget(plot_widget)
        layout.addLayout(row1)
        layout.addLayout(row2)
        group.setLayout(layout)
        return {
            "group": group, "plot": plot, "image": image, "arrow_line": arrow_line, "arrow_head": arrow_head, "cop_marker": cop_marker,
            "mag": mag, "ang": ang, "cop_x": cop_x, "cop_y": cop_y, "conf": conf, "vec": vec, "circle": None, "marker_labels": [], "markers": [],
        }

    def create_shear_tab(self):
        shear_widget = QWidget()
        layout = QVBoxLayout()
        capture_row = QHBoxLayout()
        capture_row.addStretch()
        self.shear_capture_button = QPushButton("Capture Data")
        self.shear_capture_button.setCheckable(True)
        self.shear_capture_button.toggled.connect(self.set_visualization_capture_data_enabled)
        capture_row.addWidget(self.shear_capture_button)
        layout.addLayout(capture_row)
        display = self.create_shear_display()
        screen = QApplication.primaryScreen()
        if screen is not None:
            height = screen.availableGeometry().height()
            display.setMinimumHeight(max(360, int(height * 0.52)))
            display.setMaximumHeight(max(360, int(height * 0.88)))
        layout.addWidget(display, stretch=10)
        settings = self.create_shear_settings()
        settings.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.shear_settings_scroll = QScrollArea()
        self.shear_settings_scroll.setWidgetResizable(False)
        self.shear_settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.shear_settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.shear_settings_scroll.setWidget(settings)
        self.shear_settings_scroll.setMaximumHeight(240)
        layout.addWidget(self.shear_settings_scroll, stretch=2)
        shear_widget.setLayout(layout)
        if hasattr(self, "sync_visualization_capture_buttons"):
            self.sync_visualization_capture_buttons()
        return shear_widget

    def create_shear_display(self):
        group = QGroupBox("Shear / CoP Visualization")
        layout = QVBoxLayout()
        grid_axis = np.linspace(-self.SHEAR_VIEW_EXTENT, self.SHEAR_VIEW_EXTENT, HEATMAP_WIDTH, dtype=np.float64)
        self.shear_x_grid, self.shear_y_grid = np.meshgrid(grid_axis, grid_axis)
        grid = QGridLayout()
        self.shear_cards = []
        for package_index in range(MAX_SENSOR_PACKAGES):
            card = self._create_shear_card(package_index)
            self.shear_cards.append(card)
            grid.addWidget(card["group"], package_index // 2, package_index % 2)
            self._configure_shear_plot_view(card)
            card["plot"].getViewBox().sigResized.connect(lambda *args, idx=package_index: self._on_shear_view_resized(idx))
        layout.addLayout(grid)
        self.shear_status_label = QLabel("")
        self.shear_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.shear_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.shear_status_label)
        group.setLayout(layout)
        self._add_shear_background_overlay()
        self.update_visible_shear_cards(1)
        return group

    def _configure_shear_plot_view(self, card):
        view_box = card["plot"].getViewBox()
        rect = view_box.sceneBoundingRect()
        width = max(float(rect.width()), 1.0)
        height = max(float(rect.height()), 1.0)
        aspect = width / height
        if aspect >= 1.0:
            x_extent = self.SHEAR_VIEW_EXTENT * aspect
            y_extent = self.SHEAR_VIEW_EXTENT
        else:
            x_extent = self.SHEAR_VIEW_EXTENT
            y_extent = self.SHEAR_VIEW_EXTENT / aspect
        card["plot"].setXRange(-x_extent, x_extent, padding=0.0)
        card["plot"].setYRange(-y_extent, y_extent, padding=0.0)
        card["plot"].setLimits(xMin=-x_extent, xMax=x_extent, yMin=-y_extent, yMax=y_extent)

    def _on_shear_view_resized(self, card_index):
        self._configure_shear_plot_view(self.shear_cards[card_index])

    def _arrow_item_angle_from_vector(self, dx: float, dy: float) -> float:
        return math.degrees(math.atan2(float(-dy), float(dx))) - 180.0

    def _arrow_head_tip_position(self, card, line_end_x: float, line_end_y: float, head_length_px: float):
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

    def _add_shear_background_overlay(self):
        theta = np.linspace(0.0, 2.0 * np.pi, 200)
        positions = {
            "R": (self.SHEAR_SENSOR_RADIUS, 0.0),
            "B": (0.0, -self.SHEAR_SENSOR_RADIUS),
            "C": (0.0, 0.0),
            "L": (-self.SHEAR_SENSOR_RADIUS, 0.0),
            "T": (0.0, self.SHEAR_SENSOR_RADIUS),
        }
        mapping = self.get_active_channel_sensor_map() if hasattr(self, "get_active_channel_sensor_map") else []
        numbers = {label: str(index + 1) for index, label in enumerate(mapping)}
        for card in getattr(self, "shear_cards", []):
            circle = pg.PlotDataItem(self.SHEAR_SENSOR_RADIUS * np.cos(theta), self.SHEAR_SENSOR_RADIUS * np.sin(theta), pen=pg.mkPen((200, 200, 200, 160), width=2))
            circle.setZValue(5)
            card["plot"].addItem(circle, ignoreBounds=True)
            card["circle"] = circle
            card["markers"] = []
            card["marker_labels"] = []
            for sensor_name, (x_pos, y_pos) in positions.items():
                marker = pg.ScatterPlotItem([x_pos], [y_pos], symbol="s", size=14, brush=pg.mkBrush(230, 230, 230, 200), pen=pg.mkPen(120, 120, 120, 200))
                marker.setZValue(6)
                card["plot"].addItem(marker, ignoreBounds=True)
                card["markers"].append(marker)
                label = pg.TextItem(numbers.get(sensor_name, sensor_name), color=(60, 60, 60))
                label.setAnchor((0.5, 0.5))
                label.setPos(x_pos, y_pos)
                label.setZValue(7)
                card["plot"].addItem(label, ignoreBounds=True)
                card["marker_labels"].append(label)

    def refresh_shear_background_overlay(self):
        mapping = self.get_active_channel_sensor_map() if hasattr(self, "get_active_channel_sensor_map") else []
        numbers = {label: str(index + 1) for index, label in enumerate(mapping)}
        for card in getattr(self, "shear_cards", []):
            for sensor_name, label in zip(["R", "B", "C", "L", "T"], card["marker_labels"]):
                label.setText(numbers.get(sensor_name, sensor_name))

    def update_visible_shear_cards(self, visible_count):
        for index, card in enumerate(getattr(self, "shear_cards", [])):
            card["group"].setTitle(self._get_channel_group_title(index))
            card["group"].setVisible(index < visible_count)

    def create_shear_settings(self):
        group = QGroupBox("Shear Settings")
        main_layout = QVBoxLayout()
        actions = QHBoxLayout()
        self.save_shear_settings_btn = QPushButton("Save Settings...")
        self.save_shear_settings_btn.clicked.connect(self.on_save_shear_settings_clicked)
        actions.addWidget(self.save_shear_settings_btn)
        self.load_shear_settings_btn = QPushButton("Load Settings...")
        self.load_shear_settings_btn.clicked.connect(self.on_load_shear_settings_clicked)
        actions.addWidget(self.load_shear_settings_btn)
        actions.addStretch()
        main_layout.addLayout(actions)

        signal_group = QGroupBox("Signal Processing")
        signal_layout = QGridLayout()
        signal_layout.addWidget(QLabel("Integration Window (ms):"), 0, 0)
        self.shear_window_spin = QDoubleSpinBox()
        self.shear_window_spin.setRange(1.0, 500.0)
        self.shear_window_spin.setDecimals(1)
        self.shear_window_spin.setValue(SHEAR_INTEGRATION_WINDOW_MS)
        signal_layout.addWidget(self.shear_window_spin, 0, 1)
        signal_layout.addWidget(QLabel("Conditioning Alpha:"), 0, 2)
        self.shear_conditioning_alpha_spin = QDoubleSpinBox()
        self.shear_conditioning_alpha_spin.setRange(0.0, 1.0)
        self.shear_conditioning_alpha_spin.setDecimals(3)
        self.shear_conditioning_alpha_spin.setSingleStep(0.01)
        self.shear_conditioning_alpha_spin.setValue(SHEAR_CONDITIONING_ALPHA)
        signal_layout.addWidget(self.shear_conditioning_alpha_spin, 0, 3)
        signal_layout.addWidget(QLabel("Baseline Alpha:"), 1, 0)
        self.shear_baseline_alpha_spin = QDoubleSpinBox()
        self.shear_baseline_alpha_spin.setRange(0.0, 1.0)
        self.shear_baseline_alpha_spin.setDecimals(3)
        self.shear_baseline_alpha_spin.setSingleStep(0.01)
        self.shear_baseline_alpha_spin.setValue(SHEAR_BASELINE_ALPHA)
        signal_layout.addWidget(self.shear_baseline_alpha_spin, 1, 1)
        signal_layout.addWidget(QLabel("Deadband:"), 1, 2)
        self.shear_deadband_spin = QDoubleSpinBox()
        self.shear_deadband_spin.setRange(0.0, 1e6)
        self.shear_deadband_spin.setDecimals(6)
        self.shear_deadband_spin.setValue(SHEAR_DEADBAND_THRESHOLD)
        signal_layout.addWidget(self.shear_deadband_spin, 1, 3)
        signal_layout.addWidget(QLabel("Confidence Ref:"), 1, 4)
        self.shear_confidence_ref_spin = QDoubleSpinBox()
        self.shear_confidence_ref_spin.setRange(1e-6, 1e6)
        self.shear_confidence_ref_spin.setDecimals(6)
        self.shear_confidence_ref_spin.setValue(SHEAR_CONFIDENCE_SIGNAL_REF)
        signal_layout.addWidget(self.shear_confidence_ref_spin, 1, 5)
        signal_group.setLayout(signal_layout)
        main_layout.addWidget(signal_group)

        calibration_group = QGroupBox("Per-Sensor Calibration")
        calibration_layout = QVBoxLayout()
        self.shear_gain_spins = []
        row = QHBoxLayout()
        row.addWidget(QLabel("Gain [C,R,B,L,T]:"))
        for label, value in zip(["C", "R", "B", "L", "T"], SHEAR_CHANNEL_GAINS):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(4)
            spin.setValue(value)
            spin.setPrefix(f"{label}: ")
            self.shear_gain_spins.append(spin)
            row.addWidget(spin)
        row.addStretch()
        calibration_layout.addLayout(row)
        self.shear_baseline_spins = []
        row = QHBoxLayout()
        row.addWidget(QLabel("Baseline [C,R,B,L,T]:"))
        for label, value in zip(["C", "R", "B", "L", "T"], SHEAR_CHANNEL_BASELINES):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1e6)
            spin.setDecimals(6)
            spin.setValue(value)
            spin.setPrefix(f"{label}: ")
            self.shear_baseline_spins.append(spin)
            row.addWidget(spin)
        row.addStretch()
        calibration_layout.addLayout(row)
        calibration_group.setLayout(calibration_layout)
        main_layout.addWidget(calibration_group)

        viz_group = QGroupBox("Visualization")
        viz_layout = QGridLayout()
        viz_layout.addWidget(QLabel("Gaussian Sigma X:"), 0, 0)
        self.shear_sigma_x_spin = QDoubleSpinBox()
        self.shear_sigma_x_spin.setRange(0.01, 2.0)
        self.shear_sigma_x_spin.setDecimals(3)
        self.shear_sigma_x_spin.setValue(SHEAR_GAUSSIAN_SIGMA_X)
        viz_layout.addWidget(self.shear_sigma_x_spin, 0, 1)
        viz_layout.addWidget(QLabel("Gaussian Sigma Y:"), 0, 2)
        self.shear_sigma_y_spin = QDoubleSpinBox()
        self.shear_sigma_y_spin.setRange(0.01, 2.0)
        self.shear_sigma_y_spin.setDecimals(3)
        self.shear_sigma_y_spin.setValue(SHEAR_GAUSSIAN_SIGMA_Y)
        viz_layout.addWidget(self.shear_sigma_y_spin, 0, 3)
        viz_layout.addWidget(QLabel("Intensity Scale:"), 1, 0)
        self.shear_intensity_scale_spin = QDoubleSpinBox()
        self.shear_intensity_scale_spin.setRange(0.0, 500.0)
        self.shear_intensity_scale_spin.setDecimals(6)
        self.shear_intensity_scale_spin.setSingleStep(0.01)
        self.shear_intensity_scale_spin.setValue(SHEAR_INTENSITY_SCALE)
        viz_layout.addWidget(self.shear_intensity_scale_spin, 1, 1)
        viz_layout.addWidget(QLabel("Arrow Scale:"), 1, 2)
        self.shear_arrow_scale_spin = QDoubleSpinBox()
        self.shear_arrow_scale_spin.setRange(0.0, 5.0)
        self.shear_arrow_scale_spin.setDecimals(3)
        self.shear_arrow_scale_spin.setValue(SHEAR_ARROW_SCALE)
        viz_layout.addWidget(self.shear_arrow_scale_spin, 1, 3)
        viz_group.setLayout(viz_layout)
        main_layout.addWidget(viz_group)

        self._connect_shear_settings_autosave()
        group.setLayout(main_layout)
        return group

    def get_shear_settings(self):
        return {
            "integration_window_ms": self.shear_window_spin.value(),
            "conditioning_alpha": self.shear_conditioning_alpha_spin.value(),
            "baseline_alpha": self.shear_baseline_alpha_spin.value(),
            "deadband_threshold": self.shear_deadband_spin.value(),
            "confidence_signal_ref": self.shear_confidence_ref_spin.value(),
            "sensor_gains": {label: spin.value() for label, spin in zip(["C", "R", "B", "L", "T"], self.shear_gain_spins)},
            "sensor_baselines": {label: spin.value() for label, spin in zip(["C", "R", "B", "L", "T"], self.shear_baseline_spins)},
            "blob_sigma_x": self.shear_sigma_x_spin.value(),
            "blob_sigma_y": self.shear_sigma_y_spin.value(),
            "intensity_scale": self.shear_intensity_scale_spin.value(),
            "arrow_scale": self.shear_arrow_scale_spin.value(),
            "channel_sensor_map": self.get_active_channel_sensor_map() if hasattr(self, "get_active_channel_sensor_map") else [],
        }

    def update_shear_display(self, package_results):
        self.update_visible_shear_cards(len(package_results))
        circle_mask = (self.shear_x_grid ** 2 + self.shear_y_grid ** 2) <= (self.SHEAR_SENSOR_RADIUS ** 2)
        for index, (heatmap, result) in enumerate(package_results):
            card = self.shear_cards[index]
            card["group"].setTitle(self._get_channel_group_title(index))
            masked = np.where(circle_mask, heatmap, 0.0)
            display = np.where(masked > 0.0, np.power(masked, 0.5), np.nan)
            card["image"].setImage(display.T, autoLevels=False, levels=(0, 1))
            card["image"].setRect(QRectF(-self.SHEAR_VIEW_EXTENT, -self.SHEAR_VIEW_EXTENT, 2.0 * self.SHEAR_VIEW_EXTENT, 2.0 * self.SHEAR_VIEW_EXTENT))
            arrow_end_x = result.shear_x * self.shear_arrow_scale_spin.value()
            arrow_end_y = result.shear_y * self.shear_arrow_scale_spin.value()
            arrow_length = math.hypot(arrow_end_x, arrow_end_y)
            rel = min(arrow_length / self.SHEAR_VIEW_EXTENT, 1.0)
            has_arrow = result.shear_magnitude > 1e-6 and (abs(arrow_end_x) > 1e-6 or abs(arrow_end_y) > 1e-6)
            if has_arrow:
                head_len = SHEAR_ARROW_HEAD_LENGTH_BASE_PX + rel * SHEAR_ARROW_HEAD_LENGTH_AMPLIFIER
                card["arrow_line"].setPen(pg.mkPen((235, 80, 60), width=3.0 + rel * SHEAR_ARROW_THICKNESS_AMPLIFIER))
                card["arrow_line"].setData([0.0, arrow_end_x], [0.0, arrow_end_y])
                tip_x, tip_y = self._arrow_head_tip_position(card, arrow_end_x, arrow_end_y, head_len)
                card["arrow_head"].setPos(tip_x, tip_y)
                card["arrow_head"].setStyle(angle=self._arrow_item_angle_from_vector(arrow_end_x, arrow_end_y), headLen=head_len)
                card["arrow_line"].setVisible(True)
                card["arrow_head"].setVisible(True)
            else:
                card["arrow_line"].setData([], [])
                card["arrow_line"].setVisible(False)
                card["arrow_head"].setVisible(False)
            card["cop_marker"].setData([float(result.cop_x) * self.SHEAR_SENSOR_RADIUS], [float(result.cop_y) * self.SHEAR_SENSOR_RADIUS])
            card["mag"].setText(f"Magnitude: {result.shear_magnitude:.3f}")
            card["ang"].setText(f"Angle: {result.shear_angle_deg:+.1f} deg")
            card["cop_x"].setText(f"X_CoP: {result.cop_x:+.3f}")
            card["cop_y"].setText(f"Y_CoP: {result.cop_y:+.3f}")
            card["conf"].setText(f"Conf: {result.confidence:.2f}")
            card["vec"].setText(f"V: ({result.shear_x:+.3f}, {result.shear_y:+.3f})")

    def show_shear_channel_warning(self, current_channels, required_channels="5"):
        self.shear_status_label.setText(f"Shear requires {required_channels} channels (currently {current_channels} selected)")

    def clear_shear_channel_warning(self):
        self.shear_status_label.setText("")
