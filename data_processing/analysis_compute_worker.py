"""
Analysis Compute Worker
========================
Background worker that runs prepare_analysis_data() off the GUI thread so
switching to the Analysis tab, or changing its controls, never blocks the UI.
"""

from __future__ import annotations

import queue

from PyQt6.QtCore import QThread, pyqtSignal

from data_processing.analysis_workbench import prepare_analysis_data


class AnalysisComputeWorker(QThread):
    """Runs prepare_analysis_data() in a dedicated thread.

    The queue is bounded to 1: a fresh submission evicts a still-pending one,
    so only the latest requested render is ever computed.
    """

    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self._queue: queue.Queue[object] = queue.Queue(maxsize=1)
        self._running = True

    def submit(self, payload: dict) -> None:
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(payload)
        except Exception:
            pass

    def run(self) -> None:
        while self._running:
            try:
                payload = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if payload is None:
                break

            generation = int(payload.get("generation", 0))
            try:
                prepared = prepare_analysis_data(
                    payload["snapshot"],
                    axis_mode=payload["axis_mode"],
                    visible_labels=payload["visible_labels"],
                    filter_enabled=payload["filter_enabled"],
                    filter_settings=payload["filter_settings"],
                    overlay_flags=payload["overlay_flags"],
                    vref_voltage=payload["vref_voltage"],
                    integration_window_samples=payload["integration_window_samples"],
                    hpf_cutoff_hz=payload["hpf_cutoff_hz"],
                    pzt_force_settings=payload["pzt_force_settings"],
                )
                self.result_ready.emit({
                    "generation": generation,
                    "prepared": prepared,
                    "auto_range": payload.get("auto_range", False),
                })
            except Exception as exc:
                self.error_occurred.emit(generation, str(exc))

    def stop(self) -> None:
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
