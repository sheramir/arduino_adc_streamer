import json
import unittest
from pathlib import Path

from config.sensor_config import (
    SensorConfigStore,
    mapping_to_position_channels,
    position_channels_to_mapping,
)
from config.channel_utils import unique_channels_in_order


def test_position_channel_round_trip():
    mapping = ["R", "B", "C", "L", "T"]
    position_channels = mapping_to_position_channels(mapping)

    assert position_channels == {
        "T": 5,
        "R": 1,
        "C": 3,
        "L": 4,
        "B": 2,
    }
    assert position_channels_to_mapping(position_channels) == mapping


def test_position_channels_to_mapping_rejects_duplicates():
    try:
        position_channels_to_mapping({
            "T": 1,
            "R": 1,
            "C": 3,
            "L": 4,
            "B": 5,
        })
    except ValueError as exc:
        assert "Duplicate channel assignment" in str(exc)
    else:
        raise AssertionError("Expected duplicate channel assignments to fail")


def test_store_loads_bundled_and_local_configs(tmp_path: Path):
    bundled_file = tmp_path / "sensor_configurations.json"
    bundled_file.write_text(json.dumps({
        "configurations": [
            {"name": "PLUS", "channel_sensor_map": ["R", "B", "C", "L", "T"]},
            {"name": "ARRAY_v1", "channel_sensor_map": ["T", "L", "B", "R", "C"]},
        ]
    }), encoding="utf-8")

    local_file = tmp_path / "user_sensor_configurations.json"
    local_file.write_text(json.dumps({
        "selected_name": "Custom1",
        "configurations": [
            {"name": "Custom1", "channel_sensor_map": ["C", "R", "B", "L", "T"]},
        ]
    }), encoding="utf-8")

    store = SensorConfigStore(file_path=local_file, bundled_file_path=bundled_file)
    configs, selected_name = store.load()

    assert selected_name == "Custom1"
    assert {config["name"] for config in configs} == {"PLUS", "ARRAY_v1", "Custom1"}


def test_unique_channels_in_order_preserves_first_occurrence():
    assert unique_channels_in_order([4, 2, 4, 1, 2, 3, 1]) == [4, 2, 1, 3]


class ChannelUtilsTests(unittest.TestCase):
    def test_unique_channels_in_order_preserves_first_occurrence_unittest(self):
        self.assertEqual(unique_channels_in_order([4, 2, 4, 1, 2, 3, 1]), [4, 2, 1, 3])
