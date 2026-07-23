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
from constants.defaults_555 import (
    ANALYZER555_DEFAULT_RXMAX_OHMS,
)
from constants.serial import MCU_DETECTION_TIMEOUT_SEC


class MCUDetectorMixin:
    """Mixin class for MCU detection and GUI adaptation."""

    @staticmethod
    def _get_locked_ground_pin_for_mcu_name(mcu_name: str | None) -> int | None:
        normalized_name = (mcu_name or "").strip().lower()
        if normalized_name == "array_pzt_pzr1":
            return 10
        if normalized_name == "array_pzt_pzr1.7":
            return 15
        return None

    @classmethod
    def _is_ground_default_mcu_name(cls, mcu_name: str | None) -> bool:
        return cls._get_locked_ground_pin_for_mcu_name(mcu_name) is not None

    def is_555_analyzer_mode(self) -> bool:
        return getattr(self, 'device_mode', 'adc') == '555'

    def _maybe_apply_pzt_rs_tuning_defaults(self, profile) -> None:
        if not getattr(profile, "is_pzt_rs_mode", False):
            return
        if not hasattr(self, "config"):
            return
        if not hasattr(self, "uses_generic_555_tuning_defaults"):
            return
        if not self.uses_generic_555_tuning_defaults():
            return

        self.config['rb_ohms'] = 470.0
        self.config['rk_ohms'] = 470.0
        self.config['cf_farads'] = 220e-9
        self.config['rxmax_ohms'] = ANALYZER555_DEFAULT_RXMAX_OHMS

        if hasattr(self, 'rb_spin'):
            self.rb_spin.blockSignals(True)
            self.rb_spin.setValue(470.0)
            self.rb_spin.blockSignals(False)
        if hasattr(self, 'rk_spin'):
            self.rk_spin.blockSignals(True)
            self.rk_spin.setValue(470.0)
            self.rk_spin.blockSignals(False)
        if hasattr(self, 'cf_value_spin'):
            self.cf_value_spin.blockSignals(True)
            self.cf_value_spin.setValue(220.0)
            self.cf_value_spin.blockSignals(False)
        if hasattr(self, 'cf_unit_combo'):
            self.cf_unit_combo.blockSignals(True)
            self.cf_unit_combo.setCurrentText("nF")
            self.cf_unit_combo.blockSignals(False)
        if hasattr(self, 'rxmax_spin'):
            self.rxmax_spin.blockSignals(True)
            self.rxmax_spin.setValue(ANALYZER555_DEFAULT_RXMAX_OHMS)
            self.rxmax_spin.blockSignals(False)

        self.log_status("PZT_RS defaults loaded: rb=470Ω, rk=470Ω, cf=220nF, rxmax=65500Ω")

    def _apply_mcu_state(self, state):
        previous_mcu = self.current_mcu
        self.current_mcu = state.current_mcu
        self.mcu_label.setText(state.label_text)
        if state.device_mode is not None:
            self.device_mode = state.device_mode
        if state.log_message:
            self.log_status(state.log_message)

        # Re-arm one-time defaults when MCU identity changes.
        if previous_mcu != self.current_mcu:
            self._array_pzt_pzr1_defaults_applied = False
            if hasattr(self, 'config') and hasattr(self, 'refresh_adc_mux_timing'):
                self.refresh_adc_mux_timing()
    
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

        locked_ground_pin = self._get_locked_ground_pin_for_mcu_name(self.current_mcu)
        is_ground_default_mcu = locked_ground_pin is not None
        if hasattr(self, 'ground_pin_spin'):
            lock_ground_pin = bool(view_state.show_ground_controls and is_ground_default_mcu)
            self.ground_pin_spin.setEnabled(not lock_ground_pin)
            if lock_ground_pin:
                changed_ground_pin = self.ground_pin_spin.value() != locked_ground_pin
                self.ground_pin_spin.blockSignals(True)
                self.ground_pin_spin.setValue(locked_ground_pin)
                self.ground_pin_spin.blockSignals(False)
                if hasattr(self, 'config'):
                    changed_ground_pin = changed_ground_pin or int(self.config.get('ground_pin', -1)) != locked_ground_pin
                    self.config['ground_pin'] = locked_ground_pin
                if changed_ground_pin and hasattr(self, 'update_start_button_state'):
                    self.config_is_valid = False
                    self.update_start_button_state()

        # For Array_PZT_PZR1* boards, default "Use Ground Sample" to on once per MCU
        # selection, but keep it user-editable afterward.
        if (
            is_ground_default_mcu
            and view_state.show_ground_controls
            and hasattr(self, 'use_ground_check')
            and not getattr(self, '_array_pzt_pzr1_defaults_applied', False)
        ):
            changed_use_ground = not self.use_ground_check.isChecked()
            self.use_ground_check.blockSignals(True)
            self.use_ground_check.setChecked(True)
            self.use_ground_check.blockSignals(False)
            if hasattr(self, 'config'):
                changed_use_ground = changed_use_ground or not bool(self.config.get('use_ground', False))
                self.config['use_ground'] = True
            if changed_use_ground and hasattr(self, 'update_start_button_state'):
                self.config_is_valid = False
                self.update_start_button_state()
            self._array_pzt_pzr1_defaults_applied = True

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
        if hasattr(self, 'update_array_mode_options'):
            self.update_array_mode_options()

        selected_mode = "PZT"
        if hasattr(self, 'get_selected_array_operation_mode'):
            selected_mode = self.get_selected_array_operation_mode()
        profile = resolve_mcu_profile(self.current_mcu, selected_array_mode=selected_mode)
        view_state = build_mcu_view_state(profile)
        self.device_mode = profile.device_mode
        self._maybe_apply_pzt_rs_tuning_defaults(profile)

        if profile.is_array_dual and hasattr(self, 'config'):
            self.config['array_operation_mode'] = selected_mode

        if hasattr(self, 'update_heatmap_ui_for_mode'):
            self.update_heatmap_ui_for_mode()

        if hasattr(self, 'update_array_acquisition_inputs_visibility'):
            self.update_array_acquisition_inputs_visibility()

        if hasattr(self, 'update_pzt_rs_timeseries_tabs_visibility'):
            self.update_pzt_rs_timeseries_tabs_visibility()

        if hasattr(self, 'update_pressure_map_timeline_controls'):
            self.update_pressure_map_timeline_controls()

        if hasattr(self, 'refresh_spectrum_filter_availability'):
            self.refresh_spectrum_filter_availability(log_message=False)

        self._apply_mcu_view_state(view_state)

        if hasattr(self, 'update_heatmap_ui_for_mode'):
            self.update_heatmap_ui_for_mode()

        if hasattr(self, 'update_array_acquisition_inputs_visibility'):
            self.update_array_acquisition_inputs_visibility()

        if hasattr(self, 'update_pzt_rs_timeseries_tabs_visibility'):
            self.update_pzt_rs_timeseries_tabs_visibility()

        if hasattr(self, 'update_pressure_map_timeline_controls'):
            self.update_pressure_map_timeline_controls()
