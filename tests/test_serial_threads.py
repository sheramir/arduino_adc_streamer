import struct
import threading
import time
import unittest

import numpy as np
import pytest

from constants.serial import SERIAL_ASCII_LINE_MAX_BYTES
from serial_communication.serial_threads import SerialReaderThread


@pytest.mark.parametrize('initial_timeout', [None, 1.0, .005])
@pytest.mark.parametrize('buffer_request_fails', [False, True])
def test_reader_waits_for_first_byte_then_drains_burst_and_restores_timeout(initial_timeout, buffer_request_fails):
    class Port:
        is_open = True
        timeout = 1.0
        def __init__(self):
            self.buffer = bytearray()
            self.condition = threading.Condition()
            self.waiting = threading.Event()
            self.reads = []
            self.buffer_request = None
        def set_buffer_size(self, rx_size, tx_size):
            self.buffer_request = (rx_size, tx_size)
            if buffer_request_fails:
                raise OSError('driver buffer request unsupported')
        @property
        def in_waiting(self):
            with self.condition:
                return len(self.buffer)
        def read(self, count):
            with self.condition:
                self.reads.append((count, self.timeout))
                if not self.buffer:
                    self.waiting.set()
                    self.condition.wait_for(lambda: bool(self.buffer), timeout=self.timeout)
                data = bytes(self.buffer[:count])
                del self.buffer[:count]
                return data
        def feed(self, data):
            with self.condition:
                self.buffer.extend(data)
                self.condition.notify_all()
    port = Port()
    port.timeout = initial_timeout
    reader = SerialReaderThread(port)
    batches = []
    reader.configure_batch_consumer(batches.append, 1)
    reader.set_capturing(True, 20)
    reader.start()
    try:
        assert port.waiting.wait(.5), 'reader must wait for arrivals instead of polling an empty port'
        packets = [SerialReaderThreadTests()._build_packet(list(range(20)), 1, 1000+i*100, 1019+i*100)
                   for i in range(1000)]
        port.feed(b''.join(packets))
        deadline = time.perf_counter() + 2
        while reader.pipeline_status()['accepted_frames'] < 1000 and time.perf_counter() < deadline:
            time.sleep(.001)
        reader.set_capturing(False)
        assert sum(len(b['starts']) for b in batches) == 1000
        np.testing.assert_array_equal(np.concatenate([b['starts'] for b in batches]), 1000+np.arange(1000)*100)
        assert reader.pipeline_status()['parser_rejections'] == 0
        assert port.buffer_request == (65536, 4096)
        status = reader.pipeline_status()
        if buffer_request_fails:
            assert status['driver_rx_buffer_requested_bytes'] is None
            assert 'unsupported' in status['driver_rx_buffer_request_error']
        else:
            assert status['driver_rx_buffer_requested_bytes'] == 65536
            assert status['driver_rx_buffer_request_error'] is None
        assert all(timeout <= .02 and count <= 65536 for count, timeout in port.reads)
    finally:
        reader.stop()
        assert reader.wait(2000)
    assert port.timeout == initial_timeout


def test_rejection_diagnostics_are_bounded_and_reset_per_capture():
    reader = SerialReaderThread(None)
    reader.set_capturing(True, 20)
    bad = SerialReaderThreadTests()._build_packet(list(range(20)), 1, 1000, 1000000)
    good = SerialReaderThreadTests()._build_packet(list(range(20)), 1, 1000100, 1000119)
    reader.process_binary_data(bytearray(bad * 18 + good))
    status = reader.pipeline_status()
    assert status['parser_rejections'] == 18 and status['accepted_frames'] == 1
    assert len(status['rejection_examples']) == 10
    assert status['rejection_examples'][0]['reason'] == 'timing'
    assert status['rejection_examples'][0]['block_end_us'] == 1000000
    assert all(len(bytes.fromhex(item['raw_context_hex'])) <= 256 for item in status['rejection_examples'])
    reader.set_capturing(False)
    reader.set_capturing(True, 20)
    assert reader.pipeline_status()['rejection_examples'] == []


class SerialReaderThreadTests(unittest.TestCase):
    def _build_packet(self, samples, avg_sample_time_us=61, block_start_us=1000, block_end_us=2000):
        sample_count = len(samples)
        header = bytes([0xAA, 0x55, sample_count & 0xFF, (sample_count >> 8) & 0xFF])
        payload = struct.pack("<" + ("H" * sample_count), *samples)
        footer = struct.pack("<HII", int(avg_sample_time_us), int(block_start_us), int(block_end_us))
        return header + payload + footer

    def test_false_large_header_does_not_block_following_valid_packet(self):
        reader = SerialReaderThread(serial_port=None)
        reader.set_capturing(True, expected_samples_per_sweep=20)

        accepted_packets = []
        rejection_messages = []
        reader.binary_sweep_received.connect(
            lambda samples, avg_us, start_us, end_us: accepted_packets.append((samples, avg_us, start_us, end_us))
        )
        reader.error_occurred.connect(lambda message: rejection_messages.append(str(message)))

        # False header with huge sample_count that should now be rejected quickly.
        # 0x9C40 == 40000, divisible by expected 20 but unrealistic for one packet.
        false_header = bytes([0xAA, 0x55, 0x40, 0x9C])
        valid_samples = list(range(20))
        valid_packet = self._build_packet(valid_samples, avg_sample_time_us=64, block_start_us=1234, block_end_us=2345)

        buffer = bytearray(false_header + valid_packet)
        remaining = reader.process_binary_data(buffer)

        self.assertEqual(len(accepted_packets), 1)
        parsed_samples, avg_us, start_us, end_us = accepted_packets[0]
        np.testing.assert_array_equal(parsed_samples, np.asarray(valid_samples, dtype=np.uint16))
        self.assertEqual(avg_us, 64)
        self.assertEqual(start_us, 1234)
        self.assertEqual(end_us, 2345)
        self.assertEqual(len(remaining), 0)
        self.assertTrue(any("exceeds max" in message for message in rejection_messages))

    def test_timing_sanity_rejection_recovers_to_following_valid_packet(self):
        reader = SerialReaderThread(serial_port=None)
        reader.set_capturing(True, expected_samples_per_sweep=20)

        accepted_packets = []
        rejection_messages = []
        reader.binary_sweep_received.connect(
            lambda samples, avg_us, start_us, end_us: accepted_packets.append((samples, avg_us, start_us, end_us))
        )
        reader.error_occurred.connect(lambda message: rejection_messages.append(str(message)))

        valid_samples = list(range(20))
        # Build a packet with impossible timing span: end-start much larger than sample_count*avg_dt.
        bad_timing_packet = self._build_packet(valid_samples, avg_sample_time_us=61, block_start_us=1000, block_end_us=1_000_000)
        good_packet = self._build_packet(valid_samples, avg_sample_time_us=62, block_start_us=2000, block_end_us=3178)

        remaining = reader.process_binary_data(bytearray(bad_timing_packet + good_packet))

        self.assertEqual(len(accepted_packets), 1)
        parsed_samples, avg_us, start_us, end_us = accepted_packets[0]
        np.testing.assert_array_equal(parsed_samples, np.asarray(valid_samples, dtype=np.uint16))
        self.assertEqual(avg_us, 62)
        self.assertEqual(start_us, 2000)
        self.assertEqual(end_us, 3178)
        self.assertEqual(len(remaining), 0)
        self.assertTrue(any("timing sanity check failed" in message for message in rejection_messages))


class SerialReaderAsciiLineTests(unittest.TestCase):
    def _make_reader(self):
        reader = SerialReaderThread(serial_port=None)
        lines = []
        reader.data_received.connect(lambda line: lines.append(str(line)))
        return reader, lines

    def test_complete_ascii_line_is_emitted(self):
        reader, lines = self._make_reader()

        remaining = reader.process_binary_data(bytearray(b"#OK\n"))

        self.assertEqual(lines, ["#OK"])
        self.assertEqual(len(remaining), 0)

    def test_ascii_line_split_across_reads_is_emitted_once_complete(self):
        reader, lines = self._make_reader()

        buffer = reader.process_binary_data(bytearray(b"#O"))
        self.assertEqual(lines, [])

        buffer.extend(b"K\n")
        remaining = reader.process_binary_data(buffer)

        self.assertEqual(lines, ["#OK"])
        self.assertEqual(len(remaining), 0)

    def test_unterminated_ascii_tail_resyncs_past_max_line_length(self):
        reader, lines = self._make_reader()

        oversized = bytearray(b"#" + b"A" * (SERIAL_ASCII_LINE_MAX_BYTES + 8))
        original_len = len(oversized)
        remaining = reader.process_binary_data(oversized)

        # No terminator ever arrives, so the reader must not stall on it forever.
        self.assertEqual(lines, [])
        self.assertLess(len(remaining), original_len)

    def test_binary_packet_after_split_ascii_line_is_still_parsed(self):
        reader, lines = self._make_reader()
        reader.set_capturing(True, expected_samples_per_sweep=20)

        accepted = []
        reader.binary_sweep_received.connect(
            lambda samples, avg_us, start_us, end_us: accepted.append(samples)
        )

        samples = list(range(20))
        packet = SerialReaderThreadTests()._build_packet(samples)

        buffer = reader.process_binary_data(bytearray(b"#ST"))
        buffer.extend(b"ATUS\n")
        buffer.extend(packet)
        remaining = reader.process_binary_data(buffer)

        self.assertEqual(lines, ["#STATUS"])
        self.assertEqual(len(accepted), 1)
        np.testing.assert_array_equal(accepted[0], np.asarray(samples, dtype=np.uint16))
        self.assertEqual(len(remaining), 0)


if __name__ == "__main__":
    unittest.main()
