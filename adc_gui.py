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

import os
# Suppress Qt geometry warnings - must be set before importing Qt
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.*=false'

import sys
import csv
import json
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

# Import configuration constants
from config_constants import (
    BAUD_RATE, SERIAL_TIMEOUT, COMMAND_TERMINATOR,
    CONFIG_RETRY_ATTEMPTS, CONFIG_COMMAND_TIMEOUT, CONFIG_RETRY_DELAY, INTER_COMMAND_DELAY,
    ARDUINO_RESET_DELAY, PLOT_UPDATE_DEBOUNCE, CONFIG_CHECK_INTERVAL, PLOT_UPDATE_FREQUENCY,
    WINDOW_WIDTH, WINDOW_HEIGHT, DEFAULT_WINDOW_SIZE, MAX_PLOT_COLUMNS,
    TARGET_LATENCY_SEC, PLOT_EXPORT_WIDTH, PLOT_COLORS, MAX_SAMPLES_BUFFER, USB_PACKET_SIZE
)

# Import buffer optimization utilities
from buffer_utils import calculate_optimal_sweeps_per_block, validate_and_limit_sweeps_per_block


class SerialReaderThread(QThread):
    """Background thread for reading serial data without blocking the GUI."""
    data_received = pyqtSignal(str)
    binary_sweep_received = pyqtSignal(list, int)  # samples, avg_sample_time_us
    error_occurred = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True
        self.is_capturing = False

    def run(self):
        """Continuously read from serial port and emit signals."""
        ascii_buffer = ""
        binary_buffer = bytearray()
        
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self.serial_port.in_waiting > 0:
                        data = self.serial_port.read(self.serial_port.in_waiting)
                        
                        if self.is_capturing:
                            # During capture, look for binary sweep packets and ASCII messages
                            binary_buffer.extend(data)
                            binary_buffer = self.process_binary_data(binary_buffer)
                        else:
                            # Not capturing - process as ASCII only
                            try:
                                text = data.decode('utf-8', errors='ignore')
                                ascii_buffer += text

                                # Process complete lines
                                while '\n' in ascii_buffer:
                                    line, ascii_buffer = ascii_buffer.split('\n', 1)
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

    def process_binary_data(self, buffer):
        """Process buffer for binary block packets and ASCII messages.
        
        Binary blocks contain multiple sweeps:
        - Header: [0xAA][0x55][countL][countH] (4 bytes)
        - Payload: count samples as uint16_t little-endian
        - Each block may contain multiple sweeps
        """
        while len(buffer) >= 4:
            # Look for ASCII messages (lines starting with #)
            if buffer[0] == ord('#'):
                # Find newline
                try:
                    newline_idx = buffer.index(ord('\n'))
                    line = buffer[:newline_idx].decode('utf-8', errors='ignore').strip()
                    if line:
                        self.data_received.emit(line)
                    buffer = buffer[newline_idx + 1:]
                    continue
                except (ValueError, UnicodeDecodeError):
                    # No newline found yet or decode error - wait for more data
                    if len(buffer) > 1000:  # Prevent buffer overflow
                        buffer = buffer[1:]  # Drop one byte and retry
                    else:
                        break
            
            # Look for binary block packet (0xAA 0x55 header)
            if buffer[0] == 0xAA and buffer[1] == 0x55:
                # Read total sample count in block (little-endian uint16)
                if len(buffer) < 4:
                    break  # Need more data for header
                
                sample_count = buffer[2] | (buffer[3] << 8)
                # New format: header(4) + samples(count*2) + avg_time(2)
                packet_size = 4 + (sample_count * 2) + 2
                
                if len(buffer) < packet_size:
                    break  # Need more data for complete block
                
                # Extract all samples in block (little-endian uint16)
                samples = []
                for i in range(sample_count):
                    idx = 4 + (i * 2)
                    sample = buffer[idx] | (buffer[idx + 1] << 8)
                    samples.append(sample)
                
                # Extract average sampling time (µs) from last 2 bytes (little-endian uint16)
                avg_time_idx = 4 + (sample_count * 2)
                avg_sample_time_us = buffer[avg_time_idx] | (buffer[avg_time_idx + 1] << 8)
                
                # Emit block with average sampling time
                self.binary_sweep_received.emit(samples, avg_sample_time_us)
                
                # Remove processed packet from buffer
                buffer = buffer[packet_size:]
            else:
                # Unknown byte - skip it to resync
                buffer = buffer[1:]
        
        return buffer

    def set_capturing(self, capturing):
        """Set whether we're currently capturing data."""
        self.is_capturing = capturing

    def stop(self):
        """Stop the thread."""
        self.running = False


class ForceReaderThread(QThread):
    """Background thread for reading force sensor CSV data."""
    force_data_received = pyqtSignal(float, float)  # x_force, z_force
    error_occurred = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True

    def run(self):
        """Continuously read CSV data from force sensor serial port."""
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self.serial_port.in_waiting > 0:
                        line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                        
                        if line:
                            # Parse CSV format: x,z
                            try:
                                parts = line.split(',')
                                if len(parts) >= 2:
                                    x_force = float(parts[0].strip())
                                    z_force = float(parts[1].strip())
                                    self.force_data_received.emit(x_force, z_force)
                            except ValueError:
                                pass  # Skip invalid lines
                else:
                    break

                self.msleep(10)  # Small delay to prevent CPU spinning

            except Exception as e:
                self.error_occurred.emit(f"Force sensor read error: {e}")
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
        
        # Configuration completion tracking
        self.config_completion_status: Optional[bool] = None  # None=pending, True=success, False=failed

        # Data storage
        self.raw_data: List[List[int]] = []  # List of sweeps (each sweep is a list of values)
        self.sweep_count = 0
        self.is_capturing = False
        
        # Force measurement data storage
        self.force_serial_port: Optional[serial.Serial] = None
        self.force_serial_thread: Optional[QThread] = None
        self.force_data: List[tuple] = []  # List of (timestamp, x_force, z_force) tuples
        self.force_start_time: Optional[float] = None
        self.force_calibration_offset = {'x': 0.0, 'z': 0.0}  # Calibration offsets
        self.force_calibrating = False  # Flag for calibration in progress

        # Timing measurement (Arduino-based only)
        self.timing_data = {
            'arduino_sample_time_us': None,  # Average sample time from Arduino
            'arduino_sample_rate_hz': None,  # Sampling rate calculated from Arduino timing
            'buffer_gap_time_ms': None  # Gap time between buffers (transmission + processing)
        }
        self.capture_start_time = None
        self.capture_end_time = None
        
        # Buffer timing tracking
        self.last_buffer_time = None  # Time when last buffer was received
        self.last_buffer_end_time = None  # Time when last buffer finished receiving
        self.buffer_receipt_times = []  # Timestamps of buffer arrivals
        self.buffer_gap_times = []  # Gap times between buffers (ms)
        self.arduino_sample_times = []  # Arduino-measured sample times (µs)

        # Configuration state
        self.config = {
            'channels': [],
            'repeat': 1,
            'ground_pin': -1,
            'use_ground': False,
            'resolution': 12,
            'reference': 'vdd'
        }
        
        # Track last successfully sent configuration to Arduino
        self.last_sent_config = {
            'channels': None,
            'repeat': None,
            'ground_pin': None,
            'use_ground': None,
            'resolution': None,
            'reference': None
        }
        
        # Track if configuration is up to date
        self.config_is_valid = False
        
        # Store last received Arduino status
        self.arduino_status = {
            'channels': None,
            'repeat': None,
            'ground_pin': None,
            'use_ground': None,
            'resolution': None,
            'reference': None,
            'buffer': None
        }

        # Channel checkboxes for visualization
        self.channel_checkboxes: Dict[int, QCheckBox] = {}
        self.force_x_checkbox: Optional[QCheckBox] = None
        self.force_z_checkbox: Optional[QCheckBox] = None

        # Debounce timer for plot updates
        self.plot_update_timer = QTimer()
        self.plot_update_timer.setSingleShot(True)
        self.plot_update_timer.timeout.connect(self.update_plot)
        self.plot_update_timer.timeout.connect(self.update_force_plot)

        # Flag to prevent concurrent plot updates
        self.is_updating_plot = False

        # Initialize UI
        self.init_ui()
        
        # Timer to check configuration completion
        self.config_check_timer = QTimer()
        self.config_check_timer.timeout.connect(self.check_config_completion)
        self.config_check_timer.setInterval(CONFIG_CHECK_INTERVAL)  # Check interval from constants

        # Update port list on startup
        self.update_port_list()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("ADC Streamer - Arduino Control & Visualization")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

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
        right_layout.addWidget(self.create_timing_section())
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
        layout.addWidget(self.connect_btn, 1, 0, 1, 3)
        
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

        # Buffer size (sweeps per block)
        layout.addWidget(QLabel("Sweeps per block (buffer):"), 3, 0)
        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(1, 10000)
        self.buffer_spin.setValue(10)  # Default, will be updated by suggestion
        self.buffer_spin.setToolTip("Number of sweeps sent per block from Arduino")
        self.buffer_spin.valueChanged.connect(self.on_buffer_size_changed)
        layout.addWidget(self.buffer_spin, 3, 1)
        
        # Label to show suggested buffer size
        self.buffer_suggestion_label = QLabel("(suggested: --)")
        self.buffer_suggestion_label.setStyleSheet("QLabel { color: gray; font-size: 9pt; }")
        layout.addWidget(self.buffer_suggestion_label, 3, 2)

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

        # Notes
        layout.addWidget(QLabel("Notes:"), 2, 0, Qt.AlignmentFlag.AlignTop)
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Add notes about this capture (optional)")
        self.notes_input.setMaximumHeight(60)
        layout.addWidget(self.notes_input, 2, 1, 1, 2)

        # Sample range selection
        self.use_range_check = QCheckBox("Save Range:")
        self.use_range_check.setToolTip("Enable to save only a specific range of sweeps")
        self.use_range_check.stateChanged.connect(self.on_use_range_changed)
        layout.addWidget(self.use_range_check, 3, 0)

        # Min sweep
        self.min_sweep_spin = QSpinBox()
        self.min_sweep_spin.setRange(0, 999999)
        self.min_sweep_spin.setValue(0)
        self.min_sweep_spin.setPrefix("Min: ")
        self.min_sweep_spin.setEnabled(False)
        self.min_sweep_spin.setToolTip("Starting sweep index (inclusive)")
        layout.addWidget(self.min_sweep_spin, 3, 1)

        # Max sweep
        self.max_sweep_spin = QSpinBox()
        self.max_sweep_spin.setRange(0, 999999)
        self.max_sweep_spin.setValue(1000)
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

        # Per-channel sampling rate
        layout.addWidget(QLabel("Per Channel:"))
        self.per_channel_rate_label = QLabel("- Hz")
        self.per_channel_rate_label.setStyleSheet("QLabel { font-weight: bold; color: #2196F3; }")
        layout.addWidget(self.per_channel_rate_label)

        layout.addWidget(QLabel("  |  "))

        # Total sampling rate
        layout.addWidget(QLabel("Total Rate:"))
        self.total_rate_label = QLabel("- Hz")
        self.total_rate_label.setStyleSheet("QLabel { font-weight: bold; color: #FF9800; }")
        layout.addWidget(self.total_rate_label)

        layout.addWidget(QLabel("  |  "))

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

        # Consolidated Display Settings
        display_settings_group = QGroupBox("Display Settings")
        display_settings_layout = QGridLayout()

        # Row 0: Y-Axis Range and Units
        display_settings_layout.addWidget(QLabel("Y Range:"), 0, 0)
        self.yaxis_range_combo = QComboBox()
        self.yaxis_range_combo.addItems(["Adaptive", "Full-Scale"])
        self.yaxis_range_combo.setToolTip("Adaptive: Auto-scale to visible data | Full-Scale: 0 to 2^ResolutionBits")
        self.yaxis_range_combo.currentIndexChanged.connect(self.on_yaxis_range_changed)
        display_settings_layout.addWidget(self.yaxis_range_combo, 0, 1)

        display_settings_layout.addWidget(QLabel("Y Units:"), 0, 2)
        self.yaxis_units_combo = QComboBox()
        self.yaxis_units_combo.addItems(["Values", "Voltage"])
        self.yaxis_units_combo.setToolTip("Values: Raw ADC samples | Voltage: Convert using Vref and resolution")
        self.yaxis_units_combo.currentIndexChanged.connect(self.on_yaxis_units_changed)
        display_settings_layout.addWidget(self.yaxis_units_combo, 0, 3)

        # Row 1: Window controls
        display_settings_layout.addWidget(QLabel("Window Size:"), 1, 0)
        self.window_size_spin = QSpinBox()
        self.window_size_spin.setRange(10, 10000)
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
        self.full_view_btn.setToolTip("Show all data from 0 to last sample")
        self.full_view_btn.setMaximumWidth(100)
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

    # Serial connection methods

    def update_port_list(self):
        """Update the list of available serial ports."""
        self.port_combo.clear()
        self.force_port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            port_text = f"{port.device} - {port.description}"
            self.port_combo.addItem(port_text)
            self.force_port_combo.addItem(port_text)

        if self.port_combo.count() == 0:
            self.port_combo.addItem("No ports found")
            self.force_port_combo.addItem("No ports found")

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
                baudrate=BAUD_RATE,
                timeout=SERIAL_TIMEOUT,
                rtscts=True  # Enable hardware flow control
            )
            
            # Wait for Arduino to reset (DTR/RTS can cause reset on some boards)
            time.sleep(ARDUINO_RESET_DELAY)
            
            # Clear any startup messages or garbage data
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            time.sleep(0.1)

            # Start serial reader thread
            self.serial_thread = SerialReaderThread(self.serial_port)
            self.serial_thread.data_received.connect(self.process_serial_data)
            self.serial_thread.binary_sweep_received.connect(self.process_binary_sweep)
            self.serial_thread.error_occurred.connect(self.log_status)
            self.serial_thread.start()

            self.log_status(f"Connected to {port_name}")
            self.connect_btn.setText("Disconnect")
            self.configure_btn.setEnabled(True)
            self.configure_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; }")
            self.start_btn.setEnabled(False)  # Must configure first
            self.statusBar().showMessage("Connected - Please configure")

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
        
        # Reset last sent config so next connection sends everything
        self.last_sent_config = {
            'channels': None,
            'repeat': None,
            'ground_pin': None,
            'use_ground': None,
            'resolution': None,
            'reference': None
        }
        
        # Reset config validity
        self.config_is_valid = False
        
        self.log_status("Disconnected")
        self.connect_btn.setText("Connect")
        self.configure_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("Disconnected")

        # Re-enable port selection
        self.port_combo.setEnabled(True)
        self.refresh_ports_btn.setEnabled(True)

    def toggle_force_connection(self):
        """Connect or disconnect from the force sensor serial port."""
        if self.force_serial_port is None or not self.force_serial_port.is_open:
            self.connect_force_serial()
        else:
            self.disconnect_force_serial()

    def connect_force_serial(self):
        """Connect to the force sensor serial port."""
        if self.force_port_combo.currentText() == "No ports found":
            self.log_status("ERROR: No force sensor ports available")
            return

        port_text = self.force_port_combo.currentText()
        port_name = port_text.split(" - ")[0]

        try:
            self.force_serial_port = serial.Serial(
                port=port_name,
                baudrate=115200,  # Force sensor baud rate
                timeout=1.0
            )
            
            # Clear any startup messages
            time.sleep(0.5)
            self.force_serial_port.reset_input_buffer()

            # Start force serial reader thread
            self.force_serial_thread = ForceReaderThread(self.force_serial_port)
            self.force_serial_thread.force_data_received.connect(self.process_force_data)
            self.force_serial_thread.error_occurred.connect(self.log_status)
            self.force_serial_thread.start()

            self.log_status(f"Connected to force sensor on {port_name} at 115200 baud")
            self.log_status("Calibrating force sensors (collecting 10 samples)...")
            
            # Start calibration
            self.calibrate_force_sensors()
            
            self.force_connect_btn.setText("Disconnect Force")
            
            # Disable port selection during connection
            self.force_port_combo.setEnabled(False)
            
            # Update channel list to add force checkboxes
            if self.config['channels']:  # Only if ADC is already configured
                self.update_channel_list()

        except Exception as e:
            self.log_status(f"ERROR: Failed to connect to force sensor - {e}")
            QMessageBox.critical(self, "Force Connection Error", f"Failed to connect:\n{e}")

    def disconnect_force_serial(self):
        """Disconnect from the force sensor serial port."""
        if self.force_serial_thread:
            self.force_serial_thread.stop()
            self.force_serial_thread.wait()
            self.force_serial_thread = None

        if self.force_serial_port and self.force_serial_port.is_open:
            self.force_serial_port.close()

        self.force_serial_port = None
        
        self.log_status("Force sensor disconnected")
        self.force_connect_btn.setText("Connect Force")
        
        # Re-enable port selection
        self.force_port_combo.setEnabled(True)
        
        # Update channel list to remove force checkboxes
        if self.config['channels']:  # Only if ADC is configured
            self.update_channel_list()

    def send_command(self, command: str):
        """Send a command to the Arduino (fire-and-forget for runtime commands)."""
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(f"{command}{COMMAND_TERMINATOR}".encode('utf-8'))
                self.serial_port.flush()
            except Exception as e:
                self.log_status(f"ERROR: Failed to send command - {e}")
        else:
            self.log_status("ERROR: Not connected to serial port")

    def send_command_and_wait_ack(self, command: str, expected_value: str = None, timeout: float = CONFIG_COMMAND_TIMEOUT, max_retries: int = CONFIG_RETRY_ATTEMPTS) -> tuple:
        """Send a command and wait for #OK acknowledgment with echoed argument verification.
        
        Returns:
            tuple: (success: bool, received_value: str or None)
        """
        if not self.serial_port or not self.serial_port.is_open:
            self.log_status("ERROR: Not connected to serial port")
            return (False, None)
        
        for attempt in range(max_retries):
            try:
                # Flush buffers before retry
                if attempt > 0:
                    time.sleep(CONFIG_RETRY_DELAY)
                    self.serial_port.reset_input_buffer()
                    self.serial_port.reset_output_buffer()
                
                # Send the command
                self.serial_port.write(f"{command}{COMMAND_TERMINATOR}".encode('utf-8'))
                self.serial_port.flush()
                
                # Wait for #OK or #NOT_OK with echoed value
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    try:
                        line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                        
                        if not line or not line.isprintable():
                            continue
                        
                        # Parse #OK response with optional echoed value
                        if line.startswith('#OK'):
                            received_value = line[3:].strip() if len(line) > 3 else None
                            
                            # If we expect a specific value, verify it matches
                            if expected_value is not None and received_value != expected_value:
                                self.log_status(f"MISMATCH: Sent '{expected_value}', received '{received_value}'")
                                if attempt < max_retries - 1:
                                    break  # Retry
                                else:
                                    return (False, received_value)
                            
                            return (True, received_value)
                        
                        # Parse #NOT_OK response
                        elif line.startswith('#NOT_OK'):
                            received_value = line[7:].strip() if len(line) > 7 else None
                            self.log_status(f"Command rejected: {command} (received: {received_value})")
                            if attempt < max_retries - 1:
                                break  # Retry
                            else:
                                return (False, received_value)
                        
                        # Log error messages
                        elif '# ERROR:' in line:
                            self.log_status(line)
                        
                        # Log other status messages
                        elif line.startswith('#'):
                            self.log_status(line)
                            
                    except Exception:
                        continue
                
                # Timeout - retry
                if attempt < max_retries - 1:
                    self.log_status(f"Timeout waiting for ACK: {command}, retrying...")
                else:
                    self.log_status(f"ERROR: No response after {max_retries} attempts: {command}")
                    return (False, None)
                    
            except Exception as e:
                self.log_status(f"ERROR: Failed to send command - {e}")
                if attempt >= max_retries - 1:
                    return (False, None)
        
        return (False, None)

    def process_serial_data(self, line: str):
        """Process incoming ASCII serial data (status messages, errors, etc.)."""
        if line.startswith('#'):
            # Log all status messages
            self.log_status(line)
            # Parse status lines when not in configuration mode
            if 'STATUS' in line or ':' in line or (line.startswith('#   ') and ',' in line):
                self.parse_status_line(line)
        else:
            # Only log if it's printable ASCII (not binary data that got through)
            if line.strip() and line.isprintable():
                self.log_status(f"Unexpected ASCII: {line}")

    def process_binary_sweep(self, samples: List[int], avg_sample_time_us: int):
        """Process incoming binary block data containing one or more sweeps.
        
        The Arduino now sends blocks of sweeps. Each block contains:
        - Multiple complete sweeps (samples_per_sweep * sweeps_in_block)
        - Possibly a partial block at the end of capture
        - Average sampling time per sample (in microseconds) from Arduino
        
        Args:
            samples: List of ADC sample values
            avg_sample_time_us: Average time per sample in microseconds (from Arduino)
        """
        if self.is_capturing:
            try:
                # Track buffer arrival time (start of reception)
                current_time = time.time()
                
                # Calculate gap time between blocks (time between end of last block and start of this one)
                if self.last_buffer_end_time is not None:
                    gap_time_ms = (current_time - self.last_buffer_end_time) * 1000.0
                    self.buffer_gap_times.append(gap_time_ms)
                
                self.buffer_receipt_times.append(current_time)
                
                # Track first sweep time for rate calculation
                if self.sweep_count == 0:
                    self.capture_start_time = current_time
                    self.force_start_time = self.capture_start_time  # Sync force timing
                    self.last_buffer_time = current_time
                
                # Store the average sampling time from Arduino
                self.arduino_sample_times.append(avg_sample_time_us)
                
                # Calculate samples per sweep from configuration
                channel_count = len(self.config.get('channels', []))
                repeat_count = self.config.get('repeat', 1)
                samples_per_sweep = channel_count * repeat_count
                
                if samples_per_sweep == 0:
                    self.log_status("ERROR: Invalid configuration, samples_per_sweep is 0")
                    return
                
                # Split block into individual sweeps
                total_samples = len(samples)
                sweeps_in_block = total_samples // samples_per_sweep
                remainder = total_samples % samples_per_sweep
                
                # Log warning if there are leftover samples (shouldn't happen normally)
                if remainder != 0:
                    self.log_status(f"WARNING: Block has {remainder} extra samples (expected multiple of {samples_per_sweep})")
                
                # Process each complete sweep in the block
                for sweep_idx in range(sweeps_in_block):
                    start_idx = sweep_idx * samples_per_sweep
                    end_idx = start_idx + samples_per_sweep
                    sweep_samples = samples[start_idx:end_idx]
                    
                    self.raw_data.append(sweep_samples)
                    self.sweep_count += 1

                # Update plot periodically for performance (after processing entire block)
                if self.sweep_count % PLOT_UPDATE_FREQUENCY == 0:
                    self.update_plot()
                    window_size = self.window_size_spin.value()
                    displayed_sweeps = min(len(self.raw_data), window_size)
                    # Calculate total samples correctly
                    total_samples = sum(len(sweep) for sweep in self.raw_data)
                    force_samples = len(self.force_data)
                    self.plot_info_label.setText(
                        f"ADC - Sweeps: {self.sweep_count} (showing last {displayed_sweeps}) | Samples: {total_samples}  |  Force: {force_samples} samples"
                    )
                    self.update_force_plot()
                
                # Track when this buffer finished being processed
                self.last_buffer_end_time = time.time()
                
                # Update timing display after each block
                self.update_timing_display()

            except Exception as e:
                self.log_status(f"ERROR: Failed to process binary block - {e}")

    def calibrate_force_sensors(self):
        """Calibrate force sensors by collecting baseline samples without load."""
        self.force_calibrating = True
        self.calibration_samples = {'x': [], 'z': []}
        # Calibration will be completed in process_force_data after 10 samples

    def process_force_data(self, x_force: float, z_force: float):
        """Process incoming force measurement data."""
        # Handle calibration
        if self.force_calibrating:
            self.calibration_samples['x'].append(x_force)
            self.calibration_samples['z'].append(z_force)
            
            if len(self.calibration_samples['x']) >= 10:
                # Calculate average offsets
                self.force_calibration_offset['x'] = sum(self.calibration_samples['x']) / len(self.calibration_samples['x'])
                self.force_calibration_offset['z'] = sum(self.calibration_samples['z']) / len(self.calibration_samples['z'])
                
                self.force_calibrating = False
                self.log_status(f"Force calibration complete: X offset={self.force_calibration_offset['x']:.1f}, Z offset={self.force_calibration_offset['z']:.1f}")
                self.log_status("Force sensors ready (calibrated to zero)")
            return
        
        # Apply calibration offsets
        x_calibrated = x_force - self.force_calibration_offset['x']
        z_calibrated = z_force - self.force_calibration_offset['z']
        
        if self.is_capturing and self.force_start_time is not None:
            timestamp = time.time() - self.force_start_time
            self.force_data.append((timestamp, x_calibrated, z_calibrated))
            
            # Update info label
            if len(self.force_data) % 10 == 0:  # Update every 10 samples
                total_samples = sum(len(sweep) for sweep in self.raw_data) if self.raw_data else 0
                self.plot_info_label.setText(
                    f"ADC - Sweeps: {self.sweep_count} | Samples: {total_samples}  |  Force: {len(self.force_data)} samples"
                )

    def update_force_plot(self):
        """Update the force measurement plot on the right Y-axis."""
        # Clear force plots from the force viewbox
        for item in self.force_viewbox.addedItems[:]:
            self.force_viewbox.removeItem(item)
        
        # Clear force legend
        self.force_legend.clear()
        
        # Check if we should show force data
        show_x_force = self.force_x_checkbox and self.force_x_checkbox.isChecked()
        show_z_force = self.force_z_checkbox and self.force_z_checkbox.isChecked()
        
        if not self.force_data or not self.raw_data or (not show_x_force and not show_z_force):
            return
        
        try:
            # Calculate total ADC samples per channel to get the X-axis scale
            channels = self.config['channels']
            repeat_count = self.config['repeat']
            
            if not channels:
                return
            
            # During capture, use window size; otherwise use all data
            if self.is_capturing:
                window_size = self.window_size_spin.value()
                data_to_show = self.raw_data[-window_size:] if len(self.raw_data) > window_size else self.raw_data
            else:
                data_to_show = self.raw_data
            
            # Calculate total samples per channel for X-axis scaling
            first_channel = channels[0]
            positions = [i for i, c in enumerate(channels) if c == first_channel]
            
            total_adc_samples = 0
            for sweep in data_to_show:
                for pos in positions:
                    start_idx = pos * repeat_count
                    end_idx = start_idx + repeat_count
                    if end_idx <= len(sweep):
                        total_adc_samples += (end_idx - start_idx)
            
            if total_adc_samples == 0:
                return
            
            # Get the capture duration to map force timestamps
            if self.is_capturing and self.capture_start_time:
                current_duration = time.time() - self.capture_start_time
            elif self.capture_end_time and self.capture_start_time:
                current_duration = self.capture_end_time - self.capture_start_time
            else:
                current_duration = max([d[0] for d in self.force_data]) if self.force_data else 1.0
            
            # During capture, only show force data within the time window
            if self.is_capturing:
                # Calculate time range for current window
                window_duration = current_duration * (len(data_to_show) / len(self.raw_data)) if len(self.raw_data) > 0 else current_duration
                min_time = max(0, current_duration - window_duration)
                force_data_to_show = [(t, x, z) for t, x, z in self.force_data if t >= min_time]
            else:
                force_data_to_show = self.force_data
            
            if not force_data_to_show:
                return
            
            # Get force data
            timestamps = [d[0] for d in force_data_to_show]
            x_forces = [d[1] for d in force_data_to_show]
            z_forces = [d[2] for d in force_data_to_show]
            
            # Map force timestamps to ADC sample indices
            # Normalize timestamps to 0-1 range, then scale to total_adc_samples
            if self.is_capturing:
                # During capture: map relative to window time range
                if timestamps:
                    min_timestamp = min(timestamps)
                    max_timestamp = max(timestamps)
                    time_range = max_timestamp - min_timestamp if max_timestamp > min_timestamp else 1.0
                    force_x_indices = [((t - min_timestamp) / time_range) * total_adc_samples for t in timestamps]
                else:
                    force_x_indices = []
            else:
                # After capture: map to full data range using actual time
                # Calculate total samples from ALL data (not windowed)
                total_all_adc_samples = 0
                for sweep in self.raw_data:
                    for pos in positions:
                        start_idx = pos * repeat_count
                        end_idx = start_idx + repeat_count
                        if end_idx <= len(sweep):
                            total_all_adc_samples += (end_idx - start_idx)
                
                max_force_time = max(timestamps) if timestamps else 1.0
                if max_force_time > 0:
                    force_x_indices = [(t / max_force_time) * total_all_adc_samples for t in timestamps]
                else:
                    force_x_indices = [0] * len(timestamps)
            
            # Plot X force (red) if checkbox is checked
            if show_x_force and force_x_indices:
                x_force_curve = pg.PlotCurveItem(force_x_indices, x_forces, pen=pg.mkPen(color=(255, 0, 0), width=2))
                self.force_viewbox.addItem(x_force_curve)
                self.force_legend.addItem(x_force_curve, 'X Force')
            
            # Plot Z force (blue) if checkbox is checked
            if show_z_force and force_x_indices:
                z_force_curve = pg.PlotCurveItem(force_x_indices, z_forces, pen=pg.mkPen(color=(0, 0, 255), width=2))
                self.force_viewbox.addItem(z_force_curve)
                self.force_legend.addItem(z_force_curve, 'Z Force')
            
            # Update viewbox geometry to match main plot
            self.update_force_viewbox()
            
            # Set X-axis range to match ADC data (0 to total_adc_samples)
            self.force_viewbox.setXRange(0, total_adc_samples, padding=0)
            self.force_viewbox.disableAutoRange(axis=pg.ViewBox.XAxis)
            
            # Enable auto-range for Y-axis only
            self.force_viewbox.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            
        except Exception as e:
            self.log_status(f"ERROR: Failed to update force plot - {e}")

    def parse_status_line(self, line: str):
        """Parse a single line from Arduino status output."""
        try:
            # Parse channels: "#   1,2,3,4,5"
            if line.startswith('#   ') and ',' in line and not ':' in line:
                channels_str = line[4:].strip()
                channels = [int(c.strip()) for c in channels_str.split(',')]
                self.arduino_status['channels'] = channels
                return
            
            # Parse other fields
            if ':' in line:
                parts = line.split(':', 1)
                key = parts[0].strip('# ').strip()
                value = parts[1].strip()
                
                if 'repeatCount' in key:
                    self.arduino_status['repeat'] = int(value)
                elif 'groundPin' in key:
                    self.arduino_status['ground_pin'] = int(value)
                elif 'useGroundBeforeEach' in key:
                    self.arduino_status['use_ground'] = (value.lower() == 'true')
                elif 'adcResolutionBits' in key:
                    self.arduino_status['resolution'] = int(value)
                elif 'adcReference' in key:
                    # Map Arduino reference names back to our format
                    ref_map = {
                        'INTERNAL1V2': '1.2',
                        'VDD': 'vdd',
                        '0.8*VDD': '0.8vdd',
                        'EXTERNAL_1V25': 'ext'
                    }
                    self.arduino_status['reference'] = ref_map.get(value, value.lower())
        except Exception as e:
            # Silently ignore parse errors
            pass
    
    def update_timing_display(self):
        """Update timing display based on Arduino measurements and buffer gap timing."""
        try:
            # Calculate Arduino-based timing metrics
            arduino_avg_sample_time_us = 0
            if hasattr(self, 'arduino_sample_times') and self.arduino_sample_times:
                arduino_avg_sample_time_us = sum(self.arduino_sample_times) / len(self.arduino_sample_times)
            
            # Calculate sampling rate from Arduino's measurement
            arduino_sample_rate_hz = 0
            arduino_per_channel_rate_hz = 0
            if arduino_avg_sample_time_us > 0:
                # Total sampling rate: 1,000,000 µs/s ÷ sample_time_us
                arduino_sample_rate_hz = 1000000.0 / arduino_avg_sample_time_us
                
                # Per-channel rate: divide total rate by number of unique channels
                channels = self.config.get('channels', [])
                if channels:
                    num_unique_channels = len(set(channels))
                    arduino_per_channel_rate_hz = arduino_sample_rate_hz / num_unique_channels
                else:
                    arduino_per_channel_rate_hz = arduino_sample_rate_hz
            
            # Calculate average gap between buffers (transmission + processing time)
            buffer_gap_time_ms = 0
            if hasattr(self, 'buffer_gap_times') and self.buffer_gap_times:
                buffer_gap_time_ms = sum(self.buffer_gap_times) / len(self.buffer_gap_times)
            
            # Store timing data
            self.timing_data['arduino_sample_time_us'] = arduino_avg_sample_time_us
            self.timing_data['arduino_sample_rate_hz'] = arduino_sample_rate_hz
            self.timing_data['buffer_gap_time_ms'] = buffer_gap_time_ms
            
            # Update timing labels with Arduino data
            if arduino_avg_sample_time_us > 0:
                self.per_channel_rate_label.setText(f"{arduino_per_channel_rate_hz:.2f} Hz")
                self.total_rate_label.setText(f"{arduino_sample_rate_hz:.2f} Hz")
                self.between_samples_label.setText(f"{arduino_avg_sample_time_us:.2f} µs")
            else:
                self.per_channel_rate_label.setText("- Hz")
                self.total_rate_label.setText("- Hz")
                self.between_samples_label.setText("- µs")
            
            # Display block gap time
            if buffer_gap_time_ms > 0:
                self.block_gap_label.setText(f"{buffer_gap_time_ms:.2f} ms")
            else:
                self.block_gap_label.setText("- ms")
            
        except Exception as e:
            self.log_status(f"ERROR: Failed to update timing display - {e}")

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
        self.config['resolution'] = int(text)
        self.config_is_valid = False
        self.update_start_button_state()

    def on_vref_changed(self, text: str):
        """Handle voltage reference change."""
        vref_map = {
            "1.2V (Internal)": "1.2",
            "3.3V (VDD)": "vdd",
            "0.8*VDD": "0.8vdd",
            "External 1.25V": "ext"
        }
        vref_cmd = vref_map.get(text, "vdd")
        self.config['reference'] = vref_cmd
        self.config_is_valid = False
        self.update_start_button_state()

    def on_channels_changed(self, text: str):
        """Handle channels sequence change."""
        # Always update config when text changes
        if text.strip():
            try:
                # Parse channels for visualization
                channels = [int(c.strip()) for c in text.split(',')]
                self.config['channels'] = channels
                self.update_channel_list()
                self.config_is_valid = False
                self.update_start_button_state()
                self.update_buffer_suggestion()  # Update buffer suggestion when channels change
            except:
                pass
        
        # Don't send command immediately - will be sent on Start
        # This prevents sending incomplete commands while user is typing

    def on_ground_pin_changed(self, value: int):
        """Handle ground pin change."""
        if value >= 0:
            self.config['ground_pin'] = value
            self.config_is_valid = False
            self.update_start_button_state()

    def on_use_ground_changed(self, state: int):
        """Handle use ground checkbox change."""
        use_ground = state == Qt.CheckState.Checked.value
        self.config['use_ground'] = use_ground
        self.config_is_valid = False
        self.update_start_button_state()

    def on_repeat_changed(self, value: int):
        """Handle repeat count change."""
        self.config['repeat'] = value
        self.config_is_valid = False
        self.update_start_button_state()
        self.update_buffer_suggestion()
    
    def on_buffer_size_changed(self, value: int):
        """Handle buffer size change and validate against constraints."""
        try:
            channels = self.config.get('channels', [])
            repeat_count = self.config.get('repeat', 1)
            
            if channels and repeat_count > 0:
                channel_count = len(channels)
                validated_value = validate_and_limit_sweeps_per_block(
                    value, channel_count, repeat_count
                )
                
                if validated_value != value:
                    # Value exceeds buffer capacity, set to maximum allowed
                    self.buffer_spin.blockSignals(True)
                    self.buffer_spin.setValue(validated_value)
                    self.buffer_spin.blockSignals(False)
                    
                    samples_per_sweep = channel_count * repeat_count
                    max_samples = validated_value * samples_per_sweep
                    self.log_status(
                        f"Buffer size limited to {validated_value} sweeps "
                        f"({max_samples} samples) - Arduino buffer capacity is {MAX_SAMPLES_BUFFER} samples"
                    )
        except Exception as e:
            pass  # Silently ignore validation errors

    def on_yaxis_range_changed(self, text: str):
        """Handle Y-axis range change."""
        self.trigger_plot_update()

    def on_yaxis_units_changed(self, text: str):
        """Handle Y-axis units change."""
        self.trigger_plot_update()

    def verify_configuration(self) -> bool:
        """Verify that Arduino status matches expected configuration."""
        # Check if we have valid status data
        if self.arduino_status['channels'] is None:
            self.log_status("No status data received yet")
            return False
        
        # Compare channels (most critical)
        expected_channels = self.config.get('channels', [])
        actual_channels = self.arduino_status['channels']
        
        if expected_channels != actual_channels:
            self.log_status(f"MISMATCH: Expected channels {expected_channels}, got {actual_channels}")
            return False
        
        # Check other parameters (optional - only if they were parsed)
        if self.arduino_status['repeat'] is not None:
            if self.arduino_status['repeat'] != self.config.get('repeat'):
                self.log_status(f"MISMATCH: Expected repeat {self.config.get('repeat')}, got {self.arduino_status['repeat']}")
                return False
        
        # All critical checks passed
        self.log_status(f"Configuration matches: {actual_channels}")
        return True
    
    def update_start_button_state(self):
        """Update Start button state based on configuration validity."""
        if self.serial_port and self.serial_port.is_open and not self.is_capturing:
            if self.config_is_valid:
                self.start_btn.setEnabled(True)
                self.start_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
                self.start_btn.setText("Start ✓")
            else:
                self.start_btn.setEnabled(False)
                self.start_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
                self.start_btn.setText("Start (Configure First)")
        else:
            self.start_btn.setEnabled(False)
    
    def configure_arduino(self):
        """Configure Arduino with verification and retry."""
        if not self.serial_port or not self.serial_port.is_open:
            return
        
        # Validate input
        channels_text = self.channels_input.text().strip()
        if not channels_text:
            self.log_status("ERROR: Please specify channels first")
            return
        
        try:
            desired_channels = [int(c.strip()) for c in channels_text.split(',')]
        except:
            self.log_status("ERROR: Invalid channel format")
            return
        
        self.log_status("Configuring Arduino...")
        self.configure_btn.setEnabled(False)
        
        # Reset completion status and start checking
        self.config_completion_status = None
        self.config_check_timer.start()
        
        # Run configuration in a separate thread to avoid blocking UI
        def config_worker():
            success_flag = False
            try:
                # Flush buffers before configuration
                self.serial_port.reset_input_buffer()
                self.serial_port.reset_output_buffer()
                time.sleep(0.05)
                
                max_attempts = 3
                for attempt in range(max_attempts):
                    self.log_status(f"Configuration attempt {attempt + 1}/{max_attempts}")
                    success = self.send_config_with_verification()
                    self.log_status(f"send_config_with_verification returned: {success}")
                    
                    if success:
                        # Verify final configuration
                        verified = self.verify_configuration()
                        self.log_status(f"verify_configuration returned: {verified}")
                        if verified:
                            success_flag = True
                            break
                    
                    time.sleep(0.05)  # Brief delay between retries
                    
            except Exception as e:
                print(f"ERROR: Configuration exception - {e}")
                import traceback
                traceback.print_exc()
            finally:
                # Set completion status for main thread to handle
                if success_flag:
                    self.config_completion_status = True
                else:
                    self.config_completion_status = False
        
        # Start configuration in background thread
        import threading
        threading.Thread(target=config_worker, daemon=True).start()
    
    def check_config_completion(self):
        """Check if configuration has completed (called by timer)."""
        if self.config_completion_status is not None:
            self.config_check_timer.stop()
            
            if self.config_completion_status:
                self.on_configuration_success()
            else:
                self.on_configuration_failed()
            
            # Reset status
            self.config_completion_status = None
    
    def on_configuration_success(self):
        """Handle successful configuration."""
        self.config_is_valid = True
        self.log_status("✓ Configuration verified - Ready to start")
        self.update_start_button_state()
        self.configure_btn.setEnabled(True)
        self.configure_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; }")
        self.statusBar().showMessage("Configured - Ready to capture", 3000)
    
    def on_configuration_failed(self):
        """Handle failed configuration."""
        self.log_status("ERROR: Configuration failed after retries")
        self.configure_btn.setEnabled(True)
        self.configure_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; font-weight: bold; }")
        self.statusBar().showMessage("Configuration failed - please retry", 5000)
    
    def suggest_sweeps_per_block(self, channel_count: int, repeat_count: int, baud_rate: int = BAUD_RATE) -> tuple:
        """Compute optimal sweeps per block using advanced optimization.
        
        Args:
            channel_count: Number of ADC channels
            repeat_count: Number of repeats per channel
            baud_rate: Serial baud rate (default from BAUD_RATE constant)
        
        Returns:
            Tuple of (best_sweeps, candidates_list)
            - best_sweeps: The top recommended sweeps_per_block value
            - candidates_list: List of (sweeps, metrics) for top candidates
        """
        if channel_count <= 0 or repeat_count <= 0:
            return (10, [])  # Fallback default
        
        candidates = calculate_optimal_sweeps_per_block(
            channel_count, repeat_count, baud_rate, TARGET_LATENCY_SEC, max_candidates=3
        )
        
        if candidates:
            best_sweeps = candidates[0][0]  # First candidate is best
            return (best_sweeps, candidates)
        else:
            return (10, [])

    def send_config_with_verification(self) -> bool:
        """Send configuration to Arduino with ACK verification and retry.
        
        Returns:
            bool: True if all parameters were set successfully
        """
        if not self.serial_port or not self.serial_port.is_open:
            return False
        
        all_success = True
        
        # Send resolution
        res_text = self.resolution_combo.currentText()
        success, received = self.send_command_and_wait_ack(f"res {res_text}", res_text)
        if success:
            self.arduino_status['resolution'] = int(received)
        else:
            all_success = False
        time.sleep(INTER_COMMAND_DELAY)
        
        # Send voltage reference
        vref_text = self.vref_combo.currentText()
        vref_map = {
            "1.2V (Internal)": "1.2",
            "3.3V (VDD)": "vdd",
            "0.8*VDD": "0.8vdd",
            "External 1.25V": "ext"
        }
        vref_cmd = vref_map.get(vref_text, "vdd")
        success, received = self.send_command_and_wait_ack(f"ref {vref_cmd}", vref_cmd)
        if success:
            self.arduino_status['reference'] = received
        else:
            all_success = False
        time.sleep(0.05)
        
        # Send channels
        channels_text = self.channels_input.text().strip()
        if channels_text:
            success, received = self.send_command_and_wait_ack(f"channels {channels_text}", channels_text)
            if success and received:
                self.arduino_status['channels'] = [int(c.strip()) for c in received.split(',')]
            else:
                all_success = False
        time.sleep(0.05)
        
        # Send repeat count
        repeat = str(self.repeat_spin.value())
        success, received = self.send_command_and_wait_ack(f"repeat {repeat}", repeat)
        if success:
            self.arduino_status['repeat'] = int(received)
        else:
            all_success = False
        time.sleep(0.05)
        
        # Send ground settings
        use_ground = str(self.use_ground_check.isChecked()).lower()
        success, received = self.send_command_and_wait_ack(f"ground {use_ground}", use_ground)
        if success:
            self.arduino_status['use_ground'] = (received == 'true')
        else:
            all_success = False
        
        if self.use_ground_check.isChecked():
            time.sleep(0.05)
            ground_pin = str(self.ground_pin_spin.value())
            success, received = self.send_command_and_wait_ack(f"ground {ground_pin}", ground_pin)
            if success:
                self.arduino_status['ground_pin'] = int(received)
            else:
                all_success = False
        
        # Send buffer size (sweeps per block)
        time.sleep(0.05)
        buffer_size = self.buffer_spin.value()
        # Validate buffer size
        channel_count = len(self.config.get('channels', []))
        repeat_count = self.config.get('repeat', 1)
        
        if buffer_size <= 0:
            # Compute suggested value
            buffer_size, _ = self.suggest_sweeps_per_block(channel_count, repeat_count)
            self.log_status(f"Invalid buffer size, using suggested value: {buffer_size}")
            self.buffer_spin.setValue(buffer_size)
        else:
            # Validate against buffer capacity
            buffer_size = validate_and_limit_sweeps_per_block(buffer_size, channel_count, repeat_count)
            if buffer_size != self.buffer_spin.value():
                self.log_status(f"Buffer size limited to {buffer_size} sweeps (Arduino buffer capacity)")
                self.buffer_spin.setValue(buffer_size)
        
        buffer_str = str(buffer_size)
        success, received = self.send_command_and_wait_ack(f"buffer {buffer_str}", buffer_str)
        if success:
            self.arduino_status['buffer'] = int(received)
        else:
            all_success = False
        
        return all_success
        


    def update_buffer_suggestion(self):
        """Update the suggested buffer size based on current configuration."""
        try:
            # Parse channels
            channels_text = self.channels_input.text().strip()
            if channels_text:
                channel_count = len([c.strip() for c in channels_text.split(',')])
            else:
                channel_count = 0
            
            repeat_count = self.repeat_spin.value()
            
            if channel_count > 0:
                suggested, candidates = self.suggest_sweeps_per_block(channel_count, repeat_count)
                
                # Build suggestion text with details
                if candidates:
                    best = candidates[0][1]  # metrics for best candidate
                    suggestion_text = (
                        f"(suggested: {suggested} sweeps, "
                        f"{best['transmit_time_ms']:.1f}ms, "
                        f"{best['block_bytes']} bytes)"
                    )
                else:
                    suggestion_text = f"(suggested: {suggested})"
                
                self.buffer_suggestion_label.setText(suggestion_text)
                
                # Auto-update buffer spin box to suggested value if it's currently at default/invalid
                current_buffer = self.buffer_spin.value()
                if current_buffer == 10 or current_buffer <= 0:  # Default or invalid
                    self.buffer_spin.setValue(suggested)
            else:
                self.buffer_suggestion_label.setText("(suggested: --)")
        except Exception as e:
            self.buffer_suggestion_label.setText("(suggested: --)")

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

        # Create checkboxes in a compact grid
        for idx, ch in enumerate(unique_channels):
            checkbox = QCheckBox(str(ch))
            checkbox.setChecked(True)  # Select all by default
            checkbox.stateChanged.connect(self.trigger_plot_update)

            row = idx // MAX_PLOT_COLUMNS
            col = idx % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(checkbox, row, col)

            self.channel_checkboxes[ch] = checkbox
        
        # Add force sensor checkboxes if force data is available
        if self.force_serial_port and self.force_serial_port.is_open:
            # X Force checkbox
            self.force_x_checkbox = QCheckBox("X Force")
            self.force_x_checkbox.setChecked(True)
            self.force_x_checkbox.setStyleSheet("QCheckBox { color: red; }")
            self.force_x_checkbox.stateChanged.connect(self.trigger_plot_update)
            row = len(unique_channels) // MAX_PLOT_COLUMNS
            col = len(unique_channels) % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(self.force_x_checkbox, row, col)
            
            # Z Force checkbox
            self.force_z_checkbox = QCheckBox("Z Force")
            self.force_z_checkbox.setChecked(True)
            self.force_z_checkbox.setStyleSheet("QCheckBox { color: blue; }")
            self.force_z_checkbox.stateChanged.connect(self.trigger_plot_update)
            row = (len(unique_channels) + 1) // MAX_PLOT_COLUMNS
            col = (len(unique_channels) + 1) % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(self.force_z_checkbox, row, col)

    def select_all_channels(self):
        """Select all channel checkboxes."""
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(True)
        if self.force_x_checkbox:
            self.force_x_checkbox.setChecked(True)
        if self.force_z_checkbox:
            self.force_z_checkbox.setChecked(True)

    def deselect_all_channels(self):
        """Deselect all channel checkboxes."""
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(False)
        if self.force_x_checkbox:
            self.force_x_checkbox.setChecked(False)
        if self.force_z_checkbox:
            self.force_z_checkbox.setChecked(False)

    def trigger_plot_update(self):
        """Trigger a debounced plot update to avoid lag."""
        # Restart timer
        self.plot_update_timer.stop()
        self.plot_update_timer.start(PLOT_UPDATE_DEBOUNCE)

    def reset_graph_view(self):
        """Reset the plot view to window size (X: 0 to window size, Y: according to settings)."""
        if not self.raw_data:
            return

        # Calculate X-axis range based on window size
        window_size = self.window_size_spin.value()
        
        # Determine which data would be plotted (same logic as update_plot)
        if len(self.raw_data) > window_size:
            data_to_show = self.raw_data[-window_size:]
        else:
            data_to_show = self.raw_data
        
        channels = self.config['channels']
        repeat_count = self.config['repeat']
        
        if channels:
            # Calculate samples per channel (not total samples)
            # Each channel gets plotted separately with indices 0, 1, 2, ...
            # Find positions of first channel to determine sample count
            first_channel = channels[0]
            positions = [i for i, c in enumerate(channels) if c == first_channel]
            
            # Extract data for first channel to count samples
            channel_samples = 0
            for sweep in data_to_show:
                for pos in positions:
                    start_idx = pos * repeat_count
                    end_idx = start_idx + repeat_count
                    if end_idx <= len(sweep):
                        channel_samples += (end_idx - start_idx)
            
            # Set X-axis range to match the plotted data
            self.plot_widget.setXRange(0, channel_samples, padding=0)
            
            # Set Y-axis according to current mode
            self.apply_y_axis_range()
            
            # Also update force plot to match
            self.update_force_plot()
            
            self.log_status(f"Graph view reset to window size ({len(data_to_show)} sweeps, {channel_samples} samples per channel)")

    def full_graph_view(self):
        """Show full data view (X: 0 to last sample, Y: according to settings)."""
        if not self.raw_data:
            return

        # Calculate samples per channel across all sweeps
        total_sweeps = len(self.raw_data)
        channels = self.config['channels']
        repeat_count = self.config['repeat']
        
        if channels:
            # Calculate samples per channel (not total samples)
            # Each channel gets plotted separately with indices 0, 1, 2, ...
            # Find positions of first channel to determine sample count
            first_channel = channels[0]
            positions = [i for i, c in enumerate(channels) if c == first_channel]
            
            # Extract data for first channel to count samples
            channel_samples = 0
            for sweep in self.raw_data:
                for pos in positions:
                    start_idx = pos * repeat_count
                    end_idx = start_idx + repeat_count
                    if end_idx <= len(sweep):
                        channel_samples += (end_idx - start_idx)
            
            # Set X-axis range to show all data
            self.plot_widget.setXRange(0, channel_samples, padding=0)
            
            # Set Y-axis according to current mode
            self.apply_y_axis_range()
            
            self.log_status(f"Graph view set to full data ({total_sweeps} sweeps, {channel_samples} samples per channel)")

    def apply_y_axis_range(self):
        """Apply Y-axis range according to current settings (adaptive or full-scale)."""
        if self.yaxis_range_combo.currentText() == "Full-Scale":
            # Full-scale mode: fixed range with padding
            y_min, y_max = self.get_fullscale_range()
            self.plot_widget.setYRange(y_min, y_max, padding=0)
        else:
            # Adaptive mode: auto-range based on visible data
            self.plot_widget.enableAutoRange(axis='y')

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

        # Configuration should already be done via Configure button
        # No need to send it again here

        # Lock configuration controls
        self.set_controls_enabled(False)

        # Clear previous data
        self.raw_data.clear()
        self.sweep_count = 0
        self.force_data.clear()
        self.force_start_time = None

        # Clear timing data for new measurement
        self.timing_data = {
            'per_channel_rate_hz': None,
            'total_rate_hz': None,
            'between_samples_us': None,
            'arduino_sample_time_us': None,
            'arduino_sample_rate_hz': None,
            'buffer_gap_time_ms': None
        }
        self.capture_start_time = None
        self.capture_end_time = None
        self.last_buffer_time = None
        self.last_buffer_end_time = None
        self.buffer_receipt_times.clear()
        self.buffer_gap_times.clear()
        self.arduino_sample_times.clear()
        self.per_channel_rate_label.setText("- Hz")
        self.total_rate_label.setText("- Hz")
        self.between_samples_label.setText("- µs")
        self.block_gap_label.setText("- ms")

        # Disable plot interactions during capture (scrolling mode)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)

        # Switch to binary capture mode BEFORE sending run command
        self.is_capturing = True
        if self.serial_thread:
            self.serial_thread.set_capturing(True)
        
        # Wait for thread to fully switch modes
        time.sleep(0.05)

        # Send run command - binary data will start flowing
        if self.timed_run_check.isChecked():
            duration_ms = self.timed_run_spin.value()
            self.send_command(f"run {duration_ms}")
            self.log_status(f"Starting timed capture for {duration_ms} ms")

            # Set timer to re-enable controls after timed run
            QTimer.singleShot(duration_ms + 500, self.on_capture_finished)
        else:
            self.send_command("run")
            self.log_status("Starting continuous capture")

        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        self.stop_btn.setEnabled(True)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; }")
        self.statusBar().showMessage("Capturing - Scrolling Mode")

    def stop_capture(self):
        """Stop data capture."""
        self.send_command("stop")
        self.log_status("Stopping capture")
        self.on_capture_finished()

    def on_capture_finished(self):
        """Handle capture finished (either stopped or timed out)."""
        # Record end time
        self.capture_end_time = time.time()
        
        self.is_capturing = False
        
        # Notify serial thread that we're not capturing (disables binary mode)
        if self.serial_thread:
            self.serial_thread.set_capturing(False)
        
        # Log final timing summary
        time.sleep(0.1)  # Wait for Arduino to finish sending binary data
        if hasattr(self, 'arduino_sample_times') and self.arduino_sample_times:
            avg_sample_time = sum(self.arduino_sample_times) / len(self.arduino_sample_times)
            total_rate = 1000000.0 / avg_sample_time if avg_sample_time > 0 else 0
            self.log_status(f"Capture complete - Sample interval: {avg_sample_time:.2f} µs, Total rate: {total_rate:.2f} Hz")
        
        if hasattr(self, 'buffer_gap_times') and self.buffer_gap_times:
            avg_gap = sum(self.buffer_gap_times) / len(self.buffer_gap_times)
            self.log_status(f"Average block gap: {avg_gap:.2f} ms ({len(self.buffer_gap_times)} blocks)")
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        self.update_start_button_state()  # Restore start button to proper state
        self.set_controls_enabled(True)

        # Enable plot interactions for static mode (zoom/scroll enabled)
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.setMenuEnabled(True)

        self.statusBar().showMessage("Connected - Static Display Mode")

        # Final plot update (shows all data)
        self.update_plot()
        # Calculate total samples correctly
        total_samples = sum(len(sweep) for sweep in self.raw_data) if self.raw_data else 0
        force_samples = len(self.force_data)
        self.plot_info_label.setText(
            f"ADC - Sweeps: {self.sweep_count} | Samples: {total_samples}  |  Force: {force_samples} samples"
        )

        self.log_status(f"Capture finished. Total sweeps: {self.sweep_count}, Total samples: {total_samples}, Force samples: {force_samples}")

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
        self.buffer_spin.setEnabled(enabled)

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
            self.force_data.clear()
            self.update_plot()
            self.update_force_plot()
            self.plot_info_label.setText("ADC - Sweeps: 0 | Samples: 0  |  Force: 0 samples")
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

        if self.yaxis_units_combo.currentText() == "Voltage":
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

            # Extract data for each channel
            for ch_idx, channel in enumerate(unique_channels):
                if channel not in selected_channels:
                    continue

                color = PLOT_COLORS[ch_idx % len(PLOT_COLORS)]

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
                if self.yaxis_units_combo.currentText() == "Voltage":
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
            if self.yaxis_range_combo.currentText() == "Full-Scale":
                # Full-scale mode: fixed range
                y_min, y_max = self.get_fullscale_range()
                self.plot_widget.setYRange(y_min, y_max, padding=0)
            else:
                # Adaptive mode: auto-range (pyqtgraph default)
                self.plot_widget.enableAutoRange(axis='y')

            # Update Y-axis label based on unit mode
            if self.yaxis_units_combo.currentText() == "Voltage":
                self.plot_widget.setLabel('left', 'Voltage', units='V')
            else:
                self.plot_widget.setLabel('left', 'ADC Value', units='counts')

        finally:
            # Always clear the flag, even if there's an error
            self.is_updating_plot = False

    # File management methods

    def on_use_range_changed(self, state: int):
        """Handle use range checkbox state change."""
        enabled = state == Qt.CheckState.Checked.value
        self.min_sweep_spin.setEnabled(enabled)
        self.max_sweep_spin.setEnabled(enabled)

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

        # Determine which data to save
        data_to_save = self.raw_data
        sweep_range_text = "All"
        total_sweeps = len(self.raw_data)

        # Check if range is enabled
        if self.use_range_check.isChecked():
            min_sweep = self.min_sweep_spin.value()
            max_sweep = self.max_sweep_spin.value()

            # Validate range
            if min_sweep >= max_sweep:
                QMessageBox.warning(
                    self,
                    "Invalid Range",
                    f"Min sweep ({min_sweep}) must be less than max sweep ({max_sweep})."
                )
                return

            if min_sweep < 0 or min_sweep >= total_sweeps:
                QMessageBox.warning(
                    self,
                    "Invalid Range",
                    f"Min sweep ({min_sweep}) is out of bounds. Valid range: 0 to {total_sweeps - 1}."
                )
                return

            if max_sweep < 0 or max_sweep > total_sweeps:
                QMessageBox.warning(
                    self,
                    "Invalid Range",
                    f"Max sweep ({max_sweep}) is out of bounds. Valid range: 1 to {total_sweeps}."
                )
                return

            # Slice the data (max_sweep is inclusive in user terms, but exclusive in Python slicing)
            data_to_save = self.raw_data[min_sweep:max_sweep]
            sweep_range_text = f"{min_sweep} to {max_sweep - 1}"
            self.log_status(f"Saving sweep range: {sweep_range_text} ({len(data_to_save)} sweeps)")

        # Prepare file paths
        directory = Path(self.dir_input.text())
        filename = self.filename_input.text()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        csv_path = directory / f"{filename}_{timestamp}.csv"
        metadata_path = directory / f"{filename}_{timestamp}_metadata.json"

        try:
            # Determine if we have force data
            has_force_x = any(d[1] != 0 for d in self.force_data) if self.force_data else False
            has_force_z = any(d[2] != 0 for d in self.force_data) if self.force_data else False
            
            # Create a mapping of ADC timestamps to force data
            force_dict = {}
            if self.force_data:
                for timestamp, x_force, z_force in self.force_data:
                    force_dict[timestamp] = (x_force, z_force)
            
            # Save CSV data with force columns
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Write header
                header = [f"CH{ch}" for ch in self.config['channels']] * self.config['repeat']
                header.extend(["Force_X", "Force_Z"])
                writer.writerow(header)
                
                # Write data rows
                sweep_idx = 0
                for sweep in data_to_save:
                    row = list(sweep)
                    
                    # Calculate approximate timestamp for this sweep
                    if self.capture_start_time and self.capture_end_time and len(self.raw_data) > 0:
                        sweep_time = (sweep_idx / len(data_to_save)) * (self.capture_end_time - self.capture_start_time)
                        
                        # Find closest force measurement
                        closest_force = (0.0, 0.0)
                        if force_dict:
                            min_diff = float('inf')
                            for f_time, (x, z) in force_dict.items():
                                diff = abs(f_time - sweep_time)
                                if diff < min_diff:
                                    min_diff = diff
                                    closest_force = (x, z)
                        
                        row.extend(closest_force)
                    else:
                        row.extend([0.0, 0.0])
                    
                    writer.writerow(row)
                    sweep_idx += 1

            # Prepare metadata dictionary
            metadata = {
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "total_captured_sweeps": self.sweep_count,
                "saved_sweeps": len(data_to_save),
                "sweep_range": sweep_range_text,
                "total_samples": len(data_to_save) * (len(data_to_save[0]) if data_to_save else 0),
                "configuration": {
                    "channels": self.config['channels'],
                    "repeat_count": self.config['repeat'],
                    "ground_pin": self.config['ground_pin'],
                    "use_ground_sample": self.config['use_ground'],
                    "adc_resolution_bits": self.config['resolution'],
                    "voltage_reference": self.config['reference']
                },
                "timing": {
                    "per_channel_rate_hz": self.timing_data.get('per_channel_rate_hz'),
                    "total_rate_hz": self.timing_data.get('total_rate_hz'),
                    "between_samples_us": self.timing_data.get('between_samples_us')
                },
                "force_data": {
                    "available": len(self.force_data) > 0,
                    "x_force_available": has_force_x,
                    "z_force_available": has_force_z,
                    "total_force_samples": len(self.force_data),
                    "calibration_offset_x": self.force_calibration_offset['x'],
                    "calibration_offset_z": self.force_calibration_offset['z'],
                    "note": "Force data not available" if not self.force_data else "Force data synchronized with ADC samples (calibrated to zero at connection)"
                }
            }

            # Add user notes if provided
            notes = self.notes_input.toPlainText().strip()
            if notes:
                metadata["notes"] = notes

            # Save metadata as JSON
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            self.log_status(f"Data saved to {csv_path}")
            self.log_status(f"Metadata saved to {metadata_path}")

            QMessageBox.information(
                self,
                "Save Successful",
                f"Data saved successfully:\n{csv_path}\n{metadata_path}\n\nSweeps saved: {len(data_to_save)}"
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
            exporter.parameters()['width'] = PLOT_EXPORT_WIDTH  # High resolution
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
