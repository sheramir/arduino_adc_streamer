import unittest

from data_processing.timing_display import TimingDisplayMixin


class FakeLabel:
    def __init__(self):
        self.text = None
        self.visible = True

    def setText(self, text):
        self.text = text

    def setVisible(self, value):
        self.visible = bool(value)


class TimingHarness(TimingDisplayMixin):
    def __init__(self):
        self.config = {
            'cf_farads': 100e-9,
            'rb_ohms': 1000.0,
            'rk_ohms': 500.0,
        }
        self.device_mode = '555'
        self.charge_time_label = FakeLabel()
        self.discharge_time_label = FakeLabel()


class TimingDisplayTests(unittest.TestCase):
    def test_format_time_auto_uses_scaled_units(self):
        harness = TimingHarness()
        self.assertEqual(harness._format_time_auto(0.0000005), '0.50 \u00b5s')
        self.assertEqual(harness._format_time_auto(0.05), '50.00 ms')
        self.assertEqual(harness._format_time_auto(1.25), '1.2500 s')

    def test_update_555_timing_readouts_formats_charge_and_discharge(self):
        harness = TimingHarness()

        harness.update_555_timing_readouts({1: 1000.0, 3: 2000.0})

        self.assertTrue(harness.charge_time_label.visible)
        self.assertTrue(harness.discharge_time_label.visible)
        self.assertEqual(
            harness.charge_time_label.text,
            'Charge time: Ch1: 173.29 \u00b5s | Ch3: 242.60 \u00b5s',
        )
        self.assertEqual(harness.discharge_time_label.text, 'Discharge time: 69.31 \u00b5s')


if __name__ == '__main__':
    unittest.main()
