"""
Custom Qt Widgets with enhanced behavior.
========================================
Custom spinbox widgets that don't respond to mouse wheel scrolling.
"""

from PyQt6.QtWidgets import QSpinBox, QDoubleSpinBox
from PyQt6.QtGui import QWheelEvent


class NonScrollableSpinBox(QSpinBox):
    """QSpinBox that ignores mouse wheel events to prevent accidental value changes."""
    
    def wheelEvent(self, event: QWheelEvent):
        """Override wheelEvent to ignore mouse wheel scrolling."""
        event.ignore()


class NonScrollableDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that ignores mouse wheel events to prevent accidental value changes."""
    
    def wheelEvent(self, event: QWheelEvent):
        """Override wheelEvent to ignore mouse wheel scrolling."""
        event.ignore()
