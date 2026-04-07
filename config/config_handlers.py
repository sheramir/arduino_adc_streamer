"""
Configuration Management Mixin
===============================
Handles all configuration event handlers and Arduino configuration workflow.
"""

import time
import threading
from PyQt6.QtCore import Qt

from config_constants import (
    INTER_COMMAND_DELAY, MAX_SAMPLES_BUFFER, MAX_PLOT_COLUMNS,
    ANALYZER555_DEFAULT_CF_UNIT, ANALYZER555_DEFAULT_CF_VALUE
)
from config.buffer_utils import validate_and_limit_sweeps_per_block


class ConfigurationMixin:
    """Mixin class for configuration management and event handlers."""

    def is_array_mcu_mode(self) -> bool:
        """Return True for any Array* MCU identifier."""
        return (self.current_mcu or "").strip().lower().startswith("array")

    def is_array_pzt1_mode(self) -> bool:
        """Return True when the connected MCU streams paired MUX data."""
        return (self.current_mcu or "").strip().lower() == "array_pzt1".lower()

    def get_allowed_channel_max(self) -> int:
        """Return max channel index for manual channel entry validation."""
        return 15 if self.is_array_mcu_mode() else 9

    def is_array_pzt_pzr_mode(self) -> bool:
        """Return True when MCU supports runtime PZT/PZR mode switching."""
        return (self.current_mcu or "").strip().lower().startswith("array_pzt_pzr")

    def get_selected_array_operation_mode(self) -> str:
        """Return selected operation mode for dual Array_PZT_PZR devices."""
        if self.is_array_pzt_pzr_mode() and hasattr(self, 'array_mode_combo'):
            selected = (self.array_mode_combo.currentText() or "PZT").strip().upper()
            if selected in ("PZT", "PZR"):
                return selected
        return "PZR" if getattr(self, 'device_mode', 'adc') == '555' else "PZT"

    def update_array_acquisition_inputs_visibility(self):
        """Show PZT/PZR selectors only for Array* MCU modes."""
        is_array = self.is_array_mcu_mode()
        is_dual_mode = self.is_array_pzt_pzr_mode()
        selected_mode = self.get_selected_array_operation_mode() if is_dual_mode else ""

        if hasattr(self, 'array_mode_label'):
            self.array_mode_label.setVisible(is_dual_mode)
        if hasattr(self, 'array_mode_combo'):
            self.array_mode_combo.setVisible(is_dual_mode)

        show_pzt = is_array and (not is_dual_mode or selected_mode == "PZT")
        show_pzr = is_array and (not is_dual_mode or selected_mode == "PZR")

        if hasattr(self, 'pzt_sequence_label'):
            self.pzt_sequence_label.setVisible(show_pzt)
        if hasattr(self, 'pzt_sequence_input'):
            self.pzt_sequence_input.setVisible(show_pzt)
        if hasattr(self, 'pzr_sequence_label'):
            self.pzr_sequence_label.setVisible(show_pzr)
        if hasattr(self, 'pzr_sequence_input'):
            self.pzr_sequence_input.setVisible(show_pzr)

        if not is_array:
            if hasattr(self, 'pzt_sequence_input'):
                self.pzt_sequence_input.blockSignals(True)
                self.pzt_sequence_input.clear()
                self.pzt_sequence_input.blockSignals(False)
            if hasattr(self, 'pzr_sequence_input'):
                self.pzr_sequence_input.blockSignals(True)
                self.pzr_sequence_input.clear()
                self.pzr_sequence_input.blockSignals(False)

    def _parse_sensor_numbers(self, text: str, prefix: str) -> list[str]:
        """Parse '1,3,5' into ['PZT1','PZT3','PZT5'] or ['PZR...'].

        Raises ValueError on invalid format.
        """
        raw = (text or "").strip()
        if not raw:
            return []

        sensors: list[str] = []
        seen = set()
        for token in raw.split(','):
            stripped = token.strip()
            if not stripped:
                continue
            try:
                number = int(stripped)
            except ValueError as exc:
                raise ValueError(f"Invalid {prefix} sensor list value '{stripped}'") from exc
            if number <= 0:
                raise ValueError(f"{prefix} sensor numbers must be > 0")

            sensor_id = f"{prefix}{number}"
            if sensor_id not in seen:
                seen.add(sensor_id)
                sensors.append(sensor_id)
        return sensors

    def get_effective_channels_selection(self, require_non_empty: bool = False):
        """Resolve effective channels with manual Channels Sequence override.

        Priority:
        1) If Channels Sequence is non-empty, use it and ignore PZT/PZR inputs.
        2) Else if Array* MCU, map PZT/PZR sensor IDs via active sensor mux_mapping.
        """
        channels_text = self.channels_input.text().strip() if hasattr(self, 'channels_input') else ""
        if channels_text:
            try:
                channels = [int(c.strip()) for c in channels_text.split(',') if c.strip()]
            except ValueError as exc:
                raise ValueError("Invalid channel format in Channels Sequence") from exc

            channel_max = self.get_allowed_channel_max()
            if any(channel < 0 or channel > channel_max for channel in channels):
                raise ValueError(f"Channels Sequence values must be in range 0-{channel_max}")
            if not channels and require_non_empty:
                raise ValueError("Please specify channels first")
            return channels, ",".join(str(c) for c in channels), "manual", []

        if not self.is_array_mcu_mode():
            if require_non_empty:
                raise ValueError("Please specify channels first")
            return [], "", "none", []

        pzt_text = self.pzt_sequence_input.text().strip() if hasattr(self, 'pzt_sequence_input') else ""
        pzr_text = self.pzr_sequence_input.text().strip() if hasattr(self, 'pzr_sequence_input') else ""

        if self.is_array_pzt_pzr_mode():
            selected_mode = self.get_selected_array_operation_mode()
            if selected_mode == "PZR":
                requested_sensors = self._parse_sensor_numbers(pzr_text, "PZR")
            else:
                requested_sensors = self._parse_sensor_numbers(pzt_text, "PZT")
        else:
            pzt_sensors = self._parse_sensor_numbers(pzt_text, "PZT")
            pzr_sensors = self._parse_sensor_numbers(pzr_text, "PZR")
            requested_sensors = pzt_sensors + pzr_sensors

        if not requested_sensors:
            if require_non_empty:
                if self.is_array_pzt_pzr_mode():
                    selected_mode = self.get_selected_array_operation_mode()
                    raise ValueError(f"Specify Channels Sequence or {selected_mode} sensor selections")
                raise ValueError("Specify Channels Sequence or PZT/PZR sensor selections")
            return [], "", "none", []

        active_config = self.get_active_sensor_configuration() if hasattr(self, 'get_active_sensor_configuration') else {}
        mux_mapping = active_config.get('mux_mapping', {}) if isinstance(active_config, dict) else {}
        if not isinstance(mux_mapping, dict) or not mux_mapping:
            raise ValueError("No array sensor association configured in Sensor Layout")

        missing = [sensor_id for sensor_id in requested_sensors if sensor_id not in mux_mapping]
        if missing:
            raise ValueError("No channel association configured for: " + ", ".join(missing))

        channels: list[int] = []
        for sensor_id in requested_sensors:
            mapping = mux_mapping.get(sensor_id, {})
            sensor_channels = mapping.get('channels', []) if isinstance(mapping, dict) else []
            if not isinstance(sensor_channels, list) or not sensor_channels:
                raise ValueError(f"No channels configured for {sensor_id}")
            for value in sensor_channels:
                try:
                    channel = int(value)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Invalid channel configured for {sensor_id}") from exc
                if channel < 0 or channel > 15:
                    raise ValueError(f"Out-of-range channel configured for {sensor_id}: {channel}")
                channels.append(channel)

        if not channels:
            raise ValueError("Selected sensors did not resolve to any channels")

        return channels, ",".join(str(c) for c in channels), "array", requested_sensors

    def get_effective_channel_multiplier(self) -> int:
        """Return how many physical samples each requested channel produces."""
        return 2 if self.is_array_pzt1_mode() else 1

    def is_array_sensor_selection_mode(self) -> bool:
        """Return True when active channel selection comes from Array sensor IDs."""
        return (
            self.is_array_mcu_mode()
            and str(self.config.get('channel_selection_source', 'none')).lower() == 'array'
            and bool(self.config.get('selected_array_sensors', []))
        )

    def get_array_selected_sensor_groups(self):
        """Return ordered selected Array sensor groups with sequence positions."""
        if not self.is_array_sensor_selection_mode():
            return []

        selected_sensors = list(self.config.get('selected_array_sensors', []))
        active_config = self.get_active_sensor_configuration() if hasattr(self, 'get_active_sensor_configuration') else {}
        mux_mapping = active_config.get('mux_mapping', {}) if isinstance(active_config, dict) else {}

        groups = []
        seq_cursor = 0
        for sensor_id in selected_sensors:
            sensor_mapping = mux_mapping.get(sensor_id, {}) if isinstance(mux_mapping, dict) else {}
            if not isinstance(sensor_mapping, dict):
                continue

            sensor_channels = []
            for value in sensor_mapping.get('channels', []):
                try:
                    sensor_channels.append(int(value))
                except (ValueError, TypeError):
                    continue

            if not sensor_channels:
                continue

            groups.append({
                'sensor_id': sensor_id,
                'mux': int(sensor_mapping.get('mux', 1)),
                'channels': sensor_channels,
                'positions': list(range(seq_cursor, seq_cursor + len(sensor_channels))),
            })
            seq_cursor += len(sensor_channels)

        return groups

    def get_sensor_package_groups(self, required_channels: int, channels=None):
        """Return normalized sensor-package groups for array and standard layouts."""
        if channels is None:
            channels = self.config.get('channels', [])
        channels = list(channels or [])

        try:
            required_channels = max(1, int(required_channels))
        except (TypeError, ValueError):
            return []

        if not channels:
            return []

        if self.is_array_sensor_selection_mode():
            sensor_groups = self.get_array_selected_sensor_groups()
            if not sensor_groups:
                return []
            if any(len(group.get('channels', [])) != required_channels for group in sensor_groups):
                return []

            normalized_groups = []
            for group in sensor_groups:
                normalized_groups.append({
                    'sensor_id': group.get('sensor_id'),
                    'mux': int(group.get('mux', 1)),
                    'channels': list(group.get('channels', [])),
                    'positions': list(group.get('positions', [])),
                })
            return normalized_groups

        unique_channels = []
        for channel in channels:
            if channel not in unique_channels:
                unique_channels.append(channel)

        if len(unique_channels) < required_channels or len(unique_channels) % required_channels != 0:
            return []

        package_groups = []
        for package_index in range(len(unique_channels) // required_channels):
            start = package_index * required_channels
            end = (package_index + 1) * required_channels
            package_groups.append({
                'sensor_id': None,
                'mux': 1,
                'channels': unique_channels[start:end],
                'positions': [],
            })

        return package_groups

    def get_channels_for_arduino_command(self):
        """Return channel list to send to firmware.

        In array sensor-selection mode, internal channel lists can intentionally
        contain duplicates (for per-sensor grouping). Firmware expects one
        channel-address set, so send first-occurrence unique channels only.
        """
        channels = list(self.config.get('channels', []))
        if not channels:
            return []

        if self.is_array_sensor_selection_mode():
            unique_channels = []
            seen = set()
            for channel in channels:
                if channel in seen:
                    continue
                seen.add(channel)
                unique_channels.append(channel)
            return unique_channels

        return channels

    def get_effective_samples_per_sweep(self, channels=None, repeat_count=None) -> int:
        """Return the physical sample width of one sweep for the active MCU."""
        if channels is None:
            channels = self.config.get('channels', [])
        if repeat_count is None:
            repeat_count = self.config.get('repeat', 1)
        return len(channels) * max(1, int(repeat_count)) * self.get_effective_channel_multiplier()

    def get_display_channel_specs(self, channels=None, repeat_count=None):
        """Build display-channel metadata for plotting and channel selectors."""
        if channels is None:
            channels = self.config.get('channels', [])
        if repeat_count is None:
            repeat_count = self.config.get('repeat', 1)
        repeat_count = max(1, int(repeat_count))

        unique_channels = []
        for channel in channels:
            if channel not in unique_channels:
                unique_channels.append(channel)

        specs = []
        selection_source = str(self.config.get('channel_selection_source', 'manual')).lower()
        selected_array_sensors = self.config.get('selected_array_sensors', [])

        if self.is_array_mcu_mode() and selection_source == 'array' and selected_array_sensors:
            sensor_groups = self.get_array_selected_sensor_groups()
            channel_sensor_map = self.get_active_channel_sensor_map() if hasattr(self, 'get_active_channel_sensor_map') else ["T", "R", "C", "L", "B"]

            color_slot = 0
            for group in sensor_groups:
                sensor_id = group['sensor_id']
                mux_num = int(group.get('mux', 1))
                sensor_channels = list(group.get('channels', []))
                seq_positions = list(group.get('positions', []))

                for local_idx, channel in enumerate(sensor_channels):
                    sample_indices = []
                    if local_idx < len(seq_positions):
                        seq_idx = int(seq_positions[local_idx])
                        if self.is_array_pzt1_mode():
                            mux_index = max(0, min(1, mux_num - 1))
                            base_idx = seq_idx * repeat_count * 2
                            for repeat_idx in range(repeat_count):
                                sample_indices.append(base_idx + (repeat_idx * 2) + mux_index)
                        else:
                            base_idx = seq_idx * repeat_count
                            sample_indices.extend(range(base_idx, base_idx + repeat_count))

                    placement = str(channel_sensor_map[local_idx]) if local_idx < len(channel_sensor_map) else f"C{local_idx + 1}"
                    key = ('sensor', sensor_id, placement, channel, mux_num) if self.is_array_pzt1_mode() else ('sensor', sensor_id, placement, channel)
                    specs.append({
                        'key': key,
                        'label': f"{sensor_id}_{placement}",
                        'sample_indices': sample_indices,
                        'color_slot': color_slot,
                    })
                    color_slot += 1

            if specs:
                return specs

        if self.is_array_pzt1_mode():
            for mux_index in range(2):
                mux_number = mux_index + 1
                for display_order, channel in enumerate(unique_channels):
                    sample_indices = []
                    for seq_idx, seq_channel in enumerate(channels):
                        if seq_channel != channel:
                            continue
                        base_idx = seq_idx * repeat_count * 2
                        for repeat_idx in range(repeat_count):
                            sample_indices.append(base_idx + (repeat_idx * 2) + mux_index)

                    specs.append({
                        'key': ('mux', mux_number, channel),
                        'label': f"M{mux_number}_Ch{channel}",
                        'sample_indices': sample_indices,
                        'color_slot': mux_index * max(1, len(unique_channels)) + display_order,
                    })
            return specs

        for display_order, channel in enumerate(unique_channels):
            sample_indices = []
            for seq_idx, seq_channel in enumerate(channels):
                if seq_channel != channel:
                    continue
                base_idx = seq_idx * repeat_count
                sample_indices.extend(range(base_idx, base_idx + repeat_count))

            specs.append({
                'key': ('adc', channel),
                'label': f"Ch {channel}",
                'sample_indices': sample_indices,
                'color_slot': display_order,
            })

        return specs
    
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
        # Manual channels override PZT/PZR selectors when non-empty
        if text.strip():
            try:
                # Parse channels for visualization
                channels = [int(c.strip()) for c in text.split(',') if c.strip()]
                self.config['channels'] = channels
                self.config['channel_selection_source'] = 'manual'
                self.config['selected_array_sensors'] = []
                self.update_channel_list()
                self.config_is_valid = False
                self.update_start_button_state()
            except ValueError:
                # Invalid channel format - will be caught when configuring
                pass
        elif self.is_array_mcu_mode():
            # Recompute from PZT/PZR selectors when manual channels are cleared
            self.on_array_sensor_selection_changed("")
        
        # Don't send command immediately - will be sent on Start
        # This prevents sending incomplete commands while user is typing

    def on_array_sensor_selection_changed(self, _text: str):
        """Handle PZT/PZR array sensor selectors in acquisition section."""
        if not self.is_array_mcu_mode():
            return

        # Explicit Channels Sequence has higher priority; ignore selectors.
        if hasattr(self, 'channels_input') and self.channels_input.text().strip():
            return

        try:
            channels, _, source, selected_sensors = self.get_effective_channels_selection(require_non_empty=False)
            if source == 'array':
                self.config['channels'] = channels
                self.config['channel_selection_source'] = 'array'
                self.config['selected_array_sensors'] = list(selected_sensors)
                self.update_channel_list()
                self.config_is_valid = False
                self.update_start_button_state()
            elif source == 'none':
                self.config['channels'] = []
                self.config['channel_selection_source'] = 'none'
                self.config['selected_array_sensors'] = []
                self.update_channel_list()
                self.config_is_valid = False
                self.update_start_button_state()
        except ValueError:
            # Keep UI responsive while user is typing; hard validation occurs on Configure.
            pass

    def on_array_operation_mode_changed(self, text: str):
        """Handle operation mode selection for Array_PZT_PZR* MCUs."""
        if not self.is_array_pzt_pzr_mode():
            return

        previous_mode = getattr(self, 'device_mode', 'adc')
        if hasattr(self, 'save_last_heatmap_settings'):
            self.save_last_heatmap_settings()

        mode = (text or "PZT").strip().upper()
        if mode not in ("PZT", "PZR"):
            mode = "PZT"

        self.config['array_operation_mode'] = mode
        self.device_mode = '555' if mode == 'PZR' else 'adc'

        if hasattr(self, 'update_gui_for_mcu'):
            self.update_gui_for_mcu()

        if hasattr(self, 'channels_input') and not self.channels_input.text().strip():
            self.on_array_sensor_selection_changed("")

        self.config_is_valid = False
        self.update_start_button_state()
        if previous_mode != self.device_mode:
            self.log_status(f"Array operation mode selected: {mode}")

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

    def _get_cf_farads_from_controls(self) -> float:
        unit = self.cf_unit_combo.currentText() if hasattr(self, 'cf_unit_combo') else ANALYZER555_DEFAULT_CF_UNIT
        value = float(self.cf_value_spin.value()) if hasattr(self, 'cf_value_spin') else ANALYZER555_DEFAULT_CF_VALUE
        scale = {'pF': 1e-12, 'nF': 1e-9, 'uF': 1e-6}.get(unit, 1e-9)
        return value * scale

    def on_rb_changed(self, value: float):
        self.config['rb_ohms'] = float(value)
        self.config_is_valid = False
        self.update_start_button_state()

    def on_rk_changed(self, value: float):
        self.config['rk_ohms'] = float(value)
        self.config_is_valid = False
        self.update_start_button_state()

    def on_cf_changed(self, _):
        self.config['cf_farads'] = self._get_cf_farads_from_controls()
        self.config_is_valid = False
        self.update_start_button_state()

    def on_rxmax_changed(self, value: float):
        self.config['rxmax_ohms'] = float(value)
        self.config_is_valid = False
        self.update_start_button_state()

    def _apply_555_parameter(self, command_name: str, value: str):
        if not self.serial_port or not self.serial_port.is_open:
            self.log_status("ERROR: Connect a device before applying 555 parameters")
            return

        if getattr(self, 'device_mode', 'adc') != '555':
            self.log_status("Ignoring 555 parameter apply while not in 555 mode")
            return

        success, received = self.send_command_and_wait_ack(f"{command_name} {value}", None)
        if success:
            shown = received if received is not None and received != '' else value
            self.log_status(f"Applied {command_name}={shown}")
            self.config_is_valid = False
            self.update_start_button_state()
        else:
            self.log_status(f"ERROR: Failed to apply {command_name}")

    def on_apply_rb_clicked(self):
        value = str(int(round(self.rb_spin.value())))
        self.config['rb_ohms'] = float(value)
        self._apply_555_parameter('rb', value)

    def on_apply_rk_clicked(self):
        value = str(int(round(self.rk_spin.value())))
        self.config['rk_ohms'] = float(value)
        self._apply_555_parameter('rk', value)

    def on_apply_cf_clicked(self):
        cf_farads = self._get_cf_farads_from_controls()
        self.config['cf_farads'] = cf_farads
        self._apply_555_parameter('cf', f"{cf_farads:.12g}")

    def on_apply_rxmax_clicked(self):
        value = str(int(round(self.rxmax_spin.value())))
        self.config['rxmax_ohms'] = float(value)
        self._apply_555_parameter('rxmax', value)
    
    def on_buffer_size_changed(self, value: int):
        """Handle buffer size change and validate against constraints."""
        try:
            channels = self.config.get('channels', [])
            repeat_count = self.config.get('repeat', 1)
            
            if channels and repeat_count > 0:
                channel_count = len(channels) * self.get_effective_channel_multiplier()
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
            self.log_status(f"Buffer validation error: {e}")

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
        try:
            desired_channels, effective_channels_text, source, selected_sensors = self.get_effective_channels_selection(require_non_empty=True)
        except ValueError as exc:
            self.log_status(f"ERROR: {exc}")
            return

        self.config['channels'] = desired_channels
        self.config['channel_selection_source'] = source
        self.config['selected_array_sensors'] = list(selected_sensors)
        self.update_channel_list()
        if source == 'array' and not self.channels_input.text().strip():
            self.log_status(f"Using Array sensor selection -> channels: {effective_channels_text}")
        
        self.log_status("Configuring Arduino...")
        self.configure_btn.setEnabled(False)
        
        # Clear timing data from previous runs
        self.timing_state.arduino_sample_times.clear()
        self.timing_state.buffer_gap_times.clear()
        
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
                self.log_status(f"Configuration error: {e}")
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
            return False

        if self.is_array_pzt_pzr_mode():
            selected_mode = self.get_selected_array_operation_mode()
            self.config['array_operation_mode'] = selected_mode
            self.device_mode = '555' if selected_mode == 'PZR' else 'adc'

            success, received = self.send_command_and_wait_ack(f"mode {selected_mode}", selected_mode)
            if not success:
                self.log_status(f"Dual-mode command failed: mode {selected_mode}")
                return False

            self.log_status(f"Set Array operating mode: {received or selected_mode}")
            time.sleep(INTER_COMMAND_DELAY)

        if getattr(self, 'device_mode', 'adc') == '555':
            return self._send_555_config_with_verification()
        
        all_success = True
        
        # Determine if this is a Teensy MCU
        is_teensy = self.current_mcu and "Teensy" in self.current_mcu
        is_array_mcu = self.is_array_mcu_mode()
        
        # Send voltage reference (skip for Teensy/Array - fixed 3.3V behavior)
        if not is_teensy and not is_array_mcu:
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
        elif is_array_mcu:
            self.config['reference'] = 'vdd'
            self.arduino_status['reference'] = 'vdd'
        
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
        
        # Send channels to firmware (array sensor mode uses unique channel addresses)
        channels_to_send = self.get_channels_for_arduino_command()
        channels_text = ",".join(str(channel) for channel in channels_to_send)
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
        # Validate buffer size using firmware channel sequence
        channel_count = len(channels_to_send) * self.get_effective_channel_multiplier()
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

    def _send_555_config_with_verification(self) -> bool:
        """Send only 555-analyzer supported configuration commands."""
        all_success = True

        channels_to_send = self.get_channels_for_arduino_command()
        channels_text = ",".join(str(channel) for channel in channels_to_send)
        if channels_text:
            desired_channels = [int(c.strip()) for c in channels_text.split(',') if c.strip()]
            success, received = self.send_command_and_wait_ack(f"channels {channels_text}", None)
            if success:
                if received:
                    try:
                        self.arduino_status['channels'] = [int(c.strip()) for c in received.split(',') if c.strip()]
                    except Exception:
                        self.arduino_status['channels'] = desired_channels
                else:
                    self.arduino_status['channels'] = desired_channels
            else:
                self.log_status(f"555 config command failed: channels {channels_text}")
                all_success = False
            time.sleep(0.05)

        repeat = str(self.repeat_spin.value())
        success, received = self.send_command_and_wait_ack(f"repeat {repeat}", None)
        if success:
            try:
                self.arduino_status['repeat'] = int(received) if received not in (None, '') else int(repeat)
            except Exception:
                self.arduino_status['repeat'] = int(repeat)
        else:
            self.log_status(f"555 config command failed: repeat {repeat}")
            all_success = False
        time.sleep(0.05)

        buffer_size = self.buffer_spin.value()
        if buffer_size <= 0:
            buffer_size = 1
        if buffer_size > 256:
            self.log_status(f"555 mode buffer limited from {buffer_size} to 256")
            buffer_size = 256
            self.buffer_spin.setValue(256)
        buffer_str = str(int(buffer_size))
        success, received = self.send_command_and_wait_ack(f"buffer {buffer_str}", None)
        if success:
            try:
                self.arduino_status['buffer'] = int(received) if received not in (None, '') else int(buffer_str)
            except Exception:
                self.arduino_status['buffer'] = int(buffer_str)
        else:
            self.log_status(f"555 config command failed: buffer {buffer_str}")
            all_success = False
        time.sleep(0.05)

        rb_value = str(int(round(self.rb_spin.value())))
        rk_value = str(int(round(self.rk_spin.value())))
        cf_farads = self._get_cf_farads_from_controls()
        cf_value = f"{cf_farads:.12g}"
        rxmax_value = str(int(round(self.rxmax_spin.value())))

        self.config['rb_ohms'] = float(rb_value)
        self.config['rk_ohms'] = float(rk_value)
        self.config['cf_farads'] = cf_farads
        self.config['rxmax_ohms'] = float(rxmax_value)

        for cmd, value in [
            ('rb', rb_value),
            ('rk', rk_value),
            ('cf', cf_value),
            ('rxmax', rxmax_value),
        ]:
            success, _ = self.send_command_and_wait_ack(f"{cmd} {value}", None)
            if not success:
                self.log_status(f"555 config command failed: {cmd} {value}")
                all_success = False
            time.sleep(0.05)

        return all_success

    def verify_configuration(self) -> bool:
        """Verify that Arduino status matches expected configuration."""
        if getattr(self, 'device_mode', 'adc') == '555':
            expected_channels = self.config.get('channels', [])
            actual_channels = self.arduino_status.get('channels')
            if actual_channels is None:
                # Some 555 firmwares ACK without echoing values; use desired channels if
                # command stage succeeded and no status payload was provided.
                actual_channels = expected_channels
                self.arduino_status['channels'] = actual_channels
            if expected_channels != actual_channels:
                self.log_status(f"MISMATCH: Expected channels {expected_channels}, got {actual_channels}")
                return False
            if self.arduino_status.get('repeat') is not None:
                if self.arduino_status['repeat'] != self.config.get('repeat'):
                    self.log_status(
                        f"MISMATCH: Expected repeat {self.config.get('repeat')}, got {self.arduino_status['repeat']}"
                    )
                    return False
            self.log_status(f"555 configuration matches: {actual_channels}")
            return True

        # Check if we have valid status data
        if self.arduino_status['channels'] is None:
            self.log_status("No status data received yet")
            return False
        
        # Compare channels (most critical)
        # For array mode with duplicate channels (dual MUX), Arduino may echo unique channels only
        expected_channels = self.config.get('channels', [])
        actual_channels = self.arduino_status['channels']
        
        # First try exact match
        if expected_channels == actual_channels:
            pass  # Match successful
        elif self.is_array_sensor_selection_mode():
            # In array sensor selection mode, Arduino might deduplicate the echo
            # Check if unique versions match
            expected_unique = []
            for ch in expected_channels:
                if ch not in expected_unique:
                    expected_unique.append(ch)
            actual_unique = []
            for ch in actual_channels:
                if ch not in actual_unique:
                    actual_unique.append(ch)
            
            if expected_unique != actual_unique:
                self.log_status(f"MISMATCH: Expected channels {expected_channels}, got {actual_channels}")
                return False
        else:
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

        display_specs = self.get_display_channel_specs()

        # Create checkboxes in a compact grid
        for idx, spec in enumerate(display_specs):
            from PyQt6.QtWidgets import QCheckBox
            checkbox = QCheckBox(spec['label'])
            checkbox.setChecked(True)  # Select all by default
            checkbox.stateChanged.connect(self.trigger_plot_update)

            row = idx // MAX_PLOT_COLUMNS
            col = idx % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(checkbox, row, col)

            self.channel_checkboxes[spec['key']] = checkbox
        
        # Add force sensor checkboxes if force data is available
        if self.force_serial_port and self.force_serial_port.is_open:
            from PyQt6.QtWidgets import QCheckBox
            # X Force checkbox
            self.force_x_checkbox = QCheckBox("X Force [N]")
            self.force_x_checkbox.setChecked(True)
            self.force_x_checkbox.setStyleSheet("QCheckBox { color: red; }")
            self.force_x_checkbox.stateChanged.connect(self.trigger_plot_update)
            row = len(display_specs) // MAX_PLOT_COLUMNS
            col = len(display_specs) % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(self.force_x_checkbox, row, col)
            
            # Z Force checkbox
            self.force_z_checkbox = QCheckBox("Z Force [N]")
            self.force_z_checkbox.setChecked(True)
            self.force_z_checkbox.setStyleSheet("QCheckBox { color: blue; }")
            self.force_z_checkbox.stateChanged.connect(self.trigger_plot_update)
            row = (len(display_specs) + 1) // MAX_PLOT_COLUMNS
            col = (len(display_specs) + 1) % MAX_PLOT_COLUMNS
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
        self._reset_full_view_state(trigger_plot_update=True)
