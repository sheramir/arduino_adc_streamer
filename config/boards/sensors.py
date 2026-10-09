"""Resolve bundled fallback layouts by registered profile, never PCB name."""
import json
from pathlib import Path
from . import get_board_registry


def default_sensor_layout(profile):
    data = json.loads((Path(__file__).resolve().parents[2] / 'sensors_library/sensor_configurations.json').read_text(encoding='utf-8'))
    configurations = data if isinstance(data, list) else data['configurations']
    registry = get_board_registry()
    for layout in configurations:
        if layout.get('board_profile') and registry.resolve(layout['board_profile']).id == profile.id:
            return layout
    raise ValueError(f'No sensor layout is defined for board profile {profile.id}')
