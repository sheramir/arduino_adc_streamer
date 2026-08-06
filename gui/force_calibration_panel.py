"""
Force Calibration Panel Mixin
==============================
GUI components for the Force Calibration tab.
Allows users to measure and persist force-sensor calibration rows.
"""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QFileDialog, QHeaderView
)
from PyQt6.QtCore import Qt

from constants.force import (
    FORCE_CALIBRATION_SETTINGS_DIRNAME,
    FORCE_CALIBRATION_SETTINGS_SUBDIR,
)
from data_processing.force_calibration_state import (
    build_default_force_calibration_state,
    CalibrationRow,
    ForceCalibrationSignalSource,
    get_calibration_rows_for_family,
)
from file_operations.settings_persistence import save_settings_payload, load_settings_payload


class ForceCalibrationPanelMixin:
    """Mixin for Force Calibration tab and workflow."""

    _FORCE_CALIBRATION_SENSOR_ORDER = ("T", "B", "R", "L", "C")
    _FORCE_CALIBRATION_SIGNAL_SOURCE_CHOICES = (
        ("raw", "Raw Piezo"),
        ("heatmap", "Heatmap Signals"),
        ("pressure_shear", "Pressure/Shear Signals"),
    )
    _FORCE_CALIBRATION_SIGNAL_SOURCE_LABELS = {
        "raw": "Raw",
        "heatmap": "Heatmap",
        "pressure_shear": "Pressure/Shear",
    }
    
    def create_force_calibration_tab(self) -> QWidget:
        """Create the Force Calibration tab widget.
        
        Returns:
            QWidget containing controls and calibration table.
        """
        self._force_calibration_settings_loading = False
        self._force_calibration_autosave_enabled = True
        
        tab = QWidget()
        tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(tab)
        
        # Controls group
        controls_group = QGroupBox("Calibration Controls")
        controls_layout = QGridLayout(controls_group)
        
        # Sensor family selector
        controls_layout.addWidget(QLabel("Sensor Family:"), 0, 0)
        self.force_calib_family_combo = QComboBox()
        self.force_calib_family_combo.addItems(["PZT", "PZR", "Rosette"])
        self.force_calib_family_combo.setCurrentText("PZT")
        self.force_calib_family_combo.currentTextChanged.connect(self._on_force_calib_family_changed)
        controls_layout.addWidget(self.force_calib_family_combo, 0, 1)
        
        # Sensor number selector
        controls_layout.addWidget(QLabel("Sensor Number:"), 0, 2)
        self.force_calib_sensor_number_spin = QSpinBox()
        self.force_calib_sensor_number_spin.setRange(1, 16)
        self.force_calib_sensor_number_spin.setValue(1)
        controls_layout.addWidget(self.force_calib_sensor_number_spin, 0, 3)
        
        # Signal source selector
        controls_layout.addWidget(QLabel("Signal Source:"), 0, 4)
        self.force_calib_signal_source_combo = QComboBox()
        for source_key, source_label in self._FORCE_CALIBRATION_SIGNAL_SOURCE_CHOICES:
            self.force_calib_signal_source_combo.addItem(source_label, source_key)
        self.force_calib_signal_source_combo.setCurrentIndex(1)  # heatmap
        self.force_calib_signal_source_combo.currentIndexChanged.connect(self._on_force_calib_source_changed)
        controls_layout.addWidget(self.force_calib_signal_source_combo, 0, 5)
        
        # Start/Stop button
        self.force_calib_start_stop_btn = QPushButton("Start Measure")
        self.force_calib_start_stop_btn.setEnabled(False)  # Disabled until force is connected
        self.force_calib_start_stop_btn.clicked.connect(self._on_force_calib_start_stop_clicked)
        controls_layout.addWidget(self.force_calib_start_stop_btn, 1, 0, 1, 2)
        
        # Clear table button
        self.force_calib_clear_btn = QPushButton("Clear Table")
        self.force_calib_clear_btn.clicked.connect(self._on_force_calib_clear_clicked)
        controls_layout.addWidget(self.force_calib_clear_btn, 1, 2, 1, 2)
        
        # Save/Load buttons
        self.force_calib_save_btn = QPushButton("Save Calibration")
        self.force_calib_save_btn.clicked.connect(self._on_force_calib_save_clicked)
        controls_layout.addWidget(self.force_calib_save_btn, 1, 4)
        
        self.force_calib_load_btn = QPushButton("Load Calibration")
        self.force_calib_load_btn.clicked.connect(self._on_force_calib_load_clicked)
        controls_layout.addWidget(self.force_calib_load_btn, 1, 5)
        
        layout.addWidget(controls_group)
        
        # Status label
        self.force_calib_status_label = QLabel("Disconnected - No force sensor connected")
        self.force_calib_status_label.setStyleSheet("color: orange; font-weight: bold;")
        layout.addWidget(self.force_calib_status_label)
        
        # Calibration table
        self.force_calib_table = QTableWidget()
        self.force_calib_table.setColumnCount(11)
        self._set_force_calibration_table_headers()
        self.force_calib_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.force_calib_table.setMaximumHeight(300)
        layout.addWidget(self.force_calib_table)
        
        layout.addStretch()
        return tab
    
    def init_force_calibration_state(self):
        """Initialize force calibration state during app startup."""
        self.force_calibration_state = build_default_force_calibration_state()
        self.force_calibration_state.selected_signal_source = "heatmap"
        self._force_calibration_settings_loading = False
        self._force_calibration_autosave_enabled = True

    def _normalize_force_calibration_signal_source(self, source_key: str | None) -> ForceCalibrationSignalSource:
        normalized = str(source_key or "").strip().lower()
        if normalized not in {"raw", "heatmap", "pressure_shear"}:
            return "heatmap"
        return normalized

    def _get_selected_force_calibration_signal_source(self) -> ForceCalibrationSignalSource:
        combo = getattr(self, "force_calib_signal_source_combo", None)
        if combo is None:
            return self._normalize_force_calibration_signal_source(self.force_calibration_state.selected_signal_source)
        return self._normalize_force_calibration_signal_source(str(combo.currentData() or ""))

    def _set_force_calibration_table_headers(self) -> None:
        self.force_calib_table.setHorizontalHeaderLabels([
            "Sensor",
            "Source",
            "T",
            "B",
            "L",
            "R",
            "C",
            "Total",
            "Shear T-B",
            "Shear L-R",
            "Timestamp",
        ])

    def _get_force_calibration_rows_for_current_family(self):
        return get_calibration_rows_for_family(
            self.force_calibration_state,
            self.force_calibration_state.selected_sensor_family,
        )

    def _get_force_calibration_rows_for_current_view(self):
        return self._get_force_calibration_rows_for_current_family()

    def _sensor_values_to_calibration_fields(self, sensor_values):
        values = [float(value) for value in (sensor_values or [])]
        normalized = values + [0.0] * max(0, 5 - len(values))
        sensor_map = dict(zip(self._FORCE_CALIBRATION_SENSOR_ORDER, normalized[:5]))
        return (
            sensor_map["T"],
            sensor_map["B"],
            sensor_map["L"],
            sensor_map["R"],
            sensor_map["C"],
            sum(normalized[:5]),
        )

    def _create_live_calibration_row(self):
        top, bottom, left, right, center, total = self._sensor_values_to_calibration_fields([])
        return CalibrationRow(
            sensor_family=self.force_calibration_state.selected_sensor_family,
            sensor_number=self.force_calibration_state.selected_sensor_number,
            signal_source=self._get_selected_force_calibration_signal_source(),
            sensor_top=top,
            sensor_bottom=bottom,
            sensor_left=left,
            sensor_right=right,
            sensor_center=center,
            sensor_total=total,
        )

    def _sync_active_row_with_latest_values(self):
        if not self.force_calibration_state.is_capturing:
            return

        rows = self._get_force_calibration_rows_for_current_family()
        active_row_index = self.force_calibration_state.active_row_index
        if active_row_index is None or active_row_index >= len(rows):
            return

        row = rows[active_row_index]
        latest_values = self.force_calibration_state.active_measurement_window.latest_sensor_values
        top, bottom, left, right, center, total = self._sensor_values_to_calibration_fields(latest_values)
        row.sensor_top = top
        row.sensor_bottom = bottom
        row.sensor_left = left
        row.sensor_right = right
        row.sensor_center = center
        row.sensor_total = total
        row.max_force_z = self.force_calibration_state.active_measurement_window.get_max_force_z()
        row.max_force_x = self.force_calibration_state.active_measurement_window.get_max_force_x()
        self._on_force_calib_table_refresh()

    def _get_force_calibration_selected_package_index(self) -> int:
        return max(0, int(self.force_calibration_state.selected_sensor_number) - 1)

    def _select_force_calibration_package_values(self, package_values_by_id: dict[str, dict[str, float]]) -> tuple[str, dict[str, float]] | None:
        if not package_values_by_id:
            return None
        package_ids = list(package_values_by_id.keys())
        selected_index = min(self._get_force_calibration_selected_package_index(), len(package_ids) - 1)
        package_id = package_ids[selected_index]
        return package_id, package_values_by_id[package_id]

    def _resolve_force_calibration_heatmap_sensor_values(self) -> list[float] | None:
        if not hasattr(self, "compute_channel_intensities") or not hasattr(self, "get_heatmap_settings"):
            return None
        settings = self.get_heatmap_settings()
        package_sensor_values = self.compute_channel_intensities(settings)
        if not package_sensor_values:
            return None
        selected_index = min(self._get_force_calibration_selected_package_index(), len(package_sensor_values) - 1)
        return list(package_sensor_values[selected_index])

    def _resolve_force_calibration_raw_sensor_values(self) -> list[float] | None:
        if not hasattr(self, "_get_signal_integration_raw_snapshot") or not hasattr(self, "get_display_channel_specs"):
            return None
        snapshot = self._get_signal_integration_raw_snapshot()
        if snapshot is None:
            return None

        data_array, _timestamps, _visible_start_time_sec = snapshot
        if data_array.size == 0:
            return None

        latest_sweep = data_array[-1]
        display_specs = self.get_display_channel_specs() or []
        if not display_specs:
            return None

        channel_map = self.get_active_channel_sensor_map() if hasattr(self, "get_active_channel_sensor_map") else []
        package_values_by_id: dict[str, dict[str, list[float]]] = {}
        package_order: list[str] = []
        for spec_index, spec in enumerate(display_specs):
            if not isinstance(spec, dict):
                continue
            position = None
            if hasattr(self, "_get_heatmap_position_for_display_spec"):
                position = self._get_heatmap_position_for_display_spec(spec, spec_index, channel_map)
            if position not in self._FORCE_CALIBRATION_SENSOR_ORDER:
                continue

            sample_indices = [
                int(sample_index)
                for sample_index in spec.get("sample_indices", [])
                if 0 <= int(sample_index) < latest_sweep.shape[0]
            ]
            if not sample_indices:
                continue

            if hasattr(self, "_get_signal_integration_package_id_for_display_spec"):
                package_id = self._get_signal_integration_package_id_for_display_spec(spec, spec_index)
            else:
                package_id = f"PACKAGE{(spec_index // len(self._FORCE_CALIBRATION_SENSOR_ORDER)) + 1}"

            package_id = str(package_id).strip().upper() or "PACKAGE1"
            if package_id not in package_values_by_id:
                package_values_by_id[package_id] = {label: [] for label in self._FORCE_CALIBRATION_SENSOR_ORDER}
                package_order.append(package_id)

            raw_value = float(latest_sweep[sample_indices].mean())
            package_values_by_id[package_id][position].append(raw_value)

        if not package_order:
            return None

        collapsed: dict[str, dict[str, float]] = {}
        for package_id in package_order:
            values_for_package = package_values_by_id[package_id]
            collapsed[package_id] = {
                label: (sum(values_for_package[label]) / len(values_for_package[label])) if values_for_package[label] else 0.0
                for label in self._FORCE_CALIBRATION_SENSOR_ORDER
            }

        selected = self._select_force_calibration_package_values(collapsed)
        if selected is None:
            return None
        _package_id, values = selected
        return [
            float(values.get("T", 0.0)),
            float(values.get("B", 0.0)),
            float(values.get("R", 0.0)),
            float(values.get("L", 0.0)),
            float(values.get("C", 0.0)),
        ]

    def _resolve_force_calibration_pressure_shear_sensor_values(self) -> tuple[list[float], float, float] | None:
        if not hasattr(self, "_get_signal_integration_raw_snapshot") or not hasattr(self, "get_display_channel_specs"):
            return None
        snapshot = self._get_signal_integration_raw_snapshot()
        if snapshot is None:
            return None

        data_array, timestamps_array, visible_start_time_sec = snapshot
        display_specs = self.get_display_channel_specs() or []
        if not display_specs:
            return None

        avg_sample_time_sec = float(getattr(self, "_cached_avg_sample_time_sec", 0.0) or 0.0)
        if avg_sample_time_sec <= 0.0:
            return None

        package_values: dict[str, dict[str, float]] = {}
        for spec_index, spec in enumerate(display_specs):
            if not isinstance(spec, dict):
                continue
            position = self._get_shear_position_for_display_spec(spec, spec_index) if hasattr(self, "_get_shear_position_for_display_spec") else None
            if position not in self._FORCE_CALIBRATION_SENSOR_ORDER:
                continue

            prepared = self._prepare_signal_integration_integrated_series(
                spec,
                data_array,
                timestamps_array,
                avg_sample_time_sec,
                max_samples_per_series=1,
                visible_start_time_sec=visible_start_time_sec,
            )
            if prepared is None:
                continue
            _channel_data, _channel_times, latest_value = prepared
            if latest_value is None:
                continue

            if hasattr(self, "_get_signal_integration_package_id_for_display_spec"):
                package_id = self._get_signal_integration_package_id_for_display_spec(spec, spec_index)
            else:
                package_id = f"PACKAGE{(spec_index // len(self._FORCE_CALIBRATION_SENSOR_ORDER)) + 1}"
            package_id = str(package_id).strip().upper() or "PACKAGE1"
            package_values.setdefault(package_id, {})[str(position)] = float(latest_value)

        selected = self._select_force_calibration_package_values(package_values)
        if selected is None:
            return None

        package_id, latest_values = selected
        if hasattr(self, "_calibrate_signal_integration_values_for_shear"):
            calibrated_values = self._calibrate_signal_integration_values_for_shear(latest_values, package_id)
        else:
            calibrated_values = latest_values

        shear_tb = 0.0
        shear_lr = 0.0
        if hasattr(self, "shear_detector"):
            try:
                shear_result = self.shear_detector.detect(calibrated_values)
                shear_tb = float(getattr(shear_result, "b_tb", 0.0))
                shear_lr = float(getattr(shear_result, "b_lr", 0.0))
            except Exception:
                shear_tb = 0.0
                shear_lr = 0.0

        return (
            [
                float(calibrated_values.get("T", 0.0)),
                float(calibrated_values.get("B", 0.0)),
                float(calibrated_values.get("R", 0.0)),
                float(calibrated_values.get("L", 0.0)),
                float(calibrated_values.get("C", 0.0)),
            ],
            shear_tb,
            shear_lr,
        )

    def _resolve_force_calibration_live_sensor_values(self) -> tuple[list[float], float | None, float | None] | None:
        signal_source = self._get_selected_force_calibration_signal_source()
        if signal_source == "raw":
            raw_values = self._resolve_force_calibration_raw_sensor_values()
            return None if raw_values is None else (raw_values, None, None)
        if signal_source == "pressure_shear":
            return self._resolve_force_calibration_pressure_shear_sensor_values()
        heatmap_values = self._resolve_force_calibration_heatmap_sensor_values()
        return None if heatmap_values is None else (heatmap_values, None, None)

    def update_force_calibration_live_reading_from_selected_source(self) -> None:
        resolved_values = self._resolve_force_calibration_live_sensor_values()
        if resolved_values is None:
            return
        sensor_values, shear_tb, shear_lr = resolved_values
        self.update_force_calibration_live_reading(sensor_values, shear_tb=shear_tb, shear_lr=shear_lr)

    def update_force_calibration_live_reading(self, sensor_values, shear_tb: float | None = None, shear_lr: float | None = None):
        """Update the current live calibration row from selected signal-source values."""
        if not self.force_calibration_state.is_capturing:
            return

        top, bottom, left, right, center, total = self._sensor_values_to_calibration_fields(sensor_values)
        # Stored in _FORCE_CALIBRATION_SENSOR_ORDER (T, B, R, L, C) so that
        # _sync_active_row_with_latest_values decodes it with the same convention.
        self.force_calibration_state.active_measurement_window.update_live_sensor_values(
            [top, bottom, right, left, center],
            total_value=total,
        )
        if shear_tb is not None:
            self.force_calibration_state.active_measurement_window.force_z_peaks.append(float(shear_tb))
        if shear_lr is not None:
            self.force_calibration_state.active_measurement_window.force_x_peaks.append(float(shear_lr))
        self._sync_active_row_with_latest_values()
    
    def enable_force_calibration_start_stop(self, enabled: bool):
        """Enable/disable the start/stop button based on force connection."""
        if hasattr(self, "force_calib_start_stop_btn"):
            self.force_calib_start_stop_btn.setEnabled(enabled)
            self.force_calib_start_stop_btn.setText("Start Measure" if not self.force_calibration_state.is_capturing else "Stop Measure")
            if enabled:
                self.force_calib_status_label.setText("Connected - Ready to measure")
                self.force_calib_status_label.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.force_calib_status_label.setText("Disconnected - No force sensor connected")
                self.force_calib_status_label.setStyleSheet("color: orange; font-weight: bold;")
    
    def _on_force_calib_family_changed(self, family: str):
        """Handle sensor family selection change."""
        self.force_calibration_state.selected_sensor_family = family
        self._on_force_calib_table_refresh()
        if not getattr(self, "_force_calibration_settings_loading", False):
            self.save_force_calibration_last_state()

    def _on_force_calib_source_changed(self, _index: int):
        """Handle signal-source selection change."""
        self.force_calibration_state.selected_signal_source = self._get_selected_force_calibration_signal_source()
        self._on_force_calib_table_refresh()
        if not getattr(self, "_force_calibration_settings_loading", False):
            self.save_force_calibration_last_state()
    
    def _on_force_calib_start_stop_clicked(self):
        """Toggle measurement capture."""
        port = getattr(self, "force_serial_port", None)
        
        if port is None or not getattr(port, "is_open", False):
            self.log_status("ERROR: Force sensor not connected")
            return
        
        if self.force_calibration_state.is_capturing:
            # Stop measurement
            self._stop_force_calibration_measurement()
        else:
            # Start measurement
            self._start_force_calibration_measurement()
    
    def _start_force_calibration_measurement(self):
        """Begin a new measurement window."""
        self.force_calibration_state.is_capturing = True
        self.force_calibration_state.active_measurement_window.reset()
        self.force_calibration_state.selected_signal_source = self._get_selected_force_calibration_signal_source()
        self.force_calibration_state.active_row_index = len(self._get_force_calibration_rows_for_current_family())
        self._get_force_calibration_rows_for_current_family().append(self._create_live_calibration_row())
        self.force_calib_start_stop_btn.setText("Stop Measure")
        self.force_calib_family_combo.setEnabled(False)
        self.force_calib_signal_source_combo.setEnabled(False)
        self.force_calib_sensor_number_spin.setEnabled(False)
        self._on_force_calib_table_refresh()
        self.log_status(
            f"Started measuring {self.force_calibration_state.selected_sensor_family} "
            f"sensor {self.force_calibration_state.selected_sensor_number} "
            f"using {self._FORCE_CALIBRATION_SIGNAL_SOURCE_LABELS.get(self.force_calibration_state.selected_signal_source, 'Signal')}..."
        )
    
    def _stop_force_calibration_measurement(self):
        """End measurement and commit a new row."""
        self.force_calibration_state.is_capturing = False
        self.force_calib_start_stop_btn.setText("Start Measure")
        self.force_calib_family_combo.setEnabled(True)
        self.force_calib_signal_source_combo.setEnabled(True)
        self.force_calib_sensor_number_spin.setEnabled(True)
        
        window = self.force_calibration_state.active_measurement_window
        if not window.latest_sensor_values:
            rows = self._get_force_calibration_rows_for_current_family()
            if self.force_calibration_state.active_row_index is not None and self.force_calibration_state.active_row_index < len(rows):
                rows.pop(self.force_calibration_state.active_row_index)
            self.force_calibration_state.active_row_index = None
            self._on_force_calib_table_refresh()
            self.log_status("WARNING: No sensor data captured during measurement")
            return
        
        rows = self._get_force_calibration_rows_for_current_family()
        active_row_index = self.force_calibration_state.active_row_index
        if active_row_index is None or active_row_index >= len(rows):
            self.log_status("WARNING: Could not finalize calibration row")
            return

        row = rows[active_row_index]
        row.timestamp = time.time()
        
        self.force_calibration_state.active_row_index = None
        self._on_force_calib_table_refresh()
        self.log_status(
            f"Captured calibration row: "
            f"{self._FORCE_CALIBRATION_SIGNAL_SOURCE_LABELS.get(row.signal_source, 'Signal')} | "
            f"T={row.sensor_top:.2f}, B={row.sensor_bottom:.2f}, L={row.sensor_left:.2f}, "
            f"R={row.sensor_right:.2f}, C={row.sensor_center:.2f}, Total={row.sensor_total:.2f}"
        )
        self.save_force_calibration_last_state()
    
    def _on_force_calib_table_refresh(self):
        """Repopulate the calibration table from state."""
        rows = self._get_force_calibration_rows_for_current_view()
        self._set_force_calibration_table_headers()
        
        self.force_calib_table.setRowCount(len(rows))
        for idx, row in enumerate(rows):
            sensor_label = f"{row.sensor_family} {row.sensor_number}"
            self.force_calib_table.setItem(idx, 0, QTableWidgetItem(sensor_label))
            normalized_source = self._normalize_force_calibration_signal_source(getattr(row, "signal_source", "heatmap"))
            source_label = self._FORCE_CALIBRATION_SIGNAL_SOURCE_LABELS.get(normalized_source, "Signal")
            self.force_calib_table.setItem(idx, 1, QTableWidgetItem(source_label))
            self.force_calib_table.setItem(idx, 2, QTableWidgetItem(f"{row.sensor_top:.4f}"))
            self.force_calib_table.setItem(idx, 3, QTableWidgetItem(f"{row.sensor_bottom:.4f}"))
            self.force_calib_table.setItem(idx, 4, QTableWidgetItem(f"{row.sensor_left:.4f}"))
            self.force_calib_table.setItem(idx, 5, QTableWidgetItem(f"{row.sensor_right:.4f}"))
            self.force_calib_table.setItem(idx, 6, QTableWidgetItem(f"{row.sensor_center:.4f}"))
            self.force_calib_table.setItem(idx, 7, QTableWidgetItem(f"{row.sensor_total:.4f}"))
            self.force_calib_table.setItem(idx, 8, QTableWidgetItem(f"{row.max_force_z:.4f}"))
            self.force_calib_table.setItem(idx, 9, QTableWidgetItem(f"{row.max_force_x:.4f}"))
            ts = f"{row.timestamp:.0f}" if row.timestamp else "—"
            self.force_calib_table.setItem(idx, 10, QTableWidgetItem(ts))
    
    def _on_force_calib_clear_clicked(self):
        """Clear the calibration table for the selected family."""
        family = self.force_calibration_state.selected_sensor_family
        rows = get_calibration_rows_for_family(self.force_calibration_state, family)
        rows.clear()
        self._on_force_calib_table_refresh()
        self.log_status(f"Cleared {family} calibration table")
        self.save_force_calibration_last_state()
    
    def _on_force_calib_save_clicked(self):
        """Save calibration to file."""
        family = self.force_calibration_state.selected_sensor_family
        default_dir = Path.home() / FORCE_CALIBRATION_SETTINGS_DIRNAME / FORCE_CALIBRATION_SETTINGS_SUBDIR
        default_name = f"force_calibration_{family.lower()}.json"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Force Calibration", 
            str(default_dir / default_name), 
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            self.save_force_calibration_to_path(file_path, log_message=True)
    
    def _on_force_calib_load_clicked(self):
        """Load calibration from file."""
        default_dir = Path.home() / FORCE_CALIBRATION_SETTINGS_DIRNAME / FORCE_CALIBRATION_SETTINGS_SUBDIR
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Force Calibration",
            str(default_dir),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            self.load_force_calibration_from_path(file_path, log_message=True)
    
    def save_force_calibration_to_path(self, file_path, log_message=True):
        """Persist calibration to a file."""
        payload = {
            "version": 2,
            "ui_state": {
                "selected_signal_source": self._get_selected_force_calibration_signal_source(),
            },
            "calibrations": {
                "PZT": [
                    {
                        "sensor_number": row.sensor_number,
                        "signal_source": getattr(row, "signal_source", "heatmap"),
                        "sensor_top": row.sensor_top,
                        "sensor_bottom": row.sensor_bottom,
                        "sensor_left": row.sensor_left,
                        "sensor_right": row.sensor_right,
                        "sensor_center": row.sensor_center,
                        "sensor_total": row.sensor_total,
                        "max_force_x": row.max_force_x,
                        "max_force_z": row.max_force_z,
                        "max_sensor_value": row.max_sensor_value,
                        "min_sensor_value": row.min_sensor_value,
                        "integration_samples": row.integration_samples,
                        "timestamp": row.timestamp,
                    }
                    for row in self.force_calibration_state.pzt_calibration_rows
                ],
                "PZR": [
                    {
                        "sensor_number": row.sensor_number,
                        "signal_source": getattr(row, "signal_source", "heatmap"),
                        "sensor_top": row.sensor_top,
                        "sensor_bottom": row.sensor_bottom,
                        "sensor_left": row.sensor_left,
                        "sensor_right": row.sensor_right,
                        "sensor_center": row.sensor_center,
                        "sensor_total": row.sensor_total,
                        "max_force_x": row.max_force_x,
                        "max_force_z": row.max_force_z,
                        "max_sensor_value": row.max_sensor_value,
                        "min_sensor_value": row.min_sensor_value,
                        "integration_samples": row.integration_samples,
                        "timestamp": row.timestamp,
                    }
                    for row in self.force_calibration_state.pzr_calibration_rows
                ],
                "Rosette": [
                    {
                        "sensor_number": row.sensor_number,
                        "signal_source": getattr(row, "signal_source", "heatmap"),
                        "sensor_top": row.sensor_top,
                        "sensor_bottom": row.sensor_bottom,
                        "sensor_left": row.sensor_left,
                        "sensor_right": row.sensor_right,
                        "sensor_center": row.sensor_center,
                        "sensor_total": row.sensor_total,
                        "max_force_x": row.max_force_x,
                        "max_force_z": row.max_force_z,
                        "max_sensor_value": row.max_sensor_value,
                        "min_sensor_value": row.min_sensor_value,
                        "integration_samples": row.integration_samples,
                        "timestamp": row.timestamp,
                    }
                    for row in self.force_calibration_state.rosette_calibration_rows
                ],
            }
        }
        
        save_settings_payload(
            file_path,
            payload,
            log_callback=self.log_status if log_message else None,
            success_message="Saved force calibration: {path}",
        )
    
    def load_force_calibration_from_path(self, file_path, log_message=True):
        """Load calibration from file."""
        path, payload = load_settings_payload(file_path)
        
        self._force_calibration_settings_loading = True
        try:
            # Validate version
            version = payload.get("version", 1)
            if version not in (1, 2):
                self.log_status(f"WARNING: Unknown calibration file version: {payload.get('version')}")
                return

            ui_state = payload.get("ui_state", {}) if isinstance(payload.get("ui_state", {}), dict) else {}
            selected_source = self._normalize_force_calibration_signal_source(ui_state.get("selected_signal_source", "heatmap"))
            self.force_calibration_state.selected_signal_source = selected_source
            if hasattr(self, "force_calib_signal_source_combo"):
                selected_combo_index = self.force_calib_signal_source_combo.findData(selected_source)
                if selected_combo_index >= 0:
                    self.force_calib_signal_source_combo.blockSignals(True)
                    self.force_calib_signal_source_combo.setCurrentIndex(selected_combo_index)
                    self.force_calib_signal_source_combo.blockSignals(False)
            self._set_force_calibration_table_headers()
            
            calibrations = payload.get("calibrations", {})
            
            # Load each family
            self.force_calibration_state.pzt_calibration_rows.clear()
            for row_dict in calibrations.get("PZT", []):
                row = CalibrationRow(
                    sensor_family="PZT",
                    sensor_number=row_dict.get("sensor_number", 1),
                    signal_source=self._normalize_force_calibration_signal_source(row_dict.get("signal_source", "heatmap")),
                    sensor_top=row_dict.get("sensor_top", 0.0),
                    sensor_bottom=row_dict.get("sensor_bottom", 0.0),
                    sensor_left=row_dict.get("sensor_left", 0.0),
                    sensor_right=row_dict.get("sensor_right", 0.0),
                    sensor_center=row_dict.get("sensor_center", 0.0),
                    sensor_total=row_dict.get("sensor_total", 0.0),
                    max_force_x=row_dict.get("max_force_x", 0.0),
                    max_force_z=row_dict.get("max_force_z", 0.0),
                    max_sensor_value=row_dict.get("max_sensor_value", 0.0),
                    min_sensor_value=row_dict.get("min_sensor_value"),
                    integration_samples=row_dict.get("integration_samples", 0),
                    timestamp=row_dict.get("timestamp"),
                )
                self.force_calibration_state.pzt_calibration_rows.append(row)
            
            self.force_calibration_state.pzr_calibration_rows.clear()
            for row_dict in calibrations.get("PZR", []):
                row = CalibrationRow(
                    sensor_family="PZR",
                    sensor_number=row_dict.get("sensor_number", 1),
                    signal_source=self._normalize_force_calibration_signal_source(row_dict.get("signal_source", "heatmap")),
                    sensor_top=row_dict.get("sensor_top", 0.0),
                    sensor_bottom=row_dict.get("sensor_bottom", 0.0),
                    sensor_left=row_dict.get("sensor_left", 0.0),
                    sensor_right=row_dict.get("sensor_right", 0.0),
                    sensor_center=row_dict.get("sensor_center", 0.0),
                    sensor_total=row_dict.get("sensor_total", 0.0),
                    max_force_x=row_dict.get("max_force_x", 0.0),
                    max_force_z=row_dict.get("max_force_z", 0.0),
                    max_sensor_value=row_dict.get("max_sensor_value", 0.0),
                    min_sensor_value=row_dict.get("min_sensor_value"),
                    integration_samples=row_dict.get("integration_samples", 0),
                    timestamp=row_dict.get("timestamp"),
                )
                self.force_calibration_state.pzr_calibration_rows.append(row)
            
            self.force_calibration_state.rosette_calibration_rows.clear()
            for row_dict in calibrations.get("Rosette", []):
                row = CalibrationRow(
                    sensor_family="Rosette",
                    sensor_number=row_dict.get("sensor_number", 1),
                    signal_source=self._normalize_force_calibration_signal_source(row_dict.get("signal_source", "heatmap")),
                    sensor_top=row_dict.get("sensor_top", 0.0),
                    sensor_bottom=row_dict.get("sensor_bottom", 0.0),
                    sensor_left=row_dict.get("sensor_left", 0.0),
                    sensor_right=row_dict.get("sensor_right", 0.0),
                    sensor_center=row_dict.get("sensor_center", 0.0),
                    sensor_total=row_dict.get("sensor_total", 0.0),
                    max_force_x=row_dict.get("max_force_x", 0.0),
                    max_force_z=row_dict.get("max_force_z", 0.0),
                    max_sensor_value=row_dict.get("max_sensor_value", 0.0),
                    min_sensor_value=row_dict.get("min_sensor_value"),
                    integration_samples=row_dict.get("integration_samples", 0),
                    timestamp=row_dict.get("timestamp"),
                )
                self.force_calibration_state.rosette_calibration_rows.append(row)
            
            self._on_force_calib_table_refresh()
            if log_message:
                self.log_status(f"Loaded force calibration: {path}")
        finally:
            self._force_calibration_settings_loading = False
    
    def save_force_calibration_last_state(self):
        """Autosave the current calibration state."""
        if not getattr(self, "_force_calibration_autosave_enabled", False) or getattr(self, "_force_calibration_settings_loading", False):
            return
        
        try:
            path = Path.home() / FORCE_CALIBRATION_SETTINGS_DIRNAME / FORCE_CALIBRATION_SETTINGS_SUBDIR / "last_used_force_calibration.json"
            self.save_force_calibration_to_path(path, log_message=False)
        except Exception as exc:
            self.log_status(f"WARNING: could not save last force calibration state: {exc}")
    
    def load_last_force_calibration_state(self):
        """Load the autosaved calibration state."""
        path = Path.home() / FORCE_CALIBRATION_SETTINGS_DIRNAME / FORCE_CALIBRATION_SETTINGS_SUBDIR / "last_used_force_calibration.json"
        if path.exists():
            try:
                self.load_force_calibration_from_path(path, log_message=False)
            except Exception as exc:
                self.log_status(f"WARNING: could not load last force calibration state: {exc}")
