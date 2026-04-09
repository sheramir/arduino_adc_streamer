import time
import unittest

from config.adc_configuration_runner import ADCConfigurationRunner


class FakeSerialPort:
    def __init__(self):
        self.is_open = True
        self.input_reset_count = 0
        self.output_reset_count = 0

    def reset_input_buffer(self):
        self.input_reset_count += 1

    def reset_output_buffer(self):
        self.output_reset_count += 1


class FakeService:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    def send_config_with_verification(self, request):
        self.requests.append(request)
        return self.results.pop(0)


class FakeResult:
    def __init__(self, success):
        self.success = success


class ADCConfigurationRunnerTests(unittest.TestCase):
    def test_runner_retries_until_success_and_returns_outcome(self):
        serial_port = FakeSerialPort()
        service = FakeService([FakeResult(False), FakeResult(True)])
        runner = ADCConfigurationRunner(service)

        started = runner.start(serial_port, request={"channels": [1, 2]}, max_attempts=2)
        self.assertTrue(started)

        deadline = time.time() + 1.0
        outcome = None
        while time.time() < deadline and outcome is None:
            outcome = runner.take_outcome()
            time.sleep(0.01)

        self.assertIsNotNone(outcome)
        self.assertTrue(outcome.success)
        self.assertEqual(len(service.requests), 2)
        self.assertEqual(serial_port.input_reset_count, 1)
        self.assertEqual(serial_port.output_reset_count, 1)


if __name__ == "__main__":
    unittest.main()
