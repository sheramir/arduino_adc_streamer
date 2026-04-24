import unittest

from config.adc_configuration_service import (
    ADCCommandResult,
    ADCConfigurationRequest,
    ADCConfigurationService,
)
from serial_communication.adc_connection_state import ArduinoStatus


def build_request(**overrides):
    values = {
        "current_mcu": "Arduino Uno",
        "device_mode": "adc",
        "channels": [0, 1, 2],
        "channels_to_send": [0, 1, 2],
        "repeat": 3,
        "use_ground": False,
        "ground_pin": 4,
        "buffer_size": 32,
        "reference": "vdd",
        "osr": 4,
        "gain": 2,
        "conv_speed": "med",
        "samp_speed": "med",
        "sample_rate": 0,
        "rb_ohms": 1000.0,
        "rk_ohms": 2000.0,
        "cf_farads": 1e-9,
        "rxmax_ohms": 5000.0,
        "array_operation_mode": "PZT",
        "is_array_mcu": False,
        "is_array_pzt_pzr_mode": False,
        "is_array_sensor_selection_mode": False,
        "effective_channel_multiplier": 1,
    }
    values.update(overrides)
    return ADCConfigurationRequest(**values)


class ADCConfigurationServiceTests(unittest.TestCase):
    def test_apply_555_parameter_requires_connected_555_mode(self):
        service = ADCConfigurationService(lambda command, expected: (True, "10"))

        disconnected = service.apply_555_parameter("rb", "10", is_connected=False, device_mode="555")
        wrong_mode = service.apply_555_parameter("rb", "10", is_connected=True, device_mode="adc")
        success = service.apply_555_parameter("rb", "10", is_connected=True, device_mode="555")

        self.assertFalse(disconnected.success)
        self.assertIn("Connect a device", disconnected.messages[0])
        self.assertFalse(wrong_mode.success)
        self.assertIn("not in 555 mode", wrong_mode.messages[0])
        self.assertTrue(success.success)
        self.assertEqual(success.messages, ["Applied rb=10"])

    def test_send_adc_config_runs_expected_command_sequence(self):
        commands = []

        def send_command(command, expected):
            commands.append((command, expected))
            responses = {
                "ref vdd": (True, "vdd"),
                "osr 4": (True, "4"),
                "gain 2": (True, "2"),
                "channels 0,1,2": (True, "0,1,2"),
                "repeat 3": (True, "3"),
                "ground false": (True, "false"),
                "buffer 32": (True, "32"),
            }
            return responses[command]

        service = ADCConfigurationService(send_command)
        result = service.send_config_with_verification(build_request())

        self.assertTrue(result.success)
        self.assertIsInstance(result.arduino_status, ArduinoStatus)
        self.assertEqual(
            [command for command, _ in commands],
            ["ref vdd", "osr 4", "gain 2", "channels 0,1,2", "repeat 3", "ground false", "buffer 32"],
        )
        self.assertEqual(result.arduino_status.channels, [0, 1, 2])
        self.assertIn("Configuration matches: [0, 1, 2]", result.messages)

    def test_array_sensor_selection_accepts_unique_echo_verification(self):
        def send_command(command, expected):
            responses = {
                "osr 4": (True, "4"),
                "gain 2": (True, "2"),
                "channels 1,2": (True, "1,2"),
                "repeat 3": (True, "3"),
                "ground false": (True, "false"),
                "buffer 32": (True, "32"),
            }
            return responses[command]

        service = ADCConfigurationService(send_command)
        request = build_request(
            current_mcu="Array_PZT1",
            channels=[1, 1, 2, 2],
            channels_to_send=[1, 2],
            is_array_mcu=True,
            is_array_sensor_selection_mode=True,
            effective_channel_multiplier=2,
        )
        result = service.send_config_with_verification(request)

        self.assertTrue(result.success)
        self.assertEqual(result.arduino_status.channels, [1, 2])
        self.assertIn("Configuration matches: [1, 2]", result.messages)

    def test_array_pzt_buffer_is_limited_by_mux_pair_capacity(self):
        commands = []

        def send_command(command, expected):
            commands.append((command, expected))
            responses = {
                "osr 4": (True, "4"),
                "gain 2": (True, "2"),
                "channels 0,1,2,3,4,5,6,7,8,9": (True, "0,1,2,3,4,5,6,7,8,9"),
                "repeat 1": (True, "1"),
                "ground false": (True, "false"),
                "buffer 800": (True, "800"),
            }
            return responses[command]

        service = ADCConfigurationService(send_command)
        request = build_request(
            current_mcu="Array_PZT_PZR1",
            channels=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2, 3, 4],
            channels_to_send=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            repeat=1,
            buffer_size=1000,
            is_array_mcu=True,
            is_array_sensor_selection_mode=True,
            effective_channel_multiplier=2,
        )

        result = service.send_config_with_verification(request)

        self.assertTrue(result.success)
        self.assertEqual(result.normalized_buffer_size, 800)
        self.assertIn(("buffer 800", "800"), commands)


if __name__ == "__main__":
    unittest.main()
