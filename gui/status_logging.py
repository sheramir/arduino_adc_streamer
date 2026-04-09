"""
Status Logging Mixin
====================
GUI-owned status text logging helpers.
"""

from __future__ import annotations

from datetime import datetime

from config_constants import MAX_LOG_LINES


class StatusLoggingMixin:
    """Own the status text widget update behavior."""

    def log_status(self, message: str):
        """Append a timestamped message and keep the log bounded."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.status_text.append(f"[{timestamp}] {message}")

        current_text = self.status_text.toPlainText()
        lines = current_text.split('\n')
        if len(lines) > MAX_LOG_LINES:
            self.status_text.setPlainText('\n'.join(lines[-MAX_LOG_LINES:]))

        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )
