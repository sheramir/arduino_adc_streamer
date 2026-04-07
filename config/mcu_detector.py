"""
MCU Detection Mixin
===================
Detects MCU type and adapts GUI controls accordingly.
"""

import time
from config_constants import (
    ANALYZER555_BUFFER_SIZE_MAX,
    BUFFER_SIZE_MAX,
    COMMAND_TERMINATOR,
    MCU_DETECTION_POLL_INTERVAL_SEC,
    MCU_DETECTION_TIMEOUT_SEC,
)


class MCUDetectorMixin:
    """Mixin class for MCU detection and GUI adaptation."""

    def is_555_analyzer_mode(self) -> bool:
        return getattr(self, 'device_mode', 'adc') == '555'
    
    def detect_mcu(self):
        """Detect MCU type by sending 'mcu' command and reading response."""
        if not self.serial_port or not self.serial_port.is_open:
            return
        
        try:
            # Send MCU detection command
            self.serial_port.write(f"mcu{COMMAND_TERMINATOR}".encode('utf-8'))
            self.serial_port.flush()
            
            # Wait for response within the configured detection timeout.
            start_time = time.time()
            while time.time() - start_time < MCU_DETECTION_TIMEOUT_SEC:
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
                
                time.sleep(MCU_DETECTION_POLL_INTERVAL_SEC)
            
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
        mcu_name = (self.current_mcu or "")
        lower_name = mcu_name.lower()
        is_array_dual = lower_name.startswith("array_pzt_pzr")
        is_array_mcu = lower_name.startswith("array")

        if is_array_dual:
            selected_mode = "PZT"
            if hasattr(self, 'get_selected_array_operation_mode'):
                selected_mode = self.get_selected_array_operation_mode()
            is_555 = selected_mode == "PZR"
            if hasattr(self, 'config') and isinstance(self.config, dict):
                self.config['array_operation_mode'] = selected_mode
        else:
            is_555 = "555" in lower_name

        is_teensy = ("Teensy" in mcu_name)

        self.device_mode = '555' if is_555 else 'adc'

        if hasattr(self, 'update_heatmap_ui_for_mode'):
            self.update_heatmap_ui_for_mode()

        if hasattr(self, 'update_array_acquisition_inputs_visibility'):
            self.update_array_acquisition_inputs_visibility()

        # 555 analyzer mode: hide ADC-specific controls, show 555 parameter controls
        if is_555:
            if hasattr(self, 'ground_pin_label'):
                self.ground_pin_label.hide()
            if hasattr(self, 'ground_pin_spin'):
                self.ground_pin_spin.hide()
            if hasattr(self, 'use_ground_check'):
                self.use_ground_check.hide()

            self.osr_label.hide()
            self.osr_combo.hide()
            self.conv_speed_label.hide()
            self.conv_speed_combo.hide()
            self.samp_speed_label.hide()
            self.samp_speed_combo.hide()
            self.sample_rate_label.hide()
            self.sample_rate_spin.hide()

            # Reference/gain are ADC-specific and not used by 555 analyzer
            self.vref_label.hide()
            self.vref_combo.hide()
            self.gain_label.hide()
            self.gain_combo.hide()

            if hasattr(self, 'rb_label'):
                self.rb_label.show()
                self.rb_spin.show()
                self.rb_apply_btn.show()
            if hasattr(self, 'rk_label'):
                self.rk_label.show()
                self.rk_spin.show()
                self.rk_apply_btn.show()
            if hasattr(self, 'cf_label'):
                self.cf_label.show()
                self.cf_value_spin.show()
                self.cf_unit_combo.show()
                self.cf_apply_btn.show()
            if hasattr(self, 'rxmax_label'):
                self.rxmax_label.show()
                self.rxmax_spin.show()
                self.rxmax_apply_btn.show()

            if hasattr(self, 'yaxis_units_combo'):
                self.yaxis_units_combo.setCurrentText("Values")
                self.yaxis_units_combo.setEnabled(False)

            if hasattr(self, 'buffer_spin'):
                self.buffer_spin.setRange(1, ANALYZER555_BUFFER_SIZE_MAX)
                if self.buffer_spin.value() > ANALYZER555_BUFFER_SIZE_MAX:
                    self.buffer_spin.setValue(ANALYZER555_BUFFER_SIZE_MAX)

            if hasattr(self, 'charge_time_label'):
                self.charge_time_label.setVisible(True)
            if hasattr(self, 'discharge_time_label'):
                self.discharge_time_label.setVisible(True)

            if is_array_dual:
                self.log_status("Device mode: PZR")
            else:
                self.log_status("Device mode: 555 analyzer")
            return

        # ADC streamer mode
        if hasattr(self, 'ground_pin_label'):
            self.ground_pin_label.show()
        if hasattr(self, 'ground_pin_spin'):
            self.ground_pin_spin.show()
        if hasattr(self, 'use_ground_check'):
            self.use_ground_check.show()

        # OSR/Averaging applies to ADC/PZT modes and must be restored after 555 mode.
        self.osr_label.show()
        self.osr_combo.show()

        if hasattr(self, 'rb_label'):
            self.rb_label.hide()
            self.rb_spin.hide()
            self.rb_apply_btn.hide()
        if hasattr(self, 'rk_label'):
            self.rk_label.hide()
            self.rk_spin.hide()
            self.rk_apply_btn.hide()
        if hasattr(self, 'cf_label'):
            self.cf_label.hide()
            self.cf_value_spin.hide()
            self.cf_unit_combo.hide()
            self.cf_apply_btn.hide()
        if hasattr(self, 'rxmax_label'):
            self.rxmax_label.hide()
            self.rxmax_spin.hide()
            self.rxmax_apply_btn.hide()

        if hasattr(self, 'yaxis_units_combo'):
            self.yaxis_units_combo.setEnabled(True)

        if hasattr(self, 'buffer_spin'):
            self.buffer_spin.setRange(1, BUFFER_SIZE_MAX)

        if hasattr(self, 'charge_time_label'):
            self.charge_time_label.setVisible(False)
        if hasattr(self, 'discharge_time_label'):
            self.discharge_time_label.setVisible(False)
        
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
            # Array MCU sketches use fixed 3.3V reference, so hide Vref control.
            if is_array_mcu:
                self.vref_label.hide()
                self.vref_combo.hide()
            else:
                self.vref_label.show()
                self.vref_combo.show()
            self.gain_label.show()
            self.gain_combo.show()
            
            # Reset OSR options; in array PZT mode default to 4x for better SNR.
            self.osr_label.setText("OSR (Oversampling):")
            self.osr_combo.clear()
            self.osr_combo.addItems(["2", "4", "8"])
            self.osr_combo.setCurrentText("4" if is_array_mcu else "2")
            self.osr_combo.setToolTip("Oversampling ratio: higher = better SNR, lower sample rate")
            
            # Hide Teensy-specific controls
            self.conv_speed_label.hide()
            self.conv_speed_combo.hide()
            self.samp_speed_label.hide()
            self.samp_speed_combo.hide()
            self.sample_rate_label.hide()
            self.sample_rate_spin.hide()

        if is_array_dual:
            self.log_status("Device mode: PZT")
        else:
            self.log_status("Device mode: ADC streamer")

        if hasattr(self, 'update_heatmap_ui_for_mode'):
            self.update_heatmap_ui_for_mode()

        if hasattr(self, 'update_array_acquisition_inputs_visibility'):
            self.update_array_acquisition_inputs_visibility()
