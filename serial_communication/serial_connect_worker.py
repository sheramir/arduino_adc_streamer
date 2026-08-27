"""
Serial Connect Worker
======================
Generic background worker that runs a connection workflow's connect() call
off the GUI thread, so opening a serial port (Arduino reset delay, MCU
handshake, sensor startup delay, ...) never freezes the UI. Shared by the
ADC and Force serial mixins instead of each owning its own worker thread.
"""

from __future__ import annotations

import queue

from PyQt6.QtCore import QThread, pyqtSignal


class SerialConnectWorker(QThread):
    """Persistent worker thread that runs `workflow.connect(session, port_name, **kwargs)` jobs.

    One job is in flight at a time in practice (each mixin refuses to start
    a new connect while one is already CONNECTING), but the worker stays
    alive across attempts rather than being recreated per-connect, so there
    is never a live QThread torn down mid-run.
    """

    connected = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, workflow):
        super().__init__()
        self._workflow = workflow
        self._queue: queue.Queue[object] = queue.Queue()
        self._running = True

    def submit(self, session, port_name: str, **workflow_kwargs) -> None:
        self._queue.put((session, port_name, workflow_kwargs))

    def run(self) -> None:
        while self._running:
            try:
                job = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if job is None:
                break

            session, port_name, workflow_kwargs = job
            try:
                outcome = self._workflow.connect(session, port_name, **workflow_kwargs)
                self.connected.emit(outcome)
            except Exception as exc:
                self.failed.emit(str(exc))

    def stop(self) -> None:
        self._running = False
        self._queue.put(None)
