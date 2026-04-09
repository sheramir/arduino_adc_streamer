"""
ADC Filter Engine
=================
ADC-only IIR filter design and block-processing helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from config.channel_utils import unique_channels_in_order
from config_constants import (
    FILTER_DEFAULT_ENABLED,
    FILTER_DEFAULT_MAIN_TYPE,
    FILTER_DEFAULT_ORDER,
    FILTER_DEFAULT_LOW_CUTOFF_HZ,
    FILTER_DEFAULT_HIGH_CUTOFF_HZ,
    FILTER_NOTCH1_DEFAULT_ENABLED,
    FILTER_NOTCH1_DEFAULT_FREQ_HZ,
    FILTER_NOTCH1_DEFAULT_Q,
    FILTER_NOTCH2_DEFAULT_ENABLED,
    FILTER_NOTCH2_DEFAULT_FREQ_HZ,
    FILTER_NOTCH2_DEFAULT_Q,
    FILTER_NOTCH3_DEFAULT_ENABLED,
    FILTER_NOTCH3_DEFAULT_FREQ_HZ,
    FILTER_NOTCH3_DEFAULT_Q,
)

try:
    from scipy.signal import butter, iirnotch, sosfilt, sosfilt_zi, tf2sos
    SCIPY_FILTERS_AVAILABLE = True
except Exception:
    SCIPY_FILTERS_AVAILABLE = False


@dataclass(slots=True)
class ChannelFilterRuntime:
    indices: np.ndarray
    fs_hz: float
    sos: np.ndarray | None
    zi: np.ndarray | None


def build_default_filter_settings() -> dict:
    return {
        'enabled': FILTER_DEFAULT_ENABLED,
        'main_type': FILTER_DEFAULT_MAIN_TYPE,
        'order': FILTER_DEFAULT_ORDER,
        'low_cutoff_hz': FILTER_DEFAULT_LOW_CUTOFF_HZ,
        'high_cutoff_hz': FILTER_DEFAULT_HIGH_CUTOFF_HZ,
        'notches': [
            {'enabled': FILTER_NOTCH1_DEFAULT_ENABLED, 'freq_hz': FILTER_NOTCH1_DEFAULT_FREQ_HZ, 'q': FILTER_NOTCH1_DEFAULT_Q},
            {'enabled': FILTER_NOTCH2_DEFAULT_ENABLED, 'freq_hz': FILTER_NOTCH2_DEFAULT_FREQ_HZ, 'q': FILTER_NOTCH2_DEFAULT_Q},
            {'enabled': FILTER_NOTCH3_DEFAULT_ENABLED, 'freq_hz': FILTER_NOTCH3_DEFAULT_FREQ_HZ, 'q': FILTER_NOTCH3_DEFAULT_Q},
        ],
    }


class ADCFilterEngine:
    """Owns ADC filter validation, coefficient design, and block filtering."""

    def validate_settings(self, settings: dict, channel_fs_hz: float) -> Tuple[bool, str]:
        if channel_fs_hz <= 0:
            return False, 'Sample rate unavailable for filtering.'

        nyquist = channel_fs_hz / 2.0
        low = float(settings['low_cutoff_hz'])
        high = float(settings['high_cutoff_hz'])

        for notch in settings['notches']:
            if not notch['enabled']:
                continue
            freq = float(notch['freq_hz'])
            q = float(notch['q'])
            if freq <= 0 or freq >= nyquist:
                return False, f'Notch frequency {freq:.2f} must be between 0 and Nyquist ({nyquist:.2f} Hz).'
            if q <= 0:
                return False, 'Notch Q must be > 0.'

        main_type = settings['main_type']
        if main_type == 'lowpass':
            if low <= 0 or low >= nyquist:
                return False, f'Low-pass cutoff must be between 0 and Nyquist ({nyquist:.2f} Hz).'
        elif main_type == 'highpass':
            if high <= 0 or high >= nyquist:
                return False, f'High-pass cutoff must be between 0 and Nyquist ({nyquist:.2f} Hz).'
        elif main_type == 'bandpass':
            if low <= 0 or high <= 0:
                return False, 'Band-pass cutoffs must be > 0.'
            if low >= high:
                return False, 'Band-pass low cutoff must be less than high cutoff.'
            if high >= nyquist:
                return False, f'Band-pass high cutoff must be below Nyquist ({nyquist:.2f} Hz).'

        return True, ''

    def design_channel_sos(self, settings: dict, channel_fs_hz: float):
        if not SCIPY_FILTERS_AVAILABLE:
            raise RuntimeError('SciPy is required for filtering. Install scipy and restart.')

        valid, error = self.validate_settings(settings, channel_fs_hz)
        if not valid:
            raise ValueError(error)

        sos_parts = []
        nyquist = channel_fs_hz / 2.0

        for notch in settings['notches']:
            if not notch['enabled']:
                continue
            w0 = float(notch['freq_hz']) / nyquist
            q = float(notch['q'])
            b, a = iirnotch(w0, q)
            sos_parts.append(tf2sos(b, a))

        order = max(1, int(settings['order']))
        main_type = settings['main_type']
        low = float(settings['low_cutoff_hz'])
        high = float(settings['high_cutoff_hz'])

        if main_type == 'lowpass':
            wn = low / nyquist
            sos_parts.append(butter(order, wn, btype='lowpass', output='sos'))
        elif main_type == 'highpass':
            wn = high / nyquist
            sos_parts.append(butter(order, wn, btype='highpass', output='sos'))
        elif main_type == 'bandpass':
            wn = [low / nyquist, high / nyquist]
            sos_parts.append(butter(order, wn, btype='bandpass', output='sos'))

        if not sos_parts:
            return None

        if len(sos_parts) == 1:
            return sos_parts[0]
        return np.vstack(sos_parts)

    def build_runtime_plan(self, settings: dict, total_fs_hz: float, channels: List[int], repeat_count: int) -> Dict[int, ChannelFilterRuntime]:
        unique_channels = unique_channels_in_order(channels)

        sequence_len = max(1, len(channels))
        counts = {channel: channels.count(channel) for channel in unique_channels}

        plan: Dict[int, ChannelFilterRuntime] = {}
        for channel in unique_channels:
            indices = []
            for seq_idx, seq_channel in enumerate(channels):
                if seq_channel != channel:
                    continue
                base = seq_idx * repeat_count
                indices.extend(range(base, base + repeat_count))

            if not indices:
                continue

            channel_fs_hz = total_fs_hz * (counts[channel] / sequence_len)
            sos = self.design_channel_sos(settings, channel_fs_hz)
            zi = None
            if sos is not None:
                zi = sosfilt_zi(sos).astype(np.float32) * 0.0

            plan[channel] = ChannelFilterRuntime(
                indices=np.asarray(indices, dtype=np.int32),
                fs_hz=float(channel_fs_hz),
                sos=sos,
                zi=zi,
            )

        return plan

    def reset_runtime_states(self, runtime_plan: Dict[int, ChannelFilterRuntime]) -> None:
        for runtime in runtime_plan.values():
            if runtime.sos is None:
                runtime.zi = None
            else:
                runtime.zi = sosfilt_zi(runtime.sos).astype(np.float32) * 0.0

    def filter_block(self, runtime_plan: Dict[int, ChannelFilterRuntime], block_data: np.ndarray) -> np.ndarray:
        filtered = block_data.astype(np.float32, copy=False)

        for runtime in runtime_plan.values():
            if runtime.sos is None:
                continue

            stream = filtered[:, runtime.indices].reshape(-1)
            zi = runtime.zi
            if zi is None:
                zi = sosfilt_zi(runtime.sos).astype(np.float32) * 0.0
            y, zf = sosfilt(runtime.sos, stream, zi=zi)
            runtime.zi = zf
            filtered[:, runtime.indices] = y.reshape(filtered.shape[0], len(runtime.indices))

        return filtered
