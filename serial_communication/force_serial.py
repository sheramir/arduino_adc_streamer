"""
Force Serial Communication Mixin
================================
Handles force sensor serial port connection and communication.
"""

import serial
from PyQt6.QtWidgets import QMessageBox

from serial_communication.serial_threads import ForceReaderThread


class ForceSerialMixin:
    """Mixin class for force sensor serial communication methods."""
    
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
            import time
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
