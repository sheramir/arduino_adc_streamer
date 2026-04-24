"""
Pressure-map visualization widget for the five-sensor piezo package.

The widget renders the Step 6 backend pressure grid as a heatmap with static
sensor markers, the extended circular map boundary, and a numeric normal-force
readout. It is designed to live inside the Pressure Map tab below the shear
arrow visualization.

Dependencies:
    PyQt6, pyqtgraph, constants.shear, data_processing.normal_force_calculator,
    and data_processing.pressure_map_generator.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import QGraphicsEllipseItem, QLabel, QVBoxLayout, QWidget

from constants.shear import (
    NORMAL_FORCE_SENSOR_COUNT,
    PRESSURE_MAP_CIRCLE_Z,
    PRESSURE_MAP_COLORMAP_MAX_COLOR,
    PRESSURE_MAP_COLORMAP_MIN_COLOR,
    PRESSURE_MAP_COLORMAP_POINTS,
    PRESSURE_MAP_IMAGE_Z,
    PRESSURE_MAP_LEVEL_EPSILON,
    PRESSURE_MAP_LEVEL_SCALE_ALL_SENSORS,
    PRESSURE_MAP_LEVEL_SCALE_SINGLE_SENSOR,
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
    SHEAR_AXIS_EQUAL_ASPECT_LOCKED,
    SHEAR_COMPONENT_DECIMALS,
    SHEAR_LAYOUT_BACKGROUND,
    SHEAR_LAYOUT_CIRCLE_COLOR,
    SHEAR_LAYOUT_CIRCLE_LINE_WIDTH_PX,
    SHEAR_LAYOUT_GRID_ALPHA,
    SHEAR_LAYOUT_PENS_ARE_COSMETIC,
    SHEAR_READOUT_MAGNITUDE_DECIMALS,
    SHEAR_ZERO_VALUE,
)
from data_processing.normal_force_calculator import NormalForceResult
from data_processing.pressure_map_generator import PressureMapResult


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

        layout = QVBoxLayout(self)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(PRESSURE_MAP_PLOT_MIN_HEIGHT_PX)
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

        self.image_item = pg.ImageItem()
        self.image_item.setZValue(PRESSURE_MAP_IMAGE_Z)
        self.image_item.setLookupTable(self._grayscale_lookup_table())
        self.plot_widget.addItem(self.image_item)

        self.circle_item: QGraphicsEllipseItem | None = None
        self.sensor_marker_item = pg.ScatterPlotItem()
        self.sensor_marker_item.setZValue(PRESSURE_MAP_SENSOR_Z)
        self.plot_widget.addItem(self.sensor_marker_item)

        self.update_display(None, None)

    def update_display(
        self,
        normal_force_result: NormalForceResult | None,
        pressure_result: PressureMapResult | None,
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
        if normal_force_result is None or pressure_result is None:
            self._clear_dynamic_items()
            self.readout_label.setText("No Data")
            self.plot_widget.getPlotItem().getViewBox().update()
            return

        self._update_image(normal_force_result, pressure_result)
        self._update_boundary(pressure_result)
        self._update_sensor_markers(pressure_result)
        self._update_readout(normal_force_result, pressure_result)
        self.plot_widget.getPlotItem().getViewBox().update()

    def _clear_dynamic_items(self) -> None:
        empty_grid = np.zeros((PRESSURE_MAP_COLORMAP_POINTS, PRESSURE_MAP_COLORMAP_POINTS), dtype=np.float64)
        self.image_item.setImage(
            empty_grid,
            autoLevels=False,
            levels=(PRESSURE_MAP_ZERO_LEVEL_MIN, PRESSURE_MAP_ZERO_LEVEL_MAX),
        )
        self.sensor_marker_item.setData([])

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
        if self.circle_item is None:
            self.circle_item = QGraphicsEllipseItem(-radius, -radius, radius * 2.0, radius * 2.0)
            circle_pen = QPen(QColor(SHEAR_LAYOUT_CIRCLE_COLOR))
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
    ) -> None:
        total_force = f"{normal_force_result.total_force:.{SHEAR_READOUT_MAGNITUDE_DECIMALS}f}"
        x_coord = f"{normal_force_result.x_mm:.{SHEAR_COMPONENT_DECIMALS}f}"
        y_coord = f"{normal_force_result.y_mm:.{SHEAR_COMPONENT_DECIMALS}f}"
        self.readout_label.setText(
            f"Normal: {normal_force_result.force_type} {total_force} | "
            f"Pos: ({x_coord}, {y_coord}) mm | Quadrants: {len(pressure_result.active_quadrants)}"
        )
