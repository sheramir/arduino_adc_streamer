"""Compatibility facade for the pre-registry acquisition API."""
from config.array_acquisition import build_descriptor, descriptor_specs, descriptor_groups, validate_descriptor
from config.array_acquisition import normalize_settings as _normalize_settings, validate_board_layout as _validate_board_layout
from config.boards import get_board_registry


def normalize_settings(reference, spi_clock_hz, channel_repeat, sequence, vmid, context=None):
    return _normalize_settings(reference, spi_clock_hz, channel_repeat, sequence, vmid,
                               context or get_board_registry().context('TestBoard_7953'))


def validate_board_layout(layout, context=None):
    return _validate_board_layout(layout, context or get_board_registry().context('TestBoard_7953'))
