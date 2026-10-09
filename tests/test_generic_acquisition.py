"""A JSON-only board exercises the shared high-rate GUI with new capacities."""
import copy
import json
from pathlib import Path
import shutil
import threading
import time
from unittest.mock import patch

import numpy as np
import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from config.boards import BoardRegistry, get_board_registry
from config.boards.streaming import streaming_policy
from config.boards.validation import validate_profile
from config.array_acquisition import build_descriptor, validate_descriptor
from config.array_scan import selected_arrays, order_array_routes
from data_processing.acquisition_worker import AcquisitionWorker


@pytest.fixture
def future_board(tmp_path, monkeypatch):
    import config.boards
    import config.boards.registry
    definitions = tmp_path / 'boards'
    shutil.copytree('config/boards', definitions, ignore=shutil.ignore_patterns('__pycache__', '*.py'))
    profile = json.loads(Path('config/boards/profiles/testboard_7953.json').read_text())
    profile.update(id='future_mux', mcu_aliases=['FutureMux'], profile_version=1)
    profile['hardware'].update(adc_resolution_bits=16, adc_lane_count=6, inputs_per_adc=32, max_arrays=3,
                               reserved_inputs={'vmid': 31})
    mode = profile['modes']['PZT']
    mode['emitted_adc_lanes'] = 6
    for parameter in mode['parameters'].values():
        parameter.pop('legacy_key', None)
    mode['parameters']['reference'].update(default='external', choices=[
        dict(id='external', label='4.096 V', wire_value='ext', full_scale_volts=4.096)])
    mode['parameters']['spi_clock_hz']['default'] = 7_000_000
    mode['parameters']['scan_order']['policy'] = 'editable'
    mode['parameters']['array_selection']['choices'] = [
        dict(id=a, label='All arrays' if a == 'both' else f'Array {a}', wire_value=a)
        for a in ('both', '2', '4', '7')]
    (definitions / 'profiles/future_mux.json').write_text(json.dumps(profile))
    index = json.loads((definitions / 'registry.json').read_text())
    index['profiles'].append('profiles/future_mux.json')
    (definitions / 'registry.json').write_text(json.dumps(index))
    registry = BoardRegistry(definitions)
    monkeypatch.setattr(config.boards, 'get_board_registry', lambda: registry)
    monkeypatch.setattr(config.boards.registry, 'get_board_registry', lambda: registry)
    layout = dict(name='Future layout', board_profile='future_mux', array_count=3,
                  arrays={'2': {'adc_lanes': [5, 6]}, '4': {'adc_lanes': [1, 2]}, '7': {'adc_lanes': [3, 4]}},
                  channel_sensor_map=['B', 'L', 'C', 'R', 'T'],
                  mux_mapping={'PZT1': {'mux': 1, 'channels': [10, 11, 12, 13, 14]},
                               'PZT3': {'mux': 2, 'channels': [20, 21, 22, 23, 24]}},
                  channel_layout={'channels_per_sensor': 5},
                  array_layout={'cells': [['PZT1', 'PZT3', None], [None]*3, [None]*3]})
    return registry.context('FutureMux'), layout, profile


@pytest.mark.parametrize('order', ['adc', 'array', 'interleaved'])
@pytest.mark.parametrize('selection', ['both', '2', '4', '7'])
def test_nonstandard_arrays_routes_and_offline_identity(future_board, order, selection):
    context, layout, _ = future_board
    descriptor = build_descriptor('FutureMux', dict(selected_array_sensors=['PZT3', 'PZT1'],
                                  scan_order=order, array_selection=selection), layout, context=context)
    expected_arrays = [2, 4, 7] if selection == 'both' else [int(selection)]
    assert descriptor['sampled_arrays'] == expected_arrays
    assert descriptor['adc_resolution_bits'] == 16 and descriptor['full_scale_volts'] == 4.096
    assert descriptor['spi_clock_hz'] == 7_000_000
    assert len(descriptor['ordered_routes']) == 10 * len(expected_arrays)
    validate_descriptor(json.loads(json.dumps(descriptor)), 10 * len(expected_arrays))
    for spec in descriptor['channel_specs']:
        assert spec['adc_lane'] in layout['arrays'][str(spec['array_number'])]['adc_lanes']
        assert descriptor['ordered_routes'][spec['sample_indices'][0]] == [spec['adc_lane'], spec['key'][3]]
    worker = AcquisitionWorker(descriptor, 1, threading.Lock(), 1000, None)
    assert len(worker._groups) == 2 * len(expected_arrays)
    assert sorted(i for group in worker._groups for i in group) == list(range(worker.width))
    assert selected_arrays(selection, layout) == tuple(expected_arrays)
    with pytest.raises(ValueError):
        selected_arrays('1', layout)
    with pytest.raises(ValueError):
        order_array_routes([(7, 0)], order, layout)


@pytest.mark.parametrize('mutation', [
    lambda m: m['streaming'].update(pipeline='unknown'),
    lambda m: m['streaming'].update(render_interval_ms=0),
    lambda m: m['streaming'].update(render_interval_ms=True),
    lambda m: m['streaming'].update(unknown=1),
    lambda m: m['parameters']['sweeps_per_block'].update(default=2),
    lambda m: m['parameters']['samples_per_channel'].update(policy='editable'),
    lambda m: m['adapters'].update(frame='timer_555'),
])
def test_invalid_streaming_contract_fails_before_capture(future_board, mutation):
    _, _, profile = future_board
    mutation(profile['modes']['PZT'])
    with pytest.raises(ValueError):
        validate_profile(profile)


def test_other_board_modes_keep_established_block_path():
    registry = get_board_registry()
    for board in registry.profiles.values():
        for mode in board.modes.values():
            assert streaming_policy(mode).batched == (board.id == 'testboard_7953')


def test_optional_pcb_profile_is_not_required_for_state_startup(future_board, monkeypatch):
    import config.boards
    from config.adc_config_state import build_default_adc_config_state
    from config.legacy_array_api import legacy_array_default
    from types import SimpleNamespace
    context, _, _ = future_board
    registry = config.boards.get_board_registry()
    profiles = {name: value for name, value in registry.profiles.items() if name != 'testboard_7953'}
    monkeypatch.setattr(config.boards, 'get_board_registry', lambda: SimpleNamespace(profiles=profiles))
    state = build_default_adc_config_state()
    assert legacy_array_default('spi_clock_hz') == 0
    state.register_parameters(context.mode)
    state.update(context.mode.legacy_defaults())
    assert state['spi_clock_hz'] == 7_000_000


def test_six_lane_wire_replay_preserves_large_codes_timestamps_and_gaps(future_board, tmp_path):
    from serial_communication.serial_threads import SerialReaderThread
    from data_processing.archive_writer import ArchiveWriterThread
    context, layout, _ = future_board
    descriptor = build_descriptor('FutureMux', {'selected_array_sensors': ['PZT1', 'PZT3']}, layout, context=context)
    archive = tmp_path / 'six_lane.jsonl'
    writer = ArchiveWriterThread(str(archive), {'metadata': {'testboard_acquisition': descriptor}})
    worker = AcquisitionWorker(descriptor, 1, threading.Lock(), 1000, writer)
    width, count = worker.width, 300
    dtype = np.dtype([('magic', 'u1', 2), ('count', '<u2'), ('samples', '<u2', width),
                      ('avg', '<u2'), ('start', '<u4'), ('end', '<u4')])
    frames = np.zeros(count, dtype=dtype)
    frames['magic'] = (0xAA, 0x55); frames['count'] = width; frames['avg'] = 1
    sentinels = np.array([lane * 1000 + channel for lane, channel in descriptor['ordered_routes']])
    frames['samples'] = sentinels + np.arange(count)[:, None] % 16
    starts = 0xFFFFF000 + np.arange(count, dtype=np.int64) * 50
    starts[150:] += 500000
    frames['start'] = starts & 0xFFFFFFFF; frames['end'] = (starts + width - 1) & 0xFFFFFFFF
    reader = SerialReaderThread(None)
    reader.configure_batch_consumer(worker.enqueue, 1)
    reader.set_capturing(True, width)
    data = frames.tobytes()
    writer.start(); worker.start()
    for offset in range(0, len(data), 137):
        reader._chunk_arrival = time.perf_counter()
        reader.binary_buffer.extend(data[offset:offset + 137])
        reader.process_binary_data(reader.binary_buffer)
    reader.set_capturing(False)
    worker.stop_nowait(); worker.join(5)
    writer.stop()
    assert not worker.is_alive() and worker.error is None
    assert worker.count == count and worker.gaps == 1
    assert reader._rejected_packets_total == 0
    recorded = [json.loads(line)['samples'] for line in archive.read_text().splitlines()[1:]]
    np.testing.assert_array_equal(recorded, frames['samples'])
    np.testing.assert_allclose(worker.times[:count], (starts - starts[0]) / 1e6)


def test_json_only_board_gui_configure_capture_archive_and_transition(future_board, tmp_path, monkeypatch):
    from adc_gui import ADCStreamerGUI
    from scripts.benchmark_testboard_gui import ReplayPort
    from serial_communication.serial_threads import SerialReaderThread
    from serial_communication.adc_connection_state import ArduinoStatus
    from config.adc_configuration_service import ADCConfigurationService
    from config.boards.capture import freeze_owner_context
    context, layout, _ = future_board
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(ADCStreamerGUI, '_pzt_decay_qsettings',
                        lambda self: QSettings(str(tmp_path / 'decay.ini'), QSettings.Format.IniFormat))
    monkeypatch.setattr(ADCStreamerGUI, '_pressure_map_workspace_qsettings',
                        lambda self: QSettings(str(tmp_path / 'pressure.ini'), QSettings.Format.IniFormat))
    app = QApplication.instance() or QApplication([])
    with patch('adc_gui.load_device_config', return_value={'auto_connect': False}):
        gui = ADCStreamerGUI()
    try:
        gui.sensor_configurations.append(copy.deepcopy(layout))
        gui.current_mcu = 'FutureMux'
        gui.update_gui_for_mcu()
        gui.pzt_sequence_input.setText('1,3')
        assert gui.active_sensor_config_name == layout['name']
        assert gui.board_spi_clock_spin.value() == 7
        assert gui.display_array_combo.count() == 3 and gui.display_array_id == 2
        gui.sampled_array_combo.setCurrentIndex(gui.sampled_array_combo.findData('7'))
        assert gui.get_array_selection() == '7' and gui.display_array_id == 7
        gui.use_ground_check.setChecked(True)
        gui.repeat_spin.setValue(3)
        request = gui._build_adc_configuration_request()
        assert request.parameters['settling_conversions'] == 3
        assert request.parameters['vmid_sampling'] is True
        assert request.testboard_spi_clock_hz == 7_000_000
        commands = []
        status = ArduinoStatus(reference='external', ground_pin=31, testboard_array='7', testboard_scan_order='adc',
                               testboard_sequence='manual', testboard_spi_clock_hz=7_000_000,
                               testboard_channel_repeat=3, testboard_effective_repeat=3,
                               testboard_vmid=True, testboard_effective_vmid=True,
                               testboard_routes=request.testboard_adc_routes, testboard_route_count=10,
                               testboard_engine='blocking')
        service = ADCConfigurationService(lambda command, ack: (commands.append(command) or True, ack), lambda: status)
        assert service.send_config_with_verification(request).success
        assert 'ref ext' in commands and 'array 7' in commands and 'spiclock 7000000' in commands
        gui.freeze_array_capture_descriptor()
        freeze_owner_context(gui)
        descriptor = copy.deepcopy(gui.array_capture_descriptor)
        width = len(descriptor['ordered_routes'])
        port = ReplayPort(width, 1000, .25)
        reader = SerialReaderThread(port)
        writer_path = tmp_path / 'future.jsonl'
        from data_processing.archive_writer import ArchiveWriterThread
        writer = ArchiveWriterThread(str(writer_path), {'metadata': {'testboard_acquisition': descriptor}})
        gui.serial_thread = reader
        gui._archive_writer = writer
        gui._block_timing_file = None
        gui._capture_generation = 1
        writer.start()
        gui._start_acquisition_pipeline()
        reader.set_capturing(True, width)
        reader.binary_buffer.extend(port.data)
        reader.process_binary_data(reader.binary_buffer)
        reader.set_capturing(False)
        worker = gui._acquisition_worker
        worker.stop_nowait(); worker.join(5)
        gui._acquisition_render_timer.stop()
        writer.stop()
        assert worker.error is None and worker.count == port.count
        records = [json.loads(line) for line in writer_path.read_text().splitlines()]
        assert len(records) == 251
        expected = np.arange(250) / 1000
        np.testing.assert_allclose(worker.times[:250], expected)
        assert gui.testboard_capture_descriptor is gui.array_capture_descriptor
        assert gui._testboard_worker is worker
        # Switch directly between two array boards; captured identities remain fixed.
        gui.current_mcu = 'TestBoard_7953'; gui.update_gui_for_mcu()
        assert gui.active_sensor_config_name == 'TestBoard_7953'
        assert gui.array_capture_descriptor == descriptor
        gui.current_mcu = 'MG24'; gui.update_gui_for_mcu()
        assert not gui.is_multi_array_mode()
    finally:
        gui.is_capturing = False
        gui.close(); app.processEvents()
