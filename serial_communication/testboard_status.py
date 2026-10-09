"""Decode the active firmware's key=value status (including ADC:input routes)."""


def apply_testboard_status_line(status, line, context=None):
    if not line.startswith("#") or "=" not in line:
        return False
    key, value = line[1:].strip().split("=", 1)
    key, value = key.strip(), value.strip()
    names = {"array": "testboard_array", "scanorder": "testboard_scan_order",
             "adcseq": "testboard_sequence", "spiengine": "testboard_engine"}
    integers = {"spi_clock_hz": "testboard_spi_clock_hz", "channelrepeat_requested": "testboard_channel_repeat",
                "channelrepeat_effective": "testboard_effective_repeat", "route_count": "testboard_route_count",
                "vmid_channel": "ground_pin"}
    booleans = {"vmid_between_channels_requested": "testboard_vmid",
                "vmid_between_channels_effective": "testboard_effective_vmid"}
    try:
        if key in ('sampling_sweeps', 'usb_frames_sent', 'usb_frames_discarded',
                   'sampling_period_max_us', 'sampling_period_over_1ms'):
            status.stream_diagnostics[key] = int(value)
        elif key == "adcchannels":
            from config.boards import get_board_registry
            context = context or get_board_registry().context('TestBoard_7953')
            hardware = context.profile.hardware
            routes = [tuple(int(v) for v in token.split(":")) for token in value.split(",") if token]
            if len(set(routes)) != len(routes) or any(len(r) != 2 or not 1 <= r[0] <= hardware['adc_lane_count'] or not 0 <= r[1] < hardware['inputs_per_adc'] or r[1] in hardware['reserved_inputs'].values() for r in routes):
                return False
            status.testboard_routes = routes
        elif key == "vref":
            from config.boards import get_board_registry
            context = context or get_board_registry().context('TestBoard_7953')
            status.reference = context.mode.parameters['reference'].normalize(value)
        elif key in names:
            setattr(status, names[key], value)
        elif key in integers:
            setattr(status, integers[key], int(value))
        elif key in booleans:
            if value not in ("true", "false"):
                return False
            setattr(status, booleans[key], value == "true")
        else:
            return False
    except ValueError:
        return False
    return True
