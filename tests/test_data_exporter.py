import csv
import json
import shutil
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import numpy as np

from data_processing.adc_filter_engine import ADCFilterEngine, SCIPY_FILTERS_AVAILABLE
from data_processing.filter_processor import FilterProcessorMixin
from file_operations.data_exporter import DataExporterMixin
from file_operations.export_metadata import build_analysis_export_metadata


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
        capture_start_dt = datetime(2024, 1, 2, 3, 4, 5, 678000)
        capture_start_time = capture_start_dt.timestamp()

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
        self.expected_row_times = [
            capture_start_dt.strftime("%H:%M:%S.%f"),
            "03:04:05.688000",
            "03:04:05.698000",
            "03:04:05.708000",
            "03:04:05.718000",
            "03:04:05.728000",
            "03:04:05.738000",
            "03:04:05.748000",
        ]
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
                "capture_start_time": capture_start_time,
                "capture_end_time": capture_start_time + float(self.sweep_timestamps[-1]),
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
        self.analysis_state = {"pzt_force": {"channel_calibration": {}}}
        self.analysis_snapshot = None

    def is_array_pzt1_mode(self):
        return False

    def is_array_pzt_rs_mode(self):
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


class ArrayExportHarness(ExportHarness):
    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self.raw_data = np.array(
            [
                [2045.0, 2046.0, 2043.0, 2047.0, 2047.0, 2047.0, 2040.0, 2046.0, 2049.0, 2047.0],
                [2047.0, 2046.0, 2046.0, 2049.0, 2048.0, 2048.0, 2040.0, 2046.0, 2049.0, 2047.0],
            ],
            dtype=np.float32,
        )
        self.sweep_timestamps = np.arange(len(self.raw_data), dtype=np.float64) / 100.0
        self.sweep_count = len(self.raw_data)
        self.MAX_SWEEPS_BUFFER = len(self.raw_data)
        self.config["channels"] = [0, 1, 2, 3, 4]
        self.filtering_enabled = False

    def is_array_pzt1_mode(self):
        return True

    def get_display_channel_specs(self):
        return [
            {"label": "PZT3_B", "sample_indices": [0]},
            {"label": "PZT3_L", "sample_indices": [2]},
            {"label": "PZT3_C", "sample_indices": [4]},
            {"label": "PZT3_R", "sample_indices": [6]},
            {"label": "PZT3_T", "sample_indices": [8]},
        ]

    def get_effective_samples_per_sweep(self, channels=None, repeat_count=None):
        return 10


class ArrayFilterMetadataTests(unittest.TestCase):
    def test_per_channel_rates_keyed_by_signal_name_and_uniform(self):
        with workspace_tempdir("array_filter_meta") as tmpdir:
            harness = ArrayExportHarness(tmpdir)
            harness.filtering_enabled = True

            metadata = harness.build_filter_metadata()
            rates = metadata["per_channel_sample_rates_hz"]

            # One entry per named signal (not per reused physical channel), all equal.
            self.assertEqual(
                set(rates.keys()),
                {"PZT3_B", "PZT3_L", "PZT3_C", "PZT3_R", "PZT3_T"},
            )
            values = list(rates.values())
            self.assertTrue(all(abs(v - values[0]) < 1e-6 for v in values))

    def test_capture_timing_uses_capture_wide_measurements_and_reports_ground_reads(self):
        with workspace_tempdir("array_capture_timing") as tmpdir:
            harness = ArrayExportHarness(tmpdir)
            harness.config["use_ground"] = True
            harness.timing_state.adc_active_capture_duration_us = 10_000
            harness.timing_state.adc_emitted_sample_count = 100
            harness.timing_state.adc_block_count = 4
            harness.timing_state.adc_block_gap_total_us = 1_000
            harness.timing_state.adc_block_gap_count = 2

            timing = harness._build_capture_timing_metadata([
                "PZT3_B", "PZT3_L", "PZT3_C", "PZT3_R", "PZT3_T",
            ])

            self.assertEqual(timing["adc_active_sample_interval_us"], 100.0)
            self.assertEqual(timing["adc_mean_block_capture_time_us"], 2500.0)
            self.assertEqual(timing["adc_effective_total_sample_rate_hz"], 9090.909)
            self.assertEqual(timing["adc_mean_block_gap_ms"], 0.5)
            self.assertEqual(
                timing["per_channel_sample_rates_hz"],
                {
                    "PZT3_B": 909.091,
                    "PZT3_L": 909.091,
                    "PZT3_C": 909.091,
                    "PZT3_R": 909.091,
                    "PZT3_T": 909.091,
                },
            )
            self.assertTrue(timing["adc_timing_includes_ground_samples"])
            self.assertIn("ground reads", timing["ground_sample_timing_note"])

    def test_stream_map_keeps_reused_pins_separate(self):
        with workspace_tempdir("array_filter_streams") as tmpdir:
            harness = ArrayExportHarness(tmpdir)

            stream_map = harness._build_filter_stream_map()

            self.assertEqual(
                set(stream_map.keys()),
                {"PZT3_B", "PZT3_L", "PZT3_C", "PZT3_R", "PZT3_T"},
            )
            # Each signal maps to its own distinct sweep column.
            all_positions = [int(v[0]) for v in stream_map.values()]
            self.assertEqual(sorted(all_positions), [0, 2, 4, 6, 8])


class AnalysisExportMetadataTests(unittest.TestCase):
    def test_analysis_export_preserves_loaded_metadata_and_records_settings(self):
        source_metadata = {
            "configuration": {"channels": [0], "repeat_count": 1},
            "mcu_type": "ADC",
            "timing": {"arduino_sample_rate_hz": 100.0},
        }
        analysis_state = {
            "axis_mode": "time_ms",
            "pzt_force": {
                "quiet_duration_s": 2.0,
                "channel_calibration": {
                    "CH0": {
                        "vmid_v": 1.23456,
                        "noise_threshold_v": 0.0456789,
                        "sigma_v": 0.0123456,
                        "mad_v": 0.0098765,
                    }
                },
            },
        }

        metadata = build_analysis_export_metadata(
            source_metadata,
            analysis_state,
            source_id="csv:C:/captures/source.csv|json:C:/captures/source_metadata.json",
            csv_path="C:/captures/analysis.csv",
            x_axis_label="Time",
            x_axis_units="ms",
            exported_traces=["CH0", "Calculated Force - CH0 [N]"],
        )

        self.assertEqual(metadata["configuration"], source_metadata["configuration"])
        self.assertEqual(metadata["mcu_type"], "ADC")
        self.assertEqual(
            metadata["analysis_export"]["settings"]["pzt_force"]["channel_calibration"],
            {
                "CH0": {
                    "vmid_v": 1.235,
                    "noise_threshold_v": 0.04568,
                    "sigma_v": 0.01235,
                    "mad_v": 0.0098765,
                }
            },
        )
        self.assertNotIn("calculated_vmid_noise", metadata["analysis_export"])
        self.assertEqual(metadata["analysis_export"]["csv"]["exported_traces"], ["CH0", "Calculated Force - CH0 [N]"])


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

            self.assertEqual(rows[0], ["Timestamp", "CH0", "Force_X_N", "Force_Z_N"])
            self.assertEqual([row[0] for row in rows[1:]], harness.expected_row_times)
            exported_values = np.asarray([float(row[1]) for row in rows[1:]], dtype=np.float64)
            raw_values = harness.raw_data[:, 0].astype(np.float64)
            self.assertEqual(len(exported_values), len(raw_values))
            self.assertFalse(np.allclose(exported_values, raw_values))

            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            self.assertIn("filtering", metadata)
            self.assertTrue(metadata["filtering"]["enabled"])
            self.assertTrue(metadata["filtering"]["applied"])
            self.assertTrue(metadata["filtering"]["applied_to_csv"])
            self.assertNotIn("total_sample_rate_hz", metadata["filtering"])
            self.assertNotIn("per_channel_sample_rates_hz", metadata["filtering"])
            self.assertEqual(metadata["filtering"]["settings"]["main_type"], "lowpass")
            self.assertEqual(metadata["filtering"]["settings"]["notches"], [])
            self.assertEqual(metadata["export_source"], "full_view")
            self.assertEqual(metadata["row_timestamp"]["column_name"], "Timestamp")
            self.assertEqual(metadata["row_timestamp"]["format"], "HH:MM:SS.ffffff")
            self.assertTrue(metadata["row_timestamp"]["absolute_time_available"])
            self.assertEqual(
                metadata["pzt_vmid_noise"],
                {"CH0": {"vmid_v": "No Data", "noise_threshold_v": "No Data"}},
            )

    def test_save_data_includes_in_memory_analysis_vmid_and_noise(self):
        with workspace_tempdir("data_exporter_vmid_noise") as tmpdir:
            harness = ExportHarness(tmpdir)
            harness.analysis_snapshot = type("Snapshot", (), {"source_id": "in_memory"})()
            harness.analysis_state["pzt_force"]["channel_calibration"] = {
                "CH0": {"vmid_v": 1.23456, "noise_threshold_v": 0.0456789}
            }

            with patch("file_operations.data_exporter.QMessageBox.information"), patch(
                "file_operations.data_exporter.QMessageBox.warning"
            ), patch("file_operations.data_exporter.QMessageBox.critical"):
                harness.save_data()

            metadata_path = next(tmpdir.glob("capture_*_metadata.json"))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(
                metadata["pzt_vmid_noise"],
                {"CH0": {"vmid_v": 1.235, "noise_threshold_v": 0.04568}},
            )

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

    def test_save_data_keeps_555_seconds_column_alongside_clock_timestamp(self):
        with workspace_tempdir("data_exporter_555") as tmpdir:
            harness = ExportHarness(tmpdir)
            harness.device_mode = "555"
            harness.current_mcu = "555"

            with patch("file_operations.data_exporter.QMessageBox.information"), patch(
                "file_operations.data_exporter.QMessageBox.warning"
            ), patch("file_operations.data_exporter.QMessageBox.critical"):
                harness.save_data()

            csv_files = sorted(tmpdir.glob("capture_*.csv"))
            self.assertEqual(len(csv_files), 1)

            with csv_files[0].open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))

            self.assertEqual(rows[0], ["Timestamp", "Timestamp_s", "CH0", "Force_X_N", "Force_Z_N"])
            self.assertEqual(rows[1][0], harness.expected_row_times[0])
            self.assertEqual(rows[1][1], "0.0")
            self.assertEqual(rows[2][1], "0.01")

    def test_save_data_streams_archive_beyond_display_buffer_limit(self):
        with workspace_tempdir("data_exporter_archive_stream") as tmpdir:
            harness = ExportHarness(tmpdir)
            harness.filtering_enabled = False
            harness.raw_data = []
            harness.sweep_timestamps = []
            harness.sweep_count = 50005
            archive_path = tmpdir / "capture_cache.jsonl"
            with archive_path.open("w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "metadata": {
                                "channels": [0],
                                "repeat": 1,
                                "start_time": "2024-01-02T03:04:05.678000",
                            }
                        }
                    )
                    + "\n"
                )
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
            self.assertEqual(rows[0], ["Timestamp", "CH0", "Force_X_N", "Force_Z_N"])
            self.assertEqual(rows[1][0], "03:04:05.678000")
            self.assertEqual(rows[1][1], "0.0")
            self.assertEqual(rows[-1][1], str(float(harness.sweep_count - 1)))

            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            self.assertEqual(metadata["export_source"], "archive")
            self.assertEqual(metadata["saved_sweeps"], harness.sweep_count)

    def test_array_mode_save_data_omits_unlabeled_placeholder_columns(self):
        with workspace_tempdir("data_exporter_array_header") as tmpdir:
            harness = ArrayExportHarness(tmpdir)

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

            self.assertEqual(
                rows[0],
                ["Timestamp", "PZT3_B", "PZT3_L", "PZT3_C", "PZT3_R", "PZT3_T", "Force_X_N", "Force_Z_N"],
            )

            self.assertEqual(len(rows[1]), len(rows[0]))
            self.assertEqual(rows[1][1:6], ["2045.0", "2043.0", "2047.0", "2040.0", "2049.0"])

            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            self.assertEqual(metadata["configuration"]["buffer_total_samples"], harness.buffer_spin.value() * 5)
            self.assertEqual(
                metadata["configuration"]["exported_signal_columns"],
                ["PZT3_B", "PZT3_L", "PZT3_C", "PZT3_R", "PZT3_T"],
            )


if __name__ == "__main__":
    unittest.main()
