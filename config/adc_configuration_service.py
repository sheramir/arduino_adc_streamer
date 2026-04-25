"""
ADC Configuration Service
=========================
Owns ADC/555 protocol sequencing and verification without mutating GUI widgets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from config.channel_utils import unique_channels_in_order
from config.buffer_utils import validate_and_limit_sweeps_per_block
from constants.serial import INTER_COMMAND_DELAY
from constants.serial import ARRAY_PZT_MAX_MUX_PAIRS_PER_BLOCK
from serial_communication.adc_connection_state import ArduinoStatus, build_default_arduino_status


@dataclass(slots=True)
class ADCConfigurationRequest:
    current_mcu: str | None
    device_mode: str
    channels: list[int]
    channels_to_send: list[int]
    repeat: int
    use_ground: bool
    ground_pin: int
    buffer_size: int
    reference: str
    osr: int
    gain: int
    conv_speed: str
    samp_speed: str
    sample_rate: int
    rb_ohms: float
    rk_ohms: float
    cf_farads: float
    rxmax_ohms: float
    array_operation_mode: str
    is_array_mcu: bool
    is_array_pzt_pzr_mode: bool
    is_array_sensor_selection_mode: bool
    effective_channel_multiplier: int


@dataclass(slots=True)
class ADCCommandResult:
    success: bool
    received_value: str | None = None
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ADCConfigurationResult:
    success: bool
    resolved_device_mode: str
    arduino_status: ArduinoStatus
    normalized_buffer_size: int
    messages: list[str] = field(default_factory=list)


class ADCConfigurationService:
    """Run ADC protocol commands using plain data and a command callback."""

    def __init__(self, send_command_and_wait_ack: Callable[[str, str | None], tuple[bool, str | None]]):
        self._send_command_and_wait_ack = send_command_and_wait_ack

    def apply_555_parameter(self, command_name: str, value: str, *, is_connected: bool, device_mode: str) -> ADCCommandResult:
        if not is_connected:
            return ADCCommandResult(False, messages=["ERROR: Connect a device before applying 555 parameters"])

        if device_mode != "555":
            return ADCCommandResult(False, messages=["Ignoring 555 parameter apply while not in 555 mode"])

        success, received = self._send_command_and_wait_ack(f"{command_name} {value}", None)
        if not success:
            return ADCCommandResult(False, received, [f"ERROR: Failed to apply {command_name}"])

        shown = received if received not in (None, "") else value
        return ADCCommandResult(True, received, [f"Applied {command_name}={shown}"])

    def send_config_with_verification(self, request: ADCConfigurationRequest) -> ADCConfigurationResult:
        messages: list[str] = []
        arduino_status = build_default_arduino_status()

        resolved_device_mode = request.device_mode
        if request.is_array_pzt_pzr_mode:
            selected_mode = (request.array_operation_mode or "PZT").strip().upper()
            resolved_device_mode = "555" if selected_mode == "PZR" else "adc"
            success, received = self._send_command_and_wait_ack(f"mode {selected_mode}", selected_mode)
            if not success:
                messages.append(f"Dual-mode command failed: mode {selected_mode}")
                return ADCConfigurationResult(False, resolved_device_mode, arduino_status, request.buffer_size, messages)

            messages.append(f"Set Array operating mode: {received or selected_mode}")
            time.sleep(INTER_COMMAND_DELAY)

        if resolved_device_mode == "555":
            command_success, normalized_buffer_size = self._send_555_config(request, arduino_status, messages)
        else:
            command_success, normalized_buffer_size, command_messages = self._send_adc_config(request, arduino_status)
            messages.extend(command_messages)

        messages.extend(self._verify_configuration(request, arduino_status, resolved_device_mode))
        verify_success = not any(message.startswith("MISMATCH:") or message == "No status data received yet" for message in messages)
        return ADCConfigurationResult(
            command_success and verify_success,
            resolved_device_mode,
            arduino_status,
            normalized_buffer_size,
            messages,
        )

    def verify_configuration_state(
        self,
        request: ADCConfigurationRequest,
        arduino_status: ArduinoStatus,
        *,
        resolved_device_mode: str | None = None,
    ) -> ADCCommandResult:
        mode = resolved_device_mode or request.device_mode
        messages = self._verify_configuration(request, arduino_status.copy(), mode)
        success = not any(message.startswith("MISMATCH:") or message == "No status data received yet" for message in messages)
        return ADCCommandResult(success, messages=messages)

    def _send_adc_config(self, request: ADCConfigurationRequest, arduino_status: ArduinoStatus) -> tuple[bool, int, list[str]]:
        all_success = True
        messages: list[str] = []
        is_teensy = bool(request.current_mcu and "Teensy" in request.current_mcu)

        if not is_teensy and not request.is_array_mcu:
            success, received = self._send_command_and_wait_ack(f"ref {request.reference}", request.reference)
            if success:
                arduino_status.reference = received
            else:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)
        elif request.is_array_mcu:
            arduino_status.reference = "vdd"

        success, received = self._send_command_and_wait_ack(f"osr {request.osr}", str(request.osr))
        if success and received is not None:
            arduino_status.osr = int(received)
        elif success:
            arduino_status.osr = int(request.osr)
        else:
            all_success = False
        time.sleep(INTER_COMMAND_DELAY)

        if not is_teensy:
            success, received = self._send_command_and_wait_ack(f"gain {request.gain}", str(request.gain))
            if success and received is not None:
                arduino_status.gain = int(received)
            elif success:
                arduino_status.gain = int(request.gain)
            else:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)

        if is_teensy:
            success, _ = self._send_command_and_wait_ack(f"conv {request.conv_speed}", request.conv_speed)
            if not success:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)

            success, _ = self._send_command_and_wait_ack(f"samp {request.samp_speed}", request.samp_speed)
            if not success:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)

            success, _ = self._send_command_and_wait_ack(f"rate {request.sample_rate}", str(request.sample_rate))
            if not success:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)

        channels_text = ",".join(str(channel) for channel in request.channels_to_send)
        if channels_text:
            success, received = self._send_command_and_wait_ack(f"channels {channels_text}", channels_text)
            if success:
                echoed = received or channels_text
                arduino_status.channels = [int(value.strip()) for value in echoed.split(",") if value.strip()]
            else:
                all_success = False
        time.sleep(0.05)

        repeat_text = str(request.repeat)
        success, received = self._send_command_and_wait_ack(f"repeat {repeat_text}", repeat_text)
        if success:
            arduino_status.repeat = int(received) if received not in (None, "") else request.repeat
        else:
            all_success = False
        time.sleep(0.05)

        effective_use_ground = bool(request.use_ground)
        effective_ground_pin = int(request.ground_pin)
        if effective_use_ground and request.is_array_mcu and int(request.effective_channel_multiplier) == 2:
            active_channels = {int(channel) for channel in request.channels_to_send}
            if effective_ground_pin in active_channels:
                effective_use_ground = False
                messages.append(
                    "Ground sampling disabled: ground pin "
                    f"{effective_ground_pin} overlaps active channels in Array dual-mux mode and can stall streaming"
                )

        if effective_use_ground:
            ground_pin_text = str(effective_ground_pin)
            success, received = self._send_command_and_wait_ack(f"ground {ground_pin_text}", ground_pin_text)
            if success:
                arduino_status.ground_pin = int(received) if received not in (None, "") else effective_ground_pin
                arduino_status.use_ground = True
            else:
                all_success = False
        else:
            success, received = self._send_command_and_wait_ack("ground false", "false")
            if success:
                arduino_status.use_ground = False
            else:
                all_success = False
        time.sleep(0.05)

        normalized_buffer_size = self._normalize_adc_buffer_size(request)
        buffer_text = str(normalized_buffer_size)
        success, received = self._send_command_and_wait_ack(f"buffer {buffer_text}", buffer_text)
        if success:
            arduino_status.buffer = int(received) if received not in (None, "") else normalized_buffer_size
        else:
            all_success = False

        return all_success, normalized_buffer_size, messages

    def _send_555_config(self, request: ADCConfigurationRequest, arduino_status: ArduinoStatus, messages: list[str]) -> tuple[bool, int]:
        all_success = True

        channels_text = ",".join(str(channel) for channel in request.channels_to_send)
        if channels_text:
            desired_channels = [int(value.strip()) for value in channels_text.split(",") if value.strip()]
            success, received = self._send_command_and_wait_ack(f"channels {channels_text}", None)
            if success:
                if received:
                    try:
                        arduino_status.channels = [int(value.strip()) for value in received.split(",") if value.strip()]
                    except Exception:
                        arduino_status.channels = desired_channels
                else:
                    arduino_status.channels = desired_channels
            else:
                messages.append(f"555 config command failed: channels {channels_text}")
                all_success = False
            time.sleep(0.05)

        repeat_text = str(request.repeat)
        success, received = self._send_command_and_wait_ack(f"repeat {repeat_text}", None)
        if success:
            try:
                arduino_status.repeat = int(received) if received not in (None, "") else request.repeat
            except Exception:
                arduino_status.repeat = request.repeat
        else:
            messages.append(f"555 config command failed: repeat {repeat_text}")
            all_success = False
        time.sleep(0.05)

        normalized_buffer_size = max(1, min(int(request.buffer_size), 256))
        buffer_text = str(normalized_buffer_size)
        success, received = self._send_command_and_wait_ack(f"buffer {buffer_text}", None)
        if success:
            try:
                arduino_status.buffer = int(received) if received not in (None, "") else normalized_buffer_size
            except Exception:
                arduino_status.buffer = normalized_buffer_size
        else:
            messages.append(f"555 config command failed: buffer {buffer_text}")
            all_success = False
        time.sleep(0.05)

        command_values = [
            ("rb", str(int(round(request.rb_ohms)))),
            ("rk", str(int(round(request.rk_ohms)))),
            ("cf", f"{request.cf_farads:.12g}"),
            ("rxmax", str(int(round(request.rxmax_ohms)))),
        ]
        for command, value in command_values:
            success, _ = self._send_command_and_wait_ack(f"{command} {value}", None)
            if not success:
                messages.append(f"555 config command failed: {command} {value}")
                all_success = False
            time.sleep(0.05)

        return all_success, normalized_buffer_size

    def _verify_configuration(self, request: ADCConfigurationRequest, arduino_status: ArduinoStatus, resolved_device_mode: str) -> list[str]:
        messages: list[str] = []

        if resolved_device_mode == "555":
            expected_channels = list(request.channels)
            actual_channels = arduino_status.channels
            if actual_channels is None:
                actual_channels = expected_channels
                arduino_status.channels = actual_channels

            if expected_channels != actual_channels:
                messages.append(f"MISMATCH: Expected channels {expected_channels}, got {actual_channels}")
                return messages

            actual_repeat = arduino_status.repeat
            if actual_repeat is not None and actual_repeat != request.repeat:
                messages.append(f"MISMATCH: Expected repeat {request.repeat}, got {actual_repeat}")
                return messages

            messages.append(f"555 configuration matches: {actual_channels}")
            return messages

        actual_channels = arduino_status.channels
        if actual_channels is None:
            messages.append("No status data received yet")
            return messages

        expected_channels = list(request.channels)
        if expected_channels != actual_channels:
            if request.is_array_sensor_selection_mode:
                expected_unique = unique_channels_in_order(expected_channels)
                actual_unique = unique_channels_in_order(actual_channels)
                if expected_unique != actual_unique:
                    messages.append(f"MISMATCH: Expected channels {expected_channels}, got {actual_channels}")
                    return messages
            else:
                messages.append(f"MISMATCH: Expected channels {expected_channels}, got {actual_channels}")
                return messages

        actual_repeat = arduino_status.repeat
        if actual_repeat is not None and actual_repeat != request.repeat:
            messages.append(f"MISMATCH: Expected repeat {request.repeat}, got {actual_repeat}")
            return messages

        messages.append(f"Configuration matches: {actual_channels}")
        return messages

    def _normalize_adc_buffer_size(self, request: ADCConfigurationRequest) -> int:
        channel_count = len(request.channels_to_send) * max(1, int(request.effective_channel_multiplier))
        buffer_size = int(request.buffer_size)
        if buffer_size <= 0:
            return 128
        normalized = validate_and_limit_sweeps_per_block(buffer_size, channel_count, request.repeat)
        if request.is_array_mcu and int(request.effective_channel_multiplier) == 2:
            mux_pair_count = len(request.channels_to_send) * max(1, int(request.repeat))
            if mux_pair_count > 0:
                max_sweeps_by_pair_buffer = ARRAY_PZT_MAX_MUX_PAIRS_PER_BLOCK // mux_pair_count
                normalized = min(normalized, max(1, max_sweeps_by_pair_buffer))
        return normalized
