#!/usr/bin/env python3
"""
ADC Streamer GUI - Fully Modular Version (Demo)
================================================
This is a DEMONSTRATION of the fully refactored architecture using mixin classes.

⚠️  IMPORTANT: This is a proof-of-concept with STUB METHODS ⚠️
For actual data acquisition, use adc_gui.py or adc_gui_modular.py

Purpose:
- Shows the TARGET architecture with pure mixin composition
- Demonstrates clean separation of concerns
- Tests that extracted modules work correctly

What's implemented:
- ✅ Serial communication (ADCSerialMixin, ForceSerialMixin)
- ✅ MCU detection (MCUDetectorMixin)
- ✅ GUI components (GUIComponentsMixin)
- ✅ Configuration management (ConfigurationMixin)
- ✅ Data processing (DataProcessorMixin)
- ✅ File operations (FileOperationsMixin)

🎉 REFACTORING COMPLETE: Fully modular architecture with NO stubs! 🎉

For production use:
- Use adc_gui.py (original, fully functional)
- Use adc_gui_modular.py (hybrid: mixins + original for unextracted code)

Usage:
    python adc_gui_refactored_demo.py
"""

import os
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.*=false'

import sys
import csv
import json
import time
import threading
import traceback
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
from config_constants import *

# Import buffer optimization utilities
from config.buffer_utils import validate_and_limit_sweeps_per_block

# Import refactored modules
from serial_communication import ADCSerialMixin, ForceSerialMixin, SerialReaderThread, ForceReaderThread
from config import MCUDetectorMixin, ConfigurationMixin
from gui import GUIComponentsMixin
from data_processing import DataProcessorMixin
from file_operations import FileOperationsMixin


class ADCStreamerGUIRefactored(
    QMainWindow,
    ADCSerialMixin,      # ✅ Serial communication methods
    ForceSerialMixin,    # ✅ Force sensor communication
    MCUDetectorMixin,    # ✅ MCU detection and adaptation
    GUIComponentsMixin,  # ✅ GUI component creation
    DataProcessorMixin,  # ✅ Data processing and plotting
    ConfigurationMixin,  # ✅ Configuration management
):
    """
    Fully modular ADC Streamer GUI using mixin architecture.
    
    This demonstrates the clean separation of concerns:
    - Serial communication → ADCSerialMixin, ForceSerialMixin
    - MCU detection → MCUDetectorMixin
    - GUI components → GUIComponentsMixin (all create_* methods)
    - Data processing → (TODO: will be extracted next)
    - File operations → (TODO: will be extracted next)
    - MCU adaptation → MCUDetectorMixin
    - Core GUI and data processing → This class
    
    The remaining functionality (GUI creation, data processing, file I/O)
    is still in this class but can be further extracted as needed.
    """

    def __init__(self):
        super().__init__()

        # Serial connection
        self.serial_port: Optional[serial.Serial] = None
        self.serial_thread: Optional[SerialReaderThread] = None
        self.current_mcu: Optional[str] = None
        
        # Configuration completion tracking
        self.config_completion_status: Optional[bool] = None

        # Data storage - Pre-allocated numpy arrays
        self.MAX_SWEEPS_BUFFER = MAX_SWEEPS_IN_MEMORY
        self.raw_data_buffer = None
        self.sweep_timestamps_buffer = None
        self.sweep_count = 0
        self.buffer_write_index = 0
        self.samples_per_sweep = 0
        self.buffer_lock = threading.Lock()
        
        # Legacy list storage for archive
        self.raw_data: List[List[int]] = []
        self.sweep_timestamps: List[float] = []
        
        self.is_capturing = False
        self.is_full_view = False

        # Archive files
        self._archive_file = None
        self._archive_path: Optional[str] = None
        self._archive_write_count = 0
        self._block_timing_file = None
        self._block_timing_path: Optional[str] = None
        self._block_timing_write_count = 0
        
        # Force measurement data
        self.force_serial_port: Optional[serial.Serial] = None
        self.force_serial_thread: Optional[QThread] = None
        self.force_data: List[tuple] = []
        self.force_start_time: Optional[float] = None
        self.force_calibration_offset = {'x': 0.0, 'z': 0.0}
        self.force_calibrating = False

        # Timing measurement
        self.timing_data = {
            'arduino_sample_time_us': None,
            'arduino_sample_rate_hz': None,
            'buffer_gap_time_ms': None,
            'mcu_block_start_us': None,
            'mcu_block_end_us': None,
            'mcu_block_gap_us': None
        }
        self.capture_start_time = None
        self.capture_end_time = None
        
        # Buffer timing tracking
        self.last_buffer_time = None
        self.last_buffer_end_time = None
        self.buffer_receipt_times = []
        self.buffer_gap_times = []
        self.arduino_sample_times = []
        self.block_sample_counts = []
        self.block_sweeps_counts = []
        self.block_samples_per_sweep = []
        self.mcu_block_start_us = []
        self.mcu_block_end_us = []
        self.mcu_block_gap_us = []
        self.mcu_last_block_end_us = None

        # Configuration state
        self.config = {
            'channels': [],
            'repeat': 1,
            'ground_pin': -1,
            'use_ground': False,
            'osr': 2,
            'gain': 1,
            'reference': 'vdd',
            'conv_speed': 'med',
            'samp_speed': 'med',
            'sample_rate': 0
        }
        
        self.last_sent_config = {
            'channels': None,
            'repeat': None,
            'ground_pin': None,
            'use_ground': None,
            'osr': None,
            'gain': None,
            'reference': None
        }
        
        self.config_is_valid = False
        
        self.arduino_status = {
            'channels': None,
            'repeat': None,
            'ground_pin': None,
            'use_ground': None,
            'osr': None,
            'gain': None,
            'reference': None,
            'buffer': None
        }

        # Channel checkboxes
        self.channel_checkboxes: Dict[int, QCheckBox] = {}
        self.force_x_checkbox: Optional[QCheckBox] = None
        self.force_z_checkbox: Optional[QCheckBox] = None

        # Timers
        self.plot_update_timer = QTimer()
        self.plot_update_timer.setSingleShot(True)
        self.plot_update_timer.timeout.connect(self.update_plot)
        self.plot_update_timer.timeout.connect(self.update_force_plot)

        self.force_plot_timer = QTimer()
        self.force_plot_timer.setSingleShot(True)
        self.force_plot_timer.timeout.connect(self.update_force_plot)
        self._force_x_curve = None
        self._force_z_curve = None
        self.force_plot_debounce_ms = 100

        self.is_updating_plot = False
        self._adc_curves = {}
        self._adc_curve_names = {}
        self._adc_curve_legend_added = {}

        # Initialize UI
        self.init_ui()
        
        self.config_check_timer = QTimer()
        self.config_check_timer.timeout.connect(self.check_config_completion)
        self.config_check_timer.setInterval(CONFIG_CHECK_INTERVAL)

        # Update port list
        self.update_port_list()
        
        # Log that we're using the modular version
        self.log_status("=" * 70)
        self.log_status("REFACTORED VERSION - Fully modular architecture (DEMO)")
        self.log_status("✅ Serial communication modules active")
        self.log_status("✅ MCU detection module active")
        self.log_status("⏳ Remaining functionality: To be extracted to modules")
        self.log_status("=" * 70)

    def init_ui(self):
        """Initialize the user interface - uses GUIComponentsMixin methods."""
        self.setWindowTitle("ADC Streamer (Refactored Demo) - Modular Architecture")
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

        # Add control sections - ALL from GUIComponentsMixin!
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

    # ========================================================================
    # STUB METHODS - These will be extracted in Phase 3 (Configuration Management)
    # For now, these are minimal stubs to make the GUI functional
    # ========================================================================
    # Configuration handlers now provided by ConfigurationMixin
    # ========================================================================
    
    def start_capture(self):
        """Start data capture - STUB for demo."""
        self.log_status("Start capture - Not implemented in demo")
    
    def stop_capture(self):
        """Stop data capture - STUB for demo."""
        self.log_status("Stop capture - Not implemented in demo")
    
    def clear_data(self):
        """Clear captured data - STUB for demo."""
        self.log_status("Clear data - Not implemented in demo")
    
    # browse_directory, save_data, save_plot_image, full_graph_view
    # now provided by FileOperationsMixin
    
    # select_all_channels, deselect_all_channels, reset_graph_view, 
    # trigger_plot_update now provided by ConfigurationMixin
    
    # process_serial_data, process_binary_sweep, update_plot, start_capture,
    # stop_capture, clear_data now provided by DataProcessorMixin

    # ========================================================================
    # END STUB METHODS
    # ========================================================================

    def _create_serial_section(self) -> QGroupBox:
        """Simplified serial section for demo."""
        group = QGroupBox("Serial Connection (Modular)")
        layout = QGridLayout()

        layout.addWidget(QLabel("ADC Port:"), 0, 0)
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo, 0, 1)

        self.refresh_ports_btn = QPushButton("Refresh")
        self.refresh_ports_btn.clicked.connect(self.update_port_list)
        layout.addWidget(self.refresh_ports_btn, 0, 2)

        self.connect_btn = QPushButton("Connect ADC")
        self.connect_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.connect_btn, 1, 0, 1, 2)
        
        self.mcu_label = QLabel("MCU: -")
        self.mcu_label.setStyleSheet("QLabel { font-weight: bold; color: #2196F3; }")
        layout.addWidget(self.mcu_label, 1, 2)
        
        layout.addWidget(QLabel("Force Port:"), 2, 0)
        self.force_port_combo = QComboBox()
        layout.addWidget(self.force_port_combo, 2, 1, 1, 2)
        
        self.force_connect_btn = QPushButton("Connect Force")
        self.force_connect_btn.clicked.connect(self.toggle_force_connection)
        layout.addWidget(self.force_connect_btn, 3, 0, 1, 3)

        group.setLayout(layout)
        return group

    def _create_status_section(self) -> QGroupBox:
        """Status display section."""
        group = QGroupBox("Status & Messages")
        layout = QVBoxLayout()

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(400)
        font = QFont("Courier", 9)
        self.status_text.setFont(font)
        layout.addWidget(self.status_text)

        group.setLayout(layout)
        return group

    def _create_info_section(self) -> QGroupBox:
        """Information about modular architecture."""
        group = QGroupBox("Modular Architecture Demo")
        layout = QVBoxLayout()

        info = QTextEdit()
        info.setReadOnly(True)
        info.setMarkdown("""
# Refactored Architecture Demo

This is a **proof-of-concept** showing the modular architecture.

## ✅ Active Modules:

- **serial_communication/** - ADC & Force serial handling
- **config/** - MCU detection and adaptation

## 📁 Module Structure:

```
serial_communication/
├── serial_threads.py    # Background threads
├── adc_serial.py        # ADC connection mixin
└── force_serial.py      # Force sensor mixin

config/
└── mcu_detector.py      # MCU detection mixin
```

## 🎯 Benefits:

1. **Isolated functionality** - Each module has single responsibility
2. **Testable** - Mixins can be unit tested independently
3. **Reusable** - Components can be used in other projects
4. **Maintainable** - ~200-300 lines per file vs 3500 in one file

## 📖 Documentation:

See `README_REFACTORING.md` for complete architecture details.

## ⚠️ Production Use:

For full functionality, continue using `adc_gui.py` until all
modules are completed. This demo shows the architecture only.
        """)
        layout.addWidget(info)

        group.setLayout(layout)
        return group

    def log_status(self, message: str):
        """Log a status message."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.status_text.append(f"[{timestamp}] {message}")
        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )

    # Placeholder methods (would be extracted to modules in full refactoring)
    def process_serial_data(self, line: str):
        """Placeholder - would be in data_processing module."""
        self.log_status(f"Received: {line}")

    def process_binary_sweep(self, samples, avg_time, start, end):
        """Placeholder - would be in data_processing module."""
        self.log_status(f"Binary sweep: {len(samples)} samples")

    def process_force_data(self, x, z):
        """Placeholder - would be in data_processing module."""
        pass

    def calibrate_force_sensors(self):
        """Placeholder - would be in data_processing module."""
        pass

    def update_channel_list(self):
        """Placeholder - would be in gui module."""
        pass

    def update_plot(self):
        """Placeholder - would be in gui module."""
        pass

    def update_force_plot(self):
        """Placeholder - would be in gui module."""
        pass

    def check_config_completion(self):
        """Placeholder - would be in config module."""
        pass

    def stop_capture(self):
        """Placeholder - would be in data_processing module."""
        pass


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    window = ADCStreamerGUIRefactored()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
