"""
Pressure-map visualization widget for the five-sensor piezo package.

The widget renders the Step 6 backend pressure grid as a heatmap with static
sensor markers, the extended circular map boundary, and a numeric normal-force
readout. It also draws the live shear arrow over the pressure map.

Dependencies:
    PyQt6, pyqtgraph, constants.shear, data_processing.normal_force_calculator,
    and data_processing.pressure_map_generator.
"""

from __future__ import annotations

import math
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QBrush, QColor, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
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
    NORMAL_FORCE_SENSOR_COUNT,
    PRESSURE_MAP_BACKGROUND_COLOR,
    PRESSURE_MAP_CIRCLE_Z,
    PRESSURE_MAP_COLORMAP_MAX_COLOR,
    PRESSURE_MAP_COLORMAP_MIN_COLOR,
    PRESSURE_MAP_COLORMAP_POINTS,
    PRESSURE_MAP_IMAGE_Z,
    PRESSURE_MAP_LEVEL_EPSILON,
    PRESSURE_MAP_LEVEL_SCALE_ALL_SENSORS,
    PRESSURE_MAP_LEVEL_SCALE_SINGLE_SENSOR,
    PRESSURE_MAP_OVERLAY_COLOR,
    PRESSURE_MAP_PLOT_MIN_HEIGHT_PX,
    PRESSURE_MAP_SENSOR_MARKER_BRUSH_COLOR,
    PRESSURE_MAP_SENSOR_MARKER_PEN_COLOR,
    PRESSURE_MAP_SENSOR_MARKER_PEN_WIDTH_PX,
    PRESSURE_MAP_SENSOR_MARKER_SIZE_PX,
    PRESSURE_MAP_SENSOR_MARKER_SYMBOL,
    PRESSURE_MAP_SENSOR_Z,
    PRESSURE_MAP_WIDGET_MIN_HEIGHT_PX,
    PRESSURE_MAP_ZERO_LEVEL_MAX,
    PRESSURE_MAP_ZERO_LEVEL_MIN,
    PRESSURE_GRID_MARGIN_SIDE_COUNT,
    SHEAR_ARROW_HEAD_LENGTH_FRACTION,
    SHEAR_ARROW_HEAD_WIDTH_FRACTION,
    SHEAR_ARROW_MAX_WIDTH_PX,
    SHEAR_ARROW_MIN_HEAD_LENGTH_MM,
    SHEAR_ARROW_MIN_HEAD_WIDTH_MM,
    SHEAR_ARROW_PEN_IS_COSMETIC,
    SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE,
    SHEAR_ARROW_WIDTH_SCALE_RANGE_PX,
    SHEAR_ARROW_Z,
    SHEAR_AXIS_EQUAL_ASPECT_LOCKED,
    SHEAR_COMPONENT_DECIMALS,
    SHEAR_LAYOUT_CIRCLE_LINE_WIDTH_PX,
    SHEAR_LAYOUT_PENS_ARE_COSMETIC,
    SHEAR_READOUT_ANGLE_DECIMALS,
    SHEAR_READOUT_MAGNITUDE_DECIMALS,
    SHEAR_ZERO_VALUE,
)
from data_processing.normal_force_calculator import NormalForceResult
from data_processing.pressure_map_generator import PressureMapResult
from data_processing.shear_detector import ShearResult
from gui.shear_visualization_widget import ShearArrowGeometry


class PressureMapWidget(QWidget):
    """Display a pressure heatmap and normal-force numeric readout.

    Args:
        parent: Optional Qt parent widget.

    Usage example:
        widget = PressureMapWidget()
        widget.update_display(normal_result, pressure_result)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setMinimumHeight(PRESSURE_MAP_WIDGET_MIN_HEIGHT_PX)
        self.last_pressure_result: PressureMapResult | None = None
        self.last_normal_force_result: NormalForceResult | None = None
        self.last_shear_result: ShearResult | None = None

        self.circle_radius_mm = SHEAR_ZERO_VALUE
        self.arrow_gain = DEFAULT_ARROW_GAIN
        self.arrow_max_length_fraction = DEFAULT_ARROW_MAX_LENGTH_PX
        self.arrow_min_threshold = DEFAULT_ARROW_MIN_THRESHOLD
        self.arrow_width_scales = DEFAULT_ARROW_WIDTH_SCALES
        self.arrow_base_width_px = DEFAULT_ARROW_BASE_WIDTH_PX
        self.arrow_color = DEFAULT_ARROW_COLOR
        self.last_arrow_geometry = self._hidden_arrow_geometry()

        layout = QVBoxLayout(self)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(PRESSURE_MAP_PLOT_MIN_HEIGHT_PX)
        self.plot_widget.setBackground(PRESSURE_MAP_BACKGROUND_COLOR)
        self.plot_widget.setAspectLocked(SHEAR_AXIS_EQUAL_ASPECT_LOCKED)
        self.plot_widget.showGrid(x=False, y=False)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.getPlotItem().setMenuEnabled(False)
        self.plot_widget.getViewBox().setMouseEnabled(x=False, y=False)
        self.plot_widget.getPlotItem().hideAxis("bottom")
        self.plot_widget.getPlotItem().hideAxis("left")
        layout.addWidget(self.plot_widget)

        self.readout_label = QLabel("No Data")
        layout.addWidget(self.readout_label)

        self.image_item = pg.ImageItem()
        self.image_item.setZValue(PRESSURE_MAP_IMAGE_Z)
        self.image_item.setLookupTable(self._grayscale_lookup_table())
        self.plot_widget.addItem(self.image_item)

        self.circle_item: QGraphicsEllipseItem | None = None
        self.sensor_marker_item = pg.ScatterPlotItem()
        self.sensor_marker_item.setZValue(PRESSURE_MAP_SENSOR_Z)
        self.plot_widget.addItem(self.sensor_marker_item)

        self.arrow_line_item = QGraphicsLineItem()
        self.arrow_head_item = QGraphicsPolygonItem()
        self._initialize_dynamic_arrow()

        self.update_display(None, None, None)

    def configure_arrow(
        self,
        *,
        arrow_gain: float | None = None,
        arrow_max_length_fraction: float | None = None,
        arrow_min_threshold: float | None = None,
        arrow_width_scales: bool | None = None,
        arrow_base_width_px: float | None = None,
        arrow_color: str | None = None,
    ) -> None:
        """Update shear-arrow visualization settings."""
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

    def update_display(
        self,
        normal_force_result: NormalForceResult | None,
        pressure_result: PressureMapResult | None,
        shear_result: ShearResult | None = None,
    ) -> None:
        """Update heatmap, overlays, and readout for the latest force result.

        Args:
            normal_force_result: Step 5 output for the current sample, or
                ``None`` when no force data is available.
            pressure_result: Step 6 pressure-map output for the current sample,
                or ``None`` when no map is available.

        Returns:
            None.

        Raises:
            None.
        """
        self.last_normal_force_result = normal_force_result
        self.last_pressure_result = pressure_result
        self.last_shear_result = shear_result
        if normal_force_result is None or pressure_result is None:
            self._clear_dynamic_items()
            self.readout_label.setText("No Data")
            self.plot_widget.getPlotItem().getViewBox().update()
            return

        self._update_image(normal_force_result, pressure_result)
        self._update_boundary(pressure_result)
        self._update_sensor_markers(pressure_result)
        self._update_shear_arrow(shear_result)
        self._update_readout(normal_force_result, pressure_result, shear_result)
        self.plot_widget.getPlotItem().getViewBox().update()

    def _clear_dynamic_items(self) -> None:
        empty_grid = np.zeros((PRESSURE_MAP_COLORMAP_POINTS, PRESSURE_MAP_COLORMAP_POINTS), dtype=np.float64)
        self.image_item.setImage(
            empty_grid,
            autoLevels=False,
            levels=(PRESSURE_MAP_ZERO_LEVEL_MIN, PRESSURE_MAP_ZERO_LEVEL_MAX),
        )
        self.sensor_marker_item.setData([])
        self._hide_arrow()

    def _update_image(
        self,
        normal_force_result: NormalForceResult,
        pressure_result: PressureMapResult,
    ) -> None:
        levels = self._pressure_levels(normal_force_result, pressure_result.pressure_grid)
        self.image_item.setImage(
            np.abs(pressure_result.pressure_grid).T,
            autoLevels=False,
            levels=levels,
        )
        extent = float(pressure_result.total_extent_mm)
        half_extent = extent / PRESSURE_GRID_MARGIN_SIDE_COUNT
        self.image_item.setRect(QRectF(-half_extent, -half_extent, extent, extent))
        self.plot_widget.setXRange(-half_extent, half_extent, padding=SHEAR_ZERO_VALUE)
        self.plot_widget.setYRange(-half_extent, half_extent, padding=SHEAR_ZERO_VALUE)

    def _pressure_levels(
        self,
        normal_force_result: NormalForceResult,
        pressure_grid: np.ndarray,
    ) -> tuple[float, float]:
        finite_values = np.asarray(pressure_grid[np.isfinite(pressure_grid)], dtype=np.float64)
        if finite_values.size == 0:
            return (PRESSURE_MAP_ZERO_LEVEL_MIN, PRESSURE_MAP_ZERO_LEVEL_MAX)
        magnitude_max = max(PRESSURE_MAP_ZERO_LEVEL_MIN, float(np.max(np.abs(finite_values))))
        if magnitude_max <= PRESSURE_MAP_LEVEL_EPSILON:
            return (PRESSURE_MAP_ZERO_LEVEL_MIN, PRESSURE_MAP_ZERO_LEVEL_MAX)
        active_sensor_count = self._active_sensor_count(normal_force_result)
        level_scale = self._level_scale_for_active_sensors(active_sensor_count)
        return (PRESSURE_MAP_ZERO_LEVEL_MIN, magnitude_max * level_scale)

    def _grayscale_lookup_table(self) -> np.ndarray:
        color_map = pg.ColorMap(
            [PRESSURE_MAP_ZERO_LEVEL_MIN, PRESSURE_MAP_ZERO_LEVEL_MAX],
            [PRESSURE_MAP_COLORMAP_MIN_COLOR, PRESSURE_MAP_COLORMAP_MAX_COLOR],
        )
        return color_map.getLookupTable(nPts=PRESSURE_MAP_COLORMAP_POINTS)

    def _active_sensor_count(self, normal_force_result: NormalForceResult) -> int:
        return sum(
            1
            for value in normal_force_result.residual.values()
            if abs(value) > PRESSURE_MAP_LEVEL_EPSILON
        )

    def _level_scale_for_active_sensors(self, active_sensor_count: int) -> float:
        if NORMAL_FORCE_SENSOR_COUNT <= 1:
            return PRESSURE_MAP_LEVEL_SCALE_SINGLE_SENSOR
        clamped_count = max(1, min(NORMAL_FORCE_SENSOR_COUNT, int(active_sensor_count)))
        sensor_fraction = (clamped_count - 1) / float(NORMAL_FORCE_SENSOR_COUNT - 1)
        return PRESSURE_MAP_LEVEL_SCALE_SINGLE_SENSOR + (
            sensor_fraction
            * (PRESSURE_MAP_LEVEL_SCALE_ALL_SENSORS - PRESSURE_MAP_LEVEL_SCALE_SINGLE_SENSOR)
        )

    def _update_boundary(self, pressure_result: PressureMapResult) -> None:
        radius = float(pressure_result.total_extent_mm) / PRESSURE_GRID_MARGIN_SIDE_COUNT
        self.circle_radius_mm = radius
        if self.circle_item is None:
            self.circle_item = QGraphicsEllipseItem(-radius, -radius, radius * 2.0, radius * 2.0)
            circle_pen = QPen(QColor(PRESSURE_MAP_OVERLAY_COLOR))
            circle_pen.setWidthF(SHEAR_LAYOUT_CIRCLE_LINE_WIDTH_PX)
            circle_pen.setCosmetic(SHEAR_LAYOUT_PENS_ARE_COSMETIC)
            self.circle_item.setPen(circle_pen)
            self.circle_item.setZValue(PRESSURE_MAP_CIRCLE_Z)
            self.plot_widget.addItem(self.circle_item)
            return
        self.circle_item.setRect(-radius, -radius, radius * 2.0, radius * 2.0)

    def _update_sensor_markers(self, pressure_result: PressureMapResult) -> None:
        spots = [
            {
                "pos": (x_coord, y_coord),
                "data": position,
                "symbol": PRESSURE_MAP_SENSOR_MARKER_SYMBOL,
                "size": PRESSURE_MAP_SENSOR_MARKER_SIZE_PX,
                "pen": pg.mkPen(
                    PRESSURE_MAP_SENSOR_MARKER_PEN_COLOR,
                    width=PRESSURE_MAP_SENSOR_MARKER_PEN_WIDTH_PX,
                ),
                "brush": pg.mkBrush(PRESSURE_MAP_SENSOR_MARKER_BRUSH_COLOR),
            }
            for position, (x_coord, y_coord) in self._sensor_positions_from_result(pressure_result).items()
        ]
        self.sensor_marker_item.setData(spots)

    def _sensor_positions_from_result(self, pressure_result: PressureMapResult) -> dict[str, tuple[float, float]]:
        return dict(pressure_result.sensor_positions)

    def _update_readout(
        self,
        normal_force_result: NormalForceResult,
        pressure_result: PressureMapResult,
        shear_result: ShearResult | None,
    ) -> None:
        total_force = f"{normal_force_result.total_force:.{SHEAR_READOUT_MAGNITUDE_DECIMALS}f}"
        x_coord = f"{normal_force_result.x_mm:.{SHEAR_COMPONENT_DECIMALS}f}"
        y_coord = f"{normal_force_result.y_mm:.{SHEAR_COMPONENT_DECIMALS}f}"
        shear_text = self._shear_readout_text(shear_result)
        self.readout_label.setText(
            f"Normal: {normal_force_result.force_type} {total_force} | "
            f"Pos: ({x_coord}, {y_coord}) mm | Quadrants: {len(pressure_result.active_quadrants)} | "
            f"{shear_text}"
        )

    def _shear_readout_text(self, shear_result: ShearResult | None) -> str:
        if shear_result is None:
            return "Shear: No Data"
        if not shear_result.has_shear:
            return "Shear: None"
        magnitude = f"{shear_result.shear_magnitude:.{SHEAR_READOUT_MAGNITUDE_DECIMALS}f}"
        angle = f"{shear_result.shear_angle_deg:.{SHEAR_READOUT_ANGLE_DECIMALS}f}"
        return f"Shear: {magnitude} @ {angle} deg"

    def _initialize_dynamic_arrow(self) -> None:
        arrow_z = SHEAR_ARROW_Z + 1
        self.arrow_line_item.setZValue(arrow_z)
        self.arrow_head_item.setZValue(arrow_z)
        self.plot_widget.addItem(self.arrow_line_item)
        self.plot_widget.addItem(self.arrow_head_item)
        self._hide_arrow()

    def _update_shear_arrow(self, shear_result: ShearResult | None) -> None:
        if shear_result is None:
            self._hide_arrow()
            return
        geometry = self.calculate_arrow_geometry(shear_result)
        if not geometry.visible:
            self._hide_arrow()
            return
        self._apply_arrow_geometry(geometry)

    def calculate_arrow_geometry(self, shear_result: ShearResult) -> ShearArrowGeometry:
        """Compute shear-arrow overlay geometry in pressure-map coordinates."""
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
        width_px = self._calculate_arrow_width(magnitude)
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

    def _calculate_arrow_width(self, magnitude: float) -> float:
        base_width = float(self.arrow_base_width_px)
        if not self.arrow_width_scales:
            return base_width
        reference = max(SHEAR_ZERO_VALUE, SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE)
        magnitude_fraction = SHEAR_ZERO_VALUE if not reference else min(1.0, abs(float(magnitude)) / reference)
        scaled_width = base_width + (magnitude_fraction * SHEAR_ARROW_WIDTH_SCALE_RANGE_PX)
        return min(scaled_width, max(base_width, SHEAR_ARROW_MAX_WIDTH_PX))
