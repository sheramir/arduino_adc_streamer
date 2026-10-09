"""Offline paced wire replay through the real GUI, with JSONL recording.

Run with the repository Python. No hardware port or firmware is accessed.
The finite replay source is a diagnostic fixture, not acquisition buffering.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from contextlib import ExitStack

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QSettings

from adc_gui import ADCStreamerGUI
from serial_communication.serial_threads import SerialReaderThread
from serial_communication.adc_session import ADCSessionController


class ReplayPort:
    is_open = True
    def __init__(self, width, rate, duration, *, reader_pause=False, fragmented_reads=False):
        self.width, self.rate = width, rate
        self.count = int(rate * duration)
        dtype = np.dtype([('magic', 'u1', 2), ('count', '<u2'), ('samples', '<u2', width),
                          ('avg', '<u2'), ('start', '<u4'), ('end', '<u4')])
        frames = np.zeros(self.count, dtype=dtype)
        frames['magic'] = (0xAA, 0x55)
        frames['count'] = width
        frames['samples'] = 2048 + (np.arange(self.count)[:, None] % 5)
        frames['avg'] = 1
        starts = 0xFFFF0000 + np.round(np.arange(self.count) * 1e6 / rate).astype(np.int64)
        frames['start'] = starts & 0xFFFFFFFF
        frames['end'] = (starts + width - 1) & 0xFFFFFFFF
        self.data = frames.tobytes()
        self.frame_size = dtype.itemsize
        self.position = 0
        self.begin = None
        self.limit = 0
        self.ascii = bytearray()
        self.lock = threading.Lock()
        self.reader_pause = reader_pause
        self.fragmented_reads = fragmented_reads

    def _available(self):
        if self.begin is not None:
            elapsed = time.perf_counter() - self.begin
            if self.reader_pause and 0.75 <= elapsed < 1.25:
                return 0
            # Deliver 10 ms bursts, including partial frames at read boundaries.
            due = min(self.count, int(elapsed / .01) * max(1, round(self.rate * .01)))
            self.limit = due * self.frame_size
        return max(0, self.limit - self.position)

    @property
    def in_waiting(self):
        with self.lock:
            available = self._available()
            if available and self.fragmented_reads:
                # USB can wake a one-byte read, followed by the remainder of
                # one frame. Model this instead of only large 10 ms bursts.
                offset = self.position % self.frame_size
                return min(available, self.frame_size - offset if offset else 1)
            return available if available else len(self.ascii)

    def read(self, count):
        with self.lock:
            available = self._available()
            if available:
                size = min(count, available, 16381)
                data = self.data[self.position:self.position+size]
                self.position += size
                return data
            data = bytes(self.ascii[:count])
            del self.ascii[:count]
            return data

    def write(self, data):
        with self.lock:
            command = data.decode().rstrip('*')
            if command.startswith('run'):
                self.begin = time.perf_counter()
            elif command == 'stop':
                self._available()
                self.begin = None
                self.ascii.extend(b'#OK\n')
            elif command == 'status':
                count = self.position // self.frame_size
                self.ascii.extend((f'# ---- STATUS (PZT/ADS7953) ----\n# sampling_sweeps={count}\n'
                    f'# usb_frames_sent={count}\n# usb_frames_discarded=0\n'
                    '# sampling_period_max_us=100\n# sampling_period_over_1ms=0\n# ----\n#OK\n').encode())

    def flush(self):
        pass

    def reset_input_buffer(self):
        with self.lock:
            self.ascii.clear()

    def close(self):
        self.is_open = False


class IsolatedReplayPort:
    """Same finite wire source, read in the production raw transport process."""
    is_open = True
    timeout = 0
    in_waiting = 0

    def __init__(self, width, rate, duration, *, reader_pause=False, fragmented_reads=False):
        self.count = int(rate * duration)
        self.settings = dict(width=width, rate=rate, duration=duration, reader_pause=reader_pause,
                             fragmented_reads=fragmented_reads)
        self.transport = None

    def start_reader(self):
        from serial_communication.isolated_reader import IsolatedRawReader
        self.transport = IsolatedRawReader(replay=self.settings)
        return self.transport

    def write(self, data):
        assert self.transport is not None, 'run issued before isolated reader was ready'
        self.transport.replay_write(data)

    def flush(self):
        pass

    def close(self):
        self.is_open = False
        if self.transport is not None:
            self.transport.stop()


def run_case(app, directory, width, rate, duration, stall=False, tab='Time Series', filters=False, isolated_reader=False, fragmented_reads=False):
    with patch('adc_gui.load_device_config', return_value={'auto_connect': False}), patch.object(Path, 'home', return_value=directory), \
         patch.object(ADCStreamerGUI, '_pzt_decay_qsettings', lambda self: QSettings(str(directory / 'decay.ini'), QSettings.Format.IniFormat)), \
         patch.object(ADCStreamerGUI, '_pressure_map_workspace_qsettings', lambda self: QSettings(str(directory / 'pressure.ini'), QSettings.Format.IniFormat)), ExitStack() as cleanup:
        gui = ADCStreamerGUI()
        cleanup.callback(gui.close)
        gui.current_mcu = 'TestBoard_7953'
        gui.update_gui_for_mcu()
        gui.testboard_array_combo.setCurrentIndex(gui.testboard_array_combo.findData('both' if width == 50 else '1'))
        gui.pzt_sequence_input.setText('6,7,1,3,5' if width == 50 else '6,7')
        gui._build_adc_configuration_request()
        gui.dir_input.setText(str(directory))
        gui.filename_input.setText(f'replay_{width}_{rate}')
        gui.filtering_enabled = filters
        gui.filter_settings['enabled'] = filters
        for index in range(gui.visualization_tabs.count()):
            if gui.visualization_tabs.tabText(index) == tab:
                gui.visualization_tabs.setCurrentIndex(index)
        gui.show()
        app.processEvents()
        port_class = IsolatedReplayPort if isolated_reader else ReplayPort
        port = port_class(width, rate, duration, reader_pause=stall, fragmented_reads=fragmented_reads)
        if isolated_reader:
            # Exercise the same startup handoff used for an existing Win32 COM
            # handle, substituting only the finite source inside the child.
            cleanup.enter_context(patch('serial_communication.serial_threads.supports_isolation', lambda candidate: candidate is port))
            cleanup.enter_context(patch('serial_communication.serial_threads.IsolatedRawReader', lambda candidate: candidate.start_reader()))
        session = ADCSessionController(gui.process_serial_data, gui.process_binary_sweep, gui._handle_serial_reader_error)
        reader = SerialReaderThread(port)
        reader.data_received.connect(gui.process_serial_data)
        reader.binary_sweep_received.connect(gui.process_binary_sweep)
        reader.error_occurred.connect(gui._handle_serial_reader_error)
        session.serial_port, session.serial_thread = port, reader
        gui.adc_session = session
        gui._sync_adc_transport_state()
        reader.start()
        beats, last_beat = [], [time.perf_counter()]
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        def beat():
            now = time.perf_counter()
            beats.append(now-last_beat[0])
            last_beat[0] = now
        heartbeat.timeout.connect(beat)
        max_raw = max_decoded = max_archive = 0
        max_visible_adc_curves = 0
        checked_render = None
        gui.start_capture()
        start = time.perf_counter()
        last_beat[0] = start
        heartbeat.start()
        stall_end = [None]
        recovery = None
        caught_up = None
        render_after_catchup = None
        if stall:
            def pause_gui():
                time.sleep(.5)
                stall_end[0] = time.perf_counter()
            QTimer.singleShot(1500, pause_gui)
        while time.perf_counter() - start < duration + .3 and gui.is_capturing:
            app.processEvents()
            state = gui._testboard_worker.snapshot()
            max_raw = max(max_raw, reader.raw_queue.snapshot()['bytes'])
            max_decoded = max(max_decoded, state['decoded']['sweeps'])
            max_archive = max(max_archive, gui._archive_writer.get_status_snapshot()['pending_sweeps'])
            rendered = getattr(gui, '_pipeline_render_time', None)
            if tab == 'Time Series' and rendered != checked_render:
                checked_render = rendered
                x_range, y_range = gui.plot_widget.getViewBox().viewRange()
                visible = 0
                for curve in gui._adc_curves.values():
                    x, y = curve.getData()
                    if curve.isVisible() and x is not None and len(x) > 1:
                        measured = np.isfinite(y) & (x >= x_range[0]) & (x <= x_range[1])
                        if np.any(measured & (y >= y_range[0]) & (y <= y_range[1])):
                            visible += 1
                max_visible_adc_curves = max(max_visible_adc_curves, visible)
            if recovery is None and stall_end[0] is not None:
                if caught_up is None and gui.sweep_count >= reader._accepted_packets_total - rate * .04 and state['decoded']['sweeps'] <= rate * .04:
                    caught_up = time.perf_counter()
                rendered = getattr(gui, '_pipeline_render_time', 0)
                if rendered >= stall_end[0] and gui._pipeline_last_render_count >= reader._accepted_packets_total - rate * .04:
                    recovery = rendered - stall_end[0]
                    if caught_up is not None:
                        render_after_catchup = max(0, rendered - caught_up)
            time.sleep(.001)
        gui.stop_capture()
        archive_state = gui._archive_writer.stop(timeout=15)
        heartbeat.stop()
        summary = gui.capture_summary
        reload_verified = None
        if port.count <= 5000:
            data, timestamps = gui.load_archive_data()
            expected_times = np.round(np.arange(port.count) * 1e6 / rate) / 1e6
            np.testing.assert_allclose(timestamps, expected_times, rtol=0, atol=1e-12)
            assert len(data) == port.count and len(data[0]) == width
            reload_verified = True
        result = dict(width=width, target_rate=rate, duration_s=duration, tab=tab, filters=filters,
            stall=stall, isolated_reader=isolated_reader, fragmented_reads=fragmented_reads, expected=port.count, received=gui.sweep_count,
            written=archive_state['written_sweeps'], complete=summary['complete'], interruption=summary['interruption'],
            heartbeat_p95_ms=float(np.percentile(beats,95)*1000), heartbeat_max_ms=max(beats)*1000,
            max_raw_bytes=max_raw, max_decoded_sweeps=max_decoded, max_archive_sweeps=max_archive,
            decoder=reader.pipeline_status(), worker_duration_max_ms=gui._testboard_worker.worker_duration_max_s*1000,
            render_duration_ms=getattr(gui, '_pipeline_render_duration_s', 0)*1000)
        result['reload_verified'] = reload_verified
        result['max_visible_adc_curves'] = max_visible_adc_curves
        if tab == 'Time Series' and duration >= .4:
            assert max_visible_adc_curves > 0, 'capture counts advanced without visible Time Series traces'
        result['stall_to_fresh_render_ms'] = recovery * 1000 if recovery is not None else None
        result['pipeline_catchup_ms'] = (caught_up - stall_end[0]) * 1000 if caught_up is not None else None
        result['render_recovery_after_catchup_ms'] = render_after_catchup * 1000 if render_after_catchup is not None else None
        result['decode_to_render_age_ms'] = getattr(gui, '_pipeline_decode_to_render_age_s', 0) * 1000
        app.processEvents()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--stall', action='store_true')
    parser.add_argument('--filters', action='store_true')
    parser.add_argument('--isolated-reader', action='store_true')
    parser.add_argument('--fragmented-reads', action='store_true')
    parser.add_argument('--tab', default='Time Series')
    parser.add_argument('--rate', type=int)
    parser.add_argument('--width', type=int, choices=(10,50), default=10)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    cases = [(args.width,args.rate)] if args.rate else [(50,12000),(50,17000),(10,60000),(50,20000),(10,75000)]
    results = []
    with tempfile.TemporaryDirectory(prefix='adc_gui_replay_') as temp:
        for width, rate in cases:
            result = run_case(app, Path(temp), width, rate, args.seconds, args.stall, args.tab, args.filters, args.isolated_reader, args.fragmented_reads)
            results.append(result)
            print(json.dumps(result), flush=True)
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + '\n')
    return 0 if all(r['complete'] and r['received']==r['expected']==r['written'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
