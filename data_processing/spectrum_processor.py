"""
Spectrum Processor Mixin
========================
Thread-safe spectrum extraction and frequency-domain processing.
"""

import math
import queue
from collections import deque
from typing import Dict, List

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal


class SpectrumWorkerThread(QThread):
    """Background worker thread for spectrum computations."""

    result_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue(maxsize=1)
        self._running = True

    def submit(self, payload: dict):
        """Submit latest payload, dropping stale work if needed."""
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(payload)
        except Exception:
            pass

    def run(self):
        while self._running:
            try:
                payload = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if payload is None:
                break

            try:
                result = _compute_spectrum_payload(payload)
                self.result_ready.emit(result)
            except Exception as e:
                self.error_occurred.emit(str(e))

    def stop(self):
        self._running = False
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(None)
        except Exception:
            pass


def _next_power_of_two(value: int) -> int:
    value = max(1, int(value))
    return 1 << (value - 1).bit_length()


def _window_array(window_name: str, length: int) -> np.ndarray:
    if window_name == 'hamming':
        return np.hamming(length)
    if window_name == 'blackman':
        return np.blackman(length)
    if window_name == 'rectangular':
        return np.ones(length)
    return np.hanning(length)


def _compute_fft_magnitude(samples: np.ndarray, fs_hz: float, nfft: int, window_name: str, remove_dc: bool):
    x = samples.astype(np.float64, copy=True)
    if remove_dc:
        x -= np.mean(x)

    window = _window_array(window_name, len(x))
    xw = x * window

    spectrum = np.fft.rfft(xw, n=nfft)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs_hz)

    coherent_gain = max(np.sum(window), 1e-12)
    magnitude = np.abs(spectrum) * (2.0 / coherent_gain)
    if magnitude.size > 0:
        magnitude[0] *= 0.5
        if nfft % 2 == 0 and magnitude.size > 1:
            magnitude[-1] *= 0.5

    return freqs, magnitude


def _compute_welch_psd(
    samples: np.ndarray,
    fs_hz: float,
    seg_len: int,
    overlap_percent: float,
    nfft: int,
    window_name: str,
    remove_dc: bool,
):
    x = samples.astype(np.float64, copy=True)
    if remove_dc:
        x -= np.mean(x)

    overlap_percent = max(0.0, min(95.0, float(overlap_percent)))
    step = max(1, int(seg_len * (1.0 - overlap_percent / 100.0)))

    window = _window_array(window_name, seg_len)
    window_power = max(np.sum(window ** 2), 1e-12)

    starts = range(0, max(len(x) - seg_len + 1, 1), step)
    spectra = []

    for start in starts:
        end = start + seg_len
        if end > len(x):
            break
        segment = x[start:end] * window
        fft_vals = np.fft.rfft(segment, n=nfft)
        psd = (np.abs(fft_vals) ** 2) / (fs_hz * window_power)
        if psd.size > 2:
            psd[1:-1] *= 2.0
        spectra.append(psd)

    if not spectra:
        segment = np.zeros(seg_len, dtype=np.float64)
        copy_len = min(len(x), seg_len)
        segment[:copy_len] = x[-copy_len:]
        segment *= window
        fft_vals = np.fft.rfft(segment, n=nfft)
        psd = (np.abs(fft_vals) ** 2) / (fs_hz * window_power)
        if psd.size > 2:
            psd[1:-1] *= 2.0
        spectra.append(psd)

    mean_psd = np.mean(np.array(spectra), axis=0)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs_hz)
    return freqs, mean_psd


def _compute_spectrum_payload(payload: dict) -> dict:
    mode = payload['mode']
    nfft_mode = payload['nfft_mode']
    nfft_value = int(payload['nfft_value'])
    window_name = payload['window']
    remove_dc = bool(payload['remove_dc'])
    welch_segment = int(payload['welch_segment'])
    welch_overlap = float(payload['welch_overlap'])

    channels_out = []
    freqs_ref = None
    min_samples_used = None

    for channel_entry in payload['channels']:
        label = channel_entry['label']
        samples = np.asarray(channel_entry['samples'], dtype=np.float64)
        fs_hz = float(channel_entry.get('fs_hz', 0.0))
        timestamps = np.asarray(channel_entry.get('timestamps', []), dtype=np.float64)

        # If timestamps are provided, derive effective Fs and resample to a uniform grid.
        # This compensates for block gaps/jitter that would otherwise distort FFT/PSD.
        if timestamps.size == samples.size and timestamps.size > 8:
            diffs = np.diff(timestamps)
            diffs = diffs[diffs > 0]
            if diffs.size > 0:
                dt_sec = float(np.median(diffs))
                if dt_sec > 0:
                    fs_hz = 1.0 / dt_sec
                    t0 = float(timestamps[0])
                    t1 = float(timestamps[-1])
                    if t1 > t0:
                        uniform_ts = np.arange(t0, t1, dt_sec, dtype=np.float64)
                        if uniform_ts.size > 8:
                            samples = np.interp(uniform_ts, timestamps, samples)

        requested_window_samples = int(channel_entry.get('window_samples', 0))

        if requested_window_samples <= 0:
            requested_window_samples = len(samples)

        window_samples = min(len(samples), requested_window_samples)
        if window_samples <= 4 or fs_hz <= 0:
            continue

        x = samples[-window_samples:]

        if nfft_mode == 'auto':
            nfft = _next_power_of_two(window_samples)
        else:
            nfft = max(nfft_value, window_samples)
            nfft = _next_power_of_two(nfft)

        if mode == 'fft':
            freqs, linear_values = _compute_fft_magnitude(x, fs_hz, nfft, window_name, remove_dc)
        else:
            segment_len = min(max(16, welch_segment), window_samples)
            if nfft_mode == 'auto':
                welch_nfft = _next_power_of_two(segment_len)
            else:
                welch_nfft = max(nfft_value, segment_len)
                welch_nfft = _next_power_of_two(welch_nfft)

            freqs, linear_values = _compute_welch_psd(
                x,
                fs_hz,
                seg_len=segment_len,
                overlap_percent=welch_overlap,
                nfft=welch_nfft,
                window_name=window_name,
                remove_dc=remove_dc,
            )
            nfft = welch_nfft

        freqs_ref = freqs
        min_samples_used = window_samples if min_samples_used is None else min(min_samples_used, window_samples)

        channels_out.append({
            'label': label,
            'fs_hz': fs_hz,
            'nfft': nfft,
            'window_samples': window_samples,
            'linear': linear_values,
        })

    if freqs_ref is None or not channels_out:
        return {
            'status': 'no-data',
            'message': 'Insufficient samples for spectrum.',
        }

    return {
        'status': 'ok',
        'mode': mode,
        'window': window_name,
        'remove_dc': remove_dc,
        'nfft_mode': nfft_mode,
        'nfft_value': nfft_value,
        'welch_segment': welch_segment,
        'welch_overlap': welch_overlap,
        'freqs_hz': freqs_ref,
        'channels': channels_out,
        'window_samples_effective': int(min_samples_used or 0),
    }


class SpectrumProcessorMixin:
    """Mixin for thread-safe spectrum extraction and update dispatch."""

    def _init_spectrum_state(self):
        self.spectrum_worker = SpectrumWorkerThread()
        self.spectrum_worker.result_ready.connect(self.on_spectrum_worker_result)
        self.spectrum_worker.error_occurred.connect(self.on_spectrum_worker_error)
        self.spectrum_worker.start()

        self.spectrum_busy = False
        self.spectrum_frozen = False
        self.latest_spectrum_payload = None
        self.latest_spectrum_result = None
        self.spectrum_ema_state: Dict[str, np.ndarray] = {}
        self.spectrum_navg_state: Dict[str, deque] = {}

    def shutdown_spectrum_worker(self):
        if hasattr(self, 'spectrum_worker') and self.spectrum_worker is not None:
            self.spectrum_worker.stop()
            self.spectrum_worker.wait(1500)

    def _extract_recent_sweeps(self, required_sweeps: int):
        data_buffer = self.get_active_data_buffer()
        if data_buffer is None or self.samples_per_sweep <= 0:
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index

            actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
            if actual_sweeps <= 0:
                return None

            take_sweeps = max(1, min(required_sweeps, actual_sweeps))
            write_pos = current_write_index % self.MAX_SWEEPS_BUFFER

            if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                start_idx = max(0, actual_sweeps - take_sweeps)
                data_array = data_buffer[start_idx:actual_sweeps, :].copy()
                sweep_timestamps = self.sweep_timestamps_buffer[start_idx:actual_sweeps].copy()
            else:
                start_pos = (write_pos - take_sweeps) % self.MAX_SWEEPS_BUFFER
                if start_pos < write_pos:
                    data_array = data_buffer[start_pos:write_pos, :].copy()
                    sweep_timestamps = self.sweep_timestamps_buffer[start_pos:write_pos].copy()
                else:
                    data_array = np.concatenate([
                        data_buffer[start_pos:, :],
                        data_buffer[:write_pos, :]
                    ])
                    sweep_timestamps = np.concatenate([
                        self.sweep_timestamps_buffer[start_pos:],
                        self.sweep_timestamps_buffer[:write_pos]
                    ])

        return data_array, sweep_timestamps

    def _get_total_sample_rate_hz(self):
        if hasattr(self, 'arduino_sample_times') and self.arduino_sample_times:
            latest_us = float(self.arduino_sample_times[-1])
            if latest_us > 0:
                return 1_000_000.0 / latest_us

        # Fallback: estimate from sweep timestamps if available
        if self.sweep_timestamps_buffer is not None and self.samples_per_sweep > 0:
            with self.buffer_lock:
                current_sweep_count = self.sweep_count
                current_write_index = self.buffer_write_index

                actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
                if actual_sweeps >= 3:
                    sample_count = min(actual_sweeps, 200)
                    write_pos = current_write_index % self.MAX_SWEEPS_BUFFER

                    if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                        start_idx = max(0, actual_sweeps - sample_count)
                        sweep_ts = self.sweep_timestamps_buffer[start_idx:actual_sweeps].copy()
                    else:
                        start_pos = (write_pos - sample_count) % self.MAX_SWEEPS_BUFFER
                        if start_pos < write_pos:
                            sweep_ts = self.sweep_timestamps_buffer[start_pos:write_pos].copy()
                        else:
                            sweep_ts = np.concatenate([
                                self.sweep_timestamps_buffer[start_pos:],
                                self.sweep_timestamps_buffer[:write_pos]
                            ])

            if 'sweep_ts' in locals() and sweep_ts.size >= 3:
                dt = np.diff(sweep_ts)
                dt = dt[dt > 0]
                if dt.size > 0:
                    avg_sweep_dt = float(np.median(dt))
                    if avg_sweep_dt > 0:
                        return float(self.samples_per_sweep) / avg_sweep_dt

        rate = float(self.timing_data.get('arduino_sample_rate_hz') or 0.0)
        if rate > 0:
            return rate

        configured_rate = float(self.config.get('sample_rate', 0) or 0.0)
        if configured_rate > 0:
            return configured_rate

        return 0.0

    def _build_spectrum_payload(self, spectrum_settings: dict):
        channels_sequence = self.config.get('channels', [])
        if not channels_sequence:
            return None, 'Configure channels first.'

        unique_channels = []
        for channel in channels_sequence:
            if channel not in unique_channels:
                unique_channels.append(channel)

        if len(unique_channels) == 0:
            return None, 'No channels configured for spectrum.'

        # Support 1..5 channels so spectrum remains usable even when configuration
        # is not exactly five unique channels.
        if len(unique_channels) > 5:
            unique_channels = unique_channels[:5]

        total_fs = self._get_total_sample_rate_hz()
        if total_fs <= 0:
            return None, 'Sample rate required before spectrum can run.'

        repeat_count = max(1, int(self.config.get('repeat', 1)))
        sequence_len = max(1, len(channels_sequence))
        counts = {ch: channels_sequence.count(ch) for ch in unique_channels}
        sample_interval_sec = 1.0 / total_fs if total_fs > 0 else 0.0

        window_ms = max(10, int(spectrum_settings['window_ms']))
        max_window_samples = 0
        min_samples_per_sweep = None
        channel_plan: List[dict] = []

        for channel in unique_channels:
            occurrences = counts[channel]
            samples_per_sweep = occurrences * repeat_count
            channel_fs = total_fs * (occurrences / sequence_len)
            window_samples = max(16, int(channel_fs * window_ms / 1000.0))
            max_window_samples = max(max_window_samples, window_samples)
            min_samples_per_sweep = samples_per_sweep if min_samples_per_sweep is None else min(min_samples_per_sweep, samples_per_sweep)
            channel_plan.append({
                'channel': channel,
                'occurrences': occurrences,
                'samples_per_sweep': samples_per_sweep,
                'fs_hz': channel_fs,
                'window_samples': window_samples,
            })

        if not min_samples_per_sweep or min_samples_per_sweep <= 0:
            return None, 'Invalid channel sampling configuration.'

        required_sweeps = int(math.ceil(max_window_samples / min_samples_per_sweep)) + 1
        extracted = self._extract_recent_sweeps(required_sweeps)
        if extracted is None:
            return None, 'Waiting for data...'
        data_array, sweep_timestamps = extracted
        if data_array.size == 0 or sweep_timestamps.size == 0:
            return None, 'Waiting for data...'

        payload_channels = []
        for plan in channel_plan:
            idxs = []
            for seq_idx, seq_channel in enumerate(channels_sequence):
                if seq_channel != plan['channel']:
                    continue
                base = seq_idx * repeat_count
                idxs.extend(range(base, base + repeat_count))

            if not idxs:
                continue

            sample_matrix = data_array[:, idxs]
            offset_indices = np.asarray(idxs, dtype=np.float64)
            time_matrix = sweep_timestamps.reshape(-1, 1) + (offset_indices.reshape(1, -1) * sample_interval_sec)

            channel_samples = sample_matrix.reshape(-1)
            channel_timestamps = time_matrix.reshape(-1)
            if channel_samples.size < 16:
                continue

            diffs = np.diff(channel_timestamps)
            diffs = diffs[diffs > 0]
            if diffs.size > 0:
                channel_fs_effective = 1.0 / float(np.median(diffs))
            else:
                channel_fs_effective = float(plan['fs_hz'])

            channel_window_samples = max(16, int(channel_fs_effective * window_ms / 1000.0))

            payload_channels.append({
                'label': f"Ch {plan['channel']}",
                'samples': channel_samples.astype(np.float64, copy=False),
                'timestamps': channel_timestamps.astype(np.float64, copy=False),
                'fs_hz': float(channel_fs_effective),
                'window_samples': int(channel_window_samples),
            })

        if len(payload_channels) == 0:
            return None, 'Waiting for enough channel data...'

        payload = {
            'mode': spectrum_settings['mode'],
            'nfft_mode': spectrum_settings['nfft_mode'],
            'nfft_value': spectrum_settings['nfft_value'],
            'window': spectrum_settings['window'],
            'remove_dc': spectrum_settings['remove_dc'],
            'welch_segment': spectrum_settings['welch_segment'],
            'welch_overlap': spectrum_settings['welch_overlap'],
            'channels': payload_channels,
        }

        return payload, None

    def reset_spectrum_averaging(self):
        self.spectrum_ema_state.clear()
        self.spectrum_navg_state.clear()
        if hasattr(self, 'log_status'):
            self.log_status('Spectrum averaging reset.')

    def update_spectrum(self):
        if not hasattr(self, 'visualization_tabs'):
            return

        if self.visualization_tabs.tabText(self.visualization_tabs.currentIndex()) != 'Spectrum':
            return

        if getattr(self, 'spectrum_frozen', False):
            return

        if getattr(self, 'spectrum_busy', False):
            return

        settings = self.get_spectrum_settings()
        payload, error = self._build_spectrum_payload(settings)

        if error:
            self.show_spectrum_status(error)
            return

        self.hide_spectrum_status()
        self.spectrum_busy = True
        self.latest_spectrum_payload = payload
        self.spectrum_worker.submit(payload)

    def on_spectrum_worker_result(self, result: dict):
        self.spectrum_busy = False

        if result.get('status') != 'ok':
            self.show_spectrum_status(result.get('message', 'Spectrum unavailable.'))
            return

        settings = self.get_spectrum_settings()
        mode = result['mode']
        freqs = np.asarray(result['freqs_hz'])

        channels_processed = []
        for channel_entry in result['channels']:
            label = channel_entry['label']
            linear = np.asarray(channel_entry['linear'], dtype=np.float64)

            if settings['averaging_mode'] == 'ema':
                alpha = float(settings['ema_alpha'])
                prev = self.spectrum_ema_state.get(label)
                if prev is None or prev.shape != linear.shape:
                    averaged = linear
                else:
                    averaged = alpha * linear + (1.0 - alpha) * prev
                self.spectrum_ema_state[label] = averaged
                linear_out = averaged
            else:
                navg = max(1, int(settings['n_avg']))
                history = self.spectrum_navg_state.get(label)
                history_invalid = history is None
                if history is not None and len(history) > 0 and history[0].shape != linear.shape:
                    history_invalid = True
                if history is not None and history.maxlen != navg:
                    history_invalid = True

                if history_invalid:
                    history = deque(maxlen=navg)
                    self.spectrum_navg_state[label] = history
                history.append(linear)
                linear_out = np.mean(np.array(history), axis=0)

            channels_processed.append({
                'label': label,
                'linear': linear_out,
                'fs_hz': channel_entry['fs_hz'],
                'nfft': channel_entry['nfft'],
                'window_samples': channel_entry['window_samples'],
            })

        result_out = {
            'status': 'ok',
            'mode': mode,
            'freqs_hz': freqs,
            'channels': channels_processed,
            'window': result.get('window'),
            'remove_dc': result.get('remove_dc'),
            'nfft_mode': result.get('nfft_mode'),
            'nfft_value': result.get('nfft_value'),
            'welch_segment': result.get('welch_segment'),
            'welch_overlap': result.get('welch_overlap'),
            'window_samples_effective': result.get('window_samples_effective', 0),
        }

        self.latest_spectrum_result = result_out
        self.update_spectrum_display(result_out)

    def on_spectrum_worker_error(self, message: str):
        self.spectrum_busy = False
        self.show_spectrum_status(f'Spectrum error: {message}')
