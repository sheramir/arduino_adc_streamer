"""Legacy import facade. Board values come from JSON; wiring from sensor JSON.

New consumers pass the active layout. These read-only compatibility names use
the bundled layout and must never be used to validate an edited sensor mapping.
"""
from dataclasses import dataclass
import json
from pathlib import Path
from config.boards import resolve_board, get_board_registry


def is_testboard_7953(mcu_name):
    return resolve_board(mcu_name).mode().definition['adapters']['acquisition'] == 'multi_array'


def default_layout():
    data = json.loads((Path(__file__).resolve().parents[1] / 'sensors_library/sensor_configurations.json').read_text(encoding='utf-8'))
    configs = data if isinstance(data, list) else data['configurations']
    return next(c for c in configs if c.get('board_profile') in ('TestBoard_7953', 'testboard_7953'))


@dataclass(frozen=True, slots=True)
class PztBoardRoute:
    adc_position: int
    channels: tuple


def supported_pzt_sensors(layout=None):
    return tuple((layout or default_layout())['mux_mapping'])


def build_testboard_sensor_groups(sensor_ids, layout=None):
    layout = layout or default_layout()
    groups, cursor = [], 0
    for sensor in sensor_ids:
        sensor = str(sensor).strip().upper()
        mapping = layout['mux_mapping'].get(sensor)
        if mapping is None:
            continue
        channels = list(mapping['channels'])
        groups.append(dict(sensor_id=sensor, mux=mapping['mux'], channels=channels,
                           channel_labels=list(layout['channel_sensor_map']),
                           positions=list(range(cursor, cursor + len(channels)))))
        cursor += len(channels)
    return groups


def __getattr__(key):
    profile = get_board_registry().profiles['testboard_7953']
    mode = profile.mode()
    fields = {'TESTBOARD_DEFAULT_SCAN_ORDER': ('scan_order', 'default'),
              'TESTBOARD_DEFAULT_SPI_CLOCK_HZ': ('spi_clock_hz', 'default'),
              'TESTBOARD_MIN_SPI_CLOCK_HZ': ('spi_clock_hz', 'minimum'),
              'TESTBOARD_MAX_SPI_CLOCK_HZ': ('spi_clock_hz', 'maximum')}
    if key in fields:
        param, field = fields[key]
        return mode.parameters[param].definition[field]
    if key == 'TESTBOARD_VMID_CHANNEL':
        return profile.hardware['reserved_inputs']['vmid']
    if key == 'TESTBOARD_7953_MCU_NAME':
        return profile.definition['mcu_aliases'][0]
    if key == 'TESTBOARD_MCU_ALIASES':
        return tuple(profile.definition['mcu_aliases'])
    if key == 'ARRAY_ADC_LANES':
        return {int(a): tuple(v['adc_lanes']) for a, v in default_layout()['arrays'].items()}
    if key == 'PZT_CHANNEL_LABELS':
        return tuple(default_layout()['channel_sensor_map'])
    if key == 'PZT_SENSOR_ROUTES':
        return {s: PztBoardRoute(m['mux'], tuple(m['channels'])) for s, m in default_layout()['mux_mapping'].items()}
    raise AttributeError(key)
