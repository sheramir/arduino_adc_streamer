"""Compatibility attribute names; all state lives in the shared runtime."""


def legacy_array_default(key):
    """Defaults for old dataclass fields, never the active acquisition contract.

    Older callers omit these fields. Keep their shipped defaults when available,
    but allow registries without that optional PCB profile to start normally.
    Configuration of an active board always replaces them from its own profile.
    """
    from config.boards import get_board_registry
    profile = get_board_registry().profiles.get('testboard_7953')
    if profile is not None:
        return profile.mode().parameters[key].default
    return {'array_selection': 'both', 'scan_order': 'adc', 'spi_clock_hz': 0,
            'settling_conversions': 1, 'sequence': 'manual'}[key]

def _legacy_attribute(name):
    return property(lambda self: getattr(self, name), lambda self, value: setattr(self, name, value))


class LegacyArrayAPI:
    """Read/write aliases for old extensions and callers; no acquisition logic."""

    _testboard_worker = _legacy_attribute('_acquisition_worker')
    testboard_capture_descriptor = _legacy_attribute('array_capture_descriptor')
    _testboard_acquisition_specs = _legacy_attribute('_array_acquisition_specs')
    get_testboard_descriptor = _legacy_attribute('get_array_descriptor')
    get_testboard_package_groups = _legacy_attribute('get_array_package_groups')
    freeze_testboard_capture_descriptor = _legacy_attribute('freeze_array_capture_descriptor')
    _start_testboard_pipeline = _legacy_attribute('_start_acquisition_pipeline')
    _finish_testboard_pipeline = _legacy_attribute('_finish_acquisition_pipeline')
    _refresh_testboard_live = _legacy_attribute('_refresh_live_acquisition')
    _update_testboard_worker_options = _legacy_attribute('_update_acquisition_worker_options')
    _watch_testboard_archive = _legacy_attribute('_watch_acquisition_archive')
    _testboard_force_active = _legacy_attribute('_acquisition_force_active')
    _testboard_heatmap_processors = _legacy_attribute('_array_heatmap_processors')
    _testboard_cop_history = _legacy_attribute('_array_cop_history')
    is_testboard_7953_mode = _legacy_attribute('is_multi_array_mode')
    get_testboard_array_selection = _legacy_attribute('get_array_selection')
    get_testboard_scan_order = _legacy_attribute('get_array_scan_order')
    get_testboard_adc_routes = _legacy_attribute('get_array_adc_routes')
    get_testboard_adc_routes_text = _legacy_attribute('get_array_adc_routes_text')
    _get_testboard_display_channel_specs = _legacy_attribute('_get_array_display_channel_specs')
    apply_testboard_controls = _legacy_attribute('apply_array_controls')
    refresh_testboard_sequence_controls = _legacy_attribute('refresh_array_sequence_controls')
    on_testboard_spi_clock_changed = _legacy_attribute('on_board_spi_clock_changed')
    on_testboard_sequence_changed = _legacy_attribute('on_board_sequence_changed')
    on_testboard_array_selection_changed = _legacy_attribute('on_array_selection_changed')
    on_testboard_scan_order_changed = _legacy_attribute('on_array_scan_order_changed')
    refresh_testboard_decay_preview = _legacy_attribute('refresh_live_decay_preview')
    _testboard_controls_active = _legacy_attribute('_array_controls_active')
    _pre_testboard_config = _legacy_attribute('_pre_array_config')
    _pre_testboard_sensor_name = _legacy_attribute('_pre_array_sensor_name')
    _testboard_channel_choices = _legacy_attribute('_array_channel_choices')
    _testboard_calibration_array_id = _legacy_attribute('_calibration_array_id')
    testboard_spi_clock_spin = _legacy_attribute('board_spi_clock_spin')
    testboard_spi_clock_label = _legacy_attribute('board_spi_clock_label')
    testboard_sequence_combo = _legacy_attribute('board_sequence_combo')
    testboard_sequence_label = _legacy_attribute('board_sequence_label')
    testboard_array_combo = _legacy_attribute('sampled_array_combo')
    testboard_array_label = _legacy_attribute('sampled_array_label')
    testboard_scan_order_combo = _legacy_attribute('array_scan_order_combo')
    testboard_scan_order_label = _legacy_attribute('array_scan_order_label')
