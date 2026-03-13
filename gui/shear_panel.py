"""
Shear Panel GUI Component
=========================
Real-time shear / CoP visualization for the 5-channel MG-24 piezo package.
"""

from __future__ import annotations

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
    QVBoxLayout,
    QWidget,
)
import json
import numpy as np
import pyqtgraph as pg
from pathlib import Path

from config_constants import (
    HEATMAP_HEIGHT,
    HEATMAP_WIDTH,
    HEATMAP_CHANNEL_SENSOR_MAP,
    SHEAR_ARROW_SCALE,
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
    """Mixin providing the Shear tab UI."""

    SHEAR_VIEW_EXTENT = 1.25
    SHEAR_SENSOR_RADIUS = 0.72

    def enable_shear_settings_autosave(self):
        self._shear_autosave_enabled = True

    def _get_last_shear_settings_path(self):
        return Path.home() / ".adc_streamer" / "shear" / "last_used_shear_settings.json"

    def _serialize_shear_settings(self):
        return {
            "version": 1,
            "shear_settings": self.get_shear_settings(),
        }

    def _apply_shear_settings(self, settings):
        if not settings:
            return False

        changed = False
        scalar_map = [
            ("integration_window_ms", getattr(self, "shear_window_spin", None)),
            ("conditioning_alpha", getattr(self, "shear_conditioning_alpha_spin", None)),
            ("baseline_alpha", getattr(self, "shear_baseline_alpha_spin", None)),
            ("deadband_threshold", getattr(self, "shear_deadband_spin", None)),
            ("confidence_signal_ref", getattr(self, "shear_confidence_ref_spin", None)),
            ("blob_sigma_x", getattr(self, "shear_sigma_x_spin", None)),
            ("blob_sigma_y", getattr(self, "shear_sigma_y_spin", None)),
            ("intensity_scale", getattr(self, "shear_intensity_scale_spin", None)),
            ("arrow_scale", getattr(self, "shear_arrow_scale_spin", None)),
        ]
        for key, widget in scalar_map:
            if key in settings and widget is not None:
                widget.setValue(float(settings[key]))
                changed = True

        sensor_labels = ["C", "R", "B", "L", "T"]
        gains = settings.get("sensor_gains", {})
        baselines = settings.get("sensor_baselines", {})
        for label, spin in zip(sensor_labels, getattr(self, "shear_gain_spins", [])):
            if label in gains:
                spin.setValue(float(gains[label]))
                changed = True
        for label, spin in zip(sensor_labels, getattr(self, "shear_baseline_spins", [])):
            if label in baselines:
                spin.setValue(float(baselines[label]))
                changed = True

        return changed

    def save_shear_settings_to_path(self, file_path, log_message=True):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._serialize_shear_settings()
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        if log_message:
            self.log_status(f"Saved shear settings: {path}")

    def load_shear_settings_from_path(self, file_path, log_message=True):
        path = Path(file_path)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        settings = payload.get("shear_settings", payload)
        applied = self._apply_shear_settings(settings)

        if log_message:
            if applied:
                self.log_status(f"Loaded shear settings: {path}")
            else:
                self.log_status(f"Shear settings file loaded, no applicable fields: {path}")

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

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Shear Settings",
            str(default_dir / "shear_settings.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return
        try:
            self.save_shear_settings_to_path(file_path, log_message=True)
        except Exception as exc:
            self.log_status(f"Error saving shear settings: {exc}")

    def on_load_shear_settings_clicked(self):
        default_dir = self._get_last_shear_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Shear Settings",
            str(default_dir),
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return
        try:
            self.load_shear_settings_from_path(file_path, log_message=True)
            self.save_last_shear_settings()
        except Exception as exc:
            self.log_status(f"Error loading shear settings: {exc}")

    def _connect_shear_settings_autosave(self):
        widgets = [
            getattr(self, "shear_window_spin", None),
            getattr(self, "shear_conditioning_alpha_spin", None),
            getattr(self, "shear_baseline_alpha_spin", None),
            getattr(self, "shear_deadband_spin", None),
            getattr(self, "shear_confidence_ref_spin", None),
            getattr(self, "shear_sigma_x_spin", None),
            getattr(self, "shear_sigma_y_spin", None),
            getattr(self, "shear_intensity_scale_spin", None),
            getattr(self, "shear_arrow_scale_spin", None),
        ]
        widgets.extend(getattr(self, "shear_gain_spins", []))
        widgets.extend(getattr(self, "shear_baseline_spins", []))
        for widget in widgets:
            if widget is not None:
                widget.valueChanged.connect(self.save_last_shear_settings)

    def create_shear_tab(self):
        shear_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        shear_display = self.create_shear_display()
        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_height = screen.availableGeometry().height()
            min_height = max(300, int(screen_height * 0.4))
            max_height = max(min_height, int(screen_height * 0.65))
            shear_display.setMinimumHeight(min_height)
            shear_display.setMaximumHeight(max_height)
        layout.addWidget(shear_display, stretch=5)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        readouts_panel = self.create_shear_readouts()
        readouts_panel.setMaximumHeight(96)
        bottom_layout.addWidget(readouts_panel)

        settings_panel = self.create_shear_settings()
        self.shear_settings_scroll = QScrollArea()
        self.shear_settings_scroll.setWidgetResizable(True)
        self.shear_settings_scroll.setWidget(settings_panel)
        self.shear_settings_scroll.setMaximumHeight(320)
        bottom_layout.addWidget(self.shear_settings_scroll)

        bottom_widget.setLayout(bottom_layout)
        layout.addWidget(bottom_widget, stretch=4)

        shear_widget.setLayout(layout)
        return shear_widget

    def create_shear_display(self):
        group = QGroupBox("Shear / CoP Visualization")
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.shear_plot_width = HEATMAP_WIDTH
        self.shear_plot_height = HEATMAP_HEIGHT
        grid_axis = np.linspace(-self.SHEAR_VIEW_EXTENT, self.SHEAR_VIEW_EXTENT, self.shear_plot_width, dtype=np.float64)
        self.shear_x_grid, self.shear_y_grid = np.meshgrid(grid_axis, grid_axis)

        self.shear_plot_widget = pg.GraphicsLayoutWidget()
        self.shear_plot = self.shear_plot_widget.addPlot()
        self.shear_plot_widget.setBackground("k")
        self.shear_plot.setAspectLocked(True, ratio=1.0)
        self.shear_plot.showGrid(x=False, y=False)
        self.shear_plot.showAxis("left", False)
        self.shear_plot.showAxis("bottom", False)
        self.shear_plot.setMouseEnabled(x=False, y=False)
        self.shear_plot.disableAutoRange()
        self._configure_shear_plot_view()
        self.shear_plot.getViewBox().sigResized.connect(self._on_shear_view_resized)

        self.shear_image = pg.ImageItem()
        self.shear_image.setRect(
            QRectF(
                -self.SHEAR_VIEW_EXTENT,
                -self.SHEAR_VIEW_EXTENT,
                2.0 * self.SHEAR_VIEW_EXTENT,
                2.0 * self.SHEAR_VIEW_EXTENT,
            )
        )
        self.shear_plot.addItem(self.shear_image)
        self.shear_image.setLookupTable(self._build_shear_lookup_table())
        self.shear_image.setImage(np.zeros((self.shear_plot_height, self.shear_plot_width), dtype=np.float32), autoLevels=False, levels=(0, 1))

        self.shear_arrow_line = pg.PlotDataItem([], [], pen=pg.mkPen((235, 80, 60), width=3))
        self.shear_arrow_line.setZValue(10)
        self.shear_plot.addItem(self.shear_arrow_line)

        self.shear_arrow_head = pg.ArrowItem(angle=0.0, headLen=18, tipAngle=28, baseAngle=20, brush=(235, 80, 60), pen=pg.mkPen((235, 80, 60)))
        self.shear_arrow_head.setZValue(11)
        self.shear_plot.addItem(self.shear_arrow_head)

        self.shear_cop_marker = pg.ScatterPlotItem(
            [0.0],
            [0.0],
            symbol="o",
            size=1,
            brush=pg.mkBrush(255, 255, 255, 0),
            pen=pg.mkPen((255, 255, 255, 0), width=0),
        )
        self.shear_cop_marker.setZValue(12)
        self.shear_plot.addItem(self.shear_cop_marker)

        self._add_shear_background_overlay()
        self._configure_shear_plot_view()

        self.shear_status_label = QLabel("")
        self.shear_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.shear_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.shear_plot_widget)
        layout.addWidget(self.shear_status_label)
        group.setLayout(layout)
        return group

    def _configure_shear_plot_view(self):
        view_box = self.shear_plot.getViewBox()
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

        self.shear_plot.setXRange(-x_extent, x_extent, padding=0.0)
        self.shear_plot.setYRange(-y_extent, y_extent, padding=0.0)
        self.shear_plot.setLimits(
            xMin=-x_extent,
            xMax=x_extent,
            yMin=-y_extent,
            yMax=y_extent,
        )

    def _on_shear_view_resized(self, *args):
        # Keep a stable logical coordinate space when the main window is resized/maximized.
        self._configure_shear_plot_view()

    def _build_shear_lookup_table(self):
        """Use a transparent low end so only the blob changes color, not the background."""
        base = pg.colormap.get("viridis").getLookupTable(alpha=True)
        lut = np.array(base, copy=True)
        if lut.shape[0] > 0:
            lut[0] = [0, 0, 0, 0]
        if lut.shape[0] > 1:
            ramp = np.linspace(0.0, 1.0, lut.shape[0], dtype=np.float64)
            alpha = np.clip((ramp - 0.08) / 0.35, 0.0, 1.0) ** 1.6
            lut[:, 3] = np.round(alpha * 255.0).astype(np.uint8)
            lut[0, 3] = 0
        return lut

    def _add_shear_background_overlay(self):
        theta = np.linspace(0.0, 2.0 * np.pi, 200)
        circle = pg.PlotDataItem(
            self.SHEAR_SENSOR_RADIUS * np.cos(theta),
            self.SHEAR_SENSOR_RADIUS * np.sin(theta),
            pen=pg.mkPen((200, 200, 200, 160), width=2),
        )
        circle.setZValue(5)
        self.shear_plot.addItem(circle, ignoreBounds=True)
        self.shear_circle = circle

        self.shear_marker_items = []
        self.shear_marker_labels = []
        marker_positions = {
            "R": (self.SHEAR_SENSOR_RADIUS, 0.0),
            "B": (0.0, -self.SHEAR_SENSOR_RADIUS),
            "C": (0.0, 0.0),
            "L": (-self.SHEAR_SENSOR_RADIUS, 0.0),
            "T": (0.0, self.SHEAR_SENSOR_RADIUS),
        }
        label_to_number = {
            sensor_label: str(index + 1)
            for index, sensor_label in enumerate(HEATMAP_CHANNEL_SENSOR_MAP)
        }
        for sensor_name, (x_pos, y_pos) in marker_positions.items():
            marker = pg.ScatterPlotItem([x_pos], [y_pos], symbol="s", size=14, brush=pg.mkBrush(230, 230, 230, 200), pen=pg.mkPen(120, 120, 120, 200))
            marker.setZValue(6)
            self.shear_plot.addItem(marker, ignoreBounds=True)
            self.shear_marker_items.append(marker)

            label = pg.TextItem(label_to_number.get(sensor_name, sensor_name), color=(60, 60, 60))
            label.setAnchor((0.5, 0.5))
            label.setPos(x_pos, y_pos)
            label.setZValue(7)
            self.shear_plot.addItem(label, ignoreBounds=True)
            self.shear_marker_labels.append(label)

    def create_shear_readouts(self):
        group = QGroupBox("Shear Readouts")
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        self.shear_magnitude_label = QLabel("Magnitude: 0.000")
        self.shear_magnitude_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        top_row.addWidget(self.shear_magnitude_label)

        self.shear_angle_label = QLabel("Angle: +0.0 deg")
        self.shear_angle_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        top_row.addWidget(self.shear_angle_label)

        self.shear_confidence_label = QLabel("Confidence: 0.00")
        self.shear_confidence_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        top_row.addWidget(self.shear_confidence_label)
        top_row.addStretch()
        layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        self.shear_cop_x_label = QLabel("X_CoP: +0.000")
        self.shear_cop_x_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        bottom_row.addWidget(self.shear_cop_x_label)

        self.shear_cop_y_label = QLabel("Y_CoP: +0.000")
        self.shear_cop_y_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        bottom_row.addWidget(self.shear_cop_y_label)

        self.shear_vector_label = QLabel("Vector: (+0.000, +0.000)")
        self.shear_vector_label.setStyleSheet("font-family: monospace;")
        bottom_row.addWidget(self.shear_vector_label)
        bottom_row.addStretch()
        layout.addLayout(bottom_row)

        group.setLayout(layout)
        return group

    def create_shear_settings(self):
        group = QGroupBox("Shear Settings")
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)
        self.save_shear_settings_btn = QPushButton("Save Settings...")
        self.save_shear_settings_btn.clicked.connect(self.on_save_shear_settings_clicked)
        actions_layout.addWidget(self.save_shear_settings_btn)

        self.load_shear_settings_btn = QPushButton("Load Settings...")
        self.load_shear_settings_btn.clicked.connect(self.on_load_shear_settings_clicked)
        actions_layout.addWidget(self.load_shear_settings_btn)
        actions_layout.addStretch()
        main_layout.addLayout(actions_layout)

        signal_group = QGroupBox("Signal Processing")
        signal_layout = QGridLayout()
        signal_layout.setHorizontalSpacing(6)
        signal_layout.setVerticalSpacing(4)
        signal_layout.setColumnMinimumWidth(2, 36)

        signal_layout.addWidget(QLabel("Integration Window (ms):"), 0, 0)
        self.shear_window_spin = QDoubleSpinBox()
        self.shear_window_spin.setRange(1.0, 500.0)
        self.shear_window_spin.setDecimals(1)
        self.shear_window_spin.setValue(SHEAR_INTEGRATION_WINDOW_MS)
        self.shear_window_spin.setToolTip("Signed integration window. Larger values smooth and stabilize the shear estimate but add lag.")
        signal_layout.addWidget(self.shear_window_spin, 0, 1)

        signal_layout.addWidget(QLabel("Conditioning Alpha:"), 0, 2)
        self.shear_conditioning_alpha_spin = QDoubleSpinBox()
        self.shear_conditioning_alpha_spin.setRange(0.0, 1.0)
        self.shear_conditioning_alpha_spin.setDecimals(3)
        self.shear_conditioning_alpha_spin.setSingleStep(0.01)
        self.shear_conditioning_alpha_spin.setValue(SHEAR_CONDITIONING_ALPHA)
        self.shear_conditioning_alpha_spin.setToolTip("Light EMA smoothing after baseline removal. Higher values follow new samples more strongly.")
        signal_layout.addWidget(self.shear_conditioning_alpha_spin, 0, 3)

        signal_layout.addWidget(QLabel("Baseline Alpha:"), 1, 0)
        self.shear_baseline_alpha_spin = QDoubleSpinBox()
        self.shear_baseline_alpha_spin.setRange(0.0, 1.0)
        self.shear_baseline_alpha_spin.setDecimals(3)
        self.shear_baseline_alpha_spin.setSingleStep(0.01)
        self.shear_baseline_alpha_spin.setValue(SHEAR_BASELINE_ALPHA)
        self.shear_baseline_alpha_spin.setToolTip("How quickly each channel's DC baseline adapts to drift. Lower values hold zero more steadily.")
        signal_layout.addWidget(self.shear_baseline_alpha_spin, 1, 1)

        signal_layout.addWidget(QLabel("Deadband:"), 1, 2)
        self.shear_deadband_spin = QDoubleSpinBox()
        self.shear_deadband_spin.setRange(0.0, 1e6)
        self.shear_deadband_spin.setDecimals(6)
        self.shear_deadband_spin.setValue(SHEAR_DEADBAND_THRESHOLD)
        self.shear_deadband_spin.setToolTip("Symmetric threshold around zero. Small integrated values inside this band are treated as noise.")
        signal_layout.addWidget(self.shear_deadband_spin, 1, 3)

        signal_layout.addWidget(QLabel("Confidence Ref:"), 1, 4)
        self.shear_confidence_ref_spin = QDoubleSpinBox()
        self.shear_confidence_ref_spin.setRange(1e-6, 1e6)
        self.shear_confidence_ref_spin.setDecimals(6)
        self.shear_confidence_ref_spin.setValue(SHEAR_CONFIDENCE_SIGNAL_REF)
        self.shear_confidence_ref_spin.setToolTip("Reference signal level used to scale confidence. Increase it if confidence rises too easily.")
        signal_layout.addWidget(self.shear_confidence_ref_spin, 1, 5)

        signal_group.setLayout(signal_layout)
        main_layout.addWidget(signal_group)

        calibration_group = QGroupBox("Per-Sensor Calibration")
        calibration_layout = QVBoxLayout()
        calibration_layout.setContentsMargins(6, 6, 6, 6)
        calibration_layout.setSpacing(4)
        sensor_labels = ["C", "R", "B", "L", "T"]

        gain_layout = QHBoxLayout()
        gain_layout.setSpacing(4)
        gain_layout.addWidget(QLabel("Gain [C,R,B,L,T]:"))
        self.shear_gain_spins = []
        for label, value in zip(sensor_labels, SHEAR_CHANNEL_GAINS):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(4)
            spin.setValue(value)
            spin.setPrefix(f"{label}: ")
            spin.setToolTip(f"Gain correction for sensor {label}. Applied after deadband while preserving sign.")
            self.shear_gain_spins.append(spin)
            gain_layout.addWidget(spin)
        gain_layout.addStretch()
        calibration_layout.addLayout(gain_layout)

        baseline_layout = QHBoxLayout()
        baseline_layout.setSpacing(4)
        baseline_layout.addWidget(QLabel("Baseline [C,R,B,L,T]:"))
        self.shear_baseline_spins = []
        for label, value in zip(sensor_labels, SHEAR_CHANNEL_BASELINES):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1e6)
            spin.setDecimals(6)
            spin.setValue(value)
            spin.setPrefix(f"{label}: ")
            spin.setToolTip(f"Per-channel post-integration noise floor for sensor {label}.")
            self.shear_baseline_spins.append(spin)
            baseline_layout.addWidget(spin)
        baseline_layout.addStretch()
        calibration_layout.addLayout(baseline_layout)

        calibration_group.setLayout(calibration_layout)
        main_layout.addWidget(calibration_group)

        viz_group = QGroupBox("Visualization")
        viz_layout = QGridLayout()
        viz_layout.setHorizontalSpacing(6)
        viz_layout.setVerticalSpacing(4)
        viz_layout.setColumnMinimumWidth(2, 36)

        viz_layout.addWidget(QLabel("Gaussian Sigma X:"), 0, 0)
        self.shear_sigma_x_spin = QDoubleSpinBox()
        self.shear_sigma_x_spin.setRange(0.01, 2.0)
        self.shear_sigma_x_spin.setDecimals(3)
        self.shear_sigma_x_spin.setValue(SHEAR_GAUSSIAN_SIGMA_X)
        self.shear_sigma_x_spin.setToolTip("Horizontal spread of the Gaussian CoP blob.")
        viz_layout.addWidget(self.shear_sigma_x_spin, 0, 1)

        viz_layout.addWidget(QLabel("Gaussian Sigma Y:"), 0, 2)
        self.shear_sigma_y_spin = QDoubleSpinBox()
        self.shear_sigma_y_spin.setRange(0.01, 2.0)
        self.shear_sigma_y_spin.setDecimals(3)
        self.shear_sigma_y_spin.setValue(SHEAR_GAUSSIAN_SIGMA_Y)
        self.shear_sigma_y_spin.setToolTip("Vertical spread of the Gaussian CoP blob.")
        viz_layout.addWidget(self.shear_sigma_y_spin, 0, 3)

        viz_layout.addWidget(QLabel("Intensity Scale:"), 1, 0)
        self.shear_intensity_scale_spin = QDoubleSpinBox()
        self.shear_intensity_scale_spin.setRange(0.0, 10.0)
        self.shear_intensity_scale_spin.setDecimals(6)
        self.shear_intensity_scale_spin.setSingleStep(0.01)
        self.shear_intensity_scale_spin.setValue(SHEAR_INTENSITY_SCALE)
        self.shear_intensity_scale_spin.setToolTip("Scales residual vertical-force magnitude into blob brightness.")
        viz_layout.addWidget(self.shear_intensity_scale_spin, 1, 1)

        viz_layout.addWidget(QLabel("Arrow Scale:"), 1, 2)
        self.shear_arrow_scale_spin = QDoubleSpinBox()
        self.shear_arrow_scale_spin.setRange(0.0, 5.0)
        self.shear_arrow_scale_spin.setDecimals(3)
        self.shear_arrow_scale_spin.setValue(SHEAR_ARROW_SCALE)
        self.shear_arrow_scale_spin.setToolTip("Visual scaling for the centered shear arrow length. Does not change the computed shear.")
        viz_layout.addWidget(self.shear_arrow_scale_spin, 1, 3)

        viz_group.setLayout(viz_layout)
        main_layout.addWidget(viz_group)

        self._connect_shear_settings_autosave()
        group.setLayout(main_layout)
        return group

    def get_shear_settings(self):
        sensor_labels = ["C", "R", "B", "L", "T"]
        return {
            "integration_window_ms": self.shear_window_spin.value(),
            "conditioning_alpha": self.shear_conditioning_alpha_spin.value(),
            "baseline_alpha": self.shear_baseline_alpha_spin.value(),
            "deadband_threshold": self.shear_deadband_spin.value(),
            "confidence_signal_ref": self.shear_confidence_ref_spin.value(),
            "sensor_gains": {label: spin.value() for label, spin in zip(sensor_labels, self.shear_gain_spins)},
            "sensor_baselines": {label: spin.value() for label, spin in zip(sensor_labels, self.shear_baseline_spins)},
            "blob_sigma_x": self.shear_sigma_x_spin.value(),
            "blob_sigma_y": self.shear_sigma_y_spin.value(),
            "intensity_scale": self.shear_intensity_scale_spin.value(),
            "arrow_scale": self.shear_arrow_scale_spin.value(),
            "channel_sensor_map": list(HEATMAP_CHANNEL_SENSOR_MAP),
        }

    def update_shear_display(self, heatmap, result):
        self.shear_image.setImage(heatmap, autoLevels=False, levels=(0, 1))

        arrow_scale = self.shear_arrow_scale_spin.value()
        arrow_end_x = result.shear_x * arrow_scale
        arrow_end_y = result.shear_y * arrow_scale
        has_arrow = result.shear_magnitude > 1e-6 and (abs(arrow_end_x) > 1e-6 or abs(arrow_end_y) > 1e-6)

        if has_arrow:
            self.shear_arrow_line.setData([0.0, arrow_end_x], [0.0, arrow_end_y])
            self.shear_arrow_head.setPos(arrow_end_x, arrow_end_y)
            self.shear_arrow_head.setStyle(angle=-result.shear_angle_deg + 90.0)
            self.shear_arrow_line.setVisible(True)
            self.shear_arrow_head.setVisible(True)
        else:
            self.shear_arrow_line.setData([], [])
            self.shear_arrow_line.setVisible(False)
            self.shear_arrow_head.setVisible(False)
        self.shear_cop_marker.setData([result.cop_x], [result.cop_y])

        self.shear_magnitude_label.setText(f"Magnitude: {result.shear_magnitude:.3f}")
        self.shear_angle_label.setText(f"Angle: {result.shear_angle_deg:+.1f} deg")
        self.shear_confidence_label.setText(f"Confidence: {result.confidence:.2f}")
        self.shear_cop_x_label.setText(f"X_CoP: {result.cop_x:+.3f}")
        self.shear_cop_y_label.setText(f"Y_CoP: {result.cop_y:+.3f}")
        self.shear_vector_label.setText(f"Vector: ({result.shear_x:+.3f}, {result.shear_y:+.3f})")

    def show_shear_channel_warning(self, current_channels, required_channels=5):
        self.shear_status_label.setText(
            f"Shear requires exactly {required_channels} channels (currently {current_channels} selected)"
        )

    def clear_shear_channel_warning(self):
        self.shear_status_label.setText("")
