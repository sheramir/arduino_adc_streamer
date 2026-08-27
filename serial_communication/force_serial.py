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
    ForceConnectionState,
    build_force_disconnected_view_state,
)
from serial_communication.device_config import connected_port_name, find_force_port
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

    def _toggle_force_connection(self):
        """Main button handler: auto-connect when disconnected, disconnect when connected."""
        if self.force_conn_state == ForceConnectionState.CONNECTED:
            self.disconnect_force_serial()
        elif self.force_conn_state == ForceConnectionState.DISCONNECTED:
            self._auto_connect_force()

    def _show_force_connect_menu(self):
        force_state = getattr(self, "force_conn_state", ForceConnectionState.DISCONNECTED)
        if force_state != ForceConnectionState.DISCONNECTED:
            return
        btn = self._force_arrow_btn
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        self._force_connect_menu.exec(pos)

    def _auto_connect_force(self):
        """Try to connect to the first matching Force device from adc_devices.json silently."""
        exclude_port = connected_port_name(getattr(self, "serial_port", None))
        port, dev = find_force_port(exclude_port=exclude_port)
        if port is None:
            self.log_status("[Auto-connect Force] No configured Force device found — connect manually")
            return

        sn = dev.get("serial_number") or "any S/N"
        self.log_status(f"[Auto-connect Force] Found {dev['name']} on {port} (S/N: {sn}) — connecting…")

        # Pre-select the port in the combo so the UI stays coherent
        for i in range(self.force_port_combo.count()):
            if self.force_port_combo.itemText(i).startswith(port):
                self.force_port_combo.setCurrentIndex(i)
                break

        self._start_force_connect(
            port,
            selected_port_text=f"{port} - {dev['name']}",
            on_connected=lambda _outcome: self.log_status(
                f"[Auto-connect Force] Connected to {dev['name']} on {port} at {FORCE_SENSOR_BAUD_RATE} baud"
            ),
            on_failed=lambda message: self.log_status(f"[Auto-connect Force] Failed on {port}: {message}"),
        )

    def connect_force_serial(self):
        """Connect to the force sensor serial port."""
        if self.force_port_combo.currentText() == "No ports found":
            self.log_status("ERROR: No force sensor ports available")
            return

        port_text = self.force_port_combo.currentText()
        port_name = port_text.split(" - ")[0]

        self._start_force_connect(
            port_name,
            selected_port_text=port_text,
            on_connected=lambda _outcome: self.log_status(
                f"Connected to force sensor on {port_text} at {FORCE_SENSOR_BAUD_RATE} baud"
            ),
            on_failed=lambda message: self._on_manual_force_connect_failed(message),
        )

    def _on_manual_force_connect_failed(self, message: str):
        self.log_status(f"ERROR: Failed to connect to force sensor - {message}")
        QMessageBox.critical(self, "Force Connection Error", f"Failed to connect:\n{message}")

    def _start_force_connect(self, port_name: str, *, selected_port_text: str, on_connected, on_failed):
        """Kick off a background Force connect so the sensor startup delay never blocks the GUI."""
        state = get_force_runtime_state(self)
        if getattr(self, "force_session", None) is None:
            self.force_session = self._build_force_session()

        state.raw_samples_seen = 0
        state.recent_raw_samples.clear()
        state.selected_port_text = selected_port_text

        self._force_connect_on_connected = on_connected
        self._force_connect_on_failed = on_failed
        self._force_connect_controller.start(self.force_session, port_name)

    def _on_force_connect_success(self, outcome):
        self._sync_force_transport_state()
        self.log_status(f"Calibrating force sensors (collecting {FORCE_CALIBRATION_SAMPLES} samples)…")
        QTimer.singleShot(3000, self._warn_if_no_force_data_received)

        if outcome.should_start_calibration:
            self.calibrate_force_sensors()

        self.enable_force_calibration_start_stop(True)
        if self.config.get("channels"):
            self.update_channel_list()

        self._force_connect_on_connected(outcome)

    def _on_force_connect_failure(self, message: str):
        self._sync_force_transport_state()
        self._force_connect_on_failed(message)

    def shutdown_force_connect_worker(self):
        worker = getattr(self, "force_connect_worker", None)
        if worker is not None:
            worker.stop()
            worker.wait(1500)

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
            
            self.force_conn_state = ForceConnectionState.DISCONNECTED
            self.log_status("Force sensor disconnected")
            self._apply_force_connection_view_state(build_force_disconnected_view_state())
            self.enable_force_calibration_start_stop(False)
            
            # Update channel list to remove force checkboxes
            if self.config['channels']:  # Only if ADC is configured
                self.update_channel_list()
        finally:
            state.disconnect_in_progress = False
