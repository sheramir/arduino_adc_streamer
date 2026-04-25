"""
Integrated voltage preview tab for the future shear/pressure pipeline.

This tab reads the same recent ADC circular-buffer window used by the Time
Series view, converts the selected traces to voltage independently of the Time
Series Y-axis setting, and applies a display-only high-pass filter for DC-bias
removal. It then applies a display-only rectangular moving-sum integrator. The
live acquisition loop still does not run the streaming integrator, so
responsiveness can be evaluated one processing stage at a time.

Dependencies:
    PyQt6, pyqtgraph, numpy, existing ADC plotting helpers, and config constants.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Hashable

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QFileDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from constants.filtering_defaults import FILTER_DEFAULT_LOW_CUTOFF_HZ
from constants.plotting import (
    IADC_RESOLUTION_BITS,
    MAX_PLOT_SWEEPS,
    PLOT_COLORS,
)
from constants.sensor_config import (
    SENSOR_POLARITY_NORMAL_MULTIPLIER,
    SENSOR_POLARITY_REVERSED_MULTIPLIER,
)
from config.sensor_config import normalize_array_cell
from constants.ui import PRESSURE_MAP_TAB_NAME
from constants.signal_integration import (
    DEFAULT_DISPLAY_WINDOW_SEC,
    DEFAULT_HPF_CUTOFF_HZ,
    DEFAULT_INTEGRATION_WINDOW_SAMPLES,
    SIGNAL_INTEGRATION_AVERAGE_LINE_WIDTH,
    SIGNAL_INTEGRATION_DIMMED_COLOR_FRACTION,
    SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
    SIGNAL_INTEGRATION_DISPLAY_WINDOW_DECIMALS,
    SIGNAL_INTEGRATION_DISPLAY_WINDOW_MAX_SEC,
    SIGNAL_INTEGRATION_DISPLAY_WINDOW_MIN_SEC,
    SIGNAL_INTEGRATION_DISPLAY_WINDOW_STEP_SEC,
    SIGNAL_INTEGRATION_HISTORY_DISPLAY_WINDOW_MULTIPLIER,
    SIGNAL_INTEGRATION_HISTORY_INTEGRATION_WINDOW_MULTIPLIER,
    SIGNAL_INTEGRATION_HISTORY_MIN_SWEEPS,
    SIGNAL_INTEGRATION_HPF_CUTOFF_DECIMALS,
    SIGNAL_INTEGRATION_HPF_CUTOFF_MAX_HZ,
    SIGNAL_INTEGRATION_HPF_CUTOFF_MIN_HZ,
    SIGNAL_INTEGRATION_HPF_CUTOFF_STEP_HZ,
    SIGNAL_INTEGRATION_HPF_FILTER_ORDER,
    SIGNAL_INTEGRATION_LEGEND_OFFSET,
    SIGNAL_INTEGRATION_MAX_PROCESSING_SWEEPS,
    SIGNAL_INTEGRATION_MAX_TOTAL_POINTS_TO_DISPLAY,
    SIGNAL_INTEGRATION_MIN_POINTS_PER_VISIBLE_CHANNEL,
    SIGNAL_INTEGRATION_NYQUIST_DIVISOR,
    SIGNAL_INTEGRATION_PLOT_MAX_HEIGHT_PX,
    SIGNAL_INTEGRATION_PLOT_MIN_HEIGHT_PX,
    SIGNAL_INTEGRATION_PLOT_LINE_WIDTH,
    SIGNAL_INTEGRATION_REPEAT_LINE_WIDTH,
    SIGNAL_INTEGRATION_POSITION_ORDER,
    SIGNAL_INTEGRATION_WINDOW_MAX_SAMPLES,
    SIGNAL_INTEGRATION_WINDOW_MIN_SAMPLES,
)
from constants.shear import (
    DEFAULT_ARROW_BASE_WIDTH_PX,
    DEFAULT_ARROW_GAIN,
    DEFAULT_ARROW_MAX_LENGTH_PX,
    DEFAULT_ARROW_MIN_THRESHOLD,
    DEFAULT_ARROW_WIDTH_SCALES,
    DEFAULT_CIRCLE_DIAMETER_MM,
    DEFAULT_PRESSURE_GRID_MARGIN,
    DEFAULT_PRESSURE_GRID_RESOLUTION,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    DEFAULT_SHEAR_CALIBRATION_GAIN,
    DEFAULT_SHEAR_NOISE_THRESHOLD,
    PRESSURE_CIRCLE_DIAMETER_DECIMALS,
    PRESSURE_CIRCLE_DIAMETER_MAX_MM,
    PRESSURE_CIRCLE_DIAMETER_MIN_MM,
    PRESSURE_CIRCLE_DIAMETER_STEP_MM,
    PRESSURE_GRID_MARGIN_MAX,
    PRESSURE_GRID_MARGIN_STEP,
    PRESSURE_GRID_MIN_MARGIN,
    PRESSURE_GRID_RESOLUTION_MAX,
    PRESSURE_GRID_RESOLUTION_MIN,
    PRESSURE_GRID_RESOLUTION_STEP,
    PRESSURE_MAP_STRETCH,
    PRESSURE_SENSOR_SPACING_DECIMALS,
    PRESSURE_SENSOR_SPACING_MAX_MM,
    PRESSURE_SENSOR_SPACING_MIN_MM,
    PRESSURE_SENSOR_SPACING_STEP_MM,
    SHEAR_ARROW_BASE_WIDTH_DECIMALS,
    SHEAR_ARROW_BASE_WIDTH_MAX_PX,
    SHEAR_ARROW_BASE_WIDTH_MIN_PX,
    SHEAR_ARROW_BASE_WIDTH_STEP_PX,
    SHEAR_ARROW_GAIN_DECIMALS,
    SHEAR_ARROW_GAIN_MAX,
    SHEAR_ARROW_GAIN_MIN,
    SHEAR_ARROW_GAIN_STEP,
    SHEAR_ARROW_MAX_LENGTH_DECIMALS,
    SHEAR_ARROW_MAX_LENGTH_MAX,
    SHEAR_ARROW_MAX_LENGTH_MIN,
    SHEAR_ARROW_MAX_LENGTH_STEP,
    SHEAR_ARROW_MIN_THRESHOLD_DECIMALS,
    SHEAR_ARROW_MIN_THRESHOLD_MAX,
    SHEAR_ARROW_MIN_THRESHOLD_MIN,
    SHEAR_ARROW_MIN_THRESHOLD_STEP,
    SHEAR_CALIBRATION_GAIN_DECIMALS,
    SHEAR_CALIBRATION_GAIN_MAX,
    SHEAR_CALIBRATION_GAIN_MIN,
    SHEAR_CALIBRATION_GAIN_STEP,
    SHEAR_NOISE_THRESHOLD_DECIMALS,
    SHEAR_NOISE_THRESHOLD_MAX,
    SHEAR_NOISE_THRESHOLD_MIN,
    SHEAR_NOISE_THRESHOLD_STEP,
    SHEAR_CONTROL_SPIN_WIDTH_PX,
    SHEAR_GAIN_LABEL_MAX_WIDTH_PX,
    SHEAR_GAIN_SPIN_WIDTH_PX,
    SHEAR_SENSOR_POSITIONS,
    SHEAR_SETTINGS_APP_DIRNAME,
    SHEAR_SETTINGS_DEFAULT_FILENAME,
    SHEAR_SETTINGS_FILE_FILTER,
    SHEAR_SETTINGS_GRID_COLUMNS,
    SHEAR_SETTINGS_HORIZONTAL_SPACING_PX,
    SHEAR_SETTINGS_LAST_FILENAME,
    SHEAR_SETTINGS_PAYLOAD_KEY,
    SHEAR_SETTINGS_SUBDIR,
    SHEAR_SETTINGS_VERTICAL_SPACING_PX,
    SHEAR_SETTINGS_VERSION,
)
from data_processing.adc_filter_engine import ADCFilterEngine, SCIPY_FILTERS_AVAILABLE
from data_processing.normal_force_calculator import NormalForceCalculator, NormalForceResult
from data_processing.pressure_map_generator import PressureMapGenerator, PressureMapResult
from data_processing.shear_detector import ShearDetector, ShearResult
from file_operations.settings_persistence import load_settings_payload, save_settings_payload
from gui.pressure_map_widget import PressureMapPackageDisplay, PressureMapWidget


class SignalIntegrationPanelMixin:
    """Create and refresh the pressure-map pipeline preview tab.

    The tab mirrors the Time Series buffering and curve update path while using
    its own PlotWidget and channel checkboxes. It converts ADC counts to volts
    and applies high-pass filtering plus moving-sum integration only to the
    visible display window.

    Usage example:
        tab = self.create_signal_integration_tab()
        self.visualization_tabs.addTab(tab, PRESSURE_MAP_TAB_NAME)
    """

    def create_signal_integration_tab(self) -> QWidget:
        """Create the Pressure Map tab with integrated voltage plotting.

        Args:
            None.

        Returns:
            QWidget containing HPF controls, integration controls, display
            controls, the integrated voltage plot, shear visualization, and
            pressure map visualization.

        Raises:
            None.
        """
        self._shear_settings_loading = False
        self._shear_autosave_enabled = True

        tab = QScrollArea()
        tab.setWidgetResizable(True)
        tab.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content_widget = QWidget()
        root_layout = QVBoxLayout(content_widget)
        tab.setWidget(content_widget)

        controls_group = QGroupBox("Signal Integration Controls")
        controls_layout = QGridLayout(controls_group)

        hpf_tooltip = (
            "Display-only high-pass cutoff applied before integration to remove DC bias. "
            "Lower values keep slower drift; 0 disables the HPF."
        )
        controls_layout.addWidget(self._create_tooltip_label("HPF cutoff:", hpf_tooltip), 0, 0)
        self.signal_integration_hpf_spin = QDoubleSpinBox()
        self.signal_integration_hpf_spin.setRange(
            SIGNAL_INTEGRATION_HPF_CUTOFF_MIN_HZ,
            SIGNAL_INTEGRATION_HPF_CUTOFF_MAX_HZ,
        )
        self.signal_integration_hpf_spin.setDecimals(SIGNAL_INTEGRATION_HPF_CUTOFF_DECIMALS)
        self.signal_integration_hpf_spin.setSingleStep(SIGNAL_INTEGRATION_HPF_CUTOFF_STEP_HZ)
        self.signal_integration_hpf_spin.setSuffix(" Hz")
        self.signal_integration_hpf_spin.setValue(
            float(getattr(self, "signal_integration_hpf_cutoff_hz", DEFAULT_HPF_CUTOFF_HZ))
        )
        self.signal_integration_hpf_spin.setToolTip(hpf_tooltip)
        self.signal_integration_hpf_spin.valueChanged.connect(self.on_signal_integration_settings_changed)
        controls_layout.addWidget(self.signal_integration_hpf_spin, 0, 1)

        integration_window_tooltip = (
            "Number of recent high-pass-filtered samples summed at each point. "
            "Larger windows smooth more and emphasize slower buildup."
        )
        controls_layout.addWidget(
            self._create_tooltip_label("Integration window:", integration_window_tooltip),
            0,
            2,
        )
        self.signal_integration_window_spin = QSpinBox()
        self.signal_integration_window_spin.setRange(
            SIGNAL_INTEGRATION_WINDOW_MIN_SAMPLES,
            SIGNAL_INTEGRATION_WINDOW_MAX_SAMPLES,
        )
        self.signal_integration_window_spin.setSuffix(" samples")
        self.signal_integration_window_spin.setValue(
            int(getattr(self, "signal_integration_window_samples", DEFAULT_INTEGRATION_WINDOW_SAMPLES))
        )
        self.signal_integration_window_spin.setToolTip(integration_window_tooltip)
        self.signal_integration_window_spin.valueChanged.connect(self.on_signal_integration_settings_changed)
        controls_layout.addWidget(self.signal_integration_window_spin, 0, 3)

        display_window_tooltip = (
            "How much recent history the Pressure Map tab shows and uses for the live preview."
        )
        controls_layout.addWidget(
            self._create_tooltip_label("Display window:", display_window_tooltip),
            0,
            4,
        )
        self.signal_integration_display_window_spin = QDoubleSpinBox()
        self.signal_integration_display_window_spin.setRange(
            SIGNAL_INTEGRATION_DISPLAY_WINDOW_MIN_SEC,
            SIGNAL_INTEGRATION_DISPLAY_WINDOW_MAX_SEC,
        )
        self.signal_integration_display_window_spin.setDecimals(SIGNAL_INTEGRATION_DISPLAY_WINDOW_DECIMALS)
        self.signal_integration_display_window_spin.setSingleStep(SIGNAL_INTEGRATION_DISPLAY_WINDOW_STEP_SEC)
        self.signal_integration_display_window_spin.setSuffix(" s")
        self.signal_integration_display_window_spin.setValue(
            float(getattr(self, "signal_integration_display_window_sec", DEFAULT_DISPLAY_WINDOW_SEC))
        )
        self.signal_integration_display_window_spin.setToolTip(display_window_tooltip)
        self.signal_integration_display_window_spin.valueChanged.connect(self.on_signal_integration_settings_changed)
        controls_layout.addWidget(self.signal_integration_display_window_spin, 0, 5)

        self.signal_integration_reset_btn = QPushButton("Reset View")
        self.signal_integration_reset_btn.setToolTip(
            "Refresh the integrated preview using the current settings and latest buffered data."
        )
        self.signal_integration_reset_btn.clicked.connect(self.on_signal_integration_reset_clicked)
        controls_layout.addWidget(self.signal_integration_reset_btn, 0, 6)
        root_layout.addWidget(controls_group)

        self.signal_integration_plot_widget = pg.PlotWidget()
        self.signal_integration_plot_widget.setMinimumHeight(SIGNAL_INTEGRATION_PLOT_MIN_HEIGHT_PX)
        self.signal_integration_plot_widget.setMaximumHeight(SIGNAL_INTEGRATION_PLOT_MAX_HEIGHT_PX)
        self.signal_integration_plot_widget.setBackground("w")
        self.signal_integration_plot_widget.setLabel("left", "Integrated HPF Voltage", units="V samples")
        self.signal_integration_plot_widget.setLabel("bottom", "Time", units="s")
        self.signal_integration_plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.signal_integration_plot_widget.setMouseEnabled(x=False, y=False)
        self.signal_integration_plot_widget.getPlotItem().setMenuEnabled(False)
        self.signal_integration_plot_widget.getViewBox().setMouseEnabled(x=False, y=False)
        self.signal_integration_plot_widget.addLegend(offset=SIGNAL_INTEGRATION_LEGEND_OFFSET)
        root_layout.addWidget(self.signal_integration_plot_widget)

        self.signal_integration_status_label = QLabel("Waiting for raw ADC data")
        root_layout.addWidget(self.signal_integration_status_label)

        self.shear_detector = ShearDetector()
        self.normal_force_calculator = NormalForceCalculator()
        self.pressure_map_generator = PressureMapGenerator()
        self.pressure_map_widget = PressureMapWidget()
        root_layout.addWidget(self.pressure_map_widget, stretch=PRESSURE_MAP_STRETCH)
        root_layout.addWidget(self._create_shear_visualization_settings_group())
        root_layout.addWidget(self._create_pressure_map_settings_group())
        root_layout.addWidget(self._create_pressure_package_gain_settings_group())

        self.signal_integration_curves: dict[Hashable, object] = {}
        self._latest_signal_integration_values_by_position: dict[str, float] = {}
        self._latest_signal_integration_values_by_package: dict[str, dict[str, float]] = {}
        self._latest_signal_integration_package_layout: list[dict[str, object]] = []
        self._pressure_package_sensor_gains: dict[str, dict[str, float]] = {}
        self._latest_shear_result: ShearResult | None = None
        self._latest_normal_force_result: NormalForceResult | None = None
        self._latest_pressure_map_result: PressureMapResult | None = None
        self._signal_integration_filter_engine = ADCFilterEngine()
        self._signal_integration_filter_warning = ""
        self._signal_integration_updating_plot = False

        return tab

    def _create_tooltip_label(
        self,
        text: str,
        tooltip: str,
        *,
        maximum_width: int | None = None,
    ) -> QLabel:
        """Build a label that exposes the same tooltip as its paired control."""
        label = QLabel(text)
        if maximum_width is not None:
            label.setMaximumWidth(maximum_width)
        label.setToolTip(tooltip)
        return label

    def _create_shear_visualization_settings_group(self) -> QGroupBox:
        group = QGroupBox("Shear Visualization Settings")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(SHEAR_SETTINGS_HORIZONTAL_SPACING_PX)
        layout.setVerticalSpacing(SHEAR_SETTINGS_VERTICAL_SPACING_PX)

        noise_threshold_tooltip = (
            "Zeros each integrated channel before gain and shear detection when its magnitude is below this value."
        )
        layout.addWidget(self._create_tooltip_label("Noise threshold:", noise_threshold_tooltip), 0, 0)
        self.shear_noise_threshold_spin = QDoubleSpinBox()
        self.shear_noise_threshold_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.shear_noise_threshold_spin.setRange(SHEAR_NOISE_THRESHOLD_MIN, SHEAR_NOISE_THRESHOLD_MAX)
        self.shear_noise_threshold_spin.setDecimals(SHEAR_NOISE_THRESHOLD_DECIMALS)
        self.shear_noise_threshold_spin.setSingleStep(SHEAR_NOISE_THRESHOLD_STEP)
        self.shear_noise_threshold_spin.setValue(DEFAULT_SHEAR_NOISE_THRESHOLD)
        self.shear_noise_threshold_spin.setToolTip(noise_threshold_tooltip)
        self.shear_noise_threshold_spin.valueChanged.connect(self.on_shear_processing_settings_changed)
        layout.addWidget(self.shear_noise_threshold_spin, 0, 1)

        self.shear_gain_spins: dict[str, QDoubleSpinBox] = {}
        for index, position in enumerate(SHEAR_SENSOR_POSITIONS):
            row = 1 + (index // SHEAR_SETTINGS_GRID_COLUMNS)
            col = (index % SHEAR_SETTINGS_GRID_COLUMNS) * 2
            gain_tooltip = (
                f"Calibration multiplier for the {position} integrated channel. "
                "Negative values flip that channel's polarity."
            )
            gain_label = self._create_tooltip_label(
                f"{position} gain:",
                gain_tooltip,
                maximum_width=SHEAR_GAIN_LABEL_MAX_WIDTH_PX,
            )
            layout.addWidget(gain_label, row, col)
            gain_spin = QDoubleSpinBox()
            gain_spin.setMaximumWidth(SHEAR_GAIN_SPIN_WIDTH_PX)
            gain_spin.setRange(SHEAR_CALIBRATION_GAIN_MIN, SHEAR_CALIBRATION_GAIN_MAX)
            gain_spin.setDecimals(SHEAR_CALIBRATION_GAIN_DECIMALS)
            gain_spin.setSingleStep(SHEAR_CALIBRATION_GAIN_STEP)
            gain_spin.setValue(DEFAULT_SHEAR_CALIBRATION_GAIN)
            gain_spin.setToolTip(gain_tooltip)
            gain_spin.valueChanged.connect(self.on_shear_processing_settings_changed)
            layout.addWidget(gain_spin, row, col + 1)
            self.shear_gain_spins[position] = gain_spin

        arrow_row = 2
        arrow_gain_tooltip = (
            "Scales detected shear magnitude into displayed arrow length. "
            "Higher values make the arrow longer for the same shear."
        )
        layout.addWidget(self._create_tooltip_label("Arrow gain:", arrow_gain_tooltip), arrow_row, 0)
        self.shear_arrow_gain_spin = QDoubleSpinBox()
        self.shear_arrow_gain_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.shear_arrow_gain_spin.setRange(SHEAR_ARROW_GAIN_MIN, SHEAR_ARROW_GAIN_MAX)
        self.shear_arrow_gain_spin.setDecimals(SHEAR_ARROW_GAIN_DECIMALS)
        self.shear_arrow_gain_spin.setSingleStep(SHEAR_ARROW_GAIN_STEP)
        self.shear_arrow_gain_spin.setValue(DEFAULT_ARROW_GAIN)
        self.shear_arrow_gain_spin.setToolTip(arrow_gain_tooltip)
        self.shear_arrow_gain_spin.valueChanged.connect(self.on_shear_visualization_settings_changed)
        layout.addWidget(self.shear_arrow_gain_spin, arrow_row, 1)

        arrow_threshold_tooltip = (
            "Hides only the displayed arrow when detected shear magnitude is below this value."
        )
        layout.addWidget(self._create_tooltip_label("Arrow threshold:", arrow_threshold_tooltip), arrow_row, 2)
        self.shear_arrow_threshold_spin = QDoubleSpinBox()
        self.shear_arrow_threshold_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.shear_arrow_threshold_spin.setRange(
            SHEAR_ARROW_MIN_THRESHOLD_MIN,
            SHEAR_ARROW_MIN_THRESHOLD_MAX,
        )
        self.shear_arrow_threshold_spin.setDecimals(SHEAR_ARROW_MIN_THRESHOLD_DECIMALS)
        self.shear_arrow_threshold_spin.setSingleStep(SHEAR_ARROW_MIN_THRESHOLD_STEP)
        self.shear_arrow_threshold_spin.setValue(DEFAULT_ARROW_MIN_THRESHOLD)
        self.shear_arrow_threshold_spin.setToolTip(arrow_threshold_tooltip)
        self.shear_arrow_threshold_spin.valueChanged.connect(self.on_shear_visualization_settings_changed)
        layout.addWidget(self.shear_arrow_threshold_spin, arrow_row, 3)

        arrow_max_radius_tooltip = (
            "Caps arrow length as a multiple of the visualization circle radius. "
            "A value of 1.0 reaches the circle edge."
        )
        layout.addWidget(self._create_tooltip_label("Arrow max radius:", arrow_max_radius_tooltip), arrow_row, 4)
        self.shear_arrow_max_length_spin = QDoubleSpinBox()
        self.shear_arrow_max_length_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.shear_arrow_max_length_spin.setRange(
            SHEAR_ARROW_MAX_LENGTH_MIN,
            SHEAR_ARROW_MAX_LENGTH_MAX,
        )
        self.shear_arrow_max_length_spin.setDecimals(SHEAR_ARROW_MAX_LENGTH_DECIMALS)
        self.shear_arrow_max_length_spin.setSingleStep(SHEAR_ARROW_MAX_LENGTH_STEP)
        self.shear_arrow_max_length_spin.setValue(DEFAULT_ARROW_MAX_LENGTH_PX)
        self.shear_arrow_max_length_spin.setToolTip(arrow_max_radius_tooltip)
        self.shear_arrow_max_length_spin.valueChanged.connect(self.on_shear_visualization_settings_changed)
        layout.addWidget(self.shear_arrow_max_length_spin, arrow_row, 5)

        arrow_width_tooltip = (
            "Base shaft width in screen pixels. With Scale width enabled, "
            "this becomes the minimum width before magnitude-based widening."
        )
        layout.addWidget(self._create_tooltip_label("Arrow width:", arrow_width_tooltip), arrow_row, 6)
        self.shear_arrow_base_width_spin = QDoubleSpinBox()
        self.shear_arrow_base_width_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.shear_arrow_base_width_spin.setRange(
            SHEAR_ARROW_BASE_WIDTH_MIN_PX,
            SHEAR_ARROW_BASE_WIDTH_MAX_PX,
        )
        self.shear_arrow_base_width_spin.setDecimals(SHEAR_ARROW_BASE_WIDTH_DECIMALS)
        self.shear_arrow_base_width_spin.setSingleStep(SHEAR_ARROW_BASE_WIDTH_STEP_PX)
        self.shear_arrow_base_width_spin.setValue(DEFAULT_ARROW_BASE_WIDTH_PX)
        self.shear_arrow_base_width_spin.setToolTip(arrow_width_tooltip)
        self.shear_arrow_base_width_spin.valueChanged.connect(self.on_shear_visualization_settings_changed)
        layout.addWidget(self.shear_arrow_base_width_spin, arrow_row, 7)

        self.shear_arrow_width_scales_check = QCheckBox("Scale width")
        self.shear_arrow_width_scales_check.setChecked(DEFAULT_ARROW_WIDTH_SCALES)
        self.shear_arrow_width_scales_check.setToolTip(
            "When enabled, the arrow shaft becomes wider as shear magnitude grows."
        )
        self.shear_arrow_width_scales_check.stateChanged.connect(self.on_shear_visualization_settings_changed)
        layout.addWidget(self.shear_arrow_width_scales_check, arrow_row + 1, 0)

        self.shear_save_settings_btn = QPushButton("Save Settings...")
        self.shear_save_settings_btn.setToolTip(
            "Save the current Pressure Map tab settings to a JSON file."
        )
        self.shear_save_settings_btn.clicked.connect(self.on_save_shear_settings_clicked)
        layout.addWidget(self.shear_save_settings_btn, arrow_row + 1, 1)

        self.shear_load_settings_btn = QPushButton("Load Settings...")
        self.shear_load_settings_btn.setToolTip(
            "Load Pressure Map tab settings from a JSON file and apply them immediately."
        )
        self.shear_load_settings_btn.clicked.connect(self.on_load_shear_settings_clicked)
        layout.addWidget(self.shear_load_settings_btn, arrow_row + 1, 2)

        return group

    def _create_pressure_map_settings_group(self) -> QGroupBox:
        group = QGroupBox("Pressure Map Settings")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(SHEAR_SETTINGS_HORIZONTAL_SPACING_PX)
        layout.setVerticalSpacing(SHEAR_SETTINGS_VERTICAL_SPACING_PX)

        sensor_spacing_tooltip = (
            "Center-to-outer sensor spacing in millimeters. "
            "Used for the normal-force centroid and the quadrant plane fit."
        )
        layout.addWidget(self._create_tooltip_label("Sensor spacing:", sensor_spacing_tooltip), 0, 0)
        self.pressure_sensor_spacing_spin = QDoubleSpinBox()
        self.pressure_sensor_spacing_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.pressure_sensor_spacing_spin.setRange(
            PRESSURE_SENSOR_SPACING_MIN_MM,
            PRESSURE_SENSOR_SPACING_MAX_MM,
        )
        self.pressure_sensor_spacing_spin.setDecimals(PRESSURE_SENSOR_SPACING_DECIMALS)
        self.pressure_sensor_spacing_spin.setSingleStep(PRESSURE_SENSOR_SPACING_STEP_MM)
        self.pressure_sensor_spacing_spin.setSuffix(" mm")
        self.pressure_sensor_spacing_spin.setValue(DEFAULT_PRESSURE_SENSOR_SPACING_MM)
        self.pressure_sensor_spacing_spin.setToolTip(sensor_spacing_tooltip)
        self.pressure_sensor_spacing_spin.valueChanged.connect(self.on_pressure_map_settings_changed)
        layout.addWidget(self.pressure_sensor_spacing_spin, 0, 1)

        circle_diameter_tooltip = (
            "Diameter of the circular pressure footprint in millimeters. "
            "Also sets grid cell size for a given grid resolution."
        )
        layout.addWidget(self._create_tooltip_label("Circle diameter:", circle_diameter_tooltip), 0, 2)
        self.pressure_circle_diameter_spin = QDoubleSpinBox()
        self.pressure_circle_diameter_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.pressure_circle_diameter_spin.setRange(
            PRESSURE_CIRCLE_DIAMETER_MIN_MM,
            PRESSURE_CIRCLE_DIAMETER_MAX_MM,
        )
        self.pressure_circle_diameter_spin.setDecimals(PRESSURE_CIRCLE_DIAMETER_DECIMALS)
        self.pressure_circle_diameter_spin.setSingleStep(PRESSURE_CIRCLE_DIAMETER_STEP_MM)
        self.pressure_circle_diameter_spin.setSuffix(" mm")
        self.pressure_circle_diameter_spin.setValue(DEFAULT_CIRCLE_DIAMETER_MM)
        self.pressure_circle_diameter_spin.setToolTip(circle_diameter_tooltip)
        self.pressure_circle_diameter_spin.valueChanged.connect(self.on_pressure_map_settings_changed)
        layout.addWidget(self.pressure_circle_diameter_spin, 0, 3)

        grid_resolution_tooltip = (
            "Number of grid cells across the pressure-circle diameter before margin cells are added. "
            "Higher values increase detail and computation."
        )
        layout.addWidget(self._create_tooltip_label("Grid:", grid_resolution_tooltip), 0, 4)
        self.pressure_grid_resolution_spin = QSpinBox()
        self.pressure_grid_resolution_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.pressure_grid_resolution_spin.setRange(
            PRESSURE_GRID_RESOLUTION_MIN,
            PRESSURE_GRID_RESOLUTION_MAX,
        )
        self.pressure_grid_resolution_spin.setSingleStep(PRESSURE_GRID_RESOLUTION_STEP)
        self.pressure_grid_resolution_spin.setValue(DEFAULT_PRESSURE_GRID_RESOLUTION)
        self.pressure_grid_resolution_spin.setToolTip(grid_resolution_tooltip)
        self.pressure_grid_resolution_spin.valueChanged.connect(self.on_pressure_map_settings_changed)
        layout.addWidget(self.pressure_grid_resolution_spin, 0, 5)

        grid_margin_tooltip = (
            "Extra grid cells added beyond the circle on each side so the pressure planes "
            "can extrapolate smoothly into the PDMS overhang region."
        )
        layout.addWidget(self._create_tooltip_label("Margin:", grid_margin_tooltip), 0, 6)
        self.pressure_grid_margin_spin = QSpinBox()
        self.pressure_grid_margin_spin.setMaximumWidth(SHEAR_CONTROL_SPIN_WIDTH_PX)
        self.pressure_grid_margin_spin.setRange(PRESSURE_GRID_MIN_MARGIN, PRESSURE_GRID_MARGIN_MAX)
        self.pressure_grid_margin_spin.setSingleStep(PRESSURE_GRID_MARGIN_STEP)
        self.pressure_grid_margin_spin.setValue(DEFAULT_PRESSURE_GRID_MARGIN)
        self.pressure_grid_margin_spin.setToolTip(grid_margin_tooltip)
        self.pressure_grid_margin_spin.valueChanged.connect(self.on_pressure_map_settings_changed)
        layout.addWidget(self.pressure_grid_margin_spin, 0, 7)

        return group

    def _create_pressure_package_gain_settings_group(self) -> QGroupBox:
        group = QGroupBox("Per-Package Gain Calibration")
        self.pressure_package_gain_group = group
        self.pressure_package_gain_root_layout = QVBoxLayout(group)
        self.pressure_package_gain_root_layout.setContentsMargins(0, 0, 0, 0)
        self.pressure_package_gain_root_layout.setSpacing(SHEAR_SETTINGS_VERTICAL_SPACING_PX)
        self.pressure_package_gain_spins: dict[str, dict[str, QDoubleSpinBox]] = {}
        self._refresh_pressure_package_gain_controls([])
        return group

    def _refresh_pressure_package_gain_controls(
        self,
        package_layout: list[dict[str, object]] | None = None,
    ) -> None:
        if not hasattr(self, "pressure_package_gain_root_layout"):
            return

        while self.pressure_package_gain_root_layout.count() > 0:
            item = self.pressure_package_gain_root_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if package_layout is None:
            package_layout = self._get_signal_integration_package_layout()

        package_ids = [
            str(item.get("sensor_id", "")).strip().upper()
            for item in package_layout
            if str(item.get("sensor_id", "")).strip()
        ]
        package_ids = list(dict.fromkeys(package_ids))

        show_controls = bool(
            package_ids
            and hasattr(self, "is_array_sensor_selection_mode")
            and self.is_array_sensor_selection_mode()
        )
        self.pressure_package_gain_group.setVisible(show_controls)

        if not show_controls:
            self.pressure_package_gain_spins = {}
            self.pressure_package_gain_root_layout.addWidget(
                QLabel("Array package-specific gains appear here when sensors are selected.")
            )
            return

        self.pressure_package_gain_spins = {}
        for package_id in package_ids:
            package_box = QGroupBox(f"{package_id} gains")
            package_row = QHBoxLayout(package_box)
            package_row.setContentsMargins(6, 6, 6, 6)
            package_row.setSpacing(SHEAR_SETTINGS_HORIZONTAL_SPACING_PX)

            package_gains = self._pressure_sensor_gains_for_package(package_id)
            package_spin_map: dict[str, QDoubleSpinBox] = {}
            for position in SHEAR_SENSOR_POSITIONS:
                package_row.addWidget(QLabel(f"{position}:"))
                spin = QDoubleSpinBox()
                spin.setMaximumWidth(SHEAR_GAIN_SPIN_WIDTH_PX)
                spin.setRange(SHEAR_CALIBRATION_GAIN_MIN, SHEAR_CALIBRATION_GAIN_MAX)
                spin.setDecimals(SHEAR_CALIBRATION_GAIN_DECIMALS)
                spin.setSingleStep(SHEAR_CALIBRATION_GAIN_STEP)
                spin.setValue(float(package_gains.get(position, DEFAULT_SHEAR_CALIBRATION_GAIN)))
                spin.valueChanged.connect(
                    lambda value, sid=package_id, pos=position: self._on_pressure_package_gain_changed(
                        sid,
                        pos,
                        value,
                    )
                )
                package_row.addWidget(spin)
                package_spin_map[position] = spin

            package_row.addStretch()
            self.pressure_package_gain_spins[package_id] = package_spin_map
            self.pressure_package_gain_root_layout.addWidget(package_box)

    def _on_pressure_package_gain_changed(self, package_id: str, position: str, value: float) -> None:
        normalized_package_id = self._normalize_pressure_package_id(package_id)
        if normalized_package_id is None or position not in SHEAR_SENSOR_POSITIONS:
            return

        package_gains = self._pressure_package_sensor_gains.setdefault(normalized_package_id, {})
        package_gains[position] = float(value)
        self._update_shear_visualization_from_latest()
        self.save_last_shear_settings()

    def _get_last_shear_settings_path(self) -> Path:
        return (
            Path.home()
            / SHEAR_SETTINGS_APP_DIRNAME
            / SHEAR_SETTINGS_SUBDIR
            / SHEAR_SETTINGS_LAST_FILENAME
        )

    def _serialize_shear_settings(self) -> dict[str, object]:
        return {
            "version": SHEAR_SETTINGS_VERSION,
            SHEAR_SETTINGS_PAYLOAD_KEY: self.get_shear_settings(),
        }

    def get_shear_settings(self) -> dict[str, object]:
        """Return the current signal-integration and shear-display settings.

        Args:
            None.

        Returns:
            Dict containing the Signal Integration controls, shear processing
            settings, and shear visualization settings.

        Raises:
            None.
        """
        return {
            "signal_integration": {
                "hpf_cutoff_hz": self._spin_float(
                    "signal_integration_hpf_spin",
                    float(getattr(self, "signal_integration_hpf_cutoff_hz", DEFAULT_HPF_CUTOFF_HZ)),
                ),
                "integration_window_samples": self._spin_int(
                    "signal_integration_window_spin",
                    int(getattr(self, "signal_integration_window_samples", DEFAULT_INTEGRATION_WINDOW_SAMPLES)),
                ),
                "display_window_sec": self._spin_float(
                    "signal_integration_display_window_spin",
                    float(getattr(self, "signal_integration_display_window_sec", DEFAULT_DISPLAY_WINDOW_SEC)),
                ),
            },
            "processing": {
                "noise_threshold": self._spin_float(
                    "shear_noise_threshold_spin",
                    DEFAULT_SHEAR_NOISE_THRESHOLD,
                ),
                "sensor_gains": {
                    position: float(spin.value())
                    for position, spin in getattr(self, "shear_gain_spins", {}).items()
                },
                "package_sensor_gains": {
                    package_id: {
                        position: float(value)
                        for position, value in package_gains.items()
                        if position in SHEAR_SENSOR_POSITIONS
                    }
                    for package_id, package_gains in getattr(self, "_pressure_package_sensor_gains", {}).items()
                    if str(package_id).strip()
                },
            },
            "visualization": {
                "arrow_gain": self._spin_float("shear_arrow_gain_spin", DEFAULT_ARROW_GAIN),
                "arrow_min_threshold": self._spin_float(
                    "shear_arrow_threshold_spin",
                    DEFAULT_ARROW_MIN_THRESHOLD,
                ),
                "arrow_max_length_fraction": self._spin_float(
                    "shear_arrow_max_length_spin",
                    DEFAULT_ARROW_MAX_LENGTH_PX,
                ),
                "arrow_base_width_px": self._spin_float(
                    "shear_arrow_base_width_spin",
                    DEFAULT_ARROW_BASE_WIDTH_PX,
                ),
                "arrow_width_scales": self._check_bool(
                    "shear_arrow_width_scales_check",
                    DEFAULT_ARROW_WIDTH_SCALES,
                ),
            },
            "pressure_map": {
                "sensor_spacing_mm": self._spin_float(
                    "pressure_sensor_spacing_spin",
                    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
                ),
                "circle_diameter_mm": self._spin_float(
                    "pressure_circle_diameter_spin",
                    DEFAULT_CIRCLE_DIAMETER_MM,
                ),
                "grid_resolution": self._spin_int(
                    "pressure_grid_resolution_spin",
                    DEFAULT_PRESSURE_GRID_RESOLUTION,
                ),
                "grid_margin": self._spin_int(
                    "pressure_grid_margin_spin",
                    DEFAULT_PRESSURE_GRID_MARGIN,
                ),
            },
        }

    def save_shear_settings_to_path(self, file_path: str | Path, log_message: bool = True) -> Path:
        """Write the current shear settings to a JSON file.

        Args:
            file_path: Destination JSON path.
            log_message: Whether to log a success message through
                ``log_status``.

        Returns:
            Path to the saved JSON file.

        Raises:
            OSError: If the file cannot be written.
        """
        return save_settings_payload(
            file_path,
            self._serialize_shear_settings(),
            log_callback=self.log_status if log_message and hasattr(self, "log_status") else None,
            success_message="Saved shear settings: {path}",
        )

    def load_shear_settings_from_path(self, file_path: str | Path, log_message: bool = True) -> bool:
        """Load shear settings from a JSON file and apply applicable fields.

        Args:
            file_path: Source JSON path.
            log_message: Whether to log the load result through ``log_status``.

        Returns:
            True when at least one applicable setting was found and applied.

        Raises:
            OSError: If the file cannot be read.
            ValueError: If JSON values cannot be converted to control values.
        """
        path, settings = load_settings_payload(file_path, payload_key=SHEAR_SETTINGS_PAYLOAD_KEY)
        self._shear_settings_loading = True
        try:
            applied = self._apply_shear_settings(settings)
        finally:
            self._shear_settings_loading = False

        if log_message and hasattr(self, "log_status"):
            if applied:
                self.log_status(f"Loaded shear settings: {path}")
            else:
                self.log_status(f"Shear settings file loaded, no applicable fields: {path}")
        return applied

    def save_last_shear_settings(self) -> None:
        """Persist the current tab settings as the next startup defaults.

        Args:
            None.

        Returns:
            None.

        Raises:
            None. Save failures are logged and do not interrupt the GUI.
        """
        if getattr(self, "_shear_settings_loading", False):
            return
        if not getattr(self, "_shear_autosave_enabled", True):
            return
        try:
            self.save_shear_settings_to_path(self._get_last_shear_settings_path(), log_message=False)
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"Warning: could not save shear settings: {exc}")

    def load_last_shear_settings(self) -> bool:
        """Load the last-used shear settings file when it exists.

        Args:
            None.

        Returns:
            True when a settings file existed and at least one field was
            applied; otherwise False.

        Raises:
            None. Load failures are logged and leave defaults in place.
        """
        path = self._get_last_shear_settings_path()
        if not path.exists():
            return False
        try:
            return self.load_shear_settings_from_path(path, log_message=True)
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"Warning: could not load shear settings: {exc}")
            return False

    def on_save_shear_settings_clicked(self) -> None:
        """Prompt for a custom JSON path and save current shear settings.

        Args:
            None.

        Returns:
            None.

        Raises:
            None. Dialog cancellation and save failures are handled in-place.
        """
        default_dir = self._get_last_shear_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Shear Settings",
            str(default_dir / SHEAR_SETTINGS_DEFAULT_FILENAME),
            SHEAR_SETTINGS_FILE_FILTER,
        )
        if not file_path:
            return
        try:
            self.save_shear_settings_to_path(file_path, log_message=True)
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"ERROR: failed to save shear settings - {exc}")

    def on_load_shear_settings_clicked(self) -> None:
        """Prompt for a custom JSON file and apply its shear settings.

        Args:
            None.

        Returns:
            None.

        Raises:
            None. Dialog cancellation and load failures are handled in-place.
        """
        default_dir = self._get_last_shear_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Shear Settings",
            str(default_dir),
            SHEAR_SETTINGS_FILE_FILTER,
        )
        if not file_path:
            return
        try:
            applied = self.load_shear_settings_from_path(file_path, log_message=True)
            if applied:
                self.save_last_shear_settings()
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"ERROR: failed to load shear settings - {exc}")

    def _apply_shear_settings(self, settings: dict) -> bool:
        if not settings:
            return False

        signal_integration = self._settings_section(settings, "signal_integration")
        processing = self._settings_section(settings, "processing")
        visualization = self._settings_section(settings, "visualization")
        pressure_map = self._settings_section(settings, "pressure_map")
        changed = False

        changed |= self._set_spin_value("signal_integration_hpf_spin", signal_integration, "hpf_cutoff_hz", float)
        changed |= self._set_spin_value(
            "signal_integration_window_spin",
            signal_integration,
            "integration_window_samples",
            int,
        )
        changed |= self._set_spin_value(
            "signal_integration_display_window_spin",
            signal_integration,
            "display_window_sec",
            float,
        )
        changed |= self._set_spin_value("shear_noise_threshold_spin", processing, "noise_threshold", float)

        sensor_gains = processing.get("sensor_gains", settings.get("sensor_gains", {}))
        if isinstance(sensor_gains, dict):
            for position, value in sensor_gains.items():
                spin = getattr(self, "shear_gain_spins", {}).get(str(position))
                if spin is not None and hasattr(spin, "setValue"):
                    spin.setValue(float(value))
                    changed = True

        raw_package_gains = processing.get("package_sensor_gains", settings.get("package_sensor_gains", {}))
        if not raw_package_gains:
            raw_package_gains = processing.get("sensor_package_gains", settings.get("sensor_package_gains", {}))
        normalized_package_gains = self._normalize_pressure_package_sensor_gains(raw_package_gains)
        if normalized_package_gains:
            self._pressure_package_sensor_gains = normalized_package_gains
            changed = True

        changed |= self._set_spin_value("shear_arrow_gain_spin", visualization, "arrow_gain", float)
        changed |= self._set_spin_value(
            "shear_arrow_threshold_spin",
            visualization,
            "arrow_min_threshold",
            float,
        )
        changed |= self._set_spin_value(
            "shear_arrow_max_length_spin",
            visualization,
            "arrow_max_length_fraction",
            float,
        )
        changed |= self._set_spin_value(
            "shear_arrow_base_width_spin",
            visualization,
            "arrow_base_width_px",
            float,
        )
        changed |= self._set_check_value(
            "shear_arrow_width_scales_check",
            visualization,
            "arrow_width_scales",
        )
        changed |= self._set_spin_value("pressure_sensor_spacing_spin", pressure_map, "sensor_spacing_mm", float)
        changed |= self._set_spin_value("pressure_circle_diameter_spin", pressure_map, "circle_diameter_mm", float)
        changed |= self._set_spin_value("pressure_grid_resolution_spin", pressure_map, "grid_resolution", int)
        changed |= self._set_spin_value("pressure_grid_margin_spin", pressure_map, "grid_margin", int)

        if changed:
            self._refresh_pressure_package_gain_controls()
            self.on_signal_integration_settings_changed()
            self.on_shear_processing_settings_changed()
            self.on_shear_visualization_settings_changed()
            self.on_pressure_map_settings_changed()
        return changed

    def _settings_section(self, settings: dict, section_name: str) -> dict:
        section = settings.get(section_name)
        return section if isinstance(section, dict) else settings

    def _spin_float(self, widget_name: str, fallback: float) -> float:
        widget = getattr(self, widget_name, None)
        if widget is None or not hasattr(widget, "value"):
            return float(fallback)
        return float(widget.value())

    def _spin_int(self, widget_name: str, fallback: int) -> int:
        widget = getattr(self, widget_name, None)
        if widget is None or not hasattr(widget, "value"):
            return int(fallback)
        return int(widget.value())

    def _check_bool(self, widget_name: str, fallback: bool) -> bool:
        widget = getattr(self, widget_name, None)
        if widget is None or not hasattr(widget, "isChecked"):
            return bool(fallback)
        return bool(widget.isChecked())

    def _set_spin_value(self, widget_name: str, settings: dict, key: str, value_type: type) -> bool:
        if key not in settings:
            return False
        widget = getattr(self, widget_name, None)
        if widget is None or not hasattr(widget, "setValue"):
            return False
        widget.setValue(value_type(settings[key]))
        return True

    def _set_check_value(self, widget_name: str, settings: dict, key: str) -> bool:
        if key not in settings:
            return False
        widget = getattr(self, widget_name, None)
        if widget is None or not hasattr(widget, "setChecked"):
            return False
        widget.setChecked(bool(settings[key]))
        return True

    def _normalize_pressure_package_id(self, package_id: str | None) -> str | None:
        if package_id is None:
            return None
        normalized = str(package_id).strip().upper()
        return normalized or None

    def _default_pressure_sensor_gains(self) -> dict[str, float]:
        gains: dict[str, float] = {}
        gain_spins = getattr(self, "shear_gain_spins", {})
        for position in SHEAR_SENSOR_POSITIONS:
            gain_spin = gain_spins.get(position)
            gain = float(gain_spin.value()) if gain_spin is not None else DEFAULT_SHEAR_CALIBRATION_GAIN
            gains[position] = gain
        return gains

    def _normalize_pressure_package_sensor_gains(
        self,
        raw: object,
    ) -> dict[str, dict[str, float]]:
        if not isinstance(raw, dict):
            return {}

        normalized: dict[str, dict[str, float]] = {}
        for package_id, package_gains in raw.items():
            normalized_package_id = self._normalize_pressure_package_id(str(package_id))
            if normalized_package_id is None or not isinstance(package_gains, dict):
                continue

            normalized_gains: dict[str, float] = {}
            for position in SHEAR_SENSOR_POSITIONS:
                if position in package_gains:
                    try:
                        normalized_gains[position] = float(package_gains[position])
                    except (TypeError, ValueError):
                        continue
            if normalized_gains:
                normalized[normalized_package_id] = normalized_gains

        return normalized

    def _pressure_sensor_gains_for_package(self, package_id: str | None) -> dict[str, float]:
        defaults = self._default_pressure_sensor_gains()
        normalized_package_id = self._normalize_pressure_package_id(package_id)
        if normalized_package_id is None:
            return defaults

        package_gain_map = getattr(self, "_pressure_package_sensor_gains", {})
        package_gains = package_gain_map.get(normalized_package_id)
        if package_gains is None:
            return defaults

        effective = dict(defaults)
        for position, value in package_gains.items():
            if position in SHEAR_SENSOR_POSITIONS:
                effective[position] = float(value)
        return effective

    def on_signal_integration_settings_changed(self, _value: object | None = None) -> None:
        """Apply HPF, integration, and display-window changes.

        Args:
            _value: Qt signal payload from the changed spin box.

        Returns:
            None.

        Raises:
            None.
        """
        self.signal_integration_hpf_cutoff_hz = float(self.signal_integration_hpf_spin.value())
        self.signal_integration_window_samples = int(self.signal_integration_window_spin.value())
        self.signal_integration_display_window_sec = float(self.signal_integration_display_window_spin.value())
        self._signal_integration_filter_warning = ""
        self.update_signal_integration_plot()
        self._refresh_pressure_package_gain_controls(
            getattr(self, "_latest_signal_integration_package_layout", None)
        )
        self.save_last_shear_settings()

    def on_shear_processing_settings_changed(self, _value: object | None = None) -> None:
        """Recompute shear after noise-threshold or gain controls change.

        Args:
            _value: Qt signal payload from the changed control.

        Returns:
            None.

        Raises:
            None.
        """
        self._update_shear_visualization_from_latest()
        self.save_last_shear_settings()

    def on_shear_visualization_settings_changed(self, _value: object | None = None) -> None:
        """Apply arrow-display settings to the current shear result.

        Args:
            _value: Qt signal payload from the changed control.

        Returns:
            None.

        Raises:
            None.
        """
        if not hasattr(self, "pressure_map_widget"):
            return

        self.pressure_map_widget.configure_arrow(
            arrow_gain=float(self.shear_arrow_gain_spin.value()),
            arrow_max_length_fraction=float(self.shear_arrow_max_length_spin.value()),
            arrow_min_threshold=float(self.shear_arrow_threshold_spin.value()),
            arrow_width_scales=bool(self.shear_arrow_width_scales_check.isChecked()),
            arrow_base_width_px=float(self.shear_arrow_base_width_spin.value()),
        )
        self.pressure_map_widget.update_display(
            self._latest_normal_force_result,
            self._latest_pressure_map_result,
            self._latest_shear_result,
        )
        self.save_last_shear_settings()

    def on_pressure_map_settings_changed(self, _value: object | None = None) -> None:
        """Rebuild pressure-map processors after map parameter changes.

        Args:
            _value: Qt signal payload from the changed control.

        Returns:
            None.

        Raises:
            None. Invalid settings are logged and leave the previous processors
            in place.
        """
        try:
            sensor_spacing_mm = self._spin_float(
                "pressure_sensor_spacing_spin",
                DEFAULT_PRESSURE_SENSOR_SPACING_MM,
            )
            self.normal_force_calculator = NormalForceCalculator(sensor_spacing_mm=sensor_spacing_mm)
            self.pressure_map_generator = PressureMapGenerator(
                circle_diameter_mm=self._spin_float(
                    "pressure_circle_diameter_spin",
                    DEFAULT_CIRCLE_DIAMETER_MM,
                ),
                sensor_spacing_mm=sensor_spacing_mm,
                grid_margin=self._spin_int("pressure_grid_margin_spin", DEFAULT_PRESSURE_GRID_MARGIN),
                grid_resolution=self._spin_int(
                    "pressure_grid_resolution_spin",
                    DEFAULT_PRESSURE_GRID_RESOLUTION,
                ),
            )
            self._update_pressure_map_from_latest()
            self.save_last_shear_settings()
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"ERROR updating Pressure Map settings: {exc}")

    def on_signal_integration_reset_clicked(self) -> None:
        """Reset the integrated voltage preview to the latest display window.

        Args:
            None.

        Returns:
            None.

        Raises:
            None.
        """
        self.update_signal_integration_plot()
        if hasattr(self, "signal_integration_status_label"):
            self.signal_integration_status_label.setText("Integrated display refreshed")

    def update_signal_integration_plot(self) -> None:
        """Render integrated HPF voltage using the Time Series buffer path.

        Args:
            None.

        Returns:
            None.

        Raises:
            None. Errors are logged through ``log_status`` when available.
        """
        if not hasattr(self, "signal_integration_plot_widget"):
            return
        if not self._should_refresh_signal_integration_plot():
            return
        if self._signal_integration_updating_plot:
            return

        self._signal_integration_updating_plot = True
        try:
            if not self.config["channels"]:
                self._hide_all_signal_integration_curves()
                self._clear_shear_visualization()
                self.signal_integration_status_label.setText("Configure channels first")
                return

            display_specs = self.get_display_channel_specs()
            selected_channels = {spec["key"] for spec in display_specs}
            if not display_specs:
                self._hide_all_signal_integration_curves()
                self._clear_shear_visualization()
                self.signal_integration_status_label.setText("No integrated channels available")
                return

            plot_snapshot = self._get_signal_integration_raw_snapshot()
            if plot_snapshot is None:
                self._hide_all_signal_integration_curves()
                self._clear_shear_visualization()
                self.signal_integration_status_label.setText("Waiting for raw ADC data")
                return

            data_array, timestamps_array, visible_start_time_sec = plot_snapshot
            if len(data_array) == 0 or len(timestamps_array) == 0:
                self._hide_all_signal_integration_curves()
                self._clear_shear_visualization()
                self.signal_integration_status_label.setText("Waiting for raw ADC data")
                return

            desired_curve_keys = set()
            latest_integrated_by_position: dict[str, float] = {}
            latest_integrated_by_package: dict[str, dict[str, float]] = {}
            package_series_by_position: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
            visible_series_count = max(1, len(selected_channels))
            max_samples_per_series = max(
                SIGNAL_INTEGRATION_MIN_POINTS_PER_VISIBLE_CHANNEL,
                SIGNAL_INTEGRATION_MAX_TOTAL_POINTS_TO_DISPLAY // visible_series_count,
            )
            avg_sample_time_sec = getattr(self, "_cached_avg_sample_time_sec", 0.0)
            repeat_count = max(1, int(self.config.get("repeat", 1)))
            package_layout = self._get_signal_integration_package_layout()
            self._refresh_pressure_package_gain_controls(package_layout)
            multi_package_force_mode = self._is_multi_package_force_mode(package_layout)

            for spec_index, spec in enumerate(display_specs):
                should_plot = (spec["key"] in selected_channels) and not multi_package_force_mode
                shear_position = self._get_shear_position_for_display_spec(spec, spec_index)
                should_collect_package = shear_position in SHEAR_SENSOR_POSITIONS
                should_collect_shear = (
                    should_collect_package
                    and shear_position not in latest_integrated_by_position
                )
                if not should_plot and not should_collect_package:
                    continue

                color = PLOT_COLORS[spec["color_slot"] % len(PLOT_COLORS)]
                prepared_series = self._prepare_signal_integration_integrated_series(
                    spec,
                    data_array,
                    timestamps_array,
                    avg_sample_time_sec,
                    max_samples_per_series,
                    visible_start_time_sec,
                )
                if prepared_series is None:
                    continue

                channel_data, channel_times, latest_value = prepared_series
                if should_collect_package and latest_value is not None:
                    self._record_signal_integration_package_value(
                        latest_integrated_by_package,
                        spec,
                        spec_index,
                        str(shear_position),
                        float(latest_value),
                    )
                    if should_collect_shear:
                        latest_integrated_by_position[str(shear_position)] = float(latest_value)
                    package_id = self._get_signal_integration_package_id_for_display_spec(spec, spec_index)
                    package_series = package_series_by_position.setdefault(package_id, {})
                    package_series[str(shear_position)] = (channel_data, channel_times)

                if not should_plot:
                    continue

                if self.show_all_repeats_radio.isChecked() and repeat_count > 1:
                    self._plot_signal_integration_repeat_series(
                        spec,
                        color,
                        channel_data,
                        channel_times,
                        repeat_count,
                        desired_curve_keys,
                    )
                else:
                    self._plot_signal_integration_single_or_average_series(
                        spec,
                        color,
                        channel_data,
                        channel_times,
                        repeat_count,
                        desired_curve_keys,
                    )

            if multi_package_force_mode:
                self._plot_signal_integration_package_force_series(
                    package_series_by_position,
                    package_layout,
                    desired_curve_keys,
                )

            for key, curve in self.signal_integration_curves.items():
                if key not in desired_curve_keys:
                    curve.setVisible(False)

            self._apply_signal_integration_axis_settings(is_package_force_mode=multi_package_force_mode)
            self._latest_signal_integration_values_by_package = latest_integrated_by_package
            self._latest_signal_integration_package_layout = package_layout
            self._latest_signal_integration_values_by_position = (
                self._first_complete_signal_integration_package_values(latest_integrated_by_package)
                or latest_integrated_by_position
            )
            self._update_shear_visualization_from_latest()
            self.signal_integration_status_label.setText("")

        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"ERROR updating Signal Integration integrated preview: {exc}")
        finally:
            self._signal_integration_updating_plot = False

    def _should_refresh_signal_integration_plot(self) -> bool:
        if hasattr(self, "should_update_signal_integration_display"):
            return bool(self.should_update_signal_integration_display())
        if hasattr(self, "get_current_visualization_tab_name"):
            return self.get_current_visualization_tab_name() == PRESSURE_MAP_TAB_NAME
        return True

    def _hide_all_signal_integration_curves(self) -> None:
        for curve in self.signal_integration_curves.values():
            curve.setVisible(False)

    def _clear_shear_visualization(self) -> None:
        self._latest_signal_integration_values_by_position = {}
        self._latest_signal_integration_values_by_package = {}
        self._latest_signal_integration_package_layout = []
        self._latest_shear_result = None
        self._latest_normal_force_result = None
        self._latest_pressure_map_result = None
        if hasattr(self, "pressure_map_widget"):
            self.pressure_map_widget.update_display(None, None, None)

    def _record_signal_integration_package_value(
        self,
        values_by_package: dict[str, dict[str, float]],
        spec: dict,
        spec_index: int,
        position: str,
        value: float,
    ) -> None:
        package_id = self._get_signal_integration_package_id_for_display_spec(spec, spec_index)
        package_values = values_by_package.setdefault(package_id, {})
        package_values[str(position)] = float(value)

    def _get_signal_integration_package_id_for_display_spec(self, spec: dict, spec_index: int) -> str:
        key = spec.get("key")
        if isinstance(key, tuple) and len(key) >= 2 and key[0] == "sensor":
            sensor_id = str(key[1]).strip().upper()
            if sensor_id:
                return sensor_id

        label = str(spec.get("label", "")).strip().upper()
        if "_" in label:
            sensor_id = label.split("_", 1)[0]
            if sensor_id:
                return sensor_id

        channel_count = max(1, len(SIGNAL_INTEGRATION_POSITION_ORDER))
        package_index = int(spec_index) // channel_count
        return f"PACKAGE{package_index + 1}"

    def _first_complete_signal_integration_package_values(
        self,
        values_by_package: dict[str, dict[str, float]],
    ) -> dict[str, float] | None:
        for package_values in values_by_package.values():
            if all(position in package_values for position in SHEAR_SENSOR_POSITIONS):
                return dict(package_values)
        return None

    def _get_array_sensor_grid_positions(self) -> dict[str, tuple[int, int]]:
        active_config = self.get_active_sensor_configuration() if hasattr(self, "get_active_sensor_configuration") else {}
        array_layout = active_config.get("array_layout", {}) if isinstance(active_config, dict) else {}
        cells = array_layout.get("cells", []) if isinstance(array_layout, dict) else []

        positions: dict[str, tuple[int, int]] = {}
        for row_index, row_cells in enumerate(cells):
            if not isinstance(row_cells, list):
                continue
            for col_index, cell_value in enumerate(row_cells):
                sensor_id = normalize_array_cell(cell_value)
                if sensor_id:
                    positions[sensor_id] = (int(row_index), int(col_index))
        return positions

    def _get_signal_integration_package_layout(self) -> list[dict[str, object]]:
        grid_positions = self._get_array_sensor_grid_positions()
        selected_sensors = list(self.config.get("selected_array_sensors", []))
        layout: list[dict[str, object]] = []

        if hasattr(self, "is_array_sensor_selection_mode") and self.is_array_sensor_selection_mode():
            if hasattr(self, "get_sensor_package_groups"):
                sensor_groups = self.get_sensor_package_groups(len(SHEAR_SENSOR_POSITIONS))
            else:
                sensor_groups = []

            for index, group in enumerate(sensor_groups):
                fallback_id = selected_sensors[index] if index < len(selected_sensors) else f"PACKAGE{index + 1}"
                sensor_id = str(group.get("sensor_id") or fallback_id).strip().upper()
                layout.append({
                    "sensor_id": sensor_id,
                    "grid_position": grid_positions.get(sensor_id),
                    "color_slot": index,
                    "channels": list(group.get("channels", [])),
                    "mux": int(group.get("mux", 1)),
                })
            return layout

        values_by_package = getattr(self, "_latest_signal_integration_values_by_package", {})
        package_ids = list(values_by_package.keys()) or ["PACKAGE1"]
        for index, package_id in enumerate(package_ids):
            layout.append({
                "sensor_id": package_id,
                "grid_position": None,
                "color_slot": index,
                "channels": [],
                "mux": 1,
            })
        return layout

    def _is_multi_package_force_mode(self, package_layout: list[dict[str, object]]) -> bool:
        if not (hasattr(self, "is_array_sensor_selection_mode") and self.is_array_sensor_selection_mode()):
            return False
        package_ids = [
            str(item.get("sensor_id", "")).strip().upper()
            for item in package_layout
            if str(item.get("sensor_id", "")).strip()
        ]
        return len(package_ids) > 1

    def _plot_signal_integration_package_force_series(
        self,
        package_series_by_position: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]],
        package_layout: list[dict[str, object]],
        desired_curve_keys: set,
    ) -> None:
        layout_by_sensor_id = {
            str(item.get("sensor_id", "")).strip().upper(): item
            for item in package_layout
            if str(item.get("sensor_id", "")).strip()
        }

        for fallback_slot, (package_id, position_series) in enumerate(package_series_by_position.items()):
            if not all(position in position_series for position in SHEAR_SENSOR_POSITIONS):
                continue

            times, total_force_series = self._compute_package_total_force_series(position_series, package_id)
            if times.size == 0 or total_force_series.size == 0:
                continue

            layout_item = layout_by_sensor_id.get(str(package_id).strip().upper(), {})
            color_slot = int(layout_item.get("color_slot", fallback_slot))
            if hasattr(self, "pressure_map_widget"):
                color = self.pressure_map_widget.package_color_for_index(color_slot)
            else:
                fallback_color = PLOT_COLORS[color_slot % len(PLOT_COLORS)]
                color = tuple(int(component) for component in fallback_color)

            curve_key = ("signal_integration_package_force", str(package_id).strip().upper())
            desired_curve_keys.add(curve_key)
            self._set_signal_integration_curve_data(
                curve_key,
                f"{package_id} total force",
                pg.mkPen(color=color, width=SIGNAL_INTEGRATION_PLOT_LINE_WIDTH),
                times,
                total_force_series,
            )

    def _compute_package_total_force_series(
        self,
        position_series: dict[str, tuple[np.ndarray, np.ndarray]],
        package_id: str | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        if not all(position in position_series for position in SHEAR_SENSOR_POSITIONS):
            return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)

        lengths = [
            len(np.asarray(position_series[position][0], dtype=np.float64))
            for position in SHEAR_SENSOR_POSITIONS
        ]
        if not lengths:
            return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
        sample_count = min(lengths)
        if sample_count <= 0:
            return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)

        threshold = float(self.shear_noise_threshold_spin.value())
        package_gains = self._pressure_sensor_gains_for_package(package_id)
        calibrated_series: dict[str, np.ndarray] = {}
        reference_times: np.ndarray | None = None

        for position in SHEAR_SENSOR_POSITIONS:
            data_samples, time_samples = position_series[position]
            data_array = np.asarray(data_samples, dtype=np.float64).reshape(-1)[-sample_count:]
            time_array = np.asarray(time_samples, dtype=np.float64).reshape(-1)[-sample_count:]
            if reference_times is None:
                reference_times = time_array
            gain = float(package_gains.get(position, DEFAULT_SHEAR_CALIBRATION_GAIN))
            thresholded = np.where(np.abs(data_array) < threshold, 0.0, data_array)
            calibrated_series[position] = thresholded * gain

        if reference_times is None:
            return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)

        # Total normal force is invariant to the shear-removal and baseline-offset
        # steps used downstream, so it can be computed as the calibrated channel sum.
        total_force_series = np.zeros(sample_count, dtype=np.float64)
        for position in SHEAR_SENSOR_POSITIONS:
            total_force_series += calibrated_series[position]

        return reference_times, total_force_series

    def _update_shear_visualization_from_latest(self) -> None:
        if not hasattr(self, "pressure_map_widget"):
            return

        latest_values = getattr(self, "_latest_signal_integration_values_by_position", {})
        package_values = getattr(self, "_latest_signal_integration_values_by_package", {})
        package_id: str | None = None
        if isinstance(package_values, dict):
            for candidate_id, candidate_values in package_values.items():
                if all(position in candidate_values for position in SHEAR_SENSOR_POSITIONS):
                    package_id = str(candidate_id)
                    latest_values = dict(candidate_values)
                    break

        if not all(position in latest_values for position in SHEAR_SENSOR_POSITIONS):
            self._latest_shear_result = None
            self._update_pressure_map_from_latest()
            return

        calibrated_values = self._calibrate_signal_integration_values_for_shear(latest_values, package_id)
        self._latest_shear_result = self.shear_detector.detect(calibrated_values)
        self._update_pressure_map_from_latest()

    def _update_pressure_map_from_latest(self) -> None:
        if not hasattr(self, "pressure_map_widget"):
            return
        if self._latest_shear_result is None:
            self._latest_normal_force_result = None
            self._latest_pressure_map_result = None
            self.pressure_map_widget.update_display(None, None, None)
            return

        try:
            package_displays = self._build_pressure_map_package_displays()
            if len(package_displays) > 1:
                first_package = package_displays[0]
                self._latest_shear_result = first_package.shear_result
                self._latest_normal_force_result = first_package.normal_force_result
                self._latest_pressure_map_result = first_package.pressure_result
                self.pressure_map_widget.update_package_displays(package_displays)
                return

            self._latest_normal_force_result = self.normal_force_calculator.compute(
                self._latest_shear_result.residual,
            )
            self._latest_pressure_map_result = self.pressure_map_generator.generate(
                self._latest_normal_force_result.normalized,
            )
            self.pressure_map_widget.update_display(
                self._latest_normal_force_result,
                self._latest_pressure_map_result,
                self._latest_shear_result,
            )
        except Exception as exc:
            self._latest_normal_force_result = None
            self._latest_pressure_map_result = None
            self.pressure_map_widget.update_display(None, None, None)
            if hasattr(self, "log_status"):
                self.log_status(f"ERROR updating Pressure Map visualization: {exc}")

    def _build_pressure_map_package_displays(self) -> list[PressureMapPackageDisplay]:
        values_by_package = getattr(self, "_latest_signal_integration_values_by_package", {})
        layout_by_sensor_id = {
            str(item.get("sensor_id", "")).upper(): item
            for item in getattr(self, "_latest_signal_integration_package_layout", [])
            if item.get("sensor_id")
        }
        package_displays: list[PressureMapPackageDisplay] = []

        for fallback_index, (sensor_id, package_values) in enumerate(values_by_package.items()):
            if not all(position in package_values for position in SHEAR_SENSOR_POSITIONS):
                continue

            calibrated_values = self._calibrate_signal_integration_values_for_shear(package_values, str(sensor_id))
            shear_result = self.shear_detector.detect(calibrated_values)
            normal_force_result = self.normal_force_calculator.compute(shear_result.residual)
            pressure_result = self.pressure_map_generator.generate(normal_force_result.normalized)
            layout_item = layout_by_sensor_id.get(str(sensor_id).upper(), {})
            color_slot = int(layout_item.get("color_slot", fallback_index))
            package_displays.append(
                PressureMapPackageDisplay(
                    sensor_id=str(sensor_id),
                    normal_force_result=normal_force_result,
                    pressure_result=pressure_result,
                    shear_result=shear_result,
                    grid_position=layout_item.get("grid_position"),
                    color=self.pressure_map_widget.package_color_for_index(color_slot),
                )
            )

        return package_displays

    def _calibrate_signal_integration_values_for_shear(
        self,
        latest_values: dict[str, float],
        package_id: str | None = None,
    ) -> dict[str, float]:
        threshold = float(self.shear_noise_threshold_spin.value())
        package_gains = self._pressure_sensor_gains_for_package(package_id)
        calibrated: dict[str, float] = {}
        for position in SHEAR_SENSOR_POSITIONS:
            value = float(latest_values.get(position, 0.0))
            if abs(value) < threshold:
                value = 0.0
            gain = float(package_gains.get(position, DEFAULT_SHEAR_CALIBRATION_GAIN))
            calibrated[position] = value * gain
        return calibrated

    def _get_shear_position_for_display_spec(self, spec: dict, spec_index: int) -> str | None:
        key = spec.get("key")
        if isinstance(key, tuple) and len(key) >= 3 and key[0] == "sensor":
            candidate = str(key[2]).strip().upper()
            if candidate in SHEAR_SENSOR_POSITIONS:
                return candidate

        label = str(spec.get("label", "")).strip().upper()
        if "_" in label:
            candidate = label.rsplit("_", 1)[-1]
            if candidate in SHEAR_SENSOR_POSITIONS:
                return candidate

        if hasattr(self, "get_active_channel_sensor_map"):
            channel_map = [str(value).strip().upper() for value in self.get_active_channel_sensor_map()]
        else:
            channel_map = list(SIGNAL_INTEGRATION_POSITION_ORDER)

        if spec_index < len(channel_map) and channel_map[spec_index] in SHEAR_SENSOR_POSITIONS:
            return channel_map[spec_index]

        return None

    def _get_signal_integration_raw_snapshot(self) -> tuple[np.ndarray, np.ndarray, float] | None:
        data_buffer = self.raw_data_buffer
        if data_buffer is None or self.sweep_timestamps_buffer is None or self.samples_per_sweep <= 0:
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index

        actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
        if actual_sweeps <= 0:
            return None

        window_sweeps = self._get_signal_integration_window_sweeps(actual_sweeps)
        processing_sweeps = self._get_signal_integration_processing_sweeps(
            actual_sweeps,
            window_sweeps,
        )
        snapshot = self._extract_recent_buffer_window(
            data_buffer,
            actual_sweeps,
            current_write_index,
            processing_sweeps,
        )
        if snapshot is None:
            return None

        data_array, timestamps_array = snapshot
        visible_start_index = max(0, len(timestamps_array) - window_sweeps)
        visible_start_time_sec = float(timestamps_array[visible_start_index])
        return data_array, timestamps_array, visible_start_time_sec

    def _get_signal_integration_window_sweeps(self, actual_sweeps: int) -> int:
        display_window_sec = max(
            SIGNAL_INTEGRATION_DISPLAY_WINDOW_MIN_SEC,
            float(getattr(self, "signal_integration_display_window_sec", DEFAULT_DISPLAY_WINDOW_SEC)),
        )
        avg_sample_time_sec = float(getattr(self, "_cached_avg_sample_time_sec", 0.0) or 0.0)
        sweep_time_sec = avg_sample_time_sec * max(1, int(getattr(self, "samples_per_sweep", 1)))
        if sweep_time_sec > 0.0:
            requested_sweeps = max(1, int(math.ceil(display_window_sec / sweep_time_sec)))
        else:
            requested_sweeps = min(self.window_size_spin.value(), MAX_PLOT_SWEEPS)
        return max(1, min(int(actual_sweeps), MAX_PLOT_SWEEPS, requested_sweeps))

    def _get_signal_integration_processing_sweeps(
        self,
        actual_sweeps: int,
        display_sweeps: int,
    ) -> int:
        integration_window_samples = max(
            SIGNAL_INTEGRATION_WINDOW_MIN_SAMPLES,
            int(getattr(self, "signal_integration_window_samples", DEFAULT_INTEGRATION_WINDOW_SAMPLES)),
        )
        history_sweeps = max(
            SIGNAL_INTEGRATION_HISTORY_MIN_SWEEPS,
            display_sweeps * SIGNAL_INTEGRATION_HISTORY_DISPLAY_WINDOW_MULTIPLIER,
            integration_window_samples * SIGNAL_INTEGRATION_HISTORY_INTEGRATION_WINDOW_MULTIPLIER,
        )
        requested_sweeps = display_sweeps + history_sweeps
        return max(
            display_sweeps,
            min(
                int(actual_sweeps),
                SIGNAL_INTEGRATION_MAX_PROCESSING_SWEEPS,
                requested_sweeps,
            ),
        )

    def _prepare_signal_integration_integrated_series(
        self,
        spec: dict,
        data_array: np.ndarray,
        timestamps_array: np.ndarray,
        avg_sample_time_sec: float,
        max_samples_per_series: int,
        visible_start_time_sec: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray, float | None] | None:
        sample_indices = spec["sample_indices"]
        if not sample_indices:
            return None

        sample_index_array = np.asarray(sample_indices, dtype=np.int32)
        channel_counts = data_array[:, sample_index_array].reshape(-1).astype(np.float64, copy=False)

        time_offsets = sample_index_array.astype(np.float64) * avg_sample_time_sec
        channel_times = (timestamps_array.reshape(-1, 1) + time_offsets.reshape(1, -1)).reshape(-1)

        channel_data = self._convert_signal_integration_counts_to_voltage(channel_counts)
        channel_data = self._remove_signal_integration_dc_bias(channel_data, channel_times)
        channel_data = self._integrate_signal_integration_voltage_samples(channel_data)
        channel_data = self._apply_signal_integration_sensor_polarity(channel_data)

        if visible_start_time_sec is not None:
            visible_mask = channel_times >= float(visible_start_time_sec)
            channel_data = channel_data[visible_mask]
            channel_times = channel_times[visible_mask]

        latest_value = float(channel_data[-1]) if channel_data.size > 0 else None

        if len(channel_data) > max_samples_per_series:
            downsample_factor = max(1, len(channel_data) // max_samples_per_series)
            channel_data = channel_data[::downsample_factor]
            channel_times = channel_times[::downsample_factor]

        return channel_data, channel_times, latest_value

    def _convert_signal_integration_counts_to_voltage(self, adc_counts: np.ndarray) -> np.ndarray:
        max_adc_value = float((2 ** IADC_RESOLUTION_BITS) - 1)
        return (np.asarray(adc_counts, dtype=np.float64) / max_adc_value) * float(self.get_vref_voltage())

    def _apply_signal_integration_sensor_polarity(self, integrated_samples: np.ndarray) -> np.ndarray:
        """Apply the active sensor package polarity before shear/pressure use.

        Args:
            integrated_samples: One-dimensional integrated voltage samples for
                a sensor-position trace.

        Returns:
            Integrated samples multiplied by -1 when the active sensor
            configuration is marked as reverse polarity; otherwise a float64
            copy of the original samples.

        Raises:
            None.
        """
        samples = np.asarray(integrated_samples, dtype=np.float64)
        multiplier = SENSOR_POLARITY_NORMAL_MULTIPLIER
        if hasattr(self, "is_active_sensor_reverse_polarity") and self.is_active_sensor_reverse_polarity():
            multiplier = SENSOR_POLARITY_REVERSED_MULTIPLIER
        return samples * multiplier

    def _remove_signal_integration_dc_bias(
        self,
        voltage_samples: np.ndarray,
        sample_times_sec: np.ndarray,
    ) -> np.ndarray:
        cutoff_hz = float(getattr(self, "signal_integration_hpf_cutoff_hz", DEFAULT_HPF_CUTOFF_HZ))
        if cutoff_hz <= SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ:
            return voltage_samples

        if voltage_samples.size == 0:
            return voltage_samples

        sample_rate_hz = self._estimate_signal_integration_series_rate_hz(sample_times_sec)
        if sample_rate_hz <= 0.0:
            return self._subtract_signal_integration_visible_mean(
                voltage_samples,
                "sample rate unavailable",
            )

        nyquist_hz = sample_rate_hz / SIGNAL_INTEGRATION_NYQUIST_DIVISOR
        if cutoff_hz >= nyquist_hz:
            return self._subtract_signal_integration_visible_mean(
                voltage_samples,
                f"cutoff {cutoff_hz:.2f} Hz is at or above Nyquist {nyquist_hz:.2f} Hz",
            )

        if not SCIPY_FILTERS_AVAILABLE:
            return self._subtract_signal_integration_visible_mean(
                voltage_samples,
                "SciPy unavailable",
            )

        settings = self._build_signal_integration_hpf_settings(cutoff_hz)
        try:
            filtered = self._signal_integration_filter_engine.filter_signal(
                settings,
                voltage_samples,
                sample_rate_hz,
            )
            self._signal_integration_filter_warning = ""
            return np.asarray(filtered, dtype=np.float64)
        except Exception as exc:
            return self._subtract_signal_integration_visible_mean(
                voltage_samples,
                str(exc),
            )

    def _integrate_signal_integration_voltage_samples(self, voltage_samples: np.ndarray) -> np.ndarray:
        samples = np.asarray(voltage_samples, dtype=np.float64).reshape(-1)
        if samples.size == 0:
            return samples

        window_samples = max(
            SIGNAL_INTEGRATION_WINDOW_MIN_SAMPLES,
            int(getattr(self, "signal_integration_window_samples", DEFAULT_INTEGRATION_WINDOW_SAMPLES)),
        )
        if window_samples <= SIGNAL_INTEGRATION_WINDOW_MIN_SAMPLES:
            return samples.copy()

        cumulative_sum = np.cumsum(samples, dtype=np.float64)
        integrated = cumulative_sum.copy()
        if samples.size > window_samples:
            integrated[window_samples:] = cumulative_sum[window_samples:] - cumulative_sum[:-window_samples]
        return integrated

    def _build_signal_integration_hpf_settings(self, cutoff_hz: float) -> dict:
        return {
            "enabled": True,
            "main_type": "highpass",
            "order": SIGNAL_INTEGRATION_HPF_FILTER_ORDER,
            "low_cutoff_hz": FILTER_DEFAULT_LOW_CUTOFF_HZ,
            "high_cutoff_hz": float(cutoff_hz),
            "notches": [],
        }

    def _estimate_signal_integration_series_rate_hz(self, sample_times_sec: np.ndarray) -> float:
        sample_times = np.asarray(sample_times_sec, dtype=np.float64).reshape(-1)
        if sample_times.size <= 1:
            return 0.0

        sample_intervals = np.diff(sample_times)
        positive_intervals = sample_intervals[sample_intervals > 0.0]
        if positive_intervals.size == 0:
            return 0.0

        return float(1.0 / np.median(positive_intervals))

    def _subtract_signal_integration_visible_mean(
        self,
        voltage_samples: np.ndarray,
        reason: str,
    ) -> np.ndarray:
        self._record_signal_integration_filter_warning(reason)
        return voltage_samples - float(np.mean(voltage_samples))

    def _record_signal_integration_filter_warning(self, reason: str) -> None:
        message = f"Signal Integration HPF fallback: {reason}; subtracting visible-window mean"
        if message == self._signal_integration_filter_warning:
            return
        self._signal_integration_filter_warning = message
        if hasattr(self, "log_status"):
            self.log_status(message)

    def _get_or_create_signal_integration_curve(self, curve_key: Hashable, name: str, pen):
        curve = self.signal_integration_curves.get(curve_key)
        if curve is None:
            curve = self.signal_integration_plot_widget.plot([], [], pen=pen, name=name)
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method="peak")
            self.signal_integration_curves[curve_key] = curve
        return curve

    def _set_signal_integration_curve_data(
        self,
        curve_key: Hashable,
        name: str,
        pen,
        x_data: np.ndarray,
        y_data: np.ndarray,
    ) -> None:
        curve = self._get_or_create_signal_integration_curve(curve_key, name, pen)
        curve.setVisible(True)
        curve.setPen(pen)
        curve.setData(x=x_data, y=y_data)

    def _plot_signal_integration_repeat_series(
        self,
        spec: dict,
        color: tuple[int, int, int],
        channel_data: np.ndarray,
        channel_times: np.ndarray,
        repeat_count: int,
        desired_curve_keys: set,
    ) -> bool:
        try:
            num_samples = len(channel_data) // repeat_count
            if num_samples <= 0:
                return False

            channel_data_2d = channel_data[:num_samples * repeat_count].reshape(-1, repeat_count)
            channel_times_2d = channel_times[:num_samples * repeat_count].reshape(-1, repeat_count)

            for repeat_idx in range(repeat_count):
                repeat_data = channel_data_2d[:, repeat_idx]
                repeat_times = channel_times_2d[:, repeat_idx]

                if repeat_idx == 0:
                    pen = pg.mkPen(color=color, width=SIGNAL_INTEGRATION_PLOT_LINE_WIDTH)
                else:
                    lighter_color = tuple(
                        int(component * SIGNAL_INTEGRATION_DIMMED_COLOR_FRACTION)
                        for component in color
                    )
                    pen = pg.mkPen(
                        color=lighter_color,
                        width=SIGNAL_INTEGRATION_REPEAT_LINE_WIDTH,
                        style=Qt.PenStyle.DashLine,
                    )

                name = f"{spec['label']}.{repeat_idx}"
                curve_key = ("signal_integration_repeat", spec["key"], repeat_idx)
                desired_curve_keys.add(curve_key)
                self._set_signal_integration_curve_data(curve_key, name, pen, repeat_times, repeat_data)

            return True
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"ERROR: Failed to render Signal Integration repeats - {exc}")
            return False

    def _plot_signal_integration_single_or_average_series(
        self,
        spec: dict,
        color: tuple[int, int, int],
        channel_data: np.ndarray,
        channel_times: np.ndarray,
        repeat_count: int,
        desired_curve_keys: set,
    ) -> bool:
        if self.show_average_radio.isChecked() and repeat_count > 1:
            try:
                num_samples = len(channel_data) // repeat_count
                if num_samples <= 0:
                    return False

                channel_data_2d = channel_data[:num_samples * repeat_count].reshape(-1, repeat_count)
                channel_times_2d = channel_times[:num_samples * repeat_count].reshape(-1, repeat_count)
                channel_data = np.mean(channel_data_2d, axis=1)
                channel_times = channel_times_2d[:, 0]
                name = f"{spec['label']} (avg)"
                pen = pg.mkPen(
                    color=color,
                    width=SIGNAL_INTEGRATION_AVERAGE_LINE_WIDTH,
                    style=Qt.PenStyle.DashLine,
                )
                curve_key = ("signal_integration_avg", spec["key"], 0)
            except Exception as exc:
                if hasattr(self, "log_status"):
                    self.log_status(f"ERROR: Failed to average Signal Integration data - {exc}")
                return False
        else:
            name = spec["label"]
            pen = pg.mkPen(color=color, width=SIGNAL_INTEGRATION_PLOT_LINE_WIDTH)
            curve_key = ("signal_integration_single", spec["key"], 0)

        desired_curve_keys.add(curve_key)
        self._set_signal_integration_curve_data(curve_key, name, pen, channel_times, channel_data)
        return True

    def _apply_signal_integration_axis_settings(self, *, is_package_force_mode: bool = False) -> None:
        if is_package_force_mode:
            self.signal_integration_plot_widget.setLabel("left", "Total Normal Force")
        else:
            self.signal_integration_plot_widget.setLabel("left", "Integrated HPF Voltage", units="V samples")
        self.signal_integration_plot_widget.enableAutoRange(axis="y")
        self.signal_integration_plot_widget.setLabel("bottom", "Time", units="s")
