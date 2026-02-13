"""
Control Panels Mixin
====================
GUI components for serial connection, ADC configuration, acquisition settings, and run control.
"""

import os
from PyQt6.QtWidgets import (
    QGroupBox, QGridLayout, QLabel, QPushButton, QLineEdit, 
    QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt

from config_constants import (
    GROUND_PIN_MIN, GROUND_PIN_MAX, REPEAT_COUNT_MIN, REPEAT_COUNT_MAX, 
    REPEAT_COUNT_DEFAULT, BUFFER_SIZE_MIN, BUFFER_SIZE_MAX, DEFAULT_BUFFER_SIZE,
    TIMED_RUN_MIN, TIMED_RUN_MAX, TIMED_RUN_DEFAULT,
    ANALYZER555_DEFAULT_RB_OHMS, ANALYZER555_DEFAULT_RK_OHMS,
    ANALYZER555_DEFAULT_CF_VALUE, ANALYZER555_DEFAULT_CF_UNIT,
    ANALYZER555_DEFAULT_RXMAX_OHMS
)


class ControlPanelsMixin:
    """Mixin class for control panel GUI components."""
    
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

        # 555 Analyzer Parameters (shown only in 555 mode)
        self.rb_label = QLabel("Rb [Ω]:")
        layout.addWidget(self.rb_label, 6, 0)
        self.rb_spin = QDoubleSpinBox()
        self.rb_spin.setRange(0.0, 1e9)
        self.rb_spin.setDecimals(2)
        self.rb_spin.setValue(ANALYZER555_DEFAULT_RB_OHMS)
        self.rb_spin.valueChanged.connect(self.on_rb_changed)
        layout.addWidget(self.rb_spin, 6, 1)
        self.rb_apply_btn = QPushButton("Apply")
        self.rb_apply_btn.clicked.connect(self.on_apply_rb_clicked)
        layout.addWidget(self.rb_apply_btn, 6, 2)

        self.rk_label = QLabel("Rk [Ω]:")
        layout.addWidget(self.rk_label, 7, 0)
        self.rk_spin = QDoubleSpinBox()
        self.rk_spin.setRange(0.0, 1e9)
        self.rk_spin.setDecimals(2)
        self.rk_spin.setValue(ANALYZER555_DEFAULT_RK_OHMS)
        self.rk_spin.valueChanged.connect(self.on_rk_changed)
        layout.addWidget(self.rk_spin, 7, 1)
        self.rk_apply_btn = QPushButton("Apply")
        self.rk_apply_btn.clicked.connect(self.on_apply_rk_clicked)
        layout.addWidget(self.rk_apply_btn, 7, 2)

        self.cf_label = QLabel("Cf:")
        layout.addWidget(self.cf_label, 8, 0)
        self.cf_value_spin = QDoubleSpinBox()
        self.cf_value_spin.setRange(0.0001, 1e6)
        self.cf_value_spin.setDecimals(6)
        self.cf_value_spin.setValue(ANALYZER555_DEFAULT_CF_VALUE)
        self.cf_value_spin.valueChanged.connect(self.on_cf_changed)
        layout.addWidget(self.cf_value_spin, 8, 1)
        self.cf_unit_combo = QComboBox()
        self.cf_unit_combo.addItems(["pF", "nF", "uF"])
        self.cf_unit_combo.setCurrentText(ANALYZER555_DEFAULT_CF_UNIT)
        self.cf_unit_combo.currentTextChanged.connect(self.on_cf_changed)
        layout.addWidget(self.cf_unit_combo, 8, 2)
        self.cf_apply_btn = QPushButton("Apply")
        self.cf_apply_btn.clicked.connect(self.on_apply_cf_clicked)
        layout.addWidget(self.cf_apply_btn, 8, 3)

        self.rxmax_label = QLabel("Rx max [Ω]:")
        layout.addWidget(self.rxmax_label, 9, 0)
        self.rxmax_spin = QDoubleSpinBox()
        self.rxmax_spin.setRange(1.0, 1e12)
        self.rxmax_spin.setDecimals(2)
        self.rxmax_spin.setValue(ANALYZER555_DEFAULT_RXMAX_OHMS)
        self.rxmax_spin.valueChanged.connect(self.on_rxmax_changed)
        layout.addWidget(self.rxmax_spin, 9, 1)
        self.rxmax_apply_btn = QPushButton("Apply")
        self.rxmax_apply_btn.clicked.connect(self.on_apply_rxmax_clicked)
        layout.addWidget(self.rxmax_apply_btn, 9, 2)

        self.rb_label.hide()
        self.rb_spin.hide()
        self.rb_apply_btn.hide()
        self.rk_label.hide()
        self.rk_spin.hide()
        self.rk_apply_btn.hide()
        self.cf_label.hide()
        self.cf_value_spin.hide()
        self.cf_unit_combo.hide()
        self.cf_apply_btn.hide()
        self.rxmax_label.hide()
        self.rxmax_spin.hide()
        self.rxmax_apply_btn.hide()

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
        self.ground_pin_label = QLabel("Ground Pin:")
        layout.addWidget(self.ground_pin_label, 1, 0)
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
