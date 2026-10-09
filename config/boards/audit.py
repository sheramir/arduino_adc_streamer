"""Validate installed definitions and print the identity/mode inventory."""
from pathlib import Path
import re
from .registry import BoardRegistry


def audit(root=None):
    registry = BoardRegistry(root)
    readme = Path(__file__).resolve().parents[2] / 'Arduino_Sketches/README.md'
    sketch_map = readme.read_text(encoding='utf-8').split('## Current Sketch Map', 1)[1].split('## Which Sketch', 1)[0]
    names = sorted(set(re.findall(r'`# ([^`]+)`', sketch_map)))
    for name in names:
        if name in registry.standalone_firmware:
            continue
        if registry.resolve(name).id == registry.fallback:
            raise ValueError(f'Active firmware identity has no profile: {name}')
    for board in registry.profiles.values():
        for mode in board.modes.values():
            mode.resolve_settings()
    return registry, names


def main():
    registry, names = audit()
    for board in registry.profiles.values():
        identities = ', '.join(board.definition['mcu_aliases']) or '(declared compatibility fallback)'
        print(f'{board.id}: {identities}; modes={",".join(board.modes)}')
    for name, reason in registry.standalone_firmware.items():
        print(f'{name}: {reason}')
    standalone = sum(name in registry.standalone_firmware for name in names)
    print(f'Validated {len(registry.profiles)} GUI profiles, {len(names) - standalone} active GUI identities and {standalone} standalone firmware identities.')


if __name__ == '__main__':
    main()
