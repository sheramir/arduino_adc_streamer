"""
Data Processing Mixin
=====================
Main mixin combining data processing, plotting, timing, and capture lifecycle.

This module combines:
- Serial parsing (SerialParserMixin)
- Binary data processing (BinaryProcessorMixin)
- Force data processing (ForceProcessorMixin)
- Capture lifecycle (CaptureLifecycleMixin)
- Plotting and visualization (defined here)
- Timing calculations (defined here)
"""

import time
from datetime import datetime

from config_constants import MAX_LOG_LINES, IADC_RESOLUTION_BITS

# Import sub-module mixins
from data_processing.capture_lifecycle import CaptureLifecycleMixin
from data_processing.capture_cache import CaptureCacheMixin
from data_processing.adc_plotting import ADCPlottingMixin
from data_processing.force_overlay import ForceOverlayMixin
from data_processing.timing_display import TimingDisplayMixin
from serial_communication.serial_parser import SerialParserMixin
from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.filter_processor import FilterProcessorMixin
from data_processing.force_processor import ForceProcessorMixin


class DataProcessorMixin(ForceOverlayMixin, CaptureCacheMixin, TimingDisplayMixin, ADCPlottingMixin, CaptureLifecycleMixin, FilterProcessorMixin, SerialParserMixin, BinaryProcessorMixin, ForceProcessorMixin):
    """Main mixin class for data processing, visualization, timing, and capture lifecycle."""

    PZR_ZERO_BASELINE_WINDOW_SEC = 0.5
    PZR_AUTO_BASELINE_DELAY_SEC = 1.5

    def apply_y_axis_range(self):
        """Apply Y-axis range setting to the plot."""
        if getattr(self, 'device_mode', 'adc') == '555':
            self.plot_widget.enableAutoRange(axis='y')
            return

        range_text = self.yaxis_range_combo.currentText()
        units_text = self.yaxis_units_combo.currentText()
        
        if range_text == "Adaptive":
            # Auto-scale to visible data
            self.plot_widget.enableAutoRange(axis='y')
        elif range_text == "Full-Scale":
            # Fixed range based on ADC resolution and units
            if units_text == "Voltage":
                # Full voltage range based on reference
                vref = self.get_vref_voltage()
                self.plot_widget.setYRange(0, vref, padding=0.02)
            else:
                # Full ADC range (raw values: 0 to 4095 for 12-bit)
                max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1  # 4095
                self.plot_widget.setYRange(0, max_adc_value, padding=0.02)
        else:
            # Fallback to adaptive
            self.plot_widget.enableAutoRange(axis='y')
    
    # ========================================================================
    # Timing Display
    # ========================================================================
    


    def get_vref_voltage(self) -> float:
        """Get the numeric voltage reference value."""
        vref_str = self.config['reference']

        # Map reference strings to voltage values
        if vref_str == "1.2":
            return 1.2
        elif vref_str == "3.3" or vref_str == "vdd":
            return 3.3
        elif vref_str == "0.8vdd":
            return 3.3 * 0.8  # 2.64V
        elif vref_str == "ext":
            return 1.25  # External reference
        else:
            return 3.3  # Default to VDD


    def log_status(self, message: str):
        """Log a status message."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.status_text.append(f"[{timestamp}] {message}")
        
        # Limit status text to prevent memory overflow during long sessions
        # QTextEdit.toPlainText() includes all lines with newlines
        current_text = self.status_text.toPlainText()
        lines = current_text.split('\n')
        if len(lines) > MAX_LOG_LINES:
            # Keep only the most recent lines
            self.status_text.setPlainText('\n'.join(lines[-MAX_LOG_LINES:]))
        
        # Auto-scroll to bottom
        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )
