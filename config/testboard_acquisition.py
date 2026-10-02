"""Self-contained acquisition identity derived from board and sensor definitions."""
from __future__ import annotations
from copy import deepcopy
from config.boards import get_board_registry
from config.boards.models import thaw
from config.boards.validation import validate_sensor_layout
from config.testboard_scan import build_testboard_routes, order_testboard_routes, selected_testboard_arrays


def normalize_settings(reference, spi_clock_hz, channel_repeat, sequence, vmid, context=None):
    context = context or get_board_registry().context('TestBoard_7953')
    settings = context.mode.resolve_settings(dict(reference=str(reference).removesuffix('V').strip(),
                           spi_clock_hz=spi_clock_hz, settling_conversions=channel_repeat,
                           sequence=sequence, vmid_sampling=vmid))
    values = settings.requested
    return tuple(values[k] for k in ('reference', 'spi_clock_hz', 'settling_conversions', 'sequence', 'vmid_sampling'))


def validate_board_layout(layout, context=None):
    context = context or get_board_registry().context('TestBoard_7953')
    declared = layout.get('board_profile')
    if not declared or get_board_registry().resolve(declared).id != context.profile.id:
        raise ValueError('Select a sensor configuration compatible with this board')
    validate_sensor_layout(layout, context.profile)


def _identity(layout, selected, arrays, scan_order):
    groups = [dict(sensor_id=s, mux=layout['mux_mapping'][s]['mux'], channels=list(layout['mux_mapping'][s]['channels'])) for s in selected]
    selection = 'both' if len(arrays) == 2 else str(arrays[0])
    routes = order_testboard_routes(build_testboard_routes(groups, array_selection=selection, layout=layout), scan_order)
    specs = []
    placements = layout['channel_sensor_map']
    for index, (lane, channel) in enumerate(routes):
        array = next(int(a) for a, entry in layout['arrays'].items() if lane in entry['adc_lanes'])
        mux = layout['arrays'][str(array)]['adc_lanes'].index(lane) + 1
        for sensor in selected:
            mapping = layout['mux_mapping'][sensor]
            if mapping['mux'] == mux and channel in mapping['channels']:
                offset = mapping['channels'].index(channel)
                placement = placements[offset]
                specs.append(dict(key=('sensor', f'A{array}_{sensor}', placement, channel, lane),
                       label=f'A{array}_{sensor}_{placement}', sample_indices=[index],
                       color_slot=selected.index(sensor) * len(placements) + offset,
                       array_number=array, adc_lane=lane, sensor_id=sensor, placement=placement))
                break
    if len(specs) != len(routes):
        raise ValueError('Routes cannot be associated with selected sensor channels')
    return routes, specs


def build_descriptor(mcu, config, layout, reported=None, context=None):
    context = context or get_board_registry().context(mcu, 'PZT')
    validate_board_layout(layout, context)
    selected = list(config.get('selected_array_sensors', []))
    if not selected or len(set(selected)) != len(selected) or any(s not in layout['mux_mapping'] for s in selected):
        raise ValueError('Select populated PZT sensors without duplicates')
    settings = context.mode.resolve_settings(config)
    requested, effective = settings.requested, settings.effective
    arrays = selected_testboard_arrays(requested['array_selection'])
    routes, specs = _identity(layout, selected, arrays, requested['scan_order'])
    from dataclasses import asdict, is_dataclass
    status = asdict(reported) if is_dataclass(reported) else vars(reported) if reported and hasattr(reported, '__dict__') else {}
    snapshot = context.capture_snapshot(config, status, layout)
    snapshot['routes'] = [list(r) for r in routes]
    return dict(version=2, board_context=snapshot, mcu=mcu, sensor_configuration=deepcopy(layout),
                array_count=len(layout['arrays']), sampled_arrays=list(arrays), selected_pzts=selected,
                ordered_routes=[list(r) for r in routes], channel_specs=specs, reference=requested['reference'],
                full_scale_volts=context.mode.full_scale_volts(requested['reference']),
                adc_resolution_bits=context.profile.hardware['adc_resolution_bits'], spi_clock_hz=requested['spi_clock_hz'],
                sequence=requested['sequence'], channelrepeat_requested=requested['settling_conversions'],
                channelrepeat_effective=effective['settling_conversions'], vmid_sampling=requested['vmid_sampling'],
                vmid_channel=context.profile.hardware['reserved_inputs']['vmid'], scan_order=requested['scan_order'],
                spi_engine=getattr(reported, 'testboard_engine', None))


def descriptor_specs(descriptor, array_id=None):
    specs = deepcopy(descriptor['channel_specs'])
    for spec in specs:
        spec['key'] = tuple(spec['key'])
    return [s for s in specs if array_id is None or s['array_number'] == array_id]


def validate_descriptor(descriptor, sample_count=None, labels=None):
    """Validate captured mapping against itself, independent of installed JSON.

    Version 1 is the pre-registry format, whose ADC span is the reference token.
    Version 2 carries its interpretation contract. Neither reader rewrites files.
    """
    try:
        if descriptor['version'] not in (1, 2):
            raise ValueError('Unsupported acquisition descriptor version')
        if descriptor['scan_order'] not in ('adc', 'array', 'interleaved'):
            raise ValueError('Missing or invalid captured scan order')
        layout, arrays, selected = descriptor['sensor_configuration'], descriptor['sampled_arrays'], descriptor['selected_pzts']
        if arrays not in ([1], [2], [1, 2]) or not selected or len(set(selected)) != len(selected):
            raise ValueError('Invalid captured array/sensor selection')
        routes, specs = _identity(layout, selected, arrays, descriptor['scan_order'])
        if descriptor_specs(descriptor) != specs or descriptor['ordered_routes'] != [list(r) for r in routes]:
            raise ValueError('Saved channel identity does not match captured sensor mapping')
        if descriptor['array_count'] != len(layout['arrays']):
            raise ValueError('Invalid captured array count')
        if not isinstance(descriptor['adc_resolution_bits'], int) or not 1 <= descriptor['adc_resolution_bits'] <= 32:
            raise ValueError('Invalid ADC bit depth')
        if descriptor['version'] == 2:
            from config.boards.capture import validate_capture_context
            validate_capture_context(descriptor['board_context'])
            if descriptor['adc_resolution_bits'] != descriptor['board_context']['hardware']['adc_resolution_bits']:
                raise ValueError('Inconsistent ADC interpretation')
            captured = descriptor['board_context']
            for field, parameter in (('reference', 'reference'), ('sequence', 'sequence'),
                                     ('channelrepeat_requested', 'settling_conversions'),
                                     ('spi_clock_hz', 'spi_clock_hz'), ('vmid_sampling', 'vmid_sampling'),
                                     ('scan_order', 'scan_order')):
                if descriptor[field] != captured['requested'][parameter]:
                    raise ValueError(f'Inconsistent captured {field}')
            if descriptor['channelrepeat_effective'] != captured['effective']['settling_conversions']:
                raise ValueError('Inconsistent effective settling conversions')
            if descriptor['vmid_channel'] != captured['hardware']['reserved_inputs']['vmid']:
                raise ValueError('Inconsistent captured reserved resource')
            if descriptor['ordered_routes'] != captured['routes'] or layout != captured['sensor_configuration']:
                raise ValueError('Inconsistent captured routing snapshot')
        if sample_count is not None and sample_count != len(routes):
            raise ValueError('Data width does not match captured routes')
        if labels is not None and list(labels) != [s['label'] for s in specs]:
            raise ValueError('CSV labels do not match captured routes')
    except (KeyError, TypeError, IndexError, StopIteration) as exc:
        raise ValueError('Incomplete acquisition identity') from exc
    return descriptor


def descriptor_groups(descriptor, array_id=None):
    result, layout = [], descriptor['sensor_configuration']
    for array in descriptor['sampled_arrays']:
        if array_id is not None and array != array_id:
            continue
        for sensor in descriptor['selected_pzts']:
            mapping = layout['mux_mapping'][sensor]
            lane = layout['arrays'][str(array)]['adc_lanes'][mapping['mux'] - 1]
            channels = list(mapping['channels'])
            indices = [descriptor['ordered_routes'].index([lane, ch]) for ch in channels]
            result.append(dict(sensor_id=sensor, package_id=f'A{array}_{sensor}', array_number=array,
                               mux=mapping['mux'], adc_lane=lane, channels=channels, positions=indices, sample_indices=indices))
    return result
