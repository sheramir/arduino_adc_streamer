"""Exactly-once, package-state PZT force reconstruction for Pressure Map."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import count
from typing import Hashable

import numpy as np

from constants.pzt_force import PZT_FORCE_DEFAULT_SETTINGS, PZT_FORCE_PIC_COULOMB_TO_COULOMB
from constants.shear import SHEAR_SENSOR_POSITIONS
from data_processing.normal_force_calculator import NormalForceCalculator
from data_processing.pressure_map_array_generator import PressureMapArrayForcePackage, PressureMapArrayGenerator
from data_processing.pressure_map_geometry import PressureMapGeometry
from data_processing.pzt_force_calculation import PztForceChannelIntegrator, pzt_capacitance_to_farads
from data_processing.shear_detector import ShearDetector


_FORCE_FRAME_IDS = count(1)

# Layer bookkeeping tolerance in newtons.  Far below the display noise floor
# (~2.5 mN with default settings) so it only absorbs float round-off.
_FORCE_LAYER_EPSILON_N = 1e-12


@dataclass(slots=True)
class ForceLayer:
    """One loading increment recorded with the exact shape that painted it."""

    shape: np.ndarray            # normalized |jerk| grid, peak == 1.0
    remaining_force_n: float     # magnitude, always >= 0


@dataclass(frozen=True, slots=True)
class ForceMapPackageResult:
    """Render data for one authoritative accumulated package state."""

    sensor_id: str
    force_grid_n: np.ndarray
    normal_force_n: float
    shear_x_n: float
    shear_y_n: float
    geometry: PressureMapGeometry
    x_coordinates_mm: np.ndarray
    y_coordinates_mm: np.ndarray
    sensor_positions: dict[str, tuple[float, float]]
    grid_position: tuple[int, int] | None
    frame_id: int

    @property
    def shear_force_n(self) -> float:
        return float(np.hypot(self.shear_x_n, self.shear_y_n))


@dataclass(frozen=True, slots=True)
class ForceMapArrayResult:
    """Signed and magnitude Force rasters for one composed array frame."""

    force_grid_n: np.ndarray
    magnitude_force_grid_n: np.ndarray
    x_coordinates_mm: np.ndarray
    y_coordinates_mm: np.ndarray
    package_centers: dict[str, tuple[float, float]]
    frame_id: int


@dataclass(slots=True)
class _ForcePackageState:
    channel_states: dict[str, PztForceChannelIntegrator]
    accumulated_force_grid_n: np.ndarray
    force_layers: list[ForceLayer] = field(default_factory=list)
    normal_force_n: float = 0.0
    shear_x_n: float = 0.0
    shear_y_n: float = 0.0
    applied_load_n: float = 0.0
    applied_polarity: int = 0
    quiet_sample_count: int = 0
    has_force_activity: bool = False


class PressureForceDisplayEngine:
    """Own local package force state; the array raster is render-time only."""

    def __init__(
        self, *, geometry: PressureMapGeometry, settings: Mapping[str, object] | None = None,
        normal_force_calculator: NormalForceCalculator | None = None,
        shear_detector: ShearDetector | None = None,
        pressure_map_array_generator: PressureMapArrayGenerator | None = None,
    ) -> None:
        self.geometry = geometry
        self.settings = {**PZT_FORCE_DEFAULT_SETTINGS, **dict(settings or {})}
        self.normal_force_calculator = normal_force_calculator or NormalForceCalculator(geometry.sensor_spacing_mm)
        self.shear_detector = shear_detector or ShearDetector()
        self.pressure_map_array_generator = pressure_map_array_generator or PressureMapArrayGenerator(geometry=geometry)
        self._x_coordinates_mm, self._y_coordinates_mm = self._local_grid_coordinates()
        self._sensor_positions = self._local_sensor_positions()
        self._packages: dict[str, _ForcePackageState] = {}
        self._configured_grid_positions: dict[str, tuple[int, int] | None] = {}
        self._last_sample_id: Hashable | None = None

    def configure_layout(self, grid_positions: Mapping[str, tuple[int, int] | None]) -> None:
        """Configure static package geometry and create visible zero states."""
        normalized = {
            str(sensor_id).strip().upper(): None if position is None else tuple(position)
            for sensor_id, position in grid_positions.items() if str(sensor_id).strip()
        }
        if normalized == self._configured_grid_positions:
            return
        self._configured_grid_positions = normalized
        self._packages = {sensor_id: self._new_package_state() for sensor_id in normalized}
        self._last_sample_id = None

    def reset(self) -> None:
        """Atomically clear values while retaining configured zero packages."""
        self._packages = {sensor_id: self._new_package_state() for sensor_id in self._configured_grid_positions}
        self._last_sample_id = None

    def reset_package(self, sensor_id: str) -> None:
        sensor_id = str(sensor_id).strip().upper()
        self._packages[sensor_id] = self._new_package_state()

    def process_sample(
        self, sample_id: Hashable, package_centered_voltage_v: Mapping[str, Mapping[str, float]],
        timestamps_s: Mapping[str, object] | float, *,
        grid_positions: Mapping[str, tuple[int, int] | None] | None = None,
        observations_per_sweep: int | None = None,
        leak_dt_s: Mapping[str, object] | float | None = None,
        pre_sample_decay_dt_s: Mapping[str, object] | float | None = None,
        channel_calibration: Mapping[str, Mapping[str, float]] | None = None,
    ) -> bool:
        if grid_positions is not None:
            self.configure_layout(grid_positions)
        if self._last_sample_id is not None:
            if sample_id == self._last_sample_id:
                return False
            if observations_per_sweep is not None and self._is_tuple_observation_id(sample_id) and self._is_tuple_observation_id(self._last_sample_id):
                self._validate_next_observation_id(
                    previous=self._last_sample_id,
                    current=sample_id,
                    observations_per_sweep=int(observations_per_sweep),
                )
            try:
                if sample_id < self._last_sample_id:
                    raise ValueError("force-display sample identity moved backwards")
            except TypeError:
                pass

        for raw_id, voltages in package_centered_voltage_v.items():
            sensor_id = str(raw_id).strip().upper()
            if not all(position in voltages for position in SHEAR_SENSOR_POSITIONS):
                raise ValueError(f"force-display package {sensor_id} is missing a PZT position")
            package = self._packages.setdefault(sensor_id, self._new_package_state())
            calibration = (channel_calibration or {}).get(sensor_id, {})
            current_forces: dict[str, float] = {}
            for position in SHEAR_SENSOR_POSITIONS:
                state = package.channel_states[position]
                timestamp = self._per_channel_value(timestamps_s, sensor_id, position)
                if timestamp is None:
                    raise ValueError("force-display channel timestamp is required")
                state.process_centered_sample(
                    float(voltages[position]), float(timestamp),
                    leak_dt_s=self._per_channel_value(leak_dt_s, sensor_id, position),
                    pre_sample_decay_dt_s=self._per_channel_value(pre_sample_decay_dt_s, sensor_id, position),
                )
                current_forces[position] = state.accumulated_force_n * float(calibration.get(position, 1.0))

            # Suppress the final channel-local transition entirely.  A package
            # reset is one coherent operation, not five nonlinear corrections.
            if any(state.active for state in package.channel_states.values()):
                package.quiet_sample_count = 0
                package.has_force_activity = True
            else:
                package.quiet_sample_count += 1
            if self._package_event_complete(package) or self._package_quiet_reset_due(package):
                self.reset_package(sensor_id)
                continue

            # The channel integrators are the only physical integrators.
            # Package Normal/Shear are derived from their current accumulated
            # state, never accumulated a second time.
            shear = self.shear_detector.detect(current_forces)
            normal = self.normal_force_calculator.compute(shear.residual)
            package.normal_force_n = normal.total_force
            package.shear_x_n = shear.b_lr
            package.shear_y_n = shear.b_tb

        self._last_sample_id = sample_id
        return True

    def apply_jerk_shapes(self, package_displays) -> None:
        """Reconcile each package's layer stack with its current Normal load.

        ``package_displays`` are the current Jerk display results.  This method
        intentionally consumes their exact grids rather than invoking a
        ``PressureMapGenerator`` of its own.  Loading records a new layer with
        the current normalized Jerk shape; unloading removes previously stored
        layers so release cancels the raster pixel-for-pixel and never paints
        with a release shape of its own.
        """
        for package_display in package_displays:
            sensor_id = str(getattr(package_display, "sensor_id", "")).strip().upper()
            package = self._packages.get(sensor_id)
            if package is None:
                continue
            current_normal = float(package.normal_force_n)
            polarity = 0 if current_normal == 0.0 else (1 if current_normal > 0.0 else -1)

            # A sign crossing ends the old event: its layers are removed with
            # their stored shapes before the new polarity starts loading.
            if polarity and package.applied_polarity and polarity != package.applied_polarity:
                self._clear_layers(package)

            delta_load = abs(current_normal) - package.applied_load_n
            if delta_load > _FORCE_LAYER_EPSILON_N:
                shape = self._normalized_jerk_shape(package_display, package)
                if shape is None:
                    # No usable Jerk shape: the unapplied load persists as the
                    # difference from ``applied_load_n`` until one arrives.
                    continue
                top = package.force_layers[-1] if package.force_layers else None
                if top is not None and np.array_equal(top.shape, shape):
                    # Slow monotonic loading must not grow the stack by one
                    # layer per render frame.
                    top.remaining_force_n += delta_load
                else:
                    package.force_layers.append(ForceLayer(shape, delta_load))
                package.accumulated_force_grid_n += shape * delta_load
                package.applied_load_n += delta_load
            elif delta_load < -_FORCE_LAYER_EPSILON_N:
                # Unloading needs no current Jerk shape; it drains stored
                # layers LIFO so the exact loading shapes are subtracted.
                remove = -delta_load
                while remove > _FORCE_LAYER_EPSILON_N and package.force_layers:
                    layer = package.force_layers[-1]
                    take = min(layer.remaining_force_n, remove)
                    package.accumulated_force_grid_n -= layer.shape * take
                    layer.remaining_force_n -= take
                    package.applied_load_n -= take
                    remove -= take
                    if layer.remaining_force_n <= _FORCE_LAYER_EPSILON_N:
                        package.force_layers.pop()
                if not package.force_layers:
                    # Hard zero kills float residue: full unload is exact black.
                    package.accumulated_force_grid_n = np.zeros_like(package.accumulated_force_grid_n)
                    package.applied_load_n = 0.0

            if polarity:
                package.applied_polarity = polarity
            elif package.applied_load_n <= _FORCE_LAYER_EPSILON_N:
                package.applied_polarity = 0

    @staticmethod
    def _normalized_jerk_shape(package_display, package: _ForcePackageState) -> np.ndarray | None:
        """Return the current |jerk| grid normalized to peak 1, if usable."""
        pressure_result = getattr(package_display, "pressure_result", None)
        if pressure_result is None:
            return None
        jerk_grid = np.asarray(getattr(pressure_result, "pressure_grid", ()), dtype=np.float64)
        if jerk_grid.shape != package.accumulated_force_grid_n.shape:
            # A geometry rebuild resets Force history before this can
            # normally happen.  Never paint load onto a mismatched spatial
            # coordinate system.
            return None
        shape = np.abs(jerk_grid)
        peak = float(np.max(shape)) if shape.size else 0.0
        if not np.isfinite(peak) or peak <= np.finfo(np.float64).eps:
            # A zero Jerk shape must not consume physical load waiting for
            # the next nonzero spatial frame.
            return None
        return shape / peak

    @staticmethod
    def _clear_layers(package: _ForcePackageState) -> None:
        package.force_layers.clear()
        package.accumulated_force_grid_n = np.zeros_like(package.accumulated_force_grid_n)
        package.applied_load_n = 0.0

    def package_results(self) -> list[ForceMapPackageResult]:
        return [
            ForceMapPackageResult(
                sensor_id=sensor_id, force_grid_n=state.accumulated_force_grid_n.copy(),
                normal_force_n=float(state.normal_force_n), shear_x_n=float(state.shear_x_n),
                shear_y_n=float(state.shear_y_n), geometry=self.geometry,
                x_coordinates_mm=self._x_coordinates_mm, y_coordinates_mm=self._y_coordinates_mm,
                sensor_positions=dict(self._sensor_positions),
                grid_position=self._configured_grid_positions.get(sensor_id), frame_id=next(_FORCE_FRAME_IDS),
            ) for sensor_id, state in self._packages.items()
        ]

    def array_result(self) -> ForceMapArrayResult | None:
        fields = [
            PressureMapArrayForcePackage(sensor_id, position, state.accumulated_force_grid_n,
                                         self._x_coordinates_mm, self._y_coordinates_mm)
            for sensor_id, state in self._packages.items()
            if (position := self._configured_grid_positions.get(sensor_id)) is not None
        ]
        if not fields:
            return None
        grid, magnitude_grid, x_values, y_values, centers = self.pressure_map_array_generator.compose_force_grids(fields)
        return ForceMapArrayResult(
            grid, magnitude_grid, x_values, y_values, centers, next(_FORCE_FRAME_IDS)
        )

    def _new_package_state(self) -> _ForcePackageState:
        capacitance = pzt_capacitance_to_farads(float(self.settings["capacitance_value"]), str(self.settings["capacitance_unit"]))
        off_mux = self.settings.get("off_mux_rleak_ohm") if self.settings.get("off_mux_leak_enabled") else None
        states = {
            position: PztForceChannelIntegrator(
                capacitance_f=capacitance, rleak_ohm=float(self.settings["rleak_ohm"]),
                d33_c_per_n=float(self.settings["d33_pc_per_n"]) * PZT_FORCE_PIC_COULOMB_TO_COULOMB,
                noise_threshold_v=float(self.settings["noise_threshold_v"]),
                off_mux_rleak_ohm=None if off_mux in (None, "") else float(off_mux),
                reset_on_event_complete=False,
            ) for position in SHEAR_SENSOR_POSITIONS
        }
        return _ForcePackageState(
            states,
            np.zeros(
                (self._y_coordinates_mm.size, self._x_coordinates_mm.size),
                dtype=np.float64,
            ),
        )

    def _local_grid_coordinates(self) -> tuple[np.ndarray, np.ndarray]:
        """Build only static geometry coordinates; never rasterize a Force map."""
        half_intervals = int(round(
            self.geometry.outer_boundary_half_width_mm / self.geometry.aligned_cell_size_mm
        ))
        coordinates = (
            np.arange(-half_intervals, half_intervals + 1, dtype=np.float64)
            * self.geometry.aligned_cell_size_mm
        )
        return coordinates, coordinates.copy()

    def _local_sensor_positions(self) -> dict[str, tuple[float, float]]:
        spacing = float(self.geometry.sensor_spacing_mm)
        return {
            "C": (0.0, 0.0), "L": (-spacing, 0.0), "R": (spacing, 0.0),
            "T": (0.0, spacing), "B": (0.0, -spacing),
        }

    @staticmethod
    def _package_event_complete(package: _ForcePackageState) -> bool:
        states = tuple(package.channel_states.values())
        return bool(any(state.event_completed for state in states) and all(not state.active for state in states)
                    and all((not state.saw_opposite_pair) or state.event_completed for state in states))

    def _package_quiet_reset_due(self, package: _ForcePackageState) -> bool:
        """Return whether a completed package has remained synchronously quiet."""
        quiet_limit = max(1, int(self.settings.get("reset_after_quiet_samples", 10)))
        return bool(package.has_force_activity and package.quiet_sample_count >= quiet_limit)

    @staticmethod
    def _per_channel_value(value, sensor_id: str, position: str):
        if isinstance(value, Mapping):
            value = value.get(sensor_id)
        if isinstance(value, Mapping):
            return value.get(position)
        return value

    @staticmethod
    def _is_tuple_observation_id(value: Hashable) -> bool:
        return isinstance(value, tuple) and len(value) == 2 and all(isinstance(item, (int, np.integer)) for item in value)

    @staticmethod
    def _validate_next_observation_id(
        *, previous: tuple[int, int], current: tuple[int, int], observations_per_sweep: int,
    ) -> None:
        """Reject a skipped repeat/sweep before it can bridge RC state."""
        if observations_per_sweep < 1:
            raise ValueError("force-display observations_per_sweep must be positive")
        previous_sweep, previous_repeat = int(previous[0]), int(previous[1])
        expected = (
            (previous_sweep, previous_repeat + 1)
            if previous_repeat + 1 < observations_per_sweep
            else (previous_sweep + 1, 0)
        )
        if current != expected:
            raise ValueError(
                "force-display observation discontinuity; resetting physical state"
            )
