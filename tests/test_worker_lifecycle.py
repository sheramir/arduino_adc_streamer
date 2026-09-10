import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from adc_gui import ADCStreamerGUI
from data_processing.analysis_compute_worker import AnalysisComputeWorker
from data_processing.force_block_worker import ForceBlockBatch, ForceBlockWorker
from serial_communication.serial_connect_worker import SerialConnectWorker


class DummyForceEngine:
    def __init__(self):
        self.process_calls = 0
        self.reset_calls = 0

    def process_sample(self, *args, **kwargs):
        self.process_calls += 1

    def apply_jerk_shapes(self, shapes):
        pass

    def package_results(self):
        return ["rendered"]

    def array_result(self):
        return None

    def reset(self):
        self.reset_calls += 1


class DummyConnectWorkflow:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def connect(self, session, port_name, **kwargs):
        self.calls.append((session, port_name, kwargs))
        if self.error is not None:
            raise self.error
        return {"port": port_name}


class WorkerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _stop_worker(self, worker):
        if worker.isRunning():
            worker.stop()
            worker.wait(2000)

    def test_force_worker_processes_result_and_stops(self):
        engine = DummyForceEngine()
        worker = ForceBlockWorker(engine)
        self.addCleanup(self._stop_worker, worker)
        result_spy = QSignalSpy(worker.result_ready)
        worker.start()

        batch = ForceBlockBatch(
            sweeps=np.zeros((1, 1), dtype=np.float64),
            timestamps=np.zeros(1, dtype=np.float64),
            first_sweep_id=0,
            dt_s=0.001,
            voltage_scale=1.0,
            ghost_net_centered=False,
            repeat_slots=1,
            complete_packages={},
            baselines={},
            polarity_multiplier=1.0,
            mux_timing=None,
            jerk_shapes=None,
            dropped_sweeps_before=0,
            grid_positions={},
            channel_calibration={},
        )
        worker.enqueue_batch(batch)

        if not result_spy:
            self.assertTrue(result_spy.wait(2000))
        self.assertEqual(len(result_spy), 1)
        self.assertEqual(engine.process_calls, 1)

        worker.stop()
        self.assertTrue(worker.wait(2000))
        self.assertFalse(worker.isRunning())

    def test_force_worker_stops_while_idle(self):
        worker = ForceBlockWorker(DummyForceEngine())
        self.addCleanup(self._stop_worker, worker)
        worker.start()

        worker.stop()

        self.assertTrue(worker.wait(2000))
        self.assertFalse(worker.isRunning())

    def test_analysis_worker_emits_latest_result_and_stops(self):
        worker = AnalysisComputeWorker()
        self.addCleanup(self._stop_worker, worker)
        result_spy = QSignalSpy(worker.result_ready)
        payload = {
            "generation": 7,
            "snapshot": object(),
            "axis_mode": "time_ms",
            "visible_labels": [],
            "filter_enabled": False,
            "filter_settings": {},
            "overlay_flags": {},
            "vref_voltage": 3.3,
            "integration_window_samples": 1,
            "hpf_cutoff_hz": 0.0,
            "pzt_force_settings": {},
        }

        with patch(
            "data_processing.analysis_compute_worker.prepare_analysis_data",
            return_value="prepared",
        ):
            worker.start()
            worker.submit(payload)
            if not result_spy:
                self.assertTrue(result_spy.wait(2000))

        self.assertEqual(result_spy[0][0]["generation"], 7)
        self.assertEqual(result_spy[0][0]["prepared"], "prepared")
        worker.stop()
        self.assertTrue(worker.wait(2000))

    def test_serial_worker_emits_success_and_stops(self):
        workflow = DummyConnectWorkflow()
        worker = SerialConnectWorker(workflow)
        self.addCleanup(self._stop_worker, worker)
        connected_spy = QSignalSpy(worker.connected)
        worker.start()

        worker.submit("session", "COM7", timeout=1.5)

        if not connected_spy:
            self.assertTrue(connected_spy.wait(2000))
        self.assertEqual(connected_spy[0][0], {"port": "COM7"})
        self.assertEqual(workflow.calls, [("session", "COM7", {"timeout": 1.5})])
        worker.stop()
        self.assertTrue(worker.wait(2000))

    def test_serial_worker_emits_failure_and_stops(self):
        worker = SerialConnectWorker(DummyConnectWorkflow(RuntimeError("no device")))
        self.addCleanup(self._stop_worker, worker)
        failed_spy = QSignalSpy(worker.failed)
        worker.start()

        worker.submit("session", "COM8")

        if not failed_spy:
            self.assertTrue(failed_spy.wait(2000))
        self.assertEqual(failed_spy[0][0], "no device")
        worker.stop()
        self.assertTrue(worker.wait(2000))

    def test_main_window_close_shuts_down_all_workers(self):
        calls = []
        owner = SimpleNamespace(
            serial_port=None,
            force_serial_port=None,
        )
        for method_name in (
            "save_last_spectrum_settings",
            "save_last_heatmap_settings",
            "save_last_shear_settings",
            "save_pressure_map_workspace_layout",
            "save_last_analysis_settings",
            "shutdown_filter_worker",
            "shutdown_spectrum_worker",
            "shutdown_force_worker",
            "shutdown_analysis_worker",
            "shutdown_adc_connect_worker",
            "shutdown_force_connect_worker",
        ):
            setattr(owner, method_name, lambda name=method_name: calls.append(name))
        event = SimpleNamespace(accept=lambda: calls.append("accept"))

        ADCStreamerGUI.closeEvent(owner, event)

        self.assertIn("shutdown_force_worker", calls)
        self.assertEqual(calls[-1], "accept")


if __name__ == "__main__":
    unittest.main()
