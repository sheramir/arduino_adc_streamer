"""Compatibility presentation facade over the board registry.

Existing mixins consume these properties; the values have one owner in JSON.
"""
from dataclasses import dataclass
from config.boards import resolve_board


@dataclass(frozen=True, slots=True)
class MCUProfile:
    mcu_name: str
    board: object
    mode: object

    def __getattr__(self, key):
        features = self.mode.definition['features']
        if key in features:
            return features[key]
        raise AttributeError(key)

    @property
    def array_operation_modes(self):
        return tuple(self.board.modes) if self.is_array_mcu else ('PZT', 'PZR')

    @property
    def device_mode(self):
        return self.mode.definition['device_mode']

    @property
    def is_555_mode(self):
        return self.device_mode == '555'

    @property
    def is_array_mcu(self):
        return self.mode.definition['adapters']['acquisition'] != 'channels'

    @property
    def is_array_dual(self):
        return self.is_array_mcu and len(self.board.modes) > 1

    @property
    def is_testboard_7953(self):
        return self.mode.definition['adapters']['acquisition'] == 'multi_array'

    @property
    def adc_lane_count(self):
        return self.mode.definition['emitted_adc_lanes']

    @property
    def is_array_pzt1(self):
        return self.is_array_mcu and not self.is_555_mode and self.adc_lane_count > 1

    @property
    def is_pzt_rs_mode(self):
        return self.mode.definition['adapters']['acquisition'] == 'array_combined'

    @property
    def supports_pzt_rs(self):
        return any(m.definition['adapters']['acquisition'] == 'array_combined' for m in self.board.modes.values())

    @property
    def show_testboard_scan_controls(self):
        return self.is_testboard_7953

    @property
    def show_repeat_buffer_controls(self):
        return self._editable('samples_per_channel') and self._editable('sweeps_per_block')

    @property
    def show_adc_config_section(self):
        return any(p.definition.get('section') == 'adc' and p.definition.get('policy') == 'editable'
                   for p in self.mode.parameters.values())

    @property
    def show_555_controls(self):
        return self._editable('rb_ohms')

    @property
    def buffer_size_max(self):
        return self.mode.parameters['sweeps_per_block'].definition['maximum']

    @property
    def osr_options(self):
        p = self.mode.parameters.get('osr')
        return tuple(str(c['id']) for c in p.choices) if p else ('2', '4', '8')

    @property
    def osr_default(self):
        p = self.mode.parameters.get('osr')
        return str(p.default) if p else '2'

    @property
    def osr_label_text(self):
        p = self.mode.parameters.get('osr')
        return p.label if p else 'OSR (Oversampling):'

    @property
    def osr_tooltip(self):
        p = self.mode.parameters.get('osr')
        return p.definition.get('tooltip', '') if p else 'Oversampling ratio: higher = better SNR, lower sample rate'

    def _editable(self, key):
        p = self.mode.parameters.get(key)
        return p is not None and p.definition.get('policy') == 'editable'

    @property
    def show_reference_control(self):
        return self._editable('reference')

    @property
    def show_gain_control(self):
        return self._editable('gain')

    @property
    def osr_visible(self):
        return self._editable('osr')

    @property
    def show_ground_controls(self):
        return self._editable('ground_sampling') or self._editable('vmid_sampling')

    @property
    def show_teensy_controls(self):
        return self._editable('conversion_speed')

    @property
    def show_repeat_control(self):
        return self._editable('samples_per_channel') or self._editable('settling_conversions')

    @property
    def show_buffer_control(self):
        return self._editable('sweeps_per_block')

    @property
    def show_spi_clock_control(self):
        return self._editable('spi_clock_hz')

    @property
    def show_sequence_control(self):
        return self._editable('sequence')

    @property
    def show_display_array_control(self):
        return self.board.hardware['max_arrays'] > 1

    @property
    def show_ground_pin_control(self):
        return 'ground_pin' in self.mode.parameters and self.show_ground_controls

    @property
    def reference_choices(self):
        p = self.mode.parameters.get('reference')
        return tuple(c['label'] for c in p.choices) if p else ()

    @property
    def repeat_maximum(self):
        key = 'settling_conversions' if 'settling_conversions' in self.mode.parameters else 'samples_per_channel'
        return self.mode.parameters[key].definition['maximum']


def resolve_mcu_profile(mcu_name=None, *, selected_array_mode='PZT'):
    board = resolve_board(mcu_name)
    return MCUProfile((mcu_name or '').strip(), board, board.mode(selected_array_mode))
