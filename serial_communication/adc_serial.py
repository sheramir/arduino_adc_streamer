"""
ADC Serial Communication Mixin
==============================
Handles ADC serial port connection and communication.
"""

import time
import serial
import serial.tools.list_ports
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QCoreApplication, QTimer

from config_constants import (
    BAUD_RATE, SERIAL_TIMEOUT, COMMAND_TERMINATOR, ARDUINO_RESET_DELAY,
    CONFIG_COMMAND_TIMEOUT, CONFIG_RETRY_ATTEMPTS, CONFIG_RETRY_DELAY,
    CLEAR_CACHE_ON_EXIT,
)
from serial_communication.serial_threads import SerialReaderThread


class ADCSerialMixin:
    """Mixin class for ADC serial communication methods."""

    def _clear_adc_line_waiters(self):
        self._adc_line_waiters = []

    def _handle_adc_text_line(self, line: str) -> bool:
        """Route ADC text lines to any pending waiters.

        Returns True when a waiter consumes the line and it should not continue
        through the normal status parser/log path.
        """
        waiters = list(getattr(self, "_adc_line_waiters", []))
        if not waiters:
            return False

        consumed = False
        remaining = []
        for waiter in waiters:
            matcher = waiter.get("matcher")
            if matcher is not None and matcher(line):
                waiter["matched_line"] = line
                if waiter.get("consume", False):
                    consumed = True
                continue
            remaining.append(waiter)

        self._adc_line_waiters = remaining
        return consumed

    def _wait_for_adc_line(self, matcher, timeout: float, *, consume: bool = False, send_action=None):
        """Wait for a routed ADC text line while keeping the Qt event loop alive."""
        waiter = {
            "matcher": matcher,
            "consume": consume,
            "matched_line": None,
        }
        self._adc_line_waiters.append(waiter)
        deadline = time.time() + timeout

        try:
            if send_action is not None:
                send_action()
            while time.time() < deadline:
                if waiter["matched_line"] is not None:
                    return waiter["matched_line"]
                QCoreApplication.processEvents()
                time.sleep(0.01)
            return None
        finally:
            if waiter in self._adc_line_waiters:
                self._adc_line_waiters.remove(waiter)

    @staticmethod
    def _parse_ack_line(line: str):
        if line.startswith('#OK'):
            return True, line[3:].strip() if len(line) > 3 else None
        if line.startswith('#NOT_OK'):
            return False, line[7:].strip() if len(line) > 7 else None
        return None
    
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
            
            # Wait for Arduino to reset
            time.sleep(ARDUINO_RESET_DELAY)
            
            # Clear any startup messages or garbage data
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            time.sleep(0.1)

            # Start serial reader thread
            self._clear_adc_line_waiters()
            self.serial_thread = SerialReaderThread(self.serial_port)
            self.serial_thread.data_received.connect(self.process_serial_data)
            self.serial_thread.binary_sweep_received.connect(self.process_binary_sweep)
            self.serial_thread.error_occurred.connect(self._handle_serial_reader_error)
            self.serial_thread.start()

            # Detect MCU type after the reader thread is active so only one ADC
            # consumer reads lines from the port.
            self.detect_mcu()

            self.log_status(f"Connected to {port_name}")
            self.connect_btn.setText("Disconnect")
            self.configure_btn.setEnabled(True)
            self.configure_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; }")
            self.start_btn.setEnabled(False)
            self.statusBar().showMessage("Connected - Please configure")

            # Disable port selection during connection
            self.port_combo.setEnabled(False)
            self.refresh_ports_btn.setEnabled(False)
            
            # Update GUI based on detected MCU
            self.update_gui_for_mcu()

        except Exception as e:
            self.log_status(f"ERROR: Failed to connect - {e}")
            QMessageBox.critical(self, "Connection Error", f"Failed to connect:\n{e}")

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
            thread = self.serial_thread
            if self.is_capturing:
                self.stop_capture()

            if CLEAR_CACHE_ON_EXIT and hasattr(self, 'cleanup_capture_cache'):
                self.cleanup_capture_cache(block=cleanup_block)

            if thread:
                try:
                    thread.stop()
                    if not thread.wait(250):
                        self.log_status("WARNING: Serial thread shutdown timed out; continuing disconnect")
                except Exception as e:
                    self.log_status(f"WARNING: Serial thread did not stop cleanly: {e}")
                self.serial_thread = None

            if self.serial_port and self.serial_port.is_open:
                try:
                    self.serial_port.close()
                except Exception as e:
                    self.log_status(f"WARNING: Failed to close serial port cleanly: {e}")

            self.serial_port = None
            self._clear_adc_line_waiters()
            
            # Reset MCU detection
            self.current_mcu = None
            self.device_mode = 'adc'
            self.mcu_label.setText("MCU: -")
            self.update_gui_for_mcu()
            
            # Reset last sent config
            self.last_sent_config = {
                'channels': None,
                'repeat': None,
                'ground_pin': None,
                'use_ground': None,
                'osr': None,
                'gain': None,
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
        finally:
            self._serial_disconnect_in_progress = False

    def send_command(self, command: str):
        """Send a command to the Arduino."""
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(f"{command}{COMMAND_TERMINATOR}".encode('utf-8'))
                self.serial_port.flush()
            except Exception as e:
                self.log_status(f"ERROR: Failed to send command - {e}")
        else:
            self.log_status("ERROR: Not connected to serial port")

    def drain_serial_input(self, duration: float = 0.3):
        """Drop pending ADC bytes without competing with the reader thread."""
        if not self.serial_port or not self.serial_port.is_open:
            return

        try:
            time.sleep(max(0.0, duration))
            if self.serial_thread:
                self.serial_thread.clear_buffer()
            try:
                self.serial_port.reset_input_buffer()
            except Exception:
                pass
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
        
        for attempt in range(max_retries):
            try:
                # Flush buffers before retry
                if attempt > 0:
                    time.sleep(CONFIG_RETRY_DELAY)
                    self.serial_port.reset_input_buffer()
                    self.serial_port.reset_output_buffer()
                
                line = self._wait_for_adc_line(
                    lambda text: text.startswith('#OK') or text.startswith('#NOT_OK'),
                    timeout,
                    consume=True,
                    send_action=lambda: (
                        self.serial_port.write(f"{command}{COMMAND_TERMINATOR}".encode('utf-8')),
                        self.serial_port.flush(),
                    ),
                )

                if line is None:
                    if attempt >= max_retries - 1:
                        return (False, None)
                    continue

                parsed = self._parse_ack_line(line)
                if parsed is None:
                    if attempt >= max_retries - 1:
                        return (False, None)
                    continue

                success, received_value = parsed
                if expected_value is not None and received_value != expected_value:
                    if attempt < max_retries - 1:
                        continue
                    return (False, received_value)

                return (success, received_value)
                
                # Timeout - retry silently
            except Exception as e:
                if attempt >= max_retries - 1:
                    return (False, None)
        
        return (False, None)
