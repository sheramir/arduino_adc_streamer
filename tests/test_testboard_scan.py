from config.testboard_scan import (
    build_testboard_routes,
    order_testboard_routes,
    physical_lanes_for_mapping,
)


GROUPS = [
    {"sensor_id": "PZT1", "mux": 1, "channels": [0, 1]},
    {"sensor_id": "PZT3", "mux": 2, "channels": [10, 11]},
]


def test_pair_local_lanes_follow_array_selection():
    assert physical_lanes_for_mapping(1, "1") == (1,)
    assert physical_lanes_for_mapping(2, "2") == (4,)
    assert physical_lanes_for_mapping(1, "both") == (1, 3)


def test_sparse_routes_include_only_selected_adc_channel_pairs():
    routes = build_testboard_routes(GROUPS, array_selection="both")

    assert routes == [
        (1, 0), (1, 1), (3, 0), (3, 1),
        (2, 10), (2, 11), (4, 10), (4, 11),
    ]
    assert (2, 0) not in routes
    assert (1, 10) not in routes


def test_scan_orders_change_acquisition_order_without_changing_membership():
    routes = build_testboard_routes(GROUPS, array_selection="both")

    interleaved = order_testboard_routes(routes, "interleaved")
    array_order = order_testboard_routes(routes, "array")
    adc_order = order_testboard_routes(routes, "adc")

    assert interleaved == [
        (1, 0), (2, 10), (3, 0), (4, 10),
        (1, 1), (2, 11), (3, 1), (4, 11),
    ]
    assert array_order == [
        (1, 0), (2, 10), (1, 1), (2, 11),
        (3, 0), (4, 10), (3, 1), (4, 11),
    ]
    assert adc_order == [
        (1, 0), (1, 1), (2, 10), (2, 11),
        (3, 0), (3, 1), (4, 10), (4, 11),
    ]
    assert set(interleaved) == set(array_order) == set(adc_order)
