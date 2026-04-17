"""
Force Serial Communication Mixin
================================
Handles force sensor connection workflow and GUI coordination.
"""

from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QTimer

from constants.force import (
    FORCE_CALIBRATION_SAMPLES,
    FORCE_SENSOR_BAUD_RATE,
)
from data_processing.force_state import get_force_runtime_state
from serial_communication.force_connection_state import (
    build_force_connected_view_state,
    build_force_disconnected_view_state,
)
from serial_communication.force_session import ForceSessionController


class ForceSerialMixin:
    """Mixin class for force sensor serial communication methods."""

    def _apply_force_connection_view_state(self, view_state):
        self.force_connect_btn.setText(view_state.connect_button_text)
        self.force_port_combo.setEnabled(view_state.port_selection_enabled)
        if hasattr(self, "force_reset_btn") and self.force_reset_btn is not None:
            self.force_reset_btn.setEnabled(view_state.reset_button_enabled)

    def _sync_force_transport_state(self):
        """Mirror controller-owned transport objects on the GUI for existing callers."""
        session = getattr(self, "force_session", None)
        self.force_serial_port = session.serial_port if session is not None else None
        self.force_serial_thread = session.serial_thread if session is not None else None

    def _build_force_session(self):
        return ForceSessionController(
            self.process_force_data,
            self._handle_force_reader_error,
        )

    def _warn_if_no_force_data_received(self):
        """Emit a bounded warning when the connected force port stays silent."""
        state = get_force_runtime_state(self)
        port = getattr(self, "force_serial_port", None)
        if port is None or not getattr(port, "is_open", False):
            return
        if state.raw_samples_seen > 0:
            return

        port_label = state.selected_port_text or "force port"
        self.log_status(
            f"WARNING: No force data received from {port_label} after connect. "
            "Plotting will stay empty until the device streams serial data."
        )
    
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
            state = get_force_runtime_state(self)
            if getattr(self, "force_session", None) is None:
                self.force_session = self._build_force_session()

            state.raw_samples_seen = 0
            state.recent_raw_samples.clear()
            state.selected_port_text = port_text
            outcome = self.force_connection_workflow.connect(self.force_session, port_name)
            self._sync_force_transport_state()

            self.log_status(f"Connected to force sensor on {port_text} at {FORCE_SENSOR_BAUD_RATE} baud")
            self.log_status(f"Calibrating force sensors (collecting {FORCE_CALIBRATION_SAMPLES} samples)...")
            QTimer.singleShot(3000, self._warn_if_no_force_data_received)
            
            # Start calibration
            if outcome.should_start_calibration:
                self.calibrate_force_sensors()

            self._apply_force_connection_view_state(build_force_connected_view_state())
            
            # Update channel list to add force checkboxes
            if self.config['channels']:  # Only if ADC is already configured
                self.update_channel_list()

        except Exception as e:
            self._sync_force_transport_state()
            self._apply_force_connection_view_state(build_force_disconnected_view_state())
            self.log_status(f"ERROR: Failed to connect to force sensor - {e}")
            QMessageBox.critical(self, "Force Connection Error", f"Failed to connect:\n{e}")

    def _handle_force_reader_error(self, message: str):
        """Handle force-reader errors and transition to a clean disconnected state."""
        self.log_status(message)

        if not str(message).startswith("Force sensor read error:"):
            return

        state = get_force_runtime_state(self)
        if state.disconnect_in_progress:
            return
        if not self.force_serial_port and not self.force_serial_thread:
            return

        self.log_status("Force sensor connection lost - disconnecting")
        QTimer.singleShot(0, self.disconnect_force_serial)

    def reset_force_load_cell(self):
        """Re-zero the load cell using the most recent raw force samples."""
        force_port = getattr(self, "force_serial_port", None)
        if force_port is None or not getattr(force_port, "is_open", False):
            self.log_status("WARNING: Connect the force sensor before resetting the load cell")
            return

        self.log_status(
            f"Resetting load cell baseline from the last {FORCE_CALIBRATION_SAMPLES} raw samples..."
        )
        self.reset_force_baseline_from_recent_samples()

    def disconnect_force_serial(self):
        """Disconnect from the force sensor serial port."""
        state = get_force_runtime_state(self)
        if state.disconnect_in_progress:
            return

        state.disconnect_in_progress = True

        try:
            outcome = self.force_connection_workflow.disconnect(getattr(self, "force_session", None))
            for warning in outcome.warnings:
                self.log_status(f"WARNING: {warning}")

            self._sync_force_transport_state()
            state.selected_port_text = None
            state.recent_raw_samples.clear()
            
            self.log_status("Force sensor disconnected")
            self._apply_force_connection_view_state(build_force_disconnected_view_state())
            
            # Update channel list to remove force checkboxes
            if self.config['channels']:  # Only if ADC is configured
                self.update_channel_list()
        finally:
            state.disconnect_in_progress = False
