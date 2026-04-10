"""
Force Data Processor Mixin
===========================
Handles force sensor data processing and calibration.
"""

import time

from config_constants import FORCE_CALIBRATION_SAMPLES, FORCE_STATUS_UPDATE_INTERVAL_SAMPLES
from data_processing.force_state import get_force_runtime_state


class ForceProcessorMixin:
    """Mixin for force sensor data processing."""
    
    def calibrate_force_sensors(self):
        """Calibrate force sensors by collecting baseline samples without load."""
        state = get_force_runtime_state(self)
        state.calibrating = True
        state.calibration_samples = {'x': [], 'z': []}
        # Calibration will be completed in process_force_data after enough samples.

    def process_force_data(self, x_force: float, z_force: float):
        """Process incoming force measurement data."""
        state = get_force_runtime_state(self)
        state.raw_samples_seen += 1
        if state.raw_samples_seen == 1:
            self.log_status(
                f"First force sample received: x={x_force:.3f}, z={z_force:.3f}"
            )

        # Handle calibration
        if state.calibrating:
            state.calibration_samples['x'].append(x_force)
            state.calibration_samples['z'].append(z_force)
            
            if len(state.calibration_samples['x']) >= FORCE_CALIBRATION_SAMPLES:
                # Calculate average offsets
                state.calibration_offset['x'] = sum(state.calibration_samples['x']) / len(state.calibration_samples['x'])
                state.calibration_offset['z'] = sum(state.calibration_samples['z']) / len(state.calibration_samples['z'])
                
                state.calibrating = False
                self.log_status(f"Force calibration complete: X offset={state.calibration_offset['x']:.1f}, Z offset={state.calibration_offset['z']:.1f}")
                self.log_status("Force sensors ready (calibrated to zero)")
            return
        
        # Apply calibration offsets
        x_calibrated = x_force - state.calibration_offset['x']
        z_calibrated = z_force - state.calibration_offset['z']
        
        store_capture_data = True
        if hasattr(self, "should_store_capture_data"):
            store_capture_data = bool(self.should_store_capture_data())

        if self.is_capturing and state.start_time is not None and store_capture_data:
            timestamp = time.time() - state.start_time
            state.data.append((timestamp, x_calibrated, z_calibrated))
            
            # Update info label
            if len(state.data) % FORCE_STATUS_UPDATE_INTERVAL_SAMPLES == 0:
                samples_per_sweep = max(0, int(getattr(self, 'samples_per_sweep', 0) or 0))
                total_samples = int(self.sweep_count) * samples_per_sweep
                self.plot_info_label.setText(
                    f"ADC - Sweeps: {self.sweep_count} | Samples: {total_samples}  |  Force: {len(state.data)} samples"
                )
            # Schedule the force-only debounce path so the force plot can stay fresh
            # even when no ADC buffer update has arrived yet.
            try:
                if not self.force_plot_timer.isActive():
                    self.force_plot_timer.start(self.force_plot_debounce_ms)
            except Exception:
                pass
