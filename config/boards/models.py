"""Immutable runtime definitions and the common parameter/rule vocabulary."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
from copy import deepcopy
import math


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class Parameter:
    id: str
    definition: Mapping

    @property
    def default(self):
        return self.definition['default']

    @property
    def choices(self):
        return self.definition.get('choices', ())

    @property
    def legacy_key(self):
        return self.definition.get('legacy_key', self.id)

    @property
    def label(self):
        return self.definition.get('label', self.id)

    def normalize(self, value):
        kind = self.definition['type']
        if kind == 'boolean':
            if not isinstance(value, bool):
                raise ValueError(f'{self.id} must be boolean')
        elif kind in ('integer', 'number'):
            if isinstance(value, bool):
                raise ValueError(f'{self.id} must be {kind}')
            try:
                numeric = float(value)
                if not math.isfinite(numeric) or (kind == 'integer' and not numeric.is_integer()):
                    raise ValueError()
                value = int(numeric) if kind == 'integer' else numeric
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError(f'{self.id} must be {kind}') from exc
            if value < self.definition.get('minimum', -math.inf) or value > self.definition.get('maximum', math.inf):
                raise ValueError(f'{self.id} outside allowed range')
        elif kind == 'enum':
            for choice in self.choices:
                if value == choice['id'] or value == choice.get('wire_value', choice['id']) or value in choice.get('aliases', ()):
                    value = choice['id']
                    break
            else:
                raise ValueError(f'{self.id}: unsupported value {value!r}')
        elif not isinstance(value, str):
            raise ValueError(f'{self.id} must be text')
        if self.definition.get('policy') == 'fixed' and value != self.default:
            raise ValueError(f'{self.id} is fixed at {self.default!r}')
        return value

    def choice(self, value):
        value = self.normalize(value)
        return next(c for c in self.choices if c['id'] == value)

    def wire_value(self, value):
        return self.choice(value).get('wire_value', value) if self.choices else self.normalize(value)


@dataclass(frozen=True, slots=True)
class ResolvedSettings:
    requested: Mapping
    effective: Mapping
    enabled: Mapping
    visible: Mapping


@dataclass(frozen=True, slots=True)
class ModeProfile:
    id: str
    definition: Mapping
    parameters: Mapping[str, Parameter]

    def defaults(self):
        return {k: p.default for k, p in self.parameters.items()}

    def resolve_settings(self, values=None):
        values = values or {}
        requested = {}
        for key, param in self.parameters.items():
            value = values.get(key, values.get(param.legacy_key, param.default))
            if param.definition.get('policy') in ('config_file_only', 'fixed'):
                value = param.default
            requested[key] = param.normalize(value)
        effective = dict(requested)
        enabled = {k: p.definition.get('policy', 'editable') == 'editable' for k, p in self.parameters.items()}
        visible = {k: p.definition.get('policy', 'editable') == 'editable' and p.definition.get('visible', True)
                   for k, p in self.parameters.items()}
        for rule in self.definition.get('rules', ()):
            predicate = rule['when']
            if effective[predicate['parameter']] != predicate['equals']:
                continue
            for key, value in rule.get('force', {}).items():
                requested[key] = effective[key] = self.parameters[key].normalize(value)
            for key, value in rule.get('effective', {}).items():
                effective[key] = self.parameters[key].normalize(value)
            enabled.update(rule.get('enabled', {}))
            visible.update(rule.get('visible', {}))
        return ResolvedSettings(freeze(requested), freeze(effective), freeze(enabled), freeze(visible))

    def legacy_defaults(self):
        return {p.legacy_key: p.default for p in self.parameters.values()}

    def full_scale_volts(self, reference=None):
        scaling = self.definition.get('scaling', {})
        parameter = self.parameters.get('reference')
        if parameter:
            choice = parameter.choice(reference if reference is not None else parameter.default)
            return float(choice['full_scale_volts'])
        aliases = scaling.get('legacy_references', {})
        if reference in aliases:
            return float(aliases[reference])
        return float(scaling.get('full_scale_volts', 3.3))


@dataclass(frozen=True, slots=True)
class BoardProfile:
    id: str
    definition: Mapping
    modes: Mapping[str, ModeProfile]
    fingerprint: str

    @property
    def hardware(self):
        return self.definition['hardware']

    def mode(self, selected=None):
        name = (selected or self.definition['default_mode']).strip().upper()
        return self.modes.get(name, self.modes[self.definition['default_mode']])


@dataclass(frozen=True, slots=True)
class BoardContext:
    reported_mcu: str
    profile: BoardProfile
    mode: ModeProfile
    variant: str | None = None

    def capture_snapshot(self, values=None, reported=None, sensor_configuration=None):
        settings = self.mode.resolve_settings(values)
        return dict(version=1, profile_id=self.profile.id,
                    schema_version=self.profile.definition['schema_version'],
                    profile_version=self.profile.definition['profile_version'],
                    profile_fingerprint=self.profile.fingerprint, reported_mcu=self.reported_mcu,
                    mode=self.mode.id, variant=self.variant,
                    hardware=thaw(self.profile.hardware), interpretation=thaw(self.mode.definition),
                    requested=thaw(settings.requested), effective=thaw(settings.effective),
                    full_scale_volts=self.mode.full_scale_volts(settings.requested.get('reference')),
                    reported=deepcopy(reported or {}), sensor_configuration=deepcopy(sensor_configuration))
