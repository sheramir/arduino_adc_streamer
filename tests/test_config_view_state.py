import unittest

from config.config_view_state import (
    build_configuration_failed_state,
    build_configuration_success_state,
    build_configuring_state,
    build_start_needs_config_state,
    build_start_ready_state,
    build_start_unavailable_state,
)


class ConfigViewStateTests(unittest.TestCase):
    def test_configure_states_match_expected_ui_flags(self):
        configuring = build_configuring_state()
        success = build_configuration_success_state()
        failed = build_configuration_failed_state()

        self.assertFalse(configuring.enabled)
        self.assertTrue(success.enabled)
        self.assertIn("Ready to capture", success.status_message)
        self.assertTrue(failed.enabled)
        self.assertIn("retry", failed.status_message)

    def test_start_states_match_expected_ui_flags(self):
        ready = build_start_ready_state()
        needs_config = build_start_needs_config_state()
        unavailable = build_start_unavailable_state()

        self.assertTrue(ready.enabled)
        self.assertIn("Start", ready.text)
        self.assertFalse(needs_config.enabled)
        self.assertIn("Configure First", needs_config.text)
        self.assertFalse(unavailable.enabled)
        self.assertEqual(unavailable.text, "Start")


if __name__ == "__main__":
    unittest.main()
