"""
Offline Analysis tab.

The panel is read-only relative to acquisition state.  It copies a source
snapshot, prepares display traces through ``data_processing.analysis_workbench``,
and renders them on stacked, X-linked plots.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from pyqtgraph.exporters import ImageExporter

from constants.plotting import PLOT_COLORS, PLOT_EXPORT_WIDTH
from constants.pzt_force import (
    PZT_FORCE_CAPACITANCE_UNITS,
    PZT_FORCE_DEFAULT_SETTINGS,
    PZT_FORCE_MUX_TIMING_MODES,
)
from constants.ui import AnalysisLoadState
from data_processing.analysis_compute_worker import AnalysisComputeWorker
from data_processing.analysis_workbench import (
    AnalysisPreparedData,
    AnalysisSourceSnapshot,
    build_in_memory_snapshot,
    build_snapshot_from_archive,
    estimate_analysis_pzt_force_calibration,
    load_exported_csv_snapshot,
    prepare_analysis_data,
)
from file_operations.export_metadata import build_analysis_export_metadata
from file_operations.settings_persistence import load_settings_payload, save_settings_payload


ANALYSIS_CHECKBOX_MIN_COLUMN_WIDTH = 130


class AnalysisPanelMixin:
    """Mixin providing the offline Analysis tab and interactions."""

    def _init_analysis_state(self):
        self.analysis_state = {
            "source_mode": "in_memory",
            "axis_mode": "time_ms",
            "zoom_mode": "xy",
            "filter_enabled": False,
            "marker_enabled": True,
            "overlays": {
                "shear": True,
                "normal": True,
                "integration": True,
            },
            "pzt_force": {**PZT_FORCE_DEFAULT_SETTINGS, "channel_calibration": {}},
            "visible_labels": {},
            "visible_force_labels": {},
            "csv_path": "",
            "metadata_path": "",
        }
        self._analysis_settings_loading = False
        self.analysis_snapshot: AnalysisSourceSnapshot | None = None
        self.analysis_prepared: AnalysisPreparedData | None = None
        self._analysis_load_state = AnalysisLoadState.IDLE
        self._analysis_generation = 0
        self._analysis_loaded_status = ""
        self.analysis_compute_worker = AnalysisComputeWorker()
        self.analysis_compute_worker.result_ready.connect(self._on_analysis_compute_result)
        self.analysis_compute_worker.error_occurred.connect(self._on_analysis_compute_error)
        self.analysis_compute_worker.start()
        self.analysis_channel_checks: dict[str, QCheckBox] = {}
        self.analysis_signal_curves = {}
        self.analysis_force_curves = {}
        self.analysis_overlay_curves = {}
        self.analysis_integration_curves = {}
        self.analysis_derived_curves = {}
        self.analysis_trace_colors = {}
        # Last pen color applied per (group, curve key), so an unchanged colour
        # does not rebuild and reassign a QPen on every render.
        self._analysis_pen_colors: dict[tuple[str, str], object] = {}
        self.analysis_force_checks: dict[str, QCheckBox] = {}
        self._analysis_marker_timer = QTimer()
        self._analysis_marker_timer.setSingleShot(True)
        self._analysis_pending_marker_x = None
        self._analysis_saved_view_ranges: dict[str, tuple[list[float], list[float]]] = {}

    def shutdown_analysis_worker(self):
        worker = getattr(self, "analysis_compute_worker", None)
        if worker is not None:
            worker.stop()
            worker.wait(1500)

    def _get_last_analysis_settings_path(self):
        return Path.home() / ".adc_streamer" / "analysis" / "last_used_analysis_settings.json"

    def _serialize_analysis_settings(self):
        return {"version": 1, "analysis_settings": dict(getattr(self, "analysis_state", {}))}

    def save_last_analysis_settings(self):
        if getattr(self, "_analysis_settings_loading", False):
            return
        try:
            save_settings_payload(self._get_last_analysis_settings_path(), self._serialize_analysis_settings())
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"Warning: could not save Analysis settings: {exc}")

    def load_last_analysis_settings(self):
        try:
            path = self._get_last_analysis_settings_path()
            if not path.exists():
                return
            _path, payload = load_settings_payload(path, payload_key="analysis_settings")
            if isinstance(payload, dict):
                # Capture the nested defaults first: update() replaces nested dicts
                # wholesale, which would drop any key the saved payload omits.
                default_overlays = dict(self.analysis_state.get("overlays", {}))
                default_pzt_force = dict(self.analysis_state.get("pzt_force", {}))

                self.analysis_state.update(payload)

                overlays = payload.get("overlays")
                if isinstance(overlays, dict):
                    default_overlays.update(overlays)
                    self.analysis_state["overlays"] = default_overlays
                pzt_force = payload.get("pzt_force")
                if isinstance(pzt_force, dict):
                    # Saved single-Cpzt settings remain valid: copy their value
                    # into both new package-position fields on first load.
                    legacy_capacitance = pzt_force.get("capacitance_value")
                    if legacy_capacitance is not None:
                        pzt_force = dict(pzt_force)
                        pzt_force.setdefault("center_capacitance_value", legacy_capacitance)
                        pzt_force.setdefault("outer_capacitance_value", legacy_capacitance)
                    default_pzt_force.update(pzt_force)
                    self.analysis_state["pzt_force"] = default_pzt_force
                visible = payload.get("visible_labels")
                if isinstance(visible, dict):
                    self.analysis_state["visible_labels"] = visible
                visible_force = payload.get("visible_force_labels")
                if isinstance(visible_force, dict):
                    self.analysis_state["visible_force_labels"] = visible_force
                self._apply_analysis_settings_to_widgets()
        except Exception as exc:
            if hasattr(self, "log_status"):
                self.log_status(f"Warning: could not load Analysis settings: {exc}")

    def create_analysis_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setContentsMargins(4, 2, 4, 4)
        root.setSpacing(2)

        self.analysis_disabled_label = QLabel("")
        self.analysis_disabled_label.setStyleSheet("QLabel { color: #9C27B0; font-weight: bold; }")
        self.analysis_disabled_label.setVisible(False)
        root.addWidget(self.analysis_disabled_label)

        self.analysis_inner_tabs = QTabWidget()
        root.addWidget(self.analysis_inner_tabs)

        display_scroll = QScrollArea()
        display_scroll.setWidgetResizable(True)
        display_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        display_content = QWidget()
        display_root = QVBoxLayout(display_content)
        display_scroll.setWidget(display_content)
        self.analysis_inner_tabs.addTab(display_scroll, "Display")

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_content = QWidget()
        settings_root = QVBoxLayout(settings_content)
        settings_scroll.setWidget(settings_content)
        self.analysis_inner_tabs.addTab(settings_scroll, "Settings")

        controls = QGroupBox("")
        controls.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        controls_root = QVBoxLayout(controls)
        controls_layout = QGridLayout()
        controls_root.addLayout(controls_layout)

        controls_layout.addWidget(QLabel("Source:"), 0, 0)
        self.analysis_source_combo = QComboBox()
        self.analysis_source_combo.addItems(["In-memory cache", "CSV plus JSON"])
        self.analysis_source_combo.currentIndexChanged.connect(self.on_analysis_source_changed)
        self.analysis_source_combo.setMaximumWidth(160)
        controls_layout.addWidget(self.analysis_source_combo, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        self.analysis_load_btn = QPushButton("Load")
        self.analysis_load_btn.setToolTip("Load the latest in-memory capture, or the selected CSV plus its auto-detected metadata JSON")
        self.analysis_load_btn.clicked.connect(self.load_analysis_source)
        self.analysis_load_btn.setMaximumWidth(90)
        controls_layout.addWidget(self.analysis_load_btn, 0, 2, alignment=Qt.AlignmentFlag.AlignLeft)

        self.analysis_csv_path_edit = QLineEdit()
        self.analysis_csv_path_edit.setPlaceholderText("CSV file (matching *_metadata.json is auto-detected)")
        self.analysis_csv_path_edit.setReadOnly(True)
        self.analysis_csv_path_edit.setMinimumWidth(120)
        self.analysis_csv_path_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls_layout.addWidget(self.analysis_csv_path_edit, 0, 3)

        self.analysis_browse_csv_btn = QPushButton("Browse")
        self.analysis_browse_csv_btn.clicked.connect(self.on_analysis_browse_csv)
        self.analysis_browse_csv_btn.setMaximumWidth(90)
        controls_layout.addWidget(self.analysis_browse_csv_btn, 0, 4, alignment=Qt.AlignmentFlag.AlignLeft)

        controls_layout.addWidget(QLabel("X Axis:"), 0, 5)
        self.analysis_axis_combo = QComboBox()
        self.analysis_axis_combo.addItems(["Time s", "Sample index"])
        self.analysis_axis_combo.currentIndexChanged.connect(self.on_analysis_settings_changed)
        self.analysis_axis_combo.setMaximumWidth(120)
        controls_layout.addWidget(self.analysis_axis_combo, 0, 6, alignment=Qt.AlignmentFlag.AlignLeft)

        self.analysis_reset_view_btn = QPushButton("Reset View")
        self.analysis_reset_view_btn.clicked.connect(self.reset_analysis_view)
        self.analysis_reset_view_btn.setMaximumWidth(110)
        controls_layout.addWidget(self.analysis_reset_view_btn, 0, 7, alignment=Qt.AlignmentFlag.AlignLeft)
        controls_layout.setColumnStretch(3, 1)

        self.analysis_filter_check = QCheckBox("Spectrum filter")
        self.analysis_filter_check.stateChanged.connect(self.on_analysis_settings_changed)
        controls_layout.addWidget(self.analysis_filter_check, 1, 0)
        self.analysis_shear_check = QCheckBox("Shear")
        self.analysis_shear_check.stateChanged.connect(self.on_analysis_settings_changed)
        controls_layout.addWidget(self.analysis_shear_check, 1, 1)
        self.analysis_normal_check = QCheckBox("Normal pressure")
        self.analysis_normal_check.stateChanged.connect(self.on_analysis_settings_changed)
        controls_layout.addWidget(self.analysis_normal_check, 1, 2)
        self.analysis_integration_check = QCheckBox("Integration")
        self.analysis_integration_check.stateChanged.connect(self.on_analysis_settings_changed)
        controls_layout.addWidget(self.analysis_integration_check, 1, 3)
        self.analysis_pzt_force_check = QCheckBox("Calculate PZT Force")
        self.analysis_pzt_force_check.stateChanged.connect(self.on_analysis_settings_changed)
        controls_layout.addWidget(self.analysis_pzt_force_check, 1, 4, 1, 2)
        self.analysis_marker_check = QCheckBox("Marker")
        self.analysis_marker_check.setChecked(True)
        self.analysis_marker_check.stateChanged.connect(self.on_analysis_marker_toggled)
        controls_layout.addWidget(self.analysis_marker_check, 1, 6, 1, 2)

        channel_row = QHBoxLayout()
        self.analysis_select_all_btn = QPushButton("All")
        self.analysis_select_all_btn.clicked.connect(lambda: self.set_all_analysis_channels(True))
        self.analysis_select_all_btn.setMaximumWidth(60)
        channel_row.addWidget(self.analysis_select_all_btn)
        self.analysis_select_none_btn = QPushButton("None")
        self.analysis_select_none_btn.clicked.connect(lambda: self.set_all_analysis_channels(False))
        self.analysis_select_none_btn.setMaximumWidth(60)
        channel_row.addWidget(self.analysis_select_none_btn)

        self.analysis_channel_container = QWidget()
        self.analysis_channel_layout = QGridLayout(self.analysis_channel_container)
        self.analysis_channel_layout.setContentsMargins(4, 2, 4, 2)
        self.analysis_channel_layout.setSpacing(5)
        channel_scroll = QScrollArea()
        channel_scroll.setWidget(self.analysis_channel_container)
        channel_scroll.setWidgetResizable(True)
        channel_scroll.setFixedHeight(40)
        channel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        channel_scroll.viewport().installEventFilter(self)
        self._analysis_checkbox_scroll = channel_scroll
        channel_row.addWidget(channel_scroll, stretch=1)
        controls_root.addLayout(channel_row)

        display_root.addWidget(controls)

        pzt_force_group = QGroupBox("PZT Force Settings")
        pzt_force_layout = QGridLayout(pzt_force_group)
        pzt_force_layout.addWidget(QLabel("Center Cpzt:"), 0, 0)
        self.analysis_pzt_center_capacitance_spin = QDoubleSpinBox()
        self.analysis_pzt_center_capacitance_spin.setRange(1e-9, 1e12)
        self.analysis_pzt_center_capacitance_spin.setDecimals(6)
        self.analysis_pzt_center_capacitance_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["center_capacitance_value"]))
        self.analysis_pzt_center_capacitance_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_center_capacitance_spin, 0, 1)
        self.analysis_pzt_capacitance_unit_combo = QComboBox()
        self.analysis_pzt_capacitance_unit_combo.addItems(list(PZT_FORCE_CAPACITANCE_UNITS))
        self.analysis_pzt_capacitance_unit_combo.setCurrentText(str(PZT_FORCE_DEFAULT_SETTINGS["capacitance_unit"]))
        self.analysis_pzt_capacitance_unit_combo.currentIndexChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_capacitance_unit_combo, 0, 2)

        pzt_force_layout.addWidget(QLabel("Outer Cpzt:"), 0, 3)
        self.analysis_pzt_outer_capacitance_spin = QDoubleSpinBox()
        self.analysis_pzt_outer_capacitance_spin.setRange(1e-9, 1e12)
        self.analysis_pzt_outer_capacitance_spin.setDecimals(6)
        self.analysis_pzt_outer_capacitance_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["outer_capacitance_value"]))
        self.analysis_pzt_outer_capacitance_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_outer_capacitance_spin, 0, 4)

        pzt_force_layout.addWidget(QLabel("Rleak:"), 1, 0)
        self.analysis_pzt_rleak_spin = QDoubleSpinBox()
        self.analysis_pzt_rleak_spin.setRange(1e-9, 1e15)
        self.analysis_pzt_rleak_spin.setDecimals(3)
        self.analysis_pzt_rleak_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["rleak_ohm"]))
        self.analysis_pzt_rleak_spin.setSuffix(" ohm")
        self.analysis_pzt_rleak_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_rleak_spin, 1, 1)

        pzt_force_layout.addWidget(QLabel("d33:"), 1, 2)
        self.analysis_pzt_d33_spin = QDoubleSpinBox()
        self.analysis_pzt_d33_spin.setRange(1e-9, 1e12)
        self.analysis_pzt_d33_spin.setDecimals(6)
        self.analysis_pzt_d33_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["d33_pc_per_n"]))
        self.analysis_pzt_d33_spin.setSuffix(" pC/N")
        self.analysis_pzt_d33_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_d33_spin, 1, 3)

        pzt_force_layout.addWidget(QLabel("Noise:"), 1, 4)
        self.analysis_pzt_noise_spin = QDoubleSpinBox()
        self.analysis_pzt_noise_spin.setRange(0.0, 1e6)
        self.analysis_pzt_noise_spin.setDecimals(6)
        self.analysis_pzt_noise_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["noise_threshold_v"]))
        self.analysis_pzt_noise_spin.setSuffix(" V")
        self.analysis_pzt_noise_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_noise_spin, 1, 5)

        pzt_force_layout.addWidget(QLabel("Quiet:"), 2, 0)
        self.analysis_pzt_quiet_duration_spin = QDoubleSpinBox()
        self.analysis_pzt_quiet_duration_spin.setRange(0.0, 3600.0)
        self.analysis_pzt_quiet_duration_spin.setDecimals(3)
        self.analysis_pzt_quiet_duration_spin.setSuffix(" s")
        self.analysis_pzt_quiet_duration_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["quiet_duration_s"]))
        self.analysis_pzt_quiet_duration_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_quiet_duration_spin, 2, 1)

        pzt_force_layout.addWidget(QLabel("k:"), 2, 2)
        self.analysis_pzt_noise_k_spin = QDoubleSpinBox()
        self.analysis_pzt_noise_k_spin.setRange(0.0, 100.0)
        self.analysis_pzt_noise_k_spin.setDecimals(3)
        self.analysis_pzt_noise_k_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["noise_sigma_multiplier"]))
        self.analysis_pzt_noise_k_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_noise_k_spin, 2, 3)

        self.analysis_pzt_calculate_baseline_btn = QPushButton("Calculate Vmid + Noise")
        self.analysis_pzt_calculate_baseline_btn.clicked.connect(self.calculate_analysis_pzt_baseline)
        pzt_force_layout.addWidget(self.analysis_pzt_calculate_baseline_btn, 2, 4)

        pzt_force_layout.addWidget(QLabel("MUX timing:"), 3, 0)
        self.analysis_pzt_mux_timing_combo = QComboBox()
        self.analysis_pzt_mux_timing_combo.addItems(list(PZT_FORCE_MUX_TIMING_MODES))
        self.analysis_pzt_mux_timing_combo.currentIndexChanged.connect(self.on_analysis_pzt_mux_timing_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_mux_timing_combo, 3, 1)

        pzt_force_layout.addWidget(QLabel("Connected:"), 3, 2)
        self.analysis_pzt_mux_connected_ms_spin = QDoubleSpinBox()
        self.analysis_pzt_mux_connected_ms_spin.setRange(0.001, 1e9)
        self.analysis_pzt_mux_connected_ms_spin.setDecimals(3)
        self.analysis_pzt_mux_connected_ms_spin.setSuffix(" ms")
        self.analysis_pzt_mux_connected_ms_spin.setValue(
            float(PZT_FORCE_DEFAULT_SETTINGS["mux_connected_time_s"]) * 1000.0
        )
        self.analysis_pzt_mux_connected_ms_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_mux_connected_ms_spin, 3, 3)

        self.analysis_pzt_off_mux_leak_check = QCheckBox("Off-MUX leak")
        self.analysis_pzt_off_mux_leak_check.stateChanged.connect(self.on_analysis_pzt_mux_timing_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_off_mux_leak_check, 4, 0)

        self.analysis_pzt_off_mux_rleak_spin = QDoubleSpinBox()
        self.analysis_pzt_off_mux_rleak_spin.setRange(1e-9, 1e18)
        self.analysis_pzt_off_mux_rleak_spin.setDecimals(3)
        self.analysis_pzt_off_mux_rleak_spin.setSuffix(" ohm")
        self.analysis_pzt_off_mux_rleak_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["rleak_ohm"]))
        self.analysis_pzt_off_mux_rleak_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_off_mux_rleak_spin, 4, 1)

        self.analysis_pzt_mux_timing_status = QLabel("")
        self.analysis_pzt_mux_timing_status.setStyleSheet("QLabel { color: #555555; }")
        pzt_force_layout.addWidget(self.analysis_pzt_mux_timing_status, 4, 2, 1, 3)

        self.analysis_export_csv_btn = QPushButton("Export Analysis CSV")
        self.analysis_export_csv_btn.clicked.connect(self.export_analysis_csv)
        pzt_force_layout.addWidget(self.analysis_export_csv_btn, 5, 4)
        self.analysis_pzt_baseline_results = QPlainTextEdit()
        self.analysis_pzt_baseline_results.setReadOnly(True)
        self.analysis_pzt_baseline_results.setMaximumHeight(160)
        pzt_force_layout.addWidget(self.analysis_pzt_baseline_results, 5, 0, 1, 4)

        self.analysis_pzt_stuck_failsafe_check = QCheckBox("Auto-clear stuck force")
        self.analysis_pzt_stuck_failsafe_check.setChecked(bool(PZT_FORCE_DEFAULT_SETTINGS["stuck_force_failsafe_enabled"]))
        self.analysis_pzt_stuck_failsafe_check.setToolTip(
            "A normal press/release already returns to exactly zero once a channel goes "
            "below the Force noise threshold. This only covers a channel that never "
            "fully quiets down (e.g. baseline drift, or a held press whose voltage has "
            "decayed below the threshold): its residual force decays smoothly to zero "
            "after the hold time below. Disable to keep such a residual until the next "
            "event or a manual reset."
        )
        self.analysis_pzt_stuck_failsafe_check.stateChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_stuck_failsafe_check, 6, 0)
        self.analysis_pzt_stuck_hold_spin = QDoubleSpinBox()
        self.analysis_pzt_stuck_hold_spin.setRange(0.0, 3600.0)
        self.analysis_pzt_stuck_hold_spin.setDecimals(3)
        self.analysis_pzt_stuck_hold_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["stuck_force_quiet_hold_s"]))
        self.analysis_pzt_stuck_hold_spin.setSuffix(" s after quiet")
        self.analysis_pzt_stuck_hold_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_stuck_hold_spin, 6, 1)
        self.analysis_pzt_stuck_tau_spin = QDoubleSpinBox()
        self.analysis_pzt_stuck_tau_spin.setRange(0.0, 3600.0)
        self.analysis_pzt_stuck_tau_spin.setDecimals(3)
        self.analysis_pzt_stuck_tau_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["stuck_force_decay_tau_s"]))
        self.analysis_pzt_stuck_tau_spin.setSuffix(" s decay tau")
        self.analysis_pzt_stuck_tau_spin.setToolTip("0 = instant reset instead of a smooth decay.")
        self.analysis_pzt_stuck_tau_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_stuck_tau_spin, 6, 2)
        self.analysis_pzt_stuck_failsafe_check.toggled.connect(self.analysis_pzt_stuck_hold_spin.setEnabled)
        self.analysis_pzt_stuck_failsafe_check.toggled.connect(self.analysis_pzt_stuck_tau_spin.setEnabled)
        self.analysis_pzt_stuck_hold_spin.setEnabled(self.analysis_pzt_stuck_failsafe_check.isChecked())
        self.analysis_pzt_stuck_tau_spin.setEnabled(self.analysis_pzt_stuck_failsafe_check.isChecked())

        pzt_force_layout.addWidget(QLabel("Zero floor:"), 7, 0)
        self.analysis_pzt_zero_floor_spin = QDoubleSpinBox()
        self.analysis_pzt_zero_floor_spin.setRange(0.0, 1e6)
        self.analysis_pzt_zero_floor_spin.setDecimals(4)
        self.analysis_pzt_zero_floor_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_min_n"]))
        self.analysis_pzt_zero_floor_spin.setSuffix(" N")
        self.analysis_pzt_zero_floor_spin.setToolTip(
            "Absolute floor (N) for the natural-zero band and the fail-safe snap band. A "
            "residual at or below this magnitude is treated as fully released."
        )
        self.analysis_pzt_zero_floor_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_zero_floor_spin, 7, 1)

        pzt_force_layout.addWidget(QLabel("Zero band:"), 7, 2)
        self.analysis_pzt_zero_band_fraction_spin = QDoubleSpinBox()
        self.analysis_pzt_zero_band_fraction_spin.setRange(0.0, 1.0)
        self.analysis_pzt_zero_band_fraction_spin.setDecimals(3)
        self.analysis_pzt_zero_band_fraction_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_fraction"]))
        self.analysis_pzt_zero_band_fraction_spin.setSuffix(" x peak")
        self.analysis_pzt_zero_band_fraction_spin.setToolTip(
            "Natural-zero band as a fraction of the current press's own peak force. The "
            "event ends once the force declines back inside this band around zero."
        )
        self.analysis_pzt_zero_band_fraction_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_zero_band_fraction_spin, 7, 3)

        pzt_force_layout.addWidget(QLabel("Min event peak:"), 7, 4)
        self.analysis_pzt_min_event_peak_spin = QDoubleSpinBox()
        self.analysis_pzt_min_event_peak_spin.setRange(0.0, 1e6)
        self.analysis_pzt_min_event_peak_spin.setDecimals(4)
        self.analysis_pzt_min_event_peak_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_min_event_peak_n"]))
        self.analysis_pzt_min_event_peak_spin.setSuffix(" N")
        self.analysis_pzt_min_event_peak_spin.setToolTip(
            "A press whose own peak force never reaches this magnitude is too small to "
            "distinguish 'declined' from 'held', so it is released unconditionally as soon "
            "as it goes quiet instead of waiting for the natural-zero/quiet-release check."
        )
        self.analysis_pzt_min_event_peak_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_min_event_peak_spin, 7, 5)

        pzt_force_layout.addWidget(QLabel("Quiet release:"), 8, 0)
        self.analysis_pzt_quiet_release_spin = QDoubleSpinBox()
        self.analysis_pzt_quiet_release_spin.setRange(0.0, 1.0)
        self.analysis_pzt_quiet_release_spin.setDecimals(3)
        self.analysis_pzt_quiet_release_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_release_fraction"]))
        self.analysis_pzt_quiet_release_spin.setSuffix(" x peak")
        self.analysis_pzt_quiet_release_spin.setToolTip(
            "At quiet-hold expiry, the residual must have declined to within this fraction "
            "of the press's own peak before it is released; otherwise it is presumed a held "
            "press whose voltage merely decayed quiet, left open for the stuck-force "
            "fail-safe above to eventually resolve."
        )
        self.analysis_pzt_quiet_release_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_quiet_release_spin, 8, 1)

        pzt_force_layout.addWidget(QLabel("Quiet hold:"), 8, 2)
        self.analysis_pzt_quiet_hold_spin = QDoubleSpinBox()
        self.analysis_pzt_quiet_hold_spin.setRange(0.0, 3600.0)
        self.analysis_pzt_quiet_hold_spin.setDecimals(3)
        self.analysis_pzt_quiet_hold_spin.setValue(float(PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_clear_s"]))
        self.analysis_pzt_quiet_hold_spin.setSuffix(" s")
        self.analysis_pzt_quiet_hold_spin.setToolTip(
            "How long a channel must stay continuously quiet (below the Noise threshold) "
            "before its event is considered concluded and eligible for release."
        )
        self.analysis_pzt_quiet_hold_spin.valueChanged.connect(self.on_analysis_settings_changed)
        pzt_force_layout.addWidget(self.analysis_pzt_quiet_hold_spin, 8, 3)

        settings_root.addWidget(pzt_force_group)

        zoom_group = QGroupBox("Zoom")
        zoom_layout = QHBoxLayout(zoom_group)
        zoom_layout.addWidget(QLabel("Mouse zoom axis:"))
        self.analysis_zoom_combo = QComboBox()
        self.analysis_zoom_combo.addItems(["X only", "Y only", "X and Y"])
        self.analysis_zoom_combo.currentIndexChanged.connect(self.on_analysis_zoom_changed)
        self.analysis_zoom_combo.setMaximumWidth(180)
        zoom_layout.addWidget(self.analysis_zoom_combo)
        zoom_layout.addStretch()
        settings_root.addWidget(zoom_group)

        image_export_group = QGroupBox("Analysis Image Export")
        image_export_layout = QGridLayout(image_export_group)
        self.analysis_save_raw_image_check = QCheckBox("Raw signals")
        self.analysis_save_raw_image_check.setChecked(True)
        image_export_layout.addWidget(self.analysis_save_raw_image_check, 0, 0)
        self.analysis_save_integration_image_check = QCheckBox("Integrated signals")
        self.analysis_save_integration_image_check.setChecked(True)
        image_export_layout.addWidget(self.analysis_save_integration_image_check, 0, 1)
        self.analysis_save_derived_image_check = QCheckBox("Shear / Normal")
        self.analysis_save_derived_image_check.setChecked(True)
        image_export_layout.addWidget(self.analysis_save_derived_image_check, 0, 2)
        self.analysis_save_force_image_check = QCheckBox("Force")
        self.analysis_save_force_image_check.setChecked(True)
        image_export_layout.addWidget(self.analysis_save_force_image_check, 0, 3)
        self.analysis_save_images_btn = QPushButton("Save Selected Images")
        self.analysis_save_images_btn.clicked.connect(self.save_analysis_plot_images)
        image_export_layout.addWidget(self.analysis_save_images_btn, 1, 0, 1, 4)
        settings_root.addWidget(image_export_group)
        settings_root.addStretch()

        self.analysis_plot_splitter = QSplitter(Qt.Orientation.Vertical)
        self.analysis_signal_plot = pg.PlotWidget()
        self.analysis_signal_plot.setBackground("w")
        self.analysis_signal_plot.showGrid(x=True, y=True, alpha=0.3)
        self.analysis_signal_plot.addLegend(offset=(10, 10))
        self.analysis_integration_plot = pg.PlotWidget()
        self.analysis_integration_plot.setBackground("w")
        self.analysis_integration_plot.showGrid(x=True, y=True, alpha=0.3)
        self.analysis_integration_plot.addLegend(offset=(10, 10))
        self.analysis_derived_plot = pg.PlotWidget()
        self.analysis_derived_plot.setBackground("w")
        self.analysis_derived_plot.showGrid(x=True, y=True, alpha=0.3)
        self.analysis_derived_plot.addLegend(offset=(10, 10))
        self.analysis_force_plot = pg.PlotWidget()
        self.analysis_force_plot.setBackground("w")
        self.analysis_signal_plot.setMinimumHeight(250)
        self.analysis_integration_plot.setMinimumHeight(200)
        self.analysis_derived_plot.setMinimumHeight(200)
        self.analysis_force_plot.setMinimumHeight(100)
        self.analysis_force_plot.showGrid(x=True, y=True, alpha=0.3)
        self.analysis_force_plot.addLegend(offset=(10, 10))
        self.analysis_integration_plot.setXLink(self.analysis_signal_plot)
        self.analysis_derived_plot.setXLink(self.analysis_signal_plot)
        self.analysis_force_plot.setXLink(self.analysis_signal_plot)
        self.analysis_plot_splitter.addWidget(self.analysis_signal_plot)
        self.analysis_plot_splitter.addWidget(self.analysis_integration_plot)
        self.analysis_plot_splitter.addWidget(self.analysis_derived_plot)
        self.analysis_plot_splitter.addWidget(self.analysis_force_plot)
        self.analysis_plot_splitter.setStretchFactor(0, 5)
        self.analysis_plot_splitter.setStretchFactor(1, 4)
        self.analysis_plot_splitter.setStretchFactor(2, 4)
        self.analysis_plot_splitter.setStretchFactor(3, 2)
        display_root.addWidget(self.analysis_plot_splitter)
        self._update_analysis_plot_visibility(
            show_signal=False,
            show_integration=False,
            show_derived=False,
            show_force=False,
        )

        self.analysis_marker_vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#444444", width=1))
        self.analysis_signal_plot.addItem(self.analysis_marker_vline)
        self.analysis_marker_vline.setVisible(False)
        self.analysis_mouse_proxy = pg.SignalProxy(
            self.analysis_signal_plot.scene().sigMouseMoved,
            rateLimit=30,
            slot=self._on_analysis_mouse_moved,
        )
        self._analysis_marker_timer.timeout.connect(self._flush_analysis_marker_readout)

        self.analysis_status_label = QLabel("Analysis: no source loaded")
        self.analysis_status_label.setStyleSheet("font-family: monospace;")
        self.analysis_status_label.setMinimumWidth(0)
        self.analysis_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.analysis_status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        display_root.addWidget(self.analysis_status_label)

        self._apply_analysis_settings_to_widgets()
        self.update_analysis_availability()
        self.on_analysis_source_changed()
        return tab

    def _apply_analysis_settings_to_widgets(self):
        if not hasattr(self, "analysis_source_combo"):
            return
        # Applying settings drives ~15 widgets whose change handlers each
        # persist the whole file; suppress those writes until every widget
        # has been updated.
        self._analysis_settings_loading = True
        try:
            state = self.analysis_state
            self.analysis_source_combo.setCurrentIndex(1 if state.get("source_mode") == "csv_json" else 0)
            self.analysis_axis_combo.setCurrentIndex(1 if state.get("axis_mode") == "samples" else 0)
            self.analysis_zoom_combo.setCurrentIndex({"x": 0, "y": 1, "xy": 2}.get(state.get("zoom_mode", "x"), 0))
            self.analysis_filter_check.setChecked(bool(state.get("filter_enabled", False)))
            self.analysis_marker_check.setChecked(bool(state.get("marker_enabled", True)))
            overlays = state.get("overlays", {})
            self.analysis_shear_check.setChecked(bool(overlays.get("shear", False)))
            self.analysis_normal_check.setChecked(bool(overlays.get("normal", False)))
            self.analysis_integration_check.setChecked(bool(overlays.get("integration", False)))
            pzt_force = state.get("pzt_force", {})
            self.analysis_pzt_force_check.setChecked(bool(pzt_force.get("enabled", False)))
            legacy_capacitance = pzt_force.get("capacitance_value", PZT_FORCE_DEFAULT_SETTINGS["capacitance_value"])
            self.analysis_pzt_center_capacitance_spin.setValue(float(pzt_force.get("center_capacitance_value", legacy_capacitance)))
            self.analysis_pzt_outer_capacitance_spin.setValue(float(pzt_force.get("outer_capacitance_value", legacy_capacitance)))
            self.analysis_pzt_capacitance_unit_combo.setCurrentText(str(pzt_force.get("capacitance_unit", PZT_FORCE_DEFAULT_SETTINGS["capacitance_unit"])))
            self.analysis_pzt_rleak_spin.setValue(float(pzt_force.get("rleak_ohm", PZT_FORCE_DEFAULT_SETTINGS["rleak_ohm"])))
            self.analysis_pzt_d33_spin.setValue(float(pzt_force.get("d33_pc_per_n", PZT_FORCE_DEFAULT_SETTINGS["d33_pc_per_n"])))
            self.analysis_pzt_noise_spin.setValue(float(pzt_force.get("noise_threshold_v", PZT_FORCE_DEFAULT_SETTINGS["noise_threshold_v"])))
            self.analysis_pzt_quiet_duration_spin.setValue(float(pzt_force.get("quiet_duration_s", PZT_FORCE_DEFAULT_SETTINGS["quiet_duration_s"])))
            self.analysis_pzt_noise_k_spin.setValue(float(pzt_force.get("noise_sigma_multiplier", PZT_FORCE_DEFAULT_SETTINGS["noise_sigma_multiplier"])))
            self._set_analysis_pzt_mux_timing_mode(str(pzt_force.get("mux_timing_mode", PZT_FORCE_DEFAULT_SETTINGS["mux_timing_mode"])))
            self.analysis_pzt_mux_connected_ms_spin.setValue(
                float(pzt_force.get("mux_connected_time_s", PZT_FORCE_DEFAULT_SETTINGS["mux_connected_time_s"])) * 1000.0
            )
            self.analysis_pzt_off_mux_leak_check.setChecked(bool(pzt_force.get("off_mux_leak_enabled", False)))
            off_mux_rleak = pzt_force.get("off_mux_rleak_ohm", PZT_FORCE_DEFAULT_SETTINGS["off_mux_rleak_ohm"])
            if off_mux_rleak not in (None, ""):
                self.analysis_pzt_off_mux_rleak_spin.setValue(float(off_mux_rleak))
            self.analysis_pzt_stuck_failsafe_check.setChecked(
                bool(pzt_force.get("stuck_force_failsafe_enabled", PZT_FORCE_DEFAULT_SETTINGS["stuck_force_failsafe_enabled"]))
            )
            self.analysis_pzt_stuck_hold_spin.setValue(
                float(pzt_force.get("stuck_force_quiet_hold_s", PZT_FORCE_DEFAULT_SETTINGS["stuck_force_quiet_hold_s"]))
            )
            self.analysis_pzt_stuck_tau_spin.setValue(
                float(pzt_force.get("stuck_force_decay_tau_s", PZT_FORCE_DEFAULT_SETTINGS["stuck_force_decay_tau_s"]))
            )
            self.analysis_pzt_zero_floor_spin.setValue(
                float(pzt_force.get("force_zero_band_min_n", PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_min_n"]))
            )
            self.analysis_pzt_zero_band_fraction_spin.setValue(
                float(pzt_force.get("force_zero_band_fraction", PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_fraction"]))
            )
            self.analysis_pzt_min_event_peak_spin.setValue(
                float(pzt_force.get("force_zero_min_event_peak_n", PZT_FORCE_DEFAULT_SETTINGS["force_zero_min_event_peak_n"]))
            )
            self.analysis_pzt_quiet_release_spin.setValue(
                float(pzt_force.get("quiet_hold_release_fraction", PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_release_fraction"]))
            )
            self.analysis_pzt_quiet_hold_spin.setValue(
                float(pzt_force.get("quiet_hold_clear_s", PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_clear_s"]))
            )
            self._update_analysis_pzt_mux_timing_controls()
            self._update_analysis_pzt_baseline_results()
            self.analysis_csv_path_edit.setText(str(state.get("csv_path", "")))
            self.on_analysis_zoom_changed()
        finally:
            self._analysis_settings_loading = False

    def on_analysis_source_changed(self):
        csv_mode = self.analysis_source_combo.currentIndex() == 1
        self.analysis_state["source_mode"] = "csv_json" if csv_mode else "in_memory"
        capturing = bool(getattr(self, "is_capturing", False))
        for widget in (self.analysis_csv_path_edit, self.analysis_browse_csv_btn):
            widget.setEnabled(csv_mode and not capturing)
        self.analysis_load_btn.setEnabled(
            not capturing and (csv_mode or self._analysis_has_in_memory_capture())
        )
        self.save_last_analysis_settings()

    def on_analysis_pzt_mux_timing_changed(self, *_args):
        self._update_analysis_pzt_mux_timing_controls()
        self.on_analysis_settings_changed()

    def _set_analysis_pzt_mux_timing_mode(self, mode: str):
        normalized = str(mode or "auto").strip().lower().replace("-", "_").replace(" ", "_")
        label_by_mode = {
            "auto": "Auto",
            "manual": "Manual",
            "infer": "Infer from total sample rate",
            "infer_from_rate": "Infer from total sample rate",
            "infer_from_sample_rate": "Infer from total sample rate",
            "infer_from_total_sample_rate": "Infer from total sample rate",
            "continuous": "Continuous",
            "continuous_leak": "Continuous",
        }
        self.analysis_pzt_mux_timing_combo.setCurrentText(label_by_mode.get(normalized, "Auto"))

    def _analysis_pzt_mux_timing_mode(self) -> str:
        text = str(self.analysis_pzt_mux_timing_combo.currentText()).strip().lower()
        if text.startswith("manual"):
            return "manual"
        if text.startswith("infer"):
            return "infer_from_total_sample_rate"
        if text.startswith("continuous"):
            return "continuous"
        return "auto"

    def _update_analysis_pzt_mux_timing_controls(self):
        if not hasattr(self, "analysis_pzt_mux_connected_ms_spin"):
            return
        mode = self._analysis_pzt_mux_timing_mode()
        manual = mode == "manual"
        off_mux_enabled = bool(self.analysis_pzt_off_mux_leak_check.isChecked())
        self.analysis_pzt_mux_connected_ms_spin.setVisible(manual)
        self.analysis_pzt_off_mux_rleak_spin.setEnabled(off_mux_enabled)
        if mode == "continuous":
            text = "Continuous leak uses full sample-to-sample dt."
        elif mode == "manual":
            text = f"Manual leak exposure {self.analysis_pzt_mux_connected_ms_spin.value():.3f} ms."
        elif mode == "infer_from_total_sample_rate":
            text = "Infers leak exposure as 1 / total sample rate."
        else:
            text = "Auto uses live timing, sidecar avg_dt_us, or metadata timing."
        self.analysis_pzt_mux_timing_status.setText(text)

    @staticmethod
    def _analysis_metadata_path_for_csv(csv_path: str) -> str:
        """Convention: `<csv_stem>_metadata.json` next to the CSV."""
        candidate = Path(csv_path).with_name(Path(csv_path).stem + "_metadata.json")
        return str(candidate) if candidate.exists() else ""

    def on_analysis_browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Analysis CSV",
            self._analysis_file_dialog_start_dir(),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        self.analysis_csv_path_edit.setText(path)
        metadata_path = self._analysis_metadata_path_for_csv(path)
        self.analysis_state["metadata_path"] = metadata_path
        if not metadata_path:
            self._set_analysis_status_text(
                f"Analysis: no matching *_metadata.json found next to {Path(path).name}."
            )

    def _analysis_file_dialog_start_dir(self) -> str:
        candidates = (
            self.analysis_csv_path_edit.text().strip(),
            str(self.analysis_state.get("csv_path", "")),
        )
        for candidate in candidates:
            if not candidate:
                continue
            candidate_path = Path(candidate).expanduser()
            if candidate_path.is_file():
                return str(candidate_path.parent)
            if candidate_path.is_dir():
                return str(candidate_path)

        export_dir = getattr(self, "dir_input", None)
        if export_dir is not None:
            export_text = export_dir.text().strip()
            if export_text:
                export_path = Path(export_text).expanduser()
                if export_path.is_dir():
                    return str(export_path)
        return str(Path.cwd())

    def load_analysis_source(self):
        if getattr(self, "is_capturing", False):
            self.update_analysis_availability()
            return
        try:
            if self.analysis_source_combo.currentIndex() == 1:
                csv_path = self.analysis_csv_path_edit.text().strip()
                if not csv_path:
                    self._set_analysis_status_text("Analysis: browse to a CSV file first.")
                    return
                metadata_path = self._analysis_metadata_path_for_csv(csv_path)
                if not metadata_path:
                    self._set_analysis_status_text(
                        f"Analysis: no matching *_metadata.json found next to {Path(csv_path).name}."
                    )
                    return
                self.analysis_state["csv_path"] = csv_path
                self.analysis_state["metadata_path"] = metadata_path
                self.analysis_snapshot = load_exported_csv_snapshot(csv_path, metadata_path)
            else:
                buffer_overflowed = (
                    hasattr(self, '_capture_exceeds_memory_buffer')
                    and self._capture_exceeds_memory_buffer()
                    and getattr(self, '_archive_path', None)
                )
                if buffer_overflowed:
                    self.analysis_snapshot = build_snapshot_from_archive(self)
                else:
                    self.analysis_snapshot = build_in_memory_snapshot(self)
            self._rebuild_analysis_channel_checks()
            self._analysis_pending_auto_range = True
            self._analysis_loaded_status = (
                f"Analysis loaded: {self.analysis_snapshot.sweep_count} sweeps, "
                f"{self.analysis_snapshot.samples_per_sweep} signal columns"
            )
            self.refresh_analysis_plot()
            if hasattr(self, "log_status"):
                self.log_status(self._analysis_loaded_status)
            self.save_last_analysis_settings()
        except Exception as exc:
            self._set_analysis_status_text(f"Analysis load failed: {exc}")
            if hasattr(self, "log_status"):
                self.log_status(f"Analysis load failed: {exc}")
            QMessageBox.warning(self, "Analysis Load Failed", str(exc))

    def _rebuild_analysis_channel_checks(self):
        for check in self.analysis_channel_checks.values():
            check.deleteLater()
        self.analysis_channel_checks = {}
        snapshot = self.analysis_snapshot
        if snapshot is not None:
            saved_visibility = self.analysis_state.get("visible_labels", {})
            for label in snapshot.channel_labels:
                check = QCheckBox(label)
                check.setChecked(bool(saved_visibility.get(label, True)))
                check.stateChanged.connect(self.on_analysis_settings_changed)
                self.analysis_channel_checks[label] = check
        self._relayout_analysis_checkboxes()

    def _analysis_checkbox_column_count(self) -> int:
        width = self.analysis_channel_container.width() or self._analysis_checkbox_scroll.viewport().width()
        return max(1, int(width) // ANALYSIS_CHECKBOX_MIN_COLUMN_WIDTH)

    def _relayout_analysis_checkboxes(self):
        """Re-flow channel then force checkboxes into as few rows as fit the container width."""
        layout = self.analysis_channel_layout
        while layout.count():
            layout.takeAt(0)
        columns = self._analysis_checkbox_column_count()
        checks = list(self.analysis_channel_checks.values()) + list(self.analysis_force_checks.values())
        for index, check in enumerate(checks):
            layout.addWidget(check, index // columns, index % columns)

    def eventFilter(self, obj, event):
        checkbox_scroll = getattr(self, "_analysis_checkbox_scroll", None)
        is_checkbox_resize = (
            checkbox_scroll is not None
            and obj is checkbox_scroll.viewport()
            and event.type() == QEvent.Type.Resize
        )
        if is_checkbox_resize:
            self._relayout_analysis_checkboxes()
        return False

    def set_all_analysis_channels(self, checked: bool):
        for check in self.analysis_channel_checks.values():
            check.setChecked(bool(checked))
        self.on_analysis_settings_changed()

    def on_analysis_settings_changed(self, *_args):
        if not hasattr(self, "analysis_axis_combo"):
            return
        self.analysis_state["axis_mode"] = "samples" if self.analysis_axis_combo.currentIndex() == 1 else "time_ms"
        self.analysis_state["filter_enabled"] = bool(self.analysis_filter_check.isChecked())
        self.analysis_state["marker_enabled"] = bool(self.analysis_marker_check.isChecked())
        self.analysis_state["overlays"] = {
            "shear": bool(self.analysis_shear_check.isChecked()),
            "normal": bool(self.analysis_normal_check.isChecked()),
            "integration": bool(self.analysis_integration_check.isChecked()),
        }
        self.analysis_state["pzt_force"] = {
            "enabled": bool(self.analysis_pzt_force_check.isChecked()),
            "center_capacitance_value": float(self.analysis_pzt_center_capacitance_spin.value()),
            "outer_capacitance_value": float(self.analysis_pzt_outer_capacitance_spin.value()),
            "capacitance_unit": str(self.analysis_pzt_capacitance_unit_combo.currentText()),
            "rleak_ohm": float(self.analysis_pzt_rleak_spin.value()),
            "d33_pc_per_n": float(self.analysis_pzt_d33_spin.value()),
            "noise_threshold_v": float(self.analysis_pzt_noise_spin.value()),
            "quiet_duration_s": float(self.analysis_pzt_quiet_duration_spin.value()),
            "noise_sigma_multiplier": float(self.analysis_pzt_noise_k_spin.value()),
            "mux_timing_mode": self._analysis_pzt_mux_timing_mode(),
            "mux_connected_time_s": float(self.analysis_pzt_mux_connected_ms_spin.value()) / 1000.0,
            "mux_connected_time_source": str(self.analysis_pzt_mux_timing_status.text()),
            "off_mux_leak_enabled": bool(self.analysis_pzt_off_mux_leak_check.isChecked()),
            "off_mux_rleak_ohm": (
                float(self.analysis_pzt_off_mux_rleak_spin.value())
                if self.analysis_pzt_off_mux_leak_check.isChecked()
                else None
            ),
            "stuck_force_failsafe_enabled": bool(self.analysis_pzt_stuck_failsafe_check.isChecked()),
            "stuck_force_quiet_hold_s": float(self.analysis_pzt_stuck_hold_spin.value()),
            "stuck_force_decay_tau_s": float(self.analysis_pzt_stuck_tau_spin.value()),
            "force_zero_band_min_n": float(self.analysis_pzt_zero_floor_spin.value()),
            "force_zero_band_fraction": float(self.analysis_pzt_zero_band_fraction_spin.value()),
            "force_zero_min_event_peak_n": float(self.analysis_pzt_min_event_peak_spin.value()),
            "quiet_hold_release_fraction": float(self.analysis_pzt_quiet_release_spin.value()),
            "quiet_hold_clear_s": float(self.analysis_pzt_quiet_hold_spin.value()),
            "channel_calibration": dict(self.analysis_state.get("pzt_force", {}).get("channel_calibration", {})),
        }
        self.analysis_state["visible_labels"] = {
            label: bool(check.isChecked())
            for label, check in self.analysis_channel_checks.items()
        }
        self.analysis_state["visible_force_labels"] = {
            label: bool(check.isChecked())
            for label, check in self.analysis_force_checks.items()
        }
        self.refresh_analysis_plot()
        self.save_last_analysis_settings()

    def calculate_analysis_pzt_baseline(self):
        snapshot = self.analysis_snapshot
        if snapshot is None:
            QMessageBox.warning(self, "PZT Baseline", "Load an Analysis source before calculating Vmid and noise.")
            return
        visible_labels = [
            label for label, check in self.analysis_channel_checks.items()
            if check.isChecked()
        ]
        filter_settings = self.get_filter_settings_from_ui() if hasattr(self, "get_filter_settings_from_ui") else {}
        try:
            estimates = estimate_analysis_pzt_force_calibration(
                snapshot,
                visible_labels=visible_labels,
                filter_enabled=bool(self.analysis_filter_check.isChecked()),
                filter_settings=filter_settings,
                vref_voltage=self.get_vref_voltage() if hasattr(self, "get_vref_voltage") else 3.3,
                quiet_duration_s=float(self.analysis_pzt_quiet_duration_spin.value()),
                noise_sigma_multiplier=float(self.analysis_pzt_noise_k_spin.value()),
            )
            pzt_force = dict(self.analysis_state.get("pzt_force", {}))
            pzt_force["channel_calibration"] = estimates
            pzt_force["quiet_duration_s"] = float(self.analysis_pzt_quiet_duration_spin.value())
            pzt_force["noise_sigma_multiplier"] = float(self.analysis_pzt_noise_k_spin.value())
            self.analysis_state["pzt_force"] = pzt_force
            self._update_analysis_pzt_baseline_results()
            self.refresh_analysis_plot()
            self.save_last_analysis_settings()
            self._set_analysis_status_text(f"PZT baseline calculated for {len(estimates)} channels.")
        except Exception as exc:
            QMessageBox.warning(self, "PZT Baseline Failed", str(exc))
            self._set_analysis_status_text(f"PZT baseline failed: {exc}")

    def _update_analysis_pzt_baseline_results(self):
        if not hasattr(self, "analysis_pzt_baseline_results"):
            return
        calibration = self.analysis_state.get("pzt_force", {}).get("channel_calibration", {})
        if not isinstance(calibration, dict) or not calibration:
            self.analysis_pzt_baseline_results.setPlainText("")
            return
        lines = []
        for label in sorted(calibration):
            values = calibration.get(label, {})
            if not isinstance(values, dict):
                continue
            lines.append(
                f"{label}: Vmid={float(values.get('vmid_v', 0.0)):.4f} V, "
                f"Noise={float(values.get('noise_threshold_v', 0.0)):.4f} V, "
                f"sigma={float(values.get('sigma_v', 0.0)):.4f} V, "
                f"n={int(values.get('sample_count', 0))}"
            )
        self.analysis_pzt_baseline_results.setPlainText("\n".join(lines))

    def on_analysis_zoom_changed(self, *_args):
        mode = ["x", "y", "xy"][self.analysis_zoom_combo.currentIndex()]
        self.analysis_state["zoom_mode"] = mode
        mouse_x = mode in ("x", "xy")
        mouse_y = mode in ("y", "xy")
        if hasattr(self, "analysis_signal_plot"):
            self.analysis_signal_plot.setMouseEnabled(x=mouse_x, y=mouse_y)
            self.analysis_integration_plot.setMouseEnabled(x=mouse_x, y=mouse_y)
            self.analysis_derived_plot.setMouseEnabled(x=mouse_x, y=mouse_y)
            self.analysis_force_plot.setMouseEnabled(x=mouse_x, y=mouse_y)
        self.save_last_analysis_settings()

    def on_analysis_marker_toggled(self, *_args):
        enabled = bool(self.analysis_marker_check.isChecked())
        self.analysis_state["marker_enabled"] = enabled
        if hasattr(self, "analysis_marker_vline"):
            self.analysis_marker_vline.setVisible(enabled and self.analysis_prepared is not None)
        self.save_last_analysis_settings()

    def refresh_analysis_plot(self):
        snapshot = self.analysis_snapshot
        if snapshot is None or not hasattr(self, "analysis_signal_plot"):
            return
        visible_labels = [
            label for label, check in self.analysis_channel_checks.items()
            if check.isChecked()
        ]
        filter_settings = self.get_filter_settings_from_ui() if hasattr(self, "get_filter_settings_from_ui") else {}
        self._analysis_generation += 1
        self._analysis_load_state = AnalysisLoadState.LOADING
        self._set_analysis_status_text("Analysis: preparing plot...")
        self.analysis_compute_worker.submit({
            "generation": self._analysis_generation,
            "snapshot": snapshot,
            "axis_mode": self.analysis_state.get("axis_mode", "time_ms"),
            "visible_labels": visible_labels,
            "filter_enabled": bool(self.analysis_filter_check.isChecked()),
            "filter_settings": filter_settings,
            "overlay_flags": self.analysis_state.get("overlays", {}),
            "vref_voltage": self.get_vref_voltage() if hasattr(self, "get_vref_voltage") else 3.3,
            "integration_window_samples": int(getattr(self, "signal_integration_window_samples", 1) or 1),
            "hpf_cutoff_hz": float(getattr(self, "signal_integration_hpf_cutoff_hz", 0.0) or 0.0),
            "pzt_force_settings": self.analysis_state.get("pzt_force", {}),
            "auto_range": getattr(self, "_analysis_pending_auto_range", False),
        })
        self._analysis_pending_auto_range = False

    def _on_analysis_compute_result(self, payload: dict):
        if int(payload.get("generation", -1)) != self._analysis_generation:
            return
        self.analysis_prepared = payload["prepared"]
        self._analysis_load_state = AnalysisLoadState.READY
        self._sync_analysis_force_trace_checks(self.analysis_prepared.force_traces)
        self._render_analysis_prepared(auto_range=bool(payload.get("auto_range", False)))
        self._set_analysis_status_text(self._analysis_loaded_status or "Analysis: plot ready.")

    def _on_analysis_compute_error(self, generation: int, message: str):
        if int(generation) != self._analysis_generation:
            return
        self._analysis_load_state = AnalysisLoadState.ERROR
        self._set_analysis_status_text(f"Analysis prepare failed: {message}")
        if hasattr(self, "log_status"):
            self.log_status(f"Analysis prepare failed: {message}")

    def _apply_analysis_curve_pen(self, group, key, curve, color):
        """Reassign the curve pen only when its colour actually changed."""
        cache_key = (group, key)
        if self._analysis_pen_colors.get(cache_key) == color:
            return
        curve.setPen(pg.mkPen(color=color, width=2))
        self._analysis_pen_colors[cache_key] = color

    def _upsert_analysis_curve(self, group, store, plot, key, color, trace, visible=True):
        """Create or update one analysis curve and return it."""
        curve = store.get(key)
        if curve is None:
            curve = plot.plot([], [], pen=pg.mkPen(color=color, width=2), name=key)
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method="peak")
            store[key] = curve
            self._analysis_pen_colors[(group, key)] = color
        curve.setData(trace.x, trace.y)
        self._apply_analysis_curve_pen(group, key, curve, color)
        curve.setVisible(visible)
        return curve

    ANALYSIS_STARTUP_EXCLUDE_SECONDS = 5.0

    def _analysis_startup_exclude_threshold_x(self, prepared: AnalysisPreparedData) -> float:
        """X value marking the end of the startup window (shear needs a warm-up baseline)."""
        if prepared.x_units == "s":
            return self.ANALYSIS_STARTUP_EXCLUDE_SECONDS
        snapshot = self.analysis_snapshot
        sample_rate_hz = float(snapshot.sample_rate_hz) if snapshot is not None else 0.0
        if sample_rate_hz > 0:
            return self.ANALYSIS_STARTUP_EXCLUDE_SECONDS * sample_rate_hz
        return 0.0

    @staticmethod
    def _analysis_y_bounds_excluding_startup(traces, threshold_x: float) -> tuple[float, float] | None:
        """Min/max y across traces, preferring samples at or past threshold_x."""
        y_min = None
        y_max = None
        for trace in traces:
            if trace.x.size == 0 or trace.y.size == 0:
                continue
            mask = trace.x >= threshold_x
            y = trace.y[mask] if np.any(mask) else trace.y
            if y.size == 0:
                continue
            trace_min = float(np.min(y))
            trace_max = float(np.max(y))
            y_min = trace_min if y_min is None else min(y_min, trace_min)
            y_max = trace_max if y_max is None else max(y_max, trace_max)
        return None if y_min is None else (y_min, y_max)

    def _auto_range_analysis_plot(self, plot, traces, threshold_x: float):
        """Auto-fit X normally; auto-fit Y from data at/after the startup window."""
        plot.enableAutoRange(axis=pg.ViewBox.XAxis)
        bounds = self._analysis_y_bounds_excluding_startup(traces, threshold_x)
        if bounds is None:
            plot.enableAutoRange(axis=pg.ViewBox.YAxis)
            return
        y_min, y_max = bounds
        if y_min == y_max:
            pad = abs(y_min) * 0.05 or 0.5
            y_min, y_max = y_min - pad, y_max + pad
        plot.setYRange(y_min, y_max, padding=0.05)

    @staticmethod
    def _hide_stale_analysis_curves(plot, store, desired):
        """Remove curves (and their legend entries) whose key is no longer present in the prepared data."""
        stale_keys = [key for key in store if key not in desired]
        for key in stale_keys:
            plot.removeItem(store.pop(key))

    def _render_analysis_prepared(self, auto_range: bool = False):
        prepared = self.analysis_prepared
        if prepared is None:
            return

        if not auto_range:
            x_range, _ = self.analysis_signal_plot.viewRange()
            for key, plot in (
                ("signal", self.analysis_signal_plot),
                ("integration", self.analysis_integration_plot),
                ("derived", self.analysis_derived_plot),
                ("force", self.analysis_force_plot),
            ):
                if plot.isVisible():
                    _, y_range = plot.viewRange()
                    self._analysis_saved_view_ranges[key] = (x_range, y_range)

        desired_signal = set()
        desired_integration = set()
        desired_derived = set()
        desired_force = set()
        self.analysis_trace_colors = {}
        for index, trace in enumerate(prepared.traces):
            key = trace.label
            desired_signal.add(key)
            color = PLOT_COLORS[index % len(PLOT_COLORS)]
            self.analysis_trace_colors[key] = color
            self._upsert_analysis_curve(
                "signal", self.analysis_signal_curves, self.analysis_signal_plot, key, color, trace
            )

        integration_traces = [trace for trace in prepared.overlay_traces if trace.group == "integration"]
        derived_traces = [trace for trace in prepared.overlay_traces if trace.group != "integration"]
        for index, trace in enumerate(integration_traces):
            key = trace.label
            desired_integration.add(key)
            source_label = self._analysis_integrated_source_label(key)
            color = self.analysis_trace_colors.get(source_label, PLOT_COLORS[index % len(PLOT_COLORS)])
            self._upsert_analysis_curve(
                "integration", self.analysis_integration_curves, self.analysis_integration_plot,
                key, color, trace,
            )

        for index, trace in enumerate(derived_traces):
            key = trace.label
            desired_derived.add(key)
            color = PLOT_COLORS[(index + 6) % len(PLOT_COLORS)]
            self._upsert_analysis_curve(
                "derived", self.analysis_derived_curves, self.analysis_derived_plot, key, color, trace
            )

        for index, trace in enumerate(prepared.force_traces):
            key = trace.label
            desired_force.add(key)
            color = self._analysis_force_trace_color(key, index)
            force_check = self.analysis_force_checks.get(key)
            self._upsert_analysis_curve(
                "force", self.analysis_force_curves, self.analysis_force_plot, key, color, trace,
                visible=force_check.isChecked() if force_check is not None else True,
            )

        self._hide_stale_analysis_curves(self.analysis_signal_plot, self.analysis_signal_curves, desired_signal)
        self._hide_stale_analysis_curves(
            self.analysis_integration_plot, self.analysis_integration_curves, desired_integration
        )
        self._hide_stale_analysis_curves(self.analysis_derived_plot, self.analysis_derived_curves, desired_derived)
        self._hide_stale_analysis_curves(self.analysis_force_plot, self.analysis_force_curves, desired_force)

        visible_force = any(
            self.analysis_force_checks.get(trace.label).isChecked()
            for trace in prepared.force_traces
            if trace.label in self.analysis_force_checks
        )
        self._update_analysis_plot_visibility(
            show_signal=bool(desired_signal),
            show_integration=bool(desired_integration),
            show_derived=bool(desired_derived),
            show_force=visible_force,
        )

        self.analysis_signal_plot.setLabel("left", "Signals", units="V")
        self.analysis_integration_plot.setLabel("left", "Integrated", units="V samples")
        self.analysis_derived_plot.setLabel("left", "Shear / Normal", units="V")
        self.analysis_force_plot.setLabel("left", "Force", units="N")
        stacked_plots = (
            (self.analysis_signal_plot, bool(desired_signal)),
            (self.analysis_integration_plot, bool(desired_integration)),
            (self.analysis_derived_plot, bool(desired_derived)),
            (self.analysis_force_plot, bool(desired_force)),
        )
        bottom_plot = next((plot for plot, visible in reversed(stacked_plots) if visible), None)
        for plot, _visible in stacked_plots:
            if plot is bottom_plot:
                plot.setLabel("bottom", prepared.x_label, units=prepared.x_units)
            else:
                plot.setLabel("bottom", "")
        if auto_range:
            startup_threshold_x = self._analysis_startup_exclude_threshold_x(prepared)
            for plot, traces, desired in (
                (self.analysis_signal_plot, prepared.traces, desired_signal),
                (self.analysis_integration_plot, integration_traces, desired_integration),
                (self.analysis_derived_plot, derived_traces, desired_derived),
                (self.analysis_force_plot, prepared.force_traces, desired_force),
            ):
                if desired:
                    self._auto_range_analysis_plot(plot, traces, startup_threshold_x)
        else:
            for key, plot in (
                ("signal", self.analysis_signal_plot),
                ("integration", self.analysis_integration_plot),
                ("derived", self.analysis_derived_plot),
                ("force", self.analysis_force_plot),
            ):
                if key in self._analysis_saved_view_ranges and plot.isVisible():
                    x_range, y_range = self._analysis_saved_view_ranges[key]
                    plot.setXRange(*x_range, padding=0)
                    plot.setYRange(*y_range, padding=0)
        self.analysis_marker_vline.setVisible(bool(self.analysis_marker_check.isChecked()))
        source = self.analysis_snapshot.source_id if self.analysis_snapshot else "-"
        self._set_analysis_status_text(
            f"Analysis: {len(prepared.traces)} signal traces, {len(prepared.overlay_traces)} overlays, "
            f"{len(prepared.force_traces)} force traces | {source} {prepared.status}".strip()
        )
        self._update_analysis_pzt_mux_timing_status_from_prepared(prepared.status)

    def _update_analysis_plot_visibility(
        self,
        *,
        show_signal: bool,
        show_integration: bool,
        show_derived: bool,
        show_force: bool,
    ):
        """Show only Analysis plots that have requested, available traces."""
        saved = getattr(self, "_analysis_saved_view_ranges", {})
        plot_states = (
            ("signal", self.analysis_signal_plot, bool(show_signal), 250),
            ("integration", self.analysis_integration_plot, bool(show_integration), 200),
            ("derived", self.analysis_derived_plot, bool(show_derived), 200),
            ("force", self.analysis_force_plot, bool(show_force), 100),
        )
        for key, plot, visible, _minimum_height in plot_states:
            was_visible = plot.isVisible()
            plot.setVisible(visible)
            if visible and not was_visible and key in saved:
                x_range, y_range = saved[key]
                plot.setXRange(*x_range, padding=0)
                plot.setYRange(*y_range, padding=0)

        if hasattr(self, "analysis_plot_splitter"):
            self.analysis_plot_splitter.setMinimumHeight(
                sum(minimum_height for _key, _plot, visible, minimum_height in plot_states if visible)
            )
            self.analysis_plot_splitter.setSizes(
                [minimum_height if visible else 0 for _key, _plot, visible, minimum_height in plot_states]
            )

    def _update_analysis_pzt_mux_timing_status_from_prepared(self, status: str):
        if not hasattr(self, "analysis_pzt_mux_timing_status"):
            return
        for part in str(status or "").split("|"):
            text = part.strip()
            if text.startswith("PZT MUX timing:"):
                self.analysis_pzt_mux_timing_status.setText(text.removeprefix("PZT MUX timing:").strip())
                return
            if text.startswith("PZT force skipped:"):
                self.analysis_pzt_mux_timing_status.setText(text)
                return

    def _set_analysis_plot_visible(self, key: str, plot, visible: bool):
        if visible == plot.isVisible():
            return
        plot.setVisible(visible)
        if visible and key in self._analysis_saved_view_ranges:
            x_range, y_range = self._analysis_saved_view_ranges[key]
            plot.setXRange(*x_range, padding=0)
            plot.setYRange(*y_range, padding=0)

    def _analysis_integrated_source_label(self, trace_label: str) -> str:
        prefix = "Integrated "
        suffix = " ["
        if not trace_label.startswith(prefix):
            return trace_label
        body = trace_label[len(prefix):]
        if suffix in body:
            body = body.split(suffix, 1)[0]
        return body

    def _analysis_force_trace_color(self, trace_label: str, index: int):
        source_label = self._analysis_calculated_force_source_label(trace_label)
        if source_label:
            return self.analysis_trace_colors.get(source_label, PLOT_COLORS[index % len(PLOT_COLORS)])
        return PLOT_COLORS[(index + 2) % len(PLOT_COLORS)]

    def _analysis_calculated_force_source_label(self, trace_label: str) -> str | None:
        prefix = "Calculated Force - "
        suffix = " ["
        if not trace_label.startswith(prefix):
            return None
        body = trace_label[len(prefix):]
        if suffix in body:
            body = body.split(suffix, 1)[0]
        return body or None

    def _sync_analysis_force_trace_checks(self, force_traces):
        existing = set(self.analysis_force_checks)
        desired = [trace.label for trace in force_traces]
        if existing == set(desired):
            return
        saved_visibility = self.analysis_state.get("visible_force_labels", {})
        for check in self.analysis_force_checks.values():
            check.deleteLater()
        self.analysis_force_checks = {}
        for label in desired:
            check = QCheckBox(label)
            check.setChecked(bool(saved_visibility.get(label, True)))
            check.stateChanged.connect(self.on_analysis_settings_changed)
            self.analysis_force_checks[label] = check
        self._relayout_analysis_checkboxes()

    def export_analysis_csv(self):
        if self.analysis_prepared is None:
            QMessageBox.warning(self, "Analysis Export", "No Analysis data to export.")
            return
        default_dir = Path(self.analysis_state.get("csv_path") or ".").parent
        default_name = f"analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Analysis CSV",
            str(default_dir / default_name),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not file_path:
            return
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path = path.with_name(f"{path.stem}_metadata.json")
            traces = (
                list(self.analysis_prepared.traces)
                + list(self.analysis_prepared.overlay_traces)
                + [
                    trace for trace in self.analysis_prepared.force_traces
                    if trace.label in self.analysis_force_checks and self.analysis_force_checks[trace.label].isChecked()
                ]
            )
            if not traces:
                raise ValueError("No visible Analysis traces to export.")
            max_len = max(len(trace.y) for trace in traces)
            reference_x = traces[0].x
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([self.analysis_prepared.x_label + ("_" + self.analysis_prepared.x_units if self.analysis_prepared.x_units else "")] + [trace.label for trace in traces])
                for row_index in range(max_len):
                    row = [float(reference_x[row_index]) if row_index < len(reference_x) else ""]
                    for trace in traces:
                        row.append(float(trace.y[row_index]) if row_index < len(trace.y) else "")
                    writer.writerow(row)
            snapshot = self.analysis_snapshot
            metadata = build_analysis_export_metadata(
                snapshot.metadata if snapshot is not None else {},
                self.analysis_state,
                source_id=snapshot.source_id if snapshot is not None else "unknown",
                csv_path=path,
                x_axis_label=self.analysis_prepared.x_label,
                x_axis_units=self.analysis_prepared.x_units,
                exported_traces=[trace.label for trace in traces],
            )
            with metadata_path.open("w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2)
            self._set_analysis_status_text(f"Analysis CSV and metadata exported: {path}, {metadata_path}")
            if hasattr(self, "log_status"):
                self.log_status(f"Analysis CSV exported: {path}")
                self.log_status(f"Analysis metadata exported: {metadata_path}")
        except Exception as exc:
            QMessageBox.warning(self, "Analysis Export Failed", str(exc))
            self._set_analysis_status_text(f"Analysis export failed: {exc}")

    def save_analysis_plot_images(self):
        if self.analysis_prepared is None:
            QMessageBox.warning(self, "Analysis Images", "No Analysis plots to save.")
            return
        selected = [
            ("raw", self.analysis_signal_plot, self.analysis_save_raw_image_check.isChecked()),
            ("integrated", self.analysis_integration_plot, self.analysis_save_integration_image_check.isChecked()),
            ("shear_normal", self.analysis_derived_plot, self.analysis_save_derived_image_check.isChecked()),
            ("force", self.analysis_force_plot, self.analysis_save_force_image_check.isChecked()),
        ]
        selected = [(suffix, plot) for suffix, plot, checked in selected if checked]
        if not selected:
            QMessageBox.warning(self, "Analysis Images", "Choose at least one plot image to save.")
            return

        default_dir = Path(self.analysis_state.get("csv_path") or ".").parent
        if not default_dir.exists() and hasattr(self, "dir_input"):
            export_dir = Path(self.dir_input.text().strip())
            if export_dir.exists():
                default_dir = export_dir
        default_name = f"analysis_plot_{datetime.now().strftime('%Y%m%d_%H%M')}.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Analysis Plot Image",
            str(default_dir / default_name),
            "PNG Files (*.png);;All Files (*)",
        )
        if not file_path:
            return

        try:
            base_path = Path(file_path)
            base_path.parent.mkdir(parents=True, exist_ok=True)
            saved_paths = []
            for suffix, plot in selected:
                output_path = base_path if len(selected) == 1 else base_path.with_name(f"{base_path.stem}_{suffix}.png")
                exporter = ImageExporter(plot.plotItem)
                exporter.parameters()["width"] = PLOT_EXPORT_WIDTH
                exporter.export(str(output_path))
                saved_paths.append(output_path)
            message = "Analysis plot image saved:" if len(saved_paths) == 1 else "Analysis plot images saved:"
            self._set_analysis_status_text(f"{message} {', '.join(str(path) for path in saved_paths)}")
            if hasattr(self, "log_status"):
                for path in saved_paths:
                    self.log_status(f"Analysis plot image saved to {path}")
            QMessageBox.information(self, "Analysis Images", message + "\n" + "\n".join(str(path) for path in saved_paths))
        except Exception as exc:
            QMessageBox.warning(self, "Analysis Image Export Failed", str(exc))
            self._set_analysis_status_text(f"Analysis image export failed: {exc}")

    def reset_analysis_view(self):
        for plot in (
            self.analysis_signal_plot,
            self.analysis_integration_plot,
            self.analysis_derived_plot,
            self.analysis_force_plot,
        ):
            plot.enableAutoRange()

    def _set_analysis_status_text(self, text: str):
        if not hasattr(self, "analysis_status_label"):
            return
        full_text = str(text)
        available_width = max(80, int(self.analysis_status_label.width()) - 8)
        elided = self.analysis_status_label.fontMetrics().elidedText(
            full_text,
            Qt.TextElideMode.ElideRight,
            available_width,
        )
        self.analysis_status_label.setText(elided)
        self.analysis_status_label.setToolTip(full_text)

    def _on_analysis_mouse_moved(self, evt):
        if not bool(self.analysis_marker_check.isChecked()) or self.analysis_prepared is None:
            return
        pos = evt[0]
        if not self.analysis_signal_plot.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.analysis_signal_plot.plotItem.vb.mapSceneToView(pos)
        self._analysis_pending_marker_x = float(mouse_point.x())
        if not self._analysis_marker_timer.isActive():
            self._analysis_marker_timer.start(25)

    def _flush_analysis_marker_readout(self):
        x = self._analysis_pending_marker_x
        prepared = self.analysis_prepared
        if x is None or prepared is None:
            return
        self.analysis_marker_vline.setPos(float(x))
        values = []
        for trace in prepared.traces + prepared.overlay_traces + prepared.force_traces:
            if trace.x.size == 0 or trace.y.size == 0:
                continue
            idx = int(np.argmin(np.abs(trace.x - float(x))))
            if idx < trace.y.size:
                values.append(f"{trace.label}={float(trace.y[idx]):.4g}")
        self._set_analysis_status_text(f"Marker x={float(x):.3f}: " + " | ".join(values[:12]))

    def update_analysis_availability(self):
        if not hasattr(self, "analysis_disabled_label"):
            return
        capturing = bool(getattr(self, "is_capturing", False))
        has_memory = self._analysis_has_in_memory_capture()
        self.analysis_disabled_label.setText("Analysis is disabled during active acquisition." if capturing else "")
        self.analysis_disabled_label.setVisible(capturing)

        self._set_analysis_source_item_enabled(0, has_memory and not capturing)
        self._set_analysis_source_item_enabled(1, not capturing)

        for widget in (
            self.analysis_source_combo,
            self.analysis_axis_combo,
            self.analysis_zoom_combo,
            self.analysis_filter_check,
            self.analysis_shear_check,
            self.analysis_normal_check,
            self.analysis_integration_check,
            self.analysis_pzt_force_check,
            self.analysis_pzt_center_capacitance_spin,
            self.analysis_pzt_outer_capacitance_spin,
            self.analysis_pzt_capacitance_unit_combo,
            self.analysis_pzt_rleak_spin,
            self.analysis_pzt_d33_spin,
            self.analysis_pzt_noise_spin,
            self.analysis_pzt_quiet_duration_spin,
            self.analysis_pzt_noise_k_spin,
            self.analysis_pzt_mux_timing_combo,
            self.analysis_pzt_mux_connected_ms_spin,
            self.analysis_pzt_off_mux_leak_check,
            self.analysis_pzt_off_mux_rleak_spin,
            self.analysis_pzt_calculate_baseline_btn,
            self.analysis_marker_check,
            self.analysis_reset_view_btn,
            self.analysis_export_csv_btn,
            self.analysis_save_raw_image_check,
            self.analysis_save_integration_image_check,
            self.analysis_save_derived_image_check,
            self.analysis_save_force_image_check,
            self.analysis_save_images_btn,
            self.analysis_select_all_btn,
            self.analysis_select_none_btn,
        ):
            widget.setEnabled(not capturing)
        if not capturing:
            self._update_analysis_pzt_mux_timing_controls()
        for check in self.analysis_channel_checks.values():
            check.setEnabled(not capturing)
        for check in self.analysis_force_checks.values():
            check.setEnabled(not capturing)
        self.on_analysis_source_changed()

    def _analysis_has_in_memory_capture(self) -> bool:
        try:
            if getattr(self, "raw_data_buffer", None) is None or getattr(self, "sweep_timestamps_buffer", None) is None:
                return False
            return int(getattr(self, "sweep_count", 0) or 0) > 0
        except Exception:
            return False

    def _set_analysis_source_item_enabled(self, index: int, enabled: bool) -> None:
        item = self.analysis_source_combo.model().item(index)
        if item is None:
            return
        flags = item.flags()
        if enabled:
            item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
        else:
            item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
