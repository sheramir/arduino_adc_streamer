"""
Pressure-map visualization widget for the five-sensor piezo package.

The widget renders the Step 6 backend pressure grid as a heatmap with static
sensor markers, a near-outer peak circle, optional outer-support and midpoint
squares, and a numeric normal-force readout. It also draws the live shear arrow
over the pressure map and can render one combined array-level pressure image.

Dependencies:
    PyQt6, pyqtgraph, constants.shear, data_processing.normal_force_calculator,
    data_processing.pressure_map_generator, and
    data_processing.pressure_map_array_generator.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from constants.pressure_map import (
    DEFAULT_PRESSURE_MASK_COLOR,
    DEFAULT_PRESSURE_MASK_ENABLED,
    DEFAULT_PRESSURE_MAP_MAX_INTENSITY,
    DEFAULT_PRESSURE_DISPLAY_FLOOR_HIGH,
    DEFAULT_PRESSURE_DISPLAY_FLOOR_LOW,
    DEFAULT_PRESSURE_MIRROR,
    DEFAULT_PRESSURE_SHOW_MID_BOUNDARY,
    DEFAULT_PRESSURE_SHOW_MARKER,
    DEFAULT_PRESSURE_SHOW_NEAR_OUTER_BOUNDARY,
    DEFAULT_PRESSURE_SHOW_OUTER_BOUNDARY,
    DEFAULT_PRESSURE_SHOW_SENSOR_MARKERS,
    PRESSURE_DISPLAY_MODE_MAGNITUDE,
    PRESSURE_DISPLAY_MODE_SIGNED,
    PRESSURE_MAP_BACKGROUND_COLOR,
    PRESSURE_MAP_CIRCLE_Z,
    PRESSURE_MAP_COLORMAP_POINTS,
    PRESSURE_MAP_IMAGE_Z,
    PRESSURE_MAP_LEVEL_EPSILON,
    PRESSURE_MAP_LEVEL_SCALE_ALL_SENSORS,
    PRESSURE_MAP_LEVEL_SCALE_SINGLE_SENSOR,
    PRESSURE_MAP_MASK_OUTLINE_Z,
    PRESSURE_MAP_MAX_INTENSITY_MIN,
    PRESSURE_MAP_OVERLAY_COLOR,
    PRESSURE_MAP_PACKAGE_COLORS,
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
    PRESSURE_MASK_OUTLINE_WIDTH_PX,
    PRESSURE_SUPPORT_SIDE_COUNT,
)
from constants.shear import (
    DEFAULT_ARROW_BASE_WIDTH_PX,
    DEFAULT_ARROW_COLOR,
    DEFAULT_ARROW_GAIN,
    DEFAULT_ARROW_MAX_LENGTH_PX,
    DEFAULT_ARROW_MIN_THRESHOLD,
    DEFAULT_ARROW_WIDTH_SCALES,
    NORMAL_FORCE_SENSOR_COUNT,
    SHEAR_ARROW_PEN_IS_COSMETIC,
    SHEAR_ARROW_Z,
    SHEAR_AXIS_EQUAL_ASPECT_LOCKED,
    SHEAR_COMPONENT_DECIMALS,
    SHEAR_LAYOUT_CIRCLE_LINE_WIDTH_PX,
    SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE,
    SHEAR_LAYOUT_PENS_ARE_COSMETIC,
    SHEAR_READOUT_ANGLE_DECIMALS,
    SHEAR_READOUT_MAGNITUDE_DECIMALS,
    SHEAR_ZERO_VALUE,
)
from data_processing.normal_force_calculator import NormalForceResult
from data_processing.pressure_map_array_generator import PressureMapArrayResult
from data_processing.pressure_map_mask import PressureMapMaskGeometry, mask_inside_grid
from data_processing.pressure_map_generator import PressureMapResult
from data_processing.shear_detector import ShearResult
from gui.shear_visualization_widget import ShearArrowGeometry, ShearArrowRenderMixin


def image_rect_from_centers(
    x_coordinates: np.ndarray,
    y_coordinates: np.ndarray,
    *,
    mirror_x: bool = False,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> QRectF:
    """Build a pixel-edge image rectangle from ascending grid-centre arrays."""

    x_values = np.asarray(x_coordinates, dtype=np.float64)
    y_values = np.asarray(y_coordinates, dtype=np.float64)
    if x_values.size < 2 or y_values.size < 2:
        raise ValueError("image coordinate arrays must contain at least two centres")
    dx = float(x_values[1] - x_values[0])
    dy = float(y_values[1] - y_values[0])
    if dx <= 0.0 or dy <= 0.0:
        raise ValueError("image coordinate arrays must be strictly increasing")
    left = (-float(x_values[-1]) if mirror_x else float(x_values[0])) - (dx / 2.0)
    bottom = float(y_values[0]) - (dy / 2.0)
    return QRectF(
        left + float(offset_x),
        bottom + float(offset_y),
        float(x_values[-1] - x_values[0] + dx),
        float(y_values[-1] - y_values[0] + dy),
    )


def _rect_tuple(rect: QRectF) -> tuple[float, float, float, float]:
    """Convert a Qt rectangle once for the image cache's value comparison."""

    return (rect.x(), rect.y(), rect.width(), rect.height())


@dataclass(frozen=True, slots=True)
class PressureMapPackageDisplay:
    """Display-ready pressure/shear result for one selected array package."""

    sensor_id: str
    normal_force_result: NormalForceResult
    pressure_result: PressureMapResult
    shear_result: ShearResult | None = None
    grid_position: tuple[int, int] | None = None
    color: str = PRESSURE_MAP_OVERLAY_COLOR
    calibrated_values: dict[str, float] | None = None


@dataclass(slots=True)
class _PressureMapImageCache:
    cache_key: tuple[object, ...]
    pressure_grid: np.ndarray
    levels: tuple[float, float]
    rect: tuple[float, float, float, float]


class PressureMapWidget(ShearArrowRenderMixin, QWidget):
    """Display a pressure heatmap and normal-force numeric readout.

    Args:
        parent: Optional Qt parent widget.

    Usage example:
        widget = PressureMapWidget()
        widget.update_display(normal_result, pressure_result)
    """

    COLOR_MAPS = {
        "Thermal": [
            (0, 0, 0, 0),
            (0, 32, 96, 255),
            (0, 180, 160, 255),
            (255, 220, 64, 255),
            (255, 48, 32, 255),
        ],
        "Grayscale": [
            (0, 0, 0, 0),
            (70, 70, 70, 255),
            (140, 140, 140, 255),
            (210, 210, 210, 255),
            (255, 255, 255, 255),
        ],
        "Viridis": [
            (0, 0, 0, 0),
            (68, 1, 84, 255),
            (59, 82, 139, 255),
            (33, 145, 140, 255),
            (253, 231, 37, 255),
        ],
        "Magma": [
            (0, 0, 0, 0),
            (80, 18, 123, 255),
            (182, 54, 121, 255),
            (251, 136, 97, 255),
            (252, 253, 191, 255),
        ],
    }
    ARROW_COLORS = {
        "Thermal": "#FFFFFF",
        "Grayscale": DEFAULT_ARROW_COLOR,
        "Viridis": DEFAULT_ARROW_COLOR,
        "Magma": "#FFFFFF",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setMinimumHeight(PRESSURE_MAP_WIDGET_MIN_HEIGHT_PX)
        self.last_pressure_result: PressureMapResult | None = None
        self.last_normal_force_result: NormalForceResult | None = None
        self.last_shear_result: ShearResult | None = None
        self.last_package_displays: list[PressureMapPackageDisplay] = []
        self.last_array_result: PressureMapArrayResult | None = None
        self.last_force_result = None
        self.last_force_array_result = None
        self.last_force_package_results: list[object] = []

        self.circle_radius_mm = SHEAR_ZERO_VALUE
        self.arrow_gain = DEFAULT_ARROW_GAIN
        self.arrow_max_length_fraction = DEFAULT_ARROW_MAX_LENGTH_PX
        self.arrow_min_threshold = DEFAULT_ARROW_MIN_THRESHOLD
        self.arrow_width_scales = DEFAULT_ARROW_WIDTH_SCALES
        self.arrow_base_width_px = DEFAULT_ARROW_BASE_WIDTH_PX
        self.arrow_width_reference_magnitude = SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE
        self.arrow_color = DEFAULT_ARROW_COLOR
        self.show_marker = DEFAULT_PRESSURE_SHOW_MARKER
        self.show_sensor_markers = DEFAULT_PRESSURE_SHOW_SENSOR_MARKERS
        self.show_near_outer_boundary = DEFAULT_PRESSURE_SHOW_NEAR_OUTER_BOUNDARY
        self.show_outer_boundary = DEFAULT_PRESSURE_SHOW_OUTER_BOUNDARY
        self.show_mid_boundary = DEFAULT_PRESSURE_SHOW_MID_BOUNDARY
        self.max_intensity = float(DEFAULT_PRESSURE_MAP_MAX_INTENSITY)
        self.force_max_intensity_n = 0.25
        self.force_alpha_floor_n = 0.0025
        # Display-only alpha fade.  The backend, levels, and sensor activity
        # threshold are deliberately not changed by these values.
        self.noise_floor = PRESSURE_MAP_ZERO_LEVEL_MIN
        self.display_floor_low = DEFAULT_PRESSURE_DISPLAY_FLOOR_LOW
        self.display_floor_high = DEFAULT_PRESSURE_DISPLAY_FLOOR_HIGH
        self.saturated_pixel_percentage = 0.0
        # Opt-in callers can inspect these backend diagnostics without any
        # display auto-scaling or numerical-path changes.
        self.debug_backend_maximum = 0.0
        self.debug_saturation_mask: np.ndarray | None = None
        self.mirror = bool(DEFAULT_PRESSURE_MIRROR)
        # Masking is an array-rendering-only alpha crop.  The source pressure
        # grids and every downstream calculation remain untouched.
        self.mask_enabled = bool(DEFAULT_PRESSURE_MASK_ENABLED)
        self.mask_points_mm: tuple[tuple[float, float], ...] = ()
        self.mask_color = DEFAULT_PRESSURE_MASK_COLOR
        self._mask_grid_cache: tuple[tuple[object, ...], np.ndarray] | None = None
        self.color_scale = "Grayscale"
        self.display_mode = PRESSURE_DISPLAY_MODE_MAGNITUDE
        self._color_maps: dict[str, pg.ColorMap] = {}
        self.last_arrow_geometry = self._hidden_arrow_geometry()

        layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
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
        self.readout_label.setWordWrap(True)
        self.readout_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.readout_label)

        self.image_item = pg.ImageItem()
        self.image_item.setZValue(PRESSURE_MAP_IMAGE_Z)
        self.image_item.setLookupTable(self._color_lookup_table())
        self.plot_widget.addItem(self.image_item)

        self.mask_outline_item = QGraphicsPolygonItem()
        self.mask_outline_item.setZValue(PRESSURE_MAP_MASK_OUTLINE_Z)
        self.mask_outline_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.plot_widget.addItem(self.mask_outline_item)
        self._style_mask_outline()
        self._hide_mask_outline()

        self.circle_item: QGraphicsEllipseItem | QGraphicsRectItem | None = None
        self.outer_boundary_item: QGraphicsRectItem | None = None
        self.mid_boundary_item: QGraphicsRectItem | None = None
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
        self.package_circle_items: list[QGraphicsEllipseItem | QGraphicsRectItem] = []
        self.package_outer_boundary_items: list[QGraphicsRectItem] = []
        self.package_mid_boundary_items: list[QGraphicsRectItem] = []
        self.package_sensor_marker_items: list[pg.ScatterPlotItem] = []
        self.package_peak_marker_items: list[pg.ScatterPlotItem] = []
        self.package_arrow_items: list[tuple[QGraphicsLineItem, QGraphicsPolygonItem]] = []
        self.force_callout_items: list[pg.TextItem] = []
        self._image_cache: _PressureMapImageCache | None = None
        self._package_image_caches: list[_PressureMapImageCache | None] = []
        self._view_mode: str | None = None
        self._view_range_signature: tuple[object, ...] | None = None

        self.update_display(None, None, None)

    def configure_arrow(
        self,
        *,
        arrow_gain: float | None = None,
        arrow_max_length_fraction: float | None = None,
        arrow_min_threshold: float | None = None,
        arrow_width_scales: bool | None = None,
        arrow_base_width_px: float | None = None,
        arrow_width_reference_magnitude: float | None = None,
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
        if arrow_width_reference_magnitude is not None:
            self.arrow_width_reference_magnitude = float(arrow_width_reference_magnitude)
        if arrow_color is not None:
            self.arrow_color = str(arrow_color)

    def configure_markers(
        self,
        *,
        show_marker: bool | None = None,
        show_sensor_markers: bool | None = None,
    ) -> None:
        """Update pressure-point marker and sensor-placeholder visibility."""
        changed = False
        if show_marker is not None:
            updated_show_marker = bool(show_marker)
            if self.show_marker != updated_show_marker:
                self.show_marker = updated_show_marker
                changed = True
        if show_sensor_markers is not None:
            updated_show_sensor_markers = bool(show_sensor_markers)
            if self.show_sensor_markers != updated_show_sensor_markers:
                self.show_sensor_markers = updated_show_sensor_markers
                changed = True
        if changed:
            self._refresh_cached_display()

    def configure_boundary_visibility(
        self,
        *,
        show_near_outer_boundary: bool | None = None,
        show_outer_boundary: bool | None = None,
        show_mid_boundary: bool | None = None,
    ) -> None:
        """Toggle the near-outer circle, outer-support square, and mid square."""
        changed = False
        for attribute, value in (
            ("show_near_outer_boundary", show_near_outer_boundary),
            ("show_outer_boundary", show_outer_boundary),
            ("show_mid_boundary", show_mid_boundary),
        ):
            if value is None:
                continue
            updated = bool(value)
            if getattr(self, attribute) != updated:
                setattr(self, attribute, updated)
                changed = True
        if changed:
            self._refresh_cached_display()

    def configure_intensity(self, *, max_intensity: float | None = None) -> None:
        """Update fixed pressure-map upper intensity level."""
        if max_intensity is not None:
            updated_max_intensity = max(float(max_intensity), PRESSURE_MAP_MAX_INTENSITY_MIN)
            if self.max_intensity == updated_max_intensity:
                return
            self.max_intensity = updated_max_intensity
            self._refresh_cached_display()

    def configure_force_intensity(self, *, max_force_n: float | None = None) -> None:
        """Set the stable physical N colour range used only by Force Display."""
        if max_force_n is None:
            return
        updated = max(float(max_force_n), PRESSURE_MAP_LEVEL_EPSILON)
        if updated != self.force_max_intensity_n:
            self.force_max_intensity_n = updated
            self._refresh_cached_display()

    def configure_force_display_floor(self, *, noise_equivalent_n: float | None = None) -> None:
        """Set the display-only alpha floor for valid small force fields."""
        if noise_equivalent_n is None:
            return
        updated = max(float(noise_equivalent_n), PRESSURE_MAP_LEVEL_EPSILON)
        if updated != self.force_alpha_floor_n:
            self.force_alpha_floor_n = updated
            self._refresh_cached_display()

    def configure_noise_floor(self, *, noise_floor: float | None = None) -> None:
        """Set the lower edge of the display-only smooth alpha fade."""
        if noise_floor is None:
            return
        updated_noise_floor = max(float(noise_floor), PRESSURE_MAP_ZERO_LEVEL_MIN)
        if self.noise_floor == updated_noise_floor:
            return
        self.noise_floor = updated_noise_floor
        self.display_floor_low = updated_noise_floor
        self.display_floor_high = updated_noise_floor + max(
            PRESSURE_MAP_LEVEL_EPSILON,
            float(self.max_intensity) * 0.02,
        )
        self._refresh_cached_display()

    def configure_display_alpha(
        self, *, display_floor_low: float | None = None, display_floor_high: float | None = None
    ) -> None:
        """Configure a smooth alpha fade without altering numeric colour levels."""

        low = self.display_floor_low if display_floor_low is None else max(0.0, float(display_floor_low))
        high = self.display_floor_high if display_floor_high is None else max(low, float(display_floor_high))
        if (low, high) == (self.display_floor_low, self.display_floor_high):
            return
        self.display_floor_low, self.display_floor_high = low, high
        self._refresh_cached_display()

    def configure_color_scale(self, *, color_scale: str | None = None) -> None:
        """Update the pressure-map color scale and its contrasting shear arrow."""
        if color_scale not in self.COLOR_MAPS or color_scale == self.color_scale:
            return
        self.color_scale = color_scale
        self.arrow_color = self.ARROW_COLORS[color_scale]
        lookup_table = self._color_lookup_table()
        self.image_item.setLookupTable(lookup_table)
        for image_item in self.package_image_items:
            image_item.setLookupTable(lookup_table)
        self._refresh_cached_display()

    def configure_mirror(self, *, mirror: bool | None = None) -> None:
        """Update pressure-map horizontal mirror display."""
        if mirror is not None:
            updated_mirror = bool(mirror)
            if self.mirror == updated_mirror:
                return
            self.mirror = updated_mirror
            self._invalidate_view_range()
            self._refresh_cached_display()

    def configure_mask(
        self,
        *,
        mask_enabled: bool | None = None,
        mask_points_mm: tuple[tuple[float, float], ...] | list[tuple[float, float]] | None = None,
        mask_color: str | None = None,
    ) -> None:
        """Configure the display-only polygon crop used for array images."""

        changed = False
        if mask_enabled is not None:
            updated_enabled = bool(mask_enabled)
            if updated_enabled != self.mask_enabled:
                self.mask_enabled = updated_enabled
                changed = True

        if mask_points_mm is not None:
            raw_points = tuple(mask_points_mm)
            updated_points = (
                PressureMapMaskGeometry("mask", raw_points).points_mm
                if raw_points
                else ()
            )
            if updated_points != self.mask_points_mm:
                self.mask_points_mm = updated_points
                self._mask_grid_cache = None
                changed = True

        if mask_color is not None:
            updated_color = str(mask_color)
            if updated_color != self.mask_color:
                self.mask_color = updated_color
                self._style_mask_outline()
                changed = True

        if changed:
            self._refresh_cached_display()

    def configure_display_mode(self, *, display_mode: str | None = None) -> None:
        """Choose magnitude (default) or signed pressure rendering only."""
        if display_mode not in (PRESSURE_DISPLAY_MODE_MAGNITUDE, PRESSURE_DISPLAY_MODE_SIGNED):
            return
        if self.display_mode != display_mode:
            self.display_mode = display_mode
            lookup_table = self._color_lookup_table()
            self.image_item.setLookupTable(lookup_table)
            for image_item in self.package_image_items:
                image_item.setLookupTable(lookup_table)
            self._refresh_cached_display()

    def _display_grid(self, grid: np.ndarray) -> np.ndarray:
        return np.abs(grid) if self.display_mode == PRESSURE_DISPLAY_MODE_MAGNITUDE else grid

    @staticmethod
    def _force_display_grid(grid: np.ndarray) -> np.ndarray:
        """Force Display is always magnitude-only, independent of Jerk mode."""
        return np.abs(np.asarray(grid, dtype=np.float64))

    def _array_display_grid(self, array_result: PressureMapArrayResult) -> np.ndarray:
        """Select the separately blended magnitude field when rendering arrays."""

        if self.display_mode == PRESSURE_DISPLAY_MODE_MAGNITUDE:
            return array_result.magnitude_pressure_grid
        return array_result.pressure_grid

    def _refresh_cached_display(self) -> None:
        if self._view_mode == "force-array" and self.last_force_array_result is not None:
            self.update_force_array_display(self.last_force_array_result, self.last_force_package_results)
            return
        if self._view_mode == "force" and self.last_force_result is not None:
            self.update_force_display(self.last_force_result)
            return
        if self.last_array_result is not None and self.last_package_displays:
            self.update_array_display(self.last_array_result, self.last_package_displays)
            return
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
        self.readout_label.setVisible(True)
        self._hide_force_callouts()
        self._set_view_mode(
            "single" if normal_force_result is not None and pressure_result is not None else "empty"
        )
        self._clear_package_items()
        self._hide_mask_outline()
        self.image_item.show()
        self.last_normal_force_result = normal_force_result
        self.last_pressure_result = pressure_result
        self.last_shear_result = shear_result
        self.last_package_displays = []
        self.last_array_result = None
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

    def update_force_display(self, force_result) -> None:
        """Render an accumulated force raster without fabricating a pressure result.

        ``ForceMapPackageResult`` intentionally does not contain a historical
        peak/quadrant model, so this path draws the shared geometry and sensor
        positions but always clears peak markers.
        """
        if force_result is None:
            self.update_display(None, None, None)
            return
        self.readout_label.setVisible(True)
        self._hide_force_callouts()
        self._set_view_mode("force")
        self._clear_package_items()
        self._clear_dynamic_items(clear_image=False)
        self._hide_mask_outline()
        self.image_item.show()
        self.last_normal_force_result = None
        self.last_pressure_result = None
        self.last_shear_result = None
        self.last_package_displays = []
        self.last_array_result = None
        self.last_force_result = force_result
        self.last_force_array_result = None
        self.last_force_package_results = []

        grid = self._force_display_grid(force_result.force_grid_n)
        if self.mirror:
            grid = np.fliplr(grid)
        levels, fade_levels = self._force_render_levels(grid)
        image_rect = image_rect_from_centers(
            force_result.x_coordinates_mm,
            force_result.y_coordinates_mm,
            mirror_x=self.mirror,
        )
        self._image_cache = self._update_cached_image_item(
            self.image_item,
            self._image_cache,
            grid,
            levels,
            _rect_tuple(image_rect),
            cache_key=("force", force_result.frame_id, *self._force_image_cache_key(force_result.frame_id)),
            fade_levels=fade_levels,
            force_mode=True,
        )
        self.saturated_pixel_percentage = self._saturated_pixel_percentage(
            grid, self.force_max_intensity_n
        )
        self.debug_backend_maximum = float(np.max(np.abs(grid)))
        self.debug_saturation_mask = np.abs(grid) >= self.force_max_intensity_n
        self._update_force_geometry(force_result)
        self.peak_marker_item.setData([])  # Force Display never has peak markers.
        self._update_shear_arrow(getattr(force_result, "shear_result", None))
        self.readout_label.setText(
            f"{force_result.sensor_id} | Normal Force: {force_result.normal_force_n:.3f} N | "
            f"Shear Force: {force_result.shear_force_n:.3f} N"
            f"{self._saturation_indicator()}"
        )
        signature = ("force", force_result.geometry, _rect_tuple(image_rect), self.mirror)
        if signature != self._view_range_signature:
            self._set_single_ranges(image_rect, signature)
        self.plot_widget.getPlotItem().getViewBox().update()

    def _update_force_geometry(self, force_result) -> None:
        """Draw shared pressure-map boundaries and physical sensor positions."""
        geometry = force_result.geometry
        self._update_boundary_geometry(
            visual_radius_mm=float(geometry.near_outer_circle_radius_mm),
            outer_half_width_mm=float(geometry.outer_boundary_half_width_mm),
            mid_half_width_mm=float(geometry.mid_boundary_half_width_mm),
        )
        self.sensor_marker_item.setData(
            [
                {
                    "pos": (self._mirror_x(x_coord), y_coord),
                    "symbol": PRESSURE_MAP_SENSOR_MARKER_SYMBOL,
                    "size": PRESSURE_MAP_SENSOR_MARKER_SIZE_PX,
                    "pen": pg.mkPen(PRESSURE_MAP_SENSOR_MARKER_PEN_COLOR, width=PRESSURE_MAP_SENSOR_MARKER_PEN_WIDTH_PX),
                    "brush": pg.mkBrush(PRESSURE_MAP_SENSOR_MARKER_BRUSH_COLOR),
                }
                for x_coord, y_coord in force_result.sensor_positions.values()
            ]
            if self.show_sensor_markers
            else []
        )

    def update_force_array_display(self, force_array, packages) -> None:
        """Render an accumulated world-space force field with no peak model."""
        if force_array is None:
            self.update_force_display(None)
            return
        self.readout_label.setVisible(False)
        self._set_view_mode("force-array")
        self._clear_package_items()
        self._clear_dynamic_items(clear_image=False)
        self.image_item.show()
        self.last_normal_force_result = None
        self.last_pressure_result = None
        self.last_shear_result = None
        self.last_package_displays = []
        self.last_array_result = None
        self.last_force_result = None
        self.last_force_array_result = force_array
        self.last_force_package_results = list(packages)
        # This is separately composited from absolute local package fields;
        # never use abs(signed_array_grid), since overlaps can cancel there.
        grid = self._force_display_grid(force_array.magnitude_force_grid_n)
        visibility_mask = None
        if self.mask_enabled and self.mask_points_mm:
            x_grid, y_grid = np.meshgrid(force_array.x_coordinates_mm, force_array.y_coordinates_mm)
            visibility_mask = mask_inside_grid(self.mask_points_mm, x_grid, y_grid)
        if self.mirror:
            grid = np.fliplr(grid)
            if visibility_mask is not None:
                visibility_mask = np.fliplr(visibility_mask)
        levels, fade_levels = self._force_render_levels(grid)
        image_rect = image_rect_from_centers(
            force_array.x_coordinates_mm, force_array.y_coordinates_mm, mirror_x=self.mirror
        )
        self._image_cache = self._update_cached_image_item(
            self.image_item, self._image_cache, grid, levels, _rect_tuple(image_rect),
            cache_key=("force-array", force_array.frame_id, *self._force_image_cache_key(force_array.frame_id)),
            visibility_mask=visibility_mask,
            fade_levels=fade_levels,
            force_mode=True,
        )
        self._update_force_array_package_overlays(packages, force_array.package_centers)
        # Array package marker items are the same reusable items Jerk uses.
        # Do not draw a second marker layer over them.
        self.sensor_marker_item.setData([])
        self.peak_marker_item.setData([])
        self._hide_arrow()
        self._update_mask_outline(force_array)
        self.saturated_pixel_percentage = self._saturated_pixel_percentage(
            grid, self.force_max_intensity_n
        )
        self.debug_backend_maximum = float(np.max(np.abs(grid)))
        self.debug_saturation_mask = np.abs(grid) >= self.force_max_intensity_n
        # Force callouts deliberately live beyond each package's outer support.
        # Reserve that space in the static Force viewport once, rather than
        # allowing the changing force values or callout text to move the view.
        callout_bounds = self._force_array_display_bounds(force_array.package_centers, packages)
        view_rect = image_rect.united(self._rect_from_bounds(callout_bounds))
        signature = ("force-array", _rect_tuple(view_rect), self.mirror)
        if signature != self._view_range_signature:
            self._set_single_ranges(view_rect, signature)
        self.plot_widget.getPlotItem().getViewBox().update()

    def _update_force_array_package_overlays(self, packages, centers) -> None:
        """Reuse the Jerk package background for the Force content layer."""
        self._ensure_package_item_count(len(packages))
        self._ensure_force_callout_count(len(packages))
        raw_array_center = self._force_array_center(centers)
        array_center = (self._mirror_x(raw_array_center[0]), raw_array_center[1])
        array_bounds = self._force_array_display_bounds(centers, packages)
        occupied_callouts: list[tuple[float, float]] = []
        for index, package in enumerate(packages):
            center_x, center_y = centers.get(package.sensor_id, (0.0, 0.0))
            center_x = self._mirror_x(float(center_x))
            center_y = float(center_y)
            color = self.package_color_for_index(index)
            self._update_package_boundary_geometry(
                index,
                geometry=package.geometry,
                color=color,
                center_x=center_x,
                center_y=center_y,
                mid_half_extent_mm=float(package.geometry.mid_boundary_half_width_mm),
            )
            self._update_package_sensor_markers_geometry(
                index,
                sensor_id=package.sensor_id,
                sensor_positions=package.sensor_positions,
                color=color,
                center_x=center_x,
                center_y=center_y,
            )
            self.package_peak_marker_items[index].setData([])
            self._update_force_package_shear_arrow(index, package, center_x, center_y)
            callout_x, callout_y = self._force_callout_position(
                center_x, center_y, array_center, array_bounds,
                float(package.geometry.outer_boundary_half_width_mm), occupied_callouts,
            )
            occupied_callouts.append((callout_x, callout_y))
            callout = self.force_callout_items[index]
            callout.setText(
                f"N: {package.normal_force_n:.3f} N\nS: {package.shear_force_n:.3f} N"
            )
            callout.setColor(color)
            callout.setPos(callout_x, callout_y)
            callout.setVisible(True)
        self._hide_unused_package_items(len(packages))
        self._hide_unused_force_callouts(len(packages))

    def _ensure_force_callout_count(self, count: int) -> None:
        while len(self.force_callout_items) < count:
            item = pg.TextItem(
                color=PRESSURE_MAP_OVERLAY_COLOR,
                anchor=(0.5, 0.5),
                border=QColor(PRESSURE_MAP_OVERLAY_COLOR),
                fill=QColor(0, 0, 0, 210),
                ensureInBounds=False,
            )
            item.setZValue(PRESSURE_MAP_SENSOR_Z + 4)
            self.plot_widget.addItem(item)
            self.force_callout_items.append(item)

    def _hide_force_callouts(self) -> None:
        for item in self.force_callout_items:
            item.setVisible(False)

    def _hide_unused_force_callouts(self, used_count: int) -> None:
        for item in self.force_callout_items[used_count:]:
            item.setVisible(False)

    @staticmethod
    def _force_array_center(centers) -> tuple[float, float]:
        values = tuple(centers.values())
        if not values:
            return (0.0, 0.0)
        return (
            float(sum(value[0] for value in values) / len(values)),
            float(sum(value[1] for value in values) / len(values)),
        )

    @staticmethod
    def _force_array_bounds(centers, packages) -> tuple[float, float, float, float]:
        """Return static raw-coordinate limits that include external callouts."""
        extent = max(
            (float(package.geometry.outer_boundary_half_width_mm) for package in packages),
            default=1.0,
        )
        # Include a compact text footprint as well as the callout centre.  The
        # footprint is intentionally geometry-only so Force values never cause
        # the viewport to resize or pan.
        callout_extent = PressureMapWidget._force_callout_offset(extent) + 1.5
        values = tuple(centers.values()) or ((0.0, 0.0),)
        return (
            min(float(value[0]) for value in values) - callout_extent,
            max(float(value[0]) for value in values) + callout_extent,
            min(float(value[1]) for value in values) - callout_extent,
            max(float(value[1]) for value in values) + callout_extent,
        )

    def _force_array_display_bounds(self, centers, packages) -> tuple[float, float, float, float]:
        """Return Force callout bounds in the same coordinates as the display."""
        min_x, max_x, min_y, max_y = self._force_array_bounds(centers, packages)
        if self.mirror:
            return (-max_x, -min_x, min_y, max_y)
        return (min_x, max_x, min_y, max_y)

    @staticmethod
    def _rect_from_bounds(bounds: tuple[float, float, float, float]) -> QRectF:
        min_x, max_x, min_y, max_y = bounds
        return QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

    @staticmethod
    def _force_callout_offset(package_extent: float) -> float:
        """Place the full callout clear of the package's outer boundary."""
        outer_extent = max(0.0, float(package_extent))
        # Keep the label immediately outside the outer square.  The small
        # allowance covers its border without creating a large empty margin.
        return outer_extent + max(1.5, outer_extent * 0.20)

    def _force_callout_position(
        self,
        center_x: float,
        center_y: float,
        array_center: tuple[float, float],
        bounds: tuple[float, float, float, float],
        package_extent: float,
        occupied: list[tuple[float, float]],
    ) -> tuple[float, float]:
        """Pick a static outward callout location without affecting view bounds."""
        dx, dy = center_x - array_center[0], center_y - array_center[1]
        if abs(dx) >= abs(dy) and abs(dx) > PRESSURE_MAP_LEVEL_EPSILON:
            preferred = (1.0 if dx > 0.0 else -1.0, 0.0)
        elif abs(dy) > PRESSURE_MAP_LEVEL_EPSILON:
            preferred = (0.0, 1.0 if dy > 0.0 else -1.0)
        else:
            preferred = (1.0, 1.0)
        directions = (preferred, (1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))
        min_x, max_x, min_y, max_y = bounds
        # The N/S callout belongs outside the outer package boundary, never in
        # the mid-boundary area.  The Force viewport reserves this fixed margin
        # from geometry, so this does not alter the view while streaming.
        offset = self._force_callout_offset(package_extent)
        mask_polygon = QPolygonF([
            QPointF(self._mirror_x(x_coord), y_coord) for x_coord, y_coord in self.mask_points_mm
        ]) if self.mask_enabled and self.mask_points_mm else None
        candidates: list[tuple[bool, float, float]] = []
        for direction_x, direction_y in directions:
            candidate_x = center_x + direction_x * offset
            candidate_y = center_y + direction_y * offset
            if not (min_x <= candidate_x <= max_x and min_y <= candidate_y <= max_y):
                continue
            inside_mask = bool(mask_polygon and mask_polygon.containsPoint(
                QPointF(candidate_x, candidate_y), Qt.FillRule.OddEvenFill
            ))
            collision = any(
                abs(candidate_x - used_x) < 4.8 and abs(candidate_y - used_y) < 2.6
                for used_x, used_y in occupied
            )
            candidates.append((inside_mask or collision, candidate_x, candidate_y))
        if candidates:
            _penalized, candidate_x, candidate_y = next(
                (item for item in candidates if not item[0]), candidates[0]
            )
            return candidate_x, candidate_y
        return (center_x, center_y - offset)

    def _force_render_levels(self, force_grid: np.ndarray) -> tuple[tuple[float, float], tuple[float, float]]:
        """Use a physical-N raster scale; Jerk's fixed voltage scale is inapplicable."""
        # Unlike Jerk's voltage display, force colour is physically stable:
        # 0.1 N maps to the same colour on every frame.
        peak = max(float(self.force_max_intensity_n), PRESSURE_MAP_LEVEL_EPSILON)
        levels = (0.0, peak)
        # Preserve the selected colour map while making the smallest visible
        # physical force opaque enough to see.  Jerk's voltage fade settings
        # would otherwise erase sub-newton values.
        floor = max(PRESSURE_MAP_LEVEL_EPSILON, float(self.force_alpha_floor_n))
        # Force LUT colours are made opaque below; this is the only intentional
        # small-signal transparency transition for the Force raster.
        return levels, (0.0, floor)

    def update_package_displays(self, packages: list[PressureMapPackageDisplay]) -> None:
        """Render multiple array sensor packages in their configured grid cells."""
        self.readout_label.setVisible(True)
        self._hide_force_callouts()
        self._set_view_mode("packages" if packages else "empty")
        self._clear_dynamic_items(clear_image=False)
        self._hide_mask_outline()
        self.image_item.hide()
        self.last_package_displays = list(packages)
        self.last_array_result = None
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
        half_extent = max_extent / PRESSURE_SUPPORT_SIDE_COUNT

        for index, package in enumerate(packages):
            center_x, center_y = centers[index]
            self._update_package_image(index, package, center_x, center_y)
            self._update_package_boundary(
                index,
                package,
                center_x,
                center_y,
                mid_half_extent_mm=package.pressure_result.mid_boundary_half_width_mm,
            )
            self._update_package_sensor_markers(index, package, center_x, center_y)
            self._update_package_peak_markers(index, package, center_x, center_y)
            self._update_package_shear_arrow(index, package, center_x, center_y)

        self._hide_unused_package_items(len(packages))
        range_signature = self._package_view_range_signature(
            packages,
            centers,
            half_extent,
        )
        if range_signature != self._view_range_signature:
            self._set_package_ranges(
                packages,
                centers,
                half_extent,
                range_signature,
            )
        self._update_package_readout(packages)
        self.plot_widget.getPlotItem().getViewBox().update()

    def update_array_display(
        self,
        array_result: PressureMapArrayResult,
        packages: list[PressureMapPackageDisplay],
    ) -> None:
        """Render one array-level pressure image with per-package overlays."""
        self.readout_label.setVisible(True)
        self._hide_force_callouts()
        self._set_view_mode("array" if packages else "empty")
        self._clear_dynamic_items(clear_image=False)
        self.image_item.show()
        self.last_array_result = array_result
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
        self._update_array_image(array_result, packages)
        self._update_mask_outline(array_result)

        for image_item in self.package_image_items:
            image_item.hide()

        for index, package in enumerate(packages):
            center_x, center_y = self._array_package_center(array_result, package)
            self._update_package_boundary(
                index,
                package,
                center_x,
                center_y,
                support_bounds_mm=array_result.candidate_support_bounds_mm.get(
                    package.sensor_id,
                    package.pressure_result.support_bounds_mm,
                ),
                mid_half_extent_mm=array_result.mid_boundary_half_width_mm,
            )
            self._update_package_sensor_markers(index, package, center_x, center_y)
            self._update_package_peak_markers(index, package, center_x, center_y)
            self._update_package_shear_arrow(index, package, center_x, center_y)

        self._hide_unused_package_items(len(packages))
        range_signature = self._array_view_range_signature(array_result)
        if range_signature != self._view_range_signature:
            self._set_array_ranges(array_result, range_signature)
        self._update_package_readout(packages, preserve_saturation=True)
        self.plot_widget.getPlotItem().getViewBox().update()

    def _clear_dynamic_items(self, *, clear_image: bool = True) -> None:
        if clear_image:
            empty_grid = np.zeros((PRESSURE_MAP_COLORMAP_POINTS, PRESSURE_MAP_COLORMAP_POINTS, 4), dtype=np.uint8)
            self.image_item.setImage(
                empty_grid,
                autoLevels=False,
            )
            self._image_cache = None
        self.sensor_marker_item.setData([])
        self.peak_marker_item.setData([])
        self._hide_arrow()
        self._hide_mask_outline()
        if self.circle_item is not None:
            self.circle_item.setVisible(False)
        if self.outer_boundary_item is not None:
            self.outer_boundary_item.setVisible(False)
        if self.mid_boundary_item is not None:
            self.mid_boundary_item.setVisible(False)

    def _clear_package_items(self) -> None:
        self._hide_unused_package_items(0)

    def _update_image(
        self,
        normal_force_result: NormalForceResult,
        pressure_result: PressureMapResult,
    ) -> None:
        levels = self._pressure_levels(normal_force_result, pressure_result.pressure_grid)
        # Apply mirror only for rendering; the retained pressure grid remains signed.
        grid = self._display_grid(pressure_result.pressure_grid)
        if self.mirror:
            grid = np.fliplr(grid)
        image_rect = image_rect_from_centers(
            pressure_result.x_coordinates_mm,
            pressure_result.y_coordinates_mm,
            mirror_x=self.mirror,
        )
        rect = _rect_tuple(image_rect)
        self._image_cache = self._update_cached_image_item(
            self.image_item,
            self._image_cache,
            grid,
            levels,
            rect,
            cache_key=self._image_cache_key(pressure_result.frame_id),
        )
        self.saturated_pixel_percentage = self._saturated_pixel_percentage(
            pressure_result.pressure_grid
        )
        self.debug_backend_maximum = float(np.max(np.abs(pressure_result.pressure_grid)))
        self.debug_saturation_mask = np.abs(pressure_result.pressure_grid) >= self.max_intensity
        range_signature = self._single_view_range_signature(pressure_result, image_rect)
        if range_signature != self._view_range_signature:
            self._set_single_ranges(image_rect, range_signature)

    def _update_array_image(
        self,
        array_result: PressureMapArrayResult,
        packages: list[PressureMapPackageDisplay],
    ) -> None:
        level_source = packages[0].normal_force_result
        grid = self._array_display_grid(array_result)
        visibility_mask, mask_cache_key = self._array_visibility_mask(array_result)
        if self.mirror:
            grid = np.fliplr(grid)
            if visibility_mask is not None:
                visibility_mask = np.fliplr(visibility_mask)
        levels = self._pressure_levels(level_source, grid)
        rect = _rect_tuple(image_rect_from_centers(
            array_result.x_coordinates_mm,
            array_result.y_coordinates_mm,
            mirror_x=self.mirror,
        ))
        self._image_cache = self._update_cached_image_item(
            self.image_item,
            self._image_cache,
            grid,
            levels,
            rect,
            cache_key=(*self._image_cache_key(array_result.frame_id), mask_cache_key),
            visibility_mask=visibility_mask,
        )
        self.saturated_pixel_percentage = self._saturated_pixel_percentage(
            grid
        )
        self.debug_backend_maximum = float(np.max(np.abs(grid)))
        self.debug_saturation_mask = np.abs(grid) >= self.max_intensity

    def _update_cached_image_item(
        self,
        image_item: pg.ImageItem,
        cache: _PressureMapImageCache | None,
        pressure_grid: np.ndarray,
        levels: tuple[float, float],
        rect: tuple[float, float, float, float],
        *,
        cache_key: tuple[object, ...],
        visibility_mask: np.ndarray | None = None,
        fade_levels: tuple[float, float] | None = None,
        force_mode: bool = False,
    ) -> _PressureMapImageCache:
        if cache is None or cache.cache_key != cache_key or cache.levels != levels:
            rgba = self._rgba_image(
                pressure_grid,
                levels,
                visibility_mask=visibility_mask,
                fade_levels=fade_levels,
                force_mode=force_mode,
            )
            image_item.setImage(
                np.transpose(rgba, (1, 0, 2)),
                autoLevels=False,
            )
        if cache is None or cache.rect != rect:
            image_item.setRect(QRectF(*rect))
        return _PressureMapImageCache(
            cache_key=cache_key,
            pressure_grid=pressure_grid,
            levels=levels,
            rect=rect,
        )

    def _image_cache_key(self, frame_id: int) -> tuple[object, ...]:
        return (
            frame_id, self.display_mode, self.mirror, self.color_scale,
            self.max_intensity, self.display_floor_low, self.display_floor_high,
        )

    def _rgba_image(
        self,
        pressure_grid: np.ndarray,
        levels: tuple[float, float],
        *,
        visibility_mask: np.ndarray | None = None,
        fade_levels: tuple[float, float] | None = None,
        force_mode: bool = False,
    ) -> np.ndarray:
        """Map the display grid to RGBA with a magnitude-based smooth alpha."""

        lower, upper = levels
        span = max(PRESSURE_MAP_LEVEL_EPSILON, upper - lower)
        display_grid = np.asarray(pressure_grid, dtype=np.float64)
        if force_mode:
            display_grid = np.abs(display_grid)
        normalized = np.clip((display_grid - lower) / span, 0.0, 1.0)
        indices = np.rint(normalized * (PRESSURE_MAP_COLORMAP_POINTS - 1)).astype(np.intp)
        lookup_table = np.asarray(self._color_lookup_table(force_mode=force_mode), dtype=np.uint8)
        colors = lookup_table[indices]
        if colors.shape[-1] == 3:
            rgba = np.empty((*colors.shape[:2], 4), dtype=np.uint8)
            rgba[..., :3] = colors
            rgba[..., 3] = 255
        else:
            rgba = colors.copy()
        magnitude = np.abs(display_grid)
        fade_low, fade_high = fade_levels or (self.display_floor_low, self.display_floor_high)
        fade_low = max(0.0, float(fade_low))
        fade_high = float(fade_high)
        if fade_high <= fade_low + PRESSURE_MAP_LEVEL_EPSILON:
            fade_high = fade_low + max(PRESSURE_MAP_LEVEL_EPSILON, abs(upper) * 0.02)
        alpha_t = np.clip((magnitude - fade_low) / (fade_high - fade_low), 0.0, 1.0)
        alpha = 3.0 * alpha_t ** 2 - 2.0 * alpha_t ** 3
        rgba[..., 3] = np.rint(rgba[..., 3].astype(np.float64) * alpha).astype(np.uint8)
        if visibility_mask is not None:
            visible = np.asarray(visibility_mask, dtype=bool)
            if visible.shape != pressure_grid.shape:
                raise ValueError("pressure-map visibility mask shape must match the pressure grid")
            rgba[..., 3] = np.where(visible, rgba[..., 3], 0).astype(np.uint8)
        return rgba

    def _array_visibility_mask(
        self,
        array_result: PressureMapArrayResult,
    ) -> tuple[np.ndarray | None, tuple[object, ...]]:
        """Return the cached world-space mask for the current array raster."""

        if not self.mask_enabled or not self.mask_points_mm:
            return None, ("mask-disabled",)

        x_grid = np.asarray(array_result.x_grid_mm, dtype=np.float64)
        y_grid = np.asarray(array_result.y_grid_mm, dtype=np.float64)
        if x_grid.shape != y_grid.shape:
            raise ValueError("array pressure-map coordinate grids must have matching shapes")
        if x_grid.shape != array_result.pressure_grid.shape:
            raise ValueError("array pressure-map coordinate grid must match pressure-grid shape")

        cache_key = (
            "mask",
            self.mask_points_mm,
            x_grid.shape,
            float(np.nanmin(x_grid)),
            float(np.nanmax(x_grid)),
            float(np.nanmin(y_grid)),
            float(np.nanmax(y_grid)),
            float(array_result.cell_size_x_mm),
            float(array_result.cell_size_y_mm),
            float(array_result.actual_pixels_per_mm),
        )
        if self._mask_grid_cache is not None and self._mask_grid_cache[0] == cache_key:
            return self._mask_grid_cache[1], cache_key

        visibility_mask = mask_inside_grid(self.mask_points_mm, x_grid, y_grid)
        self._mask_grid_cache = (cache_key, visibility_mask)
        return visibility_mask, cache_key

    def _style_mask_outline(self) -> None:
        pen = QPen(QColor(self.mask_color))
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setWidthF(float(PRESSURE_MASK_OUTLINE_WIDTH_PX))
        pen.setCosmetic(True)
        self.mask_outline_item.setPen(pen)
        self.mask_outline_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def _update_mask_outline(self, array_result: PressureMapArrayResult) -> None:
        """Update the one reusable polygon overlay for the active array view."""

        _ = array_result  # The mask is already expressed in array world coordinates.
        if not self.mask_enabled or not self.mask_points_mm or self._view_mode not in ("array", "force-array"):
            self._hide_mask_outline()
            return
        self._style_mask_outline()
        self.mask_outline_item.setPolygon(QPolygonF([
            QPointF(self._mirror_x(x_coord), y_coord)
            for x_coord, y_coord in self.mask_points_mm
        ]))
        self.mask_outline_item.setVisible(True)

    def _hide_mask_outline(self) -> None:
        self.mask_outline_item.setVisible(False)

    def _saturated_pixel_percentage(
        self, pressure_grid: np.ndarray, max_intensity: float | None = None,
    ) -> float:
        threshold = self.max_intensity if max_intensity is None else float(max_intensity)
        if threshold <= PRESSURE_MAP_LEVEL_EPSILON:
            return 0.0
        values = np.asarray(pressure_grid, dtype=np.float64)
        finite = np.isfinite(values)
        if not np.any(finite):
            return 0.0
        return 100.0 * float(np.mean(np.abs(values[finite]) >= threshold))

    def _pressure_levels(
        self,
        normal_force_result: NormalForceResult,
        pressure_grid: np.ndarray,
    ) -> tuple[float, float]:
        if self.max_intensity <= PRESSURE_MAP_LEVEL_EPSILON:
            return self._normalized_pressure_levels(normal_force_result, pressure_grid)

        level_max = max(float(self.max_intensity), PRESSURE_MAP_LEVEL_EPSILON)
        if self.display_mode == PRESSURE_DISPLAY_MODE_SIGNED:
            return (-level_max, level_max)
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
        # Auto scale is retained only for the legacy max-intensity=0 setting;
        # production fixed scale never changes with active sensor count.
        return (PRESSURE_MAP_ZERO_LEVEL_MIN, magnitude_max)

    def _mirror_x(self, x: float) -> float:
        """Apply horizontal mirror transformation if enabled."""
        return -x if self.mirror else x

    def _color_lookup_table(self, *, force_mode: bool = False) -> np.ndarray:
        if self.display_mode == PRESSURE_DISPLAY_MODE_SIGNED and not force_mode:
            lookup = pg.ColorMap(
                # Keep zero transparent/black against the pressure-map canvas.
                # The old white midpoint made an empty Signed map look like its
                # background had changed even though the PlotWidget was black.
                [0.0, 0.5, 1.0], ["#2166AC", "#000000", "#B2182B"]
            ).getLookupTable(nPts=PRESSURE_MAP_COLORMAP_POINTS)
            return self._force_opaque_lookup(lookup) if force_mode else lookup
        color_map = self._color_maps.get(self.color_scale)
        if color_map is None:
            color_map = pg.ColorMap(
                [0.0, 0.18, 0.42, 0.72, 1.0],
                self.COLOR_MAPS[self.color_scale],
            )
            self._color_maps[self.color_scale] = color_map
        lookup = color_map.getLookupTable(nPts=PRESSURE_MAP_COLORMAP_POINTS)
        return self._force_opaque_lookup(lookup) if force_mode else lookup

    @staticmethod
    def _force_opaque_lookup(lookup_table: np.ndarray) -> np.ndarray:
        """Ensure the Force raster has one, deliberate alpha mechanism only."""
        result = np.asarray(lookup_table, dtype=np.uint8).copy()
        if result.shape[1] == 4:
            result[:, 3] = 255
        return result

    def _grayscale_lookup_table(self) -> np.ndarray:
        """Return the legacy grayscale LUT for compatibility with callers/tests."""
        color_map = pg.ColorMap(
            [PRESSURE_MAP_ZERO_LEVEL_MIN, PRESSURE_MAP_ZERO_LEVEL_MAX],
            ["#000000", "#FFFFFF"],
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
        self._update_boundary_geometry(
            visual_radius_mm=float(pressure_result.visual_boundary_radius_mm),
            outer_half_width_mm=float(pressure_result.outer_boundary_half_width_mm),
            mid_half_width_mm=float(pressure_result.mid_boundary_half_width_mm),
        )

    def _force_image_cache_key(self, frame_id: int) -> tuple[object, ...]:
        return (
            frame_id, self.display_mode, self.mirror, self.color_scale,
            self.force_max_intensity_n, self.force_alpha_floor_n,
        )

    def _update_boundary_geometry(
        self,
        *,
        visual_radius_mm: float,
        outer_half_width_mm: float,
        mid_half_width_mm: float,
    ) -> None:
        """Draw shared package boundaries from either result representation."""
        radius = float(visual_radius_mm)
        self.circle_radius_mm = float(outer_half_width_mm)
        if self.circle_item is None:
            self.circle_item = self._new_near_boundary_item()
            self.plot_widget.addItem(self.circle_item)
        self._style_boundary_item(
            self.circle_item,
            radius,
            color=PRESSURE_MAP_OVERLAY_COLOR,
            dash_pattern=None,
        )
        self.circle_item.setVisible(bool(self.show_near_outer_boundary))

        self._ensure_single_square_items()
        self._style_boundary_item(
            self.outer_boundary_item,
            float(outer_half_width_mm),
            color=PRESSURE_MAP_OVERLAY_COLOR,
            dash_pattern=(8.0, 4.0),
        )
        self.outer_boundary_item.setVisible(bool(self.show_outer_boundary))
        self._style_boundary_item(
            self.mid_boundary_item,
            float(mid_half_width_mm),
            color=PRESSURE_MAP_OVERLAY_COLOR,
            dash_pattern=(3.0, 3.0),
        )
        self.mid_boundary_item.setVisible(bool(self.show_mid_boundary))

    def _new_near_boundary_item(self) -> QGraphicsEllipseItem:
        """Create the near-outer circle (the old item remains an API alias)."""
        return QGraphicsEllipseItem()

    def _ensure_single_square_items(self) -> None:
        if self.outer_boundary_item is None:
            self.outer_boundary_item = QGraphicsRectItem()
            self.outer_boundary_item.setZValue(PRESSURE_MAP_CIRCLE_Z)
            self.plot_widget.addItem(self.outer_boundary_item)
        if self.mid_boundary_item is None:
            self.mid_boundary_item = QGraphicsRectItem()
            self.mid_boundary_item.setZValue(PRESSURE_MAP_CIRCLE_Z)
            self.plot_widget.addItem(self.mid_boundary_item)

    def _style_boundary_item(
        self,
        item: QGraphicsEllipseItem | QGraphicsRectItem | None,
        half_extent: float,
        *,
        color: str,
        dash_pattern: tuple[float, float] | None,
    ) -> None:
        if item is None:
            return
        pen = QPen(QColor(color))
        pen.setWidthF(SHEAR_LAYOUT_CIRCLE_LINE_WIDTH_PX)
        if dash_pattern is None:
            pen.setStyle(Qt.PenStyle.DotLine)
        else:
            pen.setDashPattern(list(dash_pattern))
        pen.setCosmetic(SHEAR_LAYOUT_PENS_ARE_COSMETIC)
        item.setPen(pen)
        item.setZValue(PRESSURE_MAP_CIRCLE_Z)
        item.setRect(-half_extent, -half_extent, half_extent * 2.0, half_extent * 2.0)

    def _update_sensor_markers(self, pressure_result: PressureMapResult) -> None:
        if not self.show_sensor_markers:
            self.sensor_marker_item.setData([])
            return
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
            f"{shear_text}{self._saturation_indicator()}"
        )

    def _saturation_indicator(self) -> str:
        if self.saturated_pixel_percentage <= 0.0:
            return ""
        return f" | SAT {self.saturated_pixel_percentage:.1f}%"

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
            image_item.setLookupTable(self._color_lookup_table())
            self.plot_widget.addItem(image_item)
            self.package_image_items.append(image_item)
            self._package_image_caches.append(None)

            circle_item = self._new_near_boundary_item()
            circle_item.setZValue(PRESSURE_MAP_CIRCLE_Z)
            self.plot_widget.addItem(circle_item)
            self.package_circle_items.append(circle_item)

            outer_boundary_item = QGraphicsRectItem()
            outer_boundary_item.setZValue(PRESSURE_MAP_CIRCLE_Z)
            self.plot_widget.addItem(outer_boundary_item)
            self.package_outer_boundary_items.append(outer_boundary_item)

            mid_boundary_item = QGraphicsRectItem()
            mid_boundary_item.setZValue(PRESSURE_MAP_CIRCLE_Z)
            self.plot_widget.addItem(mid_boundary_item)
            self.package_mid_boundary_items.append(mid_boundary_item)

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

    def _hide_unused_package_items(self, used_count: int) -> None:
        for index in range(used_count, len(self.package_image_items)):
            self.package_image_items[index].hide()
            self._package_image_caches[index] = None
            self.package_circle_items[index].hide()
            self.package_outer_boundary_items[index].hide()
            self.package_mid_boundary_items[index].hide()
            self.package_sensor_marker_items[index].setData([])
            self.package_peak_marker_items[index].setData([])
            self._hide_package_arrow(index)

    def _package_centers(self, packages: list[PressureMapPackageDisplay]) -> list[tuple[float, float]]:
        spacing = float(packages[0].pressure_result.package_center_spacing_mm)
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
        grid = self._display_grid(package.pressure_result.pressure_grid)
        if self.mirror:
            grid = np.fliplr(grid)
        levels = self._pressure_levels(package.normal_force_result, grid)
        rect = _rect_tuple(image_rect_from_centers(
            package.pressure_result.x_coordinates_mm,
            package.pressure_result.y_coordinates_mm,
            mirror_x=self.mirror,
            offset_x=center_x,
            offset_y=center_y,
        ))
        self._package_image_caches[index] = self._update_cached_image_item(
            image_item,
            self._package_image_caches[index],
            grid,
            levels,
            rect,
            cache_key=self._image_cache_key(package.pressure_result.frame_id),
        )

    def _update_package_boundary(
        self,
        index: int,
        package: PressureMapPackageDisplay,
        center_x: float,
        center_y: float,
        *,
        support_bounds_mm: tuple[float, float, float, float] | None = None,
        mid_half_extent_mm: float | None = None,
    ) -> None:
        _ = support_bounds_mm
        self._update_package_boundary_geometry(
            index,
            geometry=package.pressure_result,
            color=package.color,
            center_x=center_x,
            center_y=center_y,
            mid_half_extent_mm=mid_half_extent_mm,
        )

    def _update_package_boundary_geometry(
        self,
        index: int,
        *,
        geometry,
        color: str,
        center_x: float,
        center_y: float,
        mid_half_extent_mm: float | None,
    ) -> None:
        """Draw the shared Jerk/Force package boundary primitives."""
        radius_value = getattr(geometry, "visual_boundary_radius_mm", None)
        if radius_value is None:
            radius_value = geometry.near_outer_circle_radius_mm
        radius = float(radius_value)
        near_item = self.package_circle_items[index]
        if not isinstance(near_item, QGraphicsEllipseItem):
            self.plot_widget.removeItem(near_item)
            near_item = self._new_near_boundary_item()
            near_item.setZValue(PRESSURE_MAP_CIRCLE_Z)
            self.plot_widget.addItem(near_item)
            self.package_circle_items[index] = near_item
        self._style_boundary_item(
            near_item,
            radius,
            color=color,
            dash_pattern=None,
        )
        near_item.setRect(center_x - radius, center_y - radius, radius * 2.0, radius * 2.0)
        near_item.setVisible(bool(self.show_near_outer_boundary))

        outer_item = self.package_outer_boundary_items[index]
        outer_radius = float(geometry.outer_boundary_half_width_mm)
        self._style_boundary_item(
            outer_item,
            outer_radius,
            color=color,
            dash_pattern=(8.0, 4.0),
        )
        outer_item.setRect(
            center_x - outer_radius,
            center_y - outer_radius,
            outer_radius * 2.0,
            outer_radius * 2.0,
        )
        outer_item.setVisible(bool(self.show_outer_boundary))

        mid_item = self.package_mid_boundary_items[index]
        if mid_half_extent_mm is None:
            mid_item.setVisible(False)
        else:
            self._style_boundary_item(
                mid_item,
                float(mid_half_extent_mm),
                color=color,
                dash_pattern=(3.0, 3.0),
            )
            mid_item.setRect(
                center_x - float(mid_half_extent_mm),
                center_y - float(mid_half_extent_mm),
                float(mid_half_extent_mm) * 2.0,
                float(mid_half_extent_mm) * 2.0,
            )
            mid_item.setVisible(bool(self.show_mid_boundary))

    def _update_package_sensor_markers(
        self,
        index: int,
        package: PressureMapPackageDisplay,
        center_x: float,
        center_y: float,
    ) -> None:
        self._update_package_sensor_markers_geometry(
            index,
            sensor_id=package.sensor_id,
            sensor_positions=self._sensor_positions_from_result(package.pressure_result),
            color=package.color,
            center_x=center_x,
            center_y=center_y,
        )

    def _update_package_sensor_markers_geometry(
        self,
        index: int,
        *,
        sensor_id: str,
        sensor_positions: dict[str, tuple[float, float]],
        color: str,
        center_x: float,
        center_y: float,
    ) -> None:
        """Draw the shared Jerk/Force package sensor-marker primitive."""
        if not self.show_sensor_markers:
            self.package_sensor_marker_items[index].setData([])
            return
        spots = [
            {
                "pos": (center_x + self._mirror_x(x_coord), center_y + y_coord),
                "data": (sensor_id, position),
                "symbol": PRESSURE_MAP_SENSOR_MARKER_SYMBOL,
                "size": PRESSURE_MAP_SENSOR_MARKER_SIZE_PX,
                "pen": pg.mkPen(
                    color,
                    width=PRESSURE_MAP_SENSOR_MARKER_PEN_WIDTH_PX,
                ),
                "brush": pg.mkBrush(color),
            }
            for position, (x_coord, y_coord) in sensor_positions.items()
        ]
        self.package_sensor_marker_items[index].setData(spots)

    def _array_package_center(
        self,
        array_result: PressureMapArrayResult,
        package: PressureMapPackageDisplay,
    ) -> tuple[float, float]:
        center_x, center_y = array_result.package_centers.get(package.sensor_id, (0.0, 0.0))
        return (self._mirror_x(float(center_x)), float(center_y))

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
        self.circle_radius_mm = float(package.pressure_result.outer_boundary_half_width_mm)
        geometry = self.calculate_arrow_geometry(package.shear_result)
        if not geometry.visible:
            self._hide_package_arrow(index)
            return
        self._apply_arrow_to_items(index, geometry, center_x, center_y, self.arrow_color)

    def _update_force_package_shear_arrow(
        self,
        index: int,
        package,
        center_x: float,
        center_y: float,
    ) -> None:
        """Mirror ``_update_package_shear_arrow`` for a Force array package."""
        shear_result = getattr(package, "shear_result", None)
        if shear_result is None:
            self._hide_package_arrow(index)
            return
        self.circle_radius_mm = float(package.geometry.outer_boundary_half_width_mm)
        geometry = self.calculate_arrow_geometry(shear_result)
        if not geometry.visible:
            self._hide_package_arrow(index)
            return
        self._apply_arrow_to_items(index, geometry, center_x, center_y, self.arrow_color)

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

    def _set_view_mode(self, mode: str) -> None:
        """Invalidate the cached range when the rendering structure changes."""

        if self._view_mode == mode:
            return
        self._view_mode = mode
        self._invalidate_view_range()

    def _invalidate_view_range(self) -> None:
        self._view_range_signature = None

    @staticmethod
    def _pressure_geometry_signature(result: PressureMapResult) -> tuple[object, ...]:
        """Return only geometry that can affect a pressure-map viewport."""

        return (
            float(result.total_extent_mm),
            tuple(float(value) for value in result.support_bounds_mm),
            float(result.sensor_spacing_mm),
            float(result.package_center_spacing_mm),
            float(result.outer_boundary_reach_mm),
            float(result.peak_position_outer_offset_mm),
            float(result.pixels_per_mm),
            int(result.x_coordinates_mm.size),
            int(result.y_coordinates_mm.size),
        )

    def _single_view_range_signature(
        self,
        pressure_result: PressureMapResult,
        image_rect: QRectF,
    ) -> tuple[object, ...]:
        return (
            "single",
            bool(self.mirror),
            _rect_tuple(image_rect),
            self._pressure_geometry_signature(pressure_result),
        )

    def _set_single_ranges(
        self,
        image_rect: QRectF,
        signature: tuple[object, ...],
    ) -> None:
        self.plot_widget.setXRange(
            image_rect.left(),
            image_rect.right(),
            padding=SHEAR_ZERO_VALUE,
        )
        self.plot_widget.setYRange(
            image_rect.top(),
            image_rect.bottom(),
            padding=SHEAR_ZERO_VALUE,
        )
        self._view_range_signature = signature

    def _package_view_range_signature(
        self,
        packages: list[PressureMapPackageDisplay],
        centers: list[tuple[float, float]],
        fallback_half_extent: float,
    ) -> tuple[object, ...]:
        package_geometry = tuple(sorted(
            (
                str(package.sensor_id),
                package.grid_position,
                float(package_center_x),
                float(package_center_y),
                self._pressure_geometry_signature(package.pressure_result),
            )
            for package, (package_center_x, package_center_y) in zip(packages, centers)
        ))
        return (
            "packages",
            bool(self.mirror),
            float(fallback_half_extent),
            package_geometry,
        )

    def _set_package_ranges(
        self,
        packages: list[PressureMapPackageDisplay],
        centers: list[tuple[float, float]],
        fallback_half_extent: float,
        signature: tuple[object, ...],
    ) -> None:
        if not centers or not packages:
            return

        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")
        max_radius = fallback_half_extent
        for package, (center_x, center_y) in zip(packages, centers):
            radius = float(package.pressure_result.total_extent_mm) / PRESSURE_SUPPORT_SIDE_COUNT
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
        self._view_range_signature = signature

    def _array_view_range_signature(
        self,
        array_result: PressureMapArrayResult,
    ) -> tuple[object, ...]:
        return (
            "array",
            bool(self.mirror),
            int(array_result.x_coordinates_mm.size),
            int(array_result.y_coordinates_mm.size),
            float(array_result.x_coordinates_mm[0]),
            float(array_result.x_coordinates_mm[-1]),
            float(array_result.y_coordinates_mm[0]),
            float(array_result.y_coordinates_mm[-1]),
            float(array_result.cell_size_x_mm),
            float(array_result.cell_size_y_mm),
            float(array_result.package_center_spacing_mm),
            float(array_result.outer_boundary_reach_mm),
            float(array_result.actual_pixels_per_mm),
            float(array_result.mid_boundary_half_width_mm),
            float(array_result.outer_boundary_half_width_mm),
            tuple(sorted(
                (
                    str(sensor_id),
                    float(center[0]),
                    float(center[1]),
                )
                for sensor_id, center in array_result.package_centers.items()
            )),
            tuple(sorted(array_result.structural_pairs)),
            tuple(sorted(
                (
                    str(sensor_id),
                    tuple(float(value) for value in bounds),
                )
                for sensor_id, bounds in array_result.candidate_support_bounds_mm.items()
            )),
        )

    def _set_array_ranges(
        self,
        array_result: PressureMapArrayResult,
        signature: tuple[object, ...],
    ) -> None:
        x_min = float(array_result.x_coordinates_mm[0])
        x_max = float(array_result.x_coordinates_mm[-1])
        y_min = float(array_result.y_coordinates_mm[0])
        y_max = float(array_result.y_coordinates_mm[-1])
        if self.mirror:
            x_min, x_max = -x_max, -x_min
        span_x = x_max - x_min
        span_y = y_max - y_min
        square_span = max(span_x, span_y)
        center_x = (x_min + x_max) / 2.0
        center_y = (y_min + y_max) / 2.0
        half_span = square_span / 2.0
        padding = max(SHEAR_ZERO_VALUE, half_span * PRESSURE_MAP_PACKAGE_VIEW_PADDING_FRACTION)
        self.plot_widget.setXRange(center_x - half_span - padding, center_x + half_span + padding, padding=SHEAR_ZERO_VALUE)
        self.plot_widget.setYRange(center_y - half_span - padding, center_y + half_span + padding, padding=SHEAR_ZERO_VALUE)
        self._view_range_signature = signature

    def _update_package_readout(
        self, packages: list[PressureMapPackageDisplay], *, preserve_saturation: bool = False
    ) -> None:
        total_force = sum(float(package.normal_force_result.total_force) for package in packages)
        package_labels = ", ".join(package.sensor_id for package in packages)
        finite_grids = [
            np.asarray(package.pressure_result.pressure_grid, dtype=np.float64).ravel()
            for package in packages
        ]
        if not preserve_saturation:
            self.saturated_pixel_percentage = self._saturated_pixel_percentage(
                np.concatenate(finite_grids) if finite_grids else np.asarray((), dtype=np.float64)
            )
        self.readout_label.setText(
            f"Array packages: {package_labels} | "
            f"Total normal: {total_force:.{SHEAR_READOUT_MAGNITUDE_DECIMALS}f}"
            f"{self._saturation_indicator()}"
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

