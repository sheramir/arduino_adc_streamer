"""Registry contracts, migration, editable routing and JSON-only board extension."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import shutil

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from config.boards import BoardRegistry, get_board_registry
from config.boards.capture import freeze_owner_context, validate_capture_context, full_scale_volts
from config.boards.settings import BoardPreferences
from config.boards.validation import validate_sensor_layout
from config.testboard_7953_board import default_layout
from config.testboard_acquisition import build_descriptor, validate_descriptor, descriptor_groups


@pytest.fixture
def definitions(tmp_path):
    root = tmp_path / 'boards'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'config/boards', root,
                    ignore=shutil.ignore_patterns('__pycache__', '*.py'))
    return root


def change_profile(root, name, change):
    path = root / 'profiles' / f'{name}.json'
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data), encoding='utf-8')


@pytest.mark.parametrize('name,profile', [
    (' MG24 ', 'mg24'), ('mg24_mux', 'mg24_mux'), ('TEENSY40', 'teensy40_adc'),
    ('Teensy4.1', 'teensy_adc_compat'), ('Teensy555', 'teensy555'),
    ('Array_PZT1', 'array_pzt1'), ('Array_PZT_PZR1', 'array_pzt_pzr1'),
    ('Array_PZT_PZR1.7', 'array_pzt_pzr17'), ('Array_PZT_PZR_v1', 'array_dual_compat'),
    ('PCB_TestBoard_7953', 'testboard_7953'), ('TestBoard_7953', 'testboard_7953'),
    ('new Teensy555 firmware', 'generic_555'), ('Array_unknown', 'generic_array'),
    ('new Teensy hardware', 'teensy_adc_compat'), (None, 'generic_adc'),
])
def test_inventory_and_resolution(name, profile):
    registry = get_board_registry()
    assert registry.resolve(name).id == profile
    for board in registry.profiles.values():
        for mode in board.modes.values():
            assert mode.parameters and mode.resolve_settings().requested


def test_active_mux_firmware_capacity_and_teensy_osr():
    registry = get_board_registry()
    assert registry.resolve('MG24_MUX').hardware['inputs_per_adc'] == 16
    mode = registry.resolve('TEENSY40').mode()
    assert [choice['id'] for choice in mode.parameters['osr'].choices] == [2, 4, 8]
    assert mode.parameters['reference'].definition['policy'] == 'fixed'
    assert mode.full_scale_volts() == 3.3


@pytest.mark.parametrize('edit', [
    lambda d: d.update(schema_version=99),
    lambda d: d['modes']['PZT']['parameters']['spi_clock_hz'].update(default=30000001),
    lambda d: d['modes']['PZT']['parameters']['scan_order'].update(default='unknown'),
    lambda d: d['modes']['PZT']['adapters'].update(protocol='missing'),
    lambda d: d['modes']['PZT']['rules'][0]['force'].update(missing=1),
    lambda d: d.update(mcu_aliases=['MG24']),
])
def test_bad_definitions_fail_startup(definitions, edit):
    change_profile(definitions, 'testboard_7953', edit)
    with pytest.raises(ValueError):
        BoardRegistry(definitions)


def test_requested_effective_rules_and_profile_only_scan(definitions):
    context = BoardRegistry(definitions).context('TestBoard_7953')
    auto = context.mode.resolve_settings({'settling_conversions': 3, 'sequence': 'auto1', 'scan_order': 'invalid'})
    assert auto.requested['settling_conversions'] == 3
    assert auto.effective['settling_conversions'] == 1
    assert not auto.enabled['settling_conversions']
    assert auto.requested['scan_order'] == 'adc'
    manual = context.mode.resolve_settings({**dict(auto.requested), 'vmid_sampling': True})
    assert manual.requested['sequence'] == 'manual' and not manual.enabled['sequence']
    assert manual.effective['settling_conversions'] == 3
    after_vmid = context.mode.resolve_settings({**dict(manual.requested), 'vmid_sampling': False})
    assert after_vmid.requested['sequence'] == 'manual'
    with pytest.raises(TypeError):
        context.profile.hardware['adc_resolution_bits'] = 10
    change_profile(definitions, 'testboard_7953', lambda d: d['modes']['PZT']['parameters']['scan_order'].update(default='interleaved'))
    assert BoardRegistry(definitions).context('TestBoard_7953').mode.resolve_settings().requested['scan_order'] == 'interleaved'


def test_sensor_edits_drive_routes_groups_and_saved_identity(definitions):
    registry = BoardRegistry(definitions)
    layout = default_layout()
    layout['mux_mapping']['PZT6']['channels'] = [4, 3, 2, 1, 0]
    layout['arrays']['1']['adc_lanes'], layout['arrays']['2']['adc_lanes'] = [3, 4], [1, 2]
    validate_sensor_layout(layout, registry.resolve('TestBoard_7953'))
    from config.sensor_config import normalize_combined_sensor_config
    assert normalize_combined_sensor_config(layout)['mux_mapping']['PZT6']['channels'] == [4, 3, 2, 1, 0]
    descriptor = build_descriptor('TestBoard_7953', {'selected_array_sensors': ['PZT6']}, layout,
                                  context=registry.context('TestBoard_7953'))
    first = descriptor['channel_specs'][0]
    assert (first['array_number'], first['placement'], descriptor['ordered_routes'][0]) == (2, 'B', [1, 4])
    assert descriptor_groups(descriptor)[0]['channels'] == [4, 3, 2, 1, 0]
    saved = json.loads(json.dumps(descriptor))
    change_profile(definitions, 'testboard_7953', lambda d: d['modes']['PZT']['parameters']['reference'].update(choices=[dict(id='1', label='1 V', wire_value='1', full_scale_volts=1)], default='1'))
    validate_descriptor(saved, 10)
    legacy = copy.deepcopy(saved)
    legacy.update(version=1)
    legacy.pop('board_context')
    validate_descriptor(legacy, 10)
    invalid = copy.deepcopy(layout)
    invalid['mux_mapping']['PZT6']['channels'][0] = 15
    with pytest.raises(ValueError, match='reserved'):
        validate_sensor_layout(invalid, registry.resolve('TestBoard_7953'))


def test_preferences_are_namespaced_and_fixed_values_win():
    registry = get_board_registry()
    preferences = BoardPreferences()
    mg = registry.context('MG24')
    preferences.save(mg, {'reference': '1.2', 'repeat': 3})
    assert preferences.restore(mg).requested['reference'] == '1.2'
    assert preferences.restore(registry.context('MG24_MUX')).requested['reference'] == 'vdd'
    tb = registry.context('TestBoard_7953')
    preferences.save(tb, {'reference': '5', 'settling_conversions': 3})
    assert preferences.restore(tb).requested['reference'] == '2.5'


def test_explicit_revision_restricts_modes_without_guessing():
    registry = get_board_registry()
    assert registry.context('Array_PZT_PZR1', 'PZT_RS').mode.id == 'PZT_RS'
    assert registry.context('Array_PZT_PZR1', 'PZT', 'pcb1.0').variant == 'pcb1.0'
    with pytest.raises(ValueError, match='explicit variant'):
        registry.context('Array_PZT_PZR1', 'PZT_RS', 'pcb1.0')


def test_saved_array_descriptor_does_not_resolve_installed_board(monkeypatch):
    descriptor = build_descriptor('TestBoard_7953', {'selected_array_sensors': ['PZT6']}, default_layout())
    import config.testboard_7953_board as board_facade
    def unavailable():
        raise AssertionError('Offline interpretation must not load installed profiles')
    monkeypatch.setattr(board_facade, 'get_board_registry', unavailable)
    validate_descriptor(json.loads(json.dumps(descriptor)), 10)
    assert len(descriptor_groups(descriptor)) == 2


@pytest.fixture
def future_registry(definitions):
    profile = json.loads((definitions / 'profiles/mg24.json').read_text())
    profile.update(id='future_adc', mcu_aliases=['FutureADC_16'])
    profile['hardware'].update(adc_resolution_bits=16, inputs_per_adc=32)
    mode = profile['modes']['ADC']
    mode['parameters']['reference'].update(default='external', choices=[dict(id='external', label='4.096 V custom span', wire_value='ext', full_scale_volts=4.096)])
    mode['parameters']['samples_per_channel'].update(maximum=5)
    mode['parameters']['settling_delay'] = dict(type='integer', default=7, minimum=1, maximum=20,
                label='Settling delay', policy='editable', section='adc', command='rate')
    (definitions / 'profiles/future_adc.json').write_text(json.dumps(profile))
    path = definitions / 'registry.json'
    index = json.loads(path.read_text()); index['profiles'].append('profiles/future_adc.json')
    path.write_text(json.dumps(index))
    return BoardRegistry(definitions)


def test_future_board_configures_and_scales_without_name_branches(future_registry, monkeypatch, tmp_path):
    import config.boards.registry as registry_module
    import config.boards
    monkeypatch.setattr(registry_module, 'get_board_registry', lambda: future_registry)
    monkeypatch.setattr(config.boards, 'get_board_registry', lambda: future_registry)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    from adc_gui import ADCStreamerGUI
    from config.adc_configuration_service import ADCConfigurationService
    from data_processing.analysis_workbench import load_exported_csv_snapshot, prepare_analysis_data
    with patch('adc_gui.load_device_config', return_value={'auto_connect': False}):
        gui = ADCStreamerGUI()
    try:
        gui.current_mcu = 'FutureADC_16'; gui.update_gui_for_mcu()
        assert gui.vref_combo.currentData() == 'external'
        assert gui.repeat_spin.maximum() == 5
        extra, _ = gui._board_extra_controls['settling_delay']
        assert extra.maximum() == 20 and extra.value() == 7
        extra.setValue(9)
        gui.channels_input.setText('0,31')
        request = gui._build_adc_configuration_request()
        commands = []
        def send(command, expected):
            commands.append(command)
            return True, expected
        with patch('config.adc_configuration_service.time.sleep'):
            result = ADCConfigurationService(send).send_config_with_verification(request)
        assert result.success and 'ref ext' in commands and 'rate 9' in commands
        assert gui.get_vref_voltage() == 4.096
        freeze_owner_context(gui)
        saved = copy.deepcopy(gui.board_capture_context)
        validate_capture_context(saved)
        gui.raw_data_buffer = np.array([[0, 65535], [65535, 0]], dtype=np.float32)
        gui.sweep_timestamps_buffer = np.array([0, .01])
        gui.samples_per_sweep = 2; gui.sweep_count = 2; gui.buffer_write_index = 2
        gui.current_mcu = 'MG24'; gui.update_gui_for_mcu()
        gui.channels_input.setText('9')
        assert full_scale_volts(gui) == 4.096
        gui.dir_input.setText(str(tmp_path)); gui.filename_input.setText('future')
        with patch('file_operations.data_exporter.QMessageBox.information'), patch('file_operations.data_exporter.QMessageBox.warning') as warning:
            gui.save_data()
            warning.assert_not_called()
        snapshot = load_exported_csv_snapshot(next(tmp_path.glob('future_*.csv')), next(tmp_path.glob('future_*_metadata.json')))
        assert snapshot.metadata['board_context'] == json.loads(json.dumps(saved))
        assert snapshot.data.shape == (2, 2)
        prepared = prepare_analysis_data(snapshot)
        assert max(float(np.max(trace.y)) for trace in prepared.traces) == pytest.approx(4.096)
        gui.set_controls_enabled(False)
        assert not extra.isEnabled()
    finally:
        gui.is_capturing = False
        gui.close(); app.processEvents()


def test_future_sensor_layout_can_have_two_positions(future_registry, monkeypatch):
    import config.boards
    monkeypatch.setattr(config.boards, 'get_board_registry', lambda: future_registry)
    from config.sensor_config import normalize_combined_sensor_config
    layout = dict(name='Two inputs', board_profile='future_adc', array_count=1,
                  arrays={'1': {'adc_lanes': [1]}}, channel_sensor_map=['LEFT', 'RIGHT'],
                  array_layout={'cells': [[None, None, None], [None, 'PZT1', None], [None, None, None]]},
                  mux_mapping={'PZT1': {'mux': 1, 'channels': [31, 0]}}, channel_layout={'channels_per_sensor': 2})
    normalized = normalize_combined_sensor_config(layout)
    assert normalized is not None
    assert normalized['channel_sensor_map'] == ['LEFT', 'RIGHT']
    assert normalized['mux_mapping']['PZT1']['channels'] == [31, 0]
