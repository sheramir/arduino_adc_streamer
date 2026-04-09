"""
ADC Configuration Runner
========================
Runs ADC configuration retries on a background thread without touching GUI widgets.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class ADCConfigurationRunOutcome:
    result: object | None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        return bool(self.result and getattr(self.result, "success", False))


class ADCConfigurationRunner:
    """Own the background worker for ADC configuration attempts."""

    def __init__(self, configuration_service):
        self.configuration_service = configuration_service
        self._lock = threading.Lock()
        self._running = False
        self._completed_outcome: ADCConfigurationRunOutcome | None = None

    def start(self, serial_port, request, *, max_attempts: int = 3):
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._completed_outcome = None

        def worker():
            outcome = ADCConfigurationRunOutcome(result=None)
            try:
                if not serial_port or not getattr(serial_port, "is_open", False):
                    return

                serial_port.reset_input_buffer()
                serial_port.reset_output_buffer()
                time.sleep(0.05)

                for _attempt in range(max_attempts):
                    result = self.configuration_service.send_config_with_verification(request)
                    outcome = ADCConfigurationRunOutcome(result=result)
                    if result.success:
                        break
                    time.sleep(0.05)
            except Exception as exc:
                outcome = ADCConfigurationRunOutcome(result=None, error_message=f"Configuration error: {exc}")
            finally:
                with self._lock:
                    self._completed_outcome = outcome
                    self._running = False

        threading.Thread(target=worker, daemon=True).start()
        return True

    def take_outcome(self) -> ADCConfigurationRunOutcome | None:
        with self._lock:
            if self._running or self._completed_outcome is None:
                return None
            outcome = self._completed_outcome
            self._completed_outcome = None
            return outcome

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running
