"""
ADC Session Controller
======================
Owns the ADC serial port transport, reader thread wiring, and routed text waits.
"""

from __future__ import annotations

import threading
import time

import serial
from PyQt6.QtCore import QCoreApplication, QThread

from constants.serial import (
    ARDUINO_RESET_DELAY,
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
        # connect() and detect_mcu() may now run on a background connect
        # worker while text lines still arrive via a GUI-thread Qt signal
        # queued connection, so waiter-list access must be thread-safe.
        self._waiters_lock = threading.Lock()
        self.board_context = None

    def set_board_context(self, context):
        self.board_context = context
        if self.serial_thread is not None:
            from serial_communication.protocols.registry import FRAME_ADAPTERS
            self.serial_thread.frame_codec = FRAME_ADAPTERS[context.mode.definition['adapters']['frame']]
        if self.serial_port is not None and self.serial_port.is_open:
            self.serial_port.baudrate = context.profile.definition['transport']['baud_rate']

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self, port_name: str, *, thread_wait_ms: int = 250):
        from config.boards import get_board_registry
        bootstrap = get_board_registry().bootstrap
        self.board_context = None
        port = serial.Serial(
            port=port_name,
            baudrate=bootstrap['baud_rate'],
            timeout=SERIAL_TIMEOUT,
            rtscts=True,
        )

        thread = None
        try:
            time.sleep(ARDUINO_RESET_DELAY)
            port.reset_input_buffer()
            port.reset_output_buffer()
            time.sleep(0.1)

            self.clear_line_waiters()
            thread = SerialReaderThread(port)
            thread.data_received.connect(self.on_text_line)
            thread.binary_sweep_received.connect(self.on_binary_sweep)
            thread.error_occurred.connect(self.on_error)
            thread.start()
        except Exception:
            # Leave no open port or running thread behind: a leaked port stays
            # locked by the OS and blocks every later reconnect attempt.
            try:
                if thread is not None:
                    thread.stop()
                    thread.wait(thread_wait_ms)
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
        with self._waiters_lock:
            self._adc_line_waiters = []

    def handle_text_line(self, line: str) -> bool:
        """Route ADC text lines to any pending waiters.

        Returns True when a waiter consumes the line and it should not continue
        through the normal parser/log path.
        """
        with self._waiters_lock:
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
        """Wait for a routed ADC text line.

        Pumps the Qt event loop only when called from the GUI thread; a
        background connect worker just polls, since the GUI thread's own
        event loop delivers the queued text-line signal independently.
        """
        waiter = {
            "matcher": matcher,
            "consume": consume,
            "matched_line": None,
        }
        with self._waiters_lock:
            self._adc_line_waiters.append(waiter)
        deadline = time.time() + timeout
        app = QCoreApplication.instance()
        on_gui_thread = app is not None and QThread.currentThread() is app.thread()

        try:
            if send_action is not None:
                send_action()
            while time.time() < deadline:
                if waiter["matched_line"] is not None:
                    return waiter["matched_line"]
                if on_gui_thread:
                    QCoreApplication.processEvents()
                time.sleep(0.01)
            return None
        finally:
            with self._waiters_lock:
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
        from config.boards import get_board_registry
        transport = self.board_context.profile.definition['transport'] if self.board_context else get_board_registry().bootstrap
        self.serial_port.write(f"{command}{transport['command_terminator']}".encode("utf-8"))
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

    def read_testboard_status(self, timeout=2.0):
        from serial_communication.adc_connection_state import build_default_arduino_status
        from serial_communication.testboard_status import apply_testboard_status_line
        status = build_default_arduino_status()
        started = False

        def collect(line):
            nonlocal started
            if "STATUS (PZT/ADS7953)" in line:
                started = True
            if started:
                apply_testboard_status_line(status, line, self.board_context)
            return started and line.startswith("# ---") and "STATUS" not in line

        completed = self.wait_for_line(collect, timeout, consume=True,
                                       send_action=lambda: self.send_command("status"))
        return status if completed else None

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
        if not payload or ":" in payload or "=" in payload:
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
