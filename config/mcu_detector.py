"""
MCU Detection Mixin
===================
Detects MCU type and adapts GUI controls accordingly.
"""

import time
from config_constants import COMMAND_TERMINATOR


class MCUDetectorMixin:
    """Mixin class for MCU detection and GUI adaptation."""
    
    def detect_mcu(self):
        """Detect MCU type by sending 'mcu' command and reading response."""
        if not self.serial_port or not self.serial_port.is_open:
            return
        
        try:
            # Send MCU detection command
            self.serial_port.write(f"mcu{COMMAND_TERMINATOR}".encode('utf-8'))
            self.serial_port.flush()
            
            # Wait for response (timeout 2 seconds)
            start_time = time.time()
            while time.time() - start_time < 2.0:
                if self.serial_port.in_waiting > 0:
                    line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    
                    # Look for MCU response (format: "# Teensy4.1" or "# MG24")
                    if line.startswith('#'):
                        mcu_name = line[1:].strip()
                        if mcu_name:
                            self.current_mcu = mcu_name
                            self.mcu_label.setText(f"MCU: {mcu_name}")
                            self.log_status(f"Detected MCU: {mcu_name}")
                            return
                
                time.sleep(0.01)
            
            # Timeout or no response - use generic behavior
            self.current_mcu = None
            self.mcu_label.setText("MCU: Unknown")
            self.log_status("MCU detection timeout - using generic behavior")
            
        except Exception as e:
            self.log_status(f"MCU detection failed: {e}")
            self.current_mcu = None
            self.mcu_label.setText("MCU: Unknown")

    def update_gui_for_mcu(self):
        """Update GUI controls based on detected MCU type."""
        is_teensy = self.current_mcu and "Teensy" in self.current_mcu
        
        if is_teensy:
            # Teensy 4.1: Hide reference and gain, show Teensy-specific controls
            self.vref_label.hide()
            self.vref_combo.hide()
            self.gain_label.hide()
            self.gain_combo.hide()
            
            # Update OSR label and options for Teensy (averaging)
            self.osr_label.setText("Averaging:")
            self.osr_combo.clear()
            self.osr_combo.addItems(["0", "1","4", "8", "16", "32"])
            self.osr_combo.setCurrentText("4")
            self.osr_combo.setToolTip("Hardware averaging: 0=disabled, higher = better SNR")
            
            # Show Teensy-specific controls
            self.conv_speed_label.show()
            self.conv_speed_combo.show()
            self.samp_speed_label.show()
            self.samp_speed_combo.show()
            self.sample_rate_label.show()
            self.sample_rate_spin.show()
            
        else:
            # Non-Teensy (e.g., MG24): Show reference and gain, hide Teensy controls
            self.vref_label.show()
            self.vref_combo.show()
            self.gain_label.show()
            self.gain_combo.show()
            
            # Reset OSR to original settings
            self.osr_label.setText("OSR (Oversampling):")
            self.osr_combo.clear()
            self.osr_combo.addItems(["2", "4", "8"])
            self.osr_combo.setCurrentText("2")
            self.osr_combo.setToolTip("Oversampling ratio: higher = better SNR, lower sample rate")
            
            # Hide Teensy-specific controls
            self.conv_speed_label.hide()
            self.conv_speed_combo.hide()
            self.samp_speed_label.hide()
            self.samp_speed_combo.hide()
            self.sample_rate_label.hide()
            self.sample_rate_spin.hide()
