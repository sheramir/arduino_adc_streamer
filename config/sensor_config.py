"""
Sensor configuration helpers and persistence for editable 5-channel layouts and array layouts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from constants.sensor_config import (
    DEFAULT_SENSOR_CONFIGURATION,
    DEFAULT_SENSOR_CONFIGURATION_NAME,
    SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX,
    SENSOR_CONFIG_ARRAY_COLS,
    SENSOR_CONFIG_ARRAY_ROWS,
    SENSOR_CONFIG_CHANNEL_COUNT,
    SENSOR_CONFIG_CHANNEL_MAX,
    SENSOR_CONFIG_CHANNEL_MIN,
    SENSOR_CONFIG_FILE_VERSION,
    SENSOR_CONFIG_JSON_INDENT,
    SENSOR_CONFIG_MUX_MAX,
    SENSOR_CONFIG_MUX_MIN,
    SENSOR_LOCATION_CODES,
)

SENSOR_POSITION_ORDER = ["T", "R", "C", "L", "B"]
SENSOR_POSITION_LABELS = {
    "T": "Top",
    "R": "Right",
    "C": "Center",
    "L": "Left",
    "B": "Bottom",
}

# Backward-compatible aliases for modules that still import the historical
# array-layout constants from config.sensor_config.
ARRAY_ROWS = SENSOR_CONFIG_ARRAY_ROWS
ARRAY_COLS = SENSOR_CONFIG_ARRAY_COLS
ARRAY_CELL_CHANNELS_MAX = SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX

def default_sensor_configuration() -> Dict[str, object]:
    return {
        "name": str(DEFAULT_SENSOR_CONFIGURATION.get("name", DEFAULT_SENSOR_CONFIGURATION_NAME)),
        "channel_sensor_map": list(DEFAULT_SENSOR_CONFIGURATION.get("channel_sensor_map", [])),
        "is_bundled": False,
    }


def default_array_configuration() -> Dict[str, object]:
    return {
        "array_layout": {"cells": [[None] * SENSOR_CONFIG_ARRAY_COLS for _ in range(SENSOR_CONFIG_ARRAY_ROWS)]},
        "mux_mapping": {},
        "channel_layout": {"channels_per_sensor": SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX},
    }


def normalize_channel_sensor_map(channel_sensor_map) -> List[str] | None:
    if not isinstance(channel_sensor_map, list) or len(channel_sensor_map) != SENSOR_CONFIG_CHANNEL_COUNT:
        return None

    normalized = [str(value).strip().upper() for value in channel_sensor_map]
    if sorted(normalized) != sorted(SENSOR_LOCATION_CODES):
        return None
    return normalized


def normalize_sensor_config(config: Dict[str, object]) -> Dict[str, object] | None:
    if not isinstance(config, dict):
        return None

    name = str(config.get("name", "")).strip()
    channel_sensor_map = normalize_channel_sensor_map(config.get("channel_sensor_map"))
    if not name or channel_sensor_map is None:
        return None

    return {
        "name": name,
        "channel_sensor_map": channel_sensor_map,
    }


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bundled_sensor_library_dir() -> Path:
    preferred = _project_root() / "sensors_library"
    if preferred.exists():
        return preferred
    return _project_root()


def _default_bundled_sensor_configs_path() -> Path:
    """Prefer the bundled sensor library, with backward-compatible root fallback."""
    library_dir = _bundled_sensor_library_dir()
    preferred = library_dir / "sensor_configurations.json"
    if preferred.exists():
        return preferred

    legacy = library_dir / "sensors.json"
    if legacy.exists():
        return legacy

    project_root = _project_root()
    legacy_root_preferred = project_root / "sensor_configurations.json"
    if legacy_root_preferred.exists():
        return legacy_root_preferred

    legacy_root_fallback = project_root / "sensors.json"
    if legacy_root_fallback.exists():
        return legacy_root_fallback

    return preferred


def _read_sensor_configs_file(file_path: Path) -> List[Dict[str, object]]:
    if not file_path.exists():
        return []

    with file_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_configs = payload.get("configurations", payload if isinstance(payload, list) else [])
    configs: List[Dict[str, object]] = []
    used_names = set()
    for raw_config in raw_configs:
        normalized = normalize_combined_sensor_config(raw_config)
        if normalized is not None:
            if normalized["name"] in used_names:
                continue
            used_names.add(str(normalized["name"]))
            configs.append(normalized)
    
    return configs


def mapping_to_position_channels(channel_sensor_map: List[str]) -> Dict[str, int]:
    return {
        sensor_label: channel_sensor_map.index(sensor_label) + 1
        for sensor_label in SENSOR_POSITION_ORDER
    }


def position_channels_to_mapping(position_channels: Dict[str, int]) -> List[str]:
    mapping = [None] * SENSOR_CONFIG_CHANNEL_COUNT
    for sensor_label in SENSOR_POSITION_ORDER:
        channel_number = int(position_channels[sensor_label])
        if channel_number < 1 or channel_number > SENSOR_CONFIG_CHANNEL_COUNT:
            raise ValueError(f"Channel number out of range for {sensor_label}: {channel_number}")
        if mapping[channel_number - 1] is not None:
            raise ValueError(f"Duplicate channel assignment for channel {channel_number}")
        mapping[channel_number - 1] = sensor_label

    if any(value is None for value in mapping):
        raise ValueError("Incomplete sensor mapping")
    return mapping


# ============================================================================
# Array Configuration Functions
# ============================================================================

def validate_sensor_id(sensor_id: str) -> bool:
    """Validate that sensor_id is of format PZT1/PZR1 (legacy PZT_1/PZR_1 is accepted)."""
    if not sensor_id or not isinstance(sensor_id, str):
        return True  # Empty cell is valid
    sensor_id = str(sensor_id).strip()
    if not sensor_id:
        return True  # Empty string is valid

    match = re.fullmatch(r"(PZT|PZR)_?(\d+)", sensor_id.upper())
    if not match:
        return False

    sensor_type, sensor_num = match.groups()
    if sensor_type not in ("PZT", "PZR"):
        return False

    try:
        num = int(sensor_num)
        return num > 0
    except ValueError:
        return False


def normalize_array_cell(cell_value: str | None) -> str | None:
    """Normalize array cell value to canonical PZT1/PZR1 format and validate."""
    if not cell_value or not isinstance(cell_value, str):
        return None
    normalized = str(cell_value).strip().upper()
    if not normalized:
        return None

    match = re.fullmatch(r"(PZT|PZR)_?(\d+)", normalized)
    if not match:
        return None

    sensor_type, sensor_num = match.groups()
    if not validate_sensor_id(f"{sensor_type}{sensor_num}"):
        return None

    normalized = f"{sensor_type}{int(sensor_num)}"
    if validate_sensor_id(normalized):
        return normalized
    return None


def normalize_array_layout(array_layout: Dict[str, object]) -> Dict[str, object] | None:
    """Normalize and validate array layout structure."""
    if not isinstance(array_layout, dict):
        return None
    
    cells_raw = array_layout.get("cells", [])
    if not isinstance(cells_raw, list) or len(cells_raw) != SENSOR_CONFIG_ARRAY_ROWS:
        return None
    
    cells_normalized = []
    for row_idx, row in enumerate(cells_raw):
        if not isinstance(row, list) or len(row) != SENSOR_CONFIG_ARRAY_COLS:
            return None
        normalized_row = []
        for cell in row:
            normalized_cell = normalize_array_cell(cell)
            normalized_row.append(normalized_cell)
        cells_normalized.append(normalized_row)
    
    return {"cells": cells_normalized}


def normalize_mux_mapping(
    mux_mapping: Dict[str, object],
    allowed_sensors: set[str] | None = None
) -> Dict[str, object] | None:
    """Normalize and validate MUX mapping structure."""
    if not isinstance(mux_mapping, dict):
        return None
    
    normalized = {}
    for sensor_id_raw, mapping_data in mux_mapping.items():
        sensor_id = normalize_array_cell(sensor_id_raw)
        if not sensor_id:
            continue
        if allowed_sensors and sensor_id not in allowed_sensors:
            continue  # Skip mappings for sensors not in array
        
        if not isinstance(mapping_data, dict):
            return None
        
        try:
            mux_num = int(mapping_data.get("mux", 0))
            channels_raw = mapping_data.get("channels", [])
            
            if mux_num < SENSOR_CONFIG_MUX_MIN or mux_num > SENSOR_CONFIG_MUX_MAX:
                return None
            if not isinstance(channels_raw, list):
                return None
            
            channels = [int(c) for c in channels_raw]
            if len(channels) < 1 or len(channels) > SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX:
                return None
            if any(c < SENSOR_CONFIG_CHANNEL_MIN or c > SENSOR_CONFIG_CHANNEL_MAX for c in channels):
                return None
            if len(set(channels)) != len(channels):  # Check for duplicates
                return None
            
            normalized[sensor_id] = {
                "mux": mux_num,
                "channels": sorted(channels)
            }
        except (ValueError, TypeError):
            return None
    
    return normalized


def get_sensors_from_array_layout(array_layout: Dict[str, object]) -> set[str]:
    """Extract all sensor IDs from array layout."""
    sensors = set()
    cells = array_layout.get("cells", [])
    for row in cells:
        for cell in row:
            if cell:
                sensors.add(cell)
    return sensors


def normalize_array_config(config: Dict[str, object]) -> Dict[str, object] | None:
    """Normalize and validate array configuration."""
    if not isinstance(config, dict):
        return None
    
    name = str(config.get("name", "")).strip()
    if not name:
        return None
    
    array_layout_raw = config.get("array_layout", {})
    array_layout = normalize_array_layout(array_layout_raw)
    if not array_layout:
        return None
    
    sensors = get_sensors_from_array_layout(array_layout)
    if not sensors:
        return None
    
    mux_mapping_raw = config.get("mux_mapping", {})
    mux_mapping = normalize_mux_mapping(mux_mapping_raw, allowed_sensors=sensors)
    if not mux_mapping:
        return None
    
    # Check that all sensors have MUX mappings
    for sensor in sensors:
        if sensor not in mux_mapping:
            return None
    
    channel_layout = config.get("channel_layout", {})
    if not isinstance(channel_layout, dict):
        return None
    
    try:
        channels_per_sensor = int(channel_layout.get("channels_per_sensor", SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX))
        if channels_per_sensor < 1 or channels_per_sensor > SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX:
            return None
    except (ValueError, TypeError):
        return None
    
    return {
        "name": name,
        "type": "array_layout",
        "array_layout": array_layout,
        "mux_mapping": mux_mapping,
        "channel_layout": {"channels_per_sensor": channels_per_sensor},
    }


def normalize_optional_array_config(config: Dict[str, object]) -> Dict[str, object] | None:
    """Normalize optional array attachment.

    Returns an empty dict when no array is configured, a normalized attachment when
    valid array data is present, or None when partial/invalid array data is present.
    """
    default_array = default_array_configuration()
    array_layout_raw = config.get("array_layout", default_array["array_layout"])
    mux_mapping_raw = config.get("mux_mapping", default_array["mux_mapping"])
    channel_layout_raw = config.get("channel_layout", default_array["channel_layout"])

    array_layout = normalize_array_layout(array_layout_raw)
    if array_layout is None:
        return None

    sensors = get_sensors_from_array_layout(array_layout)
    if not sensors:
        if isinstance(mux_mapping_raw, dict) and mux_mapping_raw:
            return None
        return {}

    mux_mapping = normalize_mux_mapping(mux_mapping_raw, allowed_sensors=sensors)
    if not mux_mapping:
        return None

    for sensor in sensors:
        if sensor not in mux_mapping:
            return None

    if not isinstance(channel_layout_raw, dict):
        return None

    try:
        channels_per_sensor = int(channel_layout_raw.get("channels_per_sensor", SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX))
        if channels_per_sensor < 1 or channels_per_sensor > SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX:
            return None
    except (ValueError, TypeError):
        return None

    return {
        "array_layout": array_layout,
        "mux_mapping": mux_mapping,
        "channel_layout": {"channels_per_sensor": channels_per_sensor},
    }


def normalize_combined_sensor_config(config: Dict[str, object]) -> Dict[str, object] | None:
    """Normalize a sensor config with channel mapping and optional array attachment."""
    if not isinstance(config, dict):
        return None

    name = str(config.get("name", "")).strip()
    if not name:
        return None

    default_map = list(default_sensor_configuration()["channel_sensor_map"])
    channel_sensor_map = normalize_channel_sensor_map(config.get("channel_sensor_map"))
    array_attachment = normalize_optional_array_config(config)

    if channel_sensor_map is None:
        if array_attachment is None or not array_attachment:
            return None
        channel_sensor_map = default_map

    if array_attachment is None:
        return None

    normalized = {
        "name": name,
        "channel_sensor_map": channel_sensor_map,
        "type": "array_layout" if array_attachment else "channel_layout",
    }
    normalized.update(array_attachment)
    return normalized


class SensorConfigStore:
    def __init__(self, file_path: Path | None = None, bundled_file_path: Path | None = None):
        self.file_path = file_path or (Path.home() / ".adc_streamer" / "sensors" / "sensor_configurations.json")
        self.bundled_file_path = bundled_file_path or _default_bundled_sensor_configs_path()

    def load(self) -> Tuple[List[Dict[str, object]], str]:
        default_config_normalized = normalize_combined_sensor_config(default_sensor_configuration())
        if not default_config_normalized:
            default_config_normalized = default_sensor_configuration()
        default_config_normalized["type"] = "channel_layout"
        
        bundled_configs = _read_sensor_configs_file(self.bundled_file_path)
        if not bundled_configs:
            bundled_configs = [dict(default_config_normalized)]

        local_payload = {}
        if self.file_path.exists():
            with self.file_path.open("r", encoding="utf-8") as handle:
                local_payload = json.load(handle)

        deleted_names = {
            str(name).strip()
            for name in local_payload.get("deleted_names", [])
            if str(name).strip()
        }
        local_configs = _read_sensor_configs_file(self.file_path)

        configs_by_name: Dict[str, Dict[str, object]] = {}
        for config in bundled_configs:
            if config["name"] in deleted_names:
                continue
            config_copy = dict(config)
            config_copy["is_bundled"] = True
            configs_by_name[str(config["name"])] = config_copy

        for config in local_configs:
            config_copy = dict(config)
            config_copy["is_bundled"] = False
            configs_by_name[str(config["name"])] = config_copy

        configs = list(configs_by_name.values())
        if not configs:
            configs = [dict(default_config_normalized)]

        selected_name = str(local_payload.get("selected_name", "")).strip()
        if selected_name not in {config["name"] for config in configs}:
            selected_name = str(default_config_normalized["name"])
        if selected_name not in {config["name"] for config in configs}:
            selected_name = str(configs[0]["name"])

        return configs, selected_name

    def save(self, configs: List[Dict[str, object]], selected_name: str) -> None:
        bundled_configs = {
            config["name"]: config
            for config in _read_sensor_configs_file(self.bundled_file_path)
        }

        normalized_local_configs = []
        current_names = set()
        for config in configs:
            normalized = normalize_combined_sensor_config(config)
            
            if normalized is None:
                continue
            
            name = str(normalized["name"])
            current_names.add(name)
            is_bundled = bool(config.get("is_bundled", False))
            bundled_match = bundled_configs.get(name)
            if is_bundled and bundled_match == normalized:
                continue
            normalized_local_configs.append(normalized)

        deleted_names = sorted(
            name
            for name in bundled_configs
            if name not in current_names
        )

        all_names = {
            config["name"] for config in normalized_local_configs
        } | {
            name for name in bundled_configs if name not in deleted_names
        }
        if not all_names:
            default_config = default_sensor_configuration()
            default_config["type"] = "channel_layout"
            normalized_local_configs = [normalize_combined_sensor_config(default_config) or default_config]
            selected_name = str(default_config["name"])

        if selected_name not in all_names:
            selected_name = str(next(iter(sorted(all_names))))

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": SENSOR_CONFIG_FILE_VERSION,
                    "selected_name": selected_name,
                    "deleted_names": deleted_names,
                    "configurations": normalized_local_configs,
                },
                handle,
                indent=SENSOR_CONFIG_JSON_INDENT,
            )
