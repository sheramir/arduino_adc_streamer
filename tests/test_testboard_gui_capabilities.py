"""Physical-route, protocol and runtime-view regressions for the ADS7953 board."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from config.adc_configuration_service import ADCConfigurationRequest, ADCConfigurationService
from config.mcu_profile import resolve_mcu_profile
from config.sensor_config import normalize_combined_sensor_config, SensorConfigStore
from config.testboard_acquisition import build_descriptor, descriptor_specs, normalize_settings
from config.testboard_7953_board import PZT_SENSOR_ROUTES
from serial_communication.adc_connection_state import ArduinoStatus
from serial_communication.testboard_status import apply_testboard_status_line


@pytest.fixture
def layout():
    data = json.loads((Path(__file__).resolve().parents[1] / 'sensors_library/sensor_configurations.json').read_text())
    return next(c for c in data['configurations'] if c['name'] == 'TestBoard_7953')


def config(selection='both', order='adc', sequence='manual', repeat=1):
    return dict(selected_array_sensors=['PZT3', 'PZT6'], testboard_array_selection=selection,
                testboard_scan_order=order, testboard_sequence=sequence, testboard_channel_repeat=repeat,
                testboard_spi_clock_hz=20_000_000, reference='2.5', use_ground=False)


@pytest.mark.parametrize('name', ['TestBoard_7953', 'PCB_TestBoard_7953', ' testboard_7953 '])
def test_board_aliases_and_capabilities(name):
    profile = resolve_mcu_profile(name, selected_array_mode='PZR')
    assert profile.is_testboard_7953 and profile.is_array_mcu
    assert profile.array_operation_modes == ('PZT',)
    assert profile.show_reference_control and profile.show_adc_config_section
    assert not profile.show_gain_control and not profile.osr_visible
    assert not profile.show_manual_channels


@pytest.mark.parametrize('arrays', ['1', '2', 'both'])
@pytest.mark.parametrize('order', ['adc', 'array', 'interleaved'])
@pytest.mark.parametrize('sequence,repeat', [('manual', 1), ('manual', 3), ('auto1', 2)])
def test_payload_identity_across_arrays_orders_and_settling(layout, arrays, order, sequence, repeat):
    descriptor = build_descriptor('TestBoard_7953', config(arrays, order, sequence, repeat), layout)
    specs = descriptor_specs(descriptor)
    assert len(specs) == (20 if arrays == 'both' else 10)
    assert descriptor['channelrepeat_effective'] == (1 if sequence == 'auto1' else repeat)
    # Unique sentinel values expose input-number or sensor-number collisions.
    payload = [lane * 100 + channel for lane, channel in descriptor['ordered_routes']]
    for spec in specs:
        route = PZT_SENSOR_ROUTES[spec['sensor_id']]
        channel = route.channels[('B', 'L', 'C', 'R', 'T').index(spec['placement'])]
        lane = layout['arrays'][str(spec['array_number'])]['adc_lanes'][route.adc_position - 1]
        assert payload[spec['sample_indices'][0]] == lane * 100 + channel
    assert len({s['key'] for s in specs}) == len(specs)
    assert {s['sample_indices'][0] for s in specs} == set(range(len(specs)))


def request(**changes):
    values = dict(current_mcu='TestBoard_7953', device_mode='adc', channels=[0,1,2,3,4],
                  channels_to_send=[0,1,2,3,4], repeat=1, use_ground=False, ground_pin=15,
                  buffer_size=1, reference='2.5', osr=2, gain=1, conv_speed='med', samp_speed='med',
                  sample_rate=0, rb_ohms=470, rk_ohms=470, cf_farads=22e-9, rxmax_ohms=65500,
                  array_operation_mode='PZT', pzt_muxes_to_send=[], rs_channels_to_send=[],
                  is_array_mcu=True, is_array_pzt_pzr_mode=False, is_array_sensor_selection_mode=True,
                  effective_channel_multiplier=4, testboard_array_selection='both', testboard_scan_order='adc',
                  testboard_adc_routes=[(1,0),(3,0)], is_testboard_7953=True)
    values.update(changes)
    return ADCConfigurationRequest(**values)


def reported_status(**changes):
    status = ArduinoStatus(reference='2.5', ground_pin=15, testboard_array='both', testboard_scan_order='adc',
                           testboard_sequence='manual', testboard_spi_clock_hz=20_000_000,
                           testboard_channel_repeat=1, testboard_effective_repeat=1,
                           testboard_vmid=False, testboard_effective_vmid=False,
                           testboard_routes=[(1,0),(3,0)], testboard_route_count=2, testboard_engine='blocking')
    for key,value in changes.items(): setattr(status,key,value)
    return status


def test_bare_ack_configuration_requires_actual_status():
    commands = []
    send = lambda command, expected: (commands.append((command,expected)) or (True,None))
    assert not ADCConfigurationService(send).send_config_with_verification(request()).success
    commands.clear()
    service = ADCConfigurationService(send, lambda: reported_status())
    assert service.send_config_with_verification(request()).success
    assert [c for c,_ in commands] == ['mode PZT','ref 2.5','spiclock 20000000','array both','scanorder adc',
                                     'adcchannels 1:0,3:0','channelrepeat 1','vmid false','adcseq manual']
    assert all(expected is None for _,expected in commands)
    service._read_testboard_status = lambda: reported_status(testboard_spi_clock_hz=30_000_000)
    assert not service.send_config_with_verification(request()).success


def test_configuration_aborts_on_first_failed_command():
    commands=[]
    def send(command,_expected):
        commands.append(command)
        return command != 'ref 2.5', None
    result = ADCConfigurationService(send, lambda: reported_status()).send_config_with_verification(request())
    assert not result.success
    assert commands == ['mode PZT','ref 2.5']


def test_status_routes_and_reference_are_decoded_without_colon_confusion():
    status=ArduinoStatus()
    assert apply_testboard_status_line(status,'# adcchannels=2:0,4:0,2:10,4:10')
    assert status.testboard_routes == [(2,0),(4,0),(2,10),(4,10)]
    assert apply_testboard_status_line(status,'# vref=5.0') and status.reference=='5'
    assert not apply_testboard_status_line(status,'# adcchannels=2:15')


@pytest.mark.parametrize('clock', [100_000,20_000_000,30_000_000])
def test_clock_bounds_and_vmid_sequence_constraint(clock):
    assert normalize_settings('5',clock,3,'auto1',True)==('5',clock,3,'manual',True)


@pytest.mark.parametrize('values', [('vdd',20_000_000,1,'manual',False),('2.5',30_000_001,1,'manual',False),
                                   ('2.5',99_999,1,'manual',False),('2.5',20_000_000,4,'manual',False)])
def test_invalid_settings(values):
    with pytest.raises(ValueError): normalize_settings(*values)


def test_schema_round_trip_and_wiring_rejection(layout,tmp_path):
    normalized=normalize_combined_sensor_config(layout)
    assert normalized['arrays']==layout['arrays'] and normalized['array_count']==2
    bundled=tmp_path/'bundled.json'
    bundled.write_text(json.dumps({'version':2,'configurations':[layout]}))
    store=SensorConfigStore(tmp_path/'user.json',bundled)
    configs,_=store.load()
    store.save(configs,'TestBoard_7953')
    loaded,selected=store.load()
    assert selected=='TestBoard_7953' and loaded[0]['array_count']==2
    invalid=copy.deepcopy(layout); invalid['mux_mapping']['PZT6']['mux']=2
    assert normalize_combined_sensor_config(invalid) is None
    invalid=copy.deepcopy(layout); invalid['arrays']['2']['adc_lanes']=[1,2]
    assert normalize_combined_sensor_config(invalid) is None


@pytest.fixture
def gui(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    # Settings writes and startup connection are isolated from the real user.
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    with patch('adc_gui.load_device_config',return_value={'auto_connect':False}):
        from adc_gui import ADCStreamerGUI
        window=ADCStreamerGUI()
    window.current_mcu='TestBoard_7953'; window.update_gui_for_mcu()
    window.pzt_sequence_input.setText('6,1')
    yield window
    window.is_capturing=False
    window.close(); app.processEvents()


def test_gui_constraints_board_transition_and_default_controls(gui):
    assert gui.vref_combo.currentText()=='2.5 V'
    assert gui.testboard_spi_clock_spin.value()==20
    assert gui.repeat_spin.maximum()==3 and gui.repeat_spin.value()==1
    assert gui.buffer_spin.isHidden() and gui.channels_input.isHidden() and gui.ground_pin_spin.isHidden()
    gui.repeat_spin.setValue(3)
    gui.testboard_sequence_combo.setCurrentText('auto1')
    assert gui.config['repeat']==1 and gui.config['testboard_channel_repeat']==3
    assert gui.repeat_spin.value()==1 and not gui.repeat_spin.isEnabled()
    gui.use_ground_check.setChecked(True)
    assert gui.testboard_sequence_combo.currentText()=='manual' and not gui.testboard_sequence_combo.isEnabled()
    assert gui.repeat_spin.value()==3
    assert gui._build_adc_configuration_request().ground_pin==15
    gui.current_mcu='MG24'; gui.update_gui_for_mcu()
    assert gui.repeat_spin.maximum()==16 and gui.vref_combo.currentText()=='3.3V (VDD)'
    assert gui.testboard_sequence_combo.isHidden() and not gui.buffer_spin.isHidden()


def test_switching_display_keeps_capture_descriptor_buffer_and_validity(gui):
    gui._build_adc_configuration_request()
    gui.freeze_testboard_capture_descriptor()
    all_specs=gui.get_acquisition_channel_specs()
    gui.raw_data_buffer=np.arange(40,dtype=np.float32).reshape(2,20)
    gui.samples_per_sweep=20; gui.sweep_count=2; gui.buffer_write_index=2
    gui.sweep_timestamps_buffer=np.array([0.,.01])
    gui.config_is_valid=True
    gui.is_capturing=True; gui.set_controls_enabled(False)
    descriptor=copy.deepcopy(gui.testboard_capture_descriptor)
    original=gui.raw_data_buffer.copy()
    with patch.object(gui,'send_command') as send:
        gui.display_array_combo.setCurrentText('2')
        assert all(s['array_number']==2 for s in gui.get_display_channel_specs())
        assert gui.config_is_valid and gui.is_capturing
        assert gui.display_array_combo.isEnabled() and not gui.testboard_sequence_combo.isEnabled()
        send.assert_not_called()
    assert gui.testboard_capture_descriptor==descriptor
    assert gui.get_acquisition_channel_specs()==all_specs
    np.testing.assert_array_equal(gui.raw_data_buffer,original)
    assert {s['sample_indices'][0] for s in gui.get_display_channel_specs()}==set(range(10,20))
    gui.is_capturing=False


def test_single_array_two_locks_display_to_two(gui):
    gui.testboard_array_combo.setCurrentText('Array 2')
    assert gui.display_array_id==2 and not gui.display_array_combo.isEnabled()
    assert len(gui.get_acquisition_channel_specs())==10
    assert all(s['array_number']==2 for s in gui.get_display_channel_specs())


@pytest.mark.parametrize('display_array', ['1', '2'])
def test_export_reload_preserves_both_arrays_after_disconnect(gui, tmp_path, display_array):
    from data_processing.analysis_workbench import load_exported_csv_snapshot, build_overlay_traces
    gui.vref_combo.setCurrentText('5 V')
    gui._build_adc_configuration_request()
    gui.freeze_testboard_capture_descriptor()
    descriptor = copy.deepcopy(gui.testboard_capture_descriptor)
    payload = np.array([lane * 100 + channel for lane, channel in descriptor['ordered_routes']], dtype=np.float32)
    gui.raw_data_buffer = np.tile(payload, (32, 1))
    gui.sweep_timestamps_buffer = np.arange(32) * .01
    gui.samples_per_sweep = 20; gui.sweep_count = 32; gui.buffer_write_index = 32
    gui.display_array_combo.setCurrentText(display_array)
    gui.current_mcu = 'Unknown'; gui.update_gui_for_mcu()
    gui.dir_input.setText(str(tmp_path)); gui.filename_input.setText('two_arrays')
    with patch('file_operations.data_exporter.QMessageBox.information'), patch('file_operations.data_exporter.QMessageBox.warning') as warning:
        gui.save_data()
        warning.assert_not_called()
    csv_path = next(tmp_path.glob('two_arrays_*.csv'))
    metadata_path = next(tmp_path.glob('two_arrays_*_metadata.json'))
    snapshot = load_exported_csv_snapshot(csv_path, metadata_path)
    assert snapshot.metadata['testboard_acquisition'] == json.loads(json.dumps(descriptor))
    assert snapshot.metadata['configuration']['voltage_reference'] == '5'
    assert snapshot.channel_labels == [s['label'] for s in descriptor['channel_specs']]
    np.testing.assert_array_equal(snapshot.data[0], payload)
    assert snapshot.data.shape == (32, 20)
    overlays = build_overlay_traces(snapshot, snapshot.data, axis_mode='time_ms',
        overlay_flags={'shear': True, 'normal': True}, vref_voltage=5,
        integration_window_samples=10, hpf_cutoff_hz=0)
    assert {t.label.split()[0] for t in overlays} == {'A1_PZT6', 'A1_PZT1', 'A2_PZT6', 'A2_PZT1'}
    assert gui._get_display_package_positions(2)[0] == [(1, 1), (1, 0)]


def test_full_population_and_saved_descriptor_validation(layout):
    from config.testboard_acquisition import validate_descriptor
    settings = config(); settings['selected_array_sensors'] = list(PZT_SENSOR_ROUTES)
    descriptor = build_descriptor('TestBoard_7953', settings, layout)
    assert len(descriptor['ordered_routes']) == 50
    validate_descriptor(json.loads(json.dumps(descriptor)), 50)
    damaged = copy.deepcopy(descriptor); damaged['channel_specs'][0]['sample_indices'] = [49]
    with pytest.raises(ValueError, match='identity'): validate_descriptor(damaged)
    with pytest.raises(ValueError, match='width'): validate_descriptor(descriptor, 25)


def test_heatmap_processes_both_arrays_in_selected_pzt_order(gui):
    from data_processing.heatmap_signal_processing import HeatmapSignalProcessor
    gui._build_adc_configuration_request(); gui.freeze_testboard_capture_descriptor()
    payload = np.array([lane * 100 + channel for lane, channel in gui.testboard_capture_descriptor['ordered_routes']])
    data = payload[None, :] * np.arange(10)[:, None]; times = np.arange(10) * .01
    settings = dict(dc_removal_mode='none', smooth_alpha=1, hpf_cutoff_hz=0)
    first = gui._compute_channel_intensities_from_display_specs(settings, data, times, 500)
    processors = dict(gui._testboard_heatmap_processors)
    assert set(processors) == {'A1_PZT6', 'A1_PZT1', 'A2_PZT6', 'A2_PZT1'}
    assert len(first) == 2 and first[0][0] < first[1][0]
    gui.display_array_id = 2
    second = gui._compute_channel_intensities_from_display_specs(settings, data, times, 500)
    assert len(second) == 2 and second[0][0] > first[0][0]
    assert gui._testboard_heatmap_processors == processors
    assert all(isinstance(p, HeatmapSignalProcessor) for p in processors.values())
    assert gui._get_heatmap_baseline_key_for_display_spec(gui.get_display_channel_specs()[0]) != gui._get_heatmap_baseline_key_for_display_spec(gui.get_acquisition_channel_specs()[0])


def test_calibration_target_stays_on_start_array_and_round_trips(gui, tmp_path):
    gui._build_adc_configuration_request(); gui.freeze_testboard_capture_descriptor()
    gui._start_force_calibration_measurement()
    row = gui.force_calibration_state.pzt_calibration_rows[-1]
    assert (row.array_number, row.sensor_id) == (1, 'PZT6')
    gui.display_array_combo.setCurrentText('2')
    assert {s['array_number'] for s in gui._force_calibration_channel_specs()} == {1}
    path = tmp_path / 'calibration.json'
    gui.save_force_calibration_to_path(path, log_message=False)
    gui.force_calibration_state.is_capturing = False
    gui.load_force_calibration_from_path(path, log_message=False)
    restored = gui.force_calibration_state.pzt_calibration_rows[-1]
    assert (restored.array_number, restored.sensor_id) == (1, 'PZT6')


def test_saved_scan_order_cannot_override_profile_only_setting(gui):
    gui.config['testboard_scan_order'] = 'invalid'
    assert gui._build_adc_configuration_request().testboard_scan_order == 'adc'


@pytest.mark.parametrize('complete', [True, False])
def test_status_session_requires_complete_firmware_transcript(complete):
    from serial_communication.adc_session import ADCSessionController
    session = ADCSessionController(lambda _: None, lambda *args: None, lambda _: None)
    transcript = ['# unrelated startup text', '# -------- STATUS (PZT/ADS7953) --------',
        '# adcchannels=1:0,3:0', '# array=both', '# scanorder=adc', '# adcseq=manual',
        '# spiengine=blocking', '# spi_clock_hz=20000000', '# channelrepeat_requested=1',
        '# channelrepeat_effective=1', '# vmid_channel=15', '# vmid_between_channels_requested=false',
        '# vmid_between_channels_effective=false', '# route_count=2', '# vref=2.5']
    if complete: transcript.append('# --------------------------------------')
    session.serial_port = SimpleNamespace(is_open=True, write=lambda _: [session.handle_text_line(line) for line in transcript], flush=lambda: None)
    status = session.read_testboard_status(timeout=.05)
    assert (status is not None) == complete
    if status:
        assert status.testboard_routes == [(1,0),(3,0)]
        assert status.testboard_spi_clock_hz == 20_000_000


def test_delayed_spectrum_result_cannot_overwrite_other_array(gui):
    gui._build_adc_configuration_request(); gui.freeze_testboard_capture_descriptor()
    gui.display_array_id = 2
    stale = dict(status='ok', channels=[dict(label='A1_PZT6_B')])
    with patch.object(gui, 'update_spectrum') as refresh, patch.object(gui, 'update_spectrum_display') as render:
        gui.on_spectrum_worker_result(stale)
        render.assert_not_called(); refresh.assert_called_once()
    assert not gui.spectrum_busy
