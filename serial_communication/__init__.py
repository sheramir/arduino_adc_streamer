"""
Serial Communication Module
===========================
Handles all serial communication with ADC and force sensors.
"""

from .serial_threads import SerialReaderThread, ForceReaderThread
from .adc_connection_state import (
    ADCConnectionViewState,
    ArduinoStatus,
    LastSentConfig,
    build_connected_view_state,
    build_default_arduino_status,
    build_default_last_sent_config,
    build_disconnected_view_state,
)
from .adc_connection_workflow import (
    ADCConnectOutcome,
    ADCConnectionWorkflow,
    ADCDisconnectOutcome,
)
from .force_connection_workflow import (
    ForceConnectOutcome,
    ForceConnectionWorkflow,
    ForceDisconnectOutcome,
)
from .force_connection_state import (
    ForceConnectionViewState,
    build_force_connected_view_state,
    build_force_disconnected_view_state,
)
from .adc_session import ADCSessionController
from .force_session import ForceSessionController
from .adc_serial import ADCSerialMixin
from .force_serial import ForceSerialMixin
from .serial_parser import SerialParserMixin

__all__ = [
    'SerialReaderThread',
    'ForceReaderThread',
    'ADCConnectionViewState',
    'ArduinoStatus',
    'LastSentConfig',
    'ADCConnectOutcome',
    'ADCConnectionWorkflow',
    'ADCDisconnectOutcome',
    'ForceConnectOutcome',
    'ForceConnectionWorkflow',
    'ForceDisconnectOutcome',
    'ForceConnectionViewState',
    'build_connected_view_state',
    'build_default_arduino_status',
    'build_default_last_sent_config',
    'build_disconnected_view_state',
    'build_force_connected_view_state',
    'build_force_disconnected_view_state',
    'ADCSessionController',
    'ForceSessionController',
    'ADCSerialMixin',
    'ForceSerialMixin',
    'SerialParserMixin',
]
