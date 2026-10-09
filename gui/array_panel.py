"""Multi-array sensor/display components; scalar controls bind board parameters."""
from config.array_scan import selected_arrays
from config.boards.settings import context_for, parameter_values, legacy_updates


class ArrayPanelMixin:
    def apply_array_controls(self, active):
        context = context_for(self)
        was_active = getattr(self, '_array_controls_active', False)
        entering = active and (not was_active or getattr(self, '_array_control_profile_id', None) != context.profile.id)
        if entering:
            if not was_active:
                self._pre_array_config = {k: self.config.get(k) for k in ('reference', 'repeat', 'ground_pin', 'use_ground')}
                self._pre_array_sensor_name = getattr(self, 'active_sensor_config_name', None)
            if hasattr(self.config, 'register_parameters'):
                self.config.register_parameters(context.mode)
            self.config.update(context.mode.legacy_defaults())
            self.config['ground_pin'] = context.profile.hardware['reserved_inputs'].get('vmid')
            from config.boards import resolve_board
            compatible = next((c for c in getattr(self, 'sensor_configurations', [])
                               if c.get('board_profile') and resolve_board(c['board_profile']).id == context.profile.id), None)
            if compatible:
                self.active_sensor_config_name = compatible['name']
                self._refresh_sensor_tab_ui()
                self.display_array_id = min(int(a) for a in compatible['arrays'])
        elif not active and getattr(self, '_array_controls_active', False):
            self.config.update(self._pre_array_config)
            if self._pre_array_sensor_name:
                self.active_sensor_config_name = self._pre_array_sensor_name
                self._refresh_sensor_tab_ui()
        self._array_controls_active = active
        self._array_control_profile_id = context.profile.id if active else None
        if hasattr(self, 'force_calib_family_combo'):
            if active:
                self.force_calib_family_combo.setCurrentText('PZT')
            self.force_calib_family_combo.setEnabled(not active and not self.force_calibration_state.is_capturing)
        # The registry binder runs after MCU presentation; these are specialized view components.
        self.refresh_display_array_control()
        if hasattr(self, 'refresh_pzt_decay_signals'):
            self.refresh_pzt_decay_signals()

    def refresh_array_sequence_controls(self):
        if not getattr(self, '_array_controls_active', False):
            return
        from gui.board_controls import bind_parameter
        context = context_for(self)
        resolved = context.mode.resolve_settings(parameter_values(self.config))
        self.config.update(legacy_updates(context.mode, resolved))
        stopped = not getattr(self, 'is_capturing', False) and getattr(self, '_acquisition_controls_enabled', True)
        for key, widget in (('sequence', self.board_sequence_combo), ('settling_conversions', self.repeat_spin)):
            if key not in context.mode.parameters:
                continue
            bind_parameter(widget, context.mode.parameters[key], resolved.effective[key])
            widget.setEnabled(stopped and resolved.enabled[key])

    def refresh_display_array_control(self):
        captured = getattr(self, "array_capture_descriptor", None)
        active = getattr(self, "_array_controls_active", False) or bool(captured)
        self.display_array_label.setVisible(active)
        self.display_array_combo.setVisible(active)
        if not active:
            return
        layout = self.get_active_sensor_configuration()
        if not layout.get('arrays'):
            self.display_array_combo.setEnabled(False)
            return
        resolved = context_for(self).mode.resolve_settings(parameter_values(self.config))
        arrays = captured["sampled_arrays"] if captured and getattr(self, "sweep_count", 0) else selected_arrays(resolved.requested['array_selection'], layout)
        array = getattr(self, "display_array_id", arrays[0])
        if array not in arrays:
            array = arrays[0]
        self.display_array_id = array
        self.display_array_combo.blockSignals(True)
        self.display_array_combo.clear()
        self.display_array_combo.addItems([str(a) for a in arrays])
        self.display_array_combo.setCurrentText(str(array))
        self.display_array_combo.blockSignals(False)
        self.display_array_combo.setEnabled(len(arrays) > 1)
