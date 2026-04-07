"""
Serial Reader Threads
====================
Background threads for reading serial data without blocking the GUI.
"""

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from config_constants import (
    FORCE_READER_IDLE_MS,
    SERIAL_PACKET_AVG_SAMPLE_TIME_BYTES,
    SERIAL_PACKET_BLOCK_TIMESTAMP_BYTES,
    SERIAL_PACKET_HEADER_BYTES,
    SERIAL_READER_DEBUG_LOG_LIMIT,
    SERIAL_READER_IDLE_MS,
)


class SerialReaderThread(QThread):
    """Background thread for reading serial data without blocking the GUI."""
    data_received = pyqtSignal(str)
    binary_sweep_received = pyqtSignal(object, object, object, object)  # samples (np.ndarray uint16), avg_sample_time_us, block_start_us, block_end_us
    error_occurred = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True
        self.is_capturing = False
        self.expected_samples_per_sweep = None
        # Persistent buffer that holds partial binary packets between reads
        self.binary_buffer = bytearray()
        self._debug_binary_packets_seen = 0
        self._debug_binary_rejections = 0

    def run(self):
        """Continuously read from serial port and emit signals."""
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self.serial_port.in_waiting > 0:
                        data = self.serial_port.read(self.serial_port.in_waiting)
                        
                        # Always process as binary buffer to handle mixed binary/ASCII data
                        # This prevents "Unexpected ASCII" errors when MCU sends binary packets
                        self.binary_buffer.extend(data)
                        self.binary_buffer = self.process_binary_data(self.binary_buffer)
                else:
                    break

                self.msleep(SERIAL_READER_IDLE_MS)  # Keep reads responsive at higher channel counts

            except Exception as e:
                self.error_occurred.emit(f"Serial read error: {e}")
                break

    def process_binary_data(self, buffer):
        """Process buffer for binary block packets and ASCII messages.

        Binary blocks contain multiple sweeps:
        - Header: [0xAA][0x55][countL][countH] (4 bytes)
        - Payload: count samples as uint16_t little-endian
        - Footer: avg_sample_time_us (uint16 LE) + block_start_us (uint32 LE) + block_end_us (uint32 LE)

        Uses an integer offset to avoid creating new bytearray slices on every
        packet — all consumed bytes are removed in a single ``del buffer[:n]``
        at the end of the loop.

        Samples are parsed with ``numpy.frombuffer`` (zero-copy, no Python loop)
        and emitted as a ``numpy.ndarray`` of dtype ``uint16``.

        If not capturing, binary packets are discarded (but not logged as errors).
        """
        buf_start = 0
        buf_len = len(buffer)

        while buf_start <= buf_len - 2:
            b0 = buffer[buf_start]
            b1 = buffer[buf_start + 1]

            # ----------------------------------------------------------------
            # Binary block packet (0xAA 0x55 header)
            # ----------------------------------------------------------------
            if b0 == 0xAA and b1 == 0x55:
                if buf_len - buf_start < SERIAL_PACKET_HEADER_BYTES:
                    break  # Need more data for header

                sample_count = buffer[buf_start + 2] | (buffer[buf_start + 3] << 8)
                expected = self.expected_samples_per_sweep

                if sample_count <= 0:
                    buf_start += 1
                    continue

                if expected and sample_count % expected != 0:
                    # False header match or desynced stream.
                    if self.is_capturing and self._debug_binary_rejections < SERIAL_READER_DEBUG_LOG_LIMIT:
                        self._debug_binary_rejections += 1
                        self.error_occurred.emit(
                            f"Binary packet rejected: sample_count={sample_count}, expected_multiple={expected}"
                        )
                    buf_start += 1
                    continue

                # header(4) + samples(count*2) + avg_time(2) + block_start_us(4) + block_end_us(4)
                packet_size = (
                    SERIAL_PACKET_HEADER_BYTES
                    + (sample_count * 2)
                    + SERIAL_PACKET_AVG_SAMPLE_TIME_BYTES
                    + SERIAL_PACKET_BLOCK_TIMESTAMP_BYTES
                )

                if buf_len - buf_start < packet_size:
                    break  # Need more data for complete packet

                if self.is_capturing:
                    if self._debug_binary_packets_seen < SERIAL_READER_DEBUG_LOG_LIMIT:
                        self._debug_binary_packets_seen += 1
                        self.error_occurred.emit(
                            f"Binary packet accepted: sample_count={sample_count}, expected_multiple={expected}, packet_size={packet_size}"
                        )

                    # --- Parse samples with frombuffer (no Python loop) ---
                    payload_start = buf_start + SERIAL_PACKET_HEADER_BYTES
                    payload_end = payload_start + sample_count * 2
                    # .copy() so the array owns its data before buffer is trimmed below
                    samples = np.frombuffer(
                        memoryview(buffer)[payload_start:payload_end], dtype='<u2'
                    ).copy()

                    # avg_sample_time_us: uint16 LE, 2 bytes after payload
                    avg_time_offset = payload_end
                    avg_sample_time_us = int.from_bytes(
                        buffer[avg_time_offset:avg_time_offset + SERIAL_PACKET_AVG_SAMPLE_TIME_BYTES], 'little'
                    )

                    # block_start_us / block_end_us: uint32 LE, 4 bytes each
                    # Use int.from_bytes (copies bytes immediately) instead of
                    # np.frombuffer so no memoryview holds a live export on the
                    # bytearray at the point of the del buffer[:n] trim below.
                    ts_offset = avg_time_offset + SERIAL_PACKET_AVG_SAMPLE_TIME_BYTES
                    block_start_us = int.from_bytes(
                        buffer[ts_offset:ts_offset + 4], 'little'
                    )
                    block_end_us = int.from_bytes(
                        buffer[ts_offset + 4:ts_offset + 8], 'little'
                    )

                    self.binary_sweep_received.emit(
                        samples, avg_sample_time_us, block_start_us, block_end_us
                    )

                buf_start += packet_size
                continue

            # ----------------------------------------------------------------
            # ASCII message (lines starting with '#')
            # ----------------------------------------------------------------
            if b0 == ord('#'):
                try:
                    newline_idx = buffer.index(ord('\n'), buf_start)
                    line = bytes(buffer[buf_start:newline_idx]).decode('utf-8', errors='strict').strip()
                    if line and line.isprintable():
                        self.data_received.emit(line)
                    buf_start = newline_idx + 1
                    continue
                except (ValueError, UnicodeDecodeError):
                    buf_start += 1
                    continue
                except Exception:
                    buf_start += 1
                    continue

            # Unknown byte — skip to resync
            buf_start += 1

        # Trim all consumed bytes from the buffer in a single operation.
        if buf_start > 0:
            del buffer[:buf_start]

        return buffer

    def set_capturing(self, capturing, expected_samples_per_sweep=None):
        """Set whether we're currently capturing data."""
        self.is_capturing = capturing
        self.expected_samples_per_sweep = expected_samples_per_sweep if capturing else None
        if capturing:
            self._debug_binary_packets_seen = 0
            self._debug_binary_rejections = 0
        if not capturing:
            # Drop any partial/queued binary data between captures so timestamps restart clean
            self.binary_buffer.clear()

    def clear_buffer(self):
        """Explicitly clear the internal binary buffer."""
        self.binary_buffer.clear()

    def stop(self):
        """Stop the thread."""
        self.running = False


class ForceReaderThread(QThread):
    """Background thread for reading force sensor CSV data."""
    force_data_received = pyqtSignal(float, float)  # x_force, z_force
    error_occurred = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True

    def run(self):
        """Continuously read CSV data from force sensor serial port."""
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self.serial_port.in_waiting > 0:
                        line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                        
                        if line:
                            # Parse CSV format: x,z
                            try:
                                parts = line.split(',')
                                if len(parts) >= 2:
                                    x_force = float(parts[0].strip())
                                    z_force = float(parts[1].strip())
                                    self.force_data_received.emit(x_force, z_force)
                            except ValueError:
                                pass  # Skip invalid lines
                else:
                    break

                self.msleep(FORCE_READER_IDLE_MS)  # Small delay to prevent CPU spinning

            except Exception as e:
                self.error_occurred.emit(f"Force sensor read error: {e}")
                break

    def stop(self):
        """Stop the thread."""
        self.running = False
