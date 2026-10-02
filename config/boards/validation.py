"""Strict startup validation; invalid definitions never silently become defaults."""
from .models import Parameter, freeze, ModeProfile
import math
import re
import json
from pathlib import Path
from functools import lru_cache

PROTOCOLS = {'legacy_adc', 'legacy_555', 'array_dual', 'ads7953'}
FRAMES = {'adc_u16_timed', 'timer_555', 'pzt_rs_u16', 'ads7953_u16_timed'}
ACQUISITIONS = {'channels', 'array_mux', 'array_combined', 'multi_array'}
TIMING = {'unavailable', 'mg24_mux', 'reported'}


@lru_cache(maxsize=1)
def _schema():
    return json.loads((Path(__file__).parent / 'schema.json').read_text(encoding='utf-8'))


def _object_contract(value, contract, path):
    if not isinstance(value, dict):
        raise ValueError(f'{path} must be an object')
    missing = set(contract.get('required', [])) - set(value)
    if missing:
        raise ValueError(f'{path}: missing {sorted(missing)}')
    if contract.get('additionalProperties') is False:
        extra = set(value) - set(contract.get('properties', {}))
        if extra:
            raise ValueError(f'{path}: unknown fields {sorted(extra)}')


def validate_profile(data, source='<profile>'):
    try:
        schema = _schema()
        _object_contract(data, schema, 'profile')
        _object_contract(data['hardware'], schema['properties']['hardware'], 'hardware')
        _object_contract(data['transport'], schema['properties']['transport'], 'transport')
        if not re.fullmatch(r'[a-z][a-z0-9_]*', data['id']):
            raise ValueError('invalid profile id')
        if data['schema_version'] != 1 or type(data['profile_version']) is not int or data['profile_version'] < 1:
            raise ValueError('unsupported schema/profile version')
        if not data['id'] or data['default_mode'] not in data['modes']:
            raise ValueError('invalid id or default mode')
        hw = data['hardware']
        for key in ('adc_resolution_bits', 'adc_lane_count', 'inputs_per_adc', 'max_arrays'):
            if type(hw[key]) is not int or hw[key] < 1:
                raise ValueError(f'invalid hardware {key}')
        if hw['adc_resolution_bits'] > 16:
            raise ValueError('Registered codecs support ADC resolutions up to 16 bits')
        for role, channel in hw.get('reserved_inputs', {}).items():
            if type(channel) is not int or not 0 <= channel < hw['inputs_per_adc']:
                raise ValueError(f'invalid reserved input {role}')
        if type(data['transport']['baud_rate']) is not int or data['transport']['baud_rate'] <= 0:
            raise ValueError('invalid baud rate')
        if not data['transport']['command_terminator']:
            raise ValueError('empty command terminator')
        for name, mode in data['modes'].items():
            _object_contract(mode, schema['$defs']['mode'], f'mode {name}')
            _object_contract(mode['adapters'], schema['$defs']['mode']['properties']['adapters'], 'adapters')
            if type(mode['emitted_adc_lanes']) is not int or not 1 <= mode['emitted_adc_lanes'] <= hw['adc_lane_count']:
                raise ValueError('Invalid emitted ADC lane count')
            if any(type(v) is not int or v < 1 for v in mode.get('buffer_limits', {}).values()):
                raise ValueError('invalid buffer limits')
            if name != name.upper() or mode['device_mode'] not in ('adc', '555'):
                raise ValueError('invalid mode')
            for key, allowed in (('protocol', PROTOCOLS), ('frame', FRAMES), ('acquisition', ACQUISITIONS), ('timing', TIMING)):
                if mode['adapters'][key] not in allowed:
                    raise ValueError(f'unknown {key} adapter {mode["adapters"][key]}')
            params = {}
            legacy = set()
            for key, definition in mode['parameters'].items():
                _object_contract(definition, schema['$defs']['parameter'], f'parameter {key}')
                if definition['type'] not in ('enum', 'integer', 'number', 'boolean', 'text'):
                    raise ValueError(f'invalid type for {key}')
                kind, default = definition['type'], definition['default']
                if (kind == 'integer' and type(default) is not int or
                    kind == 'boolean' and type(default) is not bool or
                    kind == 'number' and type(default) not in (int, float) or
                    kind == 'text' and not isinstance(default, str)):
                    raise ValueError(f'invalid default type for {key}')
                if definition.get('policy', 'editable') not in ('editable', 'fixed', 'config_file_only', 'reported'):
                    raise ValueError(f'invalid policy for {key}')
                if definition.get('command') and not re.fullmatch(r'[a-z][a-z0-9]*', definition['command']):
                    raise ValueError(f'invalid command for {key}')
                if definition.get('display_scale', 1) <= 0:
                    raise ValueError(f'invalid display scale for {key}')
                if definition.get('minimum', 0) > definition.get('maximum', float('inf')):
                    raise ValueError(f'inverted range for {key}')
                choices = definition.get('choices', [])
                ids = [c['id'] for c in choices]
                if len(ids) != len(set(ids)):
                    raise ValueError(f'duplicate choices for {key}')
                aliases = []
                for choice in choices:
                    _object_contract(choice, schema['$defs']['choice'], f'choice in {key}')
                    aliases.extend([choice['id'], *choice.get('aliases', [])])
                    if key == 'reference' and (not math.isfinite(choice['full_scale_volts']) or choice['full_scale_volts'] <= 0):
                        raise ValueError('invalid reference span')
                if len(aliases) != len(set(aliases)):
                    raise ValueError(f'ambiguous choice aliases for {key}')
                p = Parameter(key, freeze(definition))
                p.normalize(p.default)
                if p.legacy_key in legacy:
                    raise ValueError(f'duplicate legacy key {p.legacy_key}')
                legacy.add(p.legacy_key)
                params[key] = p
            for rule in mode.get('rules', []):
                if set(rule) - {'when', 'force', 'effective', 'enabled', 'visible'}:
                    raise ValueError('unknown rule action')
                predicate = rule['when']
                params[predicate['parameter']].normalize(predicate['equals'])
                for action in ('force', 'effective', 'enabled', 'visible'):
                    for key, value in rule.get(action, {}).items():
                        if action in ('force', 'effective'):
                            params[key].normalize(value)
                        elif key not in params or not isinstance(value, bool):
                            raise ValueError('invalid rule target/state')
            ModeProfile(name, freeze(mode), freeze(params)).resolve_settings()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'{source}: {exc}') from exc


def validate_sensor_layout(layout, profile):
    """Validate structural electrical capacity, never compare a baked-in wiring map."""
    hw = profile.hardware
    arrays = layout.get('arrays') or {'1': {'adc_lanes': list(range(1, hw['adc_lane_count'] + 1))}}
    if not 1 <= len(arrays) <= hw['max_arrays'] or layout.get('array_count', len(arrays)) != len(arrays):
        raise ValueError('Sensor array_count does not match board capacity/array entries')
    lanes_seen = set()
    pair_width = None
    for key, array in arrays.items():
        if not str(key).isdigit() or int(key) < 1:
            raise ValueError('Invalid sensor array ID')
        lanes = array['adc_lanes']
        if not lanes or len(set(lanes)) != len(lanes):
            raise ValueError('Empty or duplicate ADC lanes')
        if pair_width is not None and pair_width != len(lanes):
            raise ValueError('Mirrored arrays must have equal lane counts')
        pair_width = len(lanes)
        for lane in lanes:
            if type(lane) is not int or not 1 <= lane <= hw['adc_lane_count'] or lane in lanes_seen:
                raise ValueError('ADC lane outside board capacity or shared by arrays')
            lanes_seen.add(lane)
    positions = layout.get('channel_sensor_map', [])
    if not positions or len(set(positions)) != len(positions):
        raise ValueError('Sensor channel labels must be nonempty and unique')
    requirements = profile.definition.get('sensor_requirements', {})
    if requirements.get('placements') and set(positions) != set(requirements['placements']):
        raise ValueError('Sensor placements do not meet processing requirements')
    populated = [s for row in layout.get('array_layout', {}).get('cells', []) for s in row if s]
    cells = set(populated)
    if len(cells) != len(populated):
        raise ValueError('Duplicate spatial sensor ID')
    mappings = layout.get('mux_mapping', {})
    if cells != set(mappings):
        raise ValueError('Spatial sensors and electrical mappings disagree')
    occupied = set()
    for sensor, mapping in mappings.items():
        mux, channels = mapping['mux'], mapping['channels']
        if type(mux) is not int or not 1 <= mux <= pair_width or len(channels) != len(positions):
            raise ValueError(f'{sensor}: invalid ADC position/channel count')
        for channel in channels:
            route = (mux, channel)
            if type(channel) is not int or not 0 <= channel < hw['inputs_per_adc'] or channel in hw.get('reserved_inputs', {}).values():
                raise ValueError(f'{sensor}: reserved or out-of-range channel')
            if route in occupied:
                raise ValueError(f'{sensor}: overlapping channel mapping')
            occupied.add(route)
