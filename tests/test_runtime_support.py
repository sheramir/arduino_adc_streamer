import unittest

from config.config_handlers import ConfigurationMixin
from config_constants import MAX_LOG_LINES
from data_processing.adc_plotting import ADCPlottingMixin
from gui.status_logging import StatusLoggingMixin


class FakeScrollBar:
    def __init__(self):
        self.value = None

    def setValue(self, value):
        self.value = value

    def maximum(self):
        return 999


class FakeStatusText:
    def __init__(self):
        self._text = ''
        self._scrollbar = FakeScrollBar()

    def append(self, text):
        if self._text:
            self._text += '\n'
        self._text += text

    def toPlainText(self):
        return self._text

    def setPlainText(self, text):
        self._text = text

    def verticalScrollBar(self):
        return self._scrollbar


class FakeComboBox:
    def __init__(self, text):
        self._text = text

    def currentText(self):
        return self._text


class FakePlotWidget:
    def __init__(self):
        self.y_range = None
        self.auto_range_axis = None

    def setYRange(self, low, high, padding=0.0):
        self.y_range = (low, high, padding)

    def enableAutoRange(self, axis=None):
        self.auto_range_axis = axis


class StatusLoggingHarness(StatusLoggingMixin):
    def __init__(self):
        self.status_text = FakeStatusText()


class ConfigurationHarness(ConfigurationMixin):
    def __init__(self, reference='vdd'):
        self.config = {'reference': reference}


class ADCPlottingHarness(ADCPlottingMixin, ConfigurationHarness):
    def __init__(self, reference='vdd', range_text='Full-Scale', units_text='Voltage', device_mode='adc'):
        ConfigurationHarness.__init__(self, reference=reference)
        self.yaxis_range_combo = FakeComboBox(range_text)
        self.yaxis_units_combo = FakeComboBox(units_text)
        self.plot_widget = FakePlotWidget()
        self.device_mode = device_mode


class RuntimeSupportTests(unittest.TestCase):
    def test_get_vref_voltage_maps_known_references(self):
        self.assertEqual(ConfigurationHarness('1.2').get_vref_voltage(), 1.2)
        self.assertEqual(ConfigurationHarness('vdd').get_vref_voltage(), 3.3)
        self.assertEqual(ConfigurationHarness('0.8vdd').get_vref_voltage(), 2.64)
        self.assertEqual(ConfigurationHarness('ext').get_vref_voltage(), 1.25)
        self.assertEqual(ConfigurationHarness('unknown').get_vref_voltage(), 3.3)

    def test_log_status_trims_to_max_lines_and_scrolls(self):
        harness = StatusLoggingHarness()
        existing = '\n'.join(f'line {i}' for i in range(MAX_LOG_LINES))
        harness.status_text.setPlainText(existing)

        harness.log_status('new message')

        lines = harness.status_text.toPlainText().split('\n')
        self.assertEqual(len(lines), MAX_LOG_LINES)
        self.assertTrue(lines[-1].endswith('new message'))
        self.assertEqual(harness.status_text.verticalScrollBar().value, 999)

    def test_apply_y_axis_range_uses_configuration_voltage(self):
        harness = ADCPlottingHarness(reference='ext', range_text='Full-Scale', units_text='Voltage')

        harness.apply_y_axis_range()

        self.assertEqual(harness.plot_widget.y_range, (0, 1.25, 0.02))


if __name__ == '__main__':
    unittest.main()
