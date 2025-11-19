#!/usr/bin/env python3
"""
ADC Streamer GUI Application
=============================
A comprehensive GUI for controlling and visualizing data from the Arduino
Interactive ADC CSV Sweeper sketch.

Features:
- Serial port connection and configuration
- Real-time ADC configuration (resolution, voltage reference)
- Acquisition settings (channels, ground pin, repeat count, delay)
- Run control (continuous or timed runs)
- Real-time plotting with pyqtgraph
- Data export (CSV with metadata) and plot image export
- State management (parameter lock-out during capture)

Requirements:
- PyQt6
- pyserial
- pyqtgraph
- numpy
"""

import sys
import csv
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QComboBox,
    QCheckBox, QSpinBox, QTextEdit, QFileDialog, QGroupBox,
    QMessageBox, QSplitter, QScrollArea, QRadioButton
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor

import serial
import serial.tools.list_ports
import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter


class SerialReaderThread(QThread):
    """Background thread for reading serial data without blocking the GUI."""
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True

    def run(self):
        """Continuously read from serial port and emit signals."""
        buffer = ""
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self.serial_port.in_waiting > 0:
                        data = self.serial_port.read(self.serial_port.in_waiting)
                        try:
                            text = data.decode('utf-8', errors='ignore')
                            buffer += text

                            # Process complete lines
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = line.strip()
                                if line:
                                    self.data_received.emit(line)
                        except Exception as e:
                            self.error_occurred.emit(f"Decode error: {e}")
                else:
                    break

                self.msleep(10)  # Small delay to prevent CPU spinning

            except Exception as e:
                self.error_occurred.emit(f"Serial read error: {e}")
                break

    def stop(self):
        """Stop the thread."""
        self.running = False


class ADCStreamerGUI(QMainWindow):
    """Main GUI application for ADC streaming and visualization."""

    def __init__(self):
        super().__init__()

        # Serial connection
        self.serial_port: Optional[serial.Serial] = None
        self.serial_thread: Optional[SerialReaderThread] = None

        # Data storage
        self.raw_data: List[List[int]] = []  # List of sweeps (each sweep is a list of values)
        self.sweep_count = 0
        self.is_capturing = False

        # Configuration state
        self.config = {
            'channels': [],
            'repeat': 1,
            'delay_us': 0,
            'ground_pin': -1,
            'use_ground': False,
            'resolution': 12,
            'reference': 'vdd'
        }

        # Channel checkboxes for visualization
        self.channel_checkboxes: Dict[int, QCheckBox] = {}

        # Debounce timer for plot updates
        self.plot_update_timer = QTimer()
        self.plot_update_timer.setSingleShot(True)
        self.plot_update_timer.timeout.connect(self.update_plot)

        # Flag to prevent concurrent plot updates
        self.is_updating_plot = False

        # Initialize UI
        self.init_ui()

        # Update port list on startup
        self.update_port_list()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("ADC Streamer - Arduino Control & Visualization")
        self.setGeometry(100, 100, 1400, 900)

        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel: Controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(10)

        # Add control sections
        left_layout.addWidget(self.create_serial_section())
        left_layout.addWidget(self.create_adc_config_section())
        left_layout.addWidget(self.create_acquisition_section())
        left_layout.addWidget(self.create_run_control_section())
        left_layout.addWidget(self.create_file_management_section())
        left_layout.addWidget(self.create_status_section())
        left_layout.addStretch()

        # Right panel: Plotting and visualization
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(self.create_plot_section())
        right_layout.addWidget(self.create_visualization_controls())

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)  # Controls get 1 part
        splitter.setStretchFactor(1, 3)  # Plot gets 3 parts

        # Status bar
        self.statusBar().showMessage("Disconnected")

    def create_serial_section(self) -> QGroupBox:
        """Create serial connection control section."""
        group = QGroupBox("Serial Connection")
        layout = QGridLayout()

        # Port selection
        layout.addWidget(QLabel("Port:"), 0, 0)
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo, 0, 1)

        self.refresh_ports_btn = QPushButton("Refresh")
        self.refresh_ports_btn.clicked.connect(self.update_port_list)
        layout.addWidget(self.refresh_ports_btn, 0, 2)

        # Connect/Disconnect button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.connect_btn, 1, 0, 1, 3)

        group.setLayout(layout)
        return group

    def create_adc_config_section(self) -> QGroupBox:
        """Create ADC configuration section."""
        group = QGroupBox("ADC Configuration")
        layout = QGridLayout()

        # Resolution
        layout.addWidget(QLabel("Resolution (bits):"), 0, 0)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["8", "10", "12", "16"])
        self.resolution_combo.setCurrentText("12")
        self.resolution_combo.currentTextChanged.connect(self.on_resolution_changed)
        layout.addWidget(self.resolution_combo, 0, 1)

        # Voltage Reference
        layout.addWidget(QLabel("Voltage Reference:"), 1, 0)
        self.vref_combo = QComboBox()
        self.vref_combo.addItems(["1.2V (Internal)", "3.3V (VDD)", "0.8*VDD", "External 1.25V"])
        self.vref_combo.setCurrentIndex(1)  # Default to VDD
        self.vref_combo.currentTextChanged.connect(self.on_vref_changed)
        layout.addWidget(self.vref_combo, 1, 1)

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
        self.ground_pin_spin.setRange(-1, 255)
        self.ground_pin_spin.setValue(-1)
        self.ground_pin_spin.setSpecialValueText("Not Set")
        self.ground_pin_spin.valueChanged.connect(self.on_ground_pin_changed)
        layout.addWidget(self.ground_pin_spin, 1, 1)

        # Use ground sample
        self.use_ground_check = QCheckBox("Use Ground Sample")
        self.use_ground_check.stateChanged.connect(self.on_use_ground_changed)
        layout.addWidget(self.use_ground_check, 1, 2)

        # Repeat count
        layout.addWidget(QLabel("Repeat Count:"), 2, 0)
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 1000)
        self.repeat_spin.setValue(1)
        self.repeat_spin.valueChanged.connect(self.on_repeat_changed)
        layout.addWidget(self.repeat_spin, 2, 1)

        # Delay
        layout.addWidget(QLabel("Delay (µs):"), 3, 0)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 100000)
        self.delay_spin.setValue(0)
        self.delay_spin.valueChanged.connect(self.on_delay_changed)
        layout.addWidget(self.delay_spin, 3, 1)

        group.setLayout(layout)
        return group

    def create_run_control_section(self) -> QGroupBox:
        """Create run control section."""
        group = QGroupBox("Run Control")
        layout = QGridLayout()

        # Start button
        self.start_btn = QPushButton("Start")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_capture)
        self.start_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        layout.addWidget(self.start_btn, 0, 0, 1, 2)

        # Stop button
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_capture)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; }")
        layout.addWidget(self.stop_btn, 1, 0, 1, 2)

        # Timed run
        self.timed_run_check = QCheckBox("Timed Run (ms):")
        layout.addWidget(self.timed_run_check, 2, 0)

        self.timed_run_spin = QSpinBox()
        self.timed_run_spin.setRange(10, 3600000)  # 10ms to 1 hour
        self.timed_run_spin.setValue(1000)
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
        self.dir_input.setText(str(Path.home()))
        layout.addWidget(self.dir_input, 0, 1)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_directory)
        layout.addWidget(self.browse_btn, 0, 2)

        # Filename
        layout.addWidget(QLabel("Filename:"), 1, 0)
        self.filename_input = QLineEdit()
        self.filename_input.setText("adc_data")
        layout.addWidget(self.filename_input, 1, 1, 1, 2)

        # Save data button
        self.save_data_btn = QPushButton("Save Data (CSV)")
        self.save_data_btn.clicked.connect(self.save_data)
        layout.addWidget(self.save_data_btn, 2, 0, 1, 3)

        # Save image button
        self.save_image_btn = QPushButton("Save Plot Image")
        self.save_image_btn.clicked.connect(self.save_plot_image)
        layout.addWidget(self.save_image_btn, 3, 0, 1, 3)

        group.setLayout(layout)
        return group

    def create_status_section(self) -> QGroupBox:
        """Create status display section."""
        group = QGroupBox("Status & Messages")
        layout = QVBoxLayout()

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(150)
        font = QFont("Courier", 9)
        self.status_text.setFont(font)
        layout.addWidget(self.status_text)

        group.setLayout(layout)
        return group

    def create_plot_section(self) -> QGroupBox:
        """Create plotting section with pyqtgraph."""
        group = QGroupBox("Real-time Data Visualization")
        layout = QVBoxLayout()

        # Create plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'ADC Value', units='counts')
        self.plot_widget.setLabel('bottom', 'Sample Index')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()

        layout.addWidget(self.plot_widget)

        # Info label
        self.plot_info_label = QLabel("Sweeps: 0 | Total Samples: 0")
        layout.addWidget(self.plot_info_label)

        group.setLayout(layout)
        return group

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
        scroll.setMaximumHeight(80)
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

        # Scrolling window control
        window_group = QGroupBox("Display Window")
        window_layout = QHBoxLayout()

        window_layout.addWidget(QLabel("Window Size (sweeps):"))
        self.window_size_spin = QSpinBox()
        self.window_size_spin.setRange(10, 10000)
        self.window_size_spin.setValue(1000)
        self.window_size_spin.setToolTip("Number of sweeps to display during capture (scrolling mode)")
        window_layout.addWidget(self.window_size_spin)

        window_layout.addStretch()
        window_group.setLayout(window_layout)
        main_layout.addWidget(window_group)

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

        # Y-Axis Control (combined scaling and units)
        yaxis_group = QGroupBox("Y-Axis")
        yaxis_layout = QGridLayout()

        # Scaling mode (row 0)
        yaxis_layout.addWidget(QLabel("Range:"), 0, 0)
        self.adaptive_scale_radio = QRadioButton("Adaptive")
        self.adaptive_scale_radio.setChecked(True)
        self.adaptive_scale_radio.setToolTip("Auto-scale Y-axis to visible data range")
        self.adaptive_scale_radio.toggled.connect(self.trigger_plot_update)
        yaxis_layout.addWidget(self.adaptive_scale_radio, 0, 1)

        self.fullscale_radio = QRadioButton("Full-Scale")
        self.fullscale_radio.setToolTip("Fixed Y-axis: 0 to 2^ResolutionBits")
        self.fullscale_radio.toggled.connect(self.trigger_plot_update)
        yaxis_layout.addWidget(self.fullscale_radio, 0, 2)

        # Units mode (row 1)
        yaxis_layout.addWidget(QLabel("Units:"), 1, 0)
        self.raw_units_radio = QRadioButton("Values")
        self.raw_units_radio.setChecked(True)
        self.raw_units_radio.setToolTip("Display raw ADC values (samples)")
        self.raw_units_radio.toggled.connect(self.trigger_plot_update)
        yaxis_layout.addWidget(self.raw_units_radio, 1, 1)

        self.voltage_units_radio = QRadioButton("Voltage")
        self.voltage_units_radio.setToolTip("Convert to voltage using Vref and resolution")
        self.voltage_units_radio.toggled.connect(self.trigger_plot_update)
        yaxis_layout.addWidget(self.voltage_units_radio, 1, 2)

        yaxis_group.setLayout(yaxis_layout)
        main_layout.addWidget(yaxis_group)

        group.setLayout(main_layout)
        return group

    # Serial connection methods

    def update_port_list(self):
        """Update the list of available serial ports."""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(f"{port.device} - {port.description}")

        if self.port_combo.count() == 0:
            self.port_combo.addItem("No ports found")

    def toggle_connection(self):
        """Connect or disconnect from the serial port."""
        if self.serial_port is None or not self.serial_port.is_open:
            self.connect_serial()
        else:
            self.disconnect_serial()

    def connect_serial(self):
        """Connect to the selected serial port."""
        if self.port_combo.currentText() == "No ports found":
            self.log_status("ERROR: No serial ports available")
            return

        port_text = self.port_combo.currentText()
        port_name = port_text.split(" - ")[0]

        try:
            self.serial_port = serial.Serial(
                port=port_name,
                baudrate=115200,
                timeout=1
            )

            # Start serial reader thread
            self.serial_thread = SerialReaderThread(self.serial_port)
            self.serial_thread.data_received.connect(self.process_serial_data)
            self.serial_thread.error_occurred.connect(self.log_status)
            self.serial_thread.start()

            self.log_status(f"Connected to {port_name}")
            self.connect_btn.setText("Disconnect")
            self.start_btn.setEnabled(True)
            self.statusBar().showMessage("Connected")

            # Disable port selection during connection
            self.port_combo.setEnabled(False)
            self.refresh_ports_btn.setEnabled(False)

        except Exception as e:
            self.log_status(f"ERROR: Failed to connect - {e}")
            QMessageBox.critical(self, "Connection Error", f"Failed to connect:\n{e}")

    def disconnect_serial(self):
        """Disconnect from the serial port."""
        if self.is_capturing:
            self.stop_capture()

        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.serial_thread = None

        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()

        self.serial_port = None
        self.log_status("Disconnected")
        self.connect_btn.setText("Connect")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("Disconnected")

        # Re-enable port selection
        self.port_combo.setEnabled(True)
        self.refresh_ports_btn.setEnabled(True)

    def send_command(self, command: str):
        """Send a command to the Arduino."""
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(f"{command}\n".encode('utf-8'))
                self.log_status(f"Sent: {command}")
            except Exception as e:
                self.log_status(f"ERROR: Failed to send command - {e}")
        else:
            self.log_status("ERROR: Not connected to serial port")

    def process_serial_data(self, line: str):
        """Process incoming serial data."""
        if line.startswith('#'):
            # Status/configuration message
            self.log_status(line)
        else:
            # Data line (CSV)
            if self.is_capturing:
                try:
                    values = [int(v.strip()) for v in line.split(',')]
                    self.raw_data.append(values)
                    self.sweep_count += 1

                    # Update plot periodically (every 10 sweeps for performance)
                    if self.sweep_count % 10 == 0:
                        self.update_plot()
                        window_size = self.window_size_spin.value()
                        displayed_sweeps = min(len(self.raw_data), window_size)
                        self.plot_info_label.setText(
                            f"Sweeps: {self.sweep_count} (showing last {displayed_sweeps}) | Total Samples: {len(self.raw_data) * len(values)}"
                        )

                except Exception as e:
                    self.log_status(f"ERROR: Failed to parse data - {e}")

    def log_status(self, message: str):
        """Log a status message."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.status_text.append(f"[{timestamp}] {message}")
        # Auto-scroll to bottom
        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )

    # Configuration change handlers

    def on_resolution_changed(self, text: str):
        """Handle resolution change."""
        if self.serial_port and self.serial_port.is_open:
            self.send_command(f"res {text}")
            self.config['resolution'] = int(text)

    def on_vref_changed(self, text: str):
        """Handle voltage reference change."""
        if self.serial_port and self.serial_port.is_open:
            vref_map = {
                "1.2V (Internal)": "1.2",
                "3.3V (VDD)": "3.3",
                "0.8*VDD": "0.8vdd",
                "External 1.25V": "ext"
            }
            vref_cmd = vref_map.get(text, "3.3")
            self.send_command(f"ref {vref_cmd}")
            self.config['reference'] = vref_cmd

    def on_channels_changed(self, text: str):
        """Handle channels sequence change."""
        if self.serial_port and self.serial_port.is_open and text.strip():
            self.send_command(f"channels {text}")
            try:
                # Parse channels for visualization
                channels = [int(c.strip()) for c in text.split(',')]
                self.config['channels'] = channels
                self.update_channel_list()
            except:
                pass

    def on_ground_pin_changed(self, value: int):
        """Handle ground pin change."""
        if self.serial_port and self.serial_port.is_open:
            if value >= 0:
                self.send_command(f"ground {value}")
                self.config['ground_pin'] = value

    def on_use_ground_changed(self, state: int):
        """Handle use ground checkbox change."""
        if self.serial_port and self.serial_port.is_open:
            use_ground = state == Qt.CheckState.Checked.value
            self.send_command(f"ground {str(use_ground).lower()}")
            self.config['use_ground'] = use_ground

    def on_repeat_changed(self, value: int):
        """Handle repeat count change."""
        if self.serial_port and self.serial_port.is_open:
            self.send_command(f"repeat {value}")
            self.config['repeat'] = value

    def on_delay_changed(self, value: int):
        """Handle delay change."""
        if self.serial_port and self.serial_port.is_open:
            self.send_command(f"delay {value}")
            self.config['delay_us'] = value

    def update_channel_list(self):
        """Update the channel selector checkboxes based on configured channels."""
        # Clear existing checkboxes
        for checkbox in self.channel_checkboxes.values():
            checkbox.deleteLater()
        self.channel_checkboxes.clear()

        # Clear layout
        while self.channel_checkboxes_layout.count():
            item = self.channel_checkboxes_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.config['channels']:
            return

        # Get unique channels while preserving order
        unique_channels = []
        for ch in self.config['channels']:
            if ch not in unique_channels:
                unique_channels.append(ch)

        # Create checkboxes in a compact grid (6 columns)
        max_columns = 6
        for idx, ch in enumerate(unique_channels):
            checkbox = QCheckBox(str(ch))
            checkbox.setChecked(True)  # Select all by default
            checkbox.stateChanged.connect(self.trigger_plot_update)

            row = idx // max_columns
            col = idx % max_columns
            self.channel_checkboxes_layout.addWidget(checkbox, row, col)

            self.channel_checkboxes[ch] = checkbox

    def select_all_channels(self):
        """Select all channel checkboxes."""
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(True)

    def deselect_all_channels(self):
        """Deselect all channel checkboxes."""
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(False)

    def trigger_plot_update(self):
        """Trigger a debounced plot update to avoid lag."""
        # Restart timer (200ms delay)
        self.plot_update_timer.stop()
        self.plot_update_timer.start(200)

    # Run control methods

    def start_capture(self):
        """Start data capture."""
        if not self.config['channels']:
            QMessageBox.warning(
                self,
                "Configuration Error",
                "Please configure channels before starting capture."
            )
            return

        # Lock configuration controls
        self.set_controls_enabled(False)

        # Clear previous data
        self.raw_data.clear()
        self.sweep_count = 0

        # Disable plot interactions during capture (scrolling mode)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)

        # Send run command
        if self.timed_run_check.isChecked():
            duration_ms = self.timed_run_spin.value()
            self.send_command(f"run {duration_ms}")
            self.log_status(f"Starting timed capture for {duration_ms} ms")

            # Set timer to re-enable controls after timed run
            QTimer.singleShot(duration_ms + 500, self.on_capture_finished)
        else:
            self.send_command("run")
            self.log_status("Starting continuous capture")

        self.is_capturing = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar().showMessage("Capturing - Scrolling Mode")

    def stop_capture(self):
        """Stop data capture."""
        self.send_command("stop")
        self.log_status("Stopping capture")
        self.on_capture_finished()

    def on_capture_finished(self):
        """Handle capture finished (either stopped or timed out)."""
        self.is_capturing = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.set_controls_enabled(True)

        # Enable plot interactions for static mode (zoom/scroll enabled)
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.setMenuEnabled(True)

        self.statusBar().showMessage("Connected - Static Display Mode")

        # Final plot update (shows all data)
        self.update_plot()
        self.plot_info_label.setText(
            f"Sweeps: {self.sweep_count} | Total Samples: {len(self.raw_data) * (len(self.raw_data[0]) if self.raw_data else 0)}"
        )

        self.log_status(f"Capture finished. Total sweeps: {self.sweep_count}")

    def set_controls_enabled(self, enabled: bool):
        """Enable or disable configuration controls."""
        # Serial connection
        self.port_combo.setEnabled(enabled and not self.serial_port)
        self.refresh_ports_btn.setEnabled(enabled and not self.serial_port)

        # ADC configuration
        self.resolution_combo.setEnabled(enabled)
        self.vref_combo.setEnabled(enabled)

        # Acquisition settings
        self.channels_input.setEnabled(enabled)
        self.ground_pin_spin.setEnabled(enabled)
        self.use_ground_check.setEnabled(enabled)
        self.repeat_spin.setEnabled(enabled)
        self.delay_spin.setEnabled(enabled)

        # Run control
        self.timed_run_check.setEnabled(enabled)
        if enabled:
            self.timed_run_spin.setEnabled(self.timed_run_check.isChecked())
        else:
            self.timed_run_spin.setEnabled(False)

        # Visualization controls
        self.window_size_spin.setEnabled(enabled)

    def clear_data(self):
        """Clear all captured data."""
        reply = QMessageBox.question(
            self,
            "Clear Data",
            "Are you sure you want to clear all captured data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.raw_data.clear()
            self.sweep_count = 0
            self.update_plot()
            self.plot_info_label.setText("Sweeps: 0 | Total Samples: 0")
            self.log_status("Data cleared")

    # Helper methods for voltage conversion

    def get_vref_voltage(self) -> float:
        """Get the numeric voltage reference value."""
        vref_str = self.config['reference']

        # Map reference strings to voltage values
        if vref_str == "1.2":
            return 1.2
        elif vref_str == "3.3" or vref_str == "vdd":
            return 3.3
        elif vref_str == "0.8vdd":
            return 3.3 * 0.8  # 2.64V
        elif vref_str == "ext":
            return 1.25  # External reference
        else:
            return 3.3  # Default to VDD

    def convert_to_voltage(self, raw_value: float) -> float:
        """Convert raw ADC value to voltage."""
        resolution_bits = self.config['resolution']
        vref = self.get_vref_voltage()

        max_value = (2 ** resolution_bits) - 1
        return (raw_value / max_value) * vref

    def get_fullscale_range(self) -> tuple:
        """Get the full-scale Y-axis range with padding above max."""
        resolution_bits = self.config['resolution']
        max_raw = 2 ** resolution_bits

        if self.voltage_units_radio.isChecked():
            # Convert to voltage - add 5% padding above max
            vref = self.get_vref_voltage()
            return (0, vref * 1.05)
        else:
            # Raw ADC values - add 5% padding above max
            return (0, max_raw * 1.05)

    # Plotting methods

    def update_plot(self):
        """Update the plot with current data."""
        # Prevent concurrent updates
        if self.is_updating_plot:
            return

        self.is_updating_plot = True

        try:
            self.plot_widget.clear()

            if not self.raw_data or not self.config['channels']:
                return

            # Get selected channels from checkboxes
            selected_channels = [ch for ch, checkbox in self.channel_checkboxes.items() if checkbox.isChecked()]
            if not selected_channels:
                return

            # Determine which data to plot based on capture state
            if self.is_capturing:
                # Scrolling mode: show only last N sweeps
                window_size = self.window_size_spin.value()
                data_to_plot = self.raw_data[-window_size:] if len(self.raw_data) > window_size else self.raw_data
            else:
                # Static mode: show all data
                data_to_plot = self.raw_data

            # Process events to keep UI responsive
            QApplication.processEvents()

            # Parse data structure: each sweep contains [ch0_r1, ch0_r2, ..., ch1_r1, ...]
            channels = self.config['channels']
            repeat_count = self.config['repeat']

            # Get unique channels in order
            unique_channels = []
            for ch in channels:
                if ch not in unique_channels:
                    unique_channels.append(ch)

            # Prepare colors for each channel
            colors = [
                (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                (255, 0, 255), (0, 255, 255), (128, 0, 0), (0, 128, 0),
                (0, 0, 128), (128, 128, 0), (128, 0, 128), (0, 128, 128)
            ]

            # Extract data for each channel
            for ch_idx, channel in enumerate(unique_channels):
                if channel not in selected_channels:
                    continue

                color = colors[ch_idx % len(colors)]

                # Find all positions of this channel in the sequence
                positions = [i for i, c in enumerate(channels) if c == channel]

                # Extract data for this channel across sweeps (window or all)
                channel_data = []
                for sweep in data_to_plot:
                    for pos in positions:
                        start_idx = pos * repeat_count
                        end_idx = start_idx + repeat_count
                        if end_idx <= len(sweep):
                            channel_data.extend(sweep[start_idx:end_idx])

                if not channel_data:
                    continue

                # Convert to voltage if voltage units mode is enabled
                if self.voltage_units_radio.isChecked():
                    channel_data = [self.convert_to_voltage(v) for v in channel_data]

                # Process events periodically to keep UI responsive
                if ch_idx % 2 == 0:  # Every other channel
                    QApplication.processEvents()

                # Show based on visualization mode
                if self.show_all_repeats_radio.isChecked():
                    # Plot each repeat as a separate line
                    if repeat_count > 1:
                        # Reshape data to separate repeats
                        num_samples = len(channel_data) // repeat_count
                        if num_samples > 0:
                            reshaped = np.array(channel_data[:num_samples * repeat_count]).reshape(-1, repeat_count)

                            # Plot each repeat as a separate line
                            for repeat_idx in range(repeat_count):
                                repeat_data = reshaped[:, repeat_idx]

                                # Use slightly different line styles for each repeat
                                if repeat_idx == 0:
                                    pen = pg.mkPen(color=color, width=1.5)
                                    name = f"Ch {channel}.{repeat_idx}"
                                else:
                                    # Lighter/thinner lines for additional repeats
                                    lighter_color = tuple(int(c * 0.7) for c in color)
                                    pen = pg.mkPen(color=lighter_color, width=1, style=Qt.PenStyle.DashLine)
                                    name = f"Ch {channel}.{repeat_idx}"

                                # Plot with appropriate downsampling if needed
                                if len(repeat_data) > 10000:
                                    self.plot_widget.plot(
                                        repeat_data,
                                        pen=pen,
                                        name=name,
                                        downsample=10,
                                        downsampleMethod='subsample'
                                    )
                                else:
                                    self.plot_widget.plot(
                                        repeat_data,
                                        pen=pen,
                                        name=name
                                    )
                    else:
                        # Single repeat: plot as before
                        if len(channel_data) > 10000:
                            self.plot_widget.plot(
                                channel_data,
                                pen=pg.mkPen(color=color, width=1),
                                name=f"Ch {channel}",
                                downsample=10,
                                downsampleMethod='subsample'
                            )
                        else:
                            self.plot_widget.plot(
                                channel_data,
                                pen=pg.mkPen(color=color, width=1),
                                name=f"Ch {channel}"
                            )

                if self.show_average_radio.isChecked():
                    # Compute average across repeats
                    # Reshape data into (num_samples_per_channel, repeat_count)
                    num_samples = len(channel_data) // repeat_count
                    if num_samples > 0:
                        reshaped = np.array(channel_data[:num_samples * repeat_count]).reshape(-1, repeat_count)
                        averaged = np.mean(reshaped, axis=1)

                        # Plot average with thicker line (same x-coords as individual repeats)
                        self.plot_widget.plot(
                            averaged,
                            pen=pg.mkPen(color=color, width=3, style=Qt.PenStyle.DashLine),
                            name=f"Ch {channel} (avg)"
                        )

            # Apply Y-axis scaling mode
            if self.fullscale_radio.isChecked():
                # Full-scale mode: fixed range
                y_min, y_max = self.get_fullscale_range()
                self.plot_widget.setYRange(y_min, y_max, padding=0)
            else:
                # Adaptive mode: auto-range (pyqtgraph default)
                self.plot_widget.enableAutoRange(axis='y')

            # Update Y-axis label based on unit mode
            if self.voltage_units_radio.isChecked():
                self.plot_widget.setLabel('left', 'Voltage', units='V')
            else:
                self.plot_widget.setLabel('left', 'ADC Value', units='counts')

        finally:
            # Always clear the flag, even if there's an error
            self.is_updating_plot = False

    # File management methods

    def browse_directory(self):
        """Browse for output directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.dir_input.text()
        )
        if directory:
            self.dir_input.setText(directory)

    def save_data(self):
        """Save captured data to CSV file with metadata."""
        if not self.raw_data:
            QMessageBox.warning(self, "No Data", "No data to save.")
            return

        # Prepare file paths
        directory = Path(self.dir_input.text())
        filename = self.filename_input.text()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        csv_path = directory / f"{filename}_{timestamp}.csv"
        metadata_path = directory / f"{filename}_{timestamp}_metadata.txt"

        try:
            # Save CSV data
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                for sweep in self.raw_data:
                    writer.writerow(sweep)

            # Save metadata
            with open(metadata_path, 'w') as f:
                f.write("ADC Streamer - Acquisition Metadata\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total Sweeps: {self.sweep_count}\n")
                f.write(f"Total Samples: {len(self.raw_data) * len(self.raw_data[0])}\n\n")

                f.write("Configuration:\n")
                f.write("-" * 50 + "\n")
                f.write(f"Channels: {','.join(map(str, self.config['channels']))}\n")
                f.write(f"Repeat Count: {self.config['repeat']}\n")
                f.write(f"Delay (µs): {self.config['delay_us']}\n")
                f.write(f"Ground Pin: {self.config['ground_pin']}\n")
                f.write(f"Use Ground Sample: {self.config['use_ground']}\n")
                f.write(f"ADC Resolution: {self.config['resolution']} bits\n")
                f.write(f"Voltage Reference: {self.config['reference']}\n")

            self.log_status(f"Data saved to {csv_path}")
            self.log_status(f"Metadata saved to {metadata_path}")

            QMessageBox.information(
                self,
                "Save Successful",
                f"Data saved successfully:\n{csv_path}\n{metadata_path}"
            )

        except Exception as e:
            self.log_status(f"ERROR: Failed to save data - {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save data:\n{e}")

    def save_plot_image(self):
        """Save the current plot as an image."""
        if not self.raw_data:
            QMessageBox.warning(self, "No Data", "No plot to save.")
            return

        directory = Path(self.dir_input.text())
        filename = self.filename_input.text()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        image_path = directory / f"{filename}_{timestamp}.png"

        try:
            # Export plot as image
            exporter = ImageExporter(self.plot_widget.plotItem)
            exporter.parameters()['width'] = 1920  # High resolution
            exporter.export(str(image_path))

            self.log_status(f"Plot image saved to {image_path}")
            QMessageBox.information(
                self,
                "Save Successful",
                f"Plot image saved successfully:\n{image_path}"
            )

        except Exception as e:
            self.log_status(f"ERROR: Failed to save plot image - {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save plot image:\n{e}")

    def closeEvent(self, event):
        """Handle window close event."""
        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        event.accept()


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern look across platforms

    window = ADCStreamerGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
