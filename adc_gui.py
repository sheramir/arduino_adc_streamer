#!/usr/bin/env python3
"""
ADC Streamer GUI
================
Main application window composed from focused mixins.

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
from typing import Optional, Dict

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QCheckBox
from PyQt6.QtCore import QThread, QTimer, Qt
from PyQt6.QtGui import QGuiApplication
import serial

# Import configuration constants
from config_constants import *

# Import mixin modules
from serial_communication import ADCSerialMixin, ForceSerialMixin
from serial_communication.adc_connection_state import (
    build_default_arduino_status,
    build_default_last_sent_config,
)
from serial_communication.adc_connection_workflow import ADCConnectionWorkflow
from serial_communication.force_connection_workflow import ForceConnectionWorkflow
from serial_communication.serial_threads import SerialReaderThread
from config import MCUDetectorMixin, ConfigurationMixin
from config.adc_config_state import build_default_adc_config_state
from config.adc_configuration_service import ADCConfigurationService
from config.adc_configuration_runner import ADCConfigurationRunner
from gui import (
    ControlPanelsMixin,
    DisplayPanelsMixin,
    FilePanelsMixin,
    SensorPanelMixin,
    SpectrumPanelMixin,
    StatusLoggingMixin,
)
from data_processing import (
    DataProcessorMixin,
    SpectrumProcessorMixin,
)
from data_processing.force_state import build_default_force_runtime_state
from file_operations import (
    ArchiveLoaderMixin,
    DataExporterMixin,
    PlotExporterMixin,
)


class ADCStreamerGUI(
    QMainWindow,
    ADCSerialMixin,         # ✅ Serial communication
    ForceSerialMixin,       # ✅ Force sensor communication
    MCUDetectorMixin,       # ✅ MCU detection
    StatusLoggingMixin,     # GUI status logging
    ControlPanelsMixin,     # ✅ Control panel UI
    DisplayPanelsMixin,     # ✅ Display panel UI
    FilePanelsMixin,        # ✅ File panel UI
    SensorPanelMixin,       # ✅ Sensor panel UI
    SpectrumPanelMixin,     # ✅ Spectrum panel UI
    ConfigurationMixin,     # ✅ Configuration management
    DataProcessorMixin,     # ✅ Data processing
    SpectrumProcessorMixin, # ✅ Spectrum processing
    DataExporterMixin,      # ✅ Data export
    PlotExporterMixin,      # ✅ Plot export
    ArchiveLoaderMixin      # ✅ Archive loading
):
    """
    Main application window that coordinates serial I/O, plotting, sensor views,
    configuration, and export features across focused mixins.
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
        self._init_spectrum_state()
        self._init_timers()

        # Build user interface
        self.init_ui()
        self._refresh_sensor_tab_ui()
        self.load_last_spectrum_settings()

        # Post-initialization
        self.update_port_list()
        self._log_startup_message()

    def _init_serial_state(self):
        """Initialize serial connection state."""
        self.serial_port: Optional[serial.Serial] = None
        self.serial_thread: Optional[SerialReaderThread] = None
        self.current_mcu: Optional[str] = None
        self.adc_session = None
        self.adc_connection_workflow = ADCConnectionWorkflow()

    def _init_data_buffers(self):
        """Initialize data storage buffers."""
        self.MAX_SWEEPS_BUFFER = MAX_SWEEPS_IN_MEMORY
        self.raw_data_buffer = None
        self.processed_data_buffer = None
        self.sweep_timestamps_buffer = None
        self.samples_per_sweep = 0
        self.buffer_lock = threading.Lock()
        self._init_filter_state()
        self._reset_capture_buffer_state()
        
        self.is_capturing = False
        self.is_full_view = False

    def _init_archive_state(self):
        """Initialize archive file state."""
        self._archive_writer = None
        self._archive_path: Optional[str] = None
        self._archive_write_count = 0
        self._block_timing_file = None
        self._block_timing_path: Optional[str] = None
        self._block_timing_write_count = 0
        self._cache_dir_path: Optional[str] = None

    def _init_force_state(self):
        """Initialize force sensor state."""
        self.force_connection_workflow = ForceConnectionWorkflow()
        self.force_session = None
        self.force_serial_port: Optional[serial.Serial] = None
        self.force_serial_thread: Optional[QThread] = None
        self.force_state = build_default_force_runtime_state()

    def _init_timing_state(self):
        """Initialize timing measurement state."""
        self._reset_timing_measurements(reset_labels=False)

    def _init_config_state(self):
        """Initialize configuration state."""
        self.device_mode = 'adc'
        self.adc_configuration_service = ADCConfigurationService(self.send_command_and_wait_ack)
        self.adc_configuration_runner = ADCConfigurationRunner(self.adc_configuration_service)

        self.config = build_default_adc_config_state()
        
        self.last_sent_config = build_default_last_sent_config()
        
        self.config_is_valid = False
        
        self.arduino_status = build_default_arduino_status()

    def _init_ui_state(self):
        """Initialize UI-related state."""
        self.channel_checkboxes: Dict[int, QCheckBox] = {}
        self.force_x_checkbox: Optional[QCheckBox] = None
        self.force_z_checkbox: Optional[QCheckBox] = None
        
        self.is_updating_plot = False
        self._adc_curves = {}
        self._adc_curve_names = {}
        self._adc_curve_legend_added = {}
        self._force_x_curve = None
        self._force_z_curve = None
        self.force_plot_debounce_ms = FORCE_PLOT_DEBOUNCE_MS
        self._serial_disconnect_in_progress = False
    
    def _init_timers(self):
        """Initialize Qt timers."""
        self.plot_update_timer = QTimer()
        self.plot_update_timer.setSingleShot(True)
        # Shared debounce for ADC-driven refreshes. When ADC buffers land we redraw
        # both the ADC traces and the force traces together so the views stay aligned.
        self.plot_update_timer.timeout.connect(self.update_plot)
        self.plot_update_timer.timeout.connect(self.update_force_plot)

        self.force_plot_timer = QTimer()
        self.force_plot_timer.setSingleShot(True)
        # Separate debounce for force-only arrivals. Force samples can arrive between
        # ADC buffer updates, so this timer refreshes just the force plot without
        # waiting for the next ADC-driven redraw.
        self.force_plot_timer.timeout.connect(self.update_force_plot)
        
        self.config_check_timer = QTimer()
        self.config_check_timer.timeout.connect(self.check_config_completion)
        self.config_check_timer.setInterval(CONFIG_CHECK_INTERVAL)

        # Spectrum update timer
        self.spectrum_timer = QTimer()
        self.spectrum_timer.timeout.connect(self.update_spectrum)
        self.spectrum_timer.setInterval(SPECTRUM_UPDATE_INTERVAL_MS)

    def _log_startup_message(self):
        """Log startup message to status window."""
        self.log_status("=" * STATUS_SEPARATOR_WIDTH)
        self.log_status("ADC STREAMER - Production Modular Version")
        self.log_status("✅ All modules loaded successfully")
        self.log_status("=" * STATUS_SEPARATOR_WIDTH)

    def init_ui(self):
        """Initialize the user interface using the leaf GUI mixins."""
        self.setWindowTitle("ADC Streamer - Modular Architecture")

        # Main widget and layout
        from PyQt6.QtWidgets import QSplitter, QVBoxLayout, QSizePolicy, QLayout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        main_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        main_widget.setMinimumSize(0, 0)

        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(True)
        splitter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        main_layout.addWidget(splitter)

        # Create and add panels
        splitter.addWidget(self._create_left_control_panel())
        splitter.addWidget(self._create_right_visualization_panel())
        splitter.setStretchFactor(0, CONTROL_PANEL_STRETCH)  # Controls get 1 part
        splitter.setStretchFactor(1, VISUALIZATION_PANEL_STRETCH)  # Plot gets 3 parts

        # Status bar
        self.statusBar().showMessage("Disconnected")
        
        self.visualization_tabs.currentChanged.connect(self.on_visualization_tab_changed)

        self._fit_window_to_screen()
        QTimer.singleShot(0, self._fit_window_to_screen)

    def _fit_window_to_screen(self):
        """Clamp window geometry to current screen and relax oversize minimums."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
            return

        available = screen.availableGeometry()
        max_width = max(WINDOW_MIN_FIT_WIDTH, available.width() - WINDOW_SCREEN_MARGIN_PX)
        max_height = max(WINDOW_MIN_FIT_HEIGHT, available.height() - WINDOW_SCREEN_MARGIN_PX)

        if self.minimumSizeHint().width() > max_width or self.minimumSizeHint().height() > max_height:
            self.setMinimumSize(0, 0)
            central = self.centralWidget()
            if central is not None:
                central.setMinimumSize(0, 0)

        preferred_width = max(WINDOW_WIDTH, min(self.width() if self.width() > 0 else WINDOW_WIDTH, max_width))
        preferred_height = max(WINDOW_HEIGHT, min(self.height() if self.height() > 0 else WINDOW_HEIGHT, max_height))
        target_width = min(preferred_width, max_width)
        target_height = min(preferred_height, max_height)

        self.resize(target_width, target_height)
        self.move(
            available.x() + max(0, (available.width() - target_width) // 2),
            available.y() + max(0, (available.height() - target_height) // 2),
        )

    def _create_left_control_panel(self) -> QWidget:
        """Create left panel with all control sections."""
        from PyQt6.QtWidgets import QVBoxLayout, QSizePolicy
        panel = QWidget()
        panel.setMinimumSize(0, 0)
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(panel)
        layout.setSpacing(MAIN_PANEL_LAYOUT_SPACING)

        # Add all control sections from the leaf GUI mixins
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
        from PyQt6.QtWidgets import QVBoxLayout, QSizePolicy
        panel = QWidget()
        panel.setMinimumSize(0, 0)
        panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(panel)

        # Add tabbed visualization (timing and controls are now inside timeseries tab)
        layout.addWidget(self.create_plot_section())
        
        return panel
    
    # ========================================================================
    # Window Management
    # ========================================================================

    def closeEvent(self, event):
        """Handle window close event."""
        self.save_last_spectrum_settings()

        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        if self.force_serial_port and self.force_serial_port.is_open:
            self.disconnect_force_serial()

        self.shutdown_filter_worker()
        self.shutdown_spectrum_worker()

        event.accept()
    
    # ========================================================================
    # Visualization Tab Logic
    # ========================================================================
    
    def on_visualization_tab_changed(self, index):
        """Handle tab changes for time-series and spectrum refresh behavior."""
        current_tab = self.visualization_tabs.tabText(index)

        if current_tab == "Spectrum":
            self.start_spectrum_updates()
        else:
            self.stop_spectrum_updates()

        if current_tab == "Time Series":
            if hasattr(self, 'spectrum_busy'):
                self.spectrum_busy = False
            if (
                hasattr(self, 'should_filter_adc_data')
                and self.should_filter_adc_data()
                and hasattr(self, 'prepare_timeseries_filter_resume')
            ):
                self.prepare_timeseries_filter_resume()
            self.trigger_plot_update()
            self.update_force_plot()

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
        return False

    def should_store_capture_data(self) -> bool:
        """Return True when capture should persist/archive time-series data."""
        return bool(self.is_capturing)

    def should_update_live_timeseries_display(self) -> bool:
        """Return True when live ADC/force plot redraws should run."""
        return self.get_current_visualization_tab_name() == "Time Series"

    def start_spectrum_updates(self):
        """Start spectrum updates."""
        if not self.spectrum_timer.isActive():
            self.spectrum_timer.start()
        self.spectrum_busy = False
        QTimer.singleShot(0, self.update_spectrum)

    def stop_spectrum_updates(self):
        """Stop spectrum updates."""
        if self.spectrum_timer.isActive():
            self.spectrum_timer.stop()


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern look across platforms

    window = ADCStreamerGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
