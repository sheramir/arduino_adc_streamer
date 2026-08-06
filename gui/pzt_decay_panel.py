"""PZT_Decay_Calc tab and bridge from the existing binary stream to the analyzer."""

from __future__ import annotations

from pathlib import Path
import time

import numpy as np
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import QSettings, QTimer, QUrl, Qt
from PyQt6.QtGui import QDesktopServices
import pyqtgraph as pg

from data_processing.adc_mux_timing import calculate_adc_mux_timing_for_acquisition
from data_processing.pzt_decay import (
    PztDecayAnalyzer, PztDecaySettings, PztDecayState, PztDecayTimestampBasis,
    PztDecayTimingContext,
    resolve_pzt_decay_signal_mapping,
)
from file_operations.pzt_decay_exporter import PztDecayExporter


PZT_DECAY_TAB_NAME = "PZT_Decay_Calc"
PZT_DECAY_REPEAT_COUNT = 50
PZT_DECAY_WAIT_REPEAT_COUNT = 1
PZT_DECAY_VMID_REPEAT_COUNT = 100
PZT_DECAY_VMID_DISCARD_INITIAL_SAMPLES = 10
PZT_DECAY_SAMPLING_METHOD_BURST = "Burst Mode"
PZT_DECAY_SAMPLING_METHOD_SINGLE = "Single Mode"
PZT_DECAY_LIVE_PLOT_MAX_SAMPLES = 5_000
PZT_DECAY_NO_DATA_TIMEOUT_S = 60.0
PZT_DECAY_SETTINGS_VERSION = 3
# Keep a small, immediately preceding target plateau on the completed plot.
# This makes the release and the portion above the fit-upper threshold
# visible without allowing a long target-wait period to dominate the x-axis.
PZT_DECAY_PRE_RELEASE_PLOT_SAMPLES = 10


class PztDecayPanelMixin:
    """Owns the UI and the exclusive one-address capture workflow.

    The serial parser remains the application's normal parser.  This tab only
    takes ownership of its samples after the parser has constructed sweeps.
    """

    def init_pzt_decay_state(self) -> None:
        self.pzt_decay_analyzer = None
        self.pzt_decay_result = None
        self.pzt_decay_mapping = None
        self.pzt_decay_active = False
        self._pzt_decay_config_snapshot = None
        self._pzt_decay_control_snapshot = None
        self._pzt_decay_last_plot_s = 0.0
        self._pzt_decay_last_sample_monotonic: float | None = None
        self._pzt_decay_dense_sampling_pending = False
        self._pzt_decay_dense_sampling_active = False
        self._pzt_decay_mode: str | None = None
        self._pzt_decay_previous_repeat: int | None = None
        self._pzt_decay_next_burst_index = 0
        self._pzt_decay_saved_burst_repeat_count = PZT_DECAY_REPEAT_COUNT
        self.pzt_decay_vmid_by_signal: dict[str, tuple[float, float]] = {}
        self._pzt_decay_watchdog = QTimer(self)
        self._pzt_decay_watchdog.setInterval(250)
        self._pzt_decay_watchdog.timeout.connect(self._check_pzt_decay_watchdog)

    def create_pzt_decay_tab(self) -> QWidget:
        tab = QWidget(); layout = QHBoxLayout(tab)
        left = QVBoxLayout(); right = QVBoxLayout()
        setup = QGroupBox("PZT Decay Characterization"); form = QFormLayout(setup)
        self.pzt_decay_signal_combo = QComboBox(); self.pzt_decay_signal_combo.currentTextChanged.connect(self._update_pzt_decay_mapping_label)
        form.addRow("PZT signal:", self.pzt_decay_signal_combo)
        self.pzt_decay_mapping_label = QLabel("Select an array PZT signal."); self.pzt_decay_mapping_label.setWordWrap(True)
        form.addRow("Hardware mapping:", self.pzt_decay_mapping_label)
        self.pzt_decay_calculate_vmid_btn = QPushButton("Calculate Vmid (100 samples; discard first 10)")
        self.pzt_decay_calculate_vmid_btn.clicked.connect(self.calculate_pzt_decay_vmid)
        form.addRow("", self.pzt_decay_calculate_vmid_btn)
        self.pzt_decay_excitation_spin = QDoubleSpinBox(); self.pzt_decay_excitation_spin.setRange(0.001, 3.0); self.pzt_decay_excitation_spin.setDecimals(4); self.pzt_decay_excitation_spin.setValue(1.0); self.pzt_decay_excitation_spin.setSuffix(" V")
        form.addRow("Excitation above Vmid:", self.pzt_decay_excitation_spin)
        self.pzt_decay_sampling_method_combo = QComboBox()
        self.pzt_decay_sampling_method_combo.addItems((PZT_DECAY_SAMPLING_METHOD_BURST, PZT_DECAY_SAMPLING_METHOD_SINGLE))
        self.pzt_decay_sampling_method_combo.currentTextChanged.connect(self._update_pzt_decay_sampling_controls)
        form.addRow("Sampling Method:", self.pzt_decay_sampling_method_combo)
        self.pzt_decay_repeat_spin = QSpinBox(); self.pzt_decay_repeat_spin.setRange(1, 100); self.pzt_decay_repeat_spin.setValue(PZT_DECAY_REPEAT_COUNT); self.pzt_decay_repeat_spin.setSuffix(" retained pairs")
        form.addRow("Repeat burst count:", self.pzt_decay_repeat_spin)
        self.pzt_decay_dummy_ground_check = QCheckBox("Use dummy ground (Single Mode)")
        self.pzt_decay_dummy_ground_check.setChecked(True)
        form.addRow("", self.pzt_decay_dummy_ground_check)
        self.pzt_decay_required_voltage_label = QLabel("Calculate Vmid first.")
        form.addRow("Required applied voltage:", self.pzt_decay_required_voltage_label)
        self.pzt_decay_resistance_spin = QDoubleSpinBox(); self.pzt_decay_resistance_spin.setRange(0.0, 1e15); self.pzt_decay_resistance_spin.setDecimals(3); self.pzt_decay_resistance_spin.setValue(0.0); self.pzt_decay_resistance_spin.setSuffix(" Ω")
        form.addRow("Connected leakage resistance:", self.pzt_decay_resistance_spin)
        self.pzt_decay_capacitance_check = QCheckBox("Estimate capacitance (model-dependent)")
        form.addRow("", self.pzt_decay_capacitance_check)
        form.addRow("Assumption:", QLabel("Disconnected leakage is negligible."))
        self.pzt_decay_tolerance_spin = QDoubleSpinBox(); self.pzt_decay_tolerance_spin.setRange(0.001, 1.0); self.pzt_decay_tolerance_spin.setDecimals(4); self.pzt_decay_tolerance_spin.setValue(0.020); self.pzt_decay_tolerance_spin.setSuffix(" V")
        form.addRow("Target tolerance:", self.pzt_decay_tolerance_spin)
        self.pzt_decay_fit_upper = QDoubleSpinBox(); self.pzt_decay_fit_upper.setRange(0.05, 1.0); self.pzt_decay_fit_upper.setDecimals(4); self.pzt_decay_fit_upper.setValue(0.85)
        self.pzt_decay_fit_lower = QDoubleSpinBox(); self.pzt_decay_fit_lower.setRange(0.01, 0.95); self.pzt_decay_fit_lower.setDecimals(4); self.pzt_decay_fit_lower.setValue(0.15)
        form.addRow("Fit upper normalized:", self.pzt_decay_fit_upper); form.addRow("Fit lower normalized:", self.pzt_decay_fit_lower)
        self.pzt_decay_min_fit_spin = QSpinBox(); self.pzt_decay_min_fit_spin.setRange(3, 100000); self.pzt_decay_min_fit_spin.setValue(3)
        form.addRow("Minimum fit samples:", self.pzt_decay_min_fit_spin)
        self.pzt_decay_duration_spin = QDoubleSpinBox(); self.pzt_decay_duration_spin.setRange(1.0, 600.0); self.pzt_decay_duration_spin.setValue(60.0); self.pzt_decay_duration_spin.setSuffix(" s")
        form.addRow("Decay timeout:", self.pzt_decay_duration_spin)
        self.pzt_decay_robust_check = QCheckBox("Robust fit"); self.pzt_decay_robust_check.setChecked(True); form.addRow("", self.pzt_decay_robust_check)
        self.pzt_decay_timing_label = QLabel("Timing available after Begin."); self.pzt_decay_timing_label.setWordWrap(True); form.addRow("Timing:", self.pzt_decay_timing_label)
        left.addWidget(setup)
        buttons = QHBoxLayout(); self.pzt_decay_begin_btn = QPushButton("Start"); self.pzt_decay_begin_btn.clicked.connect(self.begin_pzt_decay_characterization)
        self.pzt_decay_cancel_btn = QPushButton("Cancel"); self.pzt_decay_cancel_btn.clicked.connect(self.cancel_pzt_decay_characterization); self.pzt_decay_cancel_btn.setEnabled(False)
        self.pzt_decay_save_btn = QPushButton("Save Result"); self.pzt_decay_save_btn.clicked.connect(self.save_pzt_decay_result); self.pzt_decay_save_btn.setEnabled(False)
        self.pzt_decay_folder_btn = QPushButton("Open Result Folder"); self.pzt_decay_folder_btn.clicked.connect(self.open_pzt_decay_result_folder)
        buttons.addWidget(self.pzt_decay_begin_btn); buttons.addWidget(self.pzt_decay_cancel_btn); buttons.addWidget(self.pzt_decay_save_btn); buttons.addWidget(self.pzt_decay_folder_btn); left.addLayout(buttons); left.addStretch()
        right.addWidget(self._create_pzt_decay_plot())
        self.pzt_decay_result_label = QLabel("Idle. Baseline, target, release, and decay are detected automatically."); self.pzt_decay_result_label.setWordWrap(True); right.addWidget(self.pzt_decay_result_label)
        layout.addLayout(left, 0); layout.addLayout(right, 1)
        self.refresh_pzt_decay_signals()
        self._connect_pzt_decay_settings_autosave(); self.load_last_pzt_decay_settings()
        self.pzt_decay_excitation_spin.valueChanged.connect(self._update_pzt_decay_required_voltage)
        self._set_pzt_decay_measurement_controls(False)
        return tab

    def _pzt_decay_qsettings(self) -> QSettings:
        return QSettings("ArduinoADCStreamer", "PztDecayCalc")

    def _connect_pzt_decay_settings_autosave(self) -> None:
        for widget in (self.pzt_decay_signal_combo, self.pzt_decay_excitation_spin, self.pzt_decay_resistance_spin,
                       self.pzt_decay_capacitance_check, self.pzt_decay_tolerance_spin, self.pzt_decay_fit_upper,
                       self.pzt_decay_fit_lower, self.pzt_decay_min_fit_spin, self.pzt_decay_duration_spin,
                       self.pzt_decay_repeat_spin, self.pzt_decay_sampling_method_combo,
                       self.pzt_decay_dummy_ground_check, self.pzt_decay_robust_check):
            signal = getattr(widget, "valueChanged", None) or getattr(widget, "currentTextChanged", None) or getattr(widget, "stateChanged", None)
            if signal: signal.connect(self.save_last_pzt_decay_settings)

    def save_last_pzt_decay_settings(self, *_args) -> None:
        if not hasattr(self, "pzt_decay_signal_combo"): return
        settings = self._pzt_decay_qsettings()
        values = {"signal": self.pzt_decay_signal_combo.currentText(), "excitation": self.pzt_decay_excitation_spin.value(),
                  "resistance": self.pzt_decay_resistance_spin.value(), "capacitance": self.pzt_decay_capacitance_check.isChecked(),
                  "tolerance": self.pzt_decay_tolerance_spin.value(), "fit_upper": self.pzt_decay_fit_upper.value(),
                  "fit_lower": self.pzt_decay_fit_lower.value(), "min_fit": self.pzt_decay_min_fit_spin.value(),
                  "duration_s": self.pzt_decay_duration_spin.value(), "repeat_count": self.pzt_decay_repeat_spin.value(),
                  "sampling_method": self.pzt_decay_sampling_method_combo.currentText(),
                  "single_dummy_ground": self.pzt_decay_dummy_ground_check.isChecked(),
                  "robust": self.pzt_decay_robust_check.isChecked()}
        for key, value in values.items(): settings.setValue(key, value)
        settings.setValue("defaults_version", PZT_DECAY_SETTINGS_VERSION)

    def load_last_pzt_decay_settings(self) -> None:
        settings = self._pzt_decay_qsettings()
        try:
            settings_version = int(settings.value("defaults_version", 0))
        except (TypeError, ValueError):
            settings_version = 0
        use_new_defaults = settings_version < PZT_DECAY_SETTINGS_VERSION
        self.pzt_decay_signal_combo.setCurrentText(str(settings.value("signal", self.pzt_decay_signal_combo.currentText())))
        self.pzt_decay_excitation_spin.setValue(float(settings.value("excitation", 1.0)))
        self.pzt_decay_resistance_spin.setValue(float(settings.value("resistance", 0.0)))
        self.pzt_decay_capacitance_check.setChecked(str(settings.value("capacitance", "false")).lower() in ("true", "1"))
        self.pzt_decay_tolerance_spin.setValue(float(settings.value("tolerance", .020)))
        self.pzt_decay_fit_upper.setValue(0.85 if use_new_defaults else float(settings.value("fit_upper", 0.85)))
        self.pzt_decay_fit_lower.setValue(0.15 if use_new_defaults else float(settings.value("fit_lower", 0.15)))
        self.pzt_decay_min_fit_spin.setValue(max(3, int(settings.value("min_fit", 3))))
        self.pzt_decay_duration_spin.setValue(float(settings.value("duration_s", 60.0)))
        self.pzt_decay_repeat_spin.setValue(PZT_DECAY_REPEAT_COUNT if use_new_defaults else max(1, int(settings.value("repeat_count", PZT_DECAY_REPEAT_COUNT))))
        self.pzt_decay_sampling_method_combo.setCurrentText(
            PZT_DECAY_SAMPLING_METHOD_BURST if use_new_defaults else str(
                settings.value("sampling_method", PZT_DECAY_SAMPLING_METHOD_BURST)
            )
        )
        self.pzt_decay_dummy_ground_check.setChecked(
            str(settings.value("single_dummy_ground", "true")).lower() in ("true", "1")
        )
        self.pzt_decay_robust_check.setChecked(str(settings.value("robust", "true")).lower() in ("true", "1"))
        self._update_pzt_decay_sampling_controls()
        if use_new_defaults:
            self.save_last_pzt_decay_settings()

    def _create_pzt_decay_plot(self) -> QGroupBox:
        group = QGroupBox("Live voltage decay"); layout = QVBoxLayout(group)
        self.pzt_decay_plot = pg.PlotWidget(); self.pzt_decay_plot.setBackground("w"); self.pzt_decay_plot.setLabel("left", "Voltage", units="V"); self.pzt_decay_plot.setLabel("bottom", "Time after release", units="s"); self.pzt_decay_plot.showGrid(x=True, y=True, alpha=0.3)
        self._pzt_decay_measured_curve = self.pzt_decay_plot.plot(pen=pg.mkPen("#1565c0", width=2), name="Measured")
        self._pzt_decay_fit_curve = self.pzt_decay_plot.plot(pen=pg.mkPen("#e65100", width=2), name="Calculated decay")
        self._pzt_decay_out_of_fit_points = self.pzt_decay_plot.plot(pen=None, symbol="o", symbolBrush="#fb8c00", symbolSize=5, name="Outside fit range")
        self._pzt_decay_fit_points = self.pzt_decay_plot.plot(pen=None, symbol="o", symbolBrush="#43a047", symbolSize=6, name="Fit samples")
        self._pzt_decay_burst_end_markers = self.pzt_decay_plot.plot(
            pen=pg.mkPen("#616161", width=1, style=Qt.PenStyle.DashLine),
            name="Burst end",
        )
        self._pzt_decay_vmid_line = pg.InfiniteLine(angle=0, pen=pg.mkPen("#666", style=Qt.PenStyle.DashLine), label="Vmid: {value:.4f} V")
        self._pzt_decay_target_line = pg.InfiniteLine(angle=0, pen=pg.mkPen("#ab47bc", style=Qt.PenStyle.DashLine), label="Target: {value:.4f} V")
        self._pzt_decay_fit_upper_line = pg.InfiniteLine(angle=0, pen=pg.mkPen("#43a047", style=Qt.PenStyle.DashLine), label="Fit upper: {value:.4f} V")
        self._pzt_decay_fit_lower_line = pg.InfiniteLine(angle=0, pen=pg.mkPen("#fb8c00", style=Qt.PenStyle.DashLine), label="Fit lower: {value:.4f} V")
        for line in (self._pzt_decay_vmid_line, self._pzt_decay_target_line, self._pzt_decay_fit_upper_line, self._pzt_decay_fit_lower_line):
            self.pzt_decay_plot.addItem(line)
        self._pzt_decay_fit_upper_line.hide(); self._pzt_decay_fit_lower_line.hide()
        layout.addWidget(self.pzt_decay_plot); return group

    def refresh_pzt_decay_signals(self) -> None:
        if not hasattr(self, "pzt_decay_signal_combo"):
            return
        current = self.pzt_decay_signal_combo.currentText(); self.pzt_decay_signal_combo.blockSignals(True); self.pzt_decay_signal_combo.clear()
        config = self.get_active_sensor_configuration() if hasattr(self, "get_active_sensor_configuration") else {}
        positions = [str(x).upper() for x in config.get("channel_sensor_map", [])]
        for sensor, mapping in config.get("mux_mapping", {}).items():
            for position in positions[:len(mapping.get("channels", []))]:
                self.pzt_decay_signal_combo.addItem(f"{sensor}_{position}")
        if current: self.pzt_decay_signal_combo.setCurrentText(current)
        self.pzt_decay_signal_combo.blockSignals(False); self._update_pzt_decay_mapping_label()

    def _selected_pzt_decay_mapping(self):
        config = self.get_active_sensor_configuration()
        return resolve_pzt_decay_signal_mapping(config, self.pzt_decay_signal_combo.currentText())

    def _update_pzt_decay_mapping_label(self, *_args) -> None:
        try:
            mapping = self._selected_pzt_decay_mapping()
            cached = mapping.logical_signal in self.pzt_decay_vmid_by_signal
            suffix = " Vmid calculated." if cached else " Calculate Vmid before starting a measurement."
            self.pzt_decay_mapping_label.setText(f"MUX{mapping.mux_number}, address {mapping.mux_address}, apply voltage to {mapping.mux_pin_label}; ADC CH{mapping.physical_adc_input}. Companion: {mapping.companion_signal or 'none'}.{suffix}")
            if hasattr(self, "pzt_decay_calculate_vmid_btn"):
                self.pzt_decay_calculate_vmid_btn.setEnabled(not self.pzt_decay_active)
            self._set_pzt_decay_measurement_controls(cached and not self.pzt_decay_active)
            self._update_pzt_decay_required_voltage()
        except Exception as exc:
            self.pzt_decay_mapping_label.setText(str(exc))

    def _set_pzt_decay_measurement_controls(self, enabled: bool) -> None:
        """Gate per-signal settings and Start until its Vmid is available."""
        for widget in (getattr(self, "pzt_decay_excitation_spin", None), getattr(self, "pzt_decay_resistance_spin", None),
                       getattr(self, "pzt_decay_capacitance_check", None), getattr(self, "pzt_decay_tolerance_spin", None),
                       getattr(self, "pzt_decay_fit_upper", None), getattr(self, "pzt_decay_fit_lower", None),
                       getattr(self, "pzt_decay_min_fit_spin", None), getattr(self, "pzt_decay_duration_spin", None),
                       getattr(self, "pzt_decay_repeat_spin", None), getattr(self, "pzt_decay_sampling_method_combo", None),
                       getattr(self, "pzt_decay_dummy_ground_check", None),
                       getattr(self, "pzt_decay_robust_check", None), getattr(self, "pzt_decay_begin_btn", None)):
            if widget is not None:
                widget.setEnabled(enabled)
        self._update_pzt_decay_sampling_controls()

    def _pzt_decay_is_single_mode(self) -> bool:
        return (
            getattr(self, "pzt_decay_sampling_method_combo", None) is not None
            and self.pzt_decay_sampling_method_combo.currentText() == PZT_DECAY_SAMPLING_METHOD_SINGLE
        )

    def _pzt_decay_measurement_repeat_count(self) -> int:
        return 1 if self._pzt_decay_is_single_mode() else self.pzt_decay_repeat_spin.value()

    def _pzt_decay_measurement_uses_dummy_ground(self) -> bool:
        return self._pzt_decay_is_single_mode() and self.pzt_decay_dummy_ground_check.isChecked()

    def _pzt_decay_ground_command(self, mapping, use_dummy_ground: bool) -> tuple[str, int]:
        """Return an existing ground command and a valid ground address when needed."""
        if not use_dummy_ground:
            return "ground false", -1
        ground_pin = self._pzt_decay_config_snapshot.ground_pin
        if ground_pin < 0 or ground_pin == mapping.mux_address:
            ground_pin = 0 if mapping.mux_address != 0 else 15
        return f"ground {ground_pin}", ground_pin

    def _update_pzt_decay_sampling_controls(self, *_args) -> None:
        """Apply method-specific control gating without changing the saved single-mode choice."""
        if not hasattr(self, "pzt_decay_repeat_spin"):
            return
        controls_enabled = getattr(self, "pzt_decay_begin_btn", None) is not None and self.pzt_decay_begin_btn.isEnabled()
        single_mode = self._pzt_decay_is_single_mode()
        if single_mode:
            if self.pzt_decay_repeat_spin.value() != 1:
                self._pzt_decay_saved_burst_repeat_count = self.pzt_decay_repeat_spin.value()
            self.pzt_decay_repeat_spin.setValue(1)
        elif self.pzt_decay_repeat_spin.value() == 1:
            self.pzt_decay_repeat_spin.setValue(max(2, self._pzt_decay_saved_burst_repeat_count))
        self.pzt_decay_repeat_spin.setEnabled(controls_enabled and not single_mode)
        self.pzt_decay_dummy_ground_check.setEnabled(controls_enabled and single_mode)

    def _update_pzt_decay_required_voltage(self, *_args) -> None:
        if not hasattr(self, "pzt_decay_required_voltage_label"):
            return
        signal = self.pzt_decay_signal_combo.currentText() if hasattr(self, "pzt_decay_signal_combo") else ""
        try:
            signal = self._selected_pzt_decay_mapping().logical_signal
        except Exception:
            pass
        cached = self.pzt_decay_vmid_by_signal.get(signal)
        if cached is None:
            self.pzt_decay_required_voltage_label.setText("Calculate Vmid first.")
            return
        vmid_v, _ = cached
        self.pzt_decay_required_voltage_label.setText(f"{vmid_v + self.pzt_decay_excitation_spin.value():.4f} V  (Vmid {vmid_v:.4f} V + excitation)")

    def _pzt_decay_settings(self) -> PztDecaySettings:
        return PztDecaySettings(
            excitation_above_vmid_v=self.pzt_decay_excitation_spin.value(),
            # Vmid must use the same no-dummy-ground electrical path as the
            # decay capture.  Capture 100 repeated samples, discard the first
            # 10 settling samples, then take the median of the remaining 90.
            baseline_duration_s=0.0,
            baseline_min_samples=(
                PZT_DECAY_VMID_REPEAT_COUNT - PZT_DECAY_VMID_DISCARD_INITIAL_SAMPLES
            ),
            baseline_discard_initial_samples=PZT_DECAY_VMID_DISCARD_INITIAL_SAMPLES,
            # A single high-rate burst naturally settles upward just after
            # parking is released.  The median is still useful after the
            # initial discard; a slow-baseline slope rule is not meaningful
            # on this sub-millisecond Vmid capture.
            baseline_validate_stability=False,
            target_tolerance_v=self.pzt_decay_tolerance_spin.value(),
            fit_upper_normalized=self.pzt_decay_fit_upper.value(), fit_lower_normalized=self.pzt_decay_fit_lower.value(),
            minimum_fit_samples=self.pzt_decay_min_fit_spin.value(),
            target_timeout_s=60.0, maximum_recording_duration_s=self.pzt_decay_duration_spin.value(),
            end_threshold_normalized=0.02, robust_fit_enabled=self.pzt_decay_robust_check.isChecked(),
            capacitance_estimation_enabled=self.pzt_decay_capacitance_check.isChecked(),
            connected_equivalent_resistance_ohm=(self.pzt_decay_resistance_spin.value() or None),
            adc_max_v=float(self.get_vref_voltage()),
        )

    def calculate_pzt_decay_vmid(self) -> None:
        """Collect and cache a median Vmid for the selected logical signal."""
        self._begin_pzt_decay_capture("vmid")

    def begin_pzt_decay_characterization(self) -> None:
        """Start a decay run using the selected signal's cached Vmid."""
        signal = self.pzt_decay_signal_combo.currentText()
        try:
            signal = self._selected_pzt_decay_mapping().logical_signal
        except Exception:
            pass
        if signal not in self.pzt_decay_vmid_by_signal:
            QMessageBox.warning(self, "PZT decay", "Calculate Vmid for this PZT signal before starting.")
            return
        self._begin_pzt_decay_capture("measurement")

    def _begin_pzt_decay_capture(self, mode: str) -> None:
        if self.pzt_decay_active: return
        if not getattr(self, "serial_port", None) or not getattr(self.serial_port, "is_open", False):
            QMessageBox.warning(self, "PZT decay", "Connect an Array PZT/PZR device before beginning characterization."); return
        if not self.is_array_pzt1_mode():
            QMessageBox.warning(self, "PZT decay", "PZT_Decay_Calc requires an Array_PZT_PZR dual-MUX device."); return
        try:
            mapping = self._selected_pzt_decay_mapping(); settings = self._pzt_decay_settings(); settings.validate()
            if self.is_capturing: self.stop_capture()
            self._pzt_decay_config_snapshot = self.config.copy()
            self._pzt_decay_control_snapshot = {"buffer": self.buffer_spin.value() if hasattr(self, "buffer_spin") else 1}
            self.set_controls_enabled(False)
            # Vmid is always one compact repeat-100, no-dummy-ground burst.
            # Measurement target detection uses repeat 1; after target it
            # switches to either the requested no-ground burst or single mode.
            initial_repeat_count = (
                PZT_DECAY_VMID_REPEAT_COUNT
                if mode == "vmid" else PZT_DECAY_WAIT_REPEAT_COUNT
            )
            use_dummy_ground = mode == "measurement" and self._pzt_decay_measurement_uses_dummy_ground()
            ground_command, ground_pin = self._pzt_decay_ground_command(mapping, use_dummy_ground)
            for command in (f"mode PZT" if self.is_array_pzt_pzr_mode() else None, f"channels {mapping.mux_address}", f"repeat {initial_repeat_count}", ground_command, "buffer 1"):
                if command:
                    ok, _ = self.send_command_and_wait_ack(command, None, timeout=0.5, max_retries=2)
                    if not ok: raise RuntimeError(f"device did not acknowledge '{command}'")
            self.config.update({"channels": [mapping.mux_address], "channel_selection_source": "pzt_decay", "selected_array_sensors": [], "array_operation_mode": "PZT", "repeat": initial_repeat_count, "ground_pin": ground_pin, "use_ground": use_dummy_ground})
            timing = calculate_adc_mux_timing_for_acquisition(self.current_mcu, self.config)
            if timing is None: raise RuntimeError("no ADC/MUX timing model is available for this device")
            context = PztDecayTimingContext.from_adc_mux_timing(timing, mapping.physical_adc_input)
            self.pzt_decay_analyzer = PztDecayAnalyzer(mapping, context, settings, {"osr": self.config.get("osr"), "gain": self.config.get("gain"), "repeat_count": initial_repeat_count, "dummy_ground_enabled": self.config.get("use_ground"), "mux_settle_us": timing.mux_settle_us, "timestamp_basis": "burst_start_plus_calculated_observation_offset"})
            if mode == "vmid":
                self.pzt_decay_analyzer.begin()
            else:
                vmid_v, baseline_sigma_v = self.pzt_decay_vmid_by_signal[mapping.logical_signal]
                self.pzt_decay_analyzer.begin_with_vmid(vmid_v, baseline_sigma_v)
                if self.pzt_decay_analyzer.state == PztDecayState.ERROR:
                    raise RuntimeError(self.pzt_decay_analyzer.error_message or "invalid Vmid/target configuration")
                self._reset_pzt_decay_plot()
            self.pzt_decay_mapping = mapping; self.pzt_decay_active = True; self.pzt_decay_result = None; self._pzt_decay_mode = mode; self._pzt_decay_previous_repeat = None
            self._pzt_decay_last_sample_monotonic = time.monotonic()
            self._pzt_decay_dense_sampling_pending = False
            self._pzt_decay_dense_sampling_active = False
            self._pzt_decay_next_burst_index = 0
            self.adc_mux_timing = timing; self.is_capturing = True
            if self.serial_thread: self.serial_thread.set_capturing(True, expected_samples_per_sweep=2 * initial_repeat_count)
            self.send_command("run")
            self._pzt_decay_watchdog.start()
            self.pzt_decay_calculate_vmid_btn.setEnabled(False); self._set_pzt_decay_measurement_controls(False)
            self.pzt_decay_cancel_btn.setEnabled(True); self.pzt_decay_save_btn.setEnabled(False)
            if mode == "vmid":
                self.pzt_decay_timing_label.setText(
                    f"CH{mapping.physical_adc_input}: collecting one {PZT_DECAY_VMID_REPEAT_COUNT}-repeat Vmid burst "
                    "without dummy-ground ADC samples. Existing firmware parking remains enabled."
                )
                self.pzt_decay_result_label.setText(
                    f"Calculating Vmid: collecting 0 / {PZT_DECAY_VMID_REPEAT_COUNT} samples "
                    f"(first {PZT_DECAY_VMID_DISCARD_INITIAL_SAMPLES} discarded). Do not apply voltage or force."
                )
                self.log_status("PZT decay Vmid measurement started; regular acquisition is locked.")
            else:
                sampling_detail = (
                    f"Single Mode: repeat 1; dummy ground {'enabled' if use_dummy_ground else 'disabled'}."
                    if self._pzt_decay_is_single_mode()
                    else f"Burst Mode: after target, {self.pzt_decay_repeat_spin.value()} connected repeats; no dummy-ground ADC conversion."
                )
                self.pzt_decay_timing_label.setText(
                    f"CH{mapping.physical_adc_input}: waiting with 1 repeat. {sampling_detail} "
                    "Existing firmware parking remains enabled. "
                    f"Dense pair-loop interval {context.pair_loop_interval_s * 1e6:.2f} µs; "
                    f"first effective sample {context.pre_sample_decay_s * 1e6:.2f} µs after connection."
                )
                self.pzt_decay_result_label.setText("Waiting for the required applied voltage. Sampling is live; Start is disabled.")
                self.log_status("PZT decay measurement started; waiting up to 60 seconds for the target signal.")
        except Exception as exc:
            self._finish_pzt_decay_capture(error=str(exc)); QMessageBox.warning(self, "PZT decay", str(exc))

    def _check_pzt_decay_watchdog(self) -> None:
        """End a run even when the firmware never sends a binary frame."""
        if not self.pzt_decay_active or self._pzt_decay_last_sample_monotonic is None:
            return
        if time.monotonic() - self._pzt_decay_last_sample_monotonic < PZT_DECAY_NO_DATA_TIMEOUT_S:
            return
        error = "Could not find a signal: no ADC data received for 60 seconds"
        if self.pzt_decay_analyzer is not None:
            self.pzt_decay_analyzer.fail(error)
        self._finish_pzt_decay_capture(error=error)

    def _start_pzt_decay_dense_sampling(self) -> None:
        """Safely restart the existing firmware in dense repeat mode after target detection."""
        if (not self.pzt_decay_active or self._pzt_decay_mode != "measurement"
                or not self._pzt_decay_dense_sampling_pending):
            return
        self._pzt_decay_dense_sampling_pending = False
        repeat_count = self._pzt_decay_measurement_repeat_count()
        try:
            # The active PZT stream only polls for ``stop``.  Stop first so
            # repeat is acknowledged by the command parser rather than being
            # lost in the streaming loop.
            ok, _ = self.send_command_and_wait_ack("stop", None, timeout=0.5, max_retries=1)
            if not ok:
                raise RuntimeError("device did not acknowledge 'stop' before dense PZT sampling")
            if self.serial_thread:
                self.serial_thread.set_capturing(False)
            if hasattr(self, "drain_serial_input"):
                self.drain_serial_input(0.02)
            ok, _ = self.send_command_and_wait_ack(
                f"repeat {repeat_count}", None, timeout=0.5, max_retries=2,
            )
            if not ok:
                raise RuntimeError("device did not acknowledge dense PZT repeat configuration")
            self.config.update({"repeat": repeat_count})
            timing = calculate_adc_mux_timing_for_acquisition(self.current_mcu, self.config)
            if timing is None:
                raise RuntimeError("no ADC/MUX timing model is available for dense PZT sampling")
            context = PztDecayTimingContext.from_adc_mux_timing(timing, self.pzt_decay_mapping.physical_adc_input)
            self.adc_mux_timing = timing
            vmid_v, baseline_sigma_v = self.pzt_decay_analyzer.vmid_v, self.pzt_decay_analyzer.baseline_sigma_v
            # The low-rate target watcher and dense burst have different repeat
            # configurations. Begin a fresh, self-consistent burst sequence so
            # no synthetic exposure is assigned across that restart.
            self.pzt_decay_analyzer = PztDecayAnalyzer(
                self.pzt_decay_mapping, context, self.pzt_decay_analyzer.settings,
                {"osr": self.config.get("osr"), "gain": self.config.get("gain"),
                 "repeat_count": repeat_count, "dummy_ground_enabled": self.config.get("use_ground"),
                 "mux_settle_us": timing.mux_settle_us,
                 "timestamp_basis": "burst_start_plus_calculated_observation_offset"},
            )
            self.pzt_decay_analyzer.begin_with_vmid(float(vmid_v), float(baseline_sigma_v))
            self._pzt_decay_previous_repeat = None
            self._pzt_decay_next_burst_index = 0
            self._pzt_decay_last_sample_monotonic = time.monotonic()
            if self.serial_thread:
                self.serial_thread.set_capturing(True, expected_samples_per_sweep=2 * repeat_count)
            self.send_command("run")
            self._pzt_decay_dense_sampling_active = True
            sampling_label = (
                f"Single Mode (dummy ground {'enabled' if self.config.get('use_ground') else 'disabled'})"
                if self._pzt_decay_is_single_mode() else "Burst Mode (no dummy ground)"
            )
            self.pzt_decay_result_label.setText(
                f"Target found. {sampling_label} sampling is ready; remove the applied voltage now to record the decay."
            )
            self.log_status(f"PZT decay target found; restarted {sampling_label} with repeat {repeat_count}.")
        except Exception as exc:
            self._finish_pzt_decay_capture(error=str(exc))

    def process_pzt_decay_block(self, block_samples: np.ndarray, sweep_timestamps_s: np.ndarray) -> None:
        if not self.pzt_decay_active or self.pzt_decay_analyzer is None: return
        self._pzt_decay_last_sample_monotonic = time.monotonic()
        timing = self.pzt_decay_analyzer.timing
        input_index = self.pzt_decay_mapping.physical_adc_input - 1
        repeat_count = timing.repeat_count
        last_column = input_index + 2 * (repeat_count - 1)
        if block_samples.ndim != 2 or block_samples.shape[1] <= last_column: return
        for sweep, timestamp in zip(block_samples, sweep_timestamps_s):
            burst_index = self._pzt_decay_next_burst_index
            state = self.pzt_decay_analyzer.state
            for repeat_index in range(repeat_count):
                voltage = float(sweep[input_index + 2 * repeat_index]) / 4095.0 * float(self.get_vref_voltage())
                previous_state = self.pzt_decay_analyzer.state
                state = self.pzt_decay_analyzer.add_sample(
                    voltage, float(timestamp), burst_index=burst_index, repeat_index=repeat_index,
                    timestamp_basis=PztDecayTimestampBasis.BURST_START,
                )
                # Completion can occur part way through a retained-pair
                # burst.  Stop consuming that burst immediately and hand the
                # result back to the GUI; otherwise a later queued callback
                # can leave the panel looking as though it is still recording.
                if state in (PztDecayState.COMPLETE, PztDecayState.ERROR):
                    break
            self._pzt_decay_next_burst_index += 1
            if self._pzt_decay_mode == "vmid" and state == PztDecayState.WAITING_FOR_TARGET:
                self.pzt_decay_vmid_by_signal[self.pzt_decay_mapping.logical_signal] = (
                    float(self.pzt_decay_analyzer.vmid_v), float(self.pzt_decay_analyzer.baseline_sigma_v)
                )
                self._finish_pzt_decay_capture()
                break
            if state == PztDecayState.WAITING_FOR_TARGET and self.pzt_decay_analyzer.target_voltage_v is not None:
                self.pzt_decay_result_label.setText(
                    f"Vmid = {self.pzt_decay_analyzer.vmid_v:.4f} V. Apply {self.pzt_decay_analyzer.target_voltage_v:.4f} V "
                    f"(Vmid + {self.pzt_decay_excitation_spin.value():.4f} V). Measurement starts automatically when stable."
                )
            if (self._pzt_decay_mode == "measurement" and not self._pzt_decay_dense_sampling_active
                    and not self._pzt_decay_dense_sampling_pending
                    and previous_state in (PztDecayState.WAITING_FOR_TARGET, PztDecayState.TARGET_STABILIZING)
                    and state == PztDecayState.RECORDING_DECAY):
                self._pzt_decay_dense_sampling_pending = True
                self.pzt_decay_result_label.setText("Target found. Preparing dense decay sampling; keep the voltage applied.")
                QTimer.singleShot(0, self._start_pzt_decay_dense_sampling)
                break
            if state in (PztDecayState.COMPLETE, PztDecayState.ERROR) or self.pzt_decay_analyzer.result is not None:
                self.pzt_decay_result = self.pzt_decay_analyzer.result; self._finish_pzt_decay_capture(error=self.pzt_decay_analyzer.error_message); break
            if not self.pzt_decay_active:
                break
        if time.monotonic() - self._pzt_decay_last_plot_s > 0.05:
            self._pzt_decay_last_plot_s = time.monotonic(); self._update_pzt_decay_plot()

    def _pzt_decay_display_samples(self):
        """Return the bounded, selected event and its plotting origin.

        Only samples assigned ``calculated_voltage_v`` are in the final event.
        Other retained samples can have their default relative time of zero,
        so they must not be used to choose the completed plot range.
        """
        analyzer = self.pzt_decay_analyzer
        if analyzer is None or not analyzer.samples:
            return [], 0.0
        if analyzer.result:
            event_indices = [
                index for index, sample in enumerate(analyzer.samples)
                if sample.calculated_voltage_v is not None
            ]
            if event_indices:
                event_start = event_indices[0]
                event = analyzer.samples[event_start:]
                event = [sample for sample in event if sample.calculated_voltage_v is not None]
                pre_event = [
                    sample for sample in analyzer.samples[:event_start]
                    if sample.measurement_state == PztDecayState.RECORDING_DECAY.value
                ][-PZT_DECAY_PRE_RELEASE_PLOT_SAMPLES:]
                return pre_event + event, event[0].timestamp_s

        release = analyzer.release_time_s or analyzer.samples[0].timestamp_s
        post = [sample for sample in analyzer.samples if sample.timestamp_s >= release]
        if len(post) > PZT_DECAY_LIVE_PLOT_MAX_SAMPLES:
            # Rendering the full high-rate target plateau repeatedly is not
            # useful and can starve Qt's event loop.  Analysis still retains
            # the complete capture; this only bounds live drawing work.
            post = post[-PZT_DECAY_LIVE_PLOT_MAX_SAMPLES:]
        return post, release

    def _update_pzt_decay_plot(self) -> None:
        analyzer = self.pzt_decay_analyzer
        if analyzer is None or not analyzer.samples: return
        post, plot_origin_s = self._pzt_decay_display_samples()
        if not post:
            return
        # Use actual effective timestamps for both live and completed plots.
        # Pre-release plateau samples do not participate in the regression
        # and therefore have no analysis-only ``relative_time_s`` value.
        x = [sample.timestamp_s - plot_origin_s for sample in post]
        y = [sample.voltage_v for sample in post]
        self._pzt_decay_measured_curve.setData(x, y)
        if analyzer.vmid_v is not None: self._pzt_decay_vmid_line.setValue(analyzer.vmid_v)
        if analyzer.target_voltage_v is not None: self._pzt_decay_target_line.setValue(analyzer.target_voltage_v)
        if analyzer.vmid_v is not None and analyzer.initial_amplitude_v is not None:
            fit_upper_v = analyzer.vmid_v + analyzer.settings.fit_upper_normalized * analyzer.initial_amplitude_v
            fit_lower_v = analyzer.vmid_v + analyzer.settings.fit_lower_normalized * analyzer.initial_amplitude_v
            self._pzt_decay_fit_upper_line.setValue(fit_upper_v)
            self._pzt_decay_fit_lower_line.setValue(fit_lower_v)
            # Explicit static labels avoid pyqtgraph retaining the line's
            # construction-time 0 V label after its position changes.
            self._pzt_decay_fit_upper_line.label.setFormat(f"Fit upper: {fit_upper_v:.4f} V")
            self._pzt_decay_fit_lower_line.label.setFormat(f"Fit lower: {fit_lower_v:.4f} V")
            self._pzt_decay_fit_upper_line.show(); self._pzt_decay_fit_lower_line.show()
        calculated = [sample for sample in post if sample.calculated_voltage_v is not None]
        self._pzt_decay_fit_curve.setData(
            [sample.timestamp_s - plot_origin_s for sample in calculated],
            [sample.calculated_voltage_v for sample in calculated],
        )
        outside = [sample for sample in post if not sample.fit_included]
        self._pzt_decay_out_of_fit_points.setData(
            [sample.timestamp_s - plot_origin_s for sample in outside],
            [sample.voltage_v for sample in outside],
        )
        included = [sample for sample in post if sample.fit_included]
        self._pzt_decay_fit_points.setData(
            [sample.timestamp_s - plot_origin_s for sample in included],
            [sample.voltage_v for sample in included],
        )
        if analyzer.vmid_v is not None:
            amplitude_v = analyzer.initial_amplitude_v or analyzer.settings.excitation_above_vmid_v
            marker_top_v = analyzer.vmid_v + max(0.002, 0.04 * amplitude_v)
            burst_ends = [
                sample for sample in post
                if sample.repeat_index == analyzer.timing.repeat_count - 1
            ]
            marker_x: list[float] = []
            marker_y: list[float] = []
            for sample in burst_ends:
                x_end = sample.timestamp_s - plot_origin_s
                # NaN ends each short tick so pyqtgraph does not connect one
                # burst marker to the next.
                marker_x.extend((x_end, x_end, np.nan))
                marker_y.extend((analyzer.vmid_v, marker_top_v, np.nan))
            self._pzt_decay_burst_end_markers.setData(marker_x, marker_y)
        else:
            self._pzt_decay_burst_end_markers.setData([], [])
        if analyzer.state == PztDecayState.BASELINE:
            self.pzt_decay_result_label.setText(
                f"Calculating Vmid: using {len(analyzer.baseline_values):,} / "
                f"{PZT_DECAY_VMID_REPEAT_COUNT - PZT_DECAY_VMID_DISCARD_INITIAL_SAMPLES} samples "
                f"after discarding the first {PZT_DECAY_VMID_DISCARD_INITIAL_SAMPLES} / "
                f"{PZT_DECAY_VMID_REPEAT_COUNT}. Do not apply voltage or force."
            )
        elif analyzer.state == PztDecayState.WAITING_FOR_TARGET and analyzer.target_voltage_v is not None:
            if not self.pzt_decay_active:
                self.pzt_decay_result_label.setText(
                    f"Vmid = {analyzer.vmid_v:.4f} V. Apply {analyzer.target_voltage_v:.4f} V, then press Start."
                )
            else:
                self.pzt_decay_result_label.setText(
                    f"Vmid = {analyzer.vmid_v:.4f} V. Apply {analyzer.target_voltage_v:.4f} V "
                    f"(Vmid + {self.pzt_decay_excitation_spin.value():.4f} V). Measurement starts automatically when stable."
                )
        elif analyzer.state == PztDecayState.WAITING_FOR_RELEASE:
            self.pzt_decay_result_label.setText("Target stable. Remove the applied voltage now; decay recording is automatic.")
        elif analyzer.state == PztDecayState.RECORDING_DECAY:
            self.pzt_decay_result_label.setText("Initial voltage found. Recording decay until it reaches Vmid + 2% of the excitation.")
        elif analyzer.state not in (PztDecayState.COMPLETE, PztDecayState.ERROR):
            self.pzt_decay_result_label.setText(f"State: {analyzer.state.value}.")

    def _reset_pzt_decay_plot(self) -> None:
        """Clear prior data and reset the next run's time axis to zero."""
        self._pzt_decay_measured_curve.setData([], [])
        self._pzt_decay_fit_curve.setData([], [])
        self._pzt_decay_out_of_fit_points.setData([], [])
        self._pzt_decay_fit_points.setData([], [])
        self._pzt_decay_burst_end_markers.setData([], [])
        self._pzt_decay_fit_upper_line.hide(); self._pzt_decay_fit_lower_line.hide()
        self.pzt_decay_plot.setXRange(0.0, self.pzt_decay_duration_spin.value(), padding=0.0)

    def cancel_pzt_decay_characterization(self) -> None:
        if self.pzt_decay_analyzer: self.pzt_decay_analyzer.cancel()
        self._finish_pzt_decay_capture()

    def _finish_pzt_decay_capture(self, error: str | None = None) -> None:
        mode = self._pzt_decay_mode
        was_active = self.pzt_decay_active; self.pzt_decay_active = False
        self._pzt_decay_watchdog.stop()
        self._pzt_decay_dense_sampling_pending = False
        self._pzt_decay_dense_sampling_active = False
        self._pzt_decay_last_sample_monotonic = None
        if was_active:
            try: self.send_command_and_wait_ack("stop", None, timeout=0.3, max_retries=1)
            except Exception: pass
        if self.serial_thread: self.serial_thread.set_capturing(False)
        self.is_capturing = False
        snapshot = self._pzt_decay_config_snapshot
        if snapshot is not None:
            self.config.update({key: getattr(snapshot, key) for key in snapshot.__dataclass_fields__})
            # Restore hardware configuration values but intentionally do not restart normal capture.
            channels = ",".join(str(value) for value in snapshot.channels)
            restore_ground = f"ground {snapshot.ground_pin}" if snapshot.use_ground and snapshot.ground_pin >= 0 else "ground false"
            restore_buffer = self._pzt_decay_control_snapshot.get("buffer", 1) if self._pzt_decay_control_snapshot else 1
            for command in (f"mode {snapshot.array_operation_mode}" if self.is_array_pzt_pzr_mode() else None,
                            f"osr {snapshot.osr}", f"gain {snapshot.gain}", f"channels {channels}" if channels else None,
                            f"repeat {snapshot.repeat}", restore_ground, f"buffer {restore_buffer}"):
                if command:
                    try: self.send_command_and_wait_ack(command, None, timeout=0.3, max_retries=1)
                    except Exception: pass
        if hasattr(self, "drain_serial_input"):
            try: self.drain_serial_input(0.05)
            except Exception: pass
        self.set_controls_enabled(True)
        selected_signal = self.pzt_decay_signal_combo.currentText()
        try:
            selected_signal_key = self._selected_pzt_decay_mapping().logical_signal
        except Exception:
            selected_signal_key = selected_signal
        has_vmid = selected_signal_key in self.pzt_decay_vmid_by_signal
        self.pzt_decay_calculate_vmid_btn.setEnabled(True)
        self._set_pzt_decay_measurement_controls(has_vmid)
        self.pzt_decay_cancel_btn.setEnabled(False)
        self.pzt_decay_save_btn.setEnabled(self.pzt_decay_result is not None)
        if self.pzt_decay_result:
            result = self.pzt_decay_result
            # Set the terminal status before rendering.  A rendering problem
            # must never make a completed/saved characterization look active.
            self.pzt_decay_result_label.setText(
                f"{result.quality_status}: τwall={result.tau_wall_s:.6g} s; "
                f"τon={result.tau_on_estimated_s:.6g} s; R²={result.r_squared:.5f}; "
                f"RMSE={result.rmse_voltage_v:.6g} V."
            )
            try:
                self._update_pzt_decay_plot()
            except Exception as exc:
                self.log_status(f"PZT decay result completed, but the final plot refresh failed: {exc}")
            lower = result.vmid_v + 0.02 * result.initial_amplitude_v
            upper = result.plateau_voltage_v - 0.10 * result.initial_amplitude_v
            if upper > lower:
                self.pzt_decay_plot.setYRange(lower, upper, padding=0.0)
            # Use the same final-event selection as the renderer.  The raw
            # capture can contain earlier recharge events and a long target
            # plateau; neither belongs in this completed decay view.
            visible_samples, plot_origin_s = self._pzt_decay_display_samples()
            visible_x = [sample.timestamp_s - plot_origin_s for sample in visible_samples]
            x_min = min(visible_x, default=0.0)
            x_max = max(visible_x, default=1e-6)
            self.pzt_decay_plot.setXRange(x_min, max(x_max, x_min + 1e-6), padding=0.05)
        elif mode == "vmid" and has_vmid:
            self._update_pzt_decay_plot()
            vmid_v, _ = self.pzt_decay_vmid_by_signal[selected_signal_key]
            self._update_pzt_decay_required_voltage()
            # A completed Vmid calculation must always release the per-signal
            # settings and Start button, even if the combo display text differs
            # from the logical mapping key used by the Vmid cache.
            self._set_pzt_decay_measurement_controls(True)
            self.pzt_decay_result_label.setText(
                f"Vmid calculated for {selected_signal}: {vmid_v:.4f} V. "
                f"Apply {vmid_v + self.pzt_decay_excitation_spin.value():.4f} V, then press Start."
            )
        elif error:
            self._update_pzt_decay_plot()
            prefix = "" if error.startswith("Warning:") else "Error: "
            self.pzt_decay_result_label.setText(f"{prefix}{error}")
        else:
            self._update_pzt_decay_plot()
            self.pzt_decay_result_label.setText("Characterization cancelled. Normal capture remains stopped.")
        self._pzt_decay_mode = None
        self.log_status("PZT decay characterization ended; normal capture remains stopped.")

    def save_pzt_decay_result(self) -> None:
        if not self.pzt_decay_result or not self.pzt_decay_analyzer: return
        directory = Path(self.dir_input.text()) if hasattr(self, "dir_input") else Path.cwd()
        try:
            paths = PztDecayExporter().export(directory, self.pzt_decay_result, self.pzt_decay_analyzer.samples)
            self.log_status(f"PZT decay result saved: {paths['result_json']}")
        except Exception as exc:
            QMessageBox.warning(self, "PZT decay save", str(exc))

    def open_pzt_decay_result_folder(self) -> None:
        directory = Path(self.dir_input.text()) if hasattr(self, "dir_input") else Path.cwd()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
