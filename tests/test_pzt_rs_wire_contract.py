"""
PZT_RS Wire-Format Contract
===========================
The host mirrors the per-sensor payload layout defined by the Teensy firmware.
These values are duplicated by necessity (Python cannot include the C++ header),
so assert directly against the firmware source to catch drift.
"""

import re
import unittest
from pathlib import Path

from constants.pzt_rs import (
    PZT_RS_CHANNELS_PER_SENSOR,
    PZT_RS_OUTPUTS_PER_SENSOR,
    PZT_RS_RS_VALUES_PER_SENSOR,
    PZT_RS_RS_WIRE_UNITS_PER_OHM,
)


FIRMWARE_HEADER = (
    Path(__file__).resolve().parents[1]
    / "Arduino_Sketches"
    / "PCB1.7_with_libraries"
    / "Teensy"
    / "libraries"
    / "PztRsController.h"
)


def _read_firmware_constant(name: str) -> int:
    source = FIRMWARE_HEADER.read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"\b{name}\s*=\s*(\d+)\s*;", source)
    if match is None:
        raise AssertionError(f"{name} not found in {FIRMWARE_HEADER.name}")
    return int(match.group(1))


class PztRsWireContractTests(unittest.TestCase):
    def test_firmware_header_is_present(self):
        self.assertTrue(FIRMWARE_HEADER.is_file(), f"missing {FIRMWARE_HEADER}")

    def test_channels_per_sensor_matches_firmware(self):
        self.assertEqual(PZT_RS_CHANNELS_PER_SENSOR, _read_firmware_constant("kChannelsPerSensor"))

    def test_rs_values_per_sensor_matches_firmware(self):
        self.assertEqual(PZT_RS_RS_VALUES_PER_SENSOR, _read_firmware_constant("kRsValuesPerSensor"))

    def test_wire_units_per_ohm_matches_firmware(self):
        self.assertEqual(PZT_RS_RS_WIRE_UNITS_PER_OHM, float(_read_firmware_constant("kWireUnitsPerOhm")))

    def test_outputs_per_sensor_is_channels_plus_rs_values(self):
        # Mirrors kOutputsPerSensor = kChannelsPerSensor + kRsValuesPerSensor.
        self.assertEqual(
            PZT_RS_OUTPUTS_PER_SENSOR,
            PZT_RS_CHANNELS_PER_SENSOR + PZT_RS_RS_VALUES_PER_SENSOR,
        )
        self.assertEqual(PZT_RS_OUTPUTS_PER_SENSOR, 7)


if __name__ == "__main__":
    unittest.main()
