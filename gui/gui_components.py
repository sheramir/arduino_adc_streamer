"""
GUI Components Mixin
====================
Contains all UI section creation methods for the ADC Streamer application.
"""

import os
from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QLineEdit, QComboBox, QCheckBox, QSpinBox, 
    QTextEdit, QWidget, QScrollArea
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import pyqtgraph as pg

from config_constants import (
    GROUND_PIN_MIN, GROUND_PIN_MAX, REPEAT_COUNT_MIN, REPEAT_COUNT_MAX, 
    REPEAT_COUNT_DEFAULT, BUFFER_SIZE_MIN, BUFFER_SIZE_MAX, DEFAULT_BUFFER_SIZE,
    TIMED_RUN_MIN, TIMED_RUN_MAX, TIMED_RUN_DEFAULT,
    SWEEP_RANGE_MIN, SWEEP_RANGE_MAX, SWEEP_RANGE_DEFAULT_MAX,
    WINDOW_SIZE_MIN, WINDOW_SIZE_MAX, DEFAULT_WINDOW_SIZE,
    NOTES_INPUT_HEIGHT, STATUS_TEXT_HEIGHT, CHANNEL_SCROLL_HEIGHT
)


class GUIComponentsMixin:
    """Mixin class for GUI component creation methods."""
    
    def create_serial_section(self) -> QGroupBox:
        """Create serial connection control section."""
        group = QGroupBox("Serial Connection")
        layout = QGridLayout()

        # ADC Port selection
        layout.addWidget(QLabel("ADC Port:"), 0, 0)
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo, 0, 1)

        self.refresh_ports_btn = QPushButton("Refresh")
        self.refresh_ports_btn.clicked.connect(self.update_port_list)
        layout.addWidget(self.refresh_ports_btn, 0, 2)

        # Connect/Disconnect button for ADC
        self.connect_btn = QPushButton("Connect ADC")
        self.connect_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.connect_btn, 1, 0, 1, 2)
        
        # MCU label (shows detected MCU type)
        self.mcu_label = QLabel("MCU: -")
        self.mcu_label.setStyleSheet("QLabel { font-weight: bold; color: #2196F3; }")
        layout.addWidget(self.mcu_label, 1, 2)
        
        # Force sensor port selection
        layout.addWidget(QLabel("Force Port:"), 2, 0)
        self.force_port_combo = QComboBox()
        layout.addWidget(self.force_port_combo, 2, 1, 1, 2)
        
        # Connect/Disconnect button for force sensors
        self.force_connect_btn = QPushButton("Connect Force")
        self.force_connect_btn.clicked.connect(self.toggle_force_connection)
        layout.addWidget(self.force_connect_btn, 3, 0, 1, 3)

        group.setLayout(layout)
        return group

    def create_adc_config_section(self) -> QGroupBox:
        """Create ADC configuration section."""
        group = QGroupBox("ADC Configuration")
        layout = QGridLayout()

        # Voltage Reference (hidden for Teensy)
        self.vref_label = QLabel("Voltage Reference:")
        layout.addWidget(self.vref_label, 0, 0)
        self.vref_combo = QComboBox()
        self.vref_combo.addItems(["1.2V (Internal)", "3.3V (VDD)"])
        self.vref_combo.setCurrentIndex(1)  # Default to VDD
        self.vref_combo.currentTextChanged.connect(self.on_vref_changed)
        layout.addWidget(self.vref_combo, 0, 1)

        # OSR (Oversampling Ratio / Averaging)
        self.osr_label = QLabel("OSR (Oversampling):")
        layout.addWidget(self.osr_label, 1, 0)
        self.osr_combo = QComboBox()
        self.osr_combo.addItems(["2", "4", "8"])
        self.osr_combo.setCurrentText("2")
        self.osr_combo.setToolTip("Oversampling ratio: higher = better SNR, lower sample rate")
        self.osr_combo.currentTextChanged.connect(self.on_osr_changed)
        layout.addWidget(self.osr_combo, 1, 1)

        # Gain (Analog Amplification) (hidden for Teensy)
        self.gain_label = QLabel("Gain (Analog):")
        layout.addWidget(self.gain_label, 2, 0)
        self.gain_combo = QComboBox()
        self.gain_combo.addItems(["1×", "2×", "3×", "4×"])
        self.gain_combo.setCurrentText("1×")
        self.gain_combo.setToolTip("Analog amplification factor (1× to 4×)")
        self.gain_combo.currentTextChanged.connect(self.on_gain_changed)
        layout.addWidget(self.gain_combo, 2, 1)

        # Teensy-specific: Conversion Speed
        self.conv_speed_label = QLabel("Conversion Speed:")
        layout.addWidget(self.conv_speed_label, 3, 0)
        self.conv_speed_combo = QComboBox()
        self.conv_speed_combo.addItems(["low", "med", "high", "ad10", "ad20"])
        self.conv_speed_combo.setCurrentText("med")
        self.conv_speed_combo.setToolTip("ADC conversion speed (Teensy only)")
        self.conv_speed_combo.currentTextChanged.connect(self.on_conv_speed_changed)
        layout.addWidget(self.conv_speed_combo, 3, 1)
        self.conv_speed_label.hide()
        self.conv_speed_combo.hide()

        # Teensy-specific: Sampling Speed
        self.samp_speed_label = QLabel("Sampling Speed:")
        layout.addWidget(self.samp_speed_label, 4, 0)
        self.samp_speed_combo = QComboBox()
        self.samp_speed_combo.addItems(["vlow", "low", "lmed", "med", "mhigh", "high", "hvhigh", "vhigh"])
        self.samp_speed_combo.setCurrentText("med")
        self.samp_speed_combo.setToolTip("ADC sampling speed (Teensy only)")
        self.samp_speed_combo.currentTextChanged.connect(self.on_samp_speed_changed)
        layout.addWidget(self.samp_speed_combo, 4, 1)
        self.samp_speed_label.hide()
        self.samp_speed_combo.hide()

        # Teensy-specific: Sampling Rate
        self.sample_rate_label = QLabel("Sampling Rate [Hz]:")
        layout.addWidget(self.sample_rate_label, 5, 0)
        self.sample_rate_spin = QSpinBox()
        self.sample_rate_spin.setRange(0, 1000000)  # 0 to 1 MHz
        self.sample_rate_spin.setValue(0)
        self.sample_rate_spin.setSpecialValueText("Free-run (max)")
        self.sample_rate_spin.setToolTip("Sampling rate in Hz, 0 = free-run at maximum speed (Teensy only)")
        self.sample_rate_spin.valueChanged.connect(self.on_sample_rate_changed)
        layout.addWidget(self.sample_rate_spin, 5, 1)
        self.sample_rate_label.hide()
        self.sample_rate_spin.hide()

        group.setLayout(layout)
        return group

    def create_acquisition_section(self) -> QGroupBox:
        """Create acquisition settings section."""
        group = QGroupBox("Acquisition Settings")
        layout = QGridLayout()

        # Channels sequence
        layout.addWidget(QLabel("Channels Sequence:"), 0, 0)
        self.channels_input = QLineEdit()
        self.channels_input.setPlaceholderText("e.g., 0,1,1,2,3")
        self.channels_input.textChanged.connect(self.on_channels_changed)
        layout.addWidget(self.channels_input, 0, 1, 1, 2)

        # Ground pin
        layout.addWidget(QLabel("Ground Pin:"), 1, 0)
        self.ground_pin_spin = QSpinBox()
        self.ground_pin_spin.setRange(GROUND_PIN_MIN, GROUND_PIN_MAX)
        self.ground_pin_spin.setValue(0)  # Default to pin 0
        self.ground_pin_spin.valueChanged.connect(self.on_ground_pin_changed)
        layout.addWidget(self.ground_pin_spin, 1, 1)

        # Use ground sample
        self.use_ground_check = QCheckBox("Use Ground Sample")
        self.use_ground_check.setChecked(False)  # Default to disabled
        self.use_ground_check.stateChanged.connect(self.on_use_ground_changed)
        layout.addWidget(self.use_ground_check, 1, 2)

        # Repeat count
        layout.addWidget(QLabel("Repeat Count:"), 2, 0)
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(REPEAT_COUNT_MIN, REPEAT_COUNT_MAX)
        self.repeat_spin.setValue(REPEAT_COUNT_DEFAULT)
        self.repeat_spin.valueChanged.connect(self.on_repeat_changed)
        layout.addWidget(self.repeat_spin, 2, 1)

        # Buffer size (sweeps per block)
        layout.addWidget(QLabel("Sweeps per block (buffer):"), 3, 0)
        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(BUFFER_SIZE_MIN, BUFFER_SIZE_MAX)
        self.buffer_spin.setValue(DEFAULT_BUFFER_SIZE)
        self.buffer_spin.setToolTip("Number of sweeps sent per block from Arduino")
        self.buffer_spin.valueChanged.connect(self.on_buffer_size_changed)
        layout.addWidget(self.buffer_spin, 3, 1)

        group.setLayout(layout)
        return group

    def create_run_control_section(self) -> QGroupBox:
        """Create run control section."""
        group = QGroupBox("Run Control")
        layout = QGridLayout()

        # Configure button
        self.configure_btn = QPushButton("Configure Arduino")
        self.configure_btn.setEnabled(False)
        self.configure_btn.clicked.connect(self.configure_arduino)
        self.configure_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        layout.addWidget(self.configure_btn, 0, 0, 1, 2)

        # Start and Stop buttons on same line
        self.start_btn = QPushButton("Start")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_capture)
        self.start_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        layout.addWidget(self.start_btn, 1, 0)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_capture)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        layout.addWidget(self.stop_btn, 1, 1)

        # Timed run
        self.timed_run_check = QCheckBox("Timed Run (ms):")
        layout.addWidget(self.timed_run_check, 2, 0)

        self.timed_run_spin = QSpinBox()
        self.timed_run_spin.setRange(TIMED_RUN_MIN, TIMED_RUN_MAX)
        self.timed_run_spin.setValue(TIMED_RUN_DEFAULT)
        self.timed_run_spin.setEnabled(False)
        self.timed_run_check.stateChanged.connect(
            lambda state: self.timed_run_spin.setEnabled(state == Qt.CheckState.Checked.value)
        )
        layout.addWidget(self.timed_run_spin, 2, 1)

        # Clear data button
        self.clear_btn = QPushButton("Clear Data")
        self.clear_btn.clicked.connect(self.clear_data)
        layout.addWidget(self.clear_btn, 3, 0, 1, 2)

        group.setLayout(layout)
        return group

    def create_file_management_section(self) -> QGroupBox:
        """Create file management section."""
        group = QGroupBox("Data Export")
        layout = QGridLayout()

        # Directory selection
        layout.addWidget(QLabel("Directory:"), 0, 0)
        self.dir_input = QLineEdit()
        # Default save directory - uses current user's home directory
        self.dir_input.setText(os.path.join(os.path.expanduser("~"), "Documents", "sensetics", "data", "adc"))
        layout.addWidget(self.dir_input, 0, 1)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_directory)
        layout.addWidget(self.browse_btn, 0, 2)

        # Filename
        layout.addWidget(QLabel("Filename:"), 1, 0)
        self.filename_input = QLineEdit()
        self.filename_input.setText("adc_data")
        layout.addWidget(self.filename_input, 1, 1, 1, 2)

        # Notes
        layout.addWidget(QLabel("Notes:"), 2, 0, Qt.AlignmentFlag.AlignTop)
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Add notes about this capture (optional)")
        self.notes_input.setMaximumHeight(NOTES_INPUT_HEIGHT)
        layout.addWidget(self.notes_input, 2, 1, 1, 2)

        # Sample range selection
        self.use_range_check = QCheckBox("Save Range:")
        self.use_range_check.setToolTip("Enable to save only a specific range of sweeps")
        self.use_range_check.stateChanged.connect(self.on_use_range_changed)
        layout.addWidget(self.use_range_check, 3, 0)

        # Min sweep
        self.min_sweep_spin = QSpinBox()
        self.min_sweep_spin.setRange(SWEEP_RANGE_MIN, SWEEP_RANGE_MAX)
        self.min_sweep_spin.setValue(SWEEP_RANGE_MIN)
        self.min_sweep_spin.setPrefix("Min: ")
        self.min_sweep_spin.setEnabled(False)
        self.min_sweep_spin.setToolTip("Starting sweep index (inclusive)")
        layout.addWidget(self.min_sweep_spin, 3, 1)

        # Max sweep
        self.max_sweep_spin = QSpinBox()
        self.max_sweep_spin.setRange(SWEEP_RANGE_MIN, SWEEP_RANGE_MAX)
        self.max_sweep_spin.setValue(SWEEP_RANGE_DEFAULT_MAX)
        self.max_sweep_spin.setPrefix("Max: ")
        self.max_sweep_spin.setEnabled(False)
        self.max_sweep_spin.setToolTip("Ending sweep index (inclusive)")
        layout.addWidget(self.max_sweep_spin, 3, 2)

        # Save data button
        self.save_data_btn = QPushButton("Save Data (CSV)")
        self.save_data_btn.clicked.connect(self.save_data)
        layout.addWidget(self.save_data_btn, 4, 0, 1, 2)

        # Save image button
        self.save_image_btn = QPushButton("Save Plot Image")
        self.save_image_btn.clicked.connect(self.save_plot_image)
        layout.addWidget(self.save_image_btn, 4, 2)

        group.setLayout(layout)
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
        self.block_gap_label.setStyleSheet("QLabel { font-weight: bold; color: #9C27B0; }")
        layout.addWidget(self.block_gap_label)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def create_status_section(self) -> QGroupBox:
        """Create status display section."""
        group = QGroupBox("Status & Messages")
        layout = QVBoxLayout()

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(STATUS_TEXT_HEIGHT)
        font = QFont("Courier", 9)
        self.status_text.setFont(font)
        layout.addWidget(self.status_text)

        group.setLayout(layout)
        return group

    def create_plot_section(self) -> QGroupBox:
        """Create plotting section with pyqtgraph."""
        group = QGroupBox("Real-time Data Visualization")
        layout = QVBoxLayout()

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
        self.plot_widget.setLabel('right', 'Force (Raw)', units='')
        self.plot_widget.showAxis('right')
        
        # Add legends
        self.adc_legend = self.plot_widget.addLegend(offset=(10, 10))
        self.force_legend = pg.LegendItem(offset=(10, 100))
        self.force_legend.setParentItem(self.plot_widget.graphicsItem())
        
        # Connect view resize to update force viewbox geometry
        self.plot_widget.getViewBox().sigResized.connect(self.update_force_viewbox)

        layout.addWidget(self.plot_widget)

        # Combined info label
        self.plot_info_label = QLabel("ADC - Sweeps: 0 | Samples: 0  |  Force: 0 samples")
        layout.addWidget(self.plot_info_label)

        group.setLayout(layout)
        return group
    
    def update_force_viewbox(self):
        """Update force viewbox geometry to match main plot viewbox."""
        if hasattr(self, 'force_viewbox'):
            self.force_viewbox.setGeometry(self.plot_widget.getViewBox().sceneBoundingRect())

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
        self.full_view_btn.setToolTip("Show all data from 0 to last sample (only available after capture finishes)")
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

        repeats_layout.addStretch()
        repeats_group.setLayout(repeats_layout)
        main_layout.addWidget(repeats_group)

        group.setLayout(main_layout)
        return group
