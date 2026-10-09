"""Wire replay through the real decoder, worker and compatible JSONL archive."""
import json
from pathlib import Path
import struct
import threading
import time

import numpy as np
import pytest

from config.testboard_acquisition import build_descriptor
from data_processing.acquisition_queue import AcquisitionQueue, AcquisitionOverrun
from data_processing.acquisition_timing import DeviceTimeline, DeviceRestart, peak_envelope
from data_processing.archive_writer import ArchiveWriterThread
from data_processing.testboard_acquisition_worker import TestBoardAcquisitionWorker as AcquisitionWorker
from serial_communication.serial_threads import SerialReaderThread


def descriptor(width=50, reported=None):
    library = json.loads(Path('sensors_library/sensor_configurations.json').read_text())
    layout = next(c for c in library['configurations'] if c['name'] == 'TestBoard_7953')
    settings = dict(selected_array_sensors=['PZT6', 'PZT7', 'PZT1', 'PZT3', 'PZT5'] if width == 50 else ['PZT6', 'PZT7'],
                    testboard_array_selection='both' if width == 50 else '1', testboard_scan_order='adc',
                    testboard_sequence='manual', testboard_channel_repeat=1, testboard_spi_clock_hz=20_000_000,
                    reference='2.5', use_ground=False)
    return build_descriptor('TestBoard_7953', settings, layout, reported)


def wire_frames(width, count, period_us, *, start=0xFFFFF000, gap_at=None):
    dtype = np.dtype([('magic', 'u1', 2), ('count', '<u2'), ('samples', '<u2', width),
                      ('avg', '<u2'), ('start', '<u4'), ('end', '<u4')])
    frames = np.zeros(count, dtype=dtype)
    frames['magic'] = (0xAA, 0x55)
    frames['count'] = width
    frames['samples'] = (np.arange(count)[:, None] + np.arange(width)) % 4096
    frames['avg'] = 1
    times = start + np.arange(count, dtype=np.int64) * period_us
    if gap_at is not None:
        times[gap_at:] += 500000
    frames['start'] = times & 0xFFFFFFFF
    frames['end'] = (times + width - 1) & 0xFFFFFFFF
    return frames, (times - times[0]) / 1e6


@pytest.mark.parametrize('width,rate', [(50, 12000), (50, 17000), (10, 60000), (50, 20000), (10, 75000)])
def test_replay_counts_order_wrap_gap_partial_ascii_and_archive(tmp_path, width, rate):
    count = 3000
    frames, expected_times = wire_frames(width, count, round(1e6 / rate), gap_at=1500)
    archive = tmp_path / 'capture.jsonl'
    writer = ArchiveWriterThread(str(archive), {'metadata': {'testboard_acquisition': descriptor(width)}})
    worker = AcquisitionWorker(descriptor(width), 1, threading.Lock(), 5000, writer)
    reader = SerialReaderThread(None)
    reader.configure_batch_consumer(worker.enqueue, 1)
    reader.set_capturing(True, width)
    ascii_lines = []
    reader.data_received.connect(ascii_lines.append)
    writer.start()
    worker.start()
    data = b'#O' + b'K\n' + frames.tobytes() + b'#END\n'
    for start in range(0, len(data), 4093):
        reader._chunk_arrival = time.perf_counter()
        reader.binary_buffer.extend(data[start:start + 4093])
        reader.process_binary_data(reader.binary_buffer)
    reader.set_capturing(False)
    worker.stop_nowait()
    worker.join(5)
    writer.stop()
    assert not worker.is_alive() and worker.error is None
    assert worker.count == count and reader._accepted_packets_total == count
    assert reader._rejected_packets_total == 0
    assert ascii_lines == ['#OK', '#END']
    np.testing.assert_allclose(worker.times[:count], expected_times, rtol=0, atol=1e-12)
    records = [json.loads(line) for line in archive.read_text().splitlines()][1:]
    np.testing.assert_array_equal([r['samples'] for r in records], frames['samples'])
    np.testing.assert_allclose([r['timestamp_s'] for r in records], expected_times, rtol=0, atol=1e-12)
    assert worker.gaps == 1


def test_timeline_multiple_rollovers_and_restart():
    timeline = DeviceTimeline()
    extended = []
    absolute = np.arange(20000, dtype=np.int64) * 1_000_000 + 12345
    for values in np.array_split(absolute & 0xFFFFFFFF, 6):
        extended.extend(timeline.extend(values))
    np.testing.assert_allclose(extended, (absolute - absolute[0]) / 1e6)
    with pytest.raises(DeviceRestart):
        timeline.extend([100])
    assert DeviceTimeline().extend([100])[0] == 0


def test_bounded_queues_fail_without_eviction():
    queue = AcquisitionQueue(max_bytes=4)
    queue.put(b'1234', size=4, sweeps=1)
    with pytest.raises(AcquisitionOverrun):
        queue.put(b'5', size=1)
    assert queue.snapshot()['bytes'] == 4
    assert queue.get() == b'1234'


@pytest.mark.parametrize('batch_size', [1, 17, 100, 1500])
def test_median_filter_batch_independence_and_reset_after_gap(batch_size):
    values = np.tile(np.array([10, 11, 4000, 12, 13, 14, 15, 4095, 16, 17], dtype=np.uint16)[:, None], (1, 10))
    starts = 1000 + np.arange(10) * 20
    starts[5:] += 500000
    worker = AcquisitionWorker(descriptor(10), 1, threading.Lock(), 100, None)
    for start in range(0, 10, batch_size):
        end = min(10, start + batch_size)
        worker.process_batch(dict(generation=1, samples=values[start:end], starts=starts[start:end],
            ends=starts[start:end] + 9, avg_us=np.ones(end-start), arrival=time.perf_counter(), decoded=time.perf_counter()))
    worker.finish_pending()
    np.testing.assert_array_equal(worker.raw[:10, 0], [10, 11, 11, 12, 13, 14, 15, 15, 16, 17])
    assert worker.gaps == 1


def test_peak_display_keeps_narrow_extrema_and_gap():
    times = np.arange(2000) * 20e-6
    times[1000:] += 0.5
    values = np.zeros(2000)
    values[333] = 123
    values[777] = -45
    x, y = peak_envelope(times, values, 100)
    assert max(y[np.isfinite(y)]) == 123 and min(y[np.isfinite(y)]) == -45
    assert len(y) <= 110 and np.count_nonzero(np.isnan(y)) == 1
    assert np.all(np.diff(x) >= 0)


def test_peak_envelope_preserves_extrema_in_unequal_length_bins():
    times = np.arange(23) * 59e-6
    values = np.zeros(23)
    values[[4, 10, 16, 22]] = [10, 20, 30, 40]
    values[[1, 6, 12, 18]] = [-10, -20, -30, -40]
    x, y = peak_envelope(times, values, 10, nominal=59e-6)
    retained = [0, 1, 4, 6, 10, 12, 16, 18, 22]
    np.testing.assert_array_equal(x, times[retained])
    np.testing.assert_array_equal(y, values[retained])


def test_archive_budget_rejection_and_final_summary(tmp_path):
    writer = ArchiveWriterThread(str(tmp_path / 'capture.jsonl'), {'metadata': {}}, max_pending_bytes=64)
    assert writer.enqueue(np.array([0.]), np.zeros((1, 10), dtype=np.uint16))
    assert not writer.enqueue(np.array([1.]), np.zeros((1, 50), dtype=np.uint16))
    assert writer.get_status_snapshot()['pending_sweeps'] == 1
    writer.final_summary = {'complete': False, 'generation': 1}
    writer.start()
    writer.stop()
    records = [json.loads(line) for line in (tmp_path / 'capture.jsonl').read_text().splitlines()]
    assert records[-1]['capture_summary']['archive_overruns'] == 1
    assert records[-1]['capture_summary']['archive_written_sweeps'] == 1


def test_generation_rejects_old_data():
    worker = AcquisitionWorker(descriptor(10), 2, threading.Lock(), 100, None)
    with pytest.raises(RuntimeError, match='generation'):
        worker.enqueue({'generation': 1})


def test_preceding_run_counters_do_not_enter_capture_configuration():
    from serial_communication.adc_connection_state import ArduinoStatus
    status = ArduinoStatus(stream_diagnostics={'usb_frames_sent': 123456})
    desc = descriptor(10, status)
    assert 'stream_diagnostics' not in desc['board_context']['reported']
    assert status.stream_diagnostics == {'usb_frames_sent': 123456}


def test_iir_is_batch_independent_and_resets_across_gap():
    from data_processing.adc_filter_engine import build_default_filter_settings
    settings = build_default_filter_settings()
    settings.update(enabled=True, main_type='lowpass', order=2, low_cutoff_hz=1000)
    for notch in settings['notches']:
        notch['enabled'] = False
    rng = np.random.default_rng(7953)
    samples = rng.integers(1900, 2100, (500,10), dtype=np.uint16)
    starts = 1000 + np.cumsum(np.resize([13,14], 500))
    starts[300:] += 500000
    outputs = []
    for size in (1, 17, 100, 500):
        worker = AcquisitionWorker(descriptor(10), 1, threading.Lock(), 1000, None)
        worker.set_options({'filter': settings})
        for start in range(0, 500, size):
            end = min(500, start + size)
            worker.process_batch(dict(generation=1, samples=samples[start:end], starts=starts[start:end],
                ends=starts[start:end]+9, avg_us=np.ones(end-start), arrival=time.perf_counter(), decoded=time.perf_counter()))
        worker.finish_pending()
        assert worker.count == 500 and worker.gaps == 1
        outputs.append(worker.processed[:500].copy())
    for output in outputs[1:]:
        np.testing.assert_allclose(output, outputs[0], rtol=0, atol=0)


def test_force_receives_every_sweep_and_resets_at_gap(monkeypatch):
    from data_processing.pressure_map_geometry import PressureMapGeometry
    from data_processing.pressure_force_display import PressureForceDisplayEngine
    desc = descriptor(10)
    packages = {}
    for spec in desc['channel_specs']:
        packages.setdefault('A1_' + spec['sensor_id'], {})[spec['placement']] = spec
    calls, resets, observed_times = [], [], []
    original_process = PressureForceDisplayEngine.process_sample
    original_reset = PressureForceDisplayEngine.reset
    def process(engine, sample_id, *args, **kwargs):
        calls.append(sample_id)
        observed_times.append(args[1])
        return original_process(engine, sample_id, *args, **kwargs)
    def reset(engine):
        resets.append(True)
        original_reset(engine)
    monkeypatch.setattr(PressureForceDisplayEngine, 'process_sample', process)
    monkeypatch.setattr(PressureForceDisplayEngine, 'reset', reset)
    worker = AcquisitionWorker(desc, 1, threading.Lock(), 1000, None)
    worker.set_options({'force': dict(revision=1, geometry=PressureMapGeometry(), settings={},
        packages=packages, baselines={s['key']: 2048 for s in desc['channel_specs']},
        voltage_scale=2.5/4095, polarity=1, grid_positions={p: (0,i) for i,p in enumerate(packages)}, calibration={})})
    starts = 1000 + np.arange(500) * 20
    starts[250:] += 500000
    averages = np.resize([1,2], 500)
    for start in range(0,500,17):
        end = min(500, start+17)
        worker.process_batch(dict(generation=1, samples=np.full((end-start,10),2048,dtype=np.uint16),
            starts=starts[start:end], ends=starts[start:end]+9*averages[start:end], avg_us=averages[start:end],
            arrival=time.perf_counter(), decoded=time.perf_counter()))
    worker.finish_pending()
    assert calls == [(i,0) for i in range(500)]
    assert len(resets) == 1 and worker.count == 500
    np.testing.assert_allclose([t['A1_PZT7']['T'] for t in observed_times],
        (starts-starts[0])/1e6 + 9*averages/1e6, rtol=0, atol=1e-12)


@pytest.mark.parametrize('has_gap', [False, True])
def test_spectrum_rejects_missing_interval_without_interpolation(has_gap):
    from data_processing.spectrum_processor import _compute_spectrum_payload
    times = np.arange(1000) * .00002
    if has_gap:
        times[500:] += .5
    payload = dict(mode='fft', nfft_mode='auto', nfft_value=1024, window='hann', remove_dc=True,
        welch_segment=256, welch_overlap=.5, channels=[dict(label='A1_PZT6_C',
        samples=np.sin(np.arange(1000)), timestamps=times, fs_hz=50000, window_samples=1000)])
    result = _compute_spectrum_payload(payload)
    assert result['status'] == ('error' if has_gap else 'ok')
    if has_gap:
        assert 'missing transmission interval' in result['message']


def test_bulk_decoder_recovers_after_corrupt_frame():
    frames, _ = wire_frames(10, 100, 20)
    frames['avg'][40] = 0
    frames['count'][70] = 9999
    reader = SerialReaderThread(None)
    batches = []
    reader.configure_batch_consumer(batches.append, 1)
    reader.set_capturing(True, 10)
    reader.process_binary_data(bytearray(frames.tobytes()))
    reader.set_capturing(False)
    starts = np.concatenate([b['starts'] for b in batches])
    np.testing.assert_array_equal(starts, np.delete(frames['start'], [40,70]))
    assert reader._accepted_packets_total == 98 and reader._rejected_packets_total >= 2


def test_real_gui_pipeline_record_reload_and_restart(tmp_path):
    from PyQt6.QtWidgets import QApplication
    from scripts.benchmark_testboard_gui import run_case
    app = QApplication.instance() or QApplication([])
    # Two independent generations run through actual widget/timer/lifecycle code.
    for width in (50,10):
        result = run_case(app, tmp_path, width, 1000, .15, filters=True)
        assert result['received'] == result['written'] == result['expected'] == 150
        assert result['complete'] and result['reload_verified']


def test_force_render_keeps_overlapping_array_layouts_separate():
    from data_processing.force_block_worker import ForceBlockWorker
    from data_processing.pressure_force_display import PressureForceDisplayEngine
    from data_processing.pressure_map_generator import PressureMapGeometry
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({'A1_PZT6': (0, 0), 'A2_PZT6': (0, 0)})
    worker = AcquisitionWorker(descriptor(), 1, threading.Lock(), 100, None)
    worker._force_consumer = ForceBlockWorker(engine)
    worker._publish_force_result(force=True)
    assert worker.latest_force_result.array_result is None
    assert all(worker.latest_force_result.array_results[a] is not None for a in (1, 2))
    assert {p.sensor_id for p in worker.latest_force_result.package_results} == {'A1_PZT6', 'A2_PZT6'}


def test_failed_acquisition_preserves_original_error_at_decoder_boundary():
    worker = AcquisitionWorker(descriptor(), 1, threading.Lock(), 100, None)
    worker.error = 'force rendering failed for array 2'
    with pytest.raises(AcquisitionOverrun, match='force rendering failed for array 2'):
        worker.enqueue({'generation': 1})
