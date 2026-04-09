"""
Channel utility helpers.
"""

from __future__ import annotations


def unique_channels_in_order(channels) -> list:
    """Return first-occurrence unique channels while preserving input order."""
    unique_channels = []
    seen = set()
    for channel in channels:
        if channel in seen:
            continue
        seen.add(channel)
        unique_channels.append(channel)
    return unique_channels
