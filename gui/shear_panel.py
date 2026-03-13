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
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
import numpy as np
import pyqtgraph as pg

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

    def create_shear_tab(self):
        shear_widget = QWidget()
        layout = QVBoxLayout()

        shear_display = self.create_shear_display()
        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_height = screen.availableGeometry().height()
            min_height = max(240, int(screen_height / 3))
            max_height = max(min_height, int(screen_height * 0.55))
            shear_display.setMinimumHeight(min_height)
            shear_display.setMaximumHeight(max_height)
        layout.addWidget(shear_display, stretch=4)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        readouts_panel = self.create_shear_readouts()
        readouts_panel.setMaximumHeight(130)
        bottom_layout.addWidget(readouts_panel)

        settings_panel = self.create_shear_settings()
        self.shear_settings_scroll = QScrollArea()
        self.shear_settings_scroll.setWidgetResizable(True)
        self.shear_settings_scroll.setWidget(settings_panel)
        self.shear_settings_scroll.setMaximumHeight(420)
        bottom_layout.addWidget(self.shear_settings_scroll)

        bottom_widget.setLayout(bottom_layout)
        layout.addWidget(bottom_widget, stretch=6)

        shear_widget.setLayout(layout)
        return shear_widget

    def create_shear_display(self):
        group = QGroupBox("Shear / CoP Visualization")
        layout = QVBoxLayout()

        self.shear_plot_width = HEATMAP_WIDTH
        self.shear_plot_height = HEATMAP_HEIGHT
        grid_axis = np.linspace(-1.0, 1.0, self.shear_plot_width, dtype=np.float64)
        self.shear_x_grid, self.shear_y_grid = np.meshgrid(grid_axis, grid_axis)

        self.shear_plot_widget = pg.GraphicsLayoutWidget()
        self.shear_plot = self.shear_plot_widget.addPlot()
        self.shear_plot.setAspectLocked(True, ratio=1.0)
        self.shear_plot.showGrid(x=False, y=False)
        self.shear_plot.showAxis("left", False)
        self.shear_plot.showAxis("bottom", False)
        self.shear_plot.setMouseEnabled(x=False, y=False)
        self.shear_plot.setXRange(-1.15, 1.15, padding=0.0)
        self.shear_plot.setYRange(-1.15, 1.15, padding=0.0)

        self.shear_image = pg.ImageItem()
        self.shear_image.setRect(QRectF(-1.0, -1.0, 2.0, 2.0))
        self.shear_plot.addItem(self.shear_image)
        colormap = pg.colormap.get("viridis")
        self.shear_image.setColorMap(colormap)
        self.shear_image.setImage(np.zeros((self.shear_plot_height, self.shear_plot_width), dtype=np.float32), autoLevels=False, levels=(0, 1))

        self.shear_arrow_line = pg.PlotDataItem([], [], pen=pg.mkPen((235, 80, 60), width=3))
        self.shear_arrow_line.setZValue(10)
        self.shear_plot.addItem(self.shear_arrow_line)

        self.shear_arrow_head = pg.ArrowItem(angle=0.0, headLen=18, tipAngle=28, baseAngle=20, brush=(235, 80, 60), pen=pg.mkPen((235, 80, 60)))
        self.shear_arrow_head.setZValue(11)
        self.shear_plot.addItem(self.shear_arrow_head)

        self.shear_cop_marker = pg.ScatterPlotItem([0.0], [0.0], symbol="o", size=12, brush=pg.mkBrush(255, 255, 255, 220), pen=pg.mkPen((60, 60, 60), width=1.5))
        self.shear_cop_marker.setZValue(12)
        self.shear_plot.addItem(self.shear_cop_marker)

        self._add_shear_background_overlay()

        self.shear_status_label = QLabel("")
        self.shear_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.shear_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.shear_plot_widget)
        layout.addWidget(self.shear_status_label)
        group.setLayout(layout)
        return group

    def _add_shear_background_overlay(self):
        theta = np.linspace(0.0, 2.0 * np.pi, 200)
        circle = pg.PlotDataItem(np.cos(theta), np.sin(theta), pen=pg.mkPen((200, 200, 200, 160), width=2))
        circle.setZValue(5)
        self.shear_plot.addItem(circle)
        self.shear_circle = circle

        self.shear_marker_items = []
        self.shear_marker_labels = []
        marker_positions = {
            "R": (1.0, 0.0),
            "B": (0.0, -1.0),
            "C": (0.0, 0.0),
            "L": (-1.0, 0.0),
            "T": (0.0, 1.0),
        }
        label_to_number = {
            sensor_label: str(index + 1)
            for index, sensor_label in enumerate(HEATMAP_CHANNEL_SENSOR_MAP)
        }
        for sensor_name, (x_pos, y_pos) in marker_positions.items():
            marker = pg.ScatterPlotItem([x_pos], [y_pos], symbol="s", size=14, brush=pg.mkBrush(230, 230, 230, 200), pen=pg.mkPen(120, 120, 120, 200))
            marker.setZValue(6)
            self.shear_plot.addItem(marker)
            self.shear_marker_items.append(marker)

            label = pg.TextItem(label_to_number.get(sensor_name, sensor_name), color=(60, 60, 60))
            label.setAnchor((0.5, 0.5))
            label.setPos(x_pos, y_pos)
            label.setZValue(7)
            self.shear_plot.addItem(label)
            self.shear_marker_labels.append(label)

    def create_shear_readouts(self):
        group = QGroupBox("Shear Readouts")
        layout = QVBoxLayout()

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

        signal_group = QGroupBox("Signal Processing")
        signal_layout = QGridLayout()
        signal_layout.setColumnMinimumWidth(2, 80)

        signal_layout.addWidget(QLabel("Integration Window (ms):"), 0, 0)
        self.shear_window_spin = QDoubleSpinBox()
        self.shear_window_spin.setRange(1.0, 500.0)
        self.shear_window_spin.setDecimals(1)
        self.shear_window_spin.setValue(SHEAR_INTEGRATION_WINDOW_MS)
        signal_layout.addWidget(self.shear_window_spin, 0, 1)

        signal_layout.addWidget(QLabel("Conditioning Alpha:"), 0, 3)
        self.shear_conditioning_alpha_spin = QDoubleSpinBox()
        self.shear_conditioning_alpha_spin.setRange(0.0, 1.0)
        self.shear_conditioning_alpha_spin.setDecimals(3)
        self.shear_conditioning_alpha_spin.setSingleStep(0.01)
        self.shear_conditioning_alpha_spin.setValue(SHEAR_CONDITIONING_ALPHA)
        signal_layout.addWidget(self.shear_conditioning_alpha_spin, 0, 4)

        signal_layout.addWidget(QLabel("Baseline Alpha:"), 1, 0)
        self.shear_baseline_alpha_spin = QDoubleSpinBox()
        self.shear_baseline_alpha_spin.setRange(0.0, 1.0)
        self.shear_baseline_alpha_spin.setDecimals(3)
        self.shear_baseline_alpha_spin.setSingleStep(0.01)
        self.shear_baseline_alpha_spin.setValue(SHEAR_BASELINE_ALPHA)
        signal_layout.addWidget(self.shear_baseline_alpha_spin, 1, 1)

        signal_layout.addWidget(QLabel("Deadband:"), 1, 3)
        self.shear_deadband_spin = QDoubleSpinBox()
        self.shear_deadband_spin.setRange(0.0, 1e6)
        self.shear_deadband_spin.setDecimals(6)
        self.shear_deadband_spin.setValue(SHEAR_DEADBAND_THRESHOLD)
        signal_layout.addWidget(self.shear_deadband_spin, 1, 4)

        signal_layout.addWidget(QLabel("Confidence Ref:"), 2, 0)
        self.shear_confidence_ref_spin = QDoubleSpinBox()
        self.shear_confidence_ref_spin.setRange(1e-6, 1e6)
        self.shear_confidence_ref_spin.setDecimals(6)
        self.shear_confidence_ref_spin.setValue(SHEAR_CONFIDENCE_SIGNAL_REF)
        signal_layout.addWidget(self.shear_confidence_ref_spin, 2, 1)

        signal_group.setLayout(signal_layout)
        main_layout.addWidget(signal_group)

        calibration_group = QGroupBox("Per-Sensor Calibration")
        calibration_layout = QVBoxLayout()
        sensor_labels = ["C", "R", "B", "L", "T"]

        gain_layout = QHBoxLayout()
        gain_layout.addWidget(QLabel("Gain [C,R,B,L,T]:"))
        self.shear_gain_spins = []
        for label, value in zip(sensor_labels, SHEAR_CHANNEL_GAINS):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(4)
            spin.setValue(value)
            spin.setPrefix(f"{label}: ")
            self.shear_gain_spins.append(spin)
            gain_layout.addWidget(spin)
        gain_layout.addStretch()
        calibration_layout.addLayout(gain_layout)

        baseline_layout = QHBoxLayout()
        baseline_layout.addWidget(QLabel("Baseline [C,R,B,L,T]:"))
        self.shear_baseline_spins = []
        for label, value in zip(sensor_labels, SHEAR_CHANNEL_BASELINES):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1e6)
            spin.setDecimals(6)
            spin.setValue(value)
            spin.setPrefix(f"{label}: ")
            self.shear_baseline_spins.append(spin)
            baseline_layout.addWidget(spin)
        baseline_layout.addStretch()
        calibration_layout.addLayout(baseline_layout)

        calibration_group.setLayout(calibration_layout)
        main_layout.addWidget(calibration_group)

        viz_group = QGroupBox("Visualization")
        viz_layout = QGridLayout()
        viz_layout.setColumnMinimumWidth(2, 80)

        viz_layout.addWidget(QLabel("Gaussian Sigma X:"), 0, 0)
        self.shear_sigma_x_spin = QDoubleSpinBox()
        self.shear_sigma_x_spin.setRange(0.01, 2.0)
        self.shear_sigma_x_spin.setDecimals(3)
        self.shear_sigma_x_spin.setValue(SHEAR_GAUSSIAN_SIGMA_X)
        viz_layout.addWidget(self.shear_sigma_x_spin, 0, 1)

        viz_layout.addWidget(QLabel("Gaussian Sigma Y:"), 0, 3)
        self.shear_sigma_y_spin = QDoubleSpinBox()
        self.shear_sigma_y_spin.setRange(0.01, 2.0)
        self.shear_sigma_y_spin.setDecimals(3)
        self.shear_sigma_y_spin.setValue(SHEAR_GAUSSIAN_SIGMA_Y)
        viz_layout.addWidget(self.shear_sigma_y_spin, 0, 4)

        viz_layout.addWidget(QLabel("Intensity Scale:"), 1, 0)
        self.shear_intensity_scale_spin = QDoubleSpinBox()
        self.shear_intensity_scale_spin.setRange(0.0, 10.0)
        self.shear_intensity_scale_spin.setDecimals(6)
        self.shear_intensity_scale_spin.setSingleStep(0.01)
        self.shear_intensity_scale_spin.setValue(SHEAR_INTENSITY_SCALE)
        viz_layout.addWidget(self.shear_intensity_scale_spin, 1, 1)

        viz_layout.addWidget(QLabel("Arrow Scale:"), 1, 3)
        self.shear_arrow_scale_spin = QDoubleSpinBox()
        self.shear_arrow_scale_spin.setRange(0.0, 5.0)
        self.shear_arrow_scale_spin.setDecimals(3)
        self.shear_arrow_scale_spin.setValue(SHEAR_ARROW_SCALE)
        viz_layout.addWidget(self.shear_arrow_scale_spin, 1, 4)

        viz_group.setLayout(viz_layout)
        main_layout.addWidget(viz_group)

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

        self.shear_arrow_line.setData([0.0, arrow_end_x], [0.0, arrow_end_y])
        self.shear_arrow_head.setPos(arrow_end_x, arrow_end_y)
        self.shear_arrow_head.setStyle(angle=-result.shear_angle_deg + 90.0)
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
