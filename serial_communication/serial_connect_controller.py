"""
Serial Connect Controller
==========================
Generic glue between a `SerialConnectWorker` and one device's connection
state/view-state, so the ADC and Force serial mixins do not each hand-roll
the same "guard on state, flip to CONNECTING, submit, apply the outcome"
sequence.

Device-specific work (MCU detection handling, force calibration, transport
sync, logging) stays in the owning mixin via the on_success/on_failure hooks
passed to the constructor; this controller only owns the state machine and
worker wiring that both devices need identically.
"""

from __future__ import annotations

from typing import Callable


class SerialConnectController:
    """Coordinates one device's async connect lifecycle against a background worker."""

    def __init__(
        self,
        *,
        worker,
        get_state: Callable[[], object],
        set_state: Callable[[object], None],
        disconnected_state,
        connecting_state,
        connected_state,
        apply_view_state: Callable[[object], None],
        connecting_view_state: Callable[[], object],
        connected_view_state: Callable[[], object],
        disconnected_view_state: Callable[[], object],
        on_success: Callable[[object], None],
        on_failure: Callable[[str], None],
    ):
        self._worker = worker
        self._get_state = get_state
        self._set_state = set_state
        self._disconnected_state = disconnected_state
        self._connecting_state = connecting_state
        self._connected_state = connected_state
        self._apply_view_state = apply_view_state
        self._connecting_view_state = connecting_view_state
        self._connected_view_state = connected_view_state
        self._disconnected_view_state = disconnected_view_state
        self._on_success = on_success
        self._on_failure = on_failure

        worker.connected.connect(self._handle_connected)
        worker.failed.connect(self._handle_failed)

    def is_disconnected(self) -> bool:
        return self._get_state() == self._disconnected_state

    def start(self, session, port_name: str, **workflow_kwargs) -> bool:
        """Submit a connect job; returns False without effect if not currently disconnected."""
        if not self.is_disconnected():
            return False

        self._set_state(self._connecting_state)
        self._apply_view_state(self._connecting_view_state())
        self._worker.submit(session, port_name, **workflow_kwargs)
        return True

    def _handle_connected(self, outcome) -> None:
        self._set_state(self._connected_state)
        self._apply_view_state(self._connected_view_state())
        self._on_success(outcome)

    def _handle_failed(self, message: str) -> None:
        self._set_state(self._disconnected_state)
        self._apply_view_state(self._disconnected_view_state())
        self._on_failure(message)
