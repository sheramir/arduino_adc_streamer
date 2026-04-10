"""
Capture Lifecycle Mixin
=======================
Owns capture start/stop/finish flow and closely related lifecycle resets.
"""

from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from config_constants import CACHE_SUBDIR_NAME, FORCE_CALIBRATION_SAMPLES
from data_processing.archive_writer import ArchiveWriterThread
from data_processing.force_state import get_force_runtime_state


class CaptureLifecycleMixin:
    """Capture lifecycle flow and closely related lifecycle resets."""

    def _reset_capture_buffer_state(self, *, reset_samples_per_sweep=False, zero_buffers=False):
        """Reset rolling capture buffers and cached full-view arrays."""
        with self.buffer_lock:
            self.raw_data = []
            self.sweep_timestamps = []
            self.sweep_count = 0
            self.buffer_write_index = 0
            if reset_samples_per_sweep:
                self.samples_per_sweep = 0

            if zero_buffers and self.raw_data_buffer is not None:
                self.raw_data_buffer.fill(0)
            if zero_buffers and self.processed_data_buffer is not None:
                self.processed_data_buffer.fill(0)
            if zero_buffers and self.sweep_timestamps_buffer is not None:
                self.sweep_timestamps_buffer.fill(0)
        self.plot_baselines = {}

    def _reset_force_capture_state(self):
        """Reset force samples for a new capture lifecycle."""
        state = get_force_runtime_state(self)
        state.data.clear()
        state.start_time = None

    def _restart_force_baseline_measurement_if_connected(self):
        """Re-zero the force baseline from fresh raw samples at capture start."""
        force_port = getattr(self, 'force_serial_port', None)
        if force_port is None or not getattr(force_port, 'is_open', False):
            return
        if not hasattr(self, 'calibrate_force_sensors'):
            return

        self.log_status(
            f"Re-zeroing force sensors at capture start (collecting {FORCE_CALIBRATION_SAMPLES} samples)..."
        )
        self.calibrate_force_sensors()

    def _reset_timing_measurements(self, *, log_timestamp_clear=False, reset_labels=False):
        """Reset capture timing fields, histories, and optional UI labels."""
        if hasattr(self, 'first_sweep_timestamp_us'):
            if log_timestamp_clear:
                self.log_status(f"Clearing first_sweep_timestamp_us (was {self.first_sweep_timestamp_us} Âµs)")
            delattr(self, 'first_sweep_timestamp_us')
        elif log_timestamp_clear:
            self.log_status("first_sweep_timestamp_us already cleared")

        self.timing_state.reset(self._build_empty_timing_data())

        if reset_labels:
            self.per_channel_rate_label.setText("- Hz")
            self.total_rate_label.setText("- Hz")
            self.between_samples_label.setText("- Âµs")
            self.block_gap_label.setText("- ms")

    def _reset_signal_processing_state(self, *, reset_shear=False):
        """Reset filter pipeline state and optionally shear processing."""
        self.filter_apply_pending = True
        self.reset_filter_states()
        if hasattr(self, '_invalidate_timeseries_filter_cache'):
            self._invalidate_timeseries_filter_cache()
        if hasattr(self, '_invalidate_full_view_filter_cache'):
            self._invalidate_full_view_filter_cache()
        if hasattr(self, '_reset_live_filtered_tracking'):
            self._reset_live_filtered_tracking(preserve_existing=False)
        if reset_shear:
            self.reset_shear_processing_state()

    def _reset_full_view_state(self, *, button_enabled=None, trigger_plot_update=False):
        """Exit full view and clear the cached reordered arrays."""
        self.is_full_view = False
        with self.buffer_lock:
            self.raw_data = []
            self.sweep_timestamps = []
        if hasattr(self, '_invalidate_full_view_filter_cache'):
            self._invalidate_full_view_filter_cache()

        if button_enabled is None:
            button_enabled = not self.is_capturing
        self.full_view_btn.setEnabled(bool(button_enabled))

        if trigger_plot_update:
            self.trigger_plot_update()

    def start_capture(self):
        """Start data capture."""
        if not self.config['channels']:
            QMessageBox.warning(
                self,
                "Configuration Error",
                "Please configure channels before starting capture."
            )
            return

        self.plot_baselines = {}

        self.set_controls_enabled(False)

        if self.is_full_view:
            self._reset_full_view_state(button_enabled=False, trigger_plot_update=False)
            self.log_status("Resetting from full view to normal view for new capture")
        else:
            self.full_view_btn.setEnabled(False)

        self._reset_capture_buffer_state()
        self._reset_signal_processing_state(reset_shear=False)
        self._reset_force_capture_state()
        self._reset_timing_measurements(reset_labels=True)

        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)

        save_dir = Path(self.dir_input.text()) if hasattr(self, 'dir_input') else Path.cwd()
        save_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = save_dir / CACHE_SUBDIR_NAME
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir_path = str(cache_dir)
        base_name = self.filename_input.text().strip() if hasattr(self, 'filename_input') else 'adc_data'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        archive_name = f"{base_name}_{timestamp}.jsonl"
        archive_path = cache_dir / archive_name
        timing_name = f"{base_name}_{timestamp}_block_timing.csv"
        timing_path = cache_dir / timing_name

        try:
            archive_metadata = {
                'metadata': {
                    'channels': self.config.get('channels', []),
                    'repeat': self.config.get('repeat', 1),
                    'ground_pin': self.config.get('ground_pin'),
                    'use_ground': self.config.get('use_ground'),
                    'osr': self.config.get('osr'),
                    'gain': self.config.get('gain'),
                    'reference': self.config.get('reference'),
                    'notes': self.notes_input.toPlainText() if hasattr(self, 'notes_input') else None,
                    'start_time': datetime.now().isoformat()
                }
            }
            self._archive_writer = ArchiveWriterThread(str(archive_path), archive_metadata)
            self._archive_writer.start()
            self._archive_path = str(archive_path)
            self._archive_write_count = 0
            self.log_status(f"Archive opened: {self._archive_path}")
        except Exception as e:
            self._archive_writer = None
            self.log_status(f"WARNING: Could not open archive file: {e}")

        try:
            self._block_timing_file = open(timing_path, 'w', encoding='utf-8', newline='')
            self._block_timing_path = str(timing_path)
            try:
                tw = csv.writer(self._block_timing_file)
                tw.writerow(["sample_count", "samples_per_sweep", "sweeps_in_block", "avg_dt_us", "block_start_us", "block_end_us", "mcu_gap_us"])
                self._block_timing_file.flush()
            except Exception:
                pass
            if self._block_timing_path:
                self.log_status(f"Block timing opened: {self._block_timing_path}")
        except Exception as e:
            self._block_timing_file = None
            self._block_timing_path = None
            self.log_status(f"WARNING: Could not open block timing file: {e}")

        self.is_capturing = True
        if self.serial_thread:
            expected_samples_per_sweep = self.get_effective_samples_per_sweep()
            self.serial_thread.set_capturing(True, expected_samples_per_sweep=expected_samples_per_sweep)

        time.sleep(0.05)

        if self.timed_run_check.isChecked():
            duration_ms = self.timed_run_spin.value()
            self.send_command(f"run {duration_ms}")
            self.log_status(f"Starting timed capture for {duration_ms} ms")
            QTimer.singleShot(duration_ms + 500, self.on_capture_finished)
        else:
            self.send_command("run")
            self.log_status("Starting continuous capture")

        self._restart_force_baseline_measurement_if_connected()

        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        self.stop_btn.setEnabled(True)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; }")
        self.statusBar().showMessage("Capturing - Scrolling Mode")

    def stop_capture(self):
        """Stop data capture."""
        if not self.is_capturing:
            self.log_status("Stop requested but capture already stopped")
            return

        self.log_status("Stopping capture")

        success, _ = self.send_command_and_wait_ack(
            "stop",
            expected_value=None,
            timeout=0.2,
            max_retries=1
        )

        if not success:
            self.log_status("WARNING: Stop command not acknowledged; halting locally")

        if self.serial_thread:
            self.serial_thread.set_capturing(False)

        self.is_capturing = False

        self.drain_serial_input(0.15)

        self.on_capture_finished()

    def on_capture_finished(self):
        """Handle capture finished (either stopped or timed out)."""
        timing = self.timing_state
        timing.capture_end_time = time.time()

        self.is_capturing = False
        get_force_runtime_state(self).start_time = None

        if self.serial_thread:
            self.serial_thread.set_capturing(False)

        if timing.arduino_sample_times:
            avg_sample_time = sum(timing.arduino_sample_times) / len(timing.arduino_sample_times)
            total_rate = 1000000.0 / avg_sample_time if avg_sample_time > 0 else 0
            self.log_status(f"Capture complete - Sample interval: {avg_sample_time:.2f} Âµs, Total rate: {total_rate:.2f} Hz")

        if timing.buffer_gap_times:
            avg_gap = sum(timing.buffer_gap_times) / len(timing.buffer_gap_times)
            self.log_status(f"Average block gap: {avg_gap:.2f} ms ({len(timing.buffer_gap_times)} blocks)")

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        self.update_start_button_state()
        self.set_controls_enabled(True)

        self.drain_serial_input(0.02)

        if not self.is_full_view:
            self.full_view_btn.setEnabled(True)

        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.setMenuEnabled(True)

        self.statusBar().showMessage("Connected - Static Display Mode")

        if hasattr(self, 'should_filter_adc_data') and self.should_filter_adc_data():
            try:
                self.reprocess_filtered_buffer()
            except Exception as exc:
                self.log_status(f"WARNING: failed to rebuild filtered ADC buffer after capture: {exc}")

        self.update_plot()

        with self.buffer_lock:
            total_samples = int(self.sweep_count) * self.samples_per_sweep if self.samples_per_sweep > 0 else 0
        force_samples = len(get_force_runtime_state(self).data)
        self.plot_info_label.setText(
            f"ADC - Sweeps: {self.sweep_count} | Samples: {total_samples}  |  Force: {force_samples} samples"
        )

        try:
            if getattr(self, '_archive_writer', None):
                snapshot = self._archive_writer.stop_nowait()
                self.log_status(
                    "Archive saving in background: "
                    f"{self._archive_path} ({snapshot.get('written_sweeps', 0)} sweeps written so far)"
                )
        except Exception as exc:
            self.log_status(f"WARNING: Failed to finalize archive save request: {exc}")

        try:
            if self._block_timing_file:
                try:
                    self._block_timing_file.flush()
                except Exception:
                    pass
                try:
                    self._block_timing_file.close()
                except Exception:
                    pass
                self.log_status(f"Block timing saved: {self._block_timing_path}")
        except Exception:
            pass

        self.log_status(f"Capture finished. Total sweeps: {self.sweep_count}, Total samples: {total_samples}, Force samples: {force_samples}")

    def set_controls_enabled(self, enabled: bool):
        """Enable or disable configuration controls."""
        self.port_combo.setEnabled(enabled and not self.serial_port)
        self.refresh_ports_btn.setEnabled(enabled and not self.serial_port)

        self.vref_combo.setEnabled(enabled)
        self.osr_combo.setEnabled(enabled)
        self.gain_combo.setEnabled(enabled)

        self.channels_input.setEnabled(enabled)
        if hasattr(self, 'array_mode_combo'):
            self.array_mode_combo.setEnabled(enabled)
        if hasattr(self, 'pzt_sequence_input'):
            self.pzt_sequence_input.setEnabled(enabled)
        if hasattr(self, 'pzr_sequence_input'):
            self.pzr_sequence_input.setEnabled(enabled)
        self.ground_pin_spin.setEnabled(enabled)
        self.use_ground_check.setEnabled(enabled)
        self.repeat_spin.setEnabled(enabled)
        self.buffer_spin.setEnabled(enabled)

        self.timed_run_check.setEnabled(enabled)
        if enabled:
            self.timed_run_spin.setEnabled(self.timed_run_check.isChecked())
        else:
            self.timed_run_spin.setEnabled(False)

        self.window_size_spin.setEnabled(enabled)
