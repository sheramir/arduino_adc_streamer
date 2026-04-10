import unittest

from serial_communication.force_connection_workflow import ForceConnectionWorkflow


class FakeSession:
    def __init__(self, warnings=None):
        self.warnings = warnings or []
        self.connected_ports = []
        self.disconnect_calls = 0

    def connect(self, port_name):
        self.connected_ports.append(port_name)

    def disconnect(self):
        self.disconnect_calls += 1
        return list(self.warnings)


class ForceConnectionWorkflowTests(unittest.TestCase):
    def test_connect_runs_session_connect_and_requests_calibration(self):
        workflow = ForceConnectionWorkflow()
        session = FakeSession()

        outcome = workflow.connect(session, "COM20")

        self.assertEqual(outcome.port_name, "COM20")
        self.assertTrue(outcome.should_start_calibration)
        self.assertEqual(session.connected_ports, ["COM20"])

    def test_disconnect_collects_session_warnings(self):
        workflow = ForceConnectionWorkflow()
        session = FakeSession(warnings=["Force serial thread shutdown timed out"])

        outcome = workflow.disconnect(session)

        self.assertEqual(session.disconnect_calls, 1)
        self.assertEqual(outcome.warnings, ["Force serial thread shutdown timed out"])

    def test_disconnect_with_missing_session_returns_empty_warnings(self):
        workflow = ForceConnectionWorkflow()

        outcome = workflow.disconnect(None)

        self.assertEqual(outcome.warnings, [])


if __name__ == "__main__":
    unittest.main()
