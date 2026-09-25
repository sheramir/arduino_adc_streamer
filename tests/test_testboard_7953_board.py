from config.testboard_7953_board import (
    ARRAY_ADC_LANES,
    PZT_CHANNEL_LABELS,
    PZT_SENSOR_ROUTES,
    build_testboard_sensor_groups,
    supported_pzt_sensors,
)


def test_physical_array_adc_pairs_match_testboard_wiring():
    assert ARRAY_ADC_LANES == {1: (1, 2), 2: (3, 4)}


def test_pzt_wiring_profile_matches_ads7953_inputs():
    assert PZT_CHANNEL_LABELS == ("B", "L", "C", "R", "T")
    assert PZT_SENSOR_ROUTES["PZT6"].adc_position == 1
    assert PZT_SENSOR_ROUTES["PZT6"].channels == (0, 1, 2, 3, 4)
    assert PZT_SENSOR_ROUTES["PZT7"].channels == (5, 6, 7, 8, 9)
    assert PZT_SENSOR_ROUTES["PZT1"].adc_position == 2
    assert PZT_SENSOR_ROUTES["PZT1"].channels == (0, 1, 2, 3, 4)
    assert PZT_SENSOR_ROUTES["PZT3"].channels == (5, 6, 7, 8, 9)
    assert PZT_SENSOR_ROUTES["PZT5"].channels == (10, 11, 12, 13, 14)
    assert supported_pzt_sensors() == ("PZT6", "PZT7", "PZT1", "PZT3", "PZT5")


def test_board_groups_preserve_user_sensor_order_and_fixed_labels():
    groups = build_testboard_sensor_groups(["PZT3", "PZT6"])

    assert [group["sensor_id"] for group in groups] == ["PZT3", "PZT6"]
    assert groups[0]["mux"] == 2
    assert groups[0]["channels"] == [5, 6, 7, 8, 9]
    assert groups[1]["mux"] == 1
    assert groups[1]["channels"] == [0, 1, 2, 3, 4]
    assert groups[0]["channel_labels"] == ["B", "L", "C", "R", "T"]
