"""
ADC Configuration Service
=========================
Owns ADC/555 protocol sequencing and verification without mutating GUI widgets.
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from typing import Callable

from config.channel_utils import unique_channels_in_order
from config.array_scan import format_array_routes, order_array_routes, selected_arrays
from config.buffer_utils import validate_and_limit_sweeps_per_block
from constants.serial import INTER_COMMAND_DELAY
from constants.serial import DEFAULT_CONFIG_BUFFER_SIZE
from constants.pzt_rs import (
    PZT_RS_CHANNELS_PER_SENSOR,
    PZT_RS_OUTPUTS_PER_SENSOR,
)
from serial_communication.adc_connection_state import ArduinoStatus, build_default_arduino_status


from config.legacy_array_api import legacy_array_default as _testboard_default


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
    pzt_muxes_to_send: list[int]
    rs_channels_to_send: list[int]
    is_array_mcu: bool
    is_array_pzt_pzr_mode: bool
    is_array_sensor_selection_mode: bool
    effective_channel_multiplier: int
    testboard_array_selection: str = "both"
    testboard_scan_order: str = "interleaved"
    testboard_adc_routes: list[tuple[int, int]] = field(default_factory=list)
    is_testboard_7953: bool = False
    testboard_spi_clock_hz: int = field(default_factory=lambda: _testboard_default("spi_clock_hz"))
    testboard_channel_repeat: int = field(default_factory=lambda: _testboard_default("settling_conversions"))
    testboard_sequence: str = field(default_factory=lambda: _testboard_default("sequence"))
    parameters: dict | None = None
    board_context: object | None = None
    sensor_configuration: dict | None = None

    @property
    def is_lane_aware(self):
        from config.boards import get_board_registry
        context = self.board_context or get_board_registry().context(self.current_mcu, self.array_operation_mode)
        return context.mode.definition['adapters']['acquisition'] == 'multi_array'


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


def _build_555_tuning_commands(request: ADCConfigurationRequest) -> list[tuple[str, str]]:
    """Return the 555 analog-tuning commands, in the order the firmware expects."""
    return [
        ("rb", str(int(round(request.rb_ohms)))),
        ("rk", str(int(round(request.rk_ohms)))),
        ("cf", f"{request.cf_farads:.12g}"),
        ("rxmax", str(int(round(request.rxmax_ohms)))),
    ]


class ADCConfigurationService:
    """Run ADC protocol commands using plain data and a command callback."""

    def __init__(self, send_command_and_wait_ack: Callable[[str, str | None], tuple[bool, str | None]], read_testboard_status=None):
        self._send_command_and_wait_ack = send_command_and_wait_ack
        self._read_testboard_status = read_testboard_status

    def apply_555_parameter(
        self,
        command_name: str,
        value: str,
        *,
        is_connected: bool,
        device_mode: str,
        allow_in_pzt_rs_mode: bool = False,
        target_array_mode: str | None = None,
    ) -> ADCCommandResult:
        if not is_connected:
            return ADCCommandResult(False, messages=["ERROR: Connect a device before applying 555 parameters"])

        if device_mode != "555" and not allow_in_pzt_rs_mode:
            return ADCCommandResult(False, messages=["Ignoring 555 parameter apply while not in 555 or PZT_RS mode"])

        messages: list[str] = []
        normalized_target_mode = (target_array_mode or "").strip().upper()
        if allow_in_pzt_rs_mode and normalized_target_mode == "PZT_RS":
            mode_success, mode_received = self._send_command_and_wait_ack("mode PZT_RS", "PZT_RS")
            if not mode_success:
                return ADCCommandResult(False, messages=["ERROR: Failed to switch device to PZT_RS mode"])
            messages.append(f"Set Array operating mode: {mode_received or 'PZT_RS'}")

        success, received = self._send_command_and_wait_ack(f"{command_name} {value}", None)
        if not success:
            messages.append(f"ERROR: Failed to apply {command_name}")
            return ADCCommandResult(False, received, messages)

        shown = received if received not in (None, "") else value
        messages.append(f"Applied {command_name}={shown}")
        return ADCCommandResult(True, received, messages)

    @staticmethod
    def estimate_555_pair_timeout_ms(*, rb_ohms: float, rk_ohms: float, cf_farads: float, rxmax_ohms: float) -> int:
        ra = max(0.0, float(rxmax_ohms) + float(rk_ohms))
        rb = max(1.0, float(rb_ohms))
        c = max(1e-15, float(cf_farads))
        timeout_ms = math.log(2.0) * c * (ra + 2.0 * rb) * 1000.0 * 3.0 + 20.0
        timeout_ms = max(50.0, min(5000.0, timeout_ms))
        return int(math.ceil(timeout_ms))

    def send_config_with_verification(self, request: ADCConfigurationRequest) -> ADCConfigurationResult:
        from config.boards import get_board_registry
        from serial_communication.protocols.registry import protocol_adapter
        context = request.board_context or get_board_registry().context(request.current_mcu, request.array_operation_mode)
        if request.parameters is not None:
            try:
                resolved = context.mode.resolve_settings(request.parameters)
                request.parameters = dict(resolved.requested)
                for key, param in context.mode.parameters.items():
                    field_name = 'buffer_size' if key == 'sweeps_per_block' else param.legacy_key
                    if hasattr(request, field_name):
                        setattr(request, field_name, resolved.requested[key])
            except ValueError as exc:
                return ADCConfigurationResult(False, context.mode.definition['device_mode'],
                    build_default_arduino_status(), request.buffer_size, [f'Invalid board settings: {exc}'])
        result = protocol_adapter(context).configure(self, request)
        if result.success and request.parameters is not None:
            handled = {'reference', 'osr', 'gain', 'samples_per_channel', 'sweeps_per_block', 'ground_pin',
                       'ground_sampling', 'vmid_sampling', 'spi_clock_hz', 'settling_conversions', 'sequence',
                       'array_selection', 'scan_order', 'conversion_speed', 'sampling_speed', 'sample_rate',
                       'rb_ohms', 'rk_ohms', 'cf_farads', 'rxmax_ohms'}
            for key, param in context.mode.parameters.items():
                command = param.definition.get('command')
                if key in handled or not command or param.definition.get('policy') == 'reported':
                    continue
                value = param.wire_value(request.parameters[key])
                encoded = str(value).lower() if isinstance(value, bool) else str(value)
                success, received = self._send_command_and_wait_ack(f'{command} {encoded}', encoded)
                if not success:
                    result.success = False
                    result.messages.append(f'Configuration failed: {command}')
                    break
                result.arduino_status.parameters[key] = received if received is not None else value
        return result

    def _send_legacy_config(self, request: ADCConfigurationRequest) -> ADCConfigurationResult:
        messages: list[str] = []
        arduino_status = build_default_arduino_status()

        resolved_device_mode = request.device_mode
        if request.is_array_pzt_pzr_mode and not request.is_lane_aware:
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
        from config.boards import get_board_registry
        context = request.board_context or get_board_registry().context(request.current_mcu, request.array_operation_mode)
        parameters = context.mode.parameters
        is_teensy = 'conversion_speed' in parameters

        if 'reference' in parameters and parameters['reference'].definition.get('policy') == 'editable':
            parameter = parameters['reference']
            wire_reference = str(parameter.wire_value(request.reference))
            success, received = self._send_command_and_wait_ack(f"ref {wire_reference}", wire_reference)
            if success:
                arduino_status.reference = parameter.normalize(received) if received is not None else None
            else:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)
        elif request.is_array_mcu:
            arduino_status.reference = "vdd"

        if 'osr' in parameters:
            success, received = self._send_command_and_wait_ack(f"osr {request.osr}", str(request.osr))
            if success and received is not None:
                arduino_status.osr = int(received)
            elif success:
                arduino_status.osr = int(request.osr)
            else:
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)

        if 'gain' in parameters:
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
        time.sleep(INTER_COMMAND_DELAY)

        if request.is_array_pzt_pzr_mode and str(request.array_operation_mode).strip().upper() == "PZT_RS":
            pzt_muxes_text = ",".join(str(mux) for mux in request.pzt_muxes_to_send)
            if not pzt_muxes_text:
                messages.append("PZT_RS config command failed: missing PZT MUX routing")
                all_success = False
            else:
                success, received = self._send_command_and_wait_ack(f"pztmuxes {pzt_muxes_text}", pzt_muxes_text)
                if success:
                    messages.append(f"Set PZT_RS PZT MUX routing: {received or pzt_muxes_text}")
                else:
                    messages.append(f"PZT_RS config command failed: pztmuxes {pzt_muxes_text}")
                    all_success = False
            time.sleep(INTER_COMMAND_DELAY)

            rs_channels_text = ",".join(str(channel) for channel in request.rs_channels_to_send)
            if not rs_channels_text:
                messages.append("PZT_RS config command failed: missing RS_MUX channel routing")
                all_success = False
            else:
                success, received = self._send_command_and_wait_ack(f"rschannels {rs_channels_text}", rs_channels_text)
                if success:
                    messages.append(f"Set PZT_RS RS_MUX channels: {received or rs_channels_text}")
                else:
                    messages.append(f"PZT_RS config command failed: rschannels {rs_channels_text}")
                    all_success = False
            time.sleep(INTER_COMMAND_DELAY)

            command_values = _build_555_tuning_commands(request)
            for command, value in command_values:
                success, received = self._send_command_and_wait_ack(f"{command} {value}", None)
                if success:
                    messages.append(f"Set PZT_RS {command}: {received or value}")
                else:
                    messages.append(f"PZT_RS config command failed: {command} {value}")
                    all_success = False
                time.sleep(INTER_COMMAND_DELAY)

        repeat_text = str(request.repeat)
        success, received = self._send_command_and_wait_ack(f"repeat {repeat_text}", repeat_text)
        if success:
            arduino_status.repeat = int(received) if received not in (None, "") else request.repeat
        else:
            all_success = False
        time.sleep(INTER_COMMAND_DELAY)

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

        park_command = "ground"
        if effective_use_ground:
            ground_pin_text = str(effective_ground_pin)
            success, received = self._send_command_and_wait_ack(f"{park_command} {ground_pin_text}", ground_pin_text)
            if success:
                arduino_status.ground_pin = int(received) if received not in (None, "") else effective_ground_pin
                arduino_status.use_ground = True
            else:
                all_success = False
        else:
            success, received = self._send_command_and_wait_ack(f"{park_command} false", "false")
            if success:
                arduino_status.use_ground = False
            else:
                all_success = False
        time.sleep(INTER_COMMAND_DELAY)

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
            time.sleep(INTER_COMMAND_DELAY)

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
        time.sleep(INTER_COMMAND_DELAY)

        normalized_buffer_size = max(1, min(int(request.buffer_size), self._request_mode(request).parameters['sweeps_per_block'].definition['maximum']))
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
        time.sleep(INTER_COMMAND_DELAY)

        command_values = _build_555_tuning_commands(request)
        for command, value in command_values:
            success, _ = self._send_command_and_wait_ack(f"{command} {value}", None)
            if not success:
                messages.append(f"555 config command failed: {command} {value}")
                all_success = False
            time.sleep(INTER_COMMAND_DELAY)

        return all_success, normalized_buffer_size

    def _verify_configuration(self, request: ADCConfigurationRequest, arduino_status: ArduinoStatus, resolved_device_mode: str) -> list[str]:
        messages: list[str] = []
        if request.is_lane_aware:
            from config.boards import get_board_registry
            from config.boards.sensors import default_sensor_layout
            context = request.board_context or get_board_registry().context(request.current_mcu, request.array_operation_mode)
            layout = request.sensor_configuration or default_sensor_layout(context.profile)
            values = context.mode.resolve_settings(dict(reference=request.reference,
                         spi_clock_hz=request.testboard_spi_clock_hz, settling_conversions=request.testboard_channel_repeat,
                         sequence=request.testboard_sequence, vmid_sampling=request.use_ground))
            expected = {
                "reference": values.requested['reference'],
                "testboard_array": request.testboard_array_selection,
                "testboard_scan_order": request.testboard_scan_order,
                "testboard_sequence": values.requested['sequence'],
                "testboard_spi_clock_hz": request.testboard_spi_clock_hz,
                "testboard_channel_repeat": request.testboard_channel_repeat,
                "testboard_effective_repeat": values.effective['settling_conversions'],
                "testboard_vmid": request.use_ground,
                "testboard_effective_vmid": request.use_ground,
                "ground_pin": context.profile.hardware['reserved_inputs']['vmid'],
                "testboard_route_count": len(request.testboard_adc_routes),
            }
            for key, value in expected.items():
                actual = getattr(arduino_status, key)
                if actual != value:
                    messages.append(f"MISMATCH: Expected {key}={value}, got {actual}")
            actual_routes = arduino_status.testboard_routes
            if actual_routes is None or order_array_routes(actual_routes, request.testboard_scan_order, layout) != order_array_routes(request.testboard_adc_routes, request.testboard_scan_order, layout):
                messages.append("MISMATCH: TestBoard ADC route membership/order")
            if arduino_status.testboard_engine not in ("blocking", "dma", "lpspi"):
                messages.append("MISMATCH: Missing or invalid TestBoard SPI engine status")
            return messages or ["TestBoard configuration matches reported status"]

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
        if (
            not request.is_lane_aware
            and actual_repeat is not None
            and actual_repeat != request.repeat
        ):
            messages.append(f"MISMATCH: Expected repeat {request.repeat}, got {actual_repeat}")
            return messages

        messages.append(f"Configuration matches: {actual_channels}")
        return messages

    @staticmethod
    def _request_mode(request):
        from config.boards import get_board_registry
        context = request.board_context or get_board_registry().context(request.current_mcu, request.array_operation_mode)
        return context.mode

    def _normalize_adc_buffer_size(self, request: ADCConfigurationRequest) -> int:
        if request.is_lane_aware:
            return 1
        if (
            request.is_array_pzt_pzr_mode
            and str(request.array_operation_mode).strip().upper() == "PZT_RS"
            and request.is_array_sensor_selection_mode
        ):
            pzt_sensor_count = max(1, len(request.channels) // PZT_RS_CHANNELS_PER_SENSOR)
            channel_count = pzt_sensor_count * PZT_RS_OUTPUTS_PER_SENSOR
        else:
            channel_count = (
                len(request.testboard_adc_routes)
                if request.is_lane_aware
                else len(request.channels_to_send) * max(1, int(request.effective_channel_multiplier))
            )
        limits = self._request_mode(request).definition.get('buffer_limits', {})
        buffer_size = int(request.buffer_size)
        if buffer_size <= 0:
            return DEFAULT_CONFIG_BUFFER_SIZE
        normalized = validate_and_limit_sweeps_per_block(buffer_size, channel_count, request.repeat)
        if request.is_array_mcu and int(request.effective_channel_multiplier) == 2:
            mux_pair_count = len(request.channels_to_send) * max(1, int(request.repeat))
            if mux_pair_count > 0:
                max_sweeps_by_pair_buffer = limits['mux_pairs'] // mux_pair_count
                normalized = min(normalized, max(1, max_sweeps_by_pair_buffer))
        if request.is_array_pzt_pzr_mode and str(request.array_operation_mode).strip().upper() == "PZT_RS":
            normalized = min(normalized, limits['max_sweeps'])
        return normalized

    def _send_testboard_config(self, request):
        from config.boards import get_board_registry
        from config.boards.sensors import default_sensor_layout
        from config.array_acquisition import normalize_settings
        context = request.board_context or get_board_registry().context(request.current_mcu, request.array_operation_mode)
        layout = request.sensor_configuration or default_sensor_layout(context.profile)
        reference, clock, repeat, sequence, vmid = normalize_settings(
            request.reference, request.testboard_spi_clock_hz, request.testboard_channel_repeat,
            request.testboard_sequence, request.use_ground, context)
        context.mode.parameters['scan_order'].normalize(request.testboard_scan_order)
        allowed = {lane for array in selected_arrays(request.testboard_array_selection, layout)
                   for lane in layout['arrays'][str(array)]['adc_lanes']}
        routes = request.testboard_adc_routes
        hardware = context.profile.hardware
        if not routes or len(set(routes)) != len(routes) or any(lane not in allowed or not 0 <= ch < hardware['inputs_per_adc'] or ch in hardware['reserved_inputs'].values() for lane, ch in routes):
            raise ValueError("Invalid or empty TestBoard ADC routes")
        reference_wire = context.mode.parameters['reference'].wire_value(reference)
        commands = [("mode", context.mode.id), ("ref", reference_wire), ("spiclock", str(clock)),
                    ("array", request.testboard_array_selection), ("scanorder", request.testboard_scan_order),
                    ("adcchannels", format_array_routes(routes)), ("channelrepeat", str(repeat)),
                    ("vmid", str(vmid).lower()), ("adcseq", sequence)]
        messages = []
        for name, value in commands:
            success, _ = self._send_command_and_wait_ack(f"{name} {value}", None)
            if not success:
                return ADCConfigurationResult(False, "adc", build_default_arduino_status(), 1,
                                              [f"TestBoard config command failed: {name} {value}"])
            messages.append(f"Set TestBoard {name}: {value}")
        status = self._read_testboard_status() if self._read_testboard_status is not None else None
        if status is None:
            return ADCConfigurationResult(False, "adc", build_default_arduino_status(), 1,
                                          messages + ["No status data received yet"])
        messages.extend(self._verify_configuration(request, status, "adc"))
        success = not any(m.startswith("MISMATCH:") for m in messages)
        if success:
            status.repeat = status.buffer = 1
            status.channels = unique_channels_in_order(request.channels_to_send)
            status.use_ground = vmid
        return ADCConfigurationResult(success, "adc", status, 1, messages)
