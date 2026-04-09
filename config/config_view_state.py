"""
Configuration View State Helpers
================================
Plain helpers for configure/start button presentation state.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigureButtonState:
    enabled: bool
    style: str | None
    status_message: str | None = None
    status_timeout_ms: int = 0


@dataclass(frozen=True, slots=True)
class StartButtonState:
    enabled: bool
    style: str | None
    text: str


def build_configuring_state() -> ConfigureButtonState:
    return ConfigureButtonState(enabled=False, style=None)


def build_configuration_success_state() -> ConfigureButtonState:
    return ConfigureButtonState(
        enabled=True,
        style="QPushButton { background-color: #2196F3; color: white; font-weight: bold; }",
        status_message="Configured - Ready to capture",
        status_timeout_ms=3000,
    )


def build_configuration_failed_state() -> ConfigureButtonState:
    return ConfigureButtonState(
        enabled=True,
        style="QPushButton { background-color: #FF9800; color: white; font-weight: bold; }",
        status_message="Configuration failed - please retry",
        status_timeout_ms=5000,
    )


def build_start_ready_state() -> StartButtonState:
    return StartButtonState(
        enabled=True,
        style="QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }",
        text="Start ✓",
    )


def build_start_needs_config_state() -> StartButtonState:
    return StartButtonState(
        enabled=False,
        style="QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }",
        text="Start (Configure First)",
    )


def build_start_unavailable_state() -> StartButtonState:
    return StartButtonState(
        enabled=False,
        style=None,
        text="Start",
    )
