"""
Serial Communication Module
===========================
Handles all serial communication with ADC and force sensors.
"""

from .serial_threads import SerialReaderThread, ForceReaderThread
from .adc_connection_state import (
    ADCConnectionViewState,
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
from .adc_session import ADCSessionController
from .adc_serial import ADCSerialMixin
from .force_serial import ForceSerialMixin
from .serial_parser import SerialParserMixin

__all__ = [
    'SerialReaderThread',
    'ForceReaderThread',
    'ADCConnectionViewState',
    'ADCConnectOutcome',
    'ADCConnectionWorkflow',
    'ADCDisconnectOutcome',
    'build_connected_view_state',
    'build_default_arduino_status',
    'build_default_last_sent_config',
    'build_disconnected_view_state',
    'ADCSessionController',
    'ADCSerialMixin',
    'ForceSerialMixin',
    'SerialParserMixin',
]
