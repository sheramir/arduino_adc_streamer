import unittest

from serial_communication.adc_connection_workflow import ADCConnectionWorkflow


class FakeSession:
    def __init__(self, mcu_name=None, warnings=None):
        self.mcu_name = mcu_name
        self.warnings = warnings or []
        self.connected_ports = []
        self.detect_timeouts = []
        self.disconnect_calls = 0

    def connect(self, port_name):
        self.connected_ports.append(port_name)

    def detect_mcu(self, timeout):
        self.detect_timeouts.append(timeout)
        return self.mcu_name

    def disconnect(self):
        self.disconnect_calls += 1
        return list(self.warnings)


class ADCConnectionWorkflowTests(unittest.TestCase):
    def test_connect_runs_session_connect_then_mcu_detection(self):
        workflow = ADCConnectionWorkflow()
        session = FakeSession(mcu_name="Teensy4.1")

        outcome = workflow.connect(session, "COM7", mcu_detection_timeout=1.5)

        self.assertEqual(outcome.port_name, "COM7")
        self.assertEqual(outcome.mcu_name, "Teensy4.1")
        self.assertEqual(session.connected_ports, ["COM7"])
        self.assertEqual(session.detect_timeouts, [1.5])

    def test_disconnect_collects_session_warnings(self):
        workflow = ADCConnectionWorkflow()
        session = FakeSession(warnings=["Serial thread shutdown timed out"])

        outcome = workflow.disconnect(session)

        self.assertEqual(session.disconnect_calls, 1)
        self.assertEqual(outcome.warnings, ["Serial thread shutdown timed out"])


if __name__ == "__main__":
    unittest.main()
