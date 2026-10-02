"""Versioned offline interpretation; never resolve saved captures against live JSON."""
from dataclasses import asdict, is_dataclass
from copy import deepcopy
import math
from .models import Parameter, ModeProfile, freeze
from .settings import context_for, parameter_values


def validate_capture_context(snapshot):
    try:
        if snapshot['version'] != 1 or snapshot['schema_version'] != 1 or not snapshot['profile_id']:
            raise ValueError('Unsupported captured board context')
        hw, interpretation = snapshot['hardware'], snapshot['interpretation']
        if type(hw['adc_resolution_bits']) is not int or not 1 <= hw['adc_resolution_bits'] <= 32:
            raise ValueError('Invalid captured ADC resolution')
        params = {k: Parameter(k, freeze(d)) for k, d in interpretation['parameters'].items()}
        mode = ModeProfile(snapshot['mode'], freeze(interpretation), freeze(params))
        resolved = mode.resolve_settings(snapshot['requested'])
        if dict(resolved.requested) != snapshot['requested'] or dict(resolved.effective) != snapshot['effective']:
            raise ValueError('Captured settings contradict captured rules')
        scale = float(snapshot.get('full_scale_volts', mode.full_scale_volts(snapshot['requested'].get('reference'))))
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError('Invalid captured voltage span')
        if scale != mode.full_scale_volts(snapshot['requested'].get('reference')):
            raise ValueError('Captured voltage span contradicts captured reference')
    except (KeyError, TypeError) as exc:
        raise ValueError('Incomplete captured board context') from exc
    return snapshot


def freeze_owner_context(owner):
    context = context_for(owner)
    status = getattr(owner, 'arduino_status', None)
    reported = asdict(status) if is_dataclass(status) else {}
    layout = owner.get_active_sensor_configuration() if hasattr(owner, 'get_active_sensor_configuration') else None
    owner.board_capture_context = context.capture_snapshot(parameter_values(owner.config), reported, layout)
    owner.board_capture_context['acquisition'] = deepcopy(parameter_values(owner.config))
    if hasattr(owner, 'get_acquisition_channel_specs'):
        from data_processing.acquisition_adapters import acquisition_adapter
        owner.board_capture_context['channel_specs'] = deepcopy(acquisition_adapter(context).channel_specs(owner))
    return owner.board_capture_context


def adc_resolution_bits(owner):
    saved = getattr(owner, 'board_capture_context', None)
    descriptor = getattr(owner, 'testboard_capture_descriptor', None)
    if descriptor:
        return descriptor['adc_resolution_bits']
    if saved:
        return saved['hardware']['adc_resolution_bits']
    return context_for(owner).profile.hardware['adc_resolution_bits']


def full_scale_volts(owner):
    descriptor = owner.get_testboard_descriptor() if hasattr(owner, 'get_testboard_descriptor') else None
    if descriptor:
        return float(descriptor.get('full_scale_volts', descriptor['reference']))
    saved = getattr(owner, 'board_capture_context', None)
    if saved:
        return float(saved['full_scale_volts'])
    context = context_for(owner)
    reference = owner.config.get('reference')
    if 'reference' in context.mode.parameters:
        try:
            return context.mode.full_scale_volts(reference)
        except ValueError:
            pass
    aliases = context.mode.definition.get('scaling', {}).get('legacy_references', {})
    if reference in aliases:
        return float(aliases[reference])
    try:
        return context.mode.full_scale_volts(reference)
    except ValueError:
        if context.mode.definition.get('scaling', {}).get('unknown_reference') == 'default':
            return context.mode.full_scale_volts()
        raise


def attach_capture_context(owner, metadata):
    saved = getattr(owner, 'board_capture_context', None)
    if saved:
        metadata['board_context'] = deepcopy(saved)
        metadata['mcu_type'] = saved['reported_mcu']
        config = metadata.setdefault('configuration', {})
        config.update(adc_resolution_bits=saved['hardware']['adc_resolution_bits'],
                      vref_voltage=saved['full_scale_volts'])
        for key, value in saved.get('acquisition', {}).items():
            if key != 'parameters':
                config[key] = deepcopy(value)
