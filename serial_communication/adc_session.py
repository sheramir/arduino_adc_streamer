"""
ADC Session Controller
======================
Owns the ADC serial port transport, reader thread wiring, and routed text waits.
"""

from __future__ import annotations

import time

import serial
from PyQt6.QtCore import QCoreApplication

from constants.serial import (
    ARDUINO_RESET_DELAY,
    BAUD_RATE,
    COMMAND_TERMINATOR,
    CONFIG_RETRY_DELAY,
    SERIAL_TIMEOUT,
)
from serial_communication.serial_threads import SerialReaderThread


class ADCSessionController:
    """Controller for ADC serial-port transport and request/response waits."""

    def __init__(self, on_text_line, on_binary_sweep, on_error):
        self.on_text_line = on_text_line
        self.on_binary_sweep = on_binary_sweep
        self.on_error = on_error
        self.serial_port = None
        self.serial_thread = None
        self._adc_line_waiters = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self, port_name: str):
        self.serial_port = serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_TIMEOUT,
            rtscts=True,
        )

        time.sleep(ARDUINO_RESET_DELAY)
        self.serial_port.reset_input_buffer()
        self.serial_port.reset_output_buffer()
        time.sleep(0.1)

        self.clear_line_waiters()
        self.serial_thread = SerialReaderThread(self.serial_port)
        self.serial_thread.data_received.connect(self.on_text_line)
        self.serial_thread.binary_sweep_received.connect(self.on_binary_sweep)
        self.serial_thread.error_occurred.connect(self.on_error)
        self.serial_thread.start()
        return self.serial_port, self.serial_thread

    def disconnect(self, *, thread_wait_ms: int = 250):
        warnings = []
        thread = self.serial_thread

        if thread:
            try:
                thread.stop()
                if not thread.wait(thread_wait_ms):
                    warnings.append("Serial thread shutdown timed out; continuing disconnect")
            except Exception as exc:
                warnings.append(f"Serial thread did not stop cleanly: {exc}")
            self.serial_thread = None

        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception as exc:
                warnings.append(f"Failed to close serial port cleanly: {exc}")

        self.serial_port = None
        self.clear_line_waiters()
        return warnings

    # ------------------------------------------------------------------
    # Routed ADC text handling
    # ------------------------------------------------------------------

    def clear_line_waiters(self):
        self._adc_line_waiters = []

    def handle_text_line(self, line: str) -> bool:
        """Route ADC text lines to any pending waiters.

        Returns True when a waiter consumes the line and it should not continue
        through the normal parser/log path.
        """
        waiters = list(self._adc_line_waiters)
        if not waiters:
            return False

        consumed = False
        remaining = []
        for waiter in waiters:
            matcher = waiter.get("matcher")
            if matcher is not None and matcher(line):
                waiter["matched_line"] = line
                if waiter.get("consume", False):
                    consumed = True
                continue
            remaining.append(waiter)

        self._adc_line_waiters = remaining
        return consumed

    def wait_for_line(self, matcher, timeout: float, *, consume: bool = False, send_action=None):
        """Wait for a routed ADC text line while keeping Qt responsive."""
        waiter = {
            "matcher": matcher,
            "consume": consume,
            "matched_line": None,
        }
        self._adc_line_waiters.append(waiter)
        deadline = time.time() + timeout

        try:
            if send_action is not None:
                send_action()
            while time.time() < deadline:
                if waiter["matched_line"] is not None:
                    return waiter["matched_line"]
                QCoreApplication.processEvents()
                time.sleep(0.01)
            return None
        finally:
            if waiter in self._adc_line_waiters:
                self._adc_line_waiters.remove(waiter)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @staticmethod
    def parse_ack_line(line: str):
        if line.startswith("#OK"):
            return True, line[3:].strip() if len(line) > 3 else None
        if line.startswith("#NOT_OK"):
            return False, line[7:].strip() if len(line) > 7 else None
        return None

    def send_command(self, command: str):
        if not self.serial_port or not self.serial_port.is_open:
            raise RuntimeError("Not connected to serial port")
        self.serial_port.write(f"{command}{COMMAND_TERMINATOR}".encode("utf-8"))
        self.serial_port.flush()

    def send_command_and_wait_ack(self, command: str, expected_value: str, timeout: float, max_retries: int):
        if not self.serial_port or not self.serial_port.is_open:
            return False, None

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    time.sleep(CONFIG_RETRY_DELAY)
                    self.serial_port.reset_input_buffer()
                    self.serial_port.reset_output_buffer()

                line = self.wait_for_line(
                    lambda text: text.startswith("#OK") or text.startswith("#NOT_OK"),
                    timeout,
                    consume=True,
                    send_action=lambda: self.send_command(command),
                )
                if line is None:
                    if attempt >= max_retries - 1:
                        return False, None
                    continue

                parsed = self.parse_ack_line(line)
                if parsed is None:
                    if attempt >= max_retries - 1:
                        return False, None
                    continue

                success, received_value = parsed
                if expected_value is not None and received_value != expected_value:
                    if attempt < max_retries - 1:
                        continue
                    return False, received_value
                return success, received_value
            except Exception:
                if attempt >= max_retries - 1:
                    return False, None

        return False, None

    def drain_input(self, duration: float = 0.3):
        """Drop pending ADC bytes without competing with the reader thread."""
        if not self.serial_port or not self.serial_port.is_open:
            return

        time.sleep(max(0.0, duration))
        if self.serial_thread:
            self.serial_thread.clear_buffer()
        self.serial_port.reset_input_buffer()

    # ------------------------------------------------------------------
    # MCU detection
    # ------------------------------------------------------------------

    @staticmethod
    def is_mcu_response_line(line: str) -> bool:
        if not line.startswith("#"):
            return False
        if line.startswith("#OK") or line.startswith("#NOT_OK") or line.startswith("#   "):
            return False
        payload = line[1:].strip()
        if not payload or ":" in payload:
            return False
        return True

    def detect_mcu(self, timeout: float):
        if not self.serial_port or not self.serial_port.is_open:
            return None

        line = self.wait_for_line(
            self.is_mcu_response_line,
            timeout,
            consume=True,
            send_action=lambda: self.send_command("mcu"),
        )
        if not line:
            return None
        return line[1:].strip() or None
