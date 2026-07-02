import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from config.adc_config_state import ADCConfigurationState
from constants.force import X_FORCE_SENSOR_TO_NEWTON, Z_FORCE_SENSOR_TO_NEWTON
from constants.pzt_force import PZT_FORCE_DEFAULT_SETTINGS
from data_processing.analysis_workbench import (
    AnalysisSourceSnapshot,
    build_in_memory_snapshot,
    build_overlay_traces,
    estimate_analysis_pzt_force_calibration,
    load_exported_csv_snapshot,
    prepare_analysis_data,
    reorder_circular_capture,
)
from data_processing.pzt_force_calculation import (
    calculate_pzt_force_from_settings,
    calculate_pzt_force_from_voltage,
    estimate_pzt_quiet_baseline,
    pzt_capacitance_to_farads,
)


class AnalysisWorkbenchTests(unittest.TestCase):
    def test_reorder_circular_capture_returns_oldest_to_newest(self):
        data = np.asarray(
            [
                [40, 41],
                [50, 51],
                [10, 11],
                [20, 21],
                [30, 31],
            ],
            dtype=np.float32,
        )
        timestamps = np.asarray([4, 5, 1, 2, 3], dtype=np.float64)

        ordered, ordered_timestamps = reorder_circular_capture(
            data,
            timestamps,
            sweep_count=7,
            write_index=2,
            max_sweeps=5,
        )

        np.testing.assert_array_equal(
            ordered,
            np.asarray([[10, 11], [20, 21], [30, 31], [40, 41], [50, 51]], dtype=np.float32),
        )
        np.testing.assert_array_equal(ordered_timestamps, np.asarray([1, 2, 3, 4, 5], dtype=np.float64))

    def test_build_in_memory_snapshot_accepts_typed_config_state(self):
        owner = SimpleNamespace(
            buffer_lock=threading.Lock(),
            raw_data_buffer=np.asarray([[1, 2], [3, 4]], dtype=np.float32),
            sweep_timestamps_buffer=np.asarray([0.0, 0.01], dtype=np.float64),
            sweep_count=2,
            buffer_write_index=2,
            MAX_SWEEPS_BUFFER=10,
            config=ADCConfigurationState(channels=[1, 2], repeat=1, sample_rate=200),
            force_state=SimpleNamespace(data=[]),
        )
        owner.get_display_channel_specs = lambda: [
            {"label": "PZT6_B", "sample_indices": [0]},
            {"label": "PZT6_C", "sample_indices": [1]},
        ]
        owner.get_rosette_display_channel_specs = lambda: []

        snapshot = build_in_memory_snapshot(owner)

        self.assertEqual(snapshot.channel_labels, ["PZT6_B", "PZT6_C"])
        self.assertEqual(snapshot.metadata["configuration"]["channels"], [1, 2])
        np.testing.assert_array_equal(snapshot.data, owner.raw_data_buffer)

    def test_build_in_memory_snapshot_converts_force_counts_to_newtons(self):
        owner = SimpleNamespace(
            buffer_lock=threading.Lock(),
            raw_data_buffer=np.asarray([[1, 2], [3, 4]], dtype=np.float32),
            sweep_timestamps_buffer=np.asarray([0.0, 0.01], dtype=np.float64),
            sweep_count=2,
            buffer_write_index=2,
            MAX_SWEEPS_BUFFER=10,
            config=ADCConfigurationState(channels=[1, 2], repeat=1, sample_rate=200),
            force_state=SimpleNamespace(
                data=[
                    (0.0, 2.0 * X_FORCE_SENSOR_TO_NEWTON, 3.0 * Z_FORCE_SENSOR_TO_NEWTON),
                    (0.1, 4.0 * X_FORCE_SENSOR_TO_NEWTON, 5.0 * Z_FORCE_SENSOR_TO_NEWTON),
                ]
            ),
        )
        owner.get_display_channel_specs = lambda: []
        owner.get_rosette_display_channel_specs = lambda: []

        snapshot = build_in_memory_snapshot(owner)

        np.testing.assert_allclose(snapshot.force_x_n, [2.0, 4.0])
        np.testing.assert_allclose(snapshot.force_z_n, [3.0, 5.0])

    def test_build_in_memory_snapshot_hides_unlabeled_buffer_columns_when_specs_exist(self):
        owner = SimpleNamespace(
            buffer_lock=threading.Lock(),
            raw_data_buffer=np.asarray([[10, 11, 12, 13], [20, 21, 22, 23]], dtype=np.float32),
            sweep_timestamps_buffer=np.asarray([0.0, 0.01], dtype=np.float64),
            sweep_count=2,
            buffer_write_index=2,
            MAX_SWEEPS_BUFFER=10,
            config=ADCConfigurationState(channels=[1, 2], repeat=1, sample_rate=400),
            force_state=SimpleNamespace(data=[]),
        )
        owner.get_display_channel_specs = lambda: [
            {"label": "PZT3_B", "sample_indices": [0]},
            {"label": "PZT3_L", "sample_indices": [2]},
        ]
        owner.get_rosette_display_channel_specs = lambda: []

        snapshot = build_in_memory_snapshot(owner)
        prepared = prepare_analysis_data(snapshot, vref_voltage=3.3)

        self.assertEqual(snapshot.channel_labels, ["PZT3_B", "PZT3_L"])
        self.assertEqual(snapshot.channel_indices, [0, 2])
        self.assertEqual([trace.label for trace in prepared.traces], ["PZT3_B", "PZT3_L"])

    def test_prepare_analysis_data_converts_adc_counts_to_volts(self):
        snapshot = AnalysisSourceSnapshot(
            data=np.asarray([[0, 2000, 474.6]], dtype=np.float32),
            timestamps_s=np.asarray([0.0], dtype=np.float64),
            channel_labels=["PZT6_B", "PZT6_C", "PZT6_RS1"],
            metadata={"configuration": {"channels": [1, 2, 3], "repeat_count": 1}},
            source_id="unit",
            sample_rate_hz=1000.0,
        )

        prepared = prepare_analysis_data(snapshot, vref_voltage=3.3)
        values_by_label = {trace.label: trace.y for trace in prepared.traces}

        np.testing.assert_allclose(values_by_label["PZT6_B"], [0.0])
        np.testing.assert_allclose(values_by_label["PZT6_C"], [3.3 * 2000.0 / 4095.0])
        np.testing.assert_allclose(values_by_label["PZT6_RS1"], [474.6])

    def test_calculate_pzt_force_uses_leakage_model(self):
        force = calculate_pzt_force_from_voltage(
            np.asarray([1.0, 1.5], dtype=np.float64),
            np.asarray([0.0, 0.001], dtype=np.float64),
            capacitance_f=1e-9,
            rleak_ohm=1e9,
            d33_c_per_n=600e-12,
            noise_threshold_v=0.1,
        )

        centered = np.asarray([-0.25, 0.25], dtype=np.float64)
        expected_second = (1e-9 / 600e-12) * (centered[1] - (np.exp(-0.001 / 1.0) * centered[0]))
        np.testing.assert_allclose(force, [0.0, expected_second])

    def test_calculated_pzt_force_zeroes_after_bipolar_event(self):
        force = calculate_pzt_force_from_voltage(
            np.asarray([0.0, 1.0, -1.0, 0.0], dtype=np.float64),
            np.asarray([0.0, 0.001, 0.002, 0.003], dtype=np.float64),
            capacitance_f=1e-9,
            rleak_ohm=1e9,
            d33_c_per_n=600e-12,
            noise_threshold_v=0.2,
        )

        self.assertAlmostEqual(float(force[-1]), 0.0)

    def test_calculated_pzt_force_ignores_voltage_below_noise_threshold(self):
        force = calculate_pzt_force_from_voltage(
            np.asarray([0.0, 0.05, -0.05, 0.0], dtype=np.float64),
            np.asarray([0.0, 0.001, 0.002, 0.003], dtype=np.float64),
            capacitance_f=1e-9,
            rleak_ohm=1e9,
            d33_c_per_n=600e-12,
            noise_threshold_v=0.1,
        )

        np.testing.assert_allclose(force, np.zeros(4))

    def test_estimate_pzt_quiet_baseline_uses_percentile_threshold_with_mad_diagnostics(self):
        estimate = estimate_pzt_quiet_baseline(
            np.asarray([1.00, 1.01, 0.99, 1.50], dtype=np.float64),
            np.asarray([0.0, 0.1, 0.2, 2.0], dtype=np.float64),
            quiet_duration_s=0.25,
            noise_sigma_multiplier=5.0,
        )

        self.assertAlmostEqual(estimate.vmid_v, 1.0)
        self.assertAlmostEqual(estimate.mad_v, 0.01)
        self.assertAlmostEqual(estimate.noise_threshold_v, 0.01)
        self.assertAlmostEqual(estimate.sigma_v, 0.01 / 5.0)
        self.assertEqual(estimate.sample_count, 3)

    def test_estimate_pzt_quiet_baseline_uses_same_percentile_method_when_mad_is_zero(self):
        estimate = estimate_pzt_quiet_baseline(
            np.asarray([1.0, 1.0, 1.0, 1.0, 1.002], dtype=np.float64),
            np.asarray([0.0, 0.1, 0.2, 0.3, 0.4], dtype=np.float64),
            quiet_duration_s=1.0,
            noise_sigma_multiplier=5.0,
        )

        self.assertAlmostEqual(estimate.vmid_v, 1.0)
        self.assertAlmostEqual(estimate.mad_v, 0.0)
        self.assertGreater(estimate.noise_threshold_v, 0.0)
        self.assertLessEqual(estimate.noise_threshold_v, 0.002)

    def test_calculated_pzt_force_uses_explicit_vmid_and_threshold(self):
        force = calculate_pzt_force_from_voltage(
            np.asarray([1.0, 1.2], dtype=np.float64),
            np.asarray([0.0, 0.001], dtype=np.float64),
            capacitance_f=1e-9,
            rleak_ohm=1e9,
            d33_c_per_n=600e-12,
            noise_threshold_v=0.05,
            vmid_v=1.0,
        )

        expected_second = (1e-9 / 600e-12) * 0.2
        np.testing.assert_allclose(force, [0.0, expected_second])

    def test_estimate_analysis_pzt_force_calibration_skips_resistance_channels(self):
        snapshot = AnalysisSourceSnapshot(
            data=np.asarray([[2048, 470.0], [2050, 471.0], [2046, 472.0]], dtype=np.float32),
            timestamps_s=np.asarray([0.0, 0.01, 0.02], dtype=np.float64),
            channel_labels=["PZT6_C", "PZT6_RS1"],
            metadata={"configuration": {"channels": [1, 2], "repeat_count": 1}},
            source_id="unit",
            sample_rate_hz=200.0,
        )

        estimates = estimate_analysis_pzt_force_calibration(
            snapshot,
            visible_labels=["PZT6_C", "PZT6_RS1"],
            vref_voltage=3.3,
            quiet_duration_s=1.0,
            noise_sigma_multiplier=4.0,
        )

        self.assertEqual(list(estimates), ["PZT6_C"])
        self.assertIn("vmid_v", estimates["PZT6_C"])
        self.assertIn("noise_threshold_v", estimates["PZT6_C"])

    def test_prepare_analysis_data_adds_calculated_pzt_force_for_visible_voltage_channels(self):
        snapshot = AnalysisSourceSnapshot(
            data=np.asarray([[1000, 474.6], [1200, 475.0], [1000, 474.8]], dtype=np.float32),
            timestamps_s=np.asarray([0.0, 0.01, 0.02], dtype=np.float64),
            channel_labels=["PZT6_C", "PZT6_RS1"],
            metadata={"configuration": {"channels": [1, 2], "repeat_count": 1}},
            source_id="unit",
            sample_rate_hz=200.0,
        )

        prepared = prepare_analysis_data(
            snapshot,
            visible_labels=["PZT6_C"],
            vref_voltage=3.3,
            pzt_force_settings={
                "enabled": True,
                "capacitance_value": 1.0,
                "capacitance_unit": "nF",
                "rleak_ohm": 1e9,
                "d33_pc_per_n": 600.0,
                "noise_threshold_v": 0.01,
            },
        )

        self.assertEqual([trace.label for trace in prepared.force_traces], ["Calculated Force - PZT6_C [N]"])
        self.assertEqual(len(prepared.force_traces[0].y), 3)

    def test_pzt_capacitance_units_convert_to_farads(self):
        self.assertAlmostEqual(pzt_capacitance_to_farads(10.0, "pF"), 10e-12)
        self.assertAlmostEqual(pzt_capacitance_to_farads(2.0, "nF"), 2e-9)
        self.assertAlmostEqual(pzt_capacitance_to_farads(3.0, "F"), 3.0)

    def test_pzt_force_settings_helper_uses_shared_defaults(self):
        self.assertEqual(PZT_FORCE_DEFAULT_SETTINGS["capacitance_value"], 150.0)
        self.assertEqual(PZT_FORCE_DEFAULT_SETTINGS["capacitance_unit"], "pF")
        self.assertEqual(PZT_FORCE_DEFAULT_SETTINGS["rleak_ohm"], 1_000_000.0)
        force = calculate_pzt_force_from_settings(
            np.asarray([1.0, 1.2], dtype=np.float64),
            np.asarray([0.0, 0.001], dtype=np.float64),
            {"enabled": True},
        )

        self.assertEqual(force.shape, (2,))

    def test_load_exported_csv_snapshot_validates_metadata_column_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            csv_path = temp_path / "capture.csv"
            metadata_path = temp_path / "capture_metadata.json"
            csv_path.write_text(
                "Timestamp,CH1,CH2,Force_X_N,Force_Z_N\n"
                "00:00:00.000000,1,2,0.5,1.5\n"
                "00:00:00.010000,3,4,0.6,1.6\n",
                encoding="utf-8",
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "configuration": {"channels": [1, 2], "repeat_count": 1},
                        "capture_duration_seconds": 0.01,
                        "timing": {"arduino_sample_rate_hz": 200.0},
                    }
                ),
                encoding="utf-8",
            )

            snapshot = load_exported_csv_snapshot(csv_path, metadata_path)

            self.assertEqual(snapshot.channel_labels, ["CH1", "CH2"])
            self.assertEqual(snapshot.data.shape, (2, 2))
            np.testing.assert_allclose(snapshot.timestamps_s, [0.0, 0.01])
            np.testing.assert_allclose(snapshot.force_x_n, [0.5, 0.6])

    def test_load_exported_csv_snapshot_converts_legacy_force_columns_to_newtons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            csv_path = temp_path / "legacy_force.csv"
            metadata_path = temp_path / "legacy_force_metadata.json"
            csv_path.write_text(
                "Timestamp,CH1,Force_X,Force_Z\n"
                f"00:00:00.000000,1,{2.0 * X_FORCE_SENSOR_TO_NEWTON},{3.0 * Z_FORCE_SENSOR_TO_NEWTON}\n"
                f"00:00:00.010000,2,{4.0 * X_FORCE_SENSOR_TO_NEWTON},{5.0 * Z_FORCE_SENSOR_TO_NEWTON}\n",
                encoding="utf-8",
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "configuration": {"channels": [1], "repeat_count": 1},
                        "capture_duration_seconds": 0.01,
                        "timing": {"arduino_sample_rate_hz": 100.0},
                    }
                ),
                encoding="utf-8",
            )

            snapshot = load_exported_csv_snapshot(csv_path, metadata_path)

            np.testing.assert_allclose(snapshot.force_x_n, [2.0, 4.0])
            np.testing.assert_allclose(snapshot.force_z_n, [3.0, 5.0])

    def test_load_exported_csv_snapshot_accepts_array_export_force_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            csv_path = temp_path / "array.csv"
            metadata_path = temp_path / "array_metadata.json"
            csv_path.write_text(
                "PZT6_B,PZT6_L,PZT6_C,PZT6_R,PZT6_T,PZT6_RS1,PZT6_RS2,Force_X,Force_Z\n"
                "2046,2052,2039,2049,2044,474.6,455.42,0,0\n"
                "2044,2052,2038,2050,2044,474.6,455.42,0,0\n",
                encoding="utf-8",
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "configuration": {
                            "channels": [10, 11, 12, 13, 14],
                            "repeat_count": 1,
                            "buffer_total_samples": 7,
                        },
                        "capture_duration_seconds": 0.01,
                        "timing": {"arduino_sample_rate_hz": 20833.333333333332},
                    }
                ),
                encoding="utf-8",
            )

            snapshot = load_exported_csv_snapshot(csv_path, metadata_path)

            self.assertEqual(snapshot.channel_labels, [
                "PZT6_B",
                "PZT6_L",
                "PZT6_C",
                "PZT6_R",
                "PZT6_T",
                "PZT6_RS1",
                "PZT6_RS2",
            ])
            self.assertEqual(snapshot.data.shape, (2, 7))
            np.testing.assert_allclose(snapshot.force_x_n, [0.0, 0.0])

    def test_prepare_analysis_data_builds_requested_overlays(self):
        snapshot = AnalysisSourceSnapshot(
            data=np.asarray(
                [
                    [100, -100, 80, 40, -40],
                    [120, -120, 100, 50, -50],
                    [140, -140, 120, 60, -60],
                ],
                dtype=np.float32,
            ),
            timestamps_s=np.asarray([0.0, 0.01, 0.02], dtype=np.float64),
            channel_labels=["C", "L", "R", "T", "B"],
            metadata={"configuration": {"channels": [1, 2, 3, 4, 5], "repeat_count": 1}},
            source_id="unit",
            sample_rate_hz=500.0,
        )

        prepared = prepare_analysis_data(
            snapshot,
            axis_mode="time_ms",
            overlay_flags={"shear": True, "normal": True, "integration": True},
            vref_voltage=3.3,
            integration_window_samples=1,
            hpf_cutoff_hz=0.0,
        )

        overlay_labels = {trace.label for trace in prepared.overlay_traces}
        self.assertIn("Shear L/R [V]", overlay_labels)
        self.assertIn("Shear T/B [V]", overlay_labels)
        self.assertIn("Normal Pressure [V]", overlay_labels)
        self.assertIn("Integrated C [V samples]", overlay_labels)

        direct_overlays = build_overlay_traces(
            snapshot,
            snapshot.data,
            axis_mode="samples",
            overlay_flags={"shear": True},
            vref_voltage=3.3,
            integration_window_samples=1,
            hpf_cutoff_hz=0.0,
        )
        self.assertEqual([trace.label for trace in direct_overlays], ["Shear L/R [V]", "Shear T/B [V]"])


if __name__ == "__main__":
    unittest.main()
