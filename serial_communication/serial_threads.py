"""
Serial Reader Threads
====================
Background threads for reading serial data without blocking the GUI.
"""

import re
import time
import struct
import threading

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from data_processing.acquisition_queue import AcquisitionQueue, AcquisitionOverrun
from serial_communication.isolated_reader import IsolatedRawReader, supports_isolation

from constants.serial import (
    FORCE_READER_IDLE_MS,
    SERIAL_ASCII_LINE_MAX_BYTES,
    SERIAL_PACKET_AVG_SAMPLE_TIME_BYTES,
    SERIAL_PACKET_AVG_SAMPLE_TIME_MAX_US,
    SERIAL_PACKET_AVG_SAMPLE_TIME_MIN_US,
    SERIAL_PACKET_BLOCK_TIMESTAMP_BYTES,
    SERIAL_PACKET_HEADER_BYTES,
    SERIAL_PACKET_SAMPLE_COUNT_MAX,
    SERIAL_PACKET_SPAN_MAX_FACTOR,
    SERIAL_PACKET_SPAN_MIN_FACTOR,
    SERIAL_PACKET_SPAN_TOLERANCE_US,
    SERIAL_READER_DEBUG_LOG_LIMIT,
    SERIAL_READER_IDLE_MS,
    SERIAL_READER_WAIT_TIMEOUT_SEC,
    SERIAL_READER_READ_MAX_BYTES,
    SERIAL_DRIVER_RX_BUFFER_BYTES,
    SERIAL_DRIVER_TX_BUFFER_BYTES,
    SERIAL_REJECTION_CONTEXT_BYTES,
)


FORCE_NUMERIC_TOKEN_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def parse_force_sensor_line(line: str):
    """Parse a force-sensor line into ``(x_force, z_force)`` floats.

    Supported formats:
    - ``x,z``
    - ``timestamp,x,z``
    - labeled/noisy variants that still contain at least two numeric tokens
    """
    stripped = (line or "").strip()
    if not stripped:
        return None

    parts = [part.strip() for part in stripped.split(',') if part.strip()]

    if len(parts) >= 3:
        try:
            return float(parts[1]), float(parts[2])
        except ValueError:
            pass

    if len(parts) >= 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass

    numeric_tokens = FORCE_NUMERIC_TOKEN_RE.findall(stripped)
    if len(numeric_tokens) >= 2:
        try:
            return float(numeric_tokens[-2]), float(numeric_tokens[-1])
        except ValueError:
            return None

    return None


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
        from serial_communication.protocols.registry import FRAME_ADAPTERS
        self.frame_codec = FRAME_ADAPTERS['adc_u16_timed']
        # Persistent buffer that holds partial binary packets between reads
        self.binary_buffer = bytearray()
        self._debug_binary_packets_seen = 0
        self._debug_binary_rejections = 0
        self._accepted_packets_total = 0
        self._rejected_packets_total = 0
        self._rejection_examples = []
        self._last_data_time = time.perf_counter()
        self._last_idle_log_time = 0.0
        self.raw_queue = AcquisitionQueue()
        self._decoder = None
        self.batch_consumer = None
        self.capture_generation = 0
        self._batch_frames = []
        self._batch_sweeps = 0
        self._batch_started = time.perf_counter()
        self._chunk_arrival = self._batch_started
        self._reader_failed = False
        self._read_interval_max_s = 0.0
        self._native_read_interval_max_s = 0.0
        self._decode_age_max_s = 0.0
        self._last_read = None
        self._trailing_capture_bytes = 0
        self._driver_rx_buffer_requested_bytes = None
        self._driver_rx_buffer_request_error = None
        self._isolated_reader = None
        self._isolation_requested = False
        self._isolation_ready = threading.Event()
        self._isolation_error = None

    @property
    def shutdown_wait_ms(self):
        return 5000 if self._isolation_requested else 0

    def _decode_loop(self):
        while self.running or self.raw_queue.snapshot()['items']:
            item = self.raw_queue.get(timeout=0.01)
            try:
                if callable(item):
                    item()
                elif item is not None:
                    data, self._chunk_arrival = item
                    self._decode_age_max_s = max(self._decode_age_max_s, time.perf_counter() - self._chunk_arrival)
                    self.binary_buffer.extend(data)
                    self.process_binary_data(self.binary_buffer)
                if self._batch_frames and time.perf_counter() - self._batch_started >= 0.02:
                    self._flush_batch()
            except Exception as exc:
                self._reader_failed = True
                self.batch_consumer = None
                self._batch_frames = []
                self._batch_sweeps = 0
                self.error_occurred.emit(f"Acquisition pipeline error: decoder: {exc}")

    def _flush_batch(self):
        if not self._batch_frames:
            return
        frames, self._batch_frames = self._batch_frames, []
        self._batch_sweeps = 0
        self._batch_started = time.perf_counter()
        if self.batch_consumer is not None:
            self.batch_consumer(dict(
                generation=self.capture_generation,
                samples=np.concatenate([f[0] for f in frames]),
                avg_us=np.concatenate([f[1] for f in frames]),
                starts=np.concatenate([f[2] for f in frames]),
                ends=np.concatenate([f[3] for f in frames]),
                arrival=frames[0][4], decoded=time.perf_counter()))

    def _decode_timed_sweep_run(self, buffer, offset):
        """Vector-validate consecutive fixed-width frames; retain scalar resync.

        Only the opt-in one-sweep consumer uses this path. Every header, width
        and timing footer is checked with the same limits as the scalar parser.
        Owned field arrays are copied before releasing/resizing the bytearray.
        """
        width = self.expected_samples_per_sweep
        packet_size = 14 + 2 * width
        limit = min(1500, max(1, 262144 // packet_size))
        count = min((len(buffer) - offset) // packet_size, limit - self._batch_sweeps)
        if count <= 0:
            return 0
        dtype = np.dtype([('magic', 'u1', 2), ('count', '<u2'), ('samples', '<u2', width),
                          ('avg', '<u2'), ('start', '<u4'), ('end', '<u4')])
        records = np.frombuffer(buffer, dtype=dtype, count=count, offset=offset)
        average = records['avg'].astype(np.int64)
        span = (records['end'].astype(np.int64) - records['start'].astype(np.int64)) & 0xFFFFFFFF
        expected_span = (width - 1) * average
        valid = ((records['magic'][:, 0] == 0xAA) & (records['magic'][:, 1] == 0x55)
                 & (records['count'] == width) & (average >= SERIAL_PACKET_AVG_SAMPLE_TIME_MIN_US)
                 & (average <= SERIAL_PACKET_AVG_SAMPLE_TIME_MAX_US)
                 & (span >= np.maximum(0, (expected_span * SERIAL_PACKET_SPAN_MIN_FACTOR).astype(np.int64) - SERIAL_PACKET_SPAN_TOLERANCE_US))
                 & (span <= (expected_span * SERIAL_PACKET_SPAN_MAX_FACTOR).astype(np.int64) + SERIAL_PACKET_SPAN_TOLERANCE_US))
        bad = np.flatnonzero(~valid)
        if len(bad):
            count = int(bad[0])
        if count:
            if not self._batch_frames:
                self._batch_started = time.perf_counter()
            self._batch_frames.append((records['samples'][:count].copy(), records['avg'][:count].copy(),
                records['start'][:count].copy(), records['end'][:count].copy(), self._chunk_arrival))
            self._batch_sweeps += count
            self._accepted_packets_total += count
        del records
        if self._batch_sweeps >= limit:
            self._flush_batch()
        return count * packet_size

    def _decoder_control(self, action):
        if not self.running and self._decoder is not None:
            self._decoder.join(5)
            if self._decoder.is_alive():
                raise AcquisitionOverrun('decoder shutdown did not drain')
        if self._decoder is None or not self._decoder.is_alive():
            action()
            return
        done = threading.Event()
        def apply():
            try:
                action()
            finally:
                done.set()
        self.raw_queue.put(apply)
        if not done.wait(5):
            raise AcquisitionOverrun("decoder did not drain within five seconds")

    def configure_batch_consumer(self, consumer, generation):
        def apply():
            self._flush_batch()
            self.batch_consumer = consumer
            self.capture_generation = generation
        self._decoder_control(apply)
        if consumer is not None and supports_isolation(self.serial_port):
            # The read thread switches owners at a read boundary. Wait for the
            # child to be ready before the GUI can issue run*: startup must not
            # consume the device's small streaming headroom.
            self._isolation_requested = True
            if self.isRunning():
                if not self._isolation_ready.wait(5):
                    raise AcquisitionOverrun('isolated raw reader was not ready before capture')
                if self._isolation_error is not None:
                    raise AcquisitionOverrun(f'isolated raw reader startup: {self._isolation_error}')

    def pipeline_status(self):
        raw = self.raw_queue.snapshot()
        width = self.expected_samples_per_sweep
        raw['estimated_sweeps'] = raw['bytes'] // (14 + 2 * width) if width else None
        return dict(raw=raw, read_interval_max_s=self._read_interval_max_s,
                    native_read_interval_max_s=self._native_read_interval_max_s,
                    decode_age_max_s=self._decode_age_max_s,
                    accepted_frames=self._accepted_packets_total, parser_rejections=self._rejected_packets_total,
                    rejection_examples=[dict(item) for item in self._rejection_examples],
                    driver_rx_buffer_requested_bytes=self._driver_rx_buffer_requested_bytes,
                    driver_rx_buffer_request_error=self._driver_rx_buffer_request_error,
                    transport=self._isolated_reader.snapshot() if self._isolated_reader is not None else dict(kind='thread'),
                    trailing_capture_bytes=self._trailing_capture_bytes)

    def _record_rejection(self, reason, *, raw_buffer=None, raw_offset=0, **details):
        self._rejected_packets_total += 1
        if self.is_capturing and len(self._rejection_examples) < SERIAL_READER_DEBUG_LOG_LIMIT:
            if raw_buffer is not None:
                start = max(0, raw_offset - 16)
                details['raw_context_hex'] = bytes(raw_buffer[start:start + SERIAL_REJECTION_CONTEXT_BYTES]).hex()
                details['candidate_offset_in_context'] = raw_offset - start
            self._rejection_examples.append(dict(reason=reason, **details))

    def run(self):
        """Continuously read from serial port and emit signals."""
        port = self.serial_port
        original_timeout = getattr(port, 'timeout', 0)
        timeout_changed = False
        self._decoder = threading.Thread(target=self._decode_loop, name='ADCDecoder', daemon=True)
        self._decoder.start()
        try:
            # pySerial requests only 4 KiB by default on Windows (~2 ms of
            # this stream). Request bounded burst headroom for brief host work.
            # SetupComm is advisory: the driver may ignore the requested size.
            set_buffer_size = getattr(port, 'set_buffer_size', None)
            if callable(set_buffer_size):
                try:
                    set_buffer_size(rx_size=SERIAL_DRIVER_RX_BUFFER_BYTES, tx_size=SERIAL_DRIVER_TX_BUFFER_BYTES)
                    self._driver_rx_buffer_requested_bytes = SERIAL_DRIVER_RX_BUFFER_BYTES
                except Exception as exc:
                    self._driver_rx_buffer_request_error = str(exc)
                    self.error_occurred.emit(f'Serial buffer warning: {exc}')
            # A bounded one-byte read wakes on actual USB arrival, rather than
            # polling an empty port on a timer. Keep stop/disconnect responsive.
            if port and hasattr(port, 'timeout') and (original_timeout is None or original_timeout > SERIAL_READER_WAIT_TIMEOUT_SEC):
                port.timeout = SERIAL_READER_WAIT_TIMEOUT_SEC
                timeout_changed = True
            self._read_loop()
        except Exception as exc:
            self.error_occurred.emit(f'Serial read error: {exc}')
        finally:
            self.running = False
            if self._isolated_reader is not None:
                self._isolated_reader.stop()
            self._isolation_ready.set()
            self._decoder.join()
            try:
                self._flush_batch()
            except Exception as exc:
                self.error_occurred.emit(f"Acquisition pipeline error: {exc}")
            if timeout_changed and port.is_open:
                try:
                    port.timeout = original_timeout
                except Exception:
                    pass  # Device removal may invalidate the port during stop.

    def _read_loop(self):
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self._isolation_requested and self._isolated_reader is None:
                        try:
                            self._isolated_reader = IsolatedRawReader(self.serial_port)
                        except Exception as exc:
                            self._isolation_error = exc
                            raise
                        finally:
                            self._isolation_ready.set()
                    # read_chunk is also used by the isolated replay fixture;
                    # production writes keep using the original COM object.
                    source = self._isolated_reader or self.serial_port
                    read_chunk = getattr(source, 'read_chunk', None)
                    if callable(read_chunk):
                        chunk = read_chunk(SERIAL_READER_WAIT_TIMEOUT_SEC)
                        data, arrival = chunk if chunk is not None else (b'', None)
                        can_wait = True
                    else:
                        bytes_waiting = self.serial_port.in_waiting
                        timeout = getattr(self.serial_port, 'timeout', 0)
                        can_wait = timeout is not None and 0 < timeout <= SERIAL_READER_WAIT_TIMEOUT_SEC
                        data = self.serial_port.read(min(bytes_waiting or 1, SERIAL_READER_READ_MAX_BYTES)) if bytes_waiting > 0 or can_wait else b''
                        arrival = time.perf_counter()
                    if data:
                        self._last_data_time = arrival
                        if self.is_capturing and self._last_read is not None:
                            self._read_interval_max_s = max(self._read_interval_max_s, self._last_data_time - self._last_read)
                            self._native_read_interval_max_s = max(self._native_read_interval_max_s,
                                getattr(source, 'last_native_read_interval_max_s', self._last_data_time - self._last_read))
                        self._last_read = self._last_data_time
                        self.raw_queue.put((data, self._last_data_time), size=len(data), arrival=self._last_data_time)
                        # Data was available, keep draining aggressively without artificial delay.
                        continue

                    self._maybe_emit_capture_idle_debug()
                else:
                    break

                # Nonblocking ports/test sources need a fallback wait. Real
                # blocking ports already waited above and must rearm promptly.
                if not can_wait:
                    time.sleep(SERIAL_READER_IDLE_MS / 1000.0)

            except Exception as e:
                prefix = "Acquisition pipeline error:" if isinstance(e, AcquisitionOverrun) else "Serial read error:"
                self.error_occurred.emit(f"{prefix} raw reader: {e}" if isinstance(e, AcquisitionOverrun) else f"{prefix} {e}")
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
                if self.is_capturing and self.batch_consumer is not None and self.expected_samples_per_sweep:
                    consumed = self._decode_timed_sweep_run(buffer, buf_start)
                    if consumed:
                        buf_start += consumed
                        continue
                if buf_len - buf_start < SERIAL_PACKET_HEADER_BYTES:
                    break  # Need more data for header

                sample_count = buffer[buf_start + 2] | (buffer[buf_start + 3] << 8)
                expected = self.expected_samples_per_sweep

                if sample_count <= 0:
                    buf_start += 1
                    continue

                if sample_count > SERIAL_PACKET_SAMPLE_COUNT_MAX:
                    self._record_rejection('sample_count_max', raw_buffer=buffer, raw_offset=buf_start, sample_count=sample_count)
                    if self.is_capturing and self._debug_binary_rejections < SERIAL_READER_DEBUG_LOG_LIMIT:
                        self._debug_binary_rejections += 1
                        self.error_occurred.emit(
                            f"Binary packet rejected: sample_count={sample_count} exceeds max={SERIAL_PACKET_SAMPLE_COUNT_MAX}"
                        )
                    buf_start += 1
                    continue

                if expected and sample_count % expected != 0:
                    # False header match or desynced stream.
                    self._record_rejection('sample_count_width', raw_buffer=buffer, raw_offset=buf_start, sample_count=sample_count, expected_width=expected)
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
                    samples = self.frame_codec.decode(memoryview(buffer)[payload_start:payload_end]).copy()

                    # avg_sample_time_us: uint16 LE, 2 bytes after payload
                    avg_time_offset = payload_end
                    avg_sample_time_us, block_start_us, block_end_us = struct.unpack_from('<HII', buffer, avg_time_offset)

                    # struct returns scalar values without retaining a view on
                    # the bytearray, which is trimmed after this decode pass.

                    if not self._is_packet_timing_sane(
                        sample_count=sample_count,
                        avg_sample_time_us=avg_sample_time_us,
                        block_start_us=block_start_us,
                        block_end_us=block_end_us,
                    ):
                        self._record_rejection('timing', raw_buffer=buffer, raw_offset=buf_start, sample_count=sample_count, avg_dt_us=avg_sample_time_us,
                                               block_start_us=block_start_us, block_end_us=block_end_us)
                        if self._debug_binary_rejections < SERIAL_READER_DEBUG_LOG_LIMIT:
                            self._debug_binary_rejections += 1
                            self.error_occurred.emit(
                                "Binary packet rejected: timing sanity check failed "
                                f"(sample_count={sample_count}, avg_dt_us={avg_sample_time_us}, "
                                f"start={block_start_us}, end={block_end_us})"
                            )
                        buf_start += 1
                        continue

                    self._accepted_packets_total += 1
                    if self.batch_consumer is None:
                        if not self._reader_failed:
                            self.binary_sweep_received.emit(samples, avg_sample_time_us, block_start_us, block_end_us)
                    else:
                        if sample_count != expected:
                            raise ValueError('Batched timed frame must contain exactly one configured sweep')
                        if not self._batch_frames:
                            self._batch_started = time.perf_counter()
                        self._batch_frames.append((samples.reshape(1, -1), np.asarray([avg_sample_time_us], dtype=np.uint16),
                            np.asarray([block_start_us], dtype=np.uint32), np.asarray([block_end_us], dtype=np.uint32), self._chunk_arrival))
                        self._batch_sweeps += 1
                        if self._batch_sweeps >= min(1500, max(1, 262144 // packet_size)):
                            self._flush_batch()

                buf_start += packet_size
                continue

            # ----------------------------------------------------------------
            # ASCII message (lines starting with '#')
            # ----------------------------------------------------------------
            if b0 == ord('#'):
                try:
                    newline_idx = buffer.index(ord('\n'), buf_start)
                except ValueError:
                    # Terminator has not arrived yet. Wait for the rest of the line
                    # instead of consuming the '#', which would destroy a line split
                    # across two reads. Resync only once the unterminated tail grows
                    # past any plausible line length.
                    if buf_len - buf_start < SERIAL_ASCII_LINE_MAX_BYTES:
                        break
                    buf_start += 1
                    continue

                try:
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
        self._decoder_control(lambda: self._set_capturing(capturing, expected_samples_per_sweep))

    def _set_capturing(self, capturing, expected_samples_per_sweep=None):
        """Set whether we're currently capturing data."""
        if not capturing:
            self._flush_batch()
        self.is_capturing = capturing
        self.expected_samples_per_sweep = expected_samples_per_sweep if capturing else None
        if capturing:
            self._debug_binary_packets_seen = 0
            self._debug_binary_rejections = 0
            self._accepted_packets_total = 0
            self._rejected_packets_total = 0
            self._rejection_examples = []
            self._last_data_time = time.perf_counter()
            self._last_idle_log_time = 0.0
            self._reader_failed = False
            self._read_interval_max_s = self._decode_age_max_s = 0.0
            self._native_read_interval_max_s = 0.0
            self._last_read = None
            self._trailing_capture_bytes = 0
        if not capturing:
            # Drop any partial/queued binary data between captures so timestamps restart clean
            self._trailing_capture_bytes = len(self.binary_buffer)
            self.binary_buffer.clear()

    def _maybe_emit_capture_idle_debug(self) -> None:
        if not self.is_capturing:
            return
        now = time.perf_counter()
        idle_for_sec = now - self._last_data_time
        if idle_for_sec < 0.25:
            return
        if (now - self._last_idle_log_time) < 1.0:
            return
        self._last_idle_log_time = now

        expected = self.expected_samples_per_sweep
        self.error_occurred.emit(
            "Serial reader idle during capture: "
            f"idle_ms={idle_for_sec * 1000.0:.1f}, expected_samples_per_sweep={expected}, "
            f"accepted_packets={self._accepted_packets_total}, rejected_packets={self._rejected_packets_total}, "
            f"buffer_len={len(self.binary_buffer)}"
        )

    def _is_packet_timing_sane(
        self,
        *,
        sample_count: int,
        avg_sample_time_us: int,
        block_start_us: int,
        block_end_us: int,
    ) -> bool:
        if avg_sample_time_us < SERIAL_PACKET_AVG_SAMPLE_TIME_MIN_US:
            return False
        if avg_sample_time_us > SERIAL_PACKET_AVG_SAMPLE_TIME_MAX_US:
            return False

        expected_span_us = max(0, int(sample_count - 1) * int(avg_sample_time_us))
        actual_span_us = int((int(block_end_us) - int(block_start_us)) & 0xFFFFFFFF)

        min_span_us = int(expected_span_us * SERIAL_PACKET_SPAN_MIN_FACTOR) - SERIAL_PACKET_SPAN_TOLERANCE_US
        max_span_us = int(expected_span_us * SERIAL_PACKET_SPAN_MAX_FACTOR) + SERIAL_PACKET_SPAN_TOLERANCE_US
        if min_span_us < 0:
            min_span_us = 0
        return min_span_us <= actual_span_us <= max_span_us

    def clear_buffer(self):
        """Explicitly clear the internal binary buffer."""
        self._decoder_control(self.binary_buffer.clear)

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
        self._debug_parse_failures = 0
        self._debug_parsed_samples = 0

    def run(self):
        """Continuously read CSV data from force sensor serial port."""
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self.serial_port.in_waiting > 0:
                        line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                        
                        if line:
                            parsed = parse_force_sensor_line(line)
                            if parsed is not None:
                                x_force, z_force = parsed
                                if self._debug_parsed_samples < 3:
                                    self._debug_parsed_samples += 1
                                    self.error_occurred.emit(
                                        f"Force reader parsed sample {self._debug_parsed_samples}: "
                                        f"x={x_force:.3f}, z={z_force:.3f}"
                                    )
                                self.force_data_received.emit(x_force, z_force)
                            elif self._debug_parse_failures < SERIAL_READER_DEBUG_LOG_LIMIT:
                                self._debug_parse_failures += 1
                                self.error_occurred.emit(
                                    f"Force reader skipped unparsed line {self._debug_parse_failures}: {line[:120]}"
                                )
                else:
                    break

                self.msleep(FORCE_READER_IDLE_MS)  # Small delay to prevent CPU spinning

            except Exception as e:
                self.error_occurred.emit(f"Force sensor read error: {e}")
                break

    def stop(self):
        """Stop the thread."""
        self.running = False
