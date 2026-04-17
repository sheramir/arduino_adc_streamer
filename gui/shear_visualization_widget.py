"""
Shear-vector visualization widget for the five-sensor piezo package.

The widget draws the static sensor package layout once with PyQtGraph graphics
items and updates only the dynamic shear arrow and readout on each frame. It is
designed for embedding below the Signal Integration plot so Step 2 shear
detection can be visually verified without adding a new top-level tab.

Dependencies:
    PyQt6, pyqtgraph, constants.shear, and data_processing.shear_detector.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import pyqtgraph as pg
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from constants.shear import (
    DEFAULT_ARROW_BASE_WIDTH_PX,
    DEFAULT_ARROW_COLOR,
    DEFAULT_ARROW_GAIN,
    DEFAULT_ARROW_MAX_LENGTH_PX,
    DEFAULT_ARROW_MIN_THRESHOLD,
    DEFAULT_ARROW_WIDTH_SCALES,
    DEFAULT_CIRCLE_DIAMETER_MM,
    DEFAULT_SENSOR_SPACING_MM,
    SHEAR_ARROW_HEAD_LENGTH_FRACTION,
    SHEAR_ARROW_HEAD_WIDTH_FRACTION,
    SHEAR_ARROW_MIN_HEAD_LENGTH_MM,
    SHEAR_ARROW_MIN_HEAD_WIDTH_MM,
    SHEAR_ARROW_MAX_WIDTH_PX,
    SHEAR_ARROW_PEN_IS_COSMETIC,
    SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE,
    SHEAR_ARROW_WIDTH_SCALE_RANGE_PX,
    SHEAR_ARROW_Z,
    SHEAR_AXIS_EQUAL_ASPECT_LOCKED,
    SHEAR_COMPONENT_DECIMALS,
    SHEAR_LABEL_Z,
    SHEAR_LAYOUT_BACKGROUND,
    SHEAR_LAYOUT_BOUNDARY_PADDING_FRACTION,
    SHEAR_LAYOUT_CIRCLE_COLOR,
    SHEAR_LAYOUT_CIRCLE_LINE_WIDTH_PX,
    SHEAR_LAYOUT_GRID_ALPHA,
    SHEAR_LAYOUT_LABEL_COLOR,
    SHEAR_LAYOUT_SENSOR_FILL_COLOR,
    SHEAR_LAYOUT_SENSOR_LINE_WIDTH_PX,
    SHEAR_LAYOUT_SENSOR_OUTLINE_COLOR,
    SHEAR_LAYOUT_PENS_ARE_COSMETIC,
    SHEAR_POSITION_BOTTOM,
    SHEAR_POSITION_CENTER,
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
    SHEAR_READOUT_ANGLE_DECIMALS,
    SHEAR_READOUT_MAGNITUDE_DECIMALS,
    SHEAR_SENSOR_LABEL_OFFSET_MM,
    SHEAR_SENSOR_POSITIONS,
    SHEAR_SENSOR_SQUARE_SIDE_MM,
    SHEAR_PLOT_MIN_HEIGHT_PX,
    SHEAR_STATIC_LAYOUT_Z,
    SHEAR_VISUALIZATION_MIN_HEIGHT_PX,
    SHEAR_ZERO_VALUE,
)
from data_processing.shear_detector import ShearResult


@dataclass(frozen=True, slots=True)
class ShearArrowGeometry:
    """Computed dynamic arrow geometry in plot coordinates.

    Args:
        visible: Whether the arrow should be drawn.
        origin_x: Arrow origin x coordinate.
        origin_y: Arrow origin y coordinate.
        tip_x: Arrow tip x coordinate.
        tip_y: Arrow tip y coordinate.
        length: Clamped arrow length in millimeter plot coordinates.
        width_px: Shaft width in screen pixels.
        angle_deg: Direction angle in degrees.

    Usage example:
        geometry = widget.calculate_arrow_geometry(result)
        assert geometry.tip_x > geometry.origin_x
    """

    visible: bool
    origin_x: float
    origin_y: float
    tip_x: float
    tip_y: float
    length: float
    width_px: float
    angle_deg: float


class ShearVisualizationWidget(QWidget):
    """Display a static sensor layout and dynamic shear arrow.

    Args:
        parent: Optional Qt parent widget.

    Usage example:
        widget = ShearVisualizationWidget()
        widget.update_display(shear_result)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.display_diameter_mm = DEFAULT_CIRCLE_DIAMETER_MM
        self.sensor_spacing_mm = DEFAULT_SENSOR_SPACING_MM
        self.arrow_gain = DEFAULT_ARROW_GAIN
        self.arrow_max_length_fraction = DEFAULT_ARROW_MAX_LENGTH_PX
        self.arrow_min_threshold = DEFAULT_ARROW_MIN_THRESHOLD
        self.arrow_width_scales = DEFAULT_ARROW_WIDTH_SCALES
        self.arrow_base_width_px = DEFAULT_ARROW_BASE_WIDTH_PX
        self.arrow_color = DEFAULT_ARROW_COLOR

        self.circle_radius_mm = self.display_diameter_mm / 2.0
        self.sensor_positions = self._build_sensor_positions()
        self.sensor_items: dict[str, QGraphicsRectItem] = {}
        self.sensor_label_items: dict[str, pg.TextItem] = {}
        self.last_arrow_geometry = self._hidden_arrow_geometry()
        self.setMinimumHeight(SHEAR_VISUALIZATION_MIN_HEIGHT_PX)

        layout = QVBoxLayout(self)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(SHEAR_PLOT_MIN_HEIGHT_PX)
        self.plot_widget.setBackground(SHEAR_LAYOUT_BACKGROUND)
        self.plot_widget.setAspectLocked(SHEAR_AXIS_EQUAL_ASPECT_LOCKED)
        self.plot_widget.showGrid(x=True, y=True, alpha=SHEAR_LAYOUT_GRID_ALPHA)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.getPlotItem().setMenuEnabled(False)
        self.plot_widget.getViewBox().setMouseEnabled(x=False, y=False)
        self.plot_widget.setLabel("bottom", "x", units="mm")
        self.plot_widget.setLabel("left", "y", units="mm")
        layout.addWidget(self.plot_widget)

        self.readout_label = QLabel("No Data")
        layout.addWidget(self.readout_label)

        self.circle_item: QGraphicsEllipseItem | None = None
        self.arrow_line_item = QGraphicsLineItem()
        self.arrow_head_item = QGraphicsPolygonItem()
        self._initialize_static_layout()
        self._initialize_dynamic_arrow()
        self.update_display(None)

    def configure(
        self,
        *,
        arrow_gain: float | None = None,
        arrow_max_length_fraction: float | None = None,
        arrow_min_threshold: float | None = None,
        arrow_width_scales: bool | None = None,
        arrow_base_width_px: float | None = None,
        arrow_color: str | None = None,
    ) -> None:
        """Update arrow visualization settings.

        Args:
            arrow_gain: Optional multiplier from shear magnitude to arrow length.
            arrow_max_length_fraction: Optional maximum length as circle-radius
                fraction.
            arrow_min_threshold: Optional magnitude threshold below which the
                arrow is hidden.
            arrow_width_scales: Optional flag enabling width scaling.
            arrow_base_width_px: Optional base shaft width in pixels.
            arrow_color: Optional arrow color string.

        Returns:
            None.

        Raises:
            None.
        """
        if arrow_gain is not None:
            self.arrow_gain = float(arrow_gain)
        if arrow_max_length_fraction is not None:
            self.arrow_max_length_fraction = float(arrow_max_length_fraction)
        if arrow_min_threshold is not None:
            self.arrow_min_threshold = float(arrow_min_threshold)
        if arrow_width_scales is not None:
            self.arrow_width_scales = bool(arrow_width_scales)
        if arrow_base_width_px is not None:
            self.arrow_base_width_px = float(arrow_base_width_px)
        if arrow_color is not None:
            self.arrow_color = str(arrow_color)

    def update_display(self, shear_result: ShearResult | None) -> None:
        """Update dynamic arrow and readout for the latest shear result.

        Args:
            shear_result: Result from ``ShearDetector.detect`` or ``None`` when
                no data is available.

        Returns:
            None.

        Raises:
            None.
        """
        if shear_result is None:
            self._hide_arrow()
            self.readout_label.setText("No Data")
            self.plot_widget.getPlotItem().getViewBox().update()
            return

        geometry = self.calculate_arrow_geometry(shear_result)
        if not geometry.visible:
            self._hide_arrow()
            self.readout_label.setText("No Shear")
            self.plot_widget.getPlotItem().getViewBox().update()
            return

        self._apply_arrow_geometry(geometry)
        magnitude = f"{shear_result.shear_magnitude:.{SHEAR_READOUT_MAGNITUDE_DECIMALS}f}"
        angle = f"{shear_result.shear_angle_deg:.{SHEAR_READOUT_ANGLE_DECIMALS}f}"
        lr_component = f"{shear_result.b_lr:.{SHEAR_COMPONENT_DECIMALS}f}"
        tb_component = f"{shear_result.b_tb:.{SHEAR_COMPONENT_DECIMALS}f}"
        self.readout_label.setText(
            f"Shear: {magnitude} @ {angle} deg | LR: {lr_component}, TB: {tb_component}"
        )
        self.plot_widget.getPlotItem().getViewBox().update()

    def calculate_arrow_geometry(self, shear_result: ShearResult) -> ShearArrowGeometry:
        """Compute arrow geometry without mutating the widget.

        Args:
            shear_result: Result from ``ShearDetector.detect``.

        Returns:
            ShearArrowGeometry containing visibility, direction, length, and
            width information.

        Raises:
            None.
        """
        magnitude = float(shear_result.shear_magnitude)
        if not shear_result.has_shear or magnitude <= float(self.arrow_min_threshold):
            return self._hidden_arrow_geometry()

        max_length = self.circle_radius_mm * max(SHEAR_ZERO_VALUE, float(self.arrow_max_length_fraction))
        length = min(magnitude * float(self.arrow_gain), max_length)
        if length <= SHEAR_ZERO_VALUE:
            return self._hidden_arrow_geometry()

        angle_deg = float(shear_result.shear_angle_deg)
        angle_rad = math.radians(angle_deg)
        tip_x = length * math.cos(angle_rad)
        tip_y = length * math.sin(angle_rad)
        width_px = self._calculate_arrow_width(magnitude, length)
        return ShearArrowGeometry(
            visible=True,
            origin_x=SHEAR_ZERO_VALUE,
            origin_y=SHEAR_ZERO_VALUE,
            tip_x=tip_x,
            tip_y=tip_y,
            length=length,
            width_px=width_px,
            angle_deg=angle_deg,
        )

    def _build_sensor_positions(self) -> dict[str, tuple[float, float]]:
        spacing = float(self.sensor_spacing_mm)
        return {
            SHEAR_POSITION_CENTER: (SHEAR_ZERO_VALUE, SHEAR_ZERO_VALUE),
            SHEAR_POSITION_LEFT: (-spacing, SHEAR_ZERO_VALUE),
            SHEAR_POSITION_RIGHT: (spacing, SHEAR_ZERO_VALUE),
            SHEAR_POSITION_TOP: (SHEAR_ZERO_VALUE, spacing),
            SHEAR_POSITION_BOTTOM: (SHEAR_ZERO_VALUE, -spacing),
        }

    def _initialize_static_layout(self) -> None:
        radius = self.circle_radius_mm
        self.circle_item = QGraphicsEllipseItem(-radius, -radius, radius * 2.0, radius * 2.0)
        circle_pen = QPen(QColor(SHEAR_LAYOUT_CIRCLE_COLOR))
        circle_pen.setWidthF(SHEAR_LAYOUT_CIRCLE_LINE_WIDTH_PX)
        circle_pen.setCosmetic(SHEAR_LAYOUT_PENS_ARE_COSMETIC)
        self.circle_item.setPen(circle_pen)
        self.circle_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.circle_item.setZValue(SHEAR_STATIC_LAYOUT_Z)
        self.plot_widget.addItem(self.circle_item)

        half_side = SHEAR_SENSOR_SQUARE_SIDE_MM / 2.0
        for position, (x_coord, y_coord) in self.sensor_positions.items():
            square = QGraphicsRectItem(
                x_coord - half_side,
                y_coord - half_side,
                SHEAR_SENSOR_SQUARE_SIDE_MM,
                SHEAR_SENSOR_SQUARE_SIDE_MM,
            )
            sensor_pen = QPen(QColor(SHEAR_LAYOUT_SENSOR_OUTLINE_COLOR))
            sensor_pen.setWidthF(SHEAR_LAYOUT_SENSOR_LINE_WIDTH_PX)
            sensor_pen.setCosmetic(SHEAR_LAYOUT_PENS_ARE_COSMETIC)
            square.setPen(sensor_pen)
            square.setBrush(QBrush(QColor(SHEAR_LAYOUT_SENSOR_FILL_COLOR)))
            square.setZValue(SHEAR_STATIC_LAYOUT_Z)
            self.plot_widget.addItem(square)
            self.sensor_items[position] = square

            label = pg.TextItem(position, color=SHEAR_LAYOUT_LABEL_COLOR, anchor=(0.5, 0.5))
            label.setZValue(SHEAR_LABEL_Z)
            label.setPos(x_coord, y_coord + self._label_y_offset(position))
            self.plot_widget.addItem(label)
            self.sensor_label_items[position] = label

        limit = radius * (1.0 + SHEAR_LAYOUT_BOUNDARY_PADDING_FRACTION)
        self.plot_widget.setXRange(-limit, limit, padding=SHEAR_ZERO_VALUE)
        self.plot_widget.setYRange(-limit, limit, padding=SHEAR_ZERO_VALUE)

    def _initialize_dynamic_arrow(self) -> None:
        self.arrow_line_item.setZValue(SHEAR_ARROW_Z)
        self.arrow_head_item.setZValue(SHEAR_ARROW_Z)
        self.plot_widget.addItem(self.arrow_line_item)
        self.plot_widget.addItem(self.arrow_head_item)
        self._hide_arrow()

    def _apply_arrow_geometry(self, geometry: ShearArrowGeometry) -> None:
        pen = QPen(QColor(self.arrow_color))
        pen.setWidthF(float(geometry.width_px))
        pen.setCosmetic(SHEAR_ARROW_PEN_IS_COSMETIC)
        self.arrow_line_item.setPen(pen)
        base_x, base_y = self._calculate_arrow_head_base(geometry)
        self.arrow_line_item.setLine(
            geometry.origin_x,
            geometry.origin_y,
            base_x,
            base_y,
        )

        polygon = self._build_arrow_head_polygon(geometry)
        self.arrow_head_item.setPolygon(polygon)
        head_pen = QPen(QColor(self.arrow_color))
        head_pen.setCosmetic(SHEAR_ARROW_PEN_IS_COSMETIC)
        self.arrow_head_item.setPen(head_pen)
        self.arrow_head_item.setBrush(QBrush(QColor(self.arrow_color)))
        self.arrow_line_item.setVisible(True)
        self.arrow_head_item.setVisible(True)
        self.last_arrow_geometry = geometry

    def _build_arrow_head_polygon(self, geometry: ShearArrowGeometry) -> QPolygonF:
        angle_rad = math.radians(geometry.angle_deg)
        unit_x = math.cos(angle_rad)
        unit_y = math.sin(angle_rad)
        perpendicular_x = -unit_y
        perpendicular_y = unit_x

        half_head_width = self._calculate_arrow_head_half_width(geometry)
        base_x, base_y = self._calculate_arrow_head_base(geometry)

        return QPolygonF([
            QPointF(
                base_x + (half_head_width * perpendicular_x),
                base_y + (half_head_width * perpendicular_y),
            ),
            QPointF(geometry.tip_x, geometry.tip_y),
            QPointF(
                base_x - (half_head_width * perpendicular_x),
                base_y - (half_head_width * perpendicular_y),
            ),
        ])

    def _calculate_arrow_head_base(self, geometry: ShearArrowGeometry) -> tuple[float, float]:
        angle_rad = math.radians(geometry.angle_deg)
        unit_x = math.cos(angle_rad)
        unit_y = math.sin(angle_rad)
        head_length = min(
            geometry.length,
            max(SHEAR_ARROW_MIN_HEAD_LENGTH_MM, geometry.length * SHEAR_ARROW_HEAD_LENGTH_FRACTION),
        )
        return (
            geometry.tip_x - (head_length * unit_x),
            geometry.tip_y - (head_length * unit_y),
        )

    def _calculate_arrow_head_half_width(self, geometry: ShearArrowGeometry) -> float:
        return max(
            SHEAR_ARROW_MIN_HEAD_WIDTH_MM,
            geometry.length * SHEAR_ARROW_HEAD_WIDTH_FRACTION,
        )

    def _hide_arrow(self) -> None:
        self.arrow_line_item.setVisible(False)
        self.arrow_head_item.setVisible(False)
        self.last_arrow_geometry = self._hidden_arrow_geometry()

    def _hidden_arrow_geometry(self) -> ShearArrowGeometry:
        return ShearArrowGeometry(
            visible=False,
            origin_x=SHEAR_ZERO_VALUE,
            origin_y=SHEAR_ZERO_VALUE,
            tip_x=SHEAR_ZERO_VALUE,
            tip_y=SHEAR_ZERO_VALUE,
            length=SHEAR_ZERO_VALUE,
            width_px=float(self.arrow_base_width_px),
            angle_deg=SHEAR_ZERO_VALUE,
        )

    def _calculate_arrow_width(self, magnitude: float, length: float | None = None) -> float:
        base_width = float(self.arrow_base_width_px)
        if not self.arrow_width_scales:
            return base_width
        _ = length
        reference = max(SHEAR_ZERO_VALUE, SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE)
        magnitude_fraction = SHEAR_ZERO_VALUE if not reference else min(1.0, abs(float(magnitude)) / reference)
        scaled_width = base_width + (magnitude_fraction * SHEAR_ARROW_WIDTH_SCALE_RANGE_PX)
        return min(scaled_width, max(base_width, SHEAR_ARROW_MAX_WIDTH_PX))

    def _label_y_offset(self, position: str) -> float:
        if position == SHEAR_POSITION_BOTTOM:
            return -SHEAR_SENSOR_LABEL_OFFSET_MM
        return SHEAR_SENSOR_LABEL_OFFSET_MM
