"""Tests for bundled and imported pressure-map mask persistence."""

import json
from pathlib import Path

import pytest

from config.pressure_map_mask_config import MaskConfigStore
from data_processing.pressure_map_mask import PressureMapMaskGeometry


def _write_mask(path: Path, name: str, points=((0, 0), (2, 0), (0, 2))) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name, "points_mm": points}), encoding="utf-8")


def test_store_loads_bundled_masks_then_non_conflicting_user_masks(tmp_path: Path):
    bundled_dir = tmp_path / "bundled"
    local_file = tmp_path / "user" / "mask_library.json"
    _write_mask(bundled_dir / "Bundle.json", "Bundle")
    local_file.parent.mkdir()
    local_file.write_text(
        json.dumps({"masks": [
            {"name": "User", "points_mm": [[0, 0], [3, 0], [0, 3]]},
            {"name": "Bundle", "points_mm": [[0, 0], [4, 0], [0, 4]]},
        ]}),
        encoding="utf-8",
    )

    masks = MaskConfigStore(file_path=local_file, bundled_masks_path=bundled_dir).load()

    assert [mask.name for mask in masks] == ["Bundle", "User"]


def test_standalone_import_persists_and_renames_duplicate_bundled_name(tmp_path: Path):
    bundled_dir = tmp_path / "bundled"
    local_file = tmp_path / "user" / "mask_library.json"
    source_file = tmp_path / "Plus5.json"
    _write_mask(bundled_dir / "Plus5.json", "Plus5")
    _write_mask(source_file, "Plus5", ((0, 0), (5, 0), (0, 5)))
    store = MaskConfigStore(file_path=local_file, bundled_masks_path=bundled_dir)

    imported_name = store.import_file(source_file)

    assert imported_name == "Plus5 2"
    assert [mask.name for mask in store.load()] == ["Plus5", "Plus5 2"]
    payload = json.loads(local_file.read_text(encoding="utf-8"))
    assert [item["name"] for item in payload["masks"]] == ["Plus5 2"]


def test_malformed_import_is_rejected_and_bundled_masks_remain_available(tmp_path: Path):
    bundled_dir = tmp_path / "bundled"
    local_file = tmp_path / "user" / "mask_library.json"
    malformed_file = tmp_path / "bad.json"
    _write_mask(bundled_dir / "Bundle.json", "Bundle")
    malformed_file.write_text('{"name": "Bad", "points_mm": [[0, 0]]}', encoding="utf-8")
    store = MaskConfigStore(file_path=local_file, bundled_masks_path=bundled_dir)

    with pytest.raises(ValueError, match="could not import"):
        store.import_file(malformed_file)

    assert [mask.name for mask in store.load()] == ["Bundle"]


def test_save_refuses_to_replace_a_bundled_mask(tmp_path: Path):
    bundled_dir = tmp_path / "bundled"
    local_file = tmp_path / "user" / "mask_library.json"
    _write_mask(bundled_dir / "Bundle.json", "Bundle")
    store = MaskConfigStore(file_path=local_file, bundled_masks_path=bundled_dir)

    with pytest.raises(ValueError, match="bundled"):
        store.save([PressureMapMaskGeometry("Bundle", ((0, 0), (3, 0), (0, 3)))])


def test_bundled_plus5_coordinates_load_exactly():
    store = MaskConfigStore()

    plus5 = {mask.name: mask for mask in store.load()}["Plus5"]

    assert plus5.points_mm == (
        (-3.75, 11.25), (3.75, 11.25), (3.75, 5.5), (5.5, 3.75),
        (11.25, 3.75), (11.25, -3.75), (5.5, -3.75), (3.75, -5.5),
        (3.75, -11.25), (-3.75, -11.25), (-3.75, -5.5), (-5.5, -3.75),
        (-11.25, -3.75), (-11.25, 3.75), (-5.5, 3.75), (-3.75, 5.5),
    )
