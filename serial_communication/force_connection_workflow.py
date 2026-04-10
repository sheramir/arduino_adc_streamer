"""
Force Connection Workflow
=========================
Coordinates force session connect/disconnect steps without touching GUI widgets.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ForceConnectOutcome:
    port_name: str
    should_start_calibration: bool = True


@dataclass(frozen=True, slots=True)
class ForceDisconnectOutcome:
    warnings: list[str] = field(default_factory=list)


class ForceConnectionWorkflow:
    """Coordinate force session connect/disconnect sequencing."""

    def connect(self, session, port_name: str) -> ForceConnectOutcome:
        session.connect(port_name)
        return ForceConnectOutcome(port_name=port_name, should_start_calibration=True)

    def disconnect(self, session) -> ForceDisconnectOutcome:
        if session is None:
            return ForceDisconnectOutcome()
        return ForceDisconnectOutcome(warnings=list(session.disconnect()))
