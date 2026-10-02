"""Read-only aliases for historical constants, without importing GUI/config code.

The JSON files remain the owner. New device logic uses BoardContext instead.
"""
import json
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=None)
def legacy_mode(profile, mode=None):
    path = Path(__file__).resolve().parents[1] / 'config/boards/profiles' / f'{profile}.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    return data['modes'][mode or data['default_mode']]


def legacy_parameter(profile, key, field='default'):
    return legacy_mode(profile)['parameters'][key][field]


@lru_cache(maxsize=1)
def legacy_bootstrap():
    path = Path(__file__).resolve().parents[1] / 'config/boards/registry.json'
    return json.loads(path.read_text(encoding='utf-8'))['bootstrap']
