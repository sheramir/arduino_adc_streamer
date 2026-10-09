"""Widget-free timed-sweep ingestion; one ordered consumer per generation."""
from copy import deepcopy
import json
import threading
import time

import numpy as np

from constants.plotting import PZR_AUTO_BASELINE_DELAY_SEC, PZR_ZERO_BASELINE_WINDOW_SEC
from data_processing.acquisition_queue import AcquisitionQueue, AcquisitionOverrun
from data_processing.acquisition_timing import DeviceTimeline, gap_indices
from data_processing.adc_filter_engine import ADCFilterEngine
from data_processing.circular_buffer import recent_window_slices, take_recent
from data_processing.pzt_blip_filter import PztBlipFilterMixin
from data_processing.pzt_ghost_removal import PztGhostRemovalMixin


class AcquisitionWorker(threading.Thread, PztGhostRemovalMixin, PztBlipFilterMixin):
    def __init__(self, descriptor, generation, buffer_lock, capacity, writer, *, ghost_enabled=False, attenuation=0.1):
        super().__init__(name='ADCAcquisition', daemon=True)
        self.descriptor = deepcopy(descriptor)
        self.generation = generation
        self.buffer_lock = buffer_lock
        self.capacity = capacity
        self.writer = writer
        self.width = len(descriptor['ordered_routes'])
        self.raw = np.zeros((capacity, self.width), dtype=np.float32)
        self.processed = np.zeros_like(self.raw)
        self.times = np.zeros(capacity, dtype=np.float64)
        self.count = 0
        self.queue = AcquisitionQueue(max_bytes=32 * 1024 * 1024, max_items=2048)
        self.timeline = DeviceTimeline()
        self.error = None
        self._closing = threading.Event()
        self._options_lock = threading.Lock()
        self._options = {}
        self._groups = tuple(tuple(i for i, route in enumerate(descriptor['ordered_routes']) if route[0] == lane)
                             for lane in sorted({route[0] for route in descriptor['ordered_routes']}))
        self._init_pzt_ghost_removal_state()
        self._init_pzt_blip_filter_state()
        self._pzt_blip_column_indices = np.arange(self.width, dtype=np.int32)
        self.pzt_ghost_removal_enabled = ghost_enabled
        self.pzt_ghost_attenuation = attenuation
        self._baseline_pending = ghost_enabled
        self._pending = []
        self._pending_bytes = 0
        self._initial = []
        self._initial_count = 0
        self.baselines = None
        self.baseline_changes = []
        self.filter_engine = ADCFilterEngine()
        self._filter_plan = {}
        self._filter_signature = None
        self._force_signature = None
        self._force_consumer = None
        self.latest_force_result = None
        self._last_force_render = 0.0
        self.last_arrival = self.last_processed = self.last_decoded = None
        self.last_device_time = None
        self.nominal_period = None
        self.last_end_us = None
        self.gaps = 0
        self.active_duration_us = self.gap_duration_us = 0
        self.avg_us = 0
        self.worker_duration_max_s = self.decode_to_process_max_s = 0.0

    def _get_pzt_ghost_groups(self, width):
        return self._groups

    def should_remove_pzt_ghost(self):
        return self.pzt_ghost_removal_enabled

    def set_options(self, options):
        with self._options_lock:
            self._options = deepcopy(options)

    def enqueue(self, batch):
        if batch['generation'] != self.generation:
            raise RuntimeError('old capture generation reached acquisition worker')
        if self.error:
            raise AcquisitionOverrun(self.error)
        if self._closing.is_set():
            raise AcquisitionOverrun('acquisition worker is closed')
        size = sum(batch[k].nbytes for k in ('samples', 'avg_us', 'starts', 'ends'))
        try:
            self.queue.put(batch, size=size, sweeps=len(batch['starts']), arrival=batch['arrival'])
        except AcquisitionOverrun as exc:
            raise AcquisitionOverrun('decoded acquisition queue budget exceeded; capture incomplete') from exc

    def stop_nowait(self):
        self._closing.set()

    def snapshot(self):
        with self.buffer_lock:
            return dict(generation=self.generation, sweeps=self.count, avg_us=self.avg_us,
                        last_arrival=self.last_arrival, last_processed=self.last_processed,
                        last_decoded=self.last_decoded,
                        baselines=None if self.baselines is None else self.baselines.copy(),
                        gaps=self.gaps, active_duration_us=self.active_duration_us,
                        gap_duration_us=self.gap_duration_us,
                        worker_duration_max_s=self.worker_duration_max_s,
                        decode_to_process_max_s=self.decode_to_process_max_s,
                        nominal_period_s=self.nominal_period, error=self.error,
                        decoded=self.queue.snapshot(), calibration_pending_bytes=self._pending_bytes,
                        force_result=self.latest_force_result)

    def run(self):
        try:
            while not self._closing.is_set() or self.queue.snapshot()['items']:
                batch = self.queue.get()
                if batch is None:
                    continue
                start = time.perf_counter()
                if isinstance(batch, tuple) and batch[0] == 'baseline':
                    self._adopt_baselines(batch[1], batch[2])
                    continue
                self.decode_to_process_max_s = max(self.decode_to_process_max_s, start - batch['decoded'])
                self.process_batch(batch)
                self.worker_duration_max_s = max(self.worker_duration_max_s, time.perf_counter() - start)
            self.finish_pending()
            self._publish_force_result(force=True)
        except Exception as exc:
            self.error = str(exc)

    def request_baselines(self, baselines, noise):
        if not self.should_remove_pzt_ghost() or not self.is_alive():
            return
        try:
            self.queue.put(('baseline', baselines.copy(), noise.copy()), size=baselines.nbytes + noise.nbytes)
        except AcquisitionOverrun as exc:
            self.error = str(exc)

    def _adopt_baselines(self, baselines, noise):
        with self.buffer_lock:
            slices = recent_window_slices(self.count, self.count, self.capacity, self.capacity)
            old = self.reconstruct_pzt_signal_for_baseline_capture(take_recent(self.raw, slices))
            self.baselines = self._pzt_ghost_baselines = baselines
            self._pzt_ghost_noise = noise
            if len(old):
                positions = np.arange(self.count - len(old), self.count) % self.capacity
                self.raw[positions] = self._apply_pzt_ghost_removal(old)
                self.processed[positions] = self.raw[positions]
        self.begin_pzt_blip_filter_capture()
        self.filter_engine.reset_runtime_states(self._filter_plan)
        if self._force_consumer is not None:
            self._force_consumer._engine.reset()
        self.baseline_changes.append(dict(timestamp_s=self.last_device_time, counts=baselines.tolist()))

    def finish_pending(self):
        if self._pending:
            self._finish_baseline()
        if self._initial:
            self._consume_initial(final=True)

    def _consume_initial(self, final=False):
        if not self._initial or (not final and self._initial_count < 101):
            return
        raw = np.concatenate([p[0] for p in self._initial])
        times = np.concatenate([p[1] for p in self._initial])
        rows = [r for p in self._initial for r in p[2]]
        deltas = np.diff(times[:101])
        self.nominal_period = float(np.median(deltas)) if len(deltas) else max(1e-6, self.avg_us * self.width / 1e6)
        self._initial = []
        self._initial_count = 0
        self._consume(raw, times, rows)

    def process_batch(self, batch):
        if batch['generation'] != self.generation:
            raise RuntimeError('capture generation mismatch')
        block = batch['samples']
        if block.ndim != 2 or block.shape[1] != self.width or len(block) != len(batch['starts']):
            raise ValueError('invalid acquisition batch shape')
        times = self.timeline.extend(batch['starts'])
        spans = (batch['ends'].astype(np.int64) - batch['starts'].astype(np.int64)) & 0xFFFFFFFF
        ends = np.concatenate(([batch['starts'][0] if self.last_end_us is None else self.last_end_us], batch['ends'][:-1]))
        gap_us = (batch['starts'].astype(np.int64) - ends) & 0xFFFFFFFF
        if self.last_end_us is None:
            gap_us[0] = 0
        if np.any(gap_us >= 0x80000000):
            raise ValueError('overlapping or out-of-order device frames')
        self.last_end_us = int(batch['ends'][-1])
        self.active_duration_us += int(spans.sum())
        self.gap_duration_us += int(gap_us.sum())
        self.avg_us = float(np.mean(batch['avg_us']))
        timing_rows = np.column_stack((np.full(len(block), self.width), np.full(len(block), self.width),
                                      np.ones(len(block), dtype=int), batch['avg_us'], batch['starts'], batch['ends'], gap_us)).tolist()
        self.last_arrival = batch['arrival']
        self.last_decoded = batch['decoded']
        if self._baseline_pending:
            self._pending.append((block, times, timing_rows))
            self._pending_bytes += block.nbytes + times.nbytes + len(timing_rows) * 384
            if self._pending_bytes > 64 * 1024 * 1024:
                raise AcquisitionOverrun('ghost calibration queue budget exceeded')
            if times[-1] >= PZR_AUTO_BASELINE_DELAY_SEC:
                self._finish_baseline()
        else:
            self._consume(block, times, timing_rows)

    def _finish_baseline(self):
        raw = np.concatenate([p[0] for p in self._pending]).astype(np.float32)
        times = np.concatenate([p[1] for p in self._pending])
        baseline_window = raw[times >= times[-1] - PZR_ZERO_BASELINE_WINDOW_SEC][-self.capacity:]
        self.baselines = np.median(baseline_window, axis=0).astype(np.float32)
        self._pzt_ghost_baselines = self.baselines
        self._pzt_ghost_noise = (1.4826 * np.median(np.abs(baseline_window - self.baselines), axis=0)).astype(np.float32)
        self._baseline_pending = False
        pending, self._pending = self._pending, []
        self._pending_bytes = 0
        for block, times, rows in pending:
            self._consume(block, times, rows)

    def _consume(self, raw, times, timing_rows):
        if self.nominal_period is None:
            self._initial.append((raw, times, timing_rows))
            self._initial_count += len(raw)
            self._consume_initial()
            return
        with self._options_lock:
            options = self._options
        gaps = gap_indices(times, previous=self.last_device_time, nominal=self.nominal_period)
        self.gaps += len(gaps)
        self.last_device_time = float(times[-1])
        block = self.prepare_pzt_ghost_block(raw.astype(np.float32))
        archive = block.copy()
        filtered = np.empty_like(block)
        sample_intervals = np.asarray([row[3] for row in timing_rows], dtype=np.float64) / 1e6
        # Each contiguous segment starts with fresh state after a missing interval.
        boundaries = np.unique(np.concatenate(([0], gaps, [len(block)])))
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            if start in gaps:
                self.begin_pzt_blip_filter_capture()
                self.filter_engine.reset_runtime_states(self._filter_plan)
                if self._force_consumer is not None:
                    self._force_consumer._engine.reset()
            block[start:end], archive[start:end] = self.prepare_pzt_blip_filter_blocks(block[start:end], archive[start:end])
            filtered[start:end] = self._filter(block[start:end], options)
            self._force(block[start:end], times[start:end], self.count + start, options, sample_intervals[start:end])
        archive = archive if self.should_remove_pzt_ghost() else raw
        if self.writer is not None and not self.writer.enqueue(times, archive, timing_rows=timing_rows):
            raise AcquisitionOverrun(self.writer.get_status_snapshot()['last_error'] or 'archive failed')
        with self.buffer_lock:
            keep = min(len(block), self.capacity)
            positions = (self.count + np.arange(len(block) - keep, len(block))) % self.capacity
            self.raw[positions] = block[-keep:]
            self.processed[positions] = filtered[-keep:]
            self.times[positions] = times[-keep:]
            self.count += len(block)
            self.last_processed = time.perf_counter()
        self._publish_force_result()

    def _filter(self, block, options):
        settings = options.get('filter')
        signature = json.dumps(settings, sort_keys=True)
        if signature != self._filter_signature:
            self._filter_plan = {}
            self._filter_signature = signature
            if settings is not None:
                index_map = {s['label']: np.asarray(s['sample_indices'], dtype=np.int32) for s in self.descriptor['channel_specs']}
                self._filter_plan = self.filter_engine.build_runtime_plan(settings, 1 / self.nominal_period,
                    [], 1, index_map=index_map, channel_fs_by_channel={k: 1 / self.nominal_period for k in index_map})
        return self.filter_engine.filter_block(self._filter_plan, block.copy()) if self._filter_plan else block

    def _force(self, block, times, first_id, options, sample_intervals):
        force = options.get('force')
        if force is None:
            return
        if force['revision'] != self._force_signature:
            from data_processing.force_block_worker import ForceBlockWorker
            from data_processing.pressure_force_display import PressureForceDisplayEngine
            self._force_consumer = ForceBlockWorker(PressureForceDisplayEngine(geometry=force['geometry'], settings=force['settings']))
            self._force_signature = force['revision']
        from data_processing.force_block_worker import ForceBlockBatch
        baselines = force['baselines']
        if self.baselines is not None:
            baselines = {tuple(s['key']): float(self.baselines[s['sample_indices'][0]]) for s in self.descriptor['channel_specs']}
        if any(tuple(s['key']) not in baselines for p in force['packages'].values() for s in p.values()):
            return
        batch = ForceBlockBatch(block, times, first_id, self.avg_us / 1e6,
            force['voltage_scale'], self.should_remove_pzt_ghost(), 1, force['packages'], baselines,
            force['polarity'], None, None, 0, force['grid_positions'], force['calibration'], sample_intervals_s=sample_intervals)
        self._force_consumer._integrate_sweeps(batch)

    def _publish_force_result(self, force=False):
        if self._force_consumer is None or (not force and time.perf_counter() - self._last_force_render < 0.2):
            return
        self.latest_force_result = self._force_consumer.build_render_result()
        self._last_force_render = time.perf_counter()
