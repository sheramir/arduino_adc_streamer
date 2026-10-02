"""Acquisition descriptors and display selection for the TestBoard GUI slice."""
from copy import deepcopy
from config.boards.settings import parameter_values, context_for

from config.testboard_acquisition import build_descriptor, descriptor_specs, descriptor_groups


class TestBoardRuntimeMixin:
    def get_testboard_descriptor(self):
        captured = getattr(self, "testboard_capture_descriptor", None)
        if captured is not None and (getattr(self, "is_capturing", False) or getattr(self, "sweep_count", 0)):
            return captured
        if not self.is_testboard_7953_mode():
            return None
        layout = self.get_active_sensor_configuration() if hasattr(self, "get_active_sensor_configuration") else {}
        if not self.config.get("selected_array_sensors") or not layout.get("board_profile"):
            return None
        config = parameter_values(self.config)
        config["testboard_scan_order"] = self.get_testboard_scan_order()
        from data_processing.acquisition_adapters import acquisition_adapter
        context = context_for(self)
        return acquisition_adapter(context).descriptor(context, config, layout, getattr(self, 'arduino_status', None))

    def get_acquisition_channel_specs(self, channels=None, repeat_count=None):
        descriptor = self.get_testboard_descriptor()
        if descriptor is not None:
            return descriptor_specs(descriptor)
        captured = getattr(self, 'board_capture_context', None)
        if captured and (getattr(self, 'is_capturing', False) or getattr(self, 'sweep_count', 0)) and captured.get('channel_specs'):
            specs = deepcopy(captured['channel_specs'])
            for spec in specs:
                spec['key'] = tuple(spec['key'])
            return specs
        return self._get_all_display_channel_specs(channels, repeat_count)

    def get_display_channel_specs(self, channels=None, repeat_count=None):
        specs = self.get_acquisition_channel_specs(channels, repeat_count)
        descriptor = self.get_testboard_descriptor()
        if descriptor is None:
            return specs
        array = getattr(self, "display_array_id", descriptor["sampled_arrays"][0])
        if array not in descriptor["sampled_arrays"]:
            array = descriptor["sampled_arrays"][0]
        return [s for s in specs if s.get("array_number") == array]

    def get_testboard_package_groups(self, *, visible=False):
        descriptor = self.get_testboard_descriptor()
        if descriptor is None:
            return []
        return descriptor_groups(descriptor, getattr(self, "display_array_id", descriptor["sampled_arrays"][0]) if visible else None)

    def freeze_testboard_capture_descriptor(self):
        # Call before acquisition begins; never derive a new capture from old data.
        self.testboard_capture_descriptor = None
        descriptor = self.get_testboard_descriptor()
        self.testboard_capture_descriptor = deepcopy(descriptor)
        self._force_display_specs_cache = None
        if descriptor:
            self.display_array_id = descriptor["sampled_arrays"][0]
            if hasattr(self, 'plot_widget'):
                self.plot_widget.setTitle(f'Array {self.display_array_id}')
            self.refresh_display_array_control()

    def on_testboard_spi_clock_changed(self, mhz):
        scale = context_for(self).mode.parameters["spi_clock_hz"].definition.get("display_scale", 1)
        self.config["testboard_spi_clock_hz"] = int(round(mhz / scale))
        self.config_is_valid = False
        self.update_start_button_state()

    def on_testboard_sequence_changed(self, sequence):
        self.config["testboard_sequence"] = self.testboard_sequence_combo.currentData() or sequence
        self.refresh_testboard_sequence_controls()
        self.config_is_valid = False
        self.update_start_button_state()

    def on_display_array_changed(self, text):
        if not text:
            return
        array = int(text)
        if array == getattr(self, "display_array_id", None):
            return
        # View-only change: retain device configuration and all computation state.
        self._testboard_channel_choices = getattr(self, "_testboard_channel_choices", {})
        self._testboard_channel_choices.update({key: cb.isChecked() for key, cb in getattr(self, "channel_checkboxes", {}).items()})
        self.display_array_id = array
        for curve in getattr(self, 'spectrum_curves', {}).values():
            curve.setVisible(False)
        if hasattr(self, 'spectrum_display_cache'):
            self.spectrum_display_cache = {'channels': [], 'freqs_show_hz': []}
        if hasattr(self, "_clear_all_plot_curves"):
            self._clear_all_plot_curves()
        if hasattr(self, "update_channel_list"):
            self.update_channel_list()
            for key, cb in self.channel_checkboxes.items():
                cb.setChecked(self._testboard_channel_choices.get(key, True))
        for name in ("refresh_spectrum_package_options", "refresh_pzt_decay_signals", "refresh_force_calibration_sources"):
            if hasattr(self, name):
                getattr(self, name)()
        for name in ("_last_spectrum_signature", "_pressure_map_render_cache_key"):
            if hasattr(self, name):
                setattr(self, name, None)
        if hasattr(self, "plot_widget"):
            self.plot_widget.setTitle(f"Array {array}")
        if hasattr(self, "trigger_plot_update"):
            self.trigger_plot_update()
        for name in ("update_spectrum", "update_signal_integration_plot", "update_heatmap_plot", "_render_pressure_force_display"):
            if hasattr(self, name):
                getattr(self, name)()
        if hasattr(self, 'process_pzt_decay_block'):
            self.process_pzt_decay_block(None, None)
