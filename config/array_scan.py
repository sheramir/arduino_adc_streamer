"""Lane-aware routing for mirrored sensor arrays, independent of board identity.

The sensor layout owns physical lane membership; the selected profile validates
electrical capacity. These orders are shared algorithms used by compatible
firmware protocols, not assumptions about a particular PCB.
"""
from collections.abc import Iterable


def selected_arrays(selection, layout):
    available = tuple(sorted(int(a) for a in layout['arrays']))
    if not available:
        raise ValueError('No sensor arrays are defined')
    if selection == 'both':  # Established wire token: all available arrays.
        return available
    try:
        selected = int(selection)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid array selection: {selection!r}') from exc
    if selected not in available:
        raise ValueError(f'Array {selected} is not defined by this sensor layout')
    return (selected,)


def physical_lanes_for_mapping(mapping_lane, selection, layout):
    position = int(mapping_lane) - 1
    arrays = selected_arrays(selection, layout)
    if position < 0 or any(position >= len(layout['arrays'][str(a)]['adc_lanes']) for a in arrays):
        raise ValueError(f'Invalid array-local ADC position: {mapping_lane}')
    return tuple(layout['arrays'][str(a)]['adc_lanes'][position] for a in arrays)


def unique_routes(routes):
    result, seen = [], set()
    for lane, channel in routes:
        route = (int(lane), int(channel))
        if route[0] < 1 or route[1] < 0:
            raise ValueError(f'Invalid ADC route: {route}')
        if route not in seen:
            seen.add(route)
            result.append(route)
    return result


def build_array_routes(sensor_groups, *, array_selection, layout):
    return unique_routes((lane, channel) for group in sensor_groups
                         for lane in physical_lanes_for_mapping(group['mux'], array_selection, layout)
                         for channel in group['channels'])


def _round_robin(routes_by_lane, lanes: Iterable[int]):
    depth, result = 0, []
    while True:
        row = [routes_by_lane[lane][depth] for lane in lanes if depth < len(routes_by_lane.get(lane, ()))]
        if not row:
            return result
        result.extend(row)
        depth += 1


def order_array_routes(routes, scan_order, layout):
    unique = unique_routes(routes)
    lanes = sorted(lane for array in layout['arrays'].values() for lane in array['adc_lanes'])
    by_lane = {lane: [r for r in unique if r[0] == lane] for lane in lanes}
    if any(lane not in by_lane for lane, _ in unique):
        raise ValueError('ADC route is absent from the sensor layout')
    if scan_order == 'adc':
        return [route for lane in lanes for route in by_lane[lane]]
    if scan_order == 'array':
        return [route for a in sorted(layout['arrays'], key=int)
                for route in _round_robin(by_lane, sorted(layout['arrays'][a]['adc_lanes']))]
    if scan_order == 'interleaved':
        return _round_robin(by_lane, lanes)
    raise ValueError(f'Unsupported scan order: {scan_order!r}')


def format_array_routes(routes):
    return ','.join(f'{int(lane)}:{int(channel)}' for lane, channel in routes)


def build_sensor_groups(sensor_ids, layout):
    groups, cursor = [], 0
    for sensor in sensor_ids:
        mapping = layout['mux_mapping'][sensor]
        channels = list(mapping['channels'])
        groups.append(dict(sensor_id=sensor, mux=mapping['mux'], channels=channels,
                           channel_labels=list(layout['channel_sensor_map']),
                           positions=list(range(cursor, cursor + len(channels)))))
        cursor += len(channels)
    return groups
