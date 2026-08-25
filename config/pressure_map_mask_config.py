"""Bundled and user-imported libraries for pressure-map display masks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from data_processing.pressure_map_mask import PressureMapMaskGeometry


MASK_LIBRARY_VERSION = 1
MASK_LIBRARY_FILENAME = "mask_library.json"
MASK_LIBRARY_JSON_INDENT = 2


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_bundled_masks_path() -> Path:
    return _project_root() / "sensors_library" / "masks"


def _geometry_from_payload(payload: object) -> PressureMapMaskGeometry:
    if not isinstance(payload, dict):
        raise ValueError("mask JSON must contain an object")
    return PressureMapMaskGeometry(
        name=payload.get("name", ""),
        points_mm=payload.get("points_mm", ()),
    )


def _geometries_from_payload(payload: object) -> list[PressureMapMaskGeometry]:
    """Read either a standalone mask object or a small library payload."""

    if isinstance(payload, dict) and "name" in payload and "points_mm" in payload:
        return [_geometry_from_payload(payload)]
    if isinstance(payload, dict):
        raw_masks = payload.get("configurations", payload.get("masks", []))
    elif isinstance(payload, list):
        raw_masks = payload
    else:
        raise ValueError("mask library must contain a list of masks")
    if not isinstance(raw_masks, list):
        raise ValueError("mask library masks must be a list")
    return [_geometry_from_payload(raw_mask) for raw_mask in raw_masks]


class MaskConfigStore:
    """Merge the read-only bundled mask library with user-imported masks."""

    def __init__(
        self,
        file_path: Path | None = None,
        bundled_masks_path: Path | None = None,
        bundled_file_path: Path | None = None,
    ) -> None:
        if bundled_masks_path is not None and bundled_file_path is not None:
            raise ValueError("provide only one bundled mask library path")
        self.file_path = file_path or (Path.home() / ".adc_streamer" / "masks" / MASK_LIBRARY_FILENAME)
        self.bundled_masks_path = bundled_masks_path or bundled_file_path or _default_bundled_masks_path()

    def _read_file(self, path: Path, *, strict: bool) -> list[PressureMapMaskGeometry]:
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as handle:
                return _geometries_from_payload(json.load(handle))
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            if strict:
                raise ValueError(f"invalid pressure-map mask file {path}: {exc}") from exc
            return []

    def _bundled_masks(self) -> list[PressureMapMaskGeometry]:
        path = self.bundled_masks_path
        paths = sorted(path.glob("*.json"), key=lambda item: (item.name.casefold(), item.name)) if path.is_dir() else [path]
        masks: list[PressureMapMaskGeometry] = []
        names: set[str] = set()
        for mask_path in paths:
            # A bad optional bundled file must not hide other bundled masks.
            for geometry in self._read_file(mask_path, strict=False):
                if geometry.name in names:
                    continue
                names.add(geometry.name)
                masks.append(geometry)
        return masks

    def _user_masks(self) -> list[PressureMapMaskGeometry]:
        masks = self._read_file(self.file_path, strict=False)
        by_name: dict[str, PressureMapMaskGeometry] = {}
        for geometry in masks:
            # Keep the first valid value from a potentially hand-edited file.
            by_name.setdefault(geometry.name, geometry)
        return [by_name[name] for name in sorted(by_name, key=lambda value: (value.casefold(), value))]

    def load(self) -> list[PressureMapMaskGeometry]:
        """Load bundled masks first, then non-conflicting user masks.

        Invalid or missing user files are treated as an empty user library so
        the bundled masks always remain available.
        """

        bundled = self._bundled_masks()
        bundled_names = {geometry.name for geometry in bundled}
        user = [geometry for geometry in self._user_masks() if geometry.name not in bundled_names]
        return [*bundled, *user]

    def save(self, masks: Iterable[PressureMapMaskGeometry]) -> None:
        """Safely persist user masks without writing over bundled entries."""

        bundled_names = {geometry.name for geometry in self._bundled_masks()}
        local_by_name: dict[str, PressureMapMaskGeometry] = {}
        for geometry in masks:
            if not isinstance(geometry, PressureMapMaskGeometry):
                geometry = _geometry_from_payload(geometry)
            if geometry.name in bundled_names:
                raise ValueError(f'cannot replace bundled pressure-map mask "{geometry.name}"')
            local_by_name.setdefault(geometry.name, geometry)

        ordered = [
            local_by_name[name]
            for name in sorted(local_by_name, key=lambda value: (value.casefold(), value))
        ]
        payload = {
            "version": MASK_LIBRARY_VERSION,
            "masks": [
                {"name": geometry.name, "points_mm": [list(point) for point in geometry.points_mm]}
                for geometry in ordered
            ],
        }
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.file_path.with_name(f".{self.file_path.name}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=MASK_LIBRARY_JSON_INDENT)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.file_path)
        finally:
            if temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def import_file(self, path: str | Path) -> str:
        """Validate and import one standalone simple-schema mask JSON file."""

        import_path = Path(path)
        try:
            with import_path.open("r", encoding="utf-8") as handle:
                geometry = _geometry_from_payload(json.load(handle))
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ValueError(f"could not import pressure-map mask: {exc}") from exc

        bundled_names = {mask.name for mask in self._bundled_masks()}
        local_masks = self._user_masks()
        used_names = bundled_names | {mask.name for mask in local_masks}
        final_name = geometry.name
        if final_name in used_names:
            suffix = 2
            while f"{geometry.name} {suffix}" in used_names:
                suffix += 1
            final_name = f"{geometry.name} {suffix}"
            geometry = PressureMapMaskGeometry(final_name, geometry.points_mm)

        self.save([*local_masks, geometry])
        return final_name
