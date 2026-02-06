"""
Configuration Management Mixin
===============================
Handles all configuration event handlers and Arduino configuration workflow.
"""

import time
import threading
from PyQt6.QtCore import Qt

from config_constants import (
    INTER_COMMAND_DELAY, MAX_SAMPLES_BUFFER, MAX_PLOT_COLUMNS
)
from config.buffer_utils import validate_and_limit_sweeps_per_block


class ConfigurationMixin:
    """Mixin class for configuration management and event handlers."""
    
    # ========================================================================
    # Configuration Event Handlers (on_*_changed methods)
    # ========================================================================
    
    def on_vref_changed(self, text: str):
        """Handle voltage reference change."""
        vref_map = {
            "1.2V (Internal)": "1.2",
            "3.3V (VDD)": "vdd"
        }
        vref_cmd = vref_map.get(text, "vdd")
        self.config['reference'] = vref_cmd
        self.config_is_valid = False
        self.update_start_button_state()
    
    def on_osr_changed(self, text: str):
        """Handle OSR (oversampling ratio) change."""
        if text.strip():  # Only update if text is not empty
            self.config['osr'] = int(text)
            self.config_is_valid = False
            self.update_start_button_state()
    
    def on_gain_changed(self, text: str):
        """Handle gain change."""
        gain_value = int(text.replace('×', ''))
        self.config['gain'] = gain_value
        self.config_is_valid = False
        self.update_start_button_state()

    def on_channels_changed(self, text: str):
        """Handle channels sequence change."""
        # Always update config when text changes
        if text.strip():
            try:
                # Parse channels for visualization
                channels = [int(c.strip()) for c in text.split(',')]
                self.config['channels'] = channels
                self.update_channel_list()
                self.config_is_valid = False
                self.update_start_button_state()
            except:
                pass
        
        # Don't send command immediately - will be sent on Start
        # This prevents sending incomplete commands while user is typing

    def on_ground_pin_changed(self, value: int):
        """Handle ground pin change."""
        if value >= 0:
            self.config['ground_pin'] = value
            self.config_is_valid = False
            self.update_start_button_state()

    def on_use_ground_changed(self, state: int):
        """Handle use ground checkbox change."""
        use_ground = state == Qt.CheckState.Checked.value
        self.config['use_ground'] = use_ground
        self.config_is_valid = False
        self.update_start_button_state()

    def on_repeat_changed(self, value: int):
        """Handle repeat count change."""
        self.config['repeat'] = value
        self.config_is_valid = False
        self.update_start_button_state()
    
    def on_conv_speed_changed(self, text: str):
        """Handle conversion speed change (Teensy only)."""
        self.config['conv_speed'] = text
        self.config_is_valid = False
        self.update_start_button_state()
    
    def on_samp_speed_changed(self, text: str):
        """Handle sampling speed change (Teensy only)."""
        self.config['samp_speed'] = text
        self.config_is_valid = False
        self.update_start_button_state()
    
    def on_sample_rate_changed(self, value: int):
        """Handle sample rate change (Teensy only)."""
        self.config['sample_rate'] = value
        self.config_is_valid = False
        self.update_start_button_state()
    
    def on_buffer_size_changed(self, value: int):
        """Handle buffer size change and validate against constraints."""
        try:
            channels = self.config.get('channels', [])
            repeat_count = self.config.get('repeat', 1)
            
            if channels and repeat_count > 0:
                channel_count = len(channels)
                validated_value = validate_and_limit_sweeps_per_block(
                    value, channel_count, repeat_count
                )
                
                if validated_value != value:
                    # Value exceeds buffer capacity, set to maximum allowed
                    self.buffer_spin.blockSignals(True)
                    self.buffer_spin.setValue(validated_value)
                    self.buffer_spin.blockSignals(False)
                    
                    samples_per_sweep = channel_count * repeat_count
                    max_samples = validated_value * samples_per_sweep
                    self.log_status(
                        f"Buffer size limited to {validated_value} sweeps "
                        f"({max_samples} samples) - Arduino buffer capacity is {MAX_SAMPLES_BUFFER} samples"
                    )
        except Exception as e:
            pass  # Silently ignore validation errors

    def on_yaxis_range_changed(self, text: str):
        """Handle Y-axis range change."""
        self.trigger_plot_update()

    def on_yaxis_units_changed(self, text: str):
        """Handle Y-axis units change."""
        self.trigger_plot_update()

    def on_use_range_changed(self, state: int):
        """Handle save range checkbox change."""
        enabled = state == Qt.CheckState.Checked.value
        self.min_sweep_spin.setEnabled(enabled)
        self.max_sweep_spin.setEnabled(enabled)

    # ========================================================================
    # Arduino Configuration Workflow
    # ========================================================================
    
    def configure_arduino(self):
        """Configure Arduino with verification and retry."""
        if not self.serial_port or not self.serial_port.is_open:
            return
        
        # Validate input
        channels_text = self.channels_input.text().strip()
        if not channels_text:
            self.log_status("ERROR: Please specify channels first")
            return
        
        try:
            desired_channels = [int(c.strip()) for c in channels_text.split(',')]
        except:
            self.log_status("ERROR: Invalid channel format")
            return
        
        self.log_status("Configuring Arduino...")
        self.configure_btn.setEnabled(False)
        
        # Clear timing data from previous runs
        self.arduino_sample_times = []
        self.buffer_gap_times = []
        
        # Reset completion status and start checking
        self.config_completion_status = None
        self.config_check_timer.start()
        
        # Run configuration in a separate thread to avoid blocking UI
        def config_worker():
            success_flag = False
            try:
                # Check serial port is still valid
                if not self.serial_port or not self.serial_port.is_open:
                    return
                    
                # Flush buffers before configuration
                self.serial_port.reset_input_buffer()
                self.serial_port.reset_output_buffer()
                time.sleep(0.05)
                
                max_attempts = 3
                for attempt in range(max_attempts):
                    success = self.send_config_with_verification()
                    
                    if success:
                        # Verify final configuration
                        verified = self.verify_configuration()
                        if verified:
                            success_flag = True
                            break
                    
                    time.sleep(0.05)  # Brief delay between retries
                    
            except Exception as e:
                pass  # Silent error handling
            finally:
                # Set completion status for main thread to handle
                if success_flag:
                    self.config_completion_status = True
                else:
                    self.config_completion_status = False
        
        # Start configuration in background thread
        threading.Thread(target=config_worker, daemon=True).start()
    
    def check_config_completion(self):
        """Check if configuration has completed (called by timer)."""
        if self.config_completion_status is not None:
            self.config_check_timer.stop()
            
            if self.config_completion_status:
                self.on_configuration_success()
            else:
                self.on_configuration_failed()
            
            # Reset status
            self.config_completion_status = None
    
    def on_configuration_success(self):
        """Handle successful configuration."""
        self.config_is_valid = True
        self.log_status("✓ Configuration verified - Ready to start")
        self.log_status("Configuration complete - all parameters confirmed")
        self.update_start_button_state()
        self.configure_btn.setEnabled(True)
        self.configure_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; }")
        self.statusBar().showMessage("Configured - Ready to capture", 3000)
    
    def on_configuration_failed(self):
        """Handle failed configuration."""
        self.log_status("ERROR: Configuration failed after retries")
        self.configure_btn.setEnabled(True)
        self.configure_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; font-weight: bold; }")
        self.statusBar().showMessage("Configuration failed - please retry", 5000)
    
    def send_config_with_verification(self) -> bool:
        """Send configuration to Arduino with ACK verification and retry.
        
        Returns:
            bool: True if all parameters were set successfully
        """
        # Thread-safe check of serial port
        if not self.serial_port or not self.serial_port.is_open:
            print("Serial port not available for configuration")
            return False
        
        all_success = True
        
        # Determine if this is a Teensy MCU
        is_teensy = self.current_mcu and "Teensy" in self.current_mcu
        
        # Send voltage reference (skip for Teensy - only supports 3.3V)
        if not is_teensy:
            vref_text = self.vref_combo.currentText()
            vref_map = {
                "1.2V (Internal)": "1.2",
                "3.3V (VDD)": "vdd"
            }
            vref_cmd = vref_map.get(vref_text, "vdd")
            success, received = self.send_command_and_wait_ack(f"ref {vref_cmd}", vref_cmd)
            if success:
                self.arduino_status['reference'] = received
            else:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)
        
        # Send OSR (oversampling ratio) / Averaging
        osr_value = self.osr_combo.currentText()
        success, received = self.send_command_and_wait_ack(f"osr {osr_value}", osr_value)
        if success:
            self.arduino_status['osr'] = int(received)
        else:
            all_success = False
        time.sleep(INTER_COMMAND_DELAY)
        
        # Send gain (skip for Teensy - doesn't support gain)
        if not is_teensy:
            gain_value = str(self.config['gain'])
            success, received = self.send_command_and_wait_ack(f"gain {gain_value}", gain_value)
            if success:
                self.arduino_status['gain'] = int(received)
            else:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)
        
        # Teensy-specific: Send conversion speed
        if is_teensy:
            conv_speed = self.conv_speed_combo.currentText()
            success, received = self.send_command_and_wait_ack(f"conv {conv_speed}", conv_speed)
            if not success:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)
        
        # Teensy-specific: Send sampling speed
        if is_teensy:
            samp_speed = self.samp_speed_combo.currentText()
            success, received = self.send_command_and_wait_ack(f"samp {samp_speed}", samp_speed)
            if not success:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)
        
        # Teensy-specific: Send sampling rate
        if is_teensy:
            sample_rate = self.sample_rate_spin.value()
            success, received = self.send_command_and_wait_ack(f"rate {sample_rate}", str(sample_rate))
            if not success:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)
        
        # Send channels
        channels_text = self.channels_input.text().strip()
        if channels_text:
            success, received = self.send_command_and_wait_ack(f"channels {channels_text}", channels_text)
            if success and received:
                self.arduino_status['channels'] = [int(c.strip()) for c in received.split(',')]
            else:
                all_success = False
        time.sleep(0.05)
        
        # Send repeat count
        repeat = str(self.repeat_spin.value())
        success, received = self.send_command_and_wait_ack(f"repeat {repeat}", repeat)
        if success:
            self.arduino_status['repeat'] = int(received)
        else:
            all_success = False
        time.sleep(0.05)
        
        # Send ground settings
        if self.use_ground_check.isChecked():
            # Send "ground N" where N is the pin number (automatically enables ground)
            ground_pin = str(self.ground_pin_spin.value())
            success, received = self.send_command_and_wait_ack(f"ground {ground_pin}", ground_pin)
            if success:
                self.arduino_status['ground_pin'] = int(received)
                self.arduino_status['use_ground'] = True
            else:
                all_success = False
        else:
            # Send "ground false" to disable ground
            success, received = self.send_command_and_wait_ack("ground false", "false")
            if success:
                self.arduino_status['use_ground'] = False
            else:
                all_success = False
        time.sleep(0.05)
        
        # Send buffer size (sweeps per block)
        time.sleep(0.05)
        buffer_size = self.buffer_spin.value()
        # Validate buffer size
        channel_count = len(self.config.get('channels', []))
        repeat_count = self.config.get('repeat', 1)
        
        if buffer_size <= 0:
            # Use default value
            buffer_size = 128
            self.log_status(f"Invalid buffer size, using default value: {buffer_size}")
            self.buffer_spin.setValue(buffer_size)
        else:
            # Validate against buffer capacity
            buffer_size = validate_and_limit_sweeps_per_block(buffer_size, channel_count, repeat_count)
            if buffer_size != self.buffer_spin.value():
                self.log_status(f"Buffer size limited to {buffer_size} sweeps (Arduino buffer capacity)")
                self.buffer_spin.setValue(buffer_size)
        
        buffer_str = str(buffer_size)
        success, received = self.send_command_and_wait_ack(f"buffer {buffer_str}", buffer_str)
        if success:
            self.arduino_status['buffer'] = int(received)
        else:
            all_success = False
        
        return all_success

    def verify_configuration(self) -> bool:
        """Verify that Arduino status matches expected configuration."""
        # Check if we have valid status data
        if self.arduino_status['channels'] is None:
            self.log_status("No status data received yet")
            return False
        
        # Compare channels (most critical)
        expected_channels = self.config.get('channels', [])
        actual_channels = self.arduino_status['channels']
        
        if expected_channels != actual_channels:
            self.log_status(f"MISMATCH: Expected channels {expected_channels}, got {actual_channels}")
            return False
        
        # Check other parameters (optional - only if they were parsed)
        if self.arduino_status['repeat'] is not None:
            if self.arduino_status['repeat'] != self.config.get('repeat'):
                self.log_status(f"MISMATCH: Expected repeat {self.config.get('repeat')}, got {self.arduino_status['repeat']}")
                return False
        
        # All critical checks passed
        self.log_status(f"Configuration matches: {actual_channels}")
        return True
    
    def update_start_button_state(self):
        """Update Start button state based on configuration validity."""
        if self.serial_port and self.serial_port.is_open and not self.is_capturing:
            if self.config_is_valid:
                self.start_btn.setEnabled(True)
                self.start_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
                self.start_btn.setText("Start ✓")
            else:
                self.start_btn.setEnabled(False)
                self.start_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
                self.start_btn.setText("Start (Configure First)")
        else:
            self.start_btn.setEnabled(False)

    # ========================================================================
    # Channel Management
    # ========================================================================

    def update_channel_list(self):
        """Update the channel selector checkboxes based on configured channels."""
        # Clear existing checkboxes
        for checkbox in self.channel_checkboxes.values():
            checkbox.deleteLater()
        self.channel_checkboxes.clear()

        # Clear layout
        while self.channel_checkboxes_layout.count():
            item = self.channel_checkboxes_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.config['channels']:
            return

        # Get unique channels while preserving order
        unique_channels = []
        for ch in self.config['channels']:
            if ch not in unique_channels:
                unique_channels.append(ch)

        # Create checkboxes in a compact grid
        for idx, ch in enumerate(unique_channels):
            from PyQt6.QtWidgets import QCheckBox
            checkbox = QCheckBox(str(ch))
            checkbox.setChecked(True)  # Select all by default
            checkbox.stateChanged.connect(self.trigger_plot_update)

            row = idx // MAX_PLOT_COLUMNS
            col = idx % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(checkbox, row, col)

            self.channel_checkboxes[ch] = checkbox
        
        # Add force sensor checkboxes if force data is available
        if self.force_serial_port and self.force_serial_port.is_open:
            from PyQt6.QtWidgets import QCheckBox
            # X Force checkbox
            self.force_x_checkbox = QCheckBox("X Force")
            self.force_x_checkbox.setChecked(True)
            self.force_x_checkbox.setStyleSheet("QCheckBox { color: red; }")
            self.force_x_checkbox.stateChanged.connect(self.trigger_plot_update)
            row = len(unique_channels) // MAX_PLOT_COLUMNS
            col = len(unique_channels) % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(self.force_x_checkbox, row, col)
            
            # Z Force checkbox
            self.force_z_checkbox = QCheckBox("Z Force")
            self.force_z_checkbox.setChecked(True)
            self.force_z_checkbox.setStyleSheet("QCheckBox { color: blue; }")
            self.force_z_checkbox.stateChanged.connect(self.trigger_plot_update)
            row = (len(unique_channels) + 1) // MAX_PLOT_COLUMNS
            col = (len(unique_channels) + 1) % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(self.force_z_checkbox, row, col)

    def select_all_channels(self):
        """Select all channel checkboxes."""
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(True)
        if self.force_x_checkbox:
            self.force_x_checkbox.setChecked(True)
        if self.force_z_checkbox:
            self.force_z_checkbox.setChecked(True)

    def deselect_all_channels(self):
        """Deselect all channel checkboxes."""
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(False)
        if self.force_x_checkbox:
            self.force_x_checkbox.setChecked(False)
        if self.force_z_checkbox:
            self.force_z_checkbox.setChecked(False)

    # ========================================================================
    # Plot Update Triggers
    # ========================================================================

    def trigger_plot_update(self):
        """Trigger a debounced plot update to avoid lag."""
        # Restart timer
        self.plot_update_timer.stop()
        self.plot_update_timer.start(getattr(self, 'PLOT_UPDATE_DEBOUNCE', 200))

    def reset_graph_view(self):
        """Reset the plot view from full view back to normal windowed view."""
        # Clear full view mode and restore normal buffer-based data
        self.is_full_view = False
        
        # Clear archive data from memory (go back to using buffer)
        with self.buffer_lock:
            self.raw_data.clear()
            self.sweep_timestamps.clear()
        
        # Re-enable button if not capturing
        if not self.is_capturing:
            self.full_view_btn.setEnabled(True)
        
        # Force plot update to show windowed data from buffer
        self.trigger_plot_update()
