"""
Force Data Processor Mixin
===========================
Handles force sensor data processing and calibration.
"""

import time

from config_constants import FORCE_CALIBRATION_SAMPLES
from data_processing.force_feedback import (
    log_first_force_sample,
    log_force_calibration_ready,
    maybe_update_force_capture_status,
    schedule_force_plot_refresh,
)
from data_processing.force_state import get_force_runtime_state


class ForceProcessorMixin:
    """Mixin for force sensor data processing."""
    
    def calibrate_force_sensors(self):
        """Calibrate force sensors by collecting baseline samples without load."""
        state = get_force_runtime_state(self)
        state.calibrating = True
        state.calibration_samples = {'x': [], 'z': []}
        # Calibration will be completed in process_force_data after enough samples.

    def reset_force_baseline_from_recent_samples(self) -> bool:
        """Recompute the force baseline offset from the latest raw samples."""
        state = get_force_runtime_state(self)
        recent_samples = list(state.recent_raw_samples)
        if len(recent_samples) < FORCE_CALIBRATION_SAMPLES:
            self.log_status(
                "WARNING: Need at least "
                f"{FORCE_CALIBRATION_SAMPLES} recent force samples before resetting load cell"
            )
            return False

        baseline_window = recent_samples[-FORCE_CALIBRATION_SAMPLES:]
        state.calibration_offset['x'] = sum(sample[0] for sample in baseline_window) / FORCE_CALIBRATION_SAMPLES
        state.calibration_offset['z'] = sum(sample[1] for sample in baseline_window) / FORCE_CALIBRATION_SAMPLES
        state.calibrating = False
        state.calibration_samples = {'x': [], 'z': []}
        self.log_status(
            "Load cell reset complete: "
            f"X offset={state.calibration_offset['x']:.1f}, "
            f"Z offset={state.calibration_offset['z']:.1f}"
        )
        self.log_status("Force sensors ready (calibrated to zero)")
        return True

    def _collect_force_calibration_sample(self, state, x_force: float, z_force: float) -> bool:
        """Capture calibration samples until the zero offset is ready."""
        if not state.calibrating:
            return False

        state.calibration_samples['x'].append(x_force)
        state.calibration_samples['z'].append(z_force)

        if len(state.calibration_samples['x']) < FORCE_CALIBRATION_SAMPLES:
            return True

        state.calibration_offset['x'] = sum(state.calibration_samples['x']) / len(
            state.calibration_samples['x']
        )
        state.calibration_offset['z'] = sum(state.calibration_samples['z']) / len(
            state.calibration_samples['z']
        )
        state.calibrating = False
        log_force_calibration_ready(self, state=state)
        return True

    def _store_force_capture_sample(self, state, x_force: float, z_force: float) -> None:
        """Append a calibrated force sample when the capture lifecycle allows it."""
        store_capture_data = True
        if hasattr(self, "should_store_capture_data"):
            store_capture_data = bool(self.should_store_capture_data())

        if not self.is_capturing or state.start_time is None or not store_capture_data:
            return

        timestamp = time.time() - state.start_time
        state.data.append((timestamp, x_force, z_force))
        maybe_update_force_capture_status(self, force_sample_count=len(state.data))
        schedule_force_plot_refresh(self)

    def process_force_data(self, x_force: float, z_force: float):
        """Process incoming force measurement data."""
        state = get_force_runtime_state(self)
        state.raw_samples_seen += 1
        state.recent_raw_samples.append((x_force, z_force))
        log_first_force_sample(self, state=state, x_force=x_force, z_force=z_force)

        if self._collect_force_calibration_sample(state, x_force, z_force):
            return

        x_calibrated = x_force - state.calibration_offset['x']
        z_calibrated = z_force - state.calibration_offset['z']
        self._store_force_capture_sample(state, x_calibrated, z_calibrated)
