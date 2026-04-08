"""
Configuration Module
====================
ADC configuration and MCU detection.
"""

from .mcu_detector import MCUDetectorMixin
from .config_handlers import ConfigurationMixin
from .sensor_config import SensorConfigStore
from .adc_configuration_service import ADCConfigurationService
from .adc_configuration_runner import ADCConfigurationRunner
from .mcu_profile import MCUProfile, resolve_mcu_profile
from .mcu_state import (
    MCUState,
    build_detected_mcu_state,
    build_disconnected_mcu_state,
    build_unknown_mcu_state,
)

__all__ = [
    'MCUDetectorMixin',
    'ConfigurationMixin',
    'SensorConfigStore',
    'ADCConfigurationService',
    'ADCConfigurationRunner',
    'MCUProfile',
    'resolve_mcu_profile',
    'MCUState',
    'build_detected_mcu_state',
    'build_disconnected_mcu_state',
    'build_unknown_mcu_state',
]
