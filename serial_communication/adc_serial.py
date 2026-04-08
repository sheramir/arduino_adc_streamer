"""
ADC Serial Communication Mixin
==============================
Handles ADC serial port connection and communication.
"""

import serial
import serial.tools.list_ports
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QTimer

from config_constants import (
    CONFIG_COMMAND_TIMEOUT, CONFIG_RETRY_ATTEMPTS,
    CLEAR_CACHE_ON_EXIT,
)
from serial_communication.adc_connection_state import (
    build_connected_view_state,
    build_default_last_sent_config,
    build_disconnected_view_state,
)
from serial_communication.adc_session import ADCSessionController


class ADCSerialMixin:
    """Mixin class for ADC serial communication methods."""

    def _apply_adc_connection_view_state(self, view_state):
        self.connect_btn.setText(view_state.connect_button_text)
        self.configure_btn.setEnabled(view_state.configure_enabled)
        if view_state.configure_style is not None:
            self.configure_btn.setStyleSheet(view_state.configure_style)
        self.start_btn.setEnabled(view_state.start_enabled)
        self.stop_btn.setEnabled(view_state.stop_enabled)
        self.statusBar().showMessage(view_state.status_message)
        self.port_combo.setEnabled(view_state.port_selection_enabled)
        self.refresh_ports_btn.setEnabled(view_state.port_selection_enabled)

    def _clear_adc_line_waiters(self):
        if getattr(self, "adc_session", None) is not None:
            self.adc_session.clear_line_waiters()

    def _sync_adc_transport_state(self):
        """Mirror controller-owned transport objects on the GUI for existing callers."""
        session = getattr(self, "adc_session", None)
        self.serial_port = session.serial_port if session is not None else None
        self.serial_thread = session.serial_thread if session is not None else None

    def _handle_adc_text_line(self, line: str) -> bool:
        session = getattr(self, "adc_session", None)
        if session is None:
            return False
        return session.handle_text_line(line)

    def _wait_for_adc_line(self, matcher, timeout: float, *, consume: bool = False, send_action=None):
        session = getattr(self, "adc_session", None)
        if session is None:
            return None
        return session.wait_for_line(matcher, timeout, consume=consume, send_action=send_action)

    @staticmethod
    def _parse_ack_line(line: str):
        return ADCSessionController.parse_ack_line(line)
    
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
            if getattr(self, "adc_session", None) is None:
                self.adc_session = self._build_adc_session()

            self.adc_session.connect(port_name)
            self._sync_adc_transport_state()

            # Detect MCU type after the reader thread is active so only one ADC
            # consumer reads lines from the port.
            self.detect_mcu()

            self.log_status(f"Connected to {port_name}")
            self._apply_adc_connection_view_state(build_connected_view_state())
            
            # Update GUI based on detected MCU
            self.update_gui_for_mcu()

        except Exception as e:
            self.log_status(f"ERROR: Failed to connect - {e}")
            QMessageBox.critical(self, "Connection Error", f"Failed to connect:\n{e}")

    def _build_adc_session(self):
        return ADCSessionController(
            self.process_serial_data,
            self.process_binary_sweep,
            self._handle_serial_reader_error,
        )

    def _handle_serial_reader_error(self, message: str):
        """Handle serial-thread errors and transition to a clean disconnected state."""
        self.log_status(message)

        if not str(message).startswith("Serial read error:"):
            return

        if self._serial_disconnect_in_progress:
            return
        if not self.serial_port and not self.serial_thread:
            return

        self.log_status("Serial device connection lost - disconnecting")
        QTimer.singleShot(0, lambda: self.disconnect_serial(cleanup_block=False))

    def disconnect_serial(self, *, cleanup_block=False):
        """Disconnect from the serial port."""
        if self._serial_disconnect_in_progress:
            return

        self._serial_disconnect_in_progress = True

        try:
            if self.is_capturing:
                self.stop_capture()

            if CLEAR_CACHE_ON_EXIT and hasattr(self, 'cleanup_capture_cache'):
                self.cleanup_capture_cache(block=cleanup_block)

            if getattr(self, "adc_session", None) is not None:
                for warning in self.adc_session.disconnect():
                    self.log_status(f"WARNING: {warning}")
            self._sync_adc_transport_state()
            self._clear_adc_line_waiters()
            
            # Reset MCU detection
            self.current_mcu = None
            self.device_mode = 'adc'
            self.mcu_label.setText("MCU: -")
            self.update_gui_for_mcu()
            
            # Reset last sent config
            self.last_sent_config = build_default_last_sent_config()
            
            # Reset config validity
            self.config_is_valid = False
            
            self.log_status("Disconnected")
            self._apply_adc_connection_view_state(build_disconnected_view_state())
        finally:
            self._serial_disconnect_in_progress = False

    def send_command(self, command: str):
        """Send a command to the Arduino."""
        try:
            if getattr(self, "adc_session", None) is None:
                raise RuntimeError("Not connected to serial port")
            self.adc_session.send_command(command)
            self._sync_adc_transport_state()
        except Exception as e:
            self.log_status(f"ERROR: Failed to send command - {e}")

    def drain_serial_input(self, duration: float = 0.3):
        """Drop pending ADC bytes without competing with the reader thread."""
        try:
            if getattr(self, "adc_session", None) is None:
                return
            self.adc_session.drain_input(duration)
        except Exception as e:
            self.log_status(f"WARNING: Failed to drain serial input: {e}")

    def send_command_and_wait_ack(self, command: str, expected_value: str = None, 
                                   timeout: float = CONFIG_COMMAND_TIMEOUT, 
                                   max_retries: int = CONFIG_RETRY_ATTEMPTS) -> tuple:
        """Send a command and wait for acknowledgment.
        
        Returns:
            tuple: (success: bool, received_value: str or None)
        """
        if not self.serial_port or not self.serial_port.is_open:
            return (False, None)
        if getattr(self, "adc_session", None) is None:
            return (False, None)
        result = self.adc_session.send_command_and_wait_ack(command, expected_value, timeout, max_retries)
        self._sync_adc_transport_state()
        return result
