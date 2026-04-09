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
from .config_view_state import (
    ConfigureButtonState,
    StartButtonState,
    build_configuration_failed_state,
    build_configuration_success_state,
    build_configuring_state,
    build_start_needs_config_state,
    build_start_ready_state,
    build_start_unavailable_state,
)
from .config_snapshot import (
    ADCConfigurationSnapshot,
    VREF_LABEL_TO_COMMAND,
    build_adc_configuration_snapshot,
    normalize_gain,
    normalize_reference,
)
from .mcu_view_state import MCUViewState, build_mcu_view_state
from .adc_config_state import ADCConfigurationState, build_default_adc_config_state

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
    'ConfigureButtonState',
    'StartButtonState',
    'build_configuration_failed_state',
    'build_configuration_success_state',
    'build_configuring_state',
    'build_start_needs_config_state',
    'build_start_ready_state',
    'build_start_unavailable_state',
    'ADCConfigurationSnapshot',
    'VREF_LABEL_TO_COMMAND',
    'build_adc_configuration_snapshot',
    'normalize_gain',
    'normalize_reference',
    'MCUViewState',
    'build_mcu_view_state',
    'ADCConfigurationState',
    'build_default_adc_config_state',
]
