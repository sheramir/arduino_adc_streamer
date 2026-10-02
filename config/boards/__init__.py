"""Versioned board definitions. Sensor wiring belongs to sensors_library/."""
from .registry import BoardRegistry, get_board_registry, resolve_board
from .models import BoardContext, BoardProfile, ModeProfile, Parameter

__all__ = ['BoardRegistry', 'BoardContext', 'BoardProfile', 'ModeProfile', 'Parameter',
           'get_board_registry', 'resolve_board']
