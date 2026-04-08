"""
ADC Connection Workflow
=======================
Coordinates ADC session connect/disconnect steps without touching GUI widgets.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ADCConnectOutcome:
    port_name: str
    mcu_name: str | None = None


@dataclass(frozen=True, slots=True)
class ADCDisconnectOutcome:
    warnings: list[str] = field(default_factory=list)


class ADCConnectionWorkflow:
    """Coordinate ADC session connect/disconnect sequencing."""

    def connect(self, session, port_name: str, *, mcu_detection_timeout: float) -> ADCConnectOutcome:
        session.connect(port_name)
        mcu_name = session.detect_mcu(mcu_detection_timeout)
        return ADCConnectOutcome(port_name=port_name, mcu_name=mcu_name)

    def disconnect(self, session) -> ADCDisconnectOutcome:
        if session is None:
            return ADCDisconnectOutcome()
        return ADCDisconnectOutcome(warnings=list(session.disconnect()))
