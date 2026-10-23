"""Schema-driven parameter forms (Components / System / Simulation tabs) and the table editor for input profiles."""
from __future__ import annotations

from typing import Any, Callable

from PyQt6 import QtCore, QtGui, QtWidgets

from ..config_utils import format_number, parse_number

NORMAL_STYLE = ""
MODIFIED_STYLE = "QLineEdit, QComboBox { background: #fff4cc; color: #000000; } QComboBox QAbstractItemView { color: #000000; background: #ffffff; }"
ERROR_STYLE = "QLineEdit { background: #ffd6d6; color: #000000; }"


class FieldRow(QtCore.QObject):
    """One labelled parameter: label | editor | unit | reset button. Reads/writes cfg through ParamForm callbacks."""

    changed = QtCore.pyqtSignal(str)

    def __init__(self, item: dict, form: "ParamForm"):
        super().__init__(form)
        self.item = item
        self.form = form
        self.path: str = item["path"]
        self.kind: str = item.get("type", "float")
        self.nullable: bool = bool(item.get("nullable"))
        tip = item.get("tip", "")
        self.label = QtWidgets.QLabel(item["label"])
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(140)
        self.label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        self.unit = QtWidgets.QLabel(item.get("unit", ""))
        self.unit.setMinimumWidth(44)
        self.reset = QtWidgets.QToolButton()
        self.reset.setText("↺")
        self.reset.setToolTip("Reset to the model default")
        self.reset.clicked.connect(self._on_reset)
        self.editor: QtWidgets.QWidget
        if self.kind == "bool":
            self.editor = QtWidgets.QCheckBox()
            self.editor.toggled.connect(self._commit_bool)
        elif self.kind == "choice":
            self.editor = QtWidgets.QComboBox()
            self.editor.addItems([str(c) for c in item["choices"]])
            self.editor.currentTextChanged.connect(self._commit_choice)
        else:
            self.editor = QtWidgets.QLineEdit()
            self.editor.setFixedWidth(110)
            if self.nullable:
                self.editor.setPlaceholderText("(not set)")
            self.editor.editingFinished.connect(self._commit_text)
        for w in (self.label, self.editor, self.unit):
            w.setToolTip(tip or item["label"])
        self.path_tip = f"{self.path}"
        self.label.setStatusTip(self.path_tip)
        self._loading = False

    # ----- widgets for the grid -----
    def widgets(self) -> list[QtWidgets.QWidget]:
        return [self.label, self.editor, self.unit, self.reset]

    # ----- cfg <-> editor -----
    def load(self) -> None:
        value = self.form.get(self.path)
        self._loading = True
        try:
            if self.kind == "bool":
                self.editor.setChecked(bool(value))
            elif self.kind == "choice":
                self.editor.setCurrentText(str(value))
            elif self.kind == "intlist":
                self.editor.setText(", ".join(str(v) for v in value))
            else:
                self.editor.setText("" if value is None else format_number(value))
        finally:
            self._loading = False
        self._style()

    def _style(self) -> None:
        modified = self.form.get(self.path) != self.form.default(self.path)
        self.reset.setEnabled(modified)
        if isinstance(self.editor, QtWidgets.QCheckBox):
            self.editor.setStyleSheet("QCheckBox { background: #fff4cc; color: #000000; }" if modified else "")
        else:
            self.editor.setStyleSheet(MODIFIED_STYLE if modified else NORMAL_STYLE)
        font = self.label.font()
        font.setBold(modified)
        self.label.setFont(font)

    def _set(self, value: Any) -> None:
        if self.form.get(self.path) != value:
            self.form.set(self.path, value)
            self.changed.emit(self.path)
        self._style()

    def _commit_bool(self, checked: bool) -> None:
        if not self._loading:
            self._set(bool(checked))

    def _commit_choice(self, text: str) -> None:
        if not self._loading and text:
            self._set(text)

    def _commit_text(self) -> None:
        if self._loading:
            return
        text = self.editor.text().strip()
        try:
            if self.kind == "intlist":
                value: Any = [int(p) for p in text.replace(";", ",").split(",") if p.strip()]
                if not value:
                    raise ValueError("enter at least one address")
            elif text == "":
                if not self.nullable:
                    raise ValueError("a value is required")
                value = None
            else:
                number = parse_number(text)
                if self.kind == "int":
                    if number != int(number):
                        raise ValueError("an integer is required")
                    value = int(number)
                else:
                    value = number
        except ValueError as exc:
            self.editor.setStyleSheet(ERROR_STYLE)
            self.editor.setToolTip(f"Invalid value: {exc}")
            QtCore.QTimer.singleShot(1800, self.load)  # restore the last good value
            return
        self.editor.setToolTip(self.item.get("tip", "") or self.item["label"])
        self._set(value)
        self.load()

    def _on_reset(self) -> None:
        self.form.set(self.path, self.form.default(self.path))
        self.changed.emit(self.path)
        self.load()


class ParamForm(QtWidgets.QWidget):
    """Scrollable form built from a manifest tab (list of {group, items})."""

    changed = QtCore.pyqtSignal(str)

    def __init__(self, groups: list[dict], get: Callable[[str], Any], set_: Callable[[str, Any], None],
                 default: Callable[[str], Any], header: QtWidgets.QWidget | None = None,
                 footer: QtWidgets.QWidget | None = None, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.get, self.set, self.default = get, set_, default
        self.rows: list[FieldRow] = []
        self._group_boxes: list[tuple[QtWidgets.QGroupBox, list[FieldRow]]] = []
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Filter parameters…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        if header is not None:
            outer.addWidget(header)
        outer.addWidget(self.filter)
        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        host = QtWidgets.QWidget()
        host_layout = QtWidgets.QVBoxLayout(host)
        for grp in groups:
            box = QtWidgets.QGroupBox(grp["group"])
            grid = QtWidgets.QGridLayout(box)
            grid.setColumnStretch(0, 1)
            rows: list[FieldRow] = []
            for r, item in enumerate(grp["items"]):
                row = FieldRow(item, self)
                row.changed.connect(self.changed)
                for c, w in enumerate(row.widgets()):
                    grid.addWidget(w, r, c)
                rows.append(row)
            self.rows += rows
            self._group_boxes.append((box, rows))
            host_layout.addWidget(box)
        host_layout.addStretch(1)
        area.setWidget(host)
        outer.addWidget(area, 1)
        if footer is not None:
            outer.addWidget(footer)
        self.refresh()

    def refresh(self) -> None:
        for row in self.rows:
            row.load()

    def modified_count(self) -> int:
        return sum(1 for r in self.rows if self.get(r.path) != self.default(r.path))

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for box, rows in self._group_boxes:
            any_visible = False
            for row in rows:
                hit = not needle or needle in row.item["label"].lower() or needle in row.path.lower() or needle in box.title().lower()
                for w in row.widgets():
                    w.setVisible(hit)
                any_visible |= hit
            box.setVisible(any_visible)


class TableEditor(QtWidgets.QGroupBox):
    """Editable table bound to a list-of-dicts configuration entry (for example the input force pulses)."""

    changed = QtCore.pyqtSignal(str)

    def __init__(self, spec: dict, get: Callable[[str], Any], set_: Callable[[str, Any], None], parent=None):
        super().__init__(spec["title"], parent)
        self.spec, self.get, self.set = spec, get, set_
        self.path = spec["path"]
        self.cols = spec["columns"]
        self._loading = False
        self.setToolTip(spec.get("tip", ""))
        lay = QtWidgets.QVBoxLayout(self)
        if spec.get("tip"):
            hint = QtWidgets.QLabel(spec["tip"])
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #555;")
            lay.addWidget(hint)
        self.table = QtWidgets.QTableWidget(0, len(self.cols))
        self.table.setHorizontalHeaderLabels([c["label"] for c in self.cols])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton(spec.get("add_label", "Add pulse"))
        add.clicked.connect(self._add)
        rem = QtWidgets.QPushButton("Remove selected")
        rem.clicked.connect(self._remove)
        clear = QtWidgets.QPushButton("No input (clear)")
        clear.clicked.connect(self._clear)
        for b in (add, rem, clear):
            buttons.addWidget(b)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        rows = self.get(self.path) or []
        self._loading = True
        try:
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, col in enumerate(self.cols):
                    self.table.setItem(r, c, QtWidgets.QTableWidgetItem(format_number(row.get(col["key"], 0))))
        finally:
            self._loading = False

    def _collect(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            row = {}
            for c, col in enumerate(self.cols):
                item = self.table.item(r, c)
                number = parse_number(item.text()) if item else 0.0
                row[col["key"]] = int(number) if col["type"] == "int" else number
            out.append(row)
        return out

    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._loading:
            return
        try:
            rows = self._collect()
            col = self.cols[item.column()]
            value = rows[item.row()][col["key"]]
            if "min" in col and value < col["min"] or "max" in col and value > col["max"]:
                raise ValueError(f"{col['label']} must be between {col.get('min')} and {col.get('max')}")
        except (ValueError, IndexError) as exc:
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Invalid value: {exc}")
            QtCore.QTimer.singleShot(0, self.refresh)
            return
        self.set(self.path, rows)
        self.changed.emit(self.path)

    def _add(self) -> None:
        rows = list(self.get(self.path) or [])
        rows.append(dict(self.spec["new_row"]))
        self.set(self.path, rows)
        self.refresh()
        self.changed.emit(self.path)

    def _remove(self) -> None:
        sel = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        rows = list(self.get(self.path) or [])
        for r in sel:
            if 0 <= r < len(rows):
                del rows[r]
        self.set(self.path, rows)
        self.refresh()
        self.changed.emit(self.path)

    def _clear(self) -> None:
        self.set(self.path, [])
        self.refresh()
        self.changed.emit(self.path)
