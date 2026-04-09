"""
MCU Detection Mixin
===================
Detects MCU type and adapts GUI controls accordingly.
"""

from config.mcu_profile import resolve_mcu_profile
from config.mcu_state import (
    build_detected_mcu_state,
    build_unknown_mcu_state,
)
from config.mcu_view_state import build_mcu_view_state
from config_constants import MCU_DETECTION_TIMEOUT_SEC


class MCUDetectorMixin:
    """Mixin class for MCU detection and GUI adaptation."""

    def is_555_analyzer_mode(self) -> bool:
        return getattr(self, 'device_mode', 'adc') == '555'

    def _apply_mcu_state(self, state):
        self.current_mcu = state.current_mcu
        self.mcu_label.setText(state.label_text)
        if state.device_mode is not None:
            self.device_mode = state.device_mode
        if state.log_message:
            self.log_status(state.log_message)
    
    def detect_mcu(self):
        """Detect MCU type by sending 'mcu' and waiting on routed ADC text lines."""
        session = getattr(self, "adc_session", None)
        if session is None or not self.serial_port or not self.serial_port.is_open:
            return
        
        try:
            mcu_name = session.detect_mcu(MCU_DETECTION_TIMEOUT_SEC)
            if mcu_name:
                self._apply_mcu_state(build_detected_mcu_state(mcu_name))
                return
            
            # Timeout or no response - use generic behavior
            self._apply_mcu_state(build_unknown_mcu_state())
            
        except Exception as e:
            self.log_status(f"MCU detection failed: {e}")
            self._apply_mcu_state(build_unknown_mcu_state())

    def _apply_mcu_view_state(self, view_state):
        if hasattr(self, 'ground_pin_label'):
            self.ground_pin_label.setVisible(view_state.show_ground_controls)
        if hasattr(self, 'ground_pin_spin'):
            self.ground_pin_spin.setVisible(view_state.show_ground_controls)
        if hasattr(self, 'use_ground_check'):
            self.use_ground_check.setVisible(view_state.show_ground_controls)

        self.osr_label.setVisible(view_state.osr_visible)
        self.osr_combo.setVisible(view_state.osr_visible)
        self.osr_label.setText(view_state.osr_label_text)
        self.osr_combo.clear()
        self.osr_combo.addItems(list(view_state.osr_options))
        self.osr_combo.setCurrentText(view_state.osr_default)
        self.osr_combo.setToolTip(view_state.osr_tooltip)

        if hasattr(self, 'rb_label'):
            self.rb_label.setVisible(view_state.show_555_controls)
            self.rb_spin.setVisible(view_state.show_555_controls)
            self.rb_apply_btn.setVisible(view_state.show_555_controls)
        if hasattr(self, 'rk_label'):
            self.rk_label.setVisible(view_state.show_555_controls)
            self.rk_spin.setVisible(view_state.show_555_controls)
            self.rk_apply_btn.setVisible(view_state.show_555_controls)
        if hasattr(self, 'cf_label'):
            self.cf_label.setVisible(view_state.show_555_controls)
            self.cf_value_spin.setVisible(view_state.show_555_controls)
            self.cf_unit_combo.setVisible(view_state.show_555_controls)
            self.cf_apply_btn.setVisible(view_state.show_555_controls)
        if hasattr(self, 'rxmax_label'):
            self.rxmax_label.setVisible(view_state.show_555_controls)
            self.rxmax_spin.setVisible(view_state.show_555_controls)
            self.rxmax_apply_btn.setVisible(view_state.show_555_controls)

        if hasattr(self, 'yaxis_units_combo'):
            if view_state.yaxis_units_value is not None:
                self.yaxis_units_combo.setCurrentText(view_state.yaxis_units_value)
            self.yaxis_units_combo.setEnabled(not view_state.yaxis_units_locked)

        if hasattr(self, 'buffer_spin'):
            self.buffer_spin.setRange(1, view_state.buffer_size_max)
            if self.buffer_spin.value() > view_state.buffer_size_max:
                self.buffer_spin.setValue(view_state.buffer_size_max)

        if hasattr(self, 'charge_time_label'):
            self.charge_time_label.setVisible(view_state.show_charge_discharge_labels)
        if hasattr(self, 'discharge_time_label'):
            self.discharge_time_label.setVisible(view_state.show_charge_discharge_labels)

        self.vref_label.setVisible(view_state.show_reference_control)
        self.vref_combo.setVisible(view_state.show_reference_control)
        self.gain_label.setVisible(view_state.show_gain_control)
        self.gain_combo.setVisible(view_state.show_gain_control)

        self.conv_speed_label.setVisible(view_state.show_teensy_controls)
        self.conv_speed_combo.setVisible(view_state.show_teensy_controls)
        self.samp_speed_label.setVisible(view_state.show_teensy_controls)
        self.samp_speed_combo.setVisible(view_state.show_teensy_controls)
        self.sample_rate_label.setVisible(view_state.show_teensy_controls)
        self.sample_rate_spin.setVisible(view_state.show_teensy_controls)

        self.log_status(f"Device mode: {view_state.device_mode_log_label}")

    def update_gui_for_mcu(self):
        """Update GUI controls based on detected MCU type."""
        selected_mode = "PZT"
        if hasattr(self, 'get_selected_array_operation_mode'):
            selected_mode = self.get_selected_array_operation_mode()
        profile = resolve_mcu_profile(self.current_mcu, selected_array_mode=selected_mode)
        view_state = build_mcu_view_state(profile)
        self.device_mode = profile.device_mode

        if profile.is_array_dual and hasattr(self, 'config'):
            self.config['array_operation_mode'] = selected_mode

        if hasattr(self, 'update_heatmap_ui_for_mode'):
            self.update_heatmap_ui_for_mode()

        if hasattr(self, 'update_array_acquisition_inputs_visibility'):
            self.update_array_acquisition_inputs_visibility()

        self._apply_mcu_view_state(view_state)

        if hasattr(self, 'update_heatmap_ui_for_mode'):
            self.update_heatmap_ui_for_mode()

        if hasattr(self, 'update_array_acquisition_inputs_visibility'):
            self.update_array_acquisition_inputs_visibility()
