import csv
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import numpy as np

from file_operations.data_exporter import DataExporterMixin
from file_operations.force_export_alignment import (
    build_export_row_timestamps,
    build_force_export_series,
    get_nearest_force_values,
)


@contextmanager
def workspace_tempdir(prefix: str):
    root = Path(".codex_test_tmp")
    root.mkdir(exist_ok=True)
    path = root / f"{prefix}_{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        import shutil

        shutil.rmtree(path, ignore_errors=True)


class SimpleText:
    def __init__(self, value=""):
        self._value = value

    def text(self):
        return self._value


class SimpleNotes:
    def __init__(self, value=""):
        self._value = value

    def toPlainText(self):
        return self._value


class SimpleCheck:
    def __init__(self, checked=False):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked


class SimpleSpin:
    def __init__(self, value=0):
        self._value = value

    def value(self):
        return self._value


class ForceExportHarness(DataExporterMixin):
    def __init__(self, output_dir: Path):
        self.device_mode = "adc"
        self.current_mcu = "ADC"
        self.dir_input = SimpleText(str(output_dir))
        self.filename_input = SimpleText("capture")
        self.notes_input = SimpleNotes("")
        self.use_range_check = SimpleCheck(False)
        self.min_sweep_spin = SimpleSpin(0)
        self.max_sweep_spin = SimpleSpin(0)
        self.buffer_spin = SimpleSpin(8)
        self.force_data = [
            (0.10, 1.0, 10.0),
            (0.30, 3.0, 30.0),
            (0.50, 5.0, 50.0),
        ]
        self.force_calibration_offset = {"x": 0.0, "z": 0.0}
        self.raw_data = np.array([[11.0], [22.0], [33.0]], dtype=np.float32)
        self.sweep_timestamps = np.array([0.05, 0.28, 0.52], dtype=np.float64)
        self.raw_data_buffer = None
        self.sweep_timestamps_buffer = None
        self.samples_per_sweep = 1
        self.sweep_count = len(self.raw_data)
        self.MAX_SWEEPS_BUFFER = len(self.raw_data)
        self.buffer_lock = None
        self.config = {
            "channels": [0],
            "repeat": 1,
            "ground_pin": None,
            "use_ground": False,
            "reference": "vdd",
            "osr": 1,
            "gain": 1,
        }
        self.timing_state = type(
            "Timing",
            (),
            {
                "capture_start_time": 0.0,
                "capture_end_time": 0.60,
                "arduino_sample_times": [],
                "timing_data": {
                    "per_channel_rate_hz": None,
                    "total_rate_hz": None,
                    "arduino_sample_time_us": None,
                    "arduino_sample_rate_hz": None,
                    "buffer_gap_time_ms": None,
                },
            },
        )()
        self._archive_path = None
        self._block_timing_path = None
        self.log_messages = []

    def is_array_pzt1_mode(self):
        return False

    def get_effective_samples_per_sweep(self):
        return 1

    def log_status(self, message):
        self.log_messages.append(message)

    def _show_save_data_notice(self, label_text: str = "Saving data..."):
        return None

    def _update_save_data_notice(self, label_text: str):
        return None

    def _hide_save_data_notice(self):
        return None


class ForceExportAlignmentTests(unittest.TestCase):
    def test_build_force_export_series_sorts_by_timestamp(self):
        series = build_force_export_series(
            [
                (0.30, 3.0, 30.0),
                (0.10, 1.0, 10.0),
                (0.20, 2.0, 20.0),
            ]
        )

        self.assertIsNotNone(series)
        self.assertEqual(series.timestamps_s.tolist(), [0.1, 0.2, 0.3])
        self.assertEqual(series.x_force.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(series.z_force.tolist(), [10.0, 20.0, 30.0])

    def test_get_nearest_force_values_prefers_earlier_sample_on_tie(self):
        series = build_force_export_series(
            [
                (0.10, 1.0, 10.0),
                (0.30, 3.0, 30.0),
            ]
        )

        self.assertEqual(get_nearest_force_values(series, 0.20), (1.0, 10.0))

    def test_build_export_row_timestamps_uses_linear_fallback_when_needed(self):
        row_timestamps = build_export_row_timestamps(
            selected_timestamps=None,
            saved_total=3,
            capture_duration_s=0.6,
        )

        self.assertIsNotNone(row_timestamps)
        self.assertTrue(np.allclose(row_timestamps, [0.0, 0.3, 0.6]))

    def test_save_data_aligns_force_columns_by_nearest_sweep_timestamp(self):
        with workspace_tempdir("force_export_alignment") as tmpdir:
            harness = ForceExportHarness(tmpdir)

            with patch("file_operations.data_exporter.QMessageBox.information"), patch(
                "file_operations.data_exporter.QMessageBox.warning"
            ), patch("file_operations.data_exporter.QMessageBox.critical"):
                harness.save_data()

            csv_files = sorted(tmpdir.glob("capture_*.csv"))
            self.assertEqual(len(csv_files), 1)

            with csv_files[0].open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))

            self.assertEqual(rows[0], ["CH0", "Force_X", "Force_Z"])
            self.assertEqual(rows[1], ["11.0", "1.0", "10.0"])
            self.assertEqual(rows[2], ["22.0", "3.0", "30.0"])
            self.assertEqual(rows[3], ["33.0", "5.0", "50.0"])


if __name__ == "__main__":
    unittest.main()
