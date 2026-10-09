"""One resolver for exact identities, ordered compatibility families and fallback."""
from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import hashlib
import json

from .models import BoardProfile, ModeProfile, Parameter, BoardContext, freeze
from .validation import validate_profile


class BoardRegistry:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path(__file__).parent
        index = json.loads((self.root / 'registry.json').read_text(encoding='utf-8'))
        if index['schema_version'] != 1:
            raise ValueError('Unsupported board registry schema')
        self.bootstrap = freeze(index['bootstrap'])
        self.profiles, self.aliases = {}, {}
        for filename in index['profiles']:
            path = (self.root / filename).resolve()
            if self.root.resolve() not in path.parents:
                raise ValueError('Profile path must stay in registry directory')
            data = json.loads(path.read_text(encoding='utf-8'))
            for mode in data['modes'].values():
                if mode.get('timing_profile'):
                    timing_path = (self.root / mode['timing_profile']).resolve()
                    if self.root.resolve() not in timing_path.parents:
                        raise ValueError('Timing profile path must stay in registry directory')
                    mode['timing'] = json.loads(timing_path.read_text(encoding='utf-8'))
            validate_profile(data, str(path))
            if data['id'] in self.profiles:
                raise ValueError(f'Duplicate profile ID: {data["id"]}')
            modes = {key: ModeProfile(key, freeze(mode), freeze({p: Parameter(p, freeze(d))
                     for p, d in mode['parameters'].items()})) for key, mode in data['modes'].items()}
            fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.profiles[data['id']] = BoardProfile(data['id'], freeze(data), freeze(modes), fingerprint)
            for alias in data['mcu_aliases']:
                normalized = alias.strip().casefold()
                if not normalized or normalized in self.aliases:
                    raise ValueError(f'Duplicate/empty MCU alias: {alias}')
                self.aliases[normalized] = data['id']
        self.families = index['compatibility_families']
        self.fallback = index['fallback']
        self.standalone_firmware = freeze(index.get('standalone_firmware', {}))
        self._standalone_names = {name.strip().casefold(): reason for name, reason in self.standalone_firmware.items()}
        if any(not name or name in self.aliases or not isinstance(reason, str) or not reason
               for name, reason in self._standalone_names.items()):
            raise ValueError('Invalid standalone firmware identity/reason')
        if self.fallback not in self.profiles:
            raise ValueError('Unknown fallback profile')
        priorities = set()
        patterns = set()
        for family in self.families:
            if family['profile'] not in self.profiles or family['match'] not in ('prefix', 'contains') or not family['value']:
                raise ValueError('Invalid compatibility family')
            if family['priority'] in priorities:
                raise ValueError('Ambiguous compatibility family priorities')
            priorities.add(family['priority'])
            pattern = (family['match'], family['value'].casefold())
            if pattern in patterns:
                raise ValueError('Duplicate compatibility family pattern')
            patterns.add(pattern)
        self.families.sort(key=lambda f: f['priority'])

    def resolve(self, mcu_name=None):
        name = (mcu_name or '').strip().casefold()
        if name in self._standalone_names:
            raise ValueError(f'{mcu_name}: {self._standalone_names[name]}')
        profile = self.aliases.get(name, name if name in self.profiles else None)
        if profile is None:
            for family in self.families:
                value = family['value'].casefold()
                if (name.startswith(value) if family['match'] == 'prefix' else value in name):
                    profile = family['profile']
                    break
        return self.profiles[profile or self.fallback]

    def context(self, mcu_name=None, mode=None, variant=None):
        profile = self.resolve(mcu_name)
        if variant is not None and variant not in profile.definition.get('variants', {}):
            raise ValueError(f'Unknown variant {variant!r} for {profile.id}')
        resolved_mode = profile.mode(mode)
        if variant is not None:
            allowed = profile.definition['variants'][variant].get('firmware_modes', tuple(profile.modes))
            if resolved_mode.id not in allowed:
                raise ValueError(f'Mode {resolved_mode.id} is not supported by explicit variant {variant}')
        return BoardContext((mcu_name or '').strip(), profile, resolved_mode, variant)


@lru_cache(maxsize=1)
def get_board_registry():
    return BoardRegistry()


def resolve_board(mcu_name=None):
    return get_board_registry().resolve(mcu_name)
