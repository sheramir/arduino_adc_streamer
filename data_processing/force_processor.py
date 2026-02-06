"""
Force Data Processor Mixin
===========================
Handles force sensor data processing and calibration.
"""

import time
from config_constants import MAX_FORCE_SAMPLES


class ForceProcessorMixin:
    """Mixin for force sensor data processing."""
    
    def calibrate_force_sensors(self):
        """Calibrate force sensors by collecting baseline samples without load."""
        self.force_calibrating = True
        self.calibration_samples = {'x': [], 'z': []}
        # Calibration will be completed in process_force_data after 10 samples

    def process_force_data(self, x_force: float, z_force: float):
        """Process incoming force measurement data."""
        # Handle calibration
        if self.force_calibrating:
            self.calibration_samples['x'].append(x_force)
            self.calibration_samples['z'].append(z_force)
            
            if len(self.calibration_samples['x']) >= 10:
                # Calculate average offsets
                self.force_calibration_offset['x'] = sum(self.calibration_samples['x']) / len(self.calibration_samples['x'])
                self.force_calibration_offset['z'] = sum(self.calibration_samples['z']) / len(self.calibration_samples['z'])
                
                self.force_calibrating = False
                self.log_status(f"Force calibration complete: X offset={self.force_calibration_offset['x']:.1f}, Z offset={self.force_calibration_offset['z']:.1f}")
                self.log_status("Force sensors ready (calibrated to zero)")
            return
        
        # Apply calibration offsets
        x_calibrated = x_force - self.force_calibration_offset['x']
        z_calibrated = z_force - self.force_calibration_offset['z']
        
        if self.is_capturing and self.force_start_time is not None:
            timestamp = time.time() - self.force_start_time
            self.force_data.append((timestamp, x_calibrated, z_calibrated))
            
            # Implement rolling window: keep only the most recent force samples
            # This prevents memory overflow during long captures
            if len(self.force_data) > MAX_FORCE_SAMPLES:
                self.force_data = self.force_data[-MAX_FORCE_SAMPLES:]
            
            # Update info label
            if len(self.force_data) % 10 == 0:  # Update every 10 samples
                total_samples = sum(len(sweep) for sweep in self.raw_data) if self.raw_data else 0
                self.plot_info_label.setText(
                    f"ADC - Sweeps: {self.sweep_count} | Samples: {total_samples}  |  Force: {len(self.force_data)} samples"
                )
            # Schedule a debounced force plot update (avoid updating GUI for every sample)
            try:
                if not self.force_plot_timer.isActive():
                    self.force_plot_timer.start(self.force_plot_debounce_ms)
            except Exception:
                pass
