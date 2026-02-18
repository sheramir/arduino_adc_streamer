"""
Spectrum Panel GUI Component
============================
Provides UI components for real-time frequency-domain visualization.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pyqtgraph.exporters import ImageExporter

from config_constants import (
    PLOT_COLORS, PLOT_EXPORT_WIDTH,
    FILTER_DEFAULT_ENABLED, FILTER_DEFAULT_MAIN_TYPE, FILTER_DEFAULT_ORDER,
    FILTER_DEFAULT_LOW_CUTOFF_HZ, FILTER_DEFAULT_HIGH_CUTOFF_HZ,
    FILTER_NOTCH1_DEFAULT_ENABLED, FILTER_NOTCH1_DEFAULT_FREQ_HZ, FILTER_NOTCH1_DEFAULT_Q,
    FILTER_NOTCH2_DEFAULT_ENABLED, FILTER_NOTCH2_DEFAULT_FREQ_HZ, FILTER_NOTCH2_DEFAULT_Q,
    FILTER_NOTCH3_DEFAULT_ENABLED, FILTER_NOTCH3_DEFAULT_FREQ_HZ, FILTER_NOTCH3_DEFAULT_Q,
)


class SpectrumPanelMixin:
    """Mixin providing spectrum display tab and interactions."""

    def _get_last_spectrum_settings_path(self):
        return Path.home() / ".adc_streamer" / "spectrum" / "last_used_spectrum_settings.json"

    def _serialize_spectrum_settings(self):
        return {
            'version': 1,
            'spectrum_settings': self.get_spectrum_settings(),
        }

    def _apply_spectrum_settings(self, settings):
        if not settings:
            return

        self.spectrum_window_ms_spin.setValue(int(settings.get('window_ms', self.spectrum_window_ms_spin.value())))

        nfft_mode = settings.get('nfft_mode', 'auto')
        self.spectrum_nfft_combo.setCurrentText('Auto (next power of 2)' if nfft_mode == 'auto' else str(settings.get('nfft_value', 2048)))

        mode = settings.get('mode', 'welch')
        self.spectrum_mode_combo.setCurrentText('Welch PSD' if mode == 'welch' else 'Single FFT')

        window_name = settings.get('window', 'hann')
        self.spectrum_window_combo.setCurrentText(window_name.capitalize() if window_name != 'rectangular' else 'Rectangular')

        self.spectrum_seg_len_spin.setValue(int(settings.get('welch_segment', self.spectrum_seg_len_spin.value())))
        self.spectrum_overlap_spin.setValue(float(settings.get('welch_overlap', self.spectrum_overlap_spin.value())))

        averaging_mode = settings.get('averaging_mode', 'ema')
        self.spectrum_averaging_combo.setCurrentText('EMA' if averaging_mode == 'ema' else 'N-Averages')
        self.spectrum_ema_alpha_spin.setValue(float(settings.get('ema_alpha', self.spectrum_ema_alpha_spin.value())))
        self.spectrum_navg_spin.setValue(int(settings.get('n_avg', self.spectrum_navg_spin.value())))

        self.spectrum_fmin_spin.setValue(float(settings.get('f_min', self.spectrum_fmin_spin.value())))
        self.spectrum_fmax_spin.setValue(float(settings.get('f_max', self.spectrum_fmax_spin.value())))

        self.spectrum_band_fmin_spin.setValue(float(settings.get('band_f1', self.spectrum_band_fmin_spin.value())))
        self.spectrum_band_fmax_spin.setValue(float(settings.get('band_f2', self.spectrum_band_fmax_spin.value())))

        self.spectrum_y_scale_combo.setCurrentText('dB' if settings.get('y_scale', 'db') == 'db' else 'Linear')
        self.spectrum_x_scale_combo.setCurrentText('Log' if settings.get('x_scale', 'linear') == 'log' else 'Linear')

        self.spectrum_update_rate_spin.setValue(int(settings.get('update_rate_hz', self.spectrum_update_rate_spin.value())))
        self.spectrum_remove_dc_check.setChecked(bool(settings.get('remove_dc', True)))
        self.spectrum_snap_peak_check.setChecked(bool(settings.get('snap_to_peak', False)))
        self.on_spectrum_update_rate_changed(self.spectrum_update_rate_spin.value())

        filter_settings = settings.get('filter_settings')
        if filter_settings and hasattr(self, 'filter_master_check'):
            self._apply_filter_widgets(filter_settings)

    def save_last_spectrum_settings(self):
        try:
            path = self._get_last_spectrum_settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='utf-8') as f:
                json.dump(self._serialize_spectrum_settings(), f, indent=2)
        except Exception as e:
            self.log_status(f"Warning: could not save spectrum settings: {e}")

    def load_last_spectrum_settings(self):
        try:
            path = self._get_last_spectrum_settings_path()
            if not path.exists():
                return
            with path.open('r', encoding='utf-8') as f:
                payload = json.load(f)
            loaded_settings = payload.get('spectrum_settings', payload)
            self._apply_spectrum_settings(loaded_settings)
            filter_settings = loaded_settings.get('filter_settings')
            if filter_settings:
                self.apply_filter_settings(filter_settings, reprocess_existing=False)
            self.log_status(f"Loaded spectrum settings: {path}")
        except Exception as e:
            self.log_status(f"Warning: could not load spectrum settings: {e}")

    def _connect_spectrum_settings_autosave(self):
        controls = [
            self.spectrum_window_ms_spin,
            self.spectrum_nfft_combo,
            self.spectrum_window_combo,
            self.spectrum_mode_combo,
            self.spectrum_seg_len_spin,
            self.spectrum_overlap_spin,
            self.spectrum_averaging_combo,
            self.spectrum_ema_alpha_spin,
            self.spectrum_navg_spin,
            self.spectrum_fmin_spin,
            self.spectrum_fmax_spin,
            self.spectrum_band_fmin_spin,
            self.spectrum_band_fmax_spin,
            self.spectrum_y_scale_combo,
            self.spectrum_x_scale_combo,
            self.spectrum_update_rate_spin,
            self.spectrum_remove_dc_check,
            self.spectrum_snap_peak_check,
            self.filter_master_check,
            self.filter_main_type_combo,
            self.filter_order_spin,
            self.filter_low_cutoff_spin,
            self.filter_high_cutoff_spin,
            self.notch1_enable_check,
            self.notch1_freq_spin,
            self.notch1_q_spin,
            self.notch2_enable_check,
            self.notch2_freq_spin,
            self.notch2_q_spin,
            self.notch3_enable_check,
            self.notch3_freq_spin,
            self.notch3_q_spin,
        ]

        for widget in controls:
            if hasattr(widget, 'valueChanged'):
                widget.valueChanged.connect(self.save_last_spectrum_settings)
            elif hasattr(widget, 'currentIndexChanged'):
                widget.currentIndexChanged.connect(self.save_last_spectrum_settings)
            elif hasattr(widget, 'stateChanged'):
                widget.stateChanged.connect(self.save_last_spectrum_settings)

    def create_spectrum_tab(self):
        tab = QWidget()
        root_layout = QVBoxLayout(tab)

        control_group = QGroupBox('Spectrum Controls')
        control_layout = QGridLayout(control_group)

        control_layout.addWidget(QLabel('Window (ms):'), 0, 0)
        self.spectrum_window_preset_combo = QComboBox()
        self.spectrum_window_preset_combo.addItems(['50', '100', '200', '500', '1000'])
        self.spectrum_window_preset_combo.setCurrentText('200')
        self.spectrum_window_preset_combo.currentTextChanged.connect(lambda text: self.spectrum_window_ms_spin.setValue(int(text)))
        control_layout.addWidget(self.spectrum_window_preset_combo, 0, 1)

        self.spectrum_window_ms_spin = QSpinBox()
        self.spectrum_window_ms_spin.setRange(10, 10000)
        self.spectrum_window_ms_spin.setValue(200)
        self.spectrum_window_ms_spin.setSuffix(' ms')
        control_layout.addWidget(self.spectrum_window_ms_spin, 0, 2)

        control_layout.addWidget(QLabel('NFFT:'), 0, 3)
        self.spectrum_nfft_combo = QComboBox()
        self.spectrum_nfft_combo.addItems(['Auto (next power of 2)', '1024', '2048', '4096', '8192', '16384'])
        self.spectrum_nfft_combo.setCurrentIndex(0)
        control_layout.addWidget(self.spectrum_nfft_combo, 0, 4)

        control_layout.addWidget(QLabel('Window Fn:'), 0, 5)
        self.spectrum_window_combo = QComboBox()
        self.spectrum_window_combo.addItems(['Hann', 'Hamming', 'Blackman', 'Rectangular'])
        control_layout.addWidget(self.spectrum_window_combo, 0, 6)

        control_layout.addWidget(QLabel('Mode:'), 1, 0)
        self.spectrum_mode_combo = QComboBox()
        self.spectrum_mode_combo.addItems(['Welch PSD', 'Single FFT'])
        control_layout.addWidget(self.spectrum_mode_combo, 1, 1)

        control_layout.addWidget(QLabel('Segment:'), 1, 2)
        self.spectrum_seg_len_spin = QSpinBox()
        self.spectrum_seg_len_spin.setRange(64, 16384)
        self.spectrum_seg_len_spin.setValue(1024)
        control_layout.addWidget(self.spectrum_seg_len_spin, 1, 3)

        control_layout.addWidget(QLabel('Overlap %:'), 1, 4)
        self.spectrum_overlap_spin = QDoubleSpinBox()
        self.spectrum_overlap_spin.setRange(0.0, 95.0)
        self.spectrum_overlap_spin.setValue(50.0)
        self.spectrum_overlap_spin.setDecimals(1)
        control_layout.addWidget(self.spectrum_overlap_spin, 1, 5)

        control_layout.addWidget(QLabel('Averaging:'), 1, 6)
        self.spectrum_averaging_combo = QComboBox()
        self.spectrum_averaging_combo.addItems(['EMA', 'N-Averages'])
        control_layout.addWidget(self.spectrum_averaging_combo, 1, 7)

        control_layout.addWidget(QLabel('EMA α:'), 2, 0)
        self.spectrum_ema_alpha_spin = QDoubleSpinBox()
        self.spectrum_ema_alpha_spin.setRange(0.01, 1.0)
        self.spectrum_ema_alpha_spin.setDecimals(2)
        self.spectrum_ema_alpha_spin.setSingleStep(0.05)
        self.spectrum_ema_alpha_spin.setValue(0.35)
        control_layout.addWidget(self.spectrum_ema_alpha_spin, 2, 1)

        control_layout.addWidget(QLabel('N Avg:'), 2, 2)
        self.spectrum_navg_spin = QSpinBox()
        self.spectrum_navg_spin.setRange(1, 100)
        self.spectrum_navg_spin.setValue(6)
        control_layout.addWidget(self.spectrum_navg_spin, 2, 3)

        control_layout.addWidget(QLabel('f_min (Hz):'), 2, 4)
        self.spectrum_fmin_spin = QDoubleSpinBox()
        self.spectrum_fmin_spin.setRange(0.0, 1_000_000.0)
        self.spectrum_fmin_spin.setValue(0.0)
        self.spectrum_fmin_spin.setDecimals(2)
        control_layout.addWidget(self.spectrum_fmin_spin, 2, 5)

        control_layout.addWidget(QLabel('f_max (Hz):'), 2, 6)
        self.spectrum_fmax_spin = QDoubleSpinBox()
        self.spectrum_fmax_spin.setRange(1.0, 1_000_000.0)
        self.spectrum_fmax_spin.setValue(2000.0)
        self.spectrum_fmax_spin.setDecimals(2)
        control_layout.addWidget(self.spectrum_fmax_spin, 2, 7)

        control_layout.addWidget(QLabel('Range Preset:'), 3, 0)
        self.spectrum_range_preset_combo = QComboBox()
        self.spectrum_range_preset_combo.addItems(['0-500', '0-2000', '0-10000'])
        self.spectrum_range_preset_combo.currentTextChanged.connect(self._on_spectrum_range_preset_changed)
        self.spectrum_range_preset_combo.setCurrentText('0-2000')
        control_layout.addWidget(self.spectrum_range_preset_combo, 3, 1)

        control_layout.addWidget(QLabel('Band f1 (Hz):'), 3, 2)
        self.spectrum_band_fmin_spin = QDoubleSpinBox()
        self.spectrum_band_fmin_spin.setRange(0.0, 1_000_000.0)
        self.spectrum_band_fmin_spin.setValue(50.0)
        control_layout.addWidget(self.spectrum_band_fmin_spin, 3, 3)

        control_layout.addWidget(QLabel('Band f2 (Hz):'), 3, 4)
        self.spectrum_band_fmax_spin = QDoubleSpinBox()
        self.spectrum_band_fmax_spin.setRange(1.0, 1_000_000.0)
        self.spectrum_band_fmax_spin.setValue(500.0)
        control_layout.addWidget(self.spectrum_band_fmax_spin, 3, 5)

        self.spectrum_y_scale_combo = QComboBox()
        self.spectrum_y_scale_combo.addItems(['dB', 'Linear'])
        control_layout.addWidget(QLabel('Y Scale:'), 3, 6)
        control_layout.addWidget(self.spectrum_y_scale_combo, 3, 7)

        control_layout.addWidget(QLabel('X Scale:'), 4, 0)
        self.spectrum_x_scale_combo = QComboBox()
        self.spectrum_x_scale_combo.addItems(['Linear', 'Log'])
        control_layout.addWidget(self.spectrum_x_scale_combo, 4, 1)

        control_layout.addWidget(QLabel('Update Rate:'), 4, 2)
        self.spectrum_update_rate_spin = QSpinBox()
        self.spectrum_update_rate_spin.setRange(1, 30)
        self.spectrum_update_rate_spin.setValue(10)
        self.spectrum_update_rate_spin.setSuffix(' Hz')
        self.spectrum_update_rate_spin.valueChanged.connect(self.on_spectrum_update_rate_changed)
        control_layout.addWidget(self.spectrum_update_rate_spin, 4, 3)

        self.spectrum_remove_dc_check = QCheckBox('Remove DC')
        self.spectrum_remove_dc_check.setChecked(True)
        control_layout.addWidget(self.spectrum_remove_dc_check, 4, 4)

        self.spectrum_snap_peak_check = QCheckBox('Snap To Peak')
        self.spectrum_snap_peak_check.setChecked(False)
        control_layout.addWidget(self.spectrum_snap_peak_check, 4, 5)

        self.spectrum_export_full_check = QCheckBox('Export Full 0..Fs/2')
        self.spectrum_export_full_check.setChecked(False)
        control_layout.addWidget(self.spectrum_export_full_check, 4, 6)

        self.spectrum_freeze_btn = QPushButton('Freeze/Hold')
        self.spectrum_freeze_btn.setCheckable(True)
        self.spectrum_freeze_btn.toggled.connect(self.on_spectrum_freeze_toggled)
        control_layout.addWidget(self.spectrum_freeze_btn, 5, 0)

        self.spectrum_reset_avg_btn = QPushButton('Reset Averaging')
        self.spectrum_reset_avg_btn.clicked.connect(self.reset_spectrum_averaging)
        control_layout.addWidget(self.spectrum_reset_avg_btn, 5, 1)

        self.spectrum_export_btn = QPushButton('Export Spectrum CSV')
        self.spectrum_export_btn.clicked.connect(self.export_spectrum_csv)
        control_layout.addWidget(self.spectrum_export_btn, 5, 2)

        self.spectrum_save_png_btn = QPushButton('Save Spectrum PNG')
        self.spectrum_save_png_btn.clicked.connect(self.save_spectrum_image)
        control_layout.addWidget(self.spectrum_save_png_btn, 5, 3)

        channel_toggle_layout = QHBoxLayout()
        channel_toggle_layout.addWidget(QLabel('Channels:'))
        self.spectrum_channel_checks = []
        for index in range(5):
            check = QCheckBox(f'Ch{index + 1}')
            check.setChecked(True)
            self.spectrum_channel_checks.append(check)
            channel_toggle_layout.addWidget(check)
        channel_toggle_layout.addStretch()
        control_layout.addLayout(channel_toggle_layout, 5, 4, 1, 4)

        root_layout.addWidget(control_group)

        filter_group = QGroupBox('Filtering')
        filter_layout = QGridLayout(filter_group)

        self.filter_master_check = QCheckBox('Filtering ON')
        self.filter_master_check.setChecked(FILTER_DEFAULT_ENABLED)
        filter_layout.addWidget(self.filter_master_check, 0, 0)

        filter_layout.addWidget(QLabel('Main filter:'), 0, 1)
        self.filter_main_type_combo = QComboBox()
        self.filter_main_type_combo.addItems(['None', 'Low-pass', 'High-pass', 'Band-pass'])
        default_main_text = {
            'none': 'None',
            'lowpass': 'Low-pass',
            'highpass': 'High-pass',
            'bandpass': 'Band-pass',
        }.get(FILTER_DEFAULT_MAIN_TYPE, 'None')
        self.filter_main_type_combo.setCurrentText(default_main_text)
        filter_layout.addWidget(self.filter_main_type_combo, 0, 2)

        filter_layout.addWidget(QLabel('Order:'), 0, 3)
        self.filter_order_spin = QSpinBox()
        self.filter_order_spin.setRange(1, 8)
        self.filter_order_spin.setValue(FILTER_DEFAULT_ORDER)
        filter_layout.addWidget(self.filter_order_spin, 0, 4)

        filter_layout.addWidget(QLabel('Low cutoff (Hz):'), 0, 5)
        self.filter_low_cutoff_spin = QDoubleSpinBox()
        self.filter_low_cutoff_spin.setRange(0.01, 1_000_000.0)
        self.filter_low_cutoff_spin.setDecimals(2)
        self.filter_low_cutoff_spin.setValue(FILTER_DEFAULT_LOW_CUTOFF_HZ)
        filter_layout.addWidget(self.filter_low_cutoff_spin, 0, 6)

        filter_layout.addWidget(QLabel('High cutoff (Hz):'), 0, 7)
        self.filter_high_cutoff_spin = QDoubleSpinBox()
        self.filter_high_cutoff_spin.setRange(0.01, 1_000_000.0)
        self.filter_high_cutoff_spin.setDecimals(2)
        self.filter_high_cutoff_spin.setValue(FILTER_DEFAULT_HIGH_CUTOFF_HZ)
        filter_layout.addWidget(self.filter_high_cutoff_spin, 0, 8)

        self.notch1_enable_check = QCheckBox('Notch1')
        self.notch1_enable_check.setChecked(FILTER_NOTCH1_DEFAULT_ENABLED)
        filter_layout.addWidget(self.notch1_enable_check, 1, 0)
        self.notch1_freq_spin = QDoubleSpinBox()
        self.notch1_freq_spin.setRange(1.0, 1_000_000.0)
        self.notch1_freq_spin.setDecimals(2)
        self.notch1_freq_spin.setValue(FILTER_NOTCH1_DEFAULT_FREQ_HZ)
        filter_layout.addWidget(self.notch1_freq_spin, 1, 1)
        self.notch1_q_spin = QDoubleSpinBox()
        self.notch1_q_spin.setRange(0.1, 200.0)
        self.notch1_q_spin.setDecimals(2)
        self.notch1_q_spin.setValue(FILTER_NOTCH1_DEFAULT_Q)
        filter_layout.addWidget(self.notch1_q_spin, 1, 2)

        self.notch2_enable_check = QCheckBox('Notch2')
        self.notch2_enable_check.setChecked(FILTER_NOTCH2_DEFAULT_ENABLED)
        filter_layout.addWidget(self.notch2_enable_check, 1, 3)
        self.notch2_freq_spin = QDoubleSpinBox()
        self.notch2_freq_spin.setRange(1.0, 1_000_000.0)
        self.notch2_freq_spin.setDecimals(2)
        self.notch2_freq_spin.setValue(FILTER_NOTCH2_DEFAULT_FREQ_HZ)
        filter_layout.addWidget(self.notch2_freq_spin, 1, 4)
        self.notch2_q_spin = QDoubleSpinBox()
        self.notch2_q_spin.setRange(0.1, 200.0)
        self.notch2_q_spin.setDecimals(2)
        self.notch2_q_spin.setValue(FILTER_NOTCH2_DEFAULT_Q)
        filter_layout.addWidget(self.notch2_q_spin, 1, 5)

        self.notch3_enable_check = QCheckBox('Notch3')
        self.notch3_enable_check.setChecked(FILTER_NOTCH3_DEFAULT_ENABLED)
        filter_layout.addWidget(self.notch3_enable_check, 1, 6)
        self.notch3_freq_spin = QDoubleSpinBox()
        self.notch3_freq_spin.setRange(1.0, 1_000_000.0)
        self.notch3_freq_spin.setDecimals(2)
        self.notch3_freq_spin.setValue(FILTER_NOTCH3_DEFAULT_FREQ_HZ)
        filter_layout.addWidget(self.notch3_freq_spin, 1, 7)
        self.notch3_q_spin = QDoubleSpinBox()
        self.notch3_q_spin.setRange(0.1, 200.0)
        self.notch3_q_spin.setDecimals(2)
        self.notch3_q_spin.setValue(FILTER_NOTCH3_DEFAULT_Q)
        filter_layout.addWidget(self.notch3_q_spin, 1, 8)

        self.filter_apply_btn = QPushButton('Apply Filter')
        self.filter_apply_btn.clicked.connect(self.on_apply_filter_clicked)
        filter_layout.addWidget(self.filter_apply_btn, 2, 0)

        self.filter_reset_btn = QPushButton('Reset Filter Defaults')
        self.filter_reset_btn.clicked.connect(self.on_reset_filter_defaults_clicked)
        filter_layout.addWidget(self.filter_reset_btn, 2, 1, 1, 3)

        root_layout.addWidget(filter_group)

        plot_group = QGroupBox('Spectrum Display')
        plot_layout = QVBoxLayout(plot_group)

        self.spectrum_plot_widget = pg.PlotWidget()
        self.spectrum_plot_widget.setBackground('w')
        self.spectrum_plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.spectrum_plot_widget.setLabel('left', 'PSD', units='')
        self.spectrum_plot_widget.setLabel('bottom', 'Frequency', units='Hz')
        self.spectrum_plot_widget.addLegend(offset=(10, 10))

        self.spectrum_curves = {}
        self.spectrum_plot_item = self.spectrum_plot_widget.getPlotItem()

        self.spectrum_vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen((120, 120, 120), width=1))
        self.spectrum_hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen((120, 120, 120), width=1))
        self.spectrum_plot_item.addItem(self.spectrum_vline, ignoreBounds=True)
        self.spectrum_plot_item.addItem(self.spectrum_hline, ignoreBounds=True)

        self.spectrum_marker_points = [None, None]
        self.spectrum_marker_items = [
            pg.ScatterPlotItem([0], [0], symbol='o', size=10, brush=pg.mkBrush(255, 0, 0, 180)),
            pg.ScatterPlotItem([0], [0], symbol='o', size=10, brush=pg.mkBrush(0, 0, 255, 180)),
        ]
        self.spectrum_marker_labels = [
            pg.TextItem('M1', color=(160, 0, 0)),
            pg.TextItem('M2', color=(0, 0, 160)),
        ]

        for marker_item, marker_label in zip(self.spectrum_marker_items, self.spectrum_marker_labels):
            marker_item.setVisible(False)
            marker_label.setVisible(False)
            self.spectrum_plot_item.addItem(marker_item)
            self.spectrum_plot_item.addItem(marker_label)

        self._next_marker_index = 0

        self.spectrum_mouse_proxy = pg.SignalProxy(
            self.spectrum_plot_widget.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_spectrum_mouse_moved,
        )
        self.spectrum_plot_widget.scene().sigMouseClicked.connect(self._on_spectrum_mouse_clicked)

        plot_layout.addWidget(self.spectrum_plot_widget)

        self.spectrum_status_label = QLabel('Waiting for data...')
        self.spectrum_status_label.setStyleSheet('color: #cc0000; font-weight: bold;')
        plot_layout.addWidget(self.spectrum_status_label)

        self.spectrum_cursor_readout_label = QLabel('Cursor: -')
        self.spectrum_marker_readout_label = QLabel('Markers: -')
        plot_layout.addWidget(self.spectrum_cursor_readout_label)
        plot_layout.addWidget(self.spectrum_marker_readout_label)

        self.spectrum_global_info_label = QLabel('Window: - | Δf: - | Range: - | Fs(ch): -')
        plot_layout.addWidget(self.spectrum_global_info_label)

        self.spectrum_channel_stats = []
        for i in range(5):
            label = QLabel(f'Ch{i + 1}: peak -, band RMS -, noise floor -')
            label.setStyleSheet('font-family: monospace;')
            self.spectrum_channel_stats.append(label)
            plot_layout.addWidget(label)

        root_layout.addWidget(plot_group)

        self.spectrum_mode_combo.currentTextChanged.connect(self._on_spectrum_mode_changed)
        self._on_spectrum_mode_changed(self.spectrum_mode_combo.currentText())
        self._apply_filter_widgets(self.get_default_filter_settings())
        self._connect_spectrum_settings_autosave()

        return tab

    def _on_spectrum_range_preset_changed(self, text):
        if text == '0-500':
            self.spectrum_fmin_spin.setValue(0.0)
            self.spectrum_fmax_spin.setValue(500.0)
        elif text == '0-2000':
            self.spectrum_fmin_spin.setValue(0.0)
            self.spectrum_fmax_spin.setValue(2000.0)
        elif text == '0-10000':
            self.spectrum_fmin_spin.setValue(0.0)
            self.spectrum_fmax_spin.setValue(10000.0)

    def _on_spectrum_mode_changed(self, mode_text):
        welch_mode = mode_text == 'Welch PSD'
        self.spectrum_seg_len_spin.setEnabled(welch_mode)
        self.spectrum_overlap_spin.setEnabled(welch_mode)
        self.spectrum_averaging_combo.setEnabled(welch_mode)
        self.spectrum_ema_alpha_spin.setEnabled(welch_mode)
        self.spectrum_navg_spin.setEnabled(welch_mode)

    def on_spectrum_update_rate_changed(self, update_rate_hz):
        if hasattr(self, 'spectrum_timer'):
            update_rate_hz = max(1, int(update_rate_hz))
            self.spectrum_timer.setInterval(int(1000 / update_rate_hz))

    def on_spectrum_freeze_toggled(self, checked):
        self.spectrum_frozen = checked
        if checked:
            self.spectrum_freeze_btn.setText('Resume')
        else:
            self.spectrum_freeze_btn.setText('Freeze/Hold')

    def _filter_main_type_to_code(self, text: str) -> str:
        mapping = {
            'None': 'none',
            'Low-pass': 'lowpass',
            'High-pass': 'highpass',
            'Band-pass': 'bandpass',
        }
        return mapping.get(text, 'none')

    def _filter_main_code_to_text(self, code: str) -> str:
        mapping = {
            'none': 'None',
            'lowpass': 'Low-pass',
            'highpass': 'High-pass',
            'bandpass': 'Band-pass',
        }
        return mapping.get(code, 'None')

    def get_filter_settings_from_ui(self) -> dict:
        return {
            'enabled': bool(self.filter_master_check.isChecked()),
            'main_type': self._filter_main_type_to_code(self.filter_main_type_combo.currentText()),
            'order': int(self.filter_order_spin.value()),
            'low_cutoff_hz': float(self.filter_low_cutoff_spin.value()),
            'high_cutoff_hz': float(self.filter_high_cutoff_spin.value()),
            'notches': [
                {
                    'enabled': bool(self.notch1_enable_check.isChecked()),
                    'freq_hz': float(self.notch1_freq_spin.value()),
                    'q': float(self.notch1_q_spin.value()),
                },
                {
                    'enabled': bool(self.notch2_enable_check.isChecked()),
                    'freq_hz': float(self.notch2_freq_spin.value()),
                    'q': float(self.notch2_q_spin.value()),
                },
                {
                    'enabled': bool(self.notch3_enable_check.isChecked()),
                    'freq_hz': float(self.notch3_freq_spin.value()),
                    'q': float(self.notch3_q_spin.value()),
                },
            ],
        }

    def _apply_filter_widgets(self, settings: dict):
        self.filter_master_check.setChecked(bool(settings.get('enabled', FILTER_DEFAULT_ENABLED)))
        self.filter_main_type_combo.setCurrentText(self._filter_main_code_to_text(settings.get('main_type', FILTER_DEFAULT_MAIN_TYPE)))
        self.filter_order_spin.setValue(int(settings.get('order', FILTER_DEFAULT_ORDER)))
        self.filter_low_cutoff_spin.setValue(float(settings.get('low_cutoff_hz', FILTER_DEFAULT_LOW_CUTOFF_HZ)))
        self.filter_high_cutoff_spin.setValue(float(settings.get('high_cutoff_hz', FILTER_DEFAULT_HIGH_CUTOFF_HZ)))

        notches = settings.get('notches', [])
        while len(notches) < 3:
            notches.append({'enabled': False, 'freq_hz': 60.0, 'q': 30.0})

        self.notch1_enable_check.setChecked(bool(notches[0].get('enabled', FILTER_NOTCH1_DEFAULT_ENABLED)))
        self.notch1_freq_spin.setValue(float(notches[0].get('freq_hz', FILTER_NOTCH1_DEFAULT_FREQ_HZ)))
        self.notch1_q_spin.setValue(float(notches[0].get('q', FILTER_NOTCH1_DEFAULT_Q)))

        self.notch2_enable_check.setChecked(bool(notches[1].get('enabled', FILTER_NOTCH2_DEFAULT_ENABLED)))
        self.notch2_freq_spin.setValue(float(notches[1].get('freq_hz', FILTER_NOTCH2_DEFAULT_FREQ_HZ)))
        self.notch2_q_spin.setValue(float(notches[1].get('q', FILTER_NOTCH2_DEFAULT_Q)))

        self.notch3_enable_check.setChecked(bool(notches[2].get('enabled', FILTER_NOTCH3_DEFAULT_ENABLED)))
        self.notch3_freq_spin.setValue(float(notches[2].get('freq_hz', FILTER_NOTCH3_DEFAULT_FREQ_HZ)))
        self.notch3_q_spin.setValue(float(notches[2].get('q', FILTER_NOTCH3_DEFAULT_Q)))

    def on_apply_filter_clicked(self):
        settings = self.get_filter_settings_from_ui()
        success, error = self.apply_filter_settings(settings, reprocess_existing=True)
        if success:
            state = 'ON' if settings.get('enabled') else 'OFF'
            self.log_status(f'Filtering applied ({state})')
            self.trigger_plot_update()
            self.update_spectrum()
        else:
            self.log_status(f'Filter apply failed: {error}')
            QMessageBox.warning(self, 'Filter Error', error)

    def on_reset_filter_defaults_clicked(self):
        defaults = self.get_default_filter_settings()
        self._apply_filter_widgets(defaults)
        self.on_apply_filter_clicked()

    def get_spectrum_settings(self):
        nfft_text = self.spectrum_nfft_combo.currentText()
        if 'Auto' in nfft_text:
            nfft_mode = 'auto'
            nfft_value = 0
        else:
            nfft_mode = 'fixed'
            nfft_value = int(nfft_text)

        mode = 'welch' if self.spectrum_mode_combo.currentText() == 'Welch PSD' else 'fft'

        window_map = {
            'Hann': 'hann',
            'Hamming': 'hamming',
            'Blackman': 'blackman',
            'Rectangular': 'rectangular',
        }

        averaging_mode = 'ema' if self.spectrum_averaging_combo.currentText() == 'EMA' else 'navg'

        return {
            'window_ms': int(self.spectrum_window_ms_spin.value()),
            'nfft_mode': nfft_mode,
            'nfft_value': nfft_value,
            'window': window_map[self.spectrum_window_combo.currentText()],
            'mode': mode,
            'welch_segment': int(self.spectrum_seg_len_spin.value()),
            'welch_overlap': float(self.spectrum_overlap_spin.value()),
            'averaging_mode': averaging_mode,
            'ema_alpha': float(self.spectrum_ema_alpha_spin.value()),
            'n_avg': int(self.spectrum_navg_spin.value()),
            'f_min': float(self.spectrum_fmin_spin.value()),
            'f_max': float(self.spectrum_fmax_spin.value()),
            'band_f1': float(self.spectrum_band_fmin_spin.value()),
            'band_f2': float(self.spectrum_band_fmax_spin.value()),
            'y_scale': 'db' if self.spectrum_y_scale_combo.currentText() == 'dB' else 'linear',
            'x_scale': 'log' if self.spectrum_x_scale_combo.currentText() == 'Log' else 'linear',
            'update_rate_hz': int(self.spectrum_update_rate_spin.value()),
            'remove_dc': bool(self.spectrum_remove_dc_check.isChecked()),
            'snap_to_peak': bool(self.spectrum_snap_peak_check.isChecked()),
            'filter_settings': self.get_filter_settings_from_ui(),
        }

    def show_spectrum_status(self, message):
        self.spectrum_status_label.setText(message)
        self.spectrum_status_label.setVisible(True)
        if getattr(self, '_last_spectrum_status_message', None) != message:
            self._last_spectrum_status_message = message
            self.log_status(f"Spectrum: {message}")

    def hide_spectrum_status(self):
        self.spectrum_status_label.setVisible(False)

    def _to_db(self, linear_vals, mode):
        if mode == 'welch':
            return 10.0 * np.log10(np.maximum(linear_vals, 1e-20))
        return 20.0 * np.log10(np.maximum(linear_vals, 1e-12))

    def update_spectrum_display(self, result):
        settings = self.get_spectrum_settings()
        freqs = np.asarray(result['freqs_hz'])
        mode = result['mode']

        f_min = max(0.0, settings['f_min'])
        f_max = max(f_min + 1.0, settings['f_max'])
        if freqs.size == 0:
            self.show_spectrum_status('No spectrum bins available.')
            return

        display_mask = (freqs >= f_min) & (freqs <= f_max)
        if not np.any(display_mask):
            display_mask = np.ones_like(freqs, dtype=bool)

        freqs_show = freqs[display_mask]

        self.spectrum_display_cache = {
            'freqs_hz': freqs,
            'freqs_show_hz': freqs_show,
            'mode': mode,
            'channels': [],
            'settings': settings,
        }

        self.spectrum_plot_item.setLogMode(x=(settings['x_scale'] == 'log'), y=False)
        self.spectrum_plot_widget.setXRange(float(freqs_show[0]), float(freqs_show[-1]), padding=0.01)

        if settings['y_scale'] == 'db':
            self.spectrum_plot_widget.setLabel('left', 'Magnitude / PSD', units='dB')
        else:
            y_units = 'counts^2/Hz' if mode == 'welch' else 'counts'
            self.spectrum_plot_widget.setLabel('left', 'Magnitude / PSD', units=y_units)
        self.spectrum_plot_widget.setLabel('bottom', 'Frequency', units='Hz')

        band_f1 = min(settings['band_f1'], settings['band_f2'])
        band_f2 = max(settings['band_f1'], settings['band_f2'])

        visible_curve_count = 0
        per_channel_info = []

        for index, channel_entry in enumerate(result['channels']):
            label = channel_entry['label']
            linear = np.asarray(channel_entry['linear'])
            display_linear = linear[display_mask]
            display_db = self._to_db(display_linear, mode)
            y_plot = display_db if settings['y_scale'] == 'db' else display_linear

            if label not in self.spectrum_curves:
                color = PLOT_COLORS[index % len(PLOT_COLORS)]
                curve = self.spectrum_plot_widget.plot([], [], pen=pg.mkPen(color=color, width=2), name=label)
                self.spectrum_curves[label] = curve

            show_curve = index < len(self.spectrum_channel_checks) and self.spectrum_channel_checks[index].isChecked()
            self.spectrum_curves[label].setVisible(show_curve)
            if show_curve:
                self.spectrum_curves[label].setData(freqs_show, y_plot)
                visible_curve_count += 1

            self.spectrum_display_cache['channels'].append({
                'label': label,
                'linear_full': linear,
                'linear_show': display_linear,
                'db_show': display_db,
                'y_show': y_plot,
            })

            # Stats on displayed range, ignoring DC bin for peak
            peak_mask = freqs_show > 0.0
            if np.any(peak_mask):
                peak_idx = np.argmax(y_plot[peak_mask])
                peak_freq = float(freqs_show[peak_mask][peak_idx])
                peak_mag = float(y_plot[peak_mask][peak_idx])
            else:
                peak_freq = 0.0
                peak_mag = 0.0

            band_mask = (freqs_show >= band_f1) & (freqs_show <= band_f2)
            if np.any(band_mask):
                if mode == 'welch':
                    band_power = float(np.trapz(display_linear[band_mask], freqs_show[band_mask]))
                    band_rms = float(np.sqrt(max(band_power, 0.0)))
                else:
                    band_rms = float(np.sqrt(np.mean(display_linear[band_mask] ** 2)))
                noise_floor_linear = float(np.median(display_linear[band_mask]))
                noise_floor_display = float(np.median(y_plot[band_mask]))
            else:
                band_rms = 0.0
                noise_floor_linear = 0.0
                noise_floor_display = 0.0

            per_channel_info.append({
                'label': label,
                'fs_hz': float(channel_entry.get('fs_hz', 0.0)),
                'peak_freq': peak_freq,
                'peak_mag': peak_mag,
                'band_rms': band_rms,
                'noise_floor_linear': noise_floor_linear,
                'noise_floor_display': noise_floor_display,
            })

        # Hide stale curves
        current_labels = {entry['label'] for entry in result['channels']}
        for label, curve in self.spectrum_curves.items():
            if label not in current_labels:
                curve.setVisible(False)

        nfft_used = max([entry['nfft'] for entry in result['channels']]) if result['channels'] else 0
        fs_ref = max([entry['fs_hz'] for entry in result['channels']]) if result['channels'] else 0.0
        df = (fs_ref / nfft_used) if (fs_ref > 0 and nfft_used > 0) else 0.0
        effective_window_samples = result.get('window_samples_effective', 0)
        effective_window_sec = (effective_window_samples / fs_ref) if fs_ref > 0 else 0.0

        fs_summary = ', '.join([
            f"{info['label']}={info['fs_hz']:.1f}Hz"
            for info in per_channel_info
        ]) if per_channel_info else '-'

        self.spectrum_global_info_label.setText(
            f"Window: {effective_window_samples} samples ({effective_window_sec:.4f} s) | Δf: {df:.3f} Hz | Range: {f_min:.1f}-{f_max:.1f} Hz | Fs(ch): {fs_summary}"
        )

        for idx, info in enumerate(per_channel_info[:5]):
            self.spectrum_channel_stats[idx].setText(
                f"{info['label']} (Fs={info['fs_hz']:.1f} Hz): peak {info['peak_freq']:.2f} Hz @ {info['peak_mag']:.3f} | "
                f"band RMS {info['band_rms']:.5f} | noise floor {info['noise_floor_display']:.3f}"
            )

        for idx in range(len(per_channel_info), 5):
            self.spectrum_channel_stats[idx].setText(f"Ch{idx + 1}: -")

        if visible_curve_count == 0:
            self.show_spectrum_status('All channel traces are hidden.')
        else:
            self.hide_spectrum_status()

    def _get_reference_series_for_cursor(self):
        if not hasattr(self, 'spectrum_display_cache'):
            return None, None

        channels = self.spectrum_display_cache.get('channels', [])
        for idx, entry in enumerate(channels):
            if idx < len(self.spectrum_channel_checks) and self.spectrum_channel_checks[idx].isChecked():
                return self.spectrum_display_cache['freqs_show_hz'], entry['y_show']
        return None, None

    def _on_spectrum_mouse_moved(self, evt):
        if not hasattr(self, 'spectrum_display_cache'):
            return

        pos = evt[0]
        if not self.spectrum_plot_widget.sceneBoundingRect().contains(pos):
            return

        mouse_point = self.spectrum_plot_widget.plotItem.vb.mapSceneToView(pos)
        x = float(mouse_point.x())
        y = float(mouse_point.y())

        self.spectrum_vline.setPos(x)
        self.spectrum_hline.setPos(y)

        freqs_full, y_ref = self._get_reference_series_for_cursor()
        if freqs_full is None or y_ref is None:
            return

        freqs_show = self.spectrum_display_cache['freqs_show_hz']
        idx = int(np.argmin(np.abs(freqs_show - x)))
        freq_val = float(freqs_show[idx])
        amp_val = float(y_ref[idx]) if idx < len(y_ref) else 0.0

        self.spectrum_cursor_readout_label.setText(f"Cursor: f={freq_val:.3f} Hz, y={amp_val:.6f}")

    def _find_marker_point(self, target_freq):
        freqs_show, y_ref = self._get_reference_series_for_cursor()
        if freqs_show is None or y_ref is None or len(freqs_show) == 0:
            return None

        idx = int(np.argmin(np.abs(freqs_show - target_freq)))

        if self.spectrum_snap_peak_check.isChecked():
            left = max(1, idx - 10)
            right = min(len(y_ref) - 1, idx + 10)
            local = y_ref[left:right + 1]
            if local.size > 0:
                idx = left + int(np.argmax(local))

        return float(freqs_show[idx]), float(y_ref[idx])

    def _on_spectrum_mouse_clicked(self, event):
        if not hasattr(self, 'spectrum_display_cache'):
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        scene_pos = event.scenePos()
        if not self.spectrum_plot_widget.sceneBoundingRect().contains(scene_pos):
            return

        mouse_point = self.spectrum_plot_widget.plotItem.vb.mapSceneToView(scene_pos)
        point = self._find_marker_point(float(mouse_point.x()))
        if point is None:
            return

        marker_index = self._next_marker_index
        self._next_marker_index = (self._next_marker_index + 1) % 2
        self.spectrum_marker_points[marker_index] = point

        for idx, marker in enumerate(self.spectrum_marker_points):
            if marker is None:
                self.spectrum_marker_items[idx].setVisible(False)
                self.spectrum_marker_labels[idx].setVisible(False)
                continue

            fx, fy = marker
            self.spectrum_marker_items[idx].setData([fx], [fy])
            self.spectrum_marker_items[idx].setVisible(True)

            self.spectrum_marker_labels[idx].setText(f"M{idx + 1}: {fx:.2f} Hz")
            self.spectrum_marker_labels[idx].setPos(fx, fy)
            self.spectrum_marker_labels[idx].setVisible(True)

        m1 = self.spectrum_marker_points[0]
        m2 = self.spectrum_marker_points[1]
        if m1 and m2:
            self.spectrum_marker_readout_label.setText(
                f"Markers: M1={m1[0]:.3f} Hz, M2={m2[0]:.3f} Hz, Δf={abs(m2[0] - m1[0]):.3f} Hz"
            )
        elif m1:
            self.spectrum_marker_readout_label.setText(f"Markers: M1={m1[0]:.3f} Hz")
        elif m2:
            self.spectrum_marker_readout_label.setText(f"Markers: M2={m2[0]:.3f} Hz")
        else:
            self.spectrum_marker_readout_label.setText('Markers: -')

    def _build_spectrum_export_rows(self):
        if not self.latest_spectrum_result or self.latest_spectrum_result.get('status') != 'ok':
            return None, None, None

        result = self.latest_spectrum_result
        settings = self.get_spectrum_settings()
        mode = result['mode']
        freqs = np.asarray(result['freqs_hz'])

        if self.spectrum_export_full_check.isChecked():
            mask = np.ones_like(freqs, dtype=bool)
        else:
            f_min = max(0.0, settings['f_min'])
            f_max = max(f_min + 1.0, settings['f_max'])
            mask = (freqs >= f_min) & (freqs <= f_max)

        if not np.any(mask):
            return None, None, None

        export_freqs = freqs[mask]
        channels = result['channels']

        rows = []
        for idx, f in enumerate(export_freqs):
            row = [float(f)]
            for ch in channels:
                linear = np.asarray(ch['linear'])[mask]
                db_vals = self._to_db(linear, mode)
                row.extend([float(linear[idx]), float(db_vals[idx])])
            rows.append(row)

        headers = ['freq_hz']
        for ch in channels:
            headers.append(f"{ch['label'].replace(' ', '_').lower()}_linear")
            headers.append(f"{ch['label'].replace(' ', '_').lower()}_db")

        metadata = {
            'timestamp_iso': datetime.now().isoformat(timespec='seconds'),
            'fs_hz': max([float(c['fs_hz']) for c in channels]) if channels else 0.0,
            'mode': mode,
            'window_function': result.get('window', settings['window']),
            'window_length_samples': result.get('window_samples_effective', 0),
            'window_length_sec': (
                float(result.get('window_samples_effective', 0)) /
                max([float(c['fs_hz']) for c in channels])
            ) if channels and max([float(c['fs_hz']) for c in channels]) > 0 else 0.0,
            'nfft': max([int(c['nfft']) for c in channels]) if channels else 0,
            'df_hz': (
                max([float(c['fs_hz']) for c in channels]) / max([int(c['nfft']) for c in channels])
            ) if channels and max([int(c['nfft']) for c in channels]) > 0 else 0.0,
            'welch_segment_length': result.get('welch_segment', settings['welch_segment']),
            'welch_overlap_percent': result.get('welch_overlap', settings['welch_overlap']),
            'averaging': settings['averaging_mode'],
            'avg_param': settings['ema_alpha'] if settings['averaging_mode'] == 'ema' else settings['n_avg'],
            'freq_range_display_hz': f"{settings['f_min']}..{settings['f_max']}",
            'y_scale': settings['y_scale'],
            'x_scale': settings['x_scale'],
            'channel_labels': ','.join([c['label'] for c in channels]),
            'units': 'counts^2/Hz' if mode == 'welch' else 'counts',
            'display_transform': 'db transform shown; linear values exported explicitly',
        }

        return headers, rows, metadata

    def export_spectrum_csv(self):
        headers, rows, metadata = self._build_spectrum_export_rows()
        if not headers or not rows:
            QMessageBox.warning(self, 'Spectrum Export', 'No spectrum data to export.')
            return

        directory = Path(self.dir_input.text())
        filename = self.filename_input.text().strip() or 'spectrum'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        fs_hz = int(metadata.get('fs_hz', 0))
        nfft = int(metadata.get('nfft', 0))
        mode = metadata.get('mode', 'welch')
        csv_path = directory / f"{filename}_spectrum_{timestamp}_fs{fs_hz}_nfft{nfft}_{mode}.csv"

        try:
            directory.mkdir(parents=True, exist_ok=True)
            with csv_path.open('w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                for key, value in metadata.items():
                    writer.writerow([f"# {key}={value}"])
                writer.writerow(headers)
                writer.writerows(rows)

            self.log_status(f"Spectrum CSV exported: {csv_path}")
            QMessageBox.information(self, 'Export Successful', f'Spectrum CSV saved:\n{csv_path}')
        except Exception as e:
            self.log_status(f"ERROR: failed to export spectrum CSV - {e}")
            QMessageBox.critical(self, 'Export Error', f'Failed to export spectrum CSV:\n{e}')

    def save_spectrum_image(self):
        if not self.latest_spectrum_result or self.latest_spectrum_result.get('status') != 'ok':
            QMessageBox.warning(self, 'No Data', 'No spectrum to save.')
            return

        directory = Path(self.dir_input.text())
        filename = self.filename_input.text().strip() or 'spectrum'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        image_path = directory / f"{filename}_spectrum_{timestamp}.png"

        try:
            directory.mkdir(parents=True, exist_ok=True)
            exporter = ImageExporter(self.spectrum_plot_widget.plotItem)
            exporter.parameters()['width'] = PLOT_EXPORT_WIDTH
            exporter.export(str(image_path))

            self.log_status(f"Spectrum image saved: {image_path}")
            QMessageBox.information(self, 'Save Successful', f'Spectrum image saved:\n{image_path}')
        except Exception as e:
            self.log_status(f"ERROR: failed to save spectrum PNG - {e}")
            QMessageBox.critical(self, 'Save Error', f'Failed to save spectrum image:\n{e}')
