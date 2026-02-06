"""
ADC Serial Communication Mixin
==============================
Handles ADC serial port connection and communication.
"""

import time
import serial
import serial.tools.list_ports
from PyQt6.QtWidgets import QMessageBox

from config_constants import (
    BAUD_RATE, SERIAL_TIMEOUT, COMMAND_TERMINATOR, ARDUINO_RESET_DELAY,
    CONFIG_COMMAND_TIMEOUT, CONFIG_RETRY_ATTEMPTS, CONFIG_RETRY_DELAY
)
from serial_communication.serial_threads import SerialReaderThread


class ADCSerialMixin:
    """Mixin class for ADC serial communication methods."""
    
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

            # Detect MCU type
            self.detect_mcu()

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
        
        # Reset MCU detection
        self.current_mcu = None
        self.mcu_label.setText("MCU: -")
        
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
        """Drain pending serial bytes to avoid stale binary data."""
        if not self.serial_port or not self.serial_port.is_open:
            return

        end_time = time.time() + duration
        drained = 0

        try:
            while time.time() < end_time:
                waiting = self.serial_port.in_waiting
                if waiting > 0:
                    drained += len(self.serial_port.read(waiting))
                else:
                    time.sleep(0.01)

            try:
                self.serial_port.reset_input_buffer()
            except Exception:
                pass
        except Exception as e:
            self.log_status(f"WARNING: Failed to drain serial input: {e}")
            return

        if drained > 0:
            self.log_status(f"Drained {drained} bytes from serial input after stop")

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
                        
                        # Parse #OK response
                        if line.startswith('#OK'):
                            received_value = line[3:].strip() if len(line) > 3 else None
                            
                            # Verify expected value if provided
                            if expected_value is not None and received_value != expected_value:
                                if attempt < max_retries - 1:
                                    break  # Retry
                                else:
                                    return (False, received_value)
                            
                            return (True, received_value)
                        
                        # Parse #NOT_OK response
                        elif line.startswith('#NOT_OK'):
                            received_value = line[7:].strip() if len(line) > 7 else None
                            if attempt < max_retries - 1:
                                break  # Retry
                            else:
                                return (False, received_value)
                            
                    except Exception:
                        continue
                
                # Timeout - retry silently
                if attempt >= max_retries - 1:
                    return (False, None)
                    
            except Exception as e:
                if attempt >= max_retries - 1:
                    return (False, None)
        
        return (False, None)
