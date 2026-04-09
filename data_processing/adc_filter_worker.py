"""
ADC Filter Worker
=================
Background worker for live ADC-only filtering.
"""

from __future__ import annotations

import queue

from PyQt6.QtCore import QThread, pyqtSignal

from data_processing.adc_filter_engine import ADCFilterEngine


class ADCFilterWorkerThread(QThread):
    """Background worker that filters ADC blocks away from the GUI thread."""

    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue()
        self._running = True
        self._engine = ADCFilterEngine()
        self._last_signature = None
        self._runtime_plan = {}

    def submit(self, payload: dict):
        try:
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
                signature = payload["signature"]
                if signature != self._last_signature:
                    self._runtime_plan = self._engine.build_runtime_plan(
                        payload["settings"],
                        payload["total_fs_hz"],
                        payload["channels"],
                        payload["repeat_count"],
                    )
                    self._engine.reset_runtime_states(self._runtime_plan)
                    self._last_signature = signature

                filtered_block = self._engine.filter_block(self._runtime_plan, payload["block_data"])
                self.result_ready.emit({
                    "write_base": payload["write_base"],
                    "sweeps_in_block": payload["sweeps_in_block"],
                    "filtered_block": filtered_block,
                })
            except Exception as exc:
                self.error_occurred.emit(str(exc))

    def stop(self):
        self._running = False
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
