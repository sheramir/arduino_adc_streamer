"""
Configuration Management Mixin
===============================
Handles all configuration event handlers and Arduino configuration workflow.
"""

from PyQt6.QtCore import Qt

from config.adc_configuration_service import ADCConfigurationRequest
from config.channel_utils import unique_channels_in_order
from config.config_view_state import (
    build_configuration_failed_state,
    build_configuration_success_state,
    build_configuring_state,
    build_start_needs_config_state,
    build_start_ready_state,
    build_start_unavailable_state,
)
from config.config_snapshot import build_adc_configuration_snapshot
from config.mcu_profile import resolve_mcu_profile
from constants.serial import MAX_SAMPLES_BUFFER
from constants.defaults_555 import (
    ANALYZER555_DEFAULT_CF_UNIT,
    ANALYZER555_DEFAULT_CF_VALUE,
)
from constants.ui import MAX_PLOT_COLUMNS
from config.buffer_utils import validate_and_limit_sweeps_per_block


class ConfigurationMixin:
    """Mixin class for configuration management and event handlers."""

    def get_vref_voltage(self) -> float:
        """Get the numeric voltage reference value for the current configuration."""
        vref_str = self.config['reference']

        if vref_str == "1.2":
            return 1.2
        if vref_str == "3.3" or vref_str == "vdd":
            return 3.3
        if vref_str == "0.8vdd":
            return 3.3 * 0.8
        if vref_str == "ext":
            return 1.25
        return 3.3

    def _apply_configure_button_state(self, state):
        self.configure_btn.setEnabled(state.enabled)
        if state.style is not None:
            self.configure_btn.setStyleSheet(state.style)
        if state.status_message:
            self.statusBar().showMessage(state.status_message, state.status_timeout_ms)

    def _apply_start_button_state(self, state):
        self.start_btn.setEnabled(state.enabled)
        if state.style is not None:
            self.start_btn.setStyleSheet(state.style)
        self.start_btn.setText(state.text)

    def is_array_mcu_mode(self) -> bool:
        """Return True for any Array* MCU identifier."""
        return resolve_mcu_profile(self.current_mcu).is_array_mcu

    def is_array_pzt1_mode(self) -> bool:
        """Return True when the connected MCU streams paired MUX data."""
        return resolve_mcu_profile(
            self.current_mcu,
            selected_array_mode=self.get_selected_array_operation_mode(),
        ).is_array_pzt1

    def get_allowed_channel_max(self) -> int:
        """Return max channel index for manual channel entry validation."""
        return 15 if self.is_array_mcu_mode() else 9

    def is_array_pzt_pzr_mode(self) -> bool:
        """Return True when MCU supports runtime PZT/PZR mode switching."""
        return resolve_mcu_profile(self.current_mcu).is_array_dual

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

        unique_channels = unique_channels_in_order(channels)

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
            return unique_channels_in_order(channels)

        return channels

    def get_effective_samples_per_sweep(self, channels=None, repeat_count=None) -> int:
        """Return the physical sample width of one sweep for the active MCU."""
        if channels is None:
            channels = self.config.get('channels', [])
        if repeat_count is None:
            repeat_count = self.config.get('repeat', 1)
        physical_channels = list(channels or [])
        if self.is_array_pzt1_mode() and self.is_array_sensor_selection_mode():
            physical_channels = self.get_channels_for_arduino_command()
        return len(physical_channels) * max(1, int(repeat_count)) * self.get_effective_channel_multiplier()

    @staticmethod
    def _get_unique_channels_in_order(channels):
        return unique_channels_in_order(channels)

    def _get_grouped_manual_channel_labels(self, channels):
        """Return manual channel labels with sensor placement names when layout is unambiguous."""
        unique_channels = self._get_unique_channels_in_order(channels)
        if len(unique_channels) != len(channels):
            return {}

        channel_sensor_map = self.get_active_channel_sensor_map() if hasattr(self, 'get_active_channel_sensor_map') else ["T", "R", "C", "L", "B"]
        channel_sensor_map = [str(label) for label in channel_sensor_map if str(label)]
        required_channels = len(channel_sensor_map)
        if required_channels <= 0:
            return {}

        use_leading_ground = (
            unique_channels
            and unique_channels[0] == 0
            and len(unique_channels) > required_channels
            and (len(unique_channels) - 1) % required_channels == 0
        )

        start_index = 1 if use_leading_ground else 0
        grouped_channels = unique_channels[start_index:]
        if not grouped_channels or len(grouped_channels) % required_channels != 0:
            return {}

        labels = {}
        if use_leading_ground:
            labels[0] = "Ch0"

        for display_index, channel in enumerate(grouped_channels):
            placement = channel_sensor_map[display_index % required_channels]
            labels[channel] = f"Ch{channel}-{placement}"

        return labels

    def get_display_channel_specs(self, channels=None, repeat_count=None):
        """Build display-channel metadata for plotting and channel selectors."""
        if channels is None:
            channels = self.config.get('channels', [])
        if repeat_count is None:
            repeat_count = self.config.get('repeat', 1)
        repeat_count = max(1, int(repeat_count))

        unique_channels = self._get_unique_channels_in_order(channels)

        specs = []
        selection_source = str(self.config.get('channel_selection_source', 'manual')).lower()
        selected_array_sensors = self.config.get('selected_array_sensors', [])

        if self.is_array_mcu_mode() and selection_source == 'array' and selected_array_sensors:
            sensor_groups = self.get_array_selected_sensor_groups()
            channel_sensor_map = self.get_active_channel_sensor_map() if hasattr(self, 'get_active_channel_sensor_map') else ["T", "R", "C", "L", "B"]
            unique_channel_positions = {channel: index for index, channel in enumerate(unique_channels)}

            color_slot = 0
            for group in sensor_groups:
                sensor_id = group['sensor_id']
                mux_num = int(group.get('mux', 1))
                sensor_channels = list(group.get('channels', []))
                seq_positions = list(group.get('positions', []))

                for local_idx, channel in enumerate(sensor_channels):
                    sample_indices = []
                    if local_idx < len(seq_positions):
                        if self.is_array_pzt1_mode():
                            unique_idx = unique_channel_positions.get(channel)
                            if unique_idx is not None:
                                mux_index = max(0, min(1, mux_num - 1))
                                base_idx = unique_idx * repeat_count * 2
                                for repeat_idx in range(repeat_count):
                                    sample_indices.append(base_idx + (repeat_idx * 2) + mux_index)
                        else:
                            seq_idx = int(seq_positions[local_idx])
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

        grouped_manual_labels = self._get_grouped_manual_channel_labels(channels)

        for display_order, channel in enumerate(unique_channels):
            sample_indices = []
            for seq_idx, seq_channel in enumerate(channels):
                if seq_channel != channel:
                    continue
                base_idx = seq_idx * repeat_count
                sample_indices.extend(range(base_idx, base_idx + repeat_count))

            specs.append({
                'key': ('adc', channel),
                'label': grouped_manual_labels.get(channel, f"Ch {channel}"),
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

    def _build_adc_configuration_request(self) -> ADCConfigurationRequest:
        """Build a plain-data snapshot for the ADC configuration service."""
        snapshot = build_adc_configuration_snapshot(
            current_reference=str(self.config.get('reference', 'vdd')),
            vref_label=self.vref_combo.currentText() if hasattr(self, 'vref_combo') else None,
            use_vref_control=bool(hasattr(self, 'vref_combo') and not self.is_array_mcu_mode() and not (self.current_mcu and "Teensy" in self.current_mcu)),
            current_osr=int(self.config.get('osr', 2)),
            osr_label=self.osr_combo.currentText().strip() if hasattr(self, 'osr_combo') and self.osr_combo.currentText().strip() else None,
            current_gain=int(self.config.get('gain', 1)),
            gain_label=self.gain_combo.currentText() if hasattr(self, 'gain_combo') else None,
            current_repeat=int(self.config.get('repeat', 1)),
            repeat_value=int(self.repeat_spin.value()) if hasattr(self, 'repeat_spin') else None,
            current_use_ground=bool(self.config.get('use_ground', False)),
            use_ground_checked=bool(self.use_ground_check.isChecked()) if hasattr(self, 'use_ground_check') else None,
            current_ground_pin=int(self.config.get('ground_pin', -1)),
            ground_pin_value=int(self.ground_pin_spin.value()) if hasattr(self, 'ground_pin_spin') else None,
            current_conv_speed=str(self.config.get('conv_speed', 'med')),
            conv_speed_label=self.conv_speed_combo.currentText() if hasattr(self, 'conv_speed_combo') else None,
            current_samp_speed=str(self.config.get('samp_speed', 'med')),
            samp_speed_label=self.samp_speed_combo.currentText() if hasattr(self, 'samp_speed_combo') else None,
            current_sample_rate=int(self.config.get('sample_rate', 0)),
            sample_rate_value=int(self.sample_rate_spin.value()) if hasattr(self, 'sample_rate_spin') else None,
            current_array_operation_mode=str(self.config.get('array_operation_mode', 'PZT')),
            array_operation_mode=self.get_selected_array_operation_mode() if self.is_array_pzt_pzr_mode() else None,
            current_rb_ohms=float(self.config.get('rb_ohms', 0.0)),
            rb_value=float(self.rb_spin.value()) if hasattr(self, 'rb_spin') else None,
            current_rk_ohms=float(self.config.get('rk_ohms', 0.0)),
            rk_value=float(self.rk_spin.value()) if hasattr(self, 'rk_spin') else None,
            cf_farads=self._get_cf_farads_from_controls(),
            current_rxmax_ohms=float(self.config.get('rxmax_ohms', 0.0)),
            rxmax_value=float(self.rxmax_spin.value()) if hasattr(self, 'rxmax_spin') else None,
        )

        snapshot.apply_to_config(self.config)
        buffer_size = int(self.buffer_spin.value()) if hasattr(self, 'buffer_spin') else 128

        return ADCConfigurationRequest(
            current_mcu=self.current_mcu,
            device_mode=str(getattr(self, 'device_mode', 'adc')),
            channels=list(self.config.get('channels', [])),
            channels_to_send=self.get_channels_for_arduino_command(),
            repeat=snapshot.repeat,
            use_ground=snapshot.use_ground,
            ground_pin=snapshot.ground_pin,
            buffer_size=buffer_size,
            reference=snapshot.reference,
            osr=snapshot.osr,
            gain=snapshot.gain,
            conv_speed=snapshot.conv_speed,
            samp_speed=snapshot.samp_speed,
            sample_rate=snapshot.sample_rate,
            rb_ohms=snapshot.rb_ohms,
            rk_ohms=snapshot.rk_ohms,
            cf_farads=snapshot.cf_farads,
            rxmax_ohms=snapshot.rxmax_ohms,
            array_operation_mode=snapshot.array_operation_mode,
            is_array_mcu=self.is_array_mcu_mode(),
            is_array_pzt_pzr_mode=self.is_array_pzt_pzr_mode(),
            is_array_sensor_selection_mode=self.is_array_sensor_selection_mode(),
            effective_channel_multiplier=self.get_effective_channel_multiplier(),
        )

    def _apply_configuration_result(self, result):
        """Apply service output back onto GUI-owned state."""
        self.device_mode = result.resolved_device_mode
        self.arduino_status.apply(result.arduino_status)

        normalized_buffer_size = int(result.normalized_buffer_size)
        current_buffer_size = int(self.buffer_spin.value()) if hasattr(self, 'buffer_spin') else normalized_buffer_size
        if normalized_buffer_size != current_buffer_size:
            if getattr(self, 'device_mode', 'adc') == '555' and current_buffer_size > 256:
                self.log_status(f"555 mode buffer limited from {current_buffer_size} to {normalized_buffer_size}")
            elif normalized_buffer_size == 128 and current_buffer_size <= 0:
                self.log_status(f"Invalid buffer size, using default value: {normalized_buffer_size}")
            else:
                self.log_status(f"Buffer size limited to {normalized_buffer_size} sweeps (Arduino buffer capacity)")
            self.buffer_spin.setValue(normalized_buffer_size)

        for message in result.messages:
            self.log_status(message)

    def _apply_555_parameter(self, command_name: str, value: str):
        result = self.adc_configuration_service.apply_555_parameter(
            command_name,
            value,
            is_connected=bool(self.serial_port and self.serial_port.is_open),
            device_mode=str(getattr(self, 'device_mode', 'adc')),
        )
        for message in result.messages:
            self.log_status(message)
        if result.success:
            self.config_is_valid = False
            self.update_start_button_state()

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
        self._apply_configure_button_state(build_configuring_state())
        
        # Clear timing data from previous runs
        self.timing_state.arduino_sample_times.clear()
        self.timing_state.buffer_gap_times.clear()

        self.config_check_timer.start()

        request = self._build_adc_configuration_request()
        started = self.adc_configuration_runner.start(self.serial_port, request, max_attempts=3)
        if not started:
            self.config_check_timer.stop()
            self.log_status("Configuration already in progress")
            self._apply_configure_button_state(build_configuration_failed_state())
    
    def check_config_completion(self):
        """Check if configuration has completed (called by timer)."""
        outcome = self.adc_configuration_runner.take_outcome()
        if outcome is None:
            return

        self.config_check_timer.stop()
        if outcome.error_message:
            self.log_status(outcome.error_message)
        if outcome.result is not None:
            self._apply_configuration_result(outcome.result)

        if outcome.success:
            self.on_configuration_success()
        else:
            self.on_configuration_failed()
    
    def on_configuration_success(self):
        """Handle successful configuration."""
        self.config_is_valid = True
        self.log_status("✓ Configuration verified - Ready to start")
        self.log_status("Configuration complete - all parameters confirmed")
        self.update_start_button_state()
        self._apply_configure_button_state(build_configuration_success_state())
    
    def on_configuration_failed(self):
        """Handle failed configuration."""
        self.log_status("ERROR: Configuration failed after retries")
        self._apply_configure_button_state(build_configuration_failed_state())
    
    def verify_configuration(self) -> bool:
        """Verify that Arduino status matches expected configuration."""
        request = self._build_adc_configuration_request()
        result = self.adc_configuration_service.verify_configuration_state(
            request,
            self.arduino_status,
            resolved_device_mode=str(getattr(self, 'device_mode', 'adc')),
        )
        for message in result.messages:
            self.log_status(message)
        return result.success
    
    def update_start_button_state(self):
        """Update Start button state based on configuration validity."""
        if self.serial_port and self.serial_port.is_open and not self.is_capturing:
            if self.config_is_valid:
                self._apply_start_button_state(build_start_ready_state())
            else:
                self._apply_start_button_state(build_start_needs_config_state())
        else:
            self._apply_start_button_state(build_start_unavailable_state())

    # ========================================================================
    # Channel Management
    # ========================================================================

    def _reset_force_channel_checkbox_refs(self):
        """Clear force-overlay checkbox references after the layout is rebuilt."""
        self.force_x_checkbox = None
        self.force_z_checkbox = None

    def _should_show_force_channel_checkboxes(self) -> bool:
        """Return True when the force overlay checkboxes should be present."""
        force_port = getattr(self, 'force_serial_port', None)
        return bool(force_port and force_port.is_open)

    def _add_force_channel_checkboxes(self, start_index: int):
        """Append force overlay checkboxes after the ADC channel checkboxes."""
        if not self._should_show_force_channel_checkboxes():
            return

        from PyQt6.QtWidgets import QCheckBox

        checkbox_specs = [
            ("force_x_checkbox", "X Force [N]", "red"),
            ("force_z_checkbox", "Z Force [N]", "blue"),
        ]

        for offset, (attribute_name, label, color) in enumerate(checkbox_specs):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.setStyleSheet(f"QCheckBox {{ color: {color}; }}")
            checkbox.stateChanged.connect(self.trigger_plot_update)

            position = start_index + offset
            row = position // MAX_PLOT_COLUMNS
            col = position % MAX_PLOT_COLUMNS
            self.channel_checkboxes_layout.addWidget(checkbox, row, col)
            setattr(self, attribute_name, checkbox)

    def _set_force_channel_checkboxes_checked(self, checked: bool):
        """Set both force-overlay channel toggles when they exist."""
        if self.force_x_checkbox:
            self.force_x_checkbox.setChecked(checked)
        if self.force_z_checkbox:
            self.force_z_checkbox.setChecked(checked)

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
        self._reset_force_channel_checkbox_refs()

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

        self._add_force_channel_checkboxes(start_index=len(display_specs))

    def select_all_channels(self):
        """Select all channel checkboxes."""
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(True)
        self._set_force_channel_checkboxes_checked(True)

    def deselect_all_channels(self):
        """Deselect all channel checkboxes."""
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(False)
        self._set_force_channel_checkboxes_checked(False)

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
