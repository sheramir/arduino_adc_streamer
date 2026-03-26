#!/usr/bin/env python3
"""
ADC Streamer GUI - Production Modular Version
==============================================
Fully refactored modular architecture using mixin classes.

All functionality extracted into focused modules:
- serial_communication/: ADC & Force serial I/O
- config/: MCU detection & configuration management
- gui/: UI component creation
- data_processing/: Data processing & plotting
- file_operations/: File I/O & export

Usage:
    python adc_gui.py
    # Or with uv:
    uv run adc_gui.py
"""

import os
# Suppress Qt geometry warnings - must be set before importing Qt
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.*=false'

import sys
import threading
from typing import List, Optional, Dict

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QCheckBox
from PyQt6.QtCore import QThread, QTimer, Qt
from PyQt6.QtGui import QGuiApplication
import serial

# Import configuration constants
from config_constants import *

# Import refactored modules
from serial_communication import ADCSerialMixin, ForceSerialMixin
from serial_communication.serial_threads import SerialReaderThread
from config import MCUDetectorMixin, ConfigurationMixin
from gui import GUIComponentsMixin
from data_processing import (
    DataProcessorMixin,
    HeatmapProcessorMixin,
    ShearProcessorMixin,
    SpectrumProcessorMixin,
    SimulatedSensorThread,
)
from file_operations import FileOperationsMixin


class ADCStreamerGUI(
    QMainWindow,
    ADCSerialMixin,         # ✅ Serial communication
    ForceSerialMixin,       # ✅ Force sensor communication
    MCUDetectorMixin,       # ✅ MCU detection
    GUIComponentsMixin,     # ✅ GUI component creation (includes HeatmapPanelMixin)
    ConfigurationMixin,     # ✅ Configuration management
    DataProcessorMixin,     # ✅ Data processing
    HeatmapProcessorMixin,  # ✅ Heatmap CoP calculation
    ShearProcessorMixin,    # ✅ Shear / CoP calculation
    SpectrumProcessorMixin, # ✅ Spectrum processing
    FileOperationsMixin     # ✅ File operations
):
    """
    Production ADC Streamer GUI using fully modular architecture.
    
    Completed extractions:
    - ✅ Serial communication (~600 lines)
    - ✅ MCU detection (~100 lines)
    - ✅ GUI components (~470 lines)
    - ✅ Configuration management (~500 lines)
    - ✅ Data processing (~1200 lines)
    - ✅ File operations (~300 lines)
    
    🎉 REFACTORING COMPLETE: 88% extracted (3,070 lines) into 6 focused modules! 🎉
    """
    
    def __init__(self):
        super().__init__()
        
        # Initialize all state variables through helper methods
        self._init_serial_state()
        self._init_data_buffers()
        self._init_archive_state()
        self._init_force_state()
        self._init_timing_state()
        self._init_config_state()
        self._init_ui_state()
        self.init_sensor_config_state()
        self._init_heatmap_state()
        self._init_shear_state()
        self._init_spectrum_state()
        self._init_timers()

        # Build user interface
        self.init_ui()
        self._refresh_sensor_tab_ui()
        self.load_last_heatmap_settings()
        self.enable_heatmap_settings_autosave()
        self.load_last_shear_settings()
        self.enable_shear_settings_autosave()
        self.load_last_spectrum_settings()

        # Post-initialization
        self.update_port_list()
        self._log_startup_message()

    def _init_serial_state(self):
        """Initialize serial connection state."""
        self.serial_port: Optional[serial.Serial] = None
        self.serial_thread: Optional[SerialReaderThread] = None
        self.current_mcu: Optional[str] = None
        self.config_completion_status: Optional[bool] = None

    def _init_data_buffers(self):
        """Initialize data storage buffers."""
        self.MAX_SWEEPS_BUFFER = MAX_SWEEPS_IN_MEMORY
        self.raw_data_buffer = None
        self.processed_data_buffer = None
        self.sweep_timestamps_buffer = None
        self.sweep_count = 0
        self.buffer_write_index = 0
        self.samples_per_sweep = 0
        self.buffer_lock = threading.Lock()
        self._init_filter_state()
        
        # Legacy list storage for archive
        self.raw_data: List[List[int]] = []
        self.sweep_timestamps: List[float] = []
        
        self.is_capturing = False
        self.is_full_view = False

    def _init_archive_state(self):
        """Initialize archive file state."""
        self._archive_file = None
        self._archive_path: Optional[str] = None
        self._archive_write_count = 0
        self._block_timing_file = None
        self._block_timing_path: Optional[str] = None
        self._block_timing_write_count = 0
        self._cache_dir_path: Optional[str] = None

    def _init_force_state(self):
        """Initialize force sensor state."""
        self.force_serial_port: Optional[serial.Serial] = None
        self.force_serial_thread: Optional[QThread] = None
        self.force_data: List[tuple] = []
        self.force_start_time: Optional[float] = None
        self.force_calibration_offset = {'x': 0.0, 'z': 0.0}
        self.force_calibrating = False

    def _init_timing_state(self):
        """Initialize timing measurement state."""
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

    def _init_config_state(self):
        """Initialize configuration state."""
        self.device_mode = 'adc'

        self.config = {
            'channels': [],
            'channel_selection_source': 'none',
            'selected_array_sensors': [],
            'repeat': 1,
            'ground_pin': -1,
            'use_ground': False,
            'osr': 2,
            'gain': 1,
            'reference': 'vdd',
            'conv_speed': 'med',
            'samp_speed': 'med',
            'sample_rate': 0,
            'rb_ohms': ANALYZER555_DEFAULT_RB_OHMS,
            'rk_ohms': ANALYZER555_DEFAULT_RK_OHMS,
            'cf_farads': ANALYZER555_DEFAULT_CF_FARADS,
            'rxmax_ohms': ANALYZER555_DEFAULT_RXMAX_OHMS,
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
            'buffer': None,
            'rb': None,
            'rk': None,
            'cf': None,
            'rxmax': None,
        }

    def _init_ui_state(self):
        """Initialize UI-related state."""
        self.channel_checkboxes: Dict[int, QCheckBox] = {}
        self.force_x_checkbox: Optional[QCheckBox] = None
        self.force_z_checkbox: Optional[QCheckBox] = None
        self._heatmap_autosave_enabled = False
        self._shear_autosave_enabled = False
        self.visualization_capture_data_enabled = False
        
        self.is_updating_plot = False
        self._adc_curves = {}
        self._adc_curve_names = {}
        self._adc_curve_legend_added = {}
        self._force_x_curve = None
        self._force_z_curve = None
        self.force_plot_debounce_ms = 100
    
    def _init_heatmap_state(self):
        """Initialize heatmap processing state."""
        import numpy as np
        from data_processing.heatmap_signal_processing import HeatmapSignalProcessor
        
        # Smoothed values for CoP and intensity
        self.smoothed_cop_x = [0.0 for _ in range(MAX_SENSOR_PACKAGES)]
        self.smoothed_cop_y = [0.0 for _ in range(MAX_SENSOR_PACKAGES)]
        self.smoothed_intensity = [0.0 for _ in range(MAX_SENSOR_PACKAGES)]
        self.active_sensor_package_count = 1
        
        # Pre-allocate heatmap buffers
        self.heatmap_buffers = [
            np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
            for _ in range(MAX_SENSOR_PACKAGES)
        ]
        
        # Pre-compute coordinate grids for Gaussian blob
        y_coords = np.linspace(-1, 1, HEATMAP_HEIGHT).reshape(-1, 1)
        x_coords = np.linspace(-1, 1, HEATMAP_WIDTH).reshape(1, -1)
        self.heatmap_y_grid = np.tile(y_coords, (1, HEATMAP_WIDTH))
        self.heatmap_x_grid = np.tile(x_coords, (HEATMAP_HEIGHT, 1))

        self.heatmap_signal_processors = [
            HeatmapSignalProcessor(
                channel_count=HEATMAP_REQUIRED_CHANNELS,
                bias_duration_sec=BIAS_CALIBRATION_DURATION_SEC,
                hpf_cutoff_hz=HPF_CUTOFF_HZ,
            )
            for _ in range(MAX_SENSOR_PACKAGES)
        ]
        self.last_heatmap_sweep_count = 0

    def _init_shear_state(self):
        """Initialize shear / CoP processing state."""
        self.init_shear_processing_state()

    def _init_timers(self):
        """Initialize Qt timers."""
        self.plot_update_timer = QTimer()
        self.plot_update_timer.setSingleShot(True)
        self.plot_update_timer.timeout.connect(self.update_plot)
        self.plot_update_timer.timeout.connect(self.update_force_plot)

        self.force_plot_timer = QTimer()
        self.force_plot_timer.setSingleShot(True)
        self.force_plot_timer.timeout.connect(self.update_force_plot)
        
        self.config_check_timer = QTimer()
        self.config_check_timer.timeout.connect(self.check_config_completion)
        self.config_check_timer.setInterval(CONFIG_CHECK_INTERVAL)
        
        # Heatmap update timer
        self.heatmap_timer = QTimer()
        self.heatmap_timer.timeout.connect(self.update_heatmap)
        self.heatmap_timer.setInterval(int(1000 / HEATMAP_FPS))  # Convert FPS to milliseconds

        # Spectrum update timer
        self.spectrum_timer = QTimer()
        self.spectrum_timer.timeout.connect(self.update_spectrum)
        self.spectrum_timer.setInterval(100)
        
        # Simulated sensor data source (for testing)
        self.simulated_sensor_thread: Optional[SimulatedSensorThread] = None
        self.use_simulated_data = False
        self.latest_sensor_values = [0.0, 0.0, 0.0, 0.0, 0.0]

    def _log_startup_message(self):
        """Log startup message to status window."""
        self.log_status("=" * 70)
        self.log_status("ADC STREAMER - Production Modular Version")
        self.log_status("✅ All modules loaded successfully")
        self.log_status("=" * 70)

    def init_ui(self):
        """Initialize the user interface using GUIComponentsMixin methods."""
        self.setWindowTitle("ADC Streamer - Modular Architecture")
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target_width = min(WINDOW_WIDTH, max(1200, available.width() - 40))
            target_height = min(WINDOW_HEIGHT, max(900, available.height() - 40))
            self.resize(target_width, target_height)
            self.move(available.x() + max(0, (available.width() - target_width) // 2),
                      available.y() + max(0, (available.height() - target_height) // 2))
        else:
            self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

        # Main widget and layout
        from PyQt6.QtWidgets import QSplitter, QVBoxLayout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Create and add panels
        splitter.addWidget(self._create_left_control_panel())
        splitter.addWidget(self._create_right_visualization_panel())
        splitter.setStretchFactor(0, 1)  # Controls get 1 part
        splitter.setStretchFactor(1, 3)  # Plot gets 3 parts

        # Status bar
        self.statusBar().showMessage("Disconnected")
        
        # Connect tab change signal to start/stop heatmap simulation
        self.visualization_tabs.currentChanged.connect(self.on_visualization_tab_changed)

    def _create_left_control_panel(self) -> QWidget:
        """Create left panel with all control sections."""
        from PyQt6.QtWidgets import QVBoxLayout
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # Add all control sections from GUIComponentsMixin
        layout.addWidget(self.create_serial_section())
        layout.addWidget(self.create_adc_config_section())
        layout.addWidget(self.create_acquisition_section())
        layout.addWidget(self.create_run_control_section())
        layout.addWidget(self.create_file_management_section())
        layout.addWidget(self.create_status_section())
        layout.addStretch()

        return panel

    def _create_right_visualization_panel(self) -> QWidget:
        """Create right panel with tabbed visualization."""
        from PyQt6.QtWidgets import QVBoxLayout
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Add tabbed visualization (timing and controls are now inside timeseries tab)
        layout.addWidget(self.create_plot_section())
        
        return panel
    
    # ========================================================================
    # Window Management
    # ========================================================================

    def closeEvent(self, event):
        """Handle window close event."""
        self.save_last_heatmap_settings()
        self.save_last_shear_settings()
        self.save_last_spectrum_settings()

        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        if self.force_serial_port and self.force_serial_port.is_open:
            self.disconnect_force()

        self.shutdown_spectrum_worker()
        
        # Stop heatmap simulation thread
        if self.simulated_sensor_thread is not None:
            self.simulated_sensor_thread.stop()
            self.simulated_sensor_thread.wait()
        
        event.accept()
    
    # ========================================================================
    # Heatmap Update Logic
    # ========================================================================
    
    def on_visualization_tab_changed(self, index):
        """Handle tab change to start/stop heatmap simulation.
        
        Args:
            index: Tab index (0=Time Series, 1=Heatmap)
        """
        current_tab = self.visualization_tabs.tabText(index)

        if current_tab in {"2D Heatmap", "Shear"}:
            self.start_heatmap_simulation()
        else:  # Time Series or other tabs
            self.stop_heatmap_simulation()

        if current_tab == "Spectrum":
            self.start_spectrum_updates()
        else:
            self.stop_spectrum_updates()

        self.sync_visualization_capture_buttons()

    def get_current_visualization_tab_name(self) -> str:
        """Return the current visualization tab title."""
        if not hasattr(self, "visualization_tabs") or self.visualization_tabs is None:
            return ""
        current_index = self.visualization_tabs.currentIndex()
        if current_index < 0:
            return ""
        return self.visualization_tabs.tabText(current_index)

    def is_live_visualization_only_tab(self) -> bool:
        """Return True when current tab should avoid time-series capture by default."""
        return self.get_current_visualization_tab_name() in {"2D Heatmap", "Shear"}

    def should_store_capture_data(self) -> bool:
        """Return True when capture should persist/archive time-series data."""
        if not self.is_capturing:
            return False
        if self.is_live_visualization_only_tab():
            return bool(self.visualization_capture_data_enabled)
        return True

    def set_visualization_capture_data_enabled(self, enabled: bool):
        """Enable or disable time-series capture while on heatmap/shear tabs."""
        enabled = bool(enabled)
        if self.visualization_capture_data_enabled == enabled:
            self.sync_visualization_capture_buttons()
            return
        self.visualization_capture_data_enabled = enabled
        state_text = "enabled" if enabled else "disabled"
        self.log_status(f"Visualization tab data capture {state_text}")
        self.sync_visualization_capture_buttons()

    def sync_visualization_capture_buttons(self):
        """Keep heatmap/shear Capture Data buttons in sync with shared state."""
        for attr_name in ("heatmap_capture_button", "shear_capture_button"):
            button = getattr(self, attr_name, None)
            if button is None:
                continue
            old_block = button.blockSignals(True)
            button.setChecked(bool(self.visualization_capture_data_enabled))
            button.blockSignals(old_block)
    
    def start_heatmap_simulation(self):
        """Start heatmap updates."""
        
        # Start heatmap update timer
        if not self.heatmap_timer.isActive():
            self.heatmap_timer.start()
    
    def stop_heatmap_simulation(self):
        """Stop heatmap updates."""
        
        # Stop heatmap update timer
        if self.heatmap_timer.isActive():
            self.heatmap_timer.stop()

    def start_spectrum_updates(self):
        """Start spectrum updates."""
        if not self.spectrum_timer.isActive():
            self.spectrum_timer.start()

    def stop_spectrum_updates(self):
        """Stop spectrum updates."""
        if self.spectrum_timer.isActive():
            self.spectrum_timer.stop()
    
    def on_simulated_sensor_data(self, sensor_values):
        """Handle new simulated sensor data (runs in main thread via signal).
        
        Args:
            sensor_values: List of 5 sensor values
        """
        # Store latest sensor values for heatmap update
        self.latest_sensor_values = sensor_values
    
    def update_heatmap(self):
        """Update heatmap display (called by QTimer at HEATMAP_FPS rate)."""
        current_tab = self.visualization_tabs.tabText(self.visualization_tabs.currentIndex())
        if current_tab not in {"2D Heatmap", "Shear"}:
            return

        if hasattr(self, 'update_heatmap_ui_for_mode'):
            self.update_heatmap_ui_for_mode()
        
        channels = self.config.get('channels', [])
        unique_channels = []
        for ch in channels:
            if ch not in unique_channels:
                unique_channels.append(ch)
        num_channels = len(unique_channels)

        # PZR and PZT modes now both use 5 channels and share the same processing
        valid_channel_count = (
            num_channels >= HEATMAP_REQUIRED_CHANNELS
            and num_channels <= HEATMAP_REQUIRED_CHANNELS * MAX_SENSOR_PACKAGES
            and num_channels % HEATMAP_REQUIRED_CHANNELS == 0
        )
        sensor_package_count = max(1, num_channels // HEATMAP_REQUIRED_CHANNELS) if valid_channel_count else 1
        required_channels = "5, 10, 15, or 20"

        self.active_sensor_package_count = sensor_package_count
        if hasattr(self, "update_visible_heatmap_cards"):
            self.update_visible_heatmap_cards(sensor_package_count)
        if hasattr(self, "update_visible_shear_cards"):
            self.update_visible_shear_cards(sensor_package_count)

        if not valid_channel_count:
            if current_tab == "Shear":
                self.show_shear_channel_warning(num_channels, required_channels)
            else:
                self.show_heatmap_channel_warning(num_channels, required_channels)
            return
        else:
            self.clear_heatmap_channel_warning()
            self.clear_shear_channel_warning()
        
        # Reset processing state if capture restarted
        if self.sweep_count < self.last_heatmap_sweep_count:
            for processor in getattr(self, "heatmap_signal_processors", []):
                processor.reset()
            self.reset_shear_processing_state()
        self.last_heatmap_sweep_count = self.sweep_count
        self.last_shear_sweep_count = self.sweep_count

        if current_tab == "Shear":
            processed = self.compute_shear_visualization(self.get_shear_settings())
            if processed is None:
                return

            self.update_shear_display(processed)
            return

        settings = self.get_heatmap_settings()
        sensor_packages = self.compute_channel_intensities(settings)
        if sensor_packages is None:
            return

        package_results = [
            self.process_sensor_data_for_heatmap(sensor_values, settings, package_index=index)
            for index, sensor_values in enumerate(sensor_packages)
        ]
        
        # Compute shear data for arrow visualization
        shear_settings = self.get_shear_settings()
        shear_processed = self.compute_shear_visualization(shear_settings)
        shear_results = shear_processed if shear_processed is not None else []
        
        # Update display
        self.update_heatmap_display(package_results, shear_results=shear_results)


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern look across platforms

    window = ADCStreamerGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
