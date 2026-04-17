"""
Timing Display Mixin
====================
Owns capture timing state, timing calculations, and 555 timing readouts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from constants.defaults_555 import (
    ANALYZER555_DEFAULT_CF_FARADS,
    ANALYZER555_DEFAULT_RB_OHMS,
    ANALYZER555_DEFAULT_RK_OHMS,
)


@dataclass
class TimingState:
    """Central store for timing metrics and recent timing history."""

    timing_data: dict
    capture_start_time: float | None = None
    capture_end_time: float | None = None
    last_buffer_time: float | None = None
    last_buffer_end_time: float | None = None
    mcu_last_block_end_us: int | None = None
    buffer_receipt_times: list = field(default_factory=list)
    buffer_gap_times: list = field(default_factory=list)
    arduino_sample_times: list = field(default_factory=list)
    block_sample_counts: list = field(default_factory=list)
    block_sweeps_counts: list = field(default_factory=list)
    block_samples_per_sweep: list = field(default_factory=list)
    mcu_block_start_us: list = field(default_factory=list)
    mcu_block_end_us: list = field(default_factory=list)
    mcu_block_gap_us: list = field(default_factory=list)

    def reset(self, empty_timing_data):
        """Clear scalar fields and keep dict/list identities stable."""
        self.timing_data.clear()
        self.timing_data.update(empty_timing_data)
        self.capture_start_time = None
        self.capture_end_time = None
        self.last_buffer_time = None
        self.last_buffer_end_time = None
        self.mcu_last_block_end_us = None
        self.buffer_receipt_times.clear()
        self.buffer_gap_times.clear()
        self.arduino_sample_times.clear()
        self.block_sample_counts.clear()
        self.block_sweeps_counts.clear()
        self.block_samples_per_sweep.clear()
        self.mcu_block_start_us.clear()
        self.mcu_block_end_us.clear()
        self.mcu_block_gap_us.clear()

    def trim_recent(self, attr_name, max_items):
        """Keep only the newest items in a history list without replacing the list object."""
        history = getattr(self, attr_name)
        if len(history) > max_items:
            del history[:-max_items]


class TimingDisplayMixin:
    """Capture timing state, timing label updates, and 555 timing readouts."""

    def _build_empty_timing_data(self):
        return {
            'per_channel_rate_hz': None,
            'total_rate_hz': None,
            'between_samples_us': None,
            'arduino_sample_time_us': None,
            'arduino_sample_rate_hz': None,
            'buffer_gap_time_ms': None,
            'mcu_block_start_us': None,
            'mcu_block_end_us': None,
            'mcu_block_gap_us': None,
        }

    def _create_timing_state(self):
        return TimingState(timing_data=self._build_empty_timing_data())

    def _ensure_timing_state(self):
        if getattr(self, '_timing_state', None) is None:
            self._timing_state = self._create_timing_state()
        return self._timing_state

    @property
    def timing_state(self):
        return self._ensure_timing_state()

    def update_timing_display(self):
        """Update timing display based on Arduino measurements and buffer gap timing."""
        try:
            timing = self.timing_state
            timing_data = timing.timing_data

            arduino_avg_sample_time_us = timing.arduino_sample_times[-1] if timing.arduino_sample_times else 0

            arduino_sample_rate_hz = 0
            arduino_per_channel_rate_hz = 0
            if arduino_avg_sample_time_us > 0:
                arduino_sample_rate_hz = 1000000.0 / arduino_avg_sample_time_us

                display_channels = self.get_display_channel_specs()
                if display_channels:
                    arduino_per_channel_rate_hz = arduino_sample_rate_hz / len(display_channels)
                else:
                    arduino_per_channel_rate_hz = arduino_sample_rate_hz

            buffer_gap_time_ms = 0
            if timing.mcu_block_gap_us:
                buffer_gap_time_ms = timing.mcu_block_gap_us[-1] / 1000.0
            elif timing.buffer_gap_times:
                buffer_gap_time_ms = sum(timing.buffer_gap_times) / len(timing.buffer_gap_times)

            timing_data['arduino_sample_time_us'] = arduino_avg_sample_time_us
            timing_data['arduino_sample_rate_hz'] = arduino_sample_rate_hz
            timing_data['per_channel_rate_hz'] = arduino_per_channel_rate_hz
            timing_data['total_rate_hz'] = arduino_sample_rate_hz
            timing_data['buffer_gap_time_ms'] = buffer_gap_time_ms

            if timing.mcu_block_start_us:
                timing_data['mcu_block_start_us'] = timing.mcu_block_start_us[-1]
                timing_data['mcu_block_end_us'] = timing.mcu_block_end_us[-1]
                if timing.mcu_block_gap_us:
                    timing_data['mcu_block_gap_us'] = timing.mcu_block_gap_us[-1]

            if arduino_avg_sample_time_us > 0:
                self.per_channel_rate_label.setText(f"{arduino_per_channel_rate_hz:.2f} Hz")
                self.total_rate_label.setText(f"{arduino_sample_rate_hz:.2f} Hz")
                self.between_samples_label.setText(f"{arduino_avg_sample_time_us:.2f} µs")
            else:
                self.per_channel_rate_label.setText("- Hz")
                self.total_rate_label.setText("- Hz")
                self.between_samples_label.setText("- µs")

            if buffer_gap_time_ms > 0:
                self.block_gap_label.setText(f"{buffer_gap_time_ms:.2f} ms")
            elif timing.mcu_block_gap_us:
                self.block_gap_label.setText(f"{(timing.mcu_block_gap_us[-1] / 1000.0):.2f} ms")
            elif timing.buffer_gap_times:
                avg_gap = sum(timing.buffer_gap_times) / len(timing.buffer_gap_times)
                self.block_gap_label.setText(f"{avg_gap:.2f} ms")
            else:
                self.block_gap_label.setText("- ms")

        except Exception as e:
            self.log_status(f"ERROR: Failed to update timing display - {e}")

    def _format_time_auto(self, seconds: float) -> str:
        value = max(0.0, float(seconds))
        if value < 1e-3:
            return f"{value * 1e6:.2f} µs"
        if value < 1.0:
            return f"{value * 1e3:.2f} ms"
        return f"{value:.4f} s"

    def update_555_timing_readouts(self, latest_channel_values):
        if not hasattr(self, 'charge_time_label') or not hasattr(self, 'discharge_time_label'):
            return

        if getattr(self, 'device_mode', 'adc') != '555':
            self.charge_time_label.setVisible(False)
            self.discharge_time_label.setVisible(False)
            return

        self.charge_time_label.setVisible(True)
        self.discharge_time_label.setVisible(True)

        cf_farads = float(self.config.get('cf_farads', ANALYZER555_DEFAULT_CF_FARADS))
        rb_ohms = float(self.config.get('rb_ohms', ANALYZER555_DEFAULT_RB_OHMS))
        rk_ohms = float(self.config.get('rk_ohms', ANALYZER555_DEFAULT_RK_OHMS))
        ln2 = 0.69314718056

        t_discharge = ln2 * cf_farads * rb_ohms

        if not latest_channel_values:
            self.charge_time_label.setText("Charge time: waiting for channel data...")
            self.discharge_time_label.setText(f"Discharge time: {self._format_time_auto(t_discharge)}")
            return

        parts = []
        for channel in sorted(latest_channel_values.keys()):
            rx = max(0.0, float(latest_channel_values[channel]))
            t_charge = ln2 * cf_farads * (rx + rk_ohms + rb_ohms)
            parts.append(f"Ch{channel}: {self._format_time_auto(t_charge)}")

        self.charge_time_label.setText("Charge time: " + " | ".join(parts))
        self.discharge_time_label.setText(f"Discharge time: {self._format_time_auto(t_discharge)}")
