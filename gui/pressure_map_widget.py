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

from dataclasses import dataclass
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

from constants.pressure_map import (
    DEFAULT_PRESSURE_MAP_MAX_INTENSITY,
    DEFAULT_PRESSURE_MIRROR,
    DEFAULT_PRESSURE_SHOW_MARKER,
    PRESSURE_MAP_BACKGROUND_COLOR,
    PRESSURE_MAP_CIRCLE_Z,
    PRESSURE_MAP_COLORMAP_MAX_COLOR,
    PRESSURE_MAP_COLORMAP_MIN_COLOR,
    PRESSURE_MAP_COLORMAP_POINTS,
    PRESSURE_MAP_IMAGE_Z,
    PRESSURE_MAP_LEVEL_EPSILON,
    PRESSURE_MAP_LEVEL_SCALE_ALL_SENSORS,
    PRESSURE_MAP_LEVEL_SCALE_SINGLE_SENSOR,
    PRESSURE_MAP_MAX_INTENSITY_MIN,
    PRESSURE_MAP_OVERLAY_COLOR,
    PRESSURE_MAP_PACKAGE_COLORS,
    PRESSURE_MAP_PACKAGE_SPACING_FRACTION,
    PRESSURE_MAP_PACKAGE_VIEW_PADDING_FRACTION,
    PRESSURE_MAP_PEAK_MARKER_COLOR,
    PRESSURE_MAP_PEAK_MARKER_PEN_WIDTH_PX,
    PRESSURE_MAP_PEAK_MARKER_SIZE_PX,
    PRESSURE_MAP_PEAK_MARKER_SYMBOL,
    PRESSURE_MAP_PEAK_MARKER_Z,
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
)
from constants.shear import (
    DEFAULT_ARROW_BASE_WIDTH_PX,
    DEFAULT_ARROW_COLOR,
    DEFAULT_ARROW_GAIN,
    DEFAULT_ARROW_MAX_LENGTH_PX,
    DEFAULT_ARROW_MIN_THRESHOLD,
    DEFAULT_ARROW_WIDTH_SCALES,
    NORMAL_FORCE_SENSOR_COUNT,
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


@dataclass(frozen=True, slots=True)
class PressureMapPackageDisplay:
    """Display-ready pressure/shear result for one selected array package."""

    sensor_id: str
    normal_force_result: NormalForceResult
    pressure_result: PressureMapResult
    shear_result: ShearResult | None = None
    grid_position: tuple[int, int] | None = None
    color: str = PRESSURE_MAP_OVERLAY_COLOR


@dataclass(slots=True)
class _PressureMapImageCache:
    pressure_grid: np.ndarray
    levels: tuple[float, float]
    rect: tuple[float, float, float, float]


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
        self.last_package_displays: list[PressureMapPackageDisplay] = []

        self.circle_radius_mm = SHEAR_ZERO_VALUE
        self.arrow_gain = DEFAULT_ARROW_GAIN
        self.arrow_max_length_fraction = DEFAULT_ARROW_MAX_LENGTH_PX
        self.arrow_min_threshold = DEFAULT_ARROW_MIN_THRESHOLD
        self.arrow_width_scales = DEFAULT_ARROW_WIDTH_SCALES
        self.arrow_base_width_px = DEFAULT_ARROW_BASE_WIDTH_PX
        self.arrow_color = DEFAULT_ARROW_COLOR
        self.show_marker = DEFAULT_PRESSURE_SHOW_MARKER
        self.max_intensity = float(DEFAULT_PRESSURE_MAP_MAX_INTENSITY)
        self.mirror = bool(DEFAULT_PRESSURE_MIRROR)
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
        self.peak_marker_item = pg.ScatterPlotItem()
        self.peak_marker_item.setZValue(PRESSURE_MAP_PEAK_MARKER_Z)
        self.plot_widget.addItem(self.peak_marker_item)

        self.arrow_line_item = QGraphicsLineItem()
        self.arrow_head_item = QGraphicsPolygonItem()
        self._initialize_dynamic_arrow()

        self.package_image_items: list[pg.ImageItem] = []
        self.package_circle_items: list[QGraphicsEllipseItem] = []
        self.package_sensor_marker_items: list[pg.ScatterPlotItem] = []
        self.package_peak_marker_items: list[pg.ScatterPlotItem] = []
        self.package_arrow_items: list[tuple[QGraphicsLineItem, QGraphicsPolygonItem]] = []
        self.package_label_items: list[pg.TextItem] = []
        self._image_cache: _PressureMapImageCache | None = None
        self._package_image_caches: list[_PressureMapImageCache | None] = []

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

    def configure_markers(self, *, show_marker: bool | None = None) -> None:
        """Update pressure-point marker visibility."""
        if show_marker is not None:
            updated_show_marker = bool(show_marker)
            if self.show_marker == updated_show_marker:
                return
            self.show_marker = updated_show_marker
            self._refresh_cached_display()

    def configure_intensity(self, *, max_intensity: float | None = None) -> None:
        """Update fixed pressure-map upper intensity level."""
        if max_intensity is not None:
            updated_max_intensity = max(float(max_intensity), PRESSURE_MAP_MAX_INTENSITY_MIN)
            if self.max_intensity == updated_max_intensity:
                return
            self.max_intensity = updated_max_intensity
            self._refresh_cached_display()

    def configure_mirror(self, *, mirror: bool | None = None) -> None:
        """Update pressure-map horizontal mirror display."""
        if mirror is not None:
            updated_mirror = bool(mirror)
            if self.mirror == updated_mirror:
                return
            self.mirror = updated_mirror
            self._refresh_cached_display()

    def _refresh_cached_display(self) -> None:
        if self.last_package_displays:
            self.update_package_displays(self.last_package_displays)
            return
        self.update_display(
            self.last_normal_force_result,
            self.last_pressure_result,
            self.last_shear_result,
        )

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
        self._clear_package_items()
        self.last_normal_force_result = normal_force_result
        self.last_pressure_result = pressure_result
        self.last_shear_result = shear_result
        self.last_package_displays = []
        if normal_force_result is None or pressure_result is None:
            self._clear_dynamic_items()
            self.readout_label.setText("No Data")
            self.plot_widget.getPlotItem().getViewBox().update()
            return

        self._update_image(normal_force_result, pressure_result)
        self._update_boundary(pressure_result)
        self._update_sensor_markers(pressure_result)
        self._update_peak_markers(pressure_result)
        self._update_shear_arrow(shear_result)
        self._update_readout(normal_force_result, pressure_result, shear_result)
        self.plot_widget.getPlotItem().getViewBox().update()

    def update_package_displays(self, packages: list[PressureMapPackageDisplay]) -> None:
        """Render multiple array sensor packages in their configured grid cells."""
        self._clear_dynamic_items()
        self.last_package_displays = list(packages)
        if not packages:
            self.last_normal_force_result = None
            self.last_pressure_result = None
            self.last_shear_result = None
            self.readout_label.setText("No Data")
            self.plot_widget.getPlotItem().getViewBox().update()
            return

        first_package = packages[0]
        self.last_normal_force_result = first_package.normal_force_result
        self.last_pressure_result = first_package.pressure_result
        self.last_shear_result = first_package.shear_result
        self._ensure_package_item_count(len(packages))

        centers = self._package_centers(packages)
        max_extent = max(float(package.pressure_result.total_extent_mm) for package in packages)
        half_extent = max_extent / PRESSURE_GRID_MARGIN_SIDE_COUNT

        for index, package in enumerate(packages):
            center_x, center_y = centers[index]
            self._update_package_image(index, package, center_x, center_y)
            self._update_package_boundary(index, package, center_x, center_y)
            self._update_package_sensor_markers(index, package, center_x, center_y)
            self._update_package_peak_markers(index, package, center_x, center_y)
            self._update_package_shear_arrow(index, package, center_x, center_y)
            self._update_package_label(index, package, center_x, center_y)

        self._hide_unused_package_items(len(packages))
        self._set_package_ranges(packages, centers, half_extent)
        self._update_package_readout(packages)
        self.plot_widget.getPlotItem().getViewBox().update()

    def _clear_dynamic_items(self) -> None:
        empty_grid = np.zeros((PRESSURE_MAP_COLORMAP_POINTS, PRESSURE_MAP_COLORMAP_POINTS), dtype=np.float64)
        self.image_item.setImage(
            empty_grid,
            autoLevels=False,
            levels=(PRESSURE_MAP_ZERO_LEVEL_MIN, PRESSURE_MAP_ZERO_LEVEL_MAX),
        )
        self._image_cache = None
        self.sensor_marker_item.setData([])
        self.peak_marker_item.setData([])
        self._hide_arrow()
        if self.circle_item is not None:
            self.circle_item.setVisible(False)

    def _clear_package_items(self) -> None:
        self._hide_unused_package_items(0)

    def _update_image(
        self,
        normal_force_result: NormalForceResult,
        pressure_result: PressureMapResult,
    ) -> None:
        levels = self._pressure_levels(normal_force_result, pressure_result.pressure_grid)
        extent = float(pressure_result.total_extent_mm)
        half_extent = extent / PRESSURE_GRID_MARGIN_SIDE_COUNT
        
        # Apply mirror flip to the grid if needed
        grid = pressure_result.pressure_grid
        if self.mirror:
            grid = np.fliplr(grid)
        
        mirror_offset = self._mirror_x(0.0)
        rect = (mirror_offset - half_extent, -half_extent, extent, extent)
        self._image_cache = self._update_cached_image_item(
            self.image_item,
            self._image_cache,
            grid,
            levels,
            rect,
        )
        self.plot_widget.setXRange(-half_extent, half_extent, padding=SHEAR_ZERO_VALUE)
        self.plot_widget.setYRange(-half_extent, half_extent, padding=SHEAR_ZERO_VALUE)

    def _update_cached_image_item(
        self,
        image_item: pg.ImageItem,
        cache: _PressureMapImageCache | None,
        pressure_grid: np.ndarray,
        levels: tuple[float, float],
        rect: tuple[float, float, float, float],
    ) -> _PressureMapImageCache:
        image_unchanged = False
        if cache is not None and cache.levels == levels and cache.rect == rect:
            image_unchanged = (
                cache.pressure_grid is pressure_grid
                or np.array_equal(cache.pressure_grid, pressure_grid)
            )

        if not image_unchanged:
            image_item.setImage(
                np.abs(pressure_grid).T,
                autoLevels=False,
                levels=levels,
            )

        image_item.setRect(QRectF(*rect))
        return _PressureMapImageCache(
            pressure_grid=pressure_grid,
            levels=levels,
            rect=rect,
        )

    def _pressure_levels(
        self,
        normal_force_result: NormalForceResult,
        pressure_grid: np.ndarray,
    ) -> tuple[float, float]:
        if self.max_intensity <= PRESSURE_MAP_LEVEL_EPSILON:
            return self._normalized_pressure_levels(normal_force_result, pressure_grid)

        level_max = max(float(self.max_intensity), PRESSURE_MAP_LEVEL_EPSILON)
        return (PRESSURE_MAP_ZERO_LEVEL_MIN, level_max)

    def _normalized_pressure_levels(
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

    def _mirror_x(self, x: float) -> float:
        """Apply horizontal mirror transformation if enabled."""
        return -x if self.mirror else x

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
        self.circle_item.setVisible(True)

    def _update_sensor_markers(self, pressure_result: PressureMapResult) -> None:
        spots = [
            {
                "pos": (self._mirror_x(x_coord), y_coord),
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

    def _update_peak_markers(self, pressure_result: PressureMapResult) -> None:
        if not self.show_marker:
            self.peak_marker_item.setData([])
            return
        self.peak_marker_item.setData(self._peak_marker_spots(pressure_result))

    def _peak_marker_spots(
        self,
        pressure_result: PressureMapResult,
        *,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> list[dict[str, object]]:
        return [
            {
                "pos": (offset_x + self._mirror_x(peak_x), offset_y + peak_y),
                "symbol": PRESSURE_MAP_PEAK_MARKER_SYMBOL,
                "size": PRESSURE_MAP_PEAK_MARKER_SIZE_PX,
                "pen": pg.mkPen(
                    PRESSURE_MAP_PEAK_MARKER_COLOR,
                    width=PRESSURE_MAP_PEAK_MARKER_PEN_WIDTH_PX,
                ),
                "brush": pg.mkBrush(PRESSURE_MAP_PEAK_MARKER_COLOR),
            }
            for plane in pressure_result.quadrant_planes
            if plane.peak_point is not None
            for peak_x, peak_y in [plane.peak_point]
        ]

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

    def _ensure_package_item_count(self, count: int) -> None:
        while len(self.package_image_items) < count:
            image_item = pg.ImageItem()
            image_item.setZValue(PRESSURE_MAP_IMAGE_Z)
            image_item.setLookupTable(self._grayscale_lookup_table())
            self.plot_widget.addItem(image_item)
            self.package_image_items.append(image_item)
            self._package_image_caches.append(None)

            circle_item = QGraphicsEllipseItem()
            circle_item.setZValue(PRESSURE_MAP_CIRCLE_Z)
            self.plot_widget.addItem(circle_item)
            self.package_circle_items.append(circle_item)

            sensor_marker_item = pg.ScatterPlotItem()
            sensor_marker_item.setZValue(PRESSURE_MAP_SENSOR_Z)
            self.plot_widget.addItem(sensor_marker_item)
            self.package_sensor_marker_items.append(sensor_marker_item)

            peak_marker_item = pg.ScatterPlotItem()
            peak_marker_item.setZValue(PRESSURE_MAP_PEAK_MARKER_Z)
            self.plot_widget.addItem(peak_marker_item)
            self.package_peak_marker_items.append(peak_marker_item)

            arrow_line_item = QGraphicsLineItem()
            arrow_head_item = QGraphicsPolygonItem()
            arrow_z = SHEAR_ARROW_Z + 1
            arrow_line_item.setZValue(arrow_z)
            arrow_head_item.setZValue(arrow_z)
            self.plot_widget.addItem(arrow_line_item)
            self.plot_widget.addItem(arrow_head_item)
            self.package_arrow_items.append((arrow_line_item, arrow_head_item))

            label_item = pg.TextItem(anchor=(0.5, 0.5))
            label_item.setZValue(PRESSURE_MAP_SENSOR_Z + 2)
            self.plot_widget.addItem(label_item)
            self.package_label_items.append(label_item)

    def _hide_unused_package_items(self, used_count: int) -> None:
        for index in range(used_count, len(self.package_image_items)):
            self.package_image_items[index].hide()
            self._package_image_caches[index] = None
            self.package_circle_items[index].hide()
            self.package_sensor_marker_items[index].setData([])
            self.package_peak_marker_items[index].setData([])
            self._hide_package_arrow(index)
            if index < len(self.package_label_items):
                self.package_label_items[index].setVisible(False)

    def _package_centers(self, packages: list[PressureMapPackageDisplay]) -> list[tuple[float, float]]:
        max_extent = max(float(package.pressure_result.total_extent_mm) for package in packages)
        spacing = max_extent * PRESSURE_MAP_PACKAGE_SPACING_FRACTION
        grid_positions = [package.grid_position for package in packages if package.grid_position is not None]

        if grid_positions:
            row_values = [row for row, _col in grid_positions]
            col_values = [col for _row, col in grid_positions]
            row_midpoint = (min(row_values) + max(row_values)) / 2.0
            col_midpoint = (min(col_values) + max(col_values)) / 2.0
            centers = []
            fallback_col = 0
            for package in packages:
                if package.grid_position is None:
                    centers.append(((fallback_col - col_midpoint) * spacing, 0.0))
                    fallback_col += 1
                    continue
                row, col = package.grid_position
                centers.append(((float(col) - col_midpoint) * spacing, (row_midpoint - float(row)) * spacing))
            return [(self._mirror_x(center_x), center_y) for center_x, center_y in centers]

        offset = (len(packages) - 1) / 2.0
        return [(self._mirror_x((index - offset) * spacing), 0.0) for index in range(len(packages))]

    def _update_package_image(
        self,
        index: int,
        package: PressureMapPackageDisplay,
        center_x: float,
        center_y: float,
    ) -> None:
        image_item = self.package_image_items[index]
        image_item.show()
        grid = package.pressure_result.pressure_grid
        if self.mirror:
            grid = np.fliplr(grid)
        levels = self._pressure_levels(package.normal_force_result, grid)
        extent = float(package.pressure_result.total_extent_mm)
        half_extent = extent / PRESSURE_GRID_MARGIN_SIDE_COUNT
        rect = (center_x - half_extent, center_y - half_extent, extent, extent)
        self._package_image_caches[index] = self._update_cached_image_item(
            image_item,
            self._package_image_caches[index],
            grid,
            levels,
            rect,
        )

    def _update_package_boundary(
        self,
        index: int,
        package: PressureMapPackageDisplay,
        center_x: float,
        center_y: float,
    ) -> None:
        radius = float(package.pressure_result.total_extent_mm) / PRESSURE_GRID_MARGIN_SIDE_COUNT
        circle_item = self.package_circle_items[index]
        circle_pen = QPen(QColor(package.color))
        circle_pen.setWidthF(SHEAR_LAYOUT_CIRCLE_LINE_WIDTH_PX)
        circle_pen.setCosmetic(SHEAR_LAYOUT_PENS_ARE_COSMETIC)
        circle_item.setPen(circle_pen)
        circle_item.setRect(center_x - radius, center_y - radius, radius * 2.0, radius * 2.0)
        circle_item.show()

    def _update_package_sensor_markers(
        self,
        index: int,
        package: PressureMapPackageDisplay,
        center_x: float,
        center_y: float,
    ) -> None:
        spots = [
            {
                "pos": (center_x + self._mirror_x(x_coord), center_y + y_coord),
                "data": (package.sensor_id, position),
                "symbol": PRESSURE_MAP_SENSOR_MARKER_SYMBOL,
                "size": PRESSURE_MAP_SENSOR_MARKER_SIZE_PX,
                "pen": pg.mkPen(
                    package.color,
                    width=PRESSURE_MAP_SENSOR_MARKER_PEN_WIDTH_PX,
                ),
                "brush": pg.mkBrush(package.color),
            }
            for position, (x_coord, y_coord) in self._sensor_positions_from_result(package.pressure_result).items()
        ]
        self.package_sensor_marker_items[index].setData(spots)

    def _update_package_peak_markers(
        self,
        index: int,
        package: PressureMapPackageDisplay,
        center_x: float,
        center_y: float,
    ) -> None:
        if not self.show_marker:
            self.package_peak_marker_items[index].setData([])
            return
        self.package_peak_marker_items[index].setData(
            self._peak_marker_spots(
                package.pressure_result,
                offset_x=center_x,
                offset_y=center_y,
            )
        )

    def _update_package_shear_arrow(
        self,
        index: int,
        package: PressureMapPackageDisplay,
        center_x: float,
        center_y: float,
    ) -> None:
        if package.shear_result is None:
            self._hide_package_arrow(index)
            return
        self.circle_radius_mm = float(package.pressure_result.total_extent_mm) / PRESSURE_GRID_MARGIN_SIDE_COUNT
        geometry = self.calculate_arrow_geometry(package.shear_result)
        if not geometry.visible:
            self._hide_package_arrow(index)
            return
        self._apply_arrow_to_items(index, geometry, center_x, center_y, self.arrow_color)

    def _update_package_label(
        self,
        index: int,
        package: PressureMapPackageDisplay,
        center_x: float,
        center_y: float,
    ) -> None:
        if index >= len(self.package_label_items):
            return
        radius = float(package.pressure_result.total_extent_mm) / PRESSURE_GRID_MARGIN_SIDE_COUNT
        label_item = self.package_label_items[index]
        label_item.setText(str(package.sensor_id), color=package.color)
        label_item.setPos(center_x, center_y + (radius * 0.82))
        label_item.setVisible(True)

    def _apply_arrow_to_items(
        self,
        index: int,
        geometry: ShearArrowGeometry,
        offset_x: float,
        offset_y: float,
        color: str,
    ) -> None:
        arrow_line_item, arrow_head_item = self.package_arrow_items[index]
        pen = QPen(QColor(color))
        pen.setWidthF(float(geometry.width_px))
        pen.setCosmetic(SHEAR_ARROW_PEN_IS_COSMETIC)
        arrow_line_item.setPen(pen)
        base_x, base_y = self._calculate_arrow_head_base(geometry)
        arrow_line_item.setLine(
            offset_x + geometry.origin_x,
            offset_y + geometry.origin_y,
            offset_x + base_x,
            offset_y + base_y,
        )

        polygon = self._build_arrow_head_polygon(geometry)
        translated_polygon = QPolygonF([
            QPointF(point.x() + offset_x, point.y() + offset_y)
            for point in polygon
        ])
        arrow_head_item.setPolygon(translated_polygon)
        head_pen = QPen(QColor(color))
        head_pen.setCosmetic(SHEAR_ARROW_PEN_IS_COSMETIC)
        arrow_head_item.setPen(head_pen)
        arrow_head_item.setBrush(QBrush(QColor(color)))
        arrow_line_item.show()
        arrow_head_item.show()
        self.last_arrow_geometry = geometry

    def _hide_package_arrow(self, index: int) -> None:
        if index >= len(self.package_arrow_items):
            return
        arrow_line_item, arrow_head_item = self.package_arrow_items[index]
        arrow_line_item.hide()
        arrow_head_item.hide()

    def _set_package_ranges(
        self,
        packages: list[PressureMapPackageDisplay],
        centers: list[tuple[float, float]],
        fallback_half_extent: float,
    ) -> None:
        if not centers or not packages:
            return

        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")
        max_radius = fallback_half_extent
        for package, (center_x, center_y) in zip(packages, centers):
            radius = float(package.pressure_result.total_extent_mm) / PRESSURE_GRID_MARGIN_SIDE_COUNT
            max_radius = max(max_radius, radius)
            min_x = min(min_x, center_x - radius)
            max_x = max(max_x, center_x + radius)
            min_y = min(min_y, center_y - radius)
            max_y = max(max_y, center_y + radius)

        span_x = max_x - min_x
        span_y = max_y - min_y
        square_half_span = max(span_x, span_y) / 2.0
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0

        # Keep a small world-space margin so circles appear larger and denser in array mode.
        padding = max_radius * PRESSURE_MAP_PACKAGE_VIEW_PADDING_FRACTION
        range_half_span = square_half_span + padding
        self.plot_widget.setXRange(
            center_x - range_half_span,
            center_x + range_half_span,
            padding=SHEAR_ZERO_VALUE,
        )
        self.plot_widget.setYRange(
            center_y - range_half_span,
            center_y + range_half_span,
            padding=SHEAR_ZERO_VALUE,
        )

    def _update_package_readout(self, packages: list[PressureMapPackageDisplay]) -> None:
        total_force = sum(float(package.normal_force_result.total_force) for package in packages)
        package_labels = ", ".join(package.sensor_id for package in packages)
        self.readout_label.setText(
            f"Array packages: {package_labels} | "
            f"Total normal: {total_force:.{SHEAR_READOUT_MAGNITUDE_DECIMALS}f}"
        )

    def package_color_for_index(self, index: int) -> str:
        return PRESSURE_MAP_PACKAGE_COLORS[int(index) % len(PRESSURE_MAP_PACKAGE_COLORS)]

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
        if self.mirror:
            tip_x = -tip_x
            angle_deg = math.degrees(math.atan2(tip_y, tip_x))
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
