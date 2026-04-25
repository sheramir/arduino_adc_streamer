import struct
import unittest

import numpy as np

from serial_communication.serial_threads import SerialReaderThread


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


if __name__ == "__main__":
    unittest.main()
