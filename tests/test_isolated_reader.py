"""Verify the real process/pipe boundary without opening a hardware port."""
import struct
import os
import subprocess
import sys
import time

import numpy as np
import pytest

from data_processing.acquisition_queue import AcquisitionQueue, AcquisitionOverrun
from serial_communication.isolated_reader import IsolatedRawReader, _WindowsWorkerProcess, _RawChunkCoalescer, _RAW
from serial_communication.serial_threads import SerialReaderThread


@pytest.mark.parametrize('width,rate,fragmented', [(50, 17000, False), (10, 75000, False), (50, 17000, True), (10, 75000, True)])
def test_raw_process_preserves_frames_and_reads_while_parent_holds_gil(width, rate, fragmented):
    duration = .4
    transport = IsolatedRawReader(replay=dict(width=width, rate=rate, duration=duration, fragmented_reads=fragmented))
    chunks = []
    arrivals = []
    interval = sys.getswitchinterval()
    try:
        transport.replay_write(b'run*')
        first = transport.read_chunk(.5)
        assert first is not None
        chunks.append(first[0])
        arrivals.append(first[1])
        # A sleeping GUI releases the GIL and cannot establish isolation.
        # Hold it deliberately, then inspect the child's own arrival times.
        sys.setswitchinterval(1)
        start = time.perf_counter()
        until = start + .2
        while time.perf_counter() < until:
            pass
        end = time.perf_counter()
        sys.setswitchinterval(interval)
        expected_bytes = int(rate * duration) * (14 + width * 2)
        received = len(first[0])
        deadline = time.perf_counter() + 3
        while received < expected_bytes and time.perf_counter() < deadline:
            item = transport.read_chunk(.05)
            if item is not None:
                chunks.append(item[0])
                arrivals.append(item[1])
                received += len(item[0])
        assert received == expected_bytes
        assert sum(start < arrival < end for arrival in arrivals) >= 5
        dtype = np.dtype([('magic', 'u1', 2), ('count', '<u2'), ('samples', '<u2', width),
                          ('avg', '<u2'), ('start', '<u4'), ('end', '<u4')])
        frames = np.frombuffer(b''.join(chunks), dtype=dtype)
        count = int(rate * duration)
        np.testing.assert_array_equal(frames['magic'], np.tile([0xAA, 0x55], (count, 1)))
        assert np.all(frames['count'] == width) and np.all(frames['avg'] == 1)
        np.testing.assert_array_equal(frames['samples'], np.broadcast_to(2048 + (np.arange(count)[:, None] % 5), (count, width)))
        starts = 0xFFFF0000 + np.round(np.arange(count) * 1e6 / rate).astype(np.int64)
        np.testing.assert_array_equal(frames['start'], starts & 0xFFFFFFFF)
        np.testing.assert_array_equal(frames['end'], (starts + width - 1) & 0xFFFFFFFF)
        transport.replay_write(b'stop*')
        transport.replay_write(b'status*')
        replies = bytearray()
        deadline = time.perf_counter() + 2
        while replies.count(b'#OK\n') < 2 and time.perf_counter() < deadline:
            item = transport.read_chunk(.02)
            if item is not None:
                replies.extend(item[0])
        assert replies.startswith(b'#OK\n# ---- STATUS')
        assert f'# usb_frames_sent={count}\n'.encode() in replies
        assert transport.snapshot()['error'] is None
        assert transport.snapshot()['reader_pid'] == transport.worker_pid
        if os.name == 'nt':
            assert transport._worker_process.pid == transport.worker_pid
        if fragmented:
            assert transport.snapshot()['connection_native_reads'] >= count * 2
            assert transport.snapshot()['connection_pipe_chunks'] < count // 10
        assert transport.snapshot()['delivery_age_max_s'] >= .1
    finally:
        sys.setswitchinterval(interval)
        transport.stop()
    assert transport.process.poll() is not None and not transport._bridge.is_alive()


@pytest.mark.skipif(os.name != 'nt', reason='native Windows handle transfer')
def test_native_handle_targets_real_interpreter_through_python_launcher():
    from serial import win32
    # This exercises real DuplicateHandle, rather than the finite replay
    # backend. An event verifies cross-process ownership without a board port.
    event = win32.CreateEvent(None, True, True, None)
    child = subprocess.Popen([sys.executable, '-c',
        'import os; from serial import win32; print(os.getpid(),flush=True); '
        'handle=int(input()); print(win32.WaitForSingleObject(handle,1000),flush=True); '
        'win32.CloseHandle(handle)'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    worker = None
    try:
        actual_pid = int(child.stdout.readline())
        worker = _WindowsWorkerProcess(actual_pid)
        duplicate = worker.duplicate_handle(event)
        output, errors = child.communicate(f'{duplicate}\n', timeout=5)
        assert child.returncode == 0, errors
        assert output.strip() == '0', 'the actual interpreter must own the signaled event'
        assert worker.wait(1000)
        assert win32.WaitForSingleObject(event, 0) == 0, 'parent must retain its original handle'
    finally:
        if worker is not None:
            worker.terminate()
            worker.close()
        if child.poll() is None:
            child.terminate()
            child.wait(2)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()
        win32.CloseHandle(event)


@pytest.mark.skipif(os.name != 'nt', reason='native Windows child termination')
def test_forced_stop_terminates_actual_interpreter_and_reaps_launcher():
    transport = IsolatedRawReader(replay=dict(width=10, rate=1000, duration=.1))
    worker = transport._worker_process
    # The graceful control command is deliberately lost. Shutdown must stop
    # the interpreter itself, rather than leaving it behind its launcher.
    transport._send = lambda message: None
    transport.stop()
    assert worker.handle is None
    assert transport.process.poll() is not None
    assert not transport._bridge.is_alive()


@pytest.mark.skipif(os.name != 'nt', reason='native Windows COM-handle preflight')
def test_invalid_com_handle_fails_before_reader_ready_and_closes_child():
    from serial import win32
    from types import SimpleNamespace
    event = win32.CreateEvent(None, True, True, None)
    instances = []
    class ObservedReader(IsolatedRawReader):
        def stop(self):
            instances.append(self)
            super().stop()
    try:
        # A correctly transferred non-COM handle must fail preflight. Before
        # the fix, H/ready was sent before ClearCommError, allowing run* first.
        with pytest.raises(OSError, match='ClearCommError'):
            ObservedReader(SimpleNamespace(_port_handle=event, baudrate=115200, timeout=.02))
        assert instances and instances[0]._fault is not None
        assert instances[0].process.poll() is not None
        assert instances[0]._worker_process.handle is None
        assert win32.WaitForSingleObject(event, 0) == 0
    finally:
        win32.CloseHandle(event)


def test_raw_process_queue_overrun_is_explicit_and_child_stops():
    transport = IsolatedRawReader(replay=dict(width=50, rate=17000, duration=.2), max_pending_bytes=64)
    try:
        transport.replay_write(b'run*')
        with pytest.raises(AcquisitionOverrun, match='isolated raw reader'):
            deadline = time.perf_counter() + 2
            while time.perf_counter() < deadline:
                transport.read_chunk(.02)
        assert transport.snapshot()['child_budget_bytes'] == 64
    finally:
        transport.stop()
    assert transport.process.poll() is not None


def test_bridge_fault_drains_owned_prefix_before_reporting_failure():
    transport = IsolatedRawReader(replay=dict(width=10, rate=1000, duration=.1))
    try:
        transport.queue.put((b'owned bytes', 123.0, 0.0), size=11, arrival=time.perf_counter())
        transport._fault = ('overrun', 'capture queue budget exceeded')
        assert transport.read_chunk(0) == (b'owned bytes', 123.0)
        with pytest.raises(AcquisitionOverrun):
            transport.read_chunk(0)
    finally:
        transport.stop()


def test_isolated_gui_replay_displays_and_reloads_original_device_timestamps(tmp_path):
    from PyQt6.QtWidgets import QApplication
    from scripts.benchmark_testboard_gui import run_case
    app = QApplication.instance() or QApplication([])
    result = run_case(app, tmp_path, 10, 2000, 1, filters=True, isolated_reader=True)
    assert result['expected'] == result['received'] == result['written'] == 2000
    assert result['complete'] and result['reload_verified']
    assert result['decoder']['transport']['kind'] == 'isolated_process'
    assert result['max_visible_adc_curves'] == 10


def test_reader_waits_for_process_before_run_and_reuses_it_across_generations(monkeypatch):
    from scripts.benchmark_testboard_gui import IsolatedReplayPort
    port = IsolatedReplayPort(50, 17000, .1)
    monkeypatch.setattr('serial_communication.serial_threads.supports_isolation', lambda candidate: candidate is port)
    monkeypatch.setattr('serial_communication.serial_threads.IsolatedRawReader', lambda candidate: candidate.start_reader())
    reader = SerialReaderThread(port)
    batches = []
    reader.start()
    try:
        reader.configure_batch_consumer(batches.append, 1)
        assert port.transport is not None and reader._isolation_ready.is_set()
        reader.set_capturing(True, 50)
        port.write(b'run*')
        deadline = time.perf_counter() + 2
        while reader.pipeline_status()['accepted_frames'] < port.count and time.perf_counter() < deadline:
            time.sleep(.002)
        reader.set_capturing(False)
        assert sum(len(batch['starts']) for batch in batches) == port.count
        assert reader.pipeline_status()['parser_rejections'] == 0
        transport = reader._isolated_reader
        reader.configure_batch_consumer(None, 1)
        reader.configure_batch_consumer(batches.append, 2)
        reader.set_capturing(True, 50)
        assert reader._isolated_reader is transport
        assert reader.pipeline_status()['accepted_frames'] == 0
    finally:
        reader.stop()
        assert reader.wait(reader.shutdown_wait_ms)
        port.close()
    assert transport.process.poll() is not None


def test_startup_failure_prevents_run(monkeypatch):
    class Port:
        is_open, in_waiting, timeout = True, 0, 0
    port = Port()
    monkeypatch.setattr('serial_communication.serial_threads.supports_isolation', lambda candidate: candidate is port)
    def fail(candidate):
        raise OSError('handle duplication failed')
    monkeypatch.setattr('serial_communication.serial_threads.IsolatedRawReader', fail)
    reader = SerialReaderThread(port)
    reader.start()
    try:
        with pytest.raises(AcquisitionOverrun, match='handle duplication failed'):
            reader.configure_batch_consumer(lambda batch: None, 1)
        assert reader.wait(2000)
    finally:
        reader.stop()
        reader.wait(2000)


def test_rejected_frame_raw_context_preserves_shift_without_relaxing_validation():
    reader = SerialReaderThread(None)
    batches = []
    reader.configure_batch_consumer(batches.append, 1)
    reader.set_capturing(True, 50)
    def packet(start):
        return b'\xaa\x55\x32\x00' + struct.pack('<50H', *range(2000, 2050)) + struct.pack('<HII', 1, start, start+49)
    good = packet(100000)
    # Extra payload word shifts the candidate footer by two bytes, like the
    # latest capture's rejected timing fields. It must stay rejected.
    bad = good[:104] + b'\x00\x08' + good[104:]
    reader.process_binary_data(bytearray(good + bad + packet(100100)))
    reader.set_capturing(False)
    status = reader.pipeline_status()
    assert status['accepted_frames'] == 2 and status['parser_rejections'] == 1
    rejection = status['rejection_examples'][0]
    context = bytes.fromhex(rejection['raw_context_hex'])
    offset = rejection['candidate_offset_in_context']
    assert context[offset:offset+len(bad)] == bad
    assert len(context) <= 256
    np.testing.assert_array_equal(np.concatenate([batch['starts'] for batch in batches]), [100000, 100100])


def test_thousands_of_tiny_reads_fit_item_budget_and_preserve_every_byte():
    queue = AcquisitionQueue(max_bytes=16000, max_items=128)
    chunks = _RawChunkCoalescer(queue)
    original = bytes(i % 256 for i in range(8000))
    for i, value in enumerate(original):
        chunks.append(bytes([value]), 100 + i * .00001)
    chunks.flush()
    assert 1 < queue.snapshot()['items'] < 50
    output = bytearray()
    arrival = []
    while queue.snapshot()['items']:
        record = queue.get(0)
        first, _, _, _, count = _RAW.unpack_from(record)
        arrival.append(first)
        assert count <= len(original)
        output.extend(record[_RAW.size:])
    assert bytes(output) == original
    assert arrival[0] == 100
    assert chunks.read_count == len(original)


def test_raw_coalescing_flushes_partial_reply_by_age_and_bounds_size():
    queue = AcquisitionQueue()
    chunks = _RawChunkCoalescer(queue, max_bytes=8, interval=.002)
    chunks.append(b'#O', 10.0)
    chunks.append(b'K\n', 10.0005)
    assert queue.snapshot()['items'] == 0
    chunks.flush_due(10.003)
    record = queue.get(0)
    assert _RAW.unpack_from(record)[0] == 10.0
    assert record[_RAW.size:] == b'#OK\n'
    chunks.append(b'1234567', 11.0)
    chunks.append(b'89', 11.0001)
    chunks.flush()
    records = [queue.get(0), queue.get(0)]
    assert all(len(record) - _RAW.size <= 8 for record in records)
    assert b''.join(record[_RAW.size:] for record in records) == b'123456789'
