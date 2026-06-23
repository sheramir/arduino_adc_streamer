"""
Display Panels Mixin
====================
GUI components for plot display, visualization controls, and timing information.
Includes the active tabbed interface for time-series, spectrum, and sensor views.
"""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QComboBox, QCheckBox, QSpinBox, QWidget, QScrollArea, QTabWidget
)
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import types

from constants.ui import (
    CHANNEL_SCROLL_HEIGHT,
    DEFAULT_WINDOW_SIZE,
    HEATMAP_TAB_NAME,
    PRESSURE_MAP_TAB_NAME,
    PZT_RS_PZT_TAB_NAME,
    ROSETTE_TAB_NAME,
    SENSOR_TAB_NAME,
    SPECTRUM_TAB_NAME,
    TIME_SERIES_TAB_NAME,
    WINDOW_SIZE_MAX,
    WINDOW_SIZE_MIN,
)
from constants.plotting import (
    ROSETTE_FIXED_Y_DECIMALS,
    ROSETTE_FIXED_Y_MAX_DEFAULT_OHMS,
    ROSETTE_FIXED_Y_MAX_LIMIT_OHMS,
    ROSETTE_FIXED_Y_MIN_DEFAULT_OHMS,
    ROSETTE_FIXED_Y_MIN_LIMIT_OHMS,
    ROSETTE_FIXED_Y_STEP_OHMS,
    ROSETTE_MOVING_AVERAGE_DEFAULT_SAMPLES,
    ROSETTE_MOVING_AVERAGE_MAX_SAMPLES,
    ROSETTE_MOVING_AVERAGE_MIN_SAMPLES,
)
from gui.custom_widgets import NonScrollableDoubleSpinBox as QDoubleSpinBox


class DisplayPanelsMixin:
    """Mixin class for display and visualization GUI components."""
    
    def create_plot_section(self) -> QWidget:
        """Create tabbed visualization section with active application views.
        
        Returns:
            QWidget: Widget containing Time Series, Spectrum, and Sensor tabs.
        """
        # Create tab widget
        self.visualization_tabs = QTabWidget()
        
        # Create time-series tab
        timeseries_tab = self.create_timeseries_tab()
        self.visualization_tabs.addTab(timeseries_tab, TIME_SERIES_TAB_NAME)
        self.timeseries_tab_index = 0

        rosette_tab = self.create_rosette_timeseries_tab()
        self.visualization_tabs.addTab(rosette_tab, ROSETTE_TAB_NAME)
        self.rosette_tab_index = 1
        self.visualization_tabs.setTabVisible(self.rosette_tab_index, False)

            # Create pressure map tab (from PressureMapPanelMixin)
        signal_integration_tab = self.create_signal_integration_tab()
        self.visualization_tabs.addTab(signal_integration_tab, PRESSURE_MAP_TAB_NAME)
        self.signal_integration_tab_index = 2

        heatmap_tab = self.create_heatmap_tab()
        self.visualization_tabs.addTab(heatmap_tab, HEATMAP_TAB_NAME)
        self.heatmap_tab_index = 3

        # Create spectrum tab (from SpectrumPanelMixin)
        spectrum_tab = self.create_spectrum_tab()
        self.visualization_tabs.addTab(spectrum_tab, SPECTRUM_TAB_NAME)
        self.spectrum_tab_index = 4

        # Create sensor tab last (from SensorPanelMixin)
        sensor_tab = self.create_sensor_tab()
        self.visualization_tabs.addTab(sensor_tab, SENSOR_TAB_NAME)
        self.sensor_tab_index = 5
        
        return self.visualization_tabs
    
    def create_timeseries_tab(self) -> QWidget:
        """Create the traditional time-series plotting tab with controls.
        
        Returns:
            QWidget: Widget containing plot, controls, and timing
        """
        tab_widget = QWidget()
        layout = QVBoxLayout()

        # Plot section
        plot_group = QGroupBox("Real-time Data Visualization")
        plot_layout = QVBoxLayout()

        # Create main plot widget with dual Y-axes (ADC on left, Force on right)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'ADC Value', units='counts')
        self.plot_widget.setLabel('bottom', 'Sample Index')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Create a second ViewBox for force data (right Y-axis)
        self.force_viewbox = pg.ViewBox()
        self.plot_widget.scene().addItem(self.force_viewbox)
        self.plot_widget.getAxis('right').linkToView(self.force_viewbox)
        self.force_viewbox.setXLink(self.plot_widget)  # Link X-axis
        self.plot_widget.setLabel('right', 'Force', units='N')
        self.plot_widget.showAxis('right')

        # Guard wheel zoom during capture to avoid heavy redraws freezing UI
        vb = self.plot_widget.getViewBox()
        vb._orig_wheel_event = vb.wheelEvent

        def wheel_event_guard(_self, event):
            if getattr(self, 'is_capturing', False):
                event.ignore()
                return
            vb._orig_wheel_event(event)

        vb.wheelEvent = types.MethodType(wheel_event_guard, vb)

        # Also guard at the PlotWidget level in case wheel events are caught there first
        pw = self.plot_widget
        pw._orig_wheel_event = pw.wheelEvent

        def pw_wheel_event_guard(_self, event):
            if getattr(self, 'is_capturing', False):
                event.ignore()
                return
            pw._orig_wheel_event(event)

        pw.wheelEvent = types.MethodType(pw_wheel_event_guard, pw)
        
        # Add legends
        self.adc_legend = self.plot_widget.addLegend(offset=(10, 10))
        self.force_legend = pg.LegendItem(offset=(10, 100))
        self.force_legend.setParentItem(self.plot_widget.graphicsItem())
        
        # Connect view resize to update force viewbox geometry
        self.plot_widget.getViewBox().sigResized.connect(self.update_force_viewbox)
        self.update_force_viewbox()

        plot_layout.addWidget(self.plot_widget)

        # Combined info label
        self.plot_info_label = QLabel("ADC - Sweeps: 0 | Samples: 0  |  Force: 0 samples  |  Clock: 0.000s")
        plot_layout.addWidget(self.plot_info_label)

        self.charge_time_label = QLabel("")
        self.charge_time_label.setStyleSheet("font-family: monospace;")
        self.charge_time_label.setVisible(False)
        plot_layout.addWidget(self.charge_time_label)

        self.discharge_time_label = QLabel("")
        self.discharge_time_label.setStyleSheet("font-family: monospace;")
        self.discharge_time_label.setVisible(False)
        plot_layout.addWidget(self.discharge_time_label)

        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)
        
        # Add timing section
        layout.addWidget(self.create_timing_section())
        
        # Add visualization controls
        layout.addWidget(self.create_visualization_controls())

        tab_widget.setLayout(layout)
        return tab_widget

    def create_rosette_timeseries_tab(self) -> QWidget:
        """Create the Rosette time-series plotting tab used by PZT_RS mode."""
        tab_widget = QWidget()
        layout = QVBoxLayout()

        plot_group = QGroupBox("Rosette Time Series")
        plot_layout = QVBoxLayout()

        self.rosette_plot_widget = pg.PlotWidget()
        self.rosette_plot_widget.setBackground('w')
        self.rosette_plot_widget.setLabel('left', 'Resistance', units='')
        self.rosette_plot_widget.setLabel('bottom', 'Time', units='s')
        self.rosette_plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.rosette_plot_widget.setMouseEnabled(x=False, y=False)
        self.rosette_plot_widget.setMenuEnabled(False)

        self.rosette_force_viewbox = pg.ViewBox()
        self.rosette_plot_widget.scene().addItem(self.rosette_force_viewbox)
        self.rosette_plot_widget.getAxis('right').linkToView(self.rosette_force_viewbox)
        # Do NOT use setXLink here — bidirectional X linking causes the force viewbox's
        # autorange (with no data) to propagate back to the main plot and disable its
        # X autorange, making RS curves invisible. Instead, sync one-directionally via
        # sigXRangeChanged in _sync_rosette_force_x_range.
        self.rosette_plot_widget.setLabel('right', 'Force', units='N')
        self.rosette_plot_widget.showAxis('right')

        self.rosette_plot_widget.addLegend(offset=(10, 10))
        self.rosette_force_legend = pg.LegendItem(offset=(10, 100))
        self.rosette_force_legend.setParentItem(self.rosette_plot_widget.graphicsItem())
        self.rosette_plot_widget.getViewBox().sigResized.connect(self.update_rosette_force_viewbox)
        self.rosette_plot_widget.getViewBox().sigXRangeChanged.connect(self._sync_rosette_force_x_range)
        self.update_rosette_force_viewbox()
        plot_layout.addWidget(self.rosette_plot_widget)

        self.rosette_plot_info_label = QLabel("Rosette - Sweeps: 0 | Samples: 0")
        plot_layout.addWidget(self.rosette_plot_info_label)

        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)
        layout.addWidget(self.create_rosette_visualization_controls())
        layout.addStretch()

        tab_widget.setLayout(layout)
        return tab_widget

    def create_rosette_visualization_controls(self) -> QGroupBox:
        """Create Rosette-specific visibility and display controls."""
        group = QGroupBox("Rosette Visualization Controls")
        main_layout = QVBoxLayout()

        channel_group = QGroupBox("Display Rosettes")
        channel_main_layout = QVBoxLayout()

        self.rosette_channel_checkboxes_container = QWidget()
        self.rosette_channel_checkboxes_layout = QGridLayout()
        self.rosette_channel_checkboxes_layout.setSpacing(5)
        self.rosette_channel_checkboxes_container.setLayout(self.rosette_channel_checkboxes_layout)

        scroll = QScrollArea()
        scroll.setWidget(self.rosette_channel_checkboxes_container)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(CHANNEL_SCROLL_HEIGHT)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        channel_main_layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        self.rosette_select_all_btn = QPushButton("All")
        self.rosette_select_all_btn.clicked.connect(self.select_all_rosette_channels)
        self.rosette_select_all_btn.setMaximumWidth(60)
        btn_layout.addWidget(self.rosette_select_all_btn)

        self.rosette_deselect_all_btn = QPushButton("None")
        self.rosette_deselect_all_btn.clicked.connect(self.deselect_all_rosette_channels)
        self.rosette_deselect_all_btn.setMaximumWidth(60)
        btn_layout.addWidget(self.rosette_deselect_all_btn)
        btn_layout.addStretch()
        channel_main_layout.addLayout(btn_layout)

        channel_group.setLayout(channel_main_layout)
        main_layout.addWidget(channel_group)

        display_group = QGroupBox("Display Mode")
        display_layout = QGridLayout()

        self.rosette_subtract_baseline_check = QCheckBox("Subtract Baseline")
        self.rosette_subtract_baseline_check.setChecked(False)
        self.rosette_subtract_baseline_check.setToolTip("Subtract the Rosette baseline captured by Zero Signals")
        self.rosette_subtract_baseline_check.stateChanged.connect(self.trigger_plot_update)
        display_layout.addWidget(self.rosette_subtract_baseline_check, 0, 0)

        self.rosette_zero_signals_btn = QPushButton("Zero Signals")
        self.rosette_zero_signals_btn.setToolTip("Capture each Rosette baseline from the latest samples")
        self.rosette_zero_signals_btn.setMaximumWidth(90)
        self.rosette_zero_signals_btn.clicked.connect(self.zero_rosette_plot_baselines)
        display_layout.addWidget(self.rosette_zero_signals_btn, 0, 1)

        self.rosette_moving_average_check = QCheckBox("Moving Avg")
        self.rosette_moving_average_check.setChecked(False)
        self.rosette_moving_average_check.setToolTip("Show a trailing moving average for each Rosette")
        self.rosette_moving_average_check.stateChanged.connect(self.trigger_plot_update)
        display_layout.addWidget(self.rosette_moving_average_check, 0, 2)

        display_layout.addWidget(QLabel("Samples:"), 0, 3)
        self.rosette_moving_average_spin = QSpinBox()
        self.rosette_moving_average_spin.setRange(
            ROSETTE_MOVING_AVERAGE_MIN_SAMPLES,
            ROSETTE_MOVING_AVERAGE_MAX_SAMPLES,
        )
        self.rosette_moving_average_spin.setValue(ROSETTE_MOVING_AVERAGE_DEFAULT_SAMPLES)
        self.rosette_moving_average_spin.setToolTip("Trailing sample count used by Rosette moving average")
        self.rosette_moving_average_spin.valueChanged.connect(self.trigger_plot_update)
        display_layout.addWidget(self.rosette_moving_average_spin, 0, 4)

        display_layout.addWidget(QLabel("Y Range:"), 1, 0)
        self.rosette_yaxis_range_combo = QComboBox()
        self.rosette_yaxis_range_combo.addItems(["Adaptive", "Fixed"])
        self.rosette_yaxis_range_combo.setCurrentText("Adaptive")
        self.rosette_yaxis_range_combo.setToolTip("Adaptive: auto-scale to visible Rosette data | Fixed: use Min and Max")
        self.rosette_yaxis_range_combo.currentIndexChanged.connect(self.on_rosette_yaxis_range_changed)
        display_layout.addWidget(self.rosette_yaxis_range_combo, 1, 1)

        self.rosette_yaxis_min_label = QLabel("Min:")
        display_layout.addWidget(self.rosette_yaxis_min_label, 1, 2)
        self.rosette_yaxis_min_spin = QDoubleSpinBox()
        self.rosette_yaxis_min_spin.setRange(
            ROSETTE_FIXED_Y_MIN_LIMIT_OHMS,
            ROSETTE_FIXED_Y_MAX_LIMIT_OHMS,
        )
        self.rosette_yaxis_min_spin.setDecimals(ROSETTE_FIXED_Y_DECIMALS)
        self.rosette_yaxis_min_spin.setSingleStep(ROSETTE_FIXED_Y_STEP_OHMS)
        self.rosette_yaxis_min_spin.setSuffix(" ohm")
        self.rosette_yaxis_min_spin.setValue(ROSETTE_FIXED_Y_MIN_DEFAULT_OHMS)
        self.rosette_yaxis_min_spin.setToolTip("Minimum resistance shown when Rosette Y Range is Fixed")
        self.rosette_yaxis_min_spin.valueChanged.connect(self.on_rosette_yaxis_range_changed)
        display_layout.addWidget(self.rosette_yaxis_min_spin, 1, 3)

        self.rosette_yaxis_max_label = QLabel("Max:")
        display_layout.addWidget(self.rosette_yaxis_max_label, 1, 4)
        self.rosette_yaxis_max_spin = QDoubleSpinBox()
        self.rosette_yaxis_max_spin.setRange(
            ROSETTE_FIXED_Y_MIN_LIMIT_OHMS,
            ROSETTE_FIXED_Y_MAX_LIMIT_OHMS,
        )
        self.rosette_yaxis_max_spin.setDecimals(ROSETTE_FIXED_Y_DECIMALS)
        self.rosette_yaxis_max_spin.setSingleStep(ROSETTE_FIXED_Y_STEP_OHMS)
        self.rosette_yaxis_max_spin.setSuffix(" ohm")
        self.rosette_yaxis_max_spin.setValue(ROSETTE_FIXED_Y_MAX_DEFAULT_OHMS)
        self.rosette_yaxis_max_spin.setToolTip("Maximum resistance shown when Rosette Y Range is Fixed")
        self.rosette_yaxis_max_spin.valueChanged.connect(self.on_rosette_yaxis_range_changed)
        display_layout.addWidget(self.rosette_yaxis_max_spin, 1, 5)
        self.on_rosette_yaxis_range_changed()

        display_group.setLayout(display_layout)
        main_layout.addWidget(display_group)

        force_group = QGroupBox("Display Force")
        force_layout = QHBoxLayout()
        self.rosette_force_x_checkbox = QCheckBox("X Force [N]")
        self.rosette_force_x_checkbox.setChecked(True)
        self.rosette_force_x_checkbox.setStyleSheet("QCheckBox { color: red; }")
        self.rosette_force_x_checkbox.stateChanged.connect(self.update_force_plot)
        force_layout.addWidget(self.rosette_force_x_checkbox)

        self.rosette_force_z_checkbox = QCheckBox("Z Force [N]")
        self.rosette_force_z_checkbox.setChecked(True)
        self.rosette_force_z_checkbox.setStyleSheet("QCheckBox { color: blue; }")
        self.rosette_force_z_checkbox.stateChanged.connect(self.update_force_plot)
        force_layout.addWidget(self.rosette_force_z_checkbox)
        force_layout.addStretch()
        force_group.setLayout(force_layout)
        main_layout.addWidget(force_group)

        group.setLayout(main_layout)
        return group

    def update_pzt_rs_timeseries_tabs_visibility(self):
        """Show the PZT/RS split time-series tabs only for PZT_RS mode."""
        if not hasattr(self, 'visualization_tabs') or not hasattr(self, 'rosette_tab_index'):
            return

        show_rosette = bool(
            hasattr(self, 'is_array_pzt_rs_mode') and self.is_array_pzt_rs_mode()
        )
        self.visualization_tabs.setTabVisible(self.rosette_tab_index, show_rosette)
        self.visualization_tabs.setTabText(
            self.timeseries_tab_index,
            PZT_RS_PZT_TAB_NAME if show_rosette else TIME_SERIES_TAB_NAME,
        )
        if hasattr(self, 'update_rosette_channel_list'):
            self.update_rosette_channel_list()

        if not show_rosette and self.visualization_tabs.currentIndex() == self.rosette_tab_index:
            self.visualization_tabs.setCurrentIndex(self.timeseries_tab_index)
    
    def update_force_viewbox(self):
        """Update force viewbox geometry to match main plot viewbox."""
        if hasattr(self, 'force_viewbox'):
            self.force_viewbox.setGeometry(self.plot_widget.getViewBox().sceneBoundingRect())

    def update_rosette_force_viewbox(self):
        """Update Rosette force viewbox geometry to match the Rosette plot."""
        if not hasattr(self, 'rosette_force_viewbox'):
            return
        self.rosette_force_viewbox.setGeometry(
            self.rosette_plot_widget.getViewBox().sceneBoundingRect()
        )
        self._sync_rosette_force_x_range()

    def _sync_rosette_force_x_range(self, *_args):
        """Push main rosette plot X range into the force viewbox (one-directional, no feedback)."""
        if not hasattr(self, 'rosette_force_viewbox') or not hasattr(self, 'rosette_plot_widget'):
            return
        x_min, x_max = self.rosette_plot_widget.getViewBox().viewRange()[0]
        self.rosette_force_viewbox.setXRange(x_min, x_max, padding=0)

    def on_rosette_yaxis_range_changed(self, _value=None):
        """Apply Rosette Y-axis control visibility and queue a redraw."""
        fixed = (
            hasattr(self, 'rosette_yaxis_range_combo')
            and self.rosette_yaxis_range_combo.currentText() == "Fixed"
        )
        for widget_name in (
            'rosette_yaxis_min_label',
            'rosette_yaxis_min_spin',
            'rosette_yaxis_max_label',
            'rosette_yaxis_max_spin',
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setVisible(fixed)
        if hasattr(self, 'apply_rosette_y_axis_range'):
            self.apply_rosette_y_axis_range()
        if hasattr(self, 'trigger_plot_update'):
            self.trigger_plot_update()

    def create_visualization_controls(self) -> QGroupBox:
        """Create visualization control section."""
        group = QGroupBox("Visualization Controls")
        main_layout = QVBoxLayout()

        # Channel selector with compact checkboxes
        channel_group = QGroupBox("Display Channels")
        channel_main_layout = QVBoxLayout()

        # Container for checkboxes (will be populated dynamically)
        self.channel_checkboxes_container = QWidget()
        self.channel_checkboxes_layout = QGridLayout()
        self.channel_checkboxes_layout.setSpacing(5)
        self.channel_checkboxes_container.setLayout(self.channel_checkboxes_layout)

        # Scroll area for many channels
        scroll = QScrollArea()
        scroll.setWidget(self.channel_checkboxes_container)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(CHANNEL_SCROLL_HEIGHT)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        channel_main_layout.addWidget(scroll)

        # Control buttons (compact, horizontal)
        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("All")
        self.select_all_btn.clicked.connect(self.select_all_channels)
        self.select_all_btn.setMaximumWidth(60)
        btn_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("None")
        self.deselect_all_btn.clicked.connect(self.deselect_all_channels)
        self.deselect_all_btn.setMaximumWidth(60)
        btn_layout.addWidget(self.deselect_all_btn)

        btn_layout.addStretch()
        channel_main_layout.addLayout(btn_layout)

        channel_group.setLayout(channel_main_layout)
        main_layout.addWidget(channel_group)

        # Consolidated Display Settings
        display_settings_group = QGroupBox("Display Settings")
        display_settings_layout = QGridLayout()

        # Row 0: Y-Axis Range and Units
        display_settings_layout.addWidget(QLabel("Y Range:"), 0, 0)
        self.yaxis_range_combo = QComboBox()
        self.yaxis_range_combo.addItems(["Adaptive", "Full-Scale"])
        self.yaxis_range_combo.setCurrentIndex(1)  # Default to Full-Scale
        self.yaxis_range_combo.setToolTip("Adaptive: Auto-scale to visible data | Full-Scale: 0 to max ADC value")
        self.yaxis_range_combo.currentIndexChanged.connect(self.on_yaxis_range_changed)
        display_settings_layout.addWidget(self.yaxis_range_combo, 0, 1)

        display_settings_layout.addWidget(QLabel("Y Units:"), 0, 2)
        self.yaxis_units_combo = QComboBox()
        self.yaxis_units_combo.addItems(["Values", "Voltage"])
        self.yaxis_units_combo.setToolTip("Values: Raw ADC samples | Voltage: Convert using Vref")
        self.yaxis_units_combo.currentIndexChanged.connect(self.on_yaxis_units_changed)
        display_settings_layout.addWidget(self.yaxis_units_combo, 0, 3)

        # Row 1: Window controls
        display_settings_layout.addWidget(QLabel("Window Size:"), 1, 0)
        self.window_size_spin = QSpinBox()
        self.window_size_spin.setRange(WINDOW_SIZE_MIN, WINDOW_SIZE_MAX)
        self.window_size_spin.setValue(DEFAULT_WINDOW_SIZE)
        self.window_size_spin.setToolTip("Number of sweeps to display during capture (scrolling mode)")
        display_settings_layout.addWidget(self.window_size_spin, 1, 1)

        self.reset_graph_btn = QPushButton("Reset View")
        self.reset_graph_btn.clicked.connect(self.reset_graph_view)
        self.reset_graph_btn.setToolTip("Reset X-axis to show window size")
        self.reset_graph_btn.setMaximumWidth(100)
        display_settings_layout.addWidget(self.reset_graph_btn, 1, 2)

        self.full_view_btn = QPushButton("Full View")
        self.full_view_btn.clicked.connect(self.full_graph_view)
        self.full_view_btn.setToolTip("Show the complete capture from Start to Stop, loading cache data when needed")
        self.full_view_btn.setMaximumWidth(100)
        self.full_view_btn.setEnabled(False)  # Disabled by default (enabled after capture)
        display_settings_layout.addWidget(self.full_view_btn, 1, 3)

        display_settings_group.setLayout(display_settings_layout)
        main_layout.addWidget(display_settings_group)

        # Repeats visualization mode (horizontal layout for compactness)
        repeats_group = QGroupBox("Display Mode")
        repeats_layout = QHBoxLayout()

        self.show_all_repeats_radio = QCheckBox("All Repeats")
        self.show_all_repeats_radio.setChecked(True)
        self.show_all_repeats_radio.toggled.connect(self.trigger_plot_update)
        repeats_layout.addWidget(self.show_all_repeats_radio)

        self.show_average_radio = QCheckBox("Average")
        self.show_average_radio.setChecked(False)
        self.show_average_radio.toggled.connect(self.trigger_plot_update)
        repeats_layout.addWidget(self.show_average_radio)
        
        self.subtract_baseline_check = QCheckBox("Subtract Baseline")
        self.subtract_baseline_check.setChecked(False)
        self.subtract_baseline_check.setToolTip("Subtract the initial DC baseline from each channel")
        self.subtract_baseline_check.stateChanged.connect(self.trigger_plot_update)
        repeats_layout.addWidget(self.subtract_baseline_check)

        self.zero_signals_btn = QPushButton("Zero Signals")
        self.zero_signals_btn.setToolTip("Reset the baseline to the current values")
        self.zero_signals_btn.setMaximumWidth(90)
        self.zero_signals_btn.clicked.connect(self.zero_plot_baselines)
        repeats_layout.addWidget(self.zero_signals_btn)

        repeats_layout.addStretch()
        repeats_group.setLayout(repeats_layout)
        main_layout.addWidget(repeats_group)

        group.setLayout(main_layout)
        return group

    def create_timing_section(self) -> QGroupBox:
        """Create timing measurement display section."""
        group = QGroupBox("Sampling Rate")
        layout = QHBoxLayout()

        # Keep rate labels for internal timing updates but hide them from the GUI
        self.per_channel_rate_label = QLabel("- Hz")
        self.per_channel_rate_label.setStyleSheet("QLabel { font-weight: bold; color: #2196F3; }")
        self.per_channel_rate_label.setVisible(False)

        self.total_rate_label = QLabel("- Hz")
        self.total_rate_label.setStyleSheet("QLabel { font-weight: bold; color: #FF9800; }")
        self.total_rate_label.setVisible(False)

        # Between samples timing
        layout.addWidget(QLabel("Sample Interval:"))
        self.between_samples_label = QLabel("- µs")
        self.between_samples_label.setStyleSheet("QLabel { font-weight: bold; }")
        layout.addWidget(self.between_samples_label)

        layout.addWidget(QLabel("  |  "))

        # Block gap timing
        layout.addWidget(QLabel("Block Gap:"))
        self.block_gap_label = QLabel("- ms")
        self.block_gap_label.setStyleSheet("QLabel { font-weight: bold; color: #FFFFFF; }")
        layout.addWidget(self.block_gap_label)

        layout.addStretch()
        group.setLayout(layout)
        return group
