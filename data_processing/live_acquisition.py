"""GUI lifecycle and latest-state rendering for profile-selected acquisition."""
from copy import deepcopy
import math
import time

from PyQt6.QtCore import QTimer, QCoreApplication, QEventLoop

from data_processing.acquisition_worker import AcquisitionWorker


class LiveAcquisitionMixin:
    @property
    def sweep_count(self):
        worker = getattr(self, '_acquisition_worker', None)
        return worker.count if worker is not None else getattr(self, '_legacy_sweep_count', 0)

    @sweep_count.setter
    def sweep_count(self, value):
        self._legacy_sweep_count = value

    @property
    def buffer_write_index(self):
        worker = getattr(self, '_acquisition_worker', None)
        return worker.count if worker is not None else getattr(self, '_legacy_write_index', 0)

    @buffer_write_index.setter
    def buffer_write_index(self, value):
        self._legacy_write_index = value

    def _start_acquisition_pipeline(self):
        from config.boards.settings import context_for
        from config.boards.streaming import streaming_policy
        policy = streaming_policy(context_for(self).mode)
        if not policy.batched:
            return
        if not getattr(self, 'array_capture_descriptor', None):
            raise RuntimeError('Batched capture requires a frozen array descriptor')
        if self.serial_thread is None or self._archive_writer is None:
            raise RuntimeError('Batched capture requires a reader and a writable archive')
        self.capture_summary = None
        self._capture_incomplete_reason = None
        self._capture_finishing = False
        self._pipeline_last_render_count = -1
        self._pipeline_last_force_result = None
        self._acquisition_force_active = False
        self._archive_writer.timing_handle = self._block_timing_file
        self._block_timing_file = None
        worker = AcquisitionWorker(self.array_capture_descriptor, self._capture_generation,
            self.buffer_lock, self.MAX_SWEEPS_BUFFER, self._archive_writer,
            ghost_enabled=self.should_remove_pzt_ghost(), attenuation=self.pzt_ghost_attenuation)
        self._acquisition_worker = worker
        self.samples_per_sweep = worker.width
        self.raw_data_buffer, self.processed_data_buffer, self.sweep_timestamps_buffer = worker.raw, worker.processed, worker.times
        self._update_acquisition_worker_options()
        worker.start()
        self.serial_thread.configure_batch_consumer(worker.enqueue, worker.generation)
        if not hasattr(self, '_acquisition_render_timer'):
            self._acquisition_render_timer = QTimer(self)
            self._acquisition_render_timer.timeout.connect(self._refresh_live_acquisition)
        self._acquisition_render_timer.setInterval(policy.render_interval_ms)
        self._acquisition_render_timer.start()
        from serial_communication.capture_awake import set_capture_awake
        set_capture_awake(True)

    def _watch_acquisition_archive(self):
        pending = []
        for writer, summary in getattr(self, '_pending_archive_completions', []):
            status = writer.get_status_snapshot()
            if status['state'] == 'failed':
                reason = status['last_error'] or 'archive writer failed'
                summary.update(complete=False, interruption=reason)
                if summary is getattr(self, 'capture_summary', None):
                    self._capture_incomplete_reason = reason
                self.log_status(f"Capture {summary['generation']} incomplete: {reason}")
                self.statusBar().showMessage(f'Capture incomplete: {reason}')
            if status['state'] not in ('closed', 'failed'):
                pending.append((writer, summary))
        self._pending_archive_completions = pending
        if not pending:
            self._archive_completion_timer.stop()

    def _update_acquisition_worker_options(self):
        worker = getattr(self, '_acquisition_worker', None)
        if worker is None:
            return
        options = {'filter': self._copy_filter_settings_snapshot() if self.should_filter_adc_data() else None}
        self._acquisition_force_active = self._acquisition_force_active or self._is_pressure_map_force_display_visible()
        if self._acquisition_force_active:
            # Resolve widget/config-dependent inputs only on the GUI thread.
            packages = self._resolve_force_complete_packages(worker.raw[:1])
            engine = getattr(self, 'pressure_force_engine', None)
            if packages and engine is not None:
                options['force'] = dict(revision=(id(engine), repr(self.plot_baselines)),
                    geometry=deepcopy(self.pressure_map_geometry), settings=dict(engine.settings),
                    packages=packages, baselines=dict(self.plot_baselines),
                    voltage_scale=float(self.get_vref_voltage()) / ((2 ** worker.descriptor['adc_resolution_bits']) - 1),
                    polarity=-1.0 if worker.descriptor['sensor_configuration'].get('reverse_polarity') else 1.0,
                    grid_positions=self._get_force_display_grid_positions(),
                    calibration={p: {k: math.copysign(1.0, g) if g else 1.0 for k, g in self._pressure_sensor_gains_for_package(p).items()} for p in packages})
        worker.set_options(options)

    def _refresh_live_acquisition(self):
        worker = getattr(self, '_acquisition_worker', None)
        if worker is None:
            return
        state = worker.snapshot()
        reader_status = self.serial_thread.pipeline_status() if self.serial_thread else {}
        writer_status = self._archive_writer.get_status_snapshot() if self._archive_writer else {}
        self.acquisition_pipeline_status = dict(processing=state, reader=reader_status, archive=writer_status)
        error = state['error'] or (writer_status.get('last_error') if writer_status.get('state') == 'failed' else None)
        if error and self.is_capturing and not self._capture_finishing:
            self._capture_incomplete_reason = error
            self.log_status(f'Capture incomplete: {error}')
            self.stop_capture()
            return
        now = time.perf_counter()
        if state['last_arrival'] is not None:
            age = now - state['last_arrival']
            processed_age = now - state['last_processed'] if state['last_processed'] else age
        else:
            age = processed_age = now - getattr(self, '_capture_host_start', now)
        self._update_acquisition_worker_options()
        self._cached_avg_sample_time_sec = state['avg_us'] / 1e6
        self._received_sweep_period_s = state['nominal_period_s']
        if state['avg_us']:
            self.timing_state.arduino_sample_times.append(state['avg_us'])
            self.timing_state.trim_recent('arduino_sample_times', 1000)
        self.timing_state.adc_active_capture_duration_us = state['active_duration_us']
        self.timing_state.adc_emitted_sample_count = worker.count * worker.width
        self.timing_state.adc_block_count = reader_status.get('accepted_frames', worker.count)
        self.timing_state.adc_block_gap_total_us = state['gap_duration_us']
        self.timing_state.adc_block_gap_count = max(0, self.timing_state.adc_block_count - 1)
        if state['baselines'] is not None:
            self._pzt_ghost_baselines = state['baselines']
            self._pzt_ghost_noise = worker._pzt_ghost_noise
            self._pzt_ghost_calibration_pending = False
            self.plot_baselines = {tuple(s['key']): float(state['baselines'][s['sample_indices'][0]]) for s in worker.descriptor['channel_specs']}
        if worker.count != self._pipeline_last_render_count:
            self._pipeline_last_render_count = worker.count
            render_start = time.perf_counter()
            if self.should_update_live_timeseries_display():
                self.update_plot()
                self.update_force_plot()
            elif self.should_update_signal_integration_display():
                self.update_signal_integration_plot()
            elif self.should_update_heatmap_display():
                self.update_heatmap_plot()
            self.refresh_live_decay_preview()
            if getattr(self.force_calibration_state, 'is_capturing', False):
                self.update_force_calibration_live_reading_from_selected_source()
            self._pipeline_render_duration_s = time.perf_counter() - render_start
            self._pipeline_render_time = time.perf_counter()
            self._pipeline_decode_to_render_age_s = max(0.0, render_start - state['last_decoded']) if state['last_decoded'] else 0.0
        if state['force_result'] is not None and state['force_result'] is not self._pipeline_last_force_result:
            self._pipeline_last_force_result = state['force_result']
            self._on_force_result_ready(state['force_result'])
        self.update_timing_display()
        raw = reader_status.get('raw', {})
        transport = reader_status.get('transport', {})
        pipe = transport.get('pending', {})
        decoded = state['decoded']
        stale = age > 0.5 or processed_age > 0.5 or raw.get('oldest_age_s', 0) > 0.5 or pipe.get('oldest_age_s', 0) > 0.5 or decoded['oldest_age_s'] > 0.5
        self.update_plot_info_label(sweep_count=worker.count, total_samples=worker.count * worker.width,
                                   force_samples=len(self.force_state.data))
        if self.is_capturing:
            message = (
                f"{'Stale data' if stale else 'Capturing'} | received {worker.count:,} sweeps | gaps {state['gaps']} | "
                f"source age {age * 1000:.0f} ms | processed age {processed_age * 1000:.0f} ms | "
                f"decode to render {getattr(self, '_pipeline_decode_to_render_age_s', 0)*1000:.0f} ms | "
                f"raw {raw.get('bytes', 0):,} B / {raw.get('oldest_age_s', 0)*1000:.0f} ms | "
                + (f"USB pipe {pipe.get('bytes', 0):,} B / {pipe.get('oldest_age_s', 0)*1000:.0f} ms | " if pipe else '') +
                f"decode {decoded['sweeps']:,} sweeps / {decoded['bytes']:,} B / {decoded['oldest_age_s']*1000:.0f} ms | "
                f"archive {writer_status.get('pending_sweeps', 0):,} sweeps / {writer_status.get('pending_bytes', 0):,} B / {writer_status.get('oldest_age_s', 0)*1000:.0f} ms")
            self.statusBar().showMessage(message)
            self.statusBar().setToolTip(message + '\n' +
                (f"USB reader: {transport['kind']}; child/bridge budgets: {transport['child_budget_bytes']:,}/{transport['budget_bytes']:,} B; child peak: {transport['child_peak_bytes']:,} B\n" if pipe else '') +
                f"Raw budget: {self.serial_thread.raw_queue.max_bytes:,} B; decoded budget: {worker.queue.max_bytes:,} B; "
                f"archive budget: {self._archive_writer.max_pending_bytes:,} B\n"
                f"Worker max: {state['worker_duration_max_s']*1000:.1f} ms; "
                f"render: {getattr(self, '_pipeline_render_duration_s', 0)*1000:.1f} ms")

    def _finish_acquisition_pipeline(self):
        worker = getattr(self, '_acquisition_worker', None)
        if worker is None or getattr(self, '_capture_finishing', False):
            return
        self._capture_finishing = True
        from serial_communication.capture_awake import set_capture_awake
        set_capture_awake(False)
        if self.serial_thread:
            try:
                # This ordered decoder barrier flushes the final partial host batch.
                self.serial_thread.set_capturing(False)
                self.serial_thread.configure_batch_consumer(None, worker.generation)
            except Exception as exc:
                self._capture_incomplete_reason = str(exc)
        worker.stop_nowait()
        deadline = time.perf_counter() + 15
        while worker.is_alive() and time.perf_counter() < deadline:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            worker.join(0.01)
        if worker.is_alive():
            raise RuntimeError('acquisition drain timed out; restart is blocked until the worker exits')
        self._acquisition_render_timer.stop()
        self._refresh_live_acquisition()
        error = getattr(self, '_capture_incomplete_reason', None) or worker.error
        diagnostics = {}
        if self.adc_session is not None and self.serial_thread is not None and self.serial_thread.running and self.serial_port and self.serial_port.is_open:
            from config.boards.settings import context_for
            from serial_communication.protocols.registry import protocol_adapter
            status = protocol_adapter(context_for(self)).stopped_status(self.adc_session)
            diagnostics = dict(status.stream_diagnostics) if status else {}
        reader = self.serial_thread.pipeline_status() if self.serial_thread else {}
        if not error and reader.get('accepted_frames', worker.count) != worker.count:
            error = 'Accepted frame count does not match processed/archived sweeps'
        if not error and (reader.get('parser_rejections') or reader.get('trailing_capture_bytes')):
            error = 'Parser rejected frames or capture ended with a partial frame'
        if not error and diagnostics.get('usb_frames_sent', worker.count) != worker.count:
            error = 'Stopped device frame count does not match received sweeps'
        self._capture_incomplete_reason = error
        self.capture_summary = dict(generation=worker.generation, complete=not bool(error),
            interruption=error, received_sweeps=worker.count, transmission_gaps=worker.gaps,
            device_diagnostics=diagnostics, parser_rejections=reader.get('parser_rejections', 0),
            ghost_baseline_changes=worker.baseline_changes,
            reader=reader, processing={k: v for k, v in worker.snapshot().items() if k not in ('baselines', 'force_result')},
            gap_policy='reset state at received intervals > max(10 us, 3 normal periods); reject affected FFT/PSD windows')
        if self._archive_writer:
            self._archive_writer.final_summary = self.capture_summary
            pending = getattr(self, '_pending_archive_completions', [])
            pending.append((self._archive_writer, self.capture_summary))
            self._pending_archive_completions = pending
            if not hasattr(self, '_archive_completion_timer'):
                self._archive_completion_timer = QTimer(self)
                self._archive_completion_timer.setInterval(200)
                self._archive_completion_timer.timeout.connect(self._watch_acquisition_archive)
            self._archive_completion_timer.start()
        self._legacy_sweep_count = self._legacy_write_index = worker.count
