"""
ADC Filter Worker
=================
Background worker for latest-only ADC display filtering.
"""

from __future__ import annotations

import queue

from PyQt6.QtCore import QThread, pyqtSignal

from data_processing.adc_filter_engine import ADCFilterEngine


class ADCFilterWorkerThread(QThread):
    """Background worker that filters ADC windows away from the GUI thread."""

    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue(maxsize=1)
        self._running = True
        self._engine = ADCFilterEngine()
        self._last_signature = None
        self._runtime_plan = {}
        self._last_generation = None

    def submit(self, payload: dict):
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
                mode = str(payload.get("mode", "timeseries_window"))
                generation = int(payload.get("generation", 0))
                if generation != self._last_generation:
                    self._last_signature = None
                    self._runtime_plan = {}
                    self._last_generation = generation

                channel_rates = payload.get("channel_fs_by_channel") or {}
                signature = payload["signature"]
                if signature != self._last_signature:
                    self._runtime_plan = self._engine.build_runtime_plan(
                        payload["settings"],
                        payload["total_fs_hz"],
                        payload["channels"],
                        payload["repeat_count"],
                        sweep_timestamps_sec=payload.get("sweep_timestamps_sec"),
                        channel_fs_by_channel=channel_rates,
                    )
                    self._last_signature = signature

                if mode == "timeseries_window":
                    self._engine.reset_runtime_states(self._runtime_plan)
                    filtered_window = self._engine.filter_block(self._runtime_plan, payload["window_data"])
                    self.result_ready.emit({
                        "mode": mode,
                        "generation": payload.get("generation", 0),
                        "snapshot_key": payload["snapshot_key"],
                        "sweep_timestamps_sec": payload["sweep_timestamps_sec"],
                        "filtered_data": filtered_window,
                        "display_sweeps": payload.get("display_sweeps", 0),
                    })
                    continue

                filtered_block = self._engine.filter_block(self._runtime_plan, payload["block_data"])
                self.result_ready.emit({
                    "mode": mode,
                    "generation": payload.get("generation", 0),
                    "write_base": payload["write_base"],
                    "sweeps_in_block": payload["sweeps_in_block"],
                    "filtered_block": filtered_block,
                })
            except Exception as exc:
                self.error_occurred.emit(str(exc))

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
