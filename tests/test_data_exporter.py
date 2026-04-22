import csv
import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import numpy as np

from data_processing.adc_filter_engine import ADCFilterEngine, SCIPY_FILTERS_AVAILABLE
from data_processing.filter_processor import FilterProcessorMixin
from file_operations.data_exporter import DataExporterMixin


@contextmanager
def workspace_tempdir(prefix: str):
    root = Path(".codex_test_tmp")
    root.mkdir(exist_ok=True)
    path = root / f"{prefix}_{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
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


class ExportHarness(DataExporterMixin, FilterProcessorMixin):
    def __init__(self, output_dir: Path):
        self.device_mode = "adc"
        self.current_mcu = "ADC"
        self.dir_input = SimpleText(str(output_dir))
        self.filename_input = SimpleText("capture")
        self.notes_input = SimpleNotes("filtered export test")
        self.use_range_check = SimpleCheck(False)
        self.min_sweep_spin = SimpleSpin(0)
        self.max_sweep_spin = SimpleSpin(0)
        self.buffer_spin = SimpleSpin(8)
        self.force_data = []
        self.force_calibration_offset = {"x": 0.0, "z": 0.0}
        self.raw_data = np.array(
            [[0.0], [100.0], [0.0], [100.0], [0.0], [100.0], [0.0], [100.0]],
            dtype=np.float32,
        )
        self.sweep_timestamps = np.arange(len(self.raw_data), dtype=np.float64) / 100.0
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
            "sample_rate": 100.0,
        }
        self.timing_state = type(
            "Timing",
            (),
            {
                "capture_start_time": None,
                "capture_end_time": None,
                "arduino_sample_times": [],
                "timing_data": {"arduino_sample_rate_hz": 100.0},
            },
        )()
        self._archive_path = None
        self._block_timing_path = None
        self.filtering_enabled = True
        self.filter_settings = self.get_default_filter_settings()
        self.filter_settings["main_type"] = "lowpass"
        self.filter_settings["low_cutoff_hz"] = 5.0
        self.filter_settings["notches"] = []
        self.adc_filter_engine = ADCFilterEngine()
        self._filter_channel_runtime = {}
        self._filter_total_fs_hz = 0.0
        self._filter_channels_signature = None
        self.filter_apply_pending = True
        self.filter_last_error = None
        self._live_filter_generation = 0
        self._full_view_filter_cache_key = None
        self._full_view_filter_cache_data = None
        self._full_view_filter_cache_timestamps = None
        self.log_messages = []
        self.save_notice_shown = 0
        self.save_notice_hidden = 0
        self.save_notice_updates = []

    def is_array_pzt1_mode(self):
        return False

    def get_effective_samples_per_sweep(self):
        return 1

    def log_status(self, message):
        self.log_messages.append(message)

    def _show_save_data_notice(self, label_text: str = "Saving data..."):
        self.save_notice_shown += 1
        self.save_notice_updates.append(("show", label_text))

    def _update_save_data_notice(self, label_text: str):
        self.save_notice_updates.append(("update", label_text))

    def _hide_save_data_notice(self):
        self.save_notice_hidden += 1


@unittest.skipUnless(SCIPY_FILTERS_AVAILABLE, "SciPy not available")
class DataExporterTests(unittest.TestCase):
    def test_export_prefers_fullest_available_source_over_short_archive_cache(self):
        with workspace_tempdir("data_exporter_source_choice") as tmpdir:
            harness = ExportHarness(tmpdir)
            archive_path = tmpdir / "capture_cache.jsonl"
            archive_path.write_text('{"metadata": {}}\n', encoding="utf-8")
            harness._archive_path = str(archive_path)
            harness.load_archive_data = lambda: (
                [[1.0], [2.0], [3.0]],
                [0.0, 0.1, 0.2],
            )

            source_sweeps, source_timestamps, export_source = harness._load_export_source_data(archive_path)

            self.assertEqual(export_source, "full_view")
            self.assertEqual(len(source_sweeps), len(harness.raw_data))
            self.assertEqual(len(source_timestamps), len(harness.sweep_timestamps))

    def test_save_data_filters_csv_and_records_filter_metadata(self):
        with workspace_tempdir("data_exporter") as tmpdir:
            harness = ExportHarness(tmpdir)

            with patch("file_operations.data_exporter.QMessageBox.information"), patch(
                "file_operations.data_exporter.QMessageBox.warning"
            ), patch("file_operations.data_exporter.QMessageBox.critical"):
                harness.save_data()

            csv_files = sorted(tmpdir.glob("capture_*.csv"))
            metadata_files = sorted(tmpdir.glob("capture_*_metadata.json"))

            self.assertEqual(len(csv_files), 1)
            self.assertEqual(len(metadata_files), 1)

            with csv_files[0].open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))

            self.assertEqual(rows[0], ["CH0", "Force_X", "Force_Z"])
            exported_values = np.asarray([float(row[0]) for row in rows[1:]], dtype=np.float64)
            raw_values = harness.raw_data[:, 0].astype(np.float64)
            self.assertEqual(len(exported_values), len(raw_values))
            self.assertFalse(np.allclose(exported_values, raw_values))

            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            self.assertIn("filtering", metadata)
            self.assertTrue(metadata["filtering"]["enabled"])
            self.assertTrue(metadata["filtering"]["applied"])
            self.assertTrue(metadata["filtering"]["applied_to_csv"])
            self.assertEqual(metadata["filtering"]["settings"]["main_type"], "lowpass")
            self.assertEqual(metadata["filtering"]["settings"]["notches"], [])
            self.assertEqual(metadata["export_source"], "full_view")

    def test_save_data_shows_and_hides_progress_notice(self):
        with workspace_tempdir("data_exporter_notice") as tmpdir:
            harness = ExportHarness(tmpdir)

            with patch("file_operations.data_exporter.QMessageBox.information"), patch(
                "file_operations.data_exporter.QMessageBox.warning"
            ), patch("file_operations.data_exporter.QMessageBox.critical"):
                harness.save_data()

            self.assertEqual(harness.save_notice_shown, 1)
            self.assertEqual(harness.save_notice_hidden, 1)
            self.assertTrue(any(kind == "update" and "Writing CSV data" in text for kind, text in harness.save_notice_updates))
            self.assertTrue(any(kind == "update" and "Writing metadata" in text for kind, text in harness.save_notice_updates))

    def test_save_data_streams_archive_beyond_display_buffer_limit(self):
        with workspace_tempdir("data_exporter_archive_stream") as tmpdir:
            harness = ExportHarness(tmpdir)
            harness.filtering_enabled = False
            harness.raw_data = []
            harness.sweep_timestamps = []
            harness.sweep_count = 50005
            archive_path = tmpdir / "capture_cache.jsonl"
            with archive_path.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps({"metadata": {"channels": [0], "repeat": 1}}) + "\n")
                for idx in range(harness.sweep_count):
                    handle.write(json.dumps({"timestamp_s": idx / 1000.0, "samples": [idx]}) + "\n")
            harness._archive_path = str(archive_path)
            harness._count_archive_sweeps = lambda path: (_ for _ in ()).throw(
                AssertionError("full archive export should stream without a count pass")
            )

            with patch("file_operations.data_exporter.QMessageBox.information"), patch(
                "file_operations.data_exporter.QMessageBox.warning"
            ), patch("file_operations.data_exporter.QMessageBox.critical"):
                harness.save_data()

            csv_files = sorted(path for path in tmpdir.glob("capture_*.csv") if "metadata" not in path.name)
            metadata_files = sorted(tmpdir.glob("capture_*_metadata.json"))

            self.assertEqual(len(csv_files), 1)
            with csv_files[0].open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))

            self.assertEqual(len(rows), harness.sweep_count + 1)
            self.assertEqual(rows[1][0], "0.0")
            self.assertEqual(rows[-1][0], str(float(harness.sweep_count - 1)))

            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            self.assertEqual(metadata["export_source"], "archive")
            self.assertEqual(metadata["saved_sweeps"], harness.sweep_count)


if __name__ == "__main__":
    unittest.main()
