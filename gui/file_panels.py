"""
File and Status Panels Mixin
=============================
GUI components for file management and status display.
"""

import os
from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QGridLayout, QLabel, QPushButton, 
    QLineEdit, QTextEdit, QCheckBox, QSpinBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from config_constants import (
    SWEEP_RANGE_MIN, SWEEP_RANGE_MAX, SWEEP_RANGE_DEFAULT_MAX,
    NOTES_INPUT_HEIGHT, STATUS_TEXT_HEIGHT
)


class FilePanelsMixin:
    """Mixin class for file management and status GUI components."""
    
    def create_file_management_section(self) -> QGroupBox:
        """Create file management section."""
        group = QGroupBox("Data Export")
        layout = QGridLayout()

        # Directory selection
        layout.addWidget(QLabel("Directory:"), 0, 0)
        self.dir_input = QLineEdit()
        # Default save directory - uses current user's home directory
        self.dir_input.setText(os.path.join(os.path.expanduser("~"), "Documents", "sensetics", "data", "adc"))
        layout.addWidget(self.dir_input, 0, 1)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_directory)
        layout.addWidget(self.browse_btn, 0, 2)

        # Filename
        layout.addWidget(QLabel("Filename:"), 1, 0)
        self.filename_input = QLineEdit()
        self.filename_input.setText("adc_data")
        layout.addWidget(self.filename_input, 1, 1, 1, 2)

        # Notes
        layout.addWidget(QLabel("Notes:"), 2, 0, Qt.AlignmentFlag.AlignTop)
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Add notes about this capture (optional)")
        self.notes_input.setMaximumHeight(NOTES_INPUT_HEIGHT)
        layout.addWidget(self.notes_input, 2, 1, 1, 2)

        # Sample range selection
        self.use_range_check = QCheckBox("Save Range:")
        self.use_range_check.setToolTip("Enable to save only a specific range of sweeps")
        self.use_range_check.stateChanged.connect(self.on_use_range_changed)
        layout.addWidget(self.use_range_check, 3, 0)

        # Min sweep
        self.min_sweep_spin = QSpinBox()
        self.min_sweep_spin.setRange(SWEEP_RANGE_MIN, SWEEP_RANGE_MAX)
        self.min_sweep_spin.setValue(SWEEP_RANGE_MIN)
        self.min_sweep_spin.setPrefix("Min: ")
        self.min_sweep_spin.setEnabled(False)
        self.min_sweep_spin.setToolTip("Starting sweep index (inclusive)")
        layout.addWidget(self.min_sweep_spin, 3, 1)

        # Max sweep
        self.max_sweep_spin = QSpinBox()
        self.max_sweep_spin.setRange(SWEEP_RANGE_MIN, SWEEP_RANGE_MAX)
        self.max_sweep_spin.setValue(SWEEP_RANGE_DEFAULT_MAX)
        self.max_sweep_spin.setPrefix("Max: ")
        self.max_sweep_spin.setEnabled(False)
        self.max_sweep_spin.setToolTip("Ending sweep index (inclusive)")
        layout.addWidget(self.max_sweep_spin, 3, 2)

        # Save data button
        self.save_data_btn = QPushButton("Save Data (CSV)")
        self.save_data_btn.clicked.connect(self.save_data)
        layout.addWidget(self.save_data_btn, 4, 0, 1, 2)

        # Save image button
        self.save_image_btn = QPushButton("Save Plot Image")
        self.save_image_btn.clicked.connect(self.save_plot_image)
        layout.addWidget(self.save_image_btn, 4, 2)

        group.setLayout(layout)
        return group

    def create_status_section(self) -> QGroupBox:
        """Create status display section."""
        group = QGroupBox("Status & Messages")
        layout = QVBoxLayout()

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(STATUS_TEXT_HEIGHT)
        font = QFont("Courier", 9)
        self.status_text.setFont(font)
        layout.addWidget(self.status_text)

        group.setLayout(layout)
        return group
