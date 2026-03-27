"""
Sensor Panel GUI Component
==========================
Provides UI for selecting and editing named 5-channel sensor layouts and array configurations.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sensor_config import (
    ARRAY_CELL_CHANNELS_MAX,
    ARRAY_COLS,
    ARRAY_ROWS,
    SENSOR_POSITION_LABELS,
    SENSOR_POSITION_ORDER,
    SensorConfigStore,
    default_array_configuration,
    default_sensor_configuration,
    get_sensors_from_array_layout,
    mapping_to_position_channels,
    normalize_combined_sensor_config,
    normalize_array_config,
    normalize_array_cell,
    normalize_sensor_config,
    position_channels_to_mapping,
)


class SensorPanelMixin:
    """Mixin providing a Sensor tab for managing named sensor mappings."""

    def init_sensor_config_state(self):
        self.sensor_config_store = SensorConfigStore()
        self.sensor_configurations = []
        self.active_sensor_config_name = ""
        self._sensor_config_ui_loading = False
        self._load_sensor_configs_from_disk()

    def _load_sensor_configs_from_disk(self):
        configs, selected_name = self.sensor_config_store.load()
        self.sensor_configurations = configs
        self.active_sensor_config_name = selected_name

    def save_sensor_configurations(self, log_message=False):
        self.sensor_config_store.save(self.sensor_configurations, self.active_sensor_config_name)
        if log_message:
            self.log_status(f"Saved sensor configurations ({len(self.sensor_configurations)})")

    def get_active_sensor_configuration(self):
        for config in self.sensor_configurations:
            if config["name"] == self.active_sensor_config_name:
                return config
        fallback = default_sensor_configuration()
        return normalize_sensor_config(fallback) or fallback

    def get_active_channel_sensor_map(self):
        config = self.get_active_sensor_configuration()
        return list(config.get("channel_sensor_map", ["T", "R", "C", "L", "B"]))

    def get_active_array_layout(self) -> dict | None:
        """Get the active sensor config if it has a configured array attachment."""
        config = self.get_active_sensor_configuration()
        if get_sensors_from_array_layout(config.get("array_layout", {})):
            return config
        return None

    def get_active_array_sensors(self) -> set[str]:
        """Get all sensors configured in the active array layout."""
        config = self.get_active_array_layout()
        if config:
            return get_sensors_from_array_layout(config.get("array_layout", {}))
        return set()

    def create_sensor_tab(self):
        sensor_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # ============================================================
        # Configuration Selector
        # ============================================================
        selector_group = QGroupBox("Active Sensor Configuration")
        selector_layout = QVBoxLayout()

        form_layout = QFormLayout()
        self.sensor_config_combo = QComboBox()
        self.sensor_config_combo.currentIndexChanged.connect(self.on_sensor_config_selected)
        form_layout.addRow("Sensor:", self.sensor_config_combo)

        self.sensor_name_edit = QLineEdit()
        self.sensor_name_edit.editingFinished.connect(self.on_sensor_name_edited)
        form_layout.addRow("Name:", self.sensor_name_edit)
        selector_layout.addLayout(form_layout)

        # Configuration type selector
        type_layout = QFormLayout()
        self.sensor_type_combo = QComboBox()
        self.sensor_type_combo.addItem("Channel Layout", "channel_layout")
        self.sensor_type_combo.addItem("Array Layout", "array_layout")
        self.sensor_type_combo.currentIndexChanged.connect(self.on_sensor_type_changed)
        type_layout.addRow("Type:", self.sensor_type_combo)
        selector_layout.addLayout(type_layout)

        actions_layout = QHBoxLayout()
        self.sensor_add_btn = QPushButton("Add New")
        self.sensor_add_btn.clicked.connect(self.on_add_sensor_config_clicked)
        actions_layout.addWidget(self.sensor_add_btn)

        self.sensor_delete_btn = QPushButton("Delete")
        self.sensor_delete_btn.clicked.connect(self.on_delete_sensor_config_clicked)
        actions_layout.addWidget(self.sensor_delete_btn)
        
        self.sensor_save_btn = QPushButton("Save")
        self.sensor_save_btn.clicked.connect(self.on_save_sensor_config_clicked)
        actions_layout.addWidget(self.sensor_save_btn)
        
        actions_layout.addStretch()
        selector_layout.addLayout(actions_layout)

        selector_group.setLayout(selector_layout)
        layout.addWidget(selector_group)

        # ============================================================
        # Configuration Editor (Tab between channel/array layout)
        # ============================================================
        self.sensor_editor_tabs = QTabWidget()
        
        # Channel Layout Tab
        self.channel_layout_editor = self._create_channel_layout_editor()
        self.sensor_editor_tabs.addTab(self.channel_layout_editor, "Channel Layout")
        
        # Array Layout Tab
        self.array_layout_editor = self._create_array_layout_editor()
        self.sensor_editor_tabs.addTab(self.array_layout_editor, "Array Layout")
        self.sensor_editor_tabs.currentChanged.connect(self.on_sensor_editor_tab_changed)
        
        layout.addWidget(self.sensor_editor_tabs)

        # ============================================================
        # Status Label
        # ============================================================
        self.sensor_status_label = QLabel("")
        self.sensor_status_label.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(self.sensor_status_label)
        layout.addStretch()

        sensor_widget.setLayout(layout)
        self._refresh_sensor_tab_ui()
        return sensor_widget

    def _create_channel_layout_editor(self) -> QWidget:
        """Create the channel layout editor widget (5-position sensor mapping)."""
        editor_widget = QWidget()
        editor_layout = QVBoxLayout()
        editor_layout.addWidget(QLabel("Set which channel number (1-5) is at each sensor position."))

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(10)

        self.sensor_position_spins = {}
        positions = {
            "T": (0, 1),
            "L": (1, 0),
            "C": (1, 1),
            "R": (1, 2),
            "B": (2, 1),
        }
        for sensor_label, (row, col) in positions.items():
            cell = QWidget()
            cell_layout = QVBoxLayout()
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(4)

            title = QLabel(SENSOR_POSITION_LABELS[sensor_label])
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell_layout.addWidget(title)

            spin = QSpinBox()
            spin.setRange(1, 5)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setProperty("sensor_label", sensor_label)
            spin.setProperty("previous_value", 1)
            spin.valueChanged.connect(self.on_sensor_position_spin_changed)
            self.sensor_position_spins[sensor_label] = spin
            cell_layout.addWidget(spin)

            cell.setLayout(cell_layout)
            grid.addWidget(cell, row, col)

        editor_layout.addLayout(grid)

        self.sensor_mapping_preview_label = QLabel("")
        self.sensor_mapping_preview_label.setStyleSheet("font-family: monospace;")
        editor_layout.addWidget(self.sensor_mapping_preview_label)
        
        editor_layout.addStretch()
        editor_widget.setLayout(editor_layout)
        return editor_widget

    def _create_array_layout_editor(self) -> QWidget:
        """Create the array layout editor widget (3x4 matrix + MUX configuration)."""
        editor_widget = QWidget()
        editor_layout = QVBoxLayout()

        # ============================================================
        # Array Matrix Editor (3x3 grid)
        # ============================================================
        array_matrix_group = QGroupBox("Array Layout (3 columns × 3 rows)")
        array_matrix_layout = QVBoxLayout()
        array_matrix_layout.addWidget(QLabel("Configure sensor positions. Enter PZT1 or PZR1 (underscore is optional) or leave empty."))

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.array_matrix_cells = {}
        for row in range(ARRAY_ROWS):
            for col in range(ARRAY_COLS):
                cell_num = row * ARRAY_COLS + col + 1
                cell_widget = QLineEdit()
                cell_widget.setPlaceholderText(f"PZT{cell_num} / PZR{cell_num}")
                cell_widget.setToolTip(f"Enter PZT{cell_num} or PZR{cell_num} (or leave empty)")
                cell_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell_widget.setProperty("array_row", row)
                cell_widget.setProperty("array_col", col)
                cell_widget.editingFinished.connect(self.on_array_cell_edited)
                self.array_matrix_cells[(row, col)] = cell_widget
                grid.addWidget(cell_widget, row, col)

        array_matrix_layout.addLayout(grid)
        array_matrix_group.setLayout(array_matrix_layout)
        editor_layout.addWidget(array_matrix_group)

        # ============================================================
        # MUX Configuration Table
        # ============================================================
        mux_config_group = QGroupBox("MUX Configuration")
        mux_config_layout = QVBoxLayout()
        mux_config_layout.addWidget(QLabel("For each sensor, specify MUX and physical channels (0-15):"))

        self.array_mux_table = QTableWidget()
        self.array_mux_table.setColumnCount(3)
        self.array_mux_table.setHorizontalHeaderLabels(["Sensor", "MUX (1-2)", "Channels (comma-separated)"])
        self.array_mux_table.setMinimumHeight(150)
        self.array_mux_table.setColumnWidth(2, 320)
        self.array_mux_table.itemChanged.connect(self.on_array_mux_table_item_changed)
        mux_config_layout.addWidget(self.array_mux_table)

        self.array_mux_warning_label = QLabel("")
        self.array_mux_warning_label.setStyleSheet("color: red; font-weight: bold;")
        self.array_mux_warning_label.setWordWrap(True)
        mux_config_layout.addWidget(self.array_mux_warning_label)

        mux_config_group.setLayout(mux_config_layout)
        editor_layout.addWidget(mux_config_group)

        # ============================================================
        # Channels Per Sensor Configuration
        # ============================================================
        channels_per_sensor_layout = QFormLayout()
        self.array_channels_per_sensor = QSpinBox()
        self.array_channels_per_sensor.setRange(1, ARRAY_CELL_CHANNELS_MAX)
        self.array_channels_per_sensor.setValue(ARRAY_CELL_CHANNELS_MAX)
        self.array_channels_per_sensor.valueChanged.connect(self.on_array_channels_per_sensor_changed)
        channels_per_sensor_layout.addRow("Channels per Sensor:", self.array_channels_per_sensor)
        editor_layout.addLayout(channels_per_sensor_layout)

        editor_layout.addStretch()
        editor_widget.setLayout(editor_layout)
        return editor_widget

    def _refresh_sensor_tab_ui(self):
        if not hasattr(self, "sensor_config_combo"):
            return

        self._sensor_config_ui_loading = True
        self.sensor_config_combo.blockSignals(True)
        self.sensor_type_combo.blockSignals(True)
        self.sensor_config_combo.clear()
        
        for config in self.sensor_configurations:
            self.sensor_config_combo.addItem(str(config["name"]))

        current_index = max(
            0,
            self.sensor_config_combo.findText(self.active_sensor_config_name),
        )
        self.sensor_config_combo.setCurrentIndex(current_index)
        self.sensor_config_combo.blockSignals(False)

        self._load_active_sensor_into_editor()
        
        self.sensor_type_combo.blockSignals(False)
        self._sensor_config_ui_loading = False

    def _load_active_sensor_into_editor(self):
        if not hasattr(self, "sensor_name_edit"):
            return

        config = self.get_active_sensor_configuration()
        self.sensor_name_edit.setText(str(config["name"]))
        
        # Load both editors for every config. Array is optional.
        current_tab_index = self.sensor_editor_tabs.currentIndex() if hasattr(self, "sensor_editor_tabs") else 0

        # Update type selector without triggering change event. This only controls
        # the default for Add New.
        self.sensor_type_combo.blockSignals(True)
        type_index = 1 if current_tab_index == 1 else 0
        self.sensor_type_combo.setCurrentIndex(type_index)
        self.sensor_type_combo.blockSignals(False)

        self._load_channel_layout_into_editor(config)
        self._load_array_layout_into_editor(config)
        self.sensor_editor_tabs.setCurrentIndex(current_tab_index if current_tab_index in (0, 1) else 0)
        
        self.sensor_status_label.setText("")
        self.refresh_sensor_mapping_usage()

    def _load_channel_layout_into_editor(self, config: dict):
        """Load channel layout configuration into the editor."""
        position_channels = mapping_to_position_channels(list(config["channel_sensor_map"]))

        for sensor_label in SENSOR_POSITION_ORDER:
            spin = self.sensor_position_spins[sensor_label]
            spin.blockSignals(True)
            spin.setValue(int(position_channels[sensor_label]))
            spin.setProperty("previous_value", int(position_channels[sensor_label]))
            spin.blockSignals(False)

        self._update_sensor_mapping_preview()

    def _load_array_layout_into_editor(self, config: dict):
        """Load array layout configuration into the editor."""
        default_array = default_array_configuration()
        array_layout = config.get("array_layout", default_array["array_layout"])
        cells = array_layout.get("cells", [])
        mux_mapping = config.get("mux_mapping", default_array["mux_mapping"])
        channel_layout = config.get("channel_layout", default_array["channel_layout"])
        
        # Load array matrix cells
        for row in range(ARRAY_ROWS):
            for col in range(ARRAY_COLS):
                cell_widget = self.array_matrix_cells[(row, col)]
                cell_widget.blockSignals(True)
                if row < len(cells) and col < len(cells[row]):
                    cell_value = cells[row][col]
                    cell_widget.setText(str(cell_value) if cell_value else "")
                else:
                    cell_widget.setText("")
                cell_widget.blockSignals(False)
        
        # Load channels per sensor
        channels_per_sensor = int(channel_layout.get("channels_per_sensor", ARRAY_CELL_CHANNELS_MAX))
        self.array_channels_per_sensor.blockSignals(True)
        self.array_channels_per_sensor.setValue(channels_per_sensor)
        self.array_channels_per_sensor.blockSignals(False)
        
        # Load MUX configuration table
        self._refresh_mux_table(mux_mapping)
        self._update_array_mux_warning_label()

    def _refresh_mux_table(self, mux_mapping: dict):
        """Rebuild the MUX table from a mux_mapping dict (used when loading a config)."""
        sensors = sorted(mux_mapping.keys())

        self.array_mux_table.blockSignals(True)
        self.array_mux_table.setRowCount(len(sensors))

        for row_idx, sensor_id in enumerate(sensors):
            # Sensor ID (read-only)
            sensor_item = QTableWidgetItem(sensor_id)
            sensor_item.setFlags(sensor_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.array_mux_table.setItem(row_idx, 0, sensor_item)

            # MUX number
            mux_num = int(mux_mapping[sensor_id].get("mux", 1))
            mux_item = QTableWidgetItem(str(mux_num))
            self.array_mux_table.setItem(row_idx, 1, mux_item)

            # Channels (comma-separated)
            channels = mux_mapping[sensor_id].get("channels", [])
            channels_str = ",".join(str(c) for c in sorted(channels))
            channels_item = QTableWidgetItem(channels_str)
            self.array_mux_table.setItem(row_idx, 2, channels_item)

        self.array_mux_table.blockSignals(False)

    def _sync_mux_table_from_cells(self):
        """Sync MUX table rows to match sensors currently in the array grid.

        - Adds rows for newly appeared sensors (with blank MUX defaults).
        - Removes rows for sensors no longer in the grid.
        - Preserves existing MUX/channel values.
        """
        # Collect sensor IDs currently in the grid
        grid_sensors: set[str] = set()
        for row in range(ARRAY_ROWS):
            for col in range(ARRAY_COLS):
                cell_widget = self.array_matrix_cells[(row, col)]
                cell_value = normalize_array_cell(cell_widget.text())
                if cell_value:
                    grid_sensors.add(cell_value)

        # Collect existing table entries (preserve current values)
        existing: dict[str, tuple[str, str]] = {}  # sensor_id -> (mux_str, channels_str)
        for row_idx in range(self.array_mux_table.rowCount()):
            s_item = self.array_mux_table.item(row_idx, 0)
            m_item = self.array_mux_table.item(row_idx, 1)
            c_item = self.array_mux_table.item(row_idx, 2)
            if s_item:
                existing[s_item.text()] = (
                    m_item.text() if m_item else "1",
                    c_item.text() if c_item else "",
                )

        # Rebuild table with sensors in the grid, sorted
        sensors = sorted(grid_sensors)
        self.array_mux_table.blockSignals(True)
        self.array_mux_table.setRowCount(len(sensors))

        for row_idx, sensor_id in enumerate(sensors):
            # Sensor ID (read-only)
            sensor_item = QTableWidgetItem(sensor_id)
            sensor_item.setFlags(sensor_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.array_mux_table.setItem(row_idx, 0, sensor_item)

            mux_str, channels_str = existing.get(sensor_id, ("1", ""))
            self.array_mux_table.setItem(row_idx, 1, QTableWidgetItem(mux_str))
            self.array_mux_table.setItem(row_idx, 2, QTableWidgetItem(channels_str))

        self.array_mux_table.blockSignals(False)

    def _set_array_mux_warning(self, message: str):
        if hasattr(self, "array_mux_warning_label"):
            self.array_mux_warning_label.setText(message)

    def _collect_array_layout_editor_data(self):
        """Collect and validate array editor fields.

        Returns:
            tuple[cells, mux_mapping, channels_per_sensor]

        Raises:
            ValueError: When editor values are incomplete or invalid.
        """
        # Extract array layout from matrix cells
        cells = []
        for row in range(ARRAY_ROWS):
            row_cells = []
            for col in range(ARRAY_COLS):
                cell_widget = self.array_matrix_cells[(row, col)]
                cell_value = normalize_array_cell(cell_widget.text())
                row_cells.append(cell_value)
            cells.append(row_cells)

        sensors_in_matrix = {
            sensor_id
            for row_cells in cells
            for sensor_id in row_cells
            if sensor_id
        }

        # Ensure user-specified cells are valid sensor IDs
        for row in range(ARRAY_ROWS):
            for col in range(ARRAY_COLS):
                raw_text = self.array_matrix_cells[(row, col)].text().strip()
                if raw_text and not normalize_array_cell(raw_text):
                    raise ValueError(
                        f"Invalid sensor ID at row {row + 1}, col {col + 1}. Use PZT1/PZR1 format."
                    )

        # Extract MUX mapping from table
        mux_mapping = {}
        for row_idx in range(self.array_mux_table.rowCount()):
            sensor_item = self.array_mux_table.item(row_idx, 0)
            mux_item = self.array_mux_table.item(row_idx, 1)
            channels_item = self.array_mux_table.item(row_idx, 2)

            if not all([sensor_item, mux_item, channels_item]):
                continue

            sensor_id = sensor_item.text().strip()
            if not sensor_id:
                continue

            try:
                mux_text = mux_item.text().strip()
                channels_str = channels_item.text().strip()

                if not mux_text:
                    raise ValueError("MUX value is required")
                if not channels_str:
                    raise ValueError("Channels value is required")

                mux_num = int(mux_text)
                channels = [int(c.strip()) for c in channels_str.split(",") if c.strip()]

                if mux_num not in (1, 2):
                    raise ValueError("MUX must be 1 or 2")
                if not channels:
                    raise ValueError("At least one channel is required")
                if len(channels) > ARRAY_CELL_CHANNELS_MAX:
                    raise ValueError(f"Maximum {ARRAY_CELL_CHANNELS_MAX} channels per sensor")
                if any(channel < 0 or channel > 15 for channel in channels):
                    raise ValueError("Channels must be in range 0-15")
                if len(set(channels)) != len(channels):
                    raise ValueError("Duplicate channels are not allowed")

                mux_mapping[sensor_id] = {
                    "mux": mux_num,
                    "channels": channels,
                }
            except ValueError as e:
                raise ValueError(f"Invalid entry in MUX table for {sensor_id}: {str(e)}")

        # If matrix has sensors, require MUX config for each sensor
        if sensors_in_matrix:
            missing = sorted(sensor_id for sensor_id in sensors_in_matrix if sensor_id not in mux_mapping)
            if missing:
                raise ValueError("Missing MUX configuration for: " + ", ".join(missing))

        # Rule: different sensors of same type must not share exact same (mux, channels)
        same_type_signatures: dict[str, dict[tuple[int, tuple[int, ...]], str]] = {
            "PZT": {},
            "PZR": {},
        }
        for sensor_id, mapping in mux_mapping.items():
            sensor_type = "PZT" if sensor_id.startswith("PZT") else "PZR"
            signature = (int(mapping["mux"]), tuple(sorted(int(c) for c in mapping["channels"])))
            previous_sensor = same_type_signatures[sensor_type].get(signature)
            if previous_sensor and previous_sensor != sensor_id:
                raise ValueError(
                    f"{sensor_type} sensors {previous_sensor} and {sensor_id} use the same MUX/channels."
                )
            same_type_signatures[sensor_type][signature] = sensor_id

        channels_per_sensor = self.array_channels_per_sensor.value()
        return cells, mux_mapping, channels_per_sensor

    def _update_array_mux_warning_label(self):
        if self._sensor_config_ui_loading:
            return
        try:
            self._collect_array_layout_editor_data()
        except ValueError as e:
            self._set_array_mux_warning(f"Warning: {str(e)}")
            return
        self._set_array_mux_warning("")

    def _update_sensor_mapping_preview(self):
        if not hasattr(self, "sensor_mapping_preview_label"):
            return
        mapping = self.get_active_channel_sensor_map()
        self.sensor_mapping_preview_label.setText(
            "Channel map [1..5]: " + ", ".join(f"{index + 1}->{label}" for index, label in enumerate(mapping))
        )

    def _set_active_sensor_config_name(self, name):
        self.active_sensor_config_name = str(name)

    def _replace_active_sensor_config(self, updated_config):
        for index, config in enumerate(self.sensor_configurations):
            if config["name"] == self.active_sensor_config_name:
                self.sensor_configurations[index] = updated_config
                self.active_sensor_config_name = str(updated_config["name"])
                return

        self.sensor_configurations.append(updated_config)
        self.active_sensor_config_name = str(updated_config["name"])

    def on_sensor_config_selected(self, index):
        if self._sensor_config_ui_loading or index < 0 or index >= len(self.sensor_configurations):
            return

        self._set_active_sensor_config_name(self.sensor_configurations[index]["name"])
        self._load_active_sensor_into_editor()
        self.save_sensor_configurations()
        self.log_status(f"Selected sensor configuration: {self.active_sensor_config_name}")

    def on_sensor_name_edited(self):
        if self._sensor_config_ui_loading:
            return

        new_name = self.sensor_name_edit.text().strip()
        if not new_name:
            self.sensor_status_label.setText("Sensor name cannot be empty.")
            self.sensor_name_edit.setText(self.active_sensor_config_name)
            return

        if new_name != self.active_sensor_config_name and any(
            config["name"] == new_name for config in self.sensor_configurations
        ):
            self.sensor_status_label.setText(f'A sensor named "{new_name}" already exists.')
            self.sensor_name_edit.setText(self.active_sensor_config_name)
            return

        config = self.get_active_sensor_configuration()
        updated_config = {
            "name": new_name,
            "type": str(config.get("type", "channel_layout")),
            "channel_sensor_map": list(config.get("channel_sensor_map", ["T", "R", "C", "L", "B"])),
            "array_layout": dict(config.get("array_layout", default_array_configuration()["array_layout"])),
            "mux_mapping": dict(config.get("mux_mapping", {})),
            "channel_layout": dict(config.get("channel_layout", {"channels_per_sensor": ARRAY_CELL_CHANNELS_MAX})),
            "is_bundled": False,
        }
        self._replace_active_sensor_config(updated_config)
        self.sensor_status_label.setText("")
        self._refresh_sensor_tab_ui()
        self.save_sensor_configurations()
        self.log_status(f"Renamed sensor configuration to: {new_name}")

    def _current_position_channels(self):
        return {
            sensor_label: self.sensor_position_spins[sensor_label].value()
            for sensor_label in SENSOR_POSITION_ORDER
        }

    def _save_sensor_mapping_from_editor(self):
        config = self.get_active_sensor_configuration()
        updated_config = {
            "name": self.active_sensor_config_name,
            "type": str(config.get("type", "channel_layout")),
            "channel_sensor_map": position_channels_to_mapping(self._current_position_channels()),
            "array_layout": dict(config.get("array_layout", default_array_configuration()["array_layout"])),
            "mux_mapping": dict(config.get("mux_mapping", {})),
            "channel_layout": dict(config.get("channel_layout", {"channels_per_sensor": ARRAY_CELL_CHANNELS_MAX})),
            "is_bundled": False,
        }
        self._replace_active_sensor_config(updated_config)
        self.sensor_status_label.setText("")
        self._update_sensor_mapping_preview()
        self.save_sensor_configurations()
        self.refresh_sensor_mapping_usage()
        self.log_status(f"Updated sensor mapping: {self.active_sensor_config_name}")

    def on_sensor_position_spin_changed(self, new_value):
        if self._sensor_config_ui_loading:
            return

        spin = self.sender()
        if spin is None:
            return

        old_value = int(spin.property("previous_value") or new_value)
        if new_value != old_value:
            for other_spin in self.sensor_position_spins.values():
                if other_spin is spin:
                    continue
                if other_spin.value() == new_value:
                    other_spin.blockSignals(True)
                    other_spin.setValue(old_value)
                    other_spin.setProperty("previous_value", old_value)
                    other_spin.blockSignals(False)
                    break

        spin.setProperty("previous_value", int(new_value))
        self._save_sensor_mapping_from_editor()

    def on_add_sensor_config_clicked(self):
        existing_names = {config["name"] for config in self.sensor_configurations}
        base_name = "New Sensor"
        suffix = 1
        new_name = base_name
        while new_name in existing_names:
            suffix += 1
            new_name = f"{base_name} {suffix}"

        new_config = {
            "name": new_name,
            "type": str(self.sensor_type_combo.currentData() or "channel_layout"),
            "channel_sensor_map": list(self.get_active_channel_sensor_map() or ["T", "R", "C", "L", "B"]),
            **default_array_configuration(),
            "is_bundled": False,
        }
        
        self.sensor_configurations.append(new_config)
        self.active_sensor_config_name = new_name
        self.sensor_status_label.setText("")
        self._refresh_sensor_tab_ui()
        self.save_sensor_configurations()
        self.log_status(f"Added sensor configuration: {new_name}")

    def on_delete_sensor_config_clicked(self):
        if len(self.sensor_configurations) <= 1:
            self.sensor_status_label.setText("At least one sensor configuration must remain.")
            return

        name = self.active_sensor_config_name
        answer = QMessageBox.question(
            self,
            "Delete Sensor Configuration",
            f'Delete sensor configuration "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.sensor_configurations = [
            config for config in self.sensor_configurations if config["name"] != name
        ]
        self.active_sensor_config_name = str(self.sensor_configurations[0]["name"])
        self.sensor_status_label.setText("")
        self._refresh_sensor_tab_ui()
        self.save_sensor_configurations()
        self.log_status(f"Deleted sensor configuration: {name}")

    def on_sensor_type_changed(self, index: int):
        """Handle configuration type change (channel_layout vs array_layout)."""
        if self._sensor_config_ui_loading:
            return
        # The loaded sensor configuration type is fixed. This selector is used
        # only to choose the default type for Add New, not to convert the
        # current configuration when switching tabs.
        self.log_status(f"New sensor type default set to: {self.sensor_type_combo.currentText()}")

    def on_sensor_editor_tab_changed(self, index: int):
        """Use the visible tab as the default type for Add New only."""
        if self._sensor_config_ui_loading:
            return

        requested_type = "array_layout" if index == 1 else "channel_layout"
        combo_index = self.sensor_type_combo.findData(requested_type)
        if combo_index >= 0 and self.sensor_type_combo.currentIndex() != combo_index:
            self.sensor_type_combo.blockSignals(True)
            self.sensor_type_combo.setCurrentIndex(combo_index)
            self.sensor_type_combo.blockSignals(False)

        self.log_status(f"New sensor type default set to: {self.sensor_type_combo.currentText()}")

    def on_save_sensor_config_clicked(self):
        """Save the current configuration being edited."""
        if self._sensor_config_ui_loading:
            return
        
        try:
            self._save_full_sensor_config_from_editor()
            
            self.save_sensor_configurations()
            self.log_status(f"Saved sensor configuration: {self.active_sensor_config_name}")
        except ValueError as e:
            self._set_array_mux_warning(f"Warning: {str(e)}")
            self.sensor_status_label.setText(f"Error: {str(e)}")

    def _save_channel_layout_from_editor(self):
        """Save channel layout configuration from editor."""
        config = self.get_active_sensor_configuration()
        updated_config = {
            "name": self.active_sensor_config_name,
            "type": str(config.get("type", "channel_layout")),
            "channel_sensor_map": position_channels_to_mapping(self._current_position_channels()),
            "array_layout": dict(config.get("array_layout", default_array_configuration()["array_layout"])),
            "mux_mapping": dict(config.get("mux_mapping", {})),
            "channel_layout": dict(config.get("channel_layout", {"channels_per_sensor": ARRAY_CELL_CHANNELS_MAX})),
            "is_bundled": False,
        }
        self._replace_active_sensor_config(updated_config)
        self._update_sensor_mapping_preview()

    def _save_full_sensor_config_from_editor(self):
        """Save channel mapping and optional array attachment together."""
        cells, mux_mapping, channels_per_sensor = self._collect_array_layout_editor_data()
        updated_config = {
            "name": self.active_sensor_config_name,
            "channel_sensor_map": position_channels_to_mapping(self._current_position_channels()),
            "array_layout": {"cells": cells},
            "mux_mapping": mux_mapping,
            "channel_layout": {"channels_per_sensor": channels_per_sensor},
            "is_bundled": False,
        }

        normalized = normalize_combined_sensor_config(updated_config)
        if not normalized:
            raise ValueError("Sensor configuration is incomplete or invalid.")

        self._replace_active_sensor_config({**normalized, "is_bundled": False})
        self._update_sensor_mapping_preview()
        self._set_array_mux_warning("")

    def _save_array_layout_from_editor(self):
        """Save array layout configuration from editor."""
        self._save_full_sensor_config_from_editor()

    def on_array_cell_edited(self):
        """Handle array matrix cell edit — sync the MUX table immediately."""
        if self._sensor_config_ui_loading:
            return
        self._sync_mux_table_from_cells()
        self._update_array_mux_warning_label()

    def on_array_mux_table_item_changed(self, item):
        """Handle live edits in MUX table and update inline warning state."""
        if self._sensor_config_ui_loading:
            return
        self._update_array_mux_warning_label()

    def on_array_channels_per_sensor_changed(self, value: int):
        """Handle channels per sensor change."""
        if self._sensor_config_ui_loading:
            return
        self._update_array_mux_warning_label()

    def refresh_sensor_mapping_usage(self):
        if hasattr(self, "smoothed_cop_x"):
            if isinstance(self.smoothed_cop_x, list):
                self.smoothed_cop_x = [0.0 for _ in self.smoothed_cop_x]
                self.smoothed_cop_y = [0.0 for _ in self.smoothed_cop_y]
                self.smoothed_intensity = [0.0 for _ in self.smoothed_intensity]
            else:
                self.smoothed_cop_x = 0.0
                self.smoothed_cop_y = 0.0
                self.smoothed_intensity = 0.0
        for processor in getattr(self, "heatmap_signal_processors", []):
            processor.reset()
        if hasattr(self, "reset_shear_processing_state"):
            self.reset_shear_processing_state()
        if hasattr(self, "_refresh_heatmap_background_overlay"):
            self._refresh_heatmap_background_overlay(force=True)
        if hasattr(self, "refresh_shear_background_overlay"):
            self.refresh_shear_background_overlay()
