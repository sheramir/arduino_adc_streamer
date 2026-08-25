"""Background worker that runs PZT force-block integration off the GUI thread."""

from __future__ import annotations

import queue
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

from data_processing.pressure_force_display import PressureForceDisplayEngine

if TYPE_CHECKING:
    pass


class WorkerState(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


_RESET_SENTINEL = object()
_STOP_SENTINEL = object()


@dataclass(frozen=True)
class ForceBlockBatch:
    sweeps: np.ndarray                # shape (N, samples_per_sweep)
    timestamps: np.ndarray            # shape (N,)
    first_sweep_id: int
    dt_s: float
    voltage_scale: float
    ghost_net_centered: bool
    repeat_slots: int
    complete_packages: dict           # deep-copied snapshot
    baselines: dict                   # copied snapshot
    polarity_multiplier: float
    mux_timing: object | None         # reference ok — immutable during capture
    jerk_shapes: list | None          # shallow copy of latest jerk package_displays
    dropped_sweeps_before: int        # counter only, not physics
    grid_positions: dict              # from _get_force_display_grid_positions()
    channel_calibration: dict         # sign-only polarity per package/position


@dataclass
class ForceRenderResult:
    package_results: list
    array_result: object | None
    dropped_sweeps: int


class ForceBlockWorker(QThread):
    """Runs force-block integration in a dedicated thread.

    The GUI thread enqueues ``ForceBlockBatch`` objects; this worker drains
    them and emits ``result_ready`` with a ``ForceRenderResult`` after each
    batch.  The queue is bounded to 1: a full queue drops the old batch so
    the newest physics data is always processed.
    """

    result_ready = pyqtSignal(object)

    def __init__(self, engine: PressureForceDisplayEngine) -> None:
        super().__init__()
        self._engine = engine
        self._queue: queue.Queue[object] = queue.Queue(maxsize=1)
        self._state = WorkerState.RUNNING

    # ------------------------------------------------------------------
    # Public interface (called from GUI thread)
    # ------------------------------------------------------------------

    def enqueue_batch(self, batch: ForceBlockBatch) -> int:
        """Enqueue a batch; return number of sweeps dropped from the old batch."""
        try:
            self._queue.put_nowait(batch)
            return 0
        except queue.Full:
            pass
        # Queue full — evict the stale batch and insert the fresh one.
        try:
            old = self._queue.get_nowait()
        except queue.Empty:
            old = None
        dropped = int(old.sweeps.shape[0]) if isinstance(old, ForceBlockBatch) else 0
        try:
            self._queue.put_nowait(batch)
        except queue.Full:
            pass
        return dropped

    def send_reset(self) -> None:
        """Drain queue and enqueue a RESET sentinel."""
        self._drain_queue()
        try:
            self._queue.put_nowait(_RESET_SENTINEL)
        except queue.Full:
            pass

    def swap_engine(self, new_engine: PressureForceDisplayEngine) -> None:
        """Replace the engine atomically: drain, then enqueue an engine object."""
        self._drain_queue()
        try:
            self._queue.put_nowait(new_engine)
        except queue.Full:
            pass

    def set_state(self, state: WorkerState) -> None:
        """Change operational state.  PAUSED drains the queue; RUNNING → reset."""
        was_paused = self._state is WorkerState.PAUSED
        self._state = state
        if state is WorkerState.PAUSED:
            self._drain_queue()
        elif state is WorkerState.RUNNING and was_paused:
            self._engine.reset()

    def drain_synchronous(self) -> None:
        """Test-only: process everything in the queue on the calling thread."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            self._handle_item(item)

    # ------------------------------------------------------------------
    # QThread run loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        while self._state is not WorkerState.STOPPING:
            try:
                item = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if self._state is WorkerState.PAUSED:
                continue
            self._handle_item(item)

    def _handle_item(self, item: object) -> None:
        if item is _RESET_SENTINEL or item is _STOP_SENTINEL:
            self._engine.reset()
            return
        if isinstance(item, PressureForceDisplayEngine):
            self._engine = item
            return
        if isinstance(item, ForceBlockBatch):
            self._process_batch(item)

    # ------------------------------------------------------------------
    # Batch processing (runs on worker thread)
    # ------------------------------------------------------------------

    def _process_batch(self, batch: ForceBlockBatch) -> None:
        try:
            self._integrate_sweeps(batch)
            if batch.jerk_shapes:
                self._engine.apply_jerk_shapes(batch.jerk_shapes)
            result = ForceRenderResult(
                package_results=self._engine.package_results(),
                array_result=self._engine.array_result(),
                dropped_sweeps=batch.dropped_sweeps_before,
            )
            self.result_ready.emit(result)
        except ValueError as exc:
            # Discontinuity (restart/buffer gap) — reset engine state and
            # continue from the next batch.  Never call back into GUI thread.
            self._engine.reset()
            _ = exc  # discontinuity logged by caller via status label indirectly

    def _integrate_sweeps(self, batch: ForceBlockBatch) -> None:
        """Integrate every sweep in batch through the force engine."""
        for row_index in range(batch.sweeps.shape[0]):
            self._integrate_sweep(batch, row_index)

    def _integrate_sweep(self, batch: ForceBlockBatch, row_index: int) -> None:
        """Integrate one sweep (all repeat slots) into the engine."""
        sweep = batch.sweeps[row_index]
        for repeat_index in range(batch.repeat_slots):
            voltages, times, leak_times, pre_times = self._build_sample_dicts(
                batch, sweep, row_index, repeat_index
            )
            self._engine.process_sample(
                (int(batch.first_sweep_id) + row_index, repeat_index),
                voltages,
                times,
                grid_positions=batch.grid_positions,
                observations_per_sweep=batch.repeat_slots,
                leak_dt_s=leak_times,
                pre_sample_decay_dt_s=pre_times,
                channel_calibration=batch.channel_calibration,
            )

    def _build_sample_dicts(
        self,
        batch: ForceBlockBatch,
        sweep: np.ndarray,
        row_index: int,
        repeat_index: int,
    ) -> tuple[dict, dict, dict, dict]:
        """Build per-position voltage/timing dicts for one repeat slot."""
        voltages: dict[str, dict[str, float]] = {}
        times: dict[str, dict[str, float]] = {}
        leak_times: dict[str, dict[str, float]] = {}
        pre_times: dict[str, dict[str, float]] = {}
        for package_id, positions in batch.complete_packages.items():
            pkg_v, pkg_t, pkg_l, pkg_p = self._build_package_dicts(
                batch, sweep, row_index, repeat_index, package_id, positions
            )
            voltages[package_id] = pkg_v
            times[package_id] = pkg_t
            leak_times[package_id] = pkg_l
            pre_times[package_id] = pkg_p
        return voltages, times, leak_times, pre_times

    def _build_package_dicts(
        self,
        batch: ForceBlockBatch,
        sweep: np.ndarray,
        row_index: int,
        repeat_index: int,
        package_id: str,
        positions: dict,
    ) -> tuple[dict, dict, dict, dict]:
        """Build per-position dicts for one package."""
        from constants.shear import SHEAR_SENSOR_POSITIONS
        pkg_v: dict[str, float] = {}
        pkg_t: dict[str, float] = {}
        pkg_l: dict[str, float] = {}
        pkg_p: dict[str, float] = {}
        for position, spec in positions.items():
            sample_index = int(spec["sample_indices"][repeat_index])
            baseline = 0.0 if batch.ghost_net_centered else float(
                batch.baselines.get(spec.get("key"), 0.0)
            )
            centered_counts = float(sweep[sample_index]) - baseline
            raw_voltage = centered_counts * batch.voltage_scale * batch.polarity_multiplier
            pkg_v[position] = raw_voltage
            pkg_t[position] = (
                float(batch.timestamps[row_index]) + float(sample_index) * batch.dt_s
            )
            self._apply_mux_timing(
                batch, spec, repeat_index, sample_index, row_index, position, pkg_t, pkg_l, pkg_p
            )
        return pkg_v, pkg_t, pkg_l, pkg_p

    def _apply_mux_timing(
        self,
        batch: ForceBlockBatch,
        spec: dict,
        repeat_index: int,
        sample_index: int,
        row_index: int,
        position: str,
        pkg_t: dict,
        pkg_l: dict,
        pkg_p: dict,
    ) -> None:
        """Overwrite channel time with MUX-model values when available."""
        if batch.mux_timing is None:
            return
        from data_processing.pzt_decay_timing import PztDecayTimingContext
        key = spec.get("key")
        adc_input = key[4] if isinstance(key, tuple) and len(key) >= 5 else None
        try:
            adc_input = int(adc_input)
            if adc_input not in (1, 2):
                return
            timing_context = PztDecayTimingContext.from_adc_mux_timing(
                batch.mux_timing, adc_input
            )
            first_index = int(spec["sample_indices"][0])
            pkg_t[position] = (
                float(batch.timestamps[row_index]) + float(first_index) * batch.dt_s
                + timing_context.observation_offset_s(repeat_index)
                - timing_context.observation_offset_s(0)
            )
            previous_repeat = batch.repeat_slots - 1 if repeat_index == 0 else repeat_index - 1
            pkg_l[position] = timing_context.connected_exposure_between(
                previous_repeat, repeat_index
            )
            pkg_p[position] = float(
                batch.mux_timing.decay_before_effective_sample_s(
                    adc_input=adc_input, repeat_index=repeat_index
                )
            )
        except (TypeError, ValueError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
