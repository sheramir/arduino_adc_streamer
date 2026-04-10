"""
Force Session Controller
========================
Owns the force serial-port transport and reader-thread wiring.
"""

from __future__ import annotations

import time

import serial

from config_constants import (
    FORCE_SENSOR_BAUD_RATE,
    FORCE_SENSOR_STARTUP_DELAY_SEC,
    FORCE_THREAD_STOP_TIMEOUT_MS,
)
from serial_communication.serial_threads import ForceReaderThread


class ForceSessionController:
    """Controller for the force-sensor serial transport and reader thread."""

    def __init__(self, on_force_data, on_error):
        self.on_force_data = on_force_data
        self.on_error = on_error
        self.serial_port = None
        self.serial_thread = None

    def connect(self, port_name: str):
        """Open the force serial port and start the reader thread."""
        port = serial.Serial(
            port=port_name,
            baudrate=FORCE_SENSOR_BAUD_RATE,
            timeout=1.0,
        )

        thread = None
        try:
            time.sleep(FORCE_SENSOR_STARTUP_DELAY_SEC)
            port.reset_input_buffer()

            thread = ForceReaderThread(port)
            thread.force_data_received.connect(self.on_force_data)
            thread.error_occurred.connect(self.on_error)
            thread.start()
        except Exception:
            try:
                if thread is not None:
                    thread.stop()
                    thread.wait(FORCE_THREAD_STOP_TIMEOUT_MS)
            except Exception:
                pass
            try:
                if port.is_open:
                    port.close()
            except Exception:
                pass
            raise

        self.serial_port = port
        self.serial_thread = thread
        return self.serial_port, self.serial_thread

    def disconnect(self, *, thread_wait_ms: int = FORCE_THREAD_STOP_TIMEOUT_MS):
        """Stop the reader thread and close the force serial port."""
        warnings = []
        thread = self.serial_thread

        if thread:
            try:
                thread.stop()
                if not thread.wait(thread_wait_ms):
                    warnings.append("Force serial thread shutdown timed out; continuing disconnect")
            except Exception as exc:
                warnings.append(f"Force serial thread did not stop cleanly: {exc}")
            self.serial_thread = None

        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception as exc:
                warnings.append(f"Failed to close force serial port cleanly: {exc}")

        self.serial_port = None
        return warnings
