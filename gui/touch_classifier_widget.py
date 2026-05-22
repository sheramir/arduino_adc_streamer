"""Material classifier bar widget for the Pressure Map demo."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from constants.touch_id import (
    TOUCH_CLASSIFIER_ACTIVE_COLOR,
    TOUCH_CLASSIFIER_INACTIVE_COLOR,
)


class TouchClassifierWidget(QWidget):
    """Render per-material score bars and numeric values."""

    def __init__(self, materials: list[str] | tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.materials = [str(item) for item in materials]
        self._rows: list[tuple[QLabel, QProgressBar, QLabel]] = []

        layout = QVBoxLayout(self)
        group = QGroupBox("Material Classifier Demo")
        group_layout = QGridLayout(group)

        for row, material_name in enumerate(self.materials):
            name_label = QLabel(material_name)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setMinimumHeight(18)
            value_label = QLabel("0.0")
            value_label.setMinimumWidth(40)

            group_layout.addWidget(name_label, row, 0)
            group_layout.addWidget(bar, row, 1)
            group_layout.addWidget(value_label, row, 2)
            self._rows.append((name_label, bar, value_label))

        layout.addWidget(group)
        self.set_scores([0.0] * len(self.materials), None)

    def set_scores(self, scores: list[float] | tuple[float, ...], active_index: int | None) -> None:
        for index, (name_label, bar, value_label) in enumerate(self._rows):
            value = 0.0
            if index < len(scores):
                try:
                    value = float(scores[index])
                except (TypeError, ValueError):
                    value = 0.0
            bounded = max(0.0, min(100.0, value))
            bar.setValue(int(round(bounded)))
            value_label.setText(f"{bounded:.1f}")

            if active_index is not None and index == int(active_index):
                color = TOUCH_CLASSIFIER_ACTIVE_COLOR
            else:
                color = TOUCH_CLASSIFIER_INACTIVE_COLOR

            bar.setStyleSheet(
                "QProgressBar { border: 1px solid #5D5D5D; border-radius: 4px; background: #1B1B1B; }"
                f"QProgressBar::chunk {{ background-color: {color}; }}"
            )
            name_label.setStyleSheet("color: #E6E6E6;")
            value_label.setStyleSheet("color: #E6E6E6;")
