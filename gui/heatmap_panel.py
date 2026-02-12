"""
Heatmap Panel GUI Component
============================
Provides UI components for real-time 2D heatmap visualization.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QFileDialog
)
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import numpy as np
import json
from pathlib import Path

from config_constants import (
    HEATMAP_WIDTH, HEATMAP_HEIGHT, SENSOR_CALIBRATION, SENSOR_SIZE,
    INTENSITY_SCALE, BLOB_SIGMA_X, BLOB_SIGMA_Y, SMOOTH_ALPHA,
    RMS_WINDOW_MS, SENSOR_NOISE_FLOOR, HEATMAP_DC_REMOVAL_MODE,
    HPF_CUTOFF_HZ, HEATMAP_CHANNEL_SENSOR_MAP, HEATMAP_THRESHOLD,
    CONFIDENCE_INTENSITY_REF, SIGMA_SPREAD_FACTOR
)


class HeatmapPanelMixin:
    """Mixin providing heatmap visualization panel components."""

    def _get_last_heatmap_settings_path(self):
        return Path.home() / ".adc_streamer" / "heatmap" / "last_used_heatmap_settings.json"

    def _serialize_heatmap_settings(self):
        return {
            'version': 1,
            'heatmap_settings': self.get_heatmap_settings(),
        }

    def _apply_heatmap_settings(self, settings):
        if not settings:
            return False

        changed = False

        if 'sensor_calibration' in settings and isinstance(settings['sensor_calibration'], list):
            for spin, value in zip(self.sensor_gain_spins, settings['sensor_calibration']):
                spin.setValue(float(value))
                changed = True

        if 'sensor_noise_floor' in settings and isinstance(settings['sensor_noise_floor'], list):
            for spin, value in zip(self.sensor_noise_spins, settings['sensor_noise_floor']):
                spin.setValue(float(value))
                changed = True

        scalar_map = [
            ('sensor_size', self.sensor_size_spin),
            ('intensity_scale', self.intensity_scale_spin),
            ('blob_sigma_x', self.blob_sigma_x_spin),
            ('blob_sigma_y', self.blob_sigma_y_spin),
            ('smooth_alpha', self.smooth_alpha_spin),
            ('hpf_cutoff_hz', self.hpf_cutoff_spin),
            ('magnitude_threshold', self.magnitude_threshold_spin),
        ]

        for key, widget in scalar_map:
            if key in settings:
                widget.setValue(float(settings[key]))
                changed = True

        if 'rms_window_ms' in settings:
            self.rms_window_spin.setValue(int(round(float(settings['rms_window_ms']))))
            changed = True

        dc_mode = settings.get('dc_removal_mode')
        if dc_mode == 'bias':
            self.dc_removal_combo.setCurrentIndex(0)
            changed = True
        elif dc_mode == 'highpass':
            self.dc_removal_combo.setCurrentIndex(1)
            changed = True

        return changed

    def save_heatmap_settings_to_path(self, file_path, log_message=True):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._serialize_heatmap_settings()
        with path.open('w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        if log_message:
            self.log_status(f"Saved heatmap settings: {path}")

    def load_heatmap_settings_from_path(self, file_path, log_message=True):
        path = Path(file_path)
        with path.open('r', encoding='utf-8') as f:
            payload = json.load(f)

        settings = payload.get('heatmap_settings', payload)
        applied = self._apply_heatmap_settings(settings)

        if log_message:
            if applied:
                self.log_status(f"Loaded heatmap settings: {path}")
            else:
                self.log_status(f"Heatmap settings file loaded, no applicable fields: {path}")

        return applied

    def save_last_heatmap_settings(self):
        try:
            self.save_heatmap_settings_to_path(self._get_last_heatmap_settings_path(), log_message=False)
        except Exception as e:
            self.log_status(f"Warning: could not save last heatmap settings: {e}")

    def load_last_heatmap_settings(self):
        path = self._get_last_heatmap_settings_path()
        if not path.exists():
            return False

        try:
            return self.load_heatmap_settings_from_path(path, log_message=True)
        except Exception as e:
            self.log_status(f"Warning: could not load last heatmap settings: {e}")
            return False

    def on_save_heatmap_settings_clicked(self):
        default_dir = self._get_last_heatmap_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Heatmap Settings",
            str(default_dir / "heatmap_settings.json"),
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            self.save_heatmap_settings_to_path(file_path, log_message=True)
        except Exception as e:
            self.log_status(f"Error saving heatmap settings: {e}")

    def on_load_heatmap_settings_clicked(self):
        default_dir = self._get_last_heatmap_settings_path().parent
        default_dir.mkdir(parents=True, exist_ok=True)

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Heatmap Settings",
            str(default_dir),
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            self.load_heatmap_settings_from_path(file_path, log_message=True)
            self.save_last_heatmap_settings()
        except Exception as e:
            self.log_status(f"Error loading heatmap settings: {e}")

    def _connect_heatmap_settings_autosave(self):
        self.rms_window_spin.valueChanged.connect(self.save_last_heatmap_settings)
        self.dc_removal_combo.currentIndexChanged.connect(self.save_last_heatmap_settings)
        self.hpf_cutoff_spin.valueChanged.connect(self.save_last_heatmap_settings)
        self.magnitude_threshold_spin.valueChanged.connect(self.save_last_heatmap_settings)

        for spin in self.sensor_gain_spins:
            spin.valueChanged.connect(self.save_last_heatmap_settings)
        for spin in self.sensor_noise_spins:
            spin.valueChanged.connect(self.save_last_heatmap_settings)

        self.sensor_size_spin.valueChanged.connect(self.save_last_heatmap_settings)
        self.intensity_scale_spin.valueChanged.connect(self.save_last_heatmap_settings)
        self.blob_sigma_x_spin.valueChanged.connect(self.save_last_heatmap_settings)
        self.blob_sigma_y_spin.valueChanged.connect(self.save_last_heatmap_settings)
        self.smooth_alpha_spin.valueChanged.connect(self.save_last_heatmap_settings)
    
    def create_heatmap_tab(self):
        """Create the heatmap visualization tab.
        
        Returns:
            QWidget: Widget containing heatmap display and readouts
        """
        heatmap_widget = QWidget()
        layout = QVBoxLayout()
        
        # Create heatmap display (takes most space)
        heatmap_display = self.create_heatmap_display()
        layout.addWidget(heatmap_display, stretch=5)
        
        # Create readouts panel (compact)
        readouts_panel = self.create_heatmap_readouts()
        layout.addWidget(readouts_panel, stretch=0)

        # Create heatmap settings panel
        settings_panel = self.create_heatmap_settings()
        layout.addWidget(settings_panel, stretch=0)
        
        heatmap_widget.setLayout(layout)
        return heatmap_widget
    
    def create_heatmap_display(self):
        """Create the pyqtgraph heatmap image display.
        
        Returns:
            QGroupBox: Group box containing heatmap plot
        """
        group = QGroupBox("2D Pressure Heatmap")
        layout = QVBoxLayout()
        
        # Create GraphicsLayoutWidget for heatmap
        self.heatmap_plot_widget = pg.GraphicsLayoutWidget()
        self.heatmap_plot = self.heatmap_plot_widget.addPlot()
        
        # Configure plot - lock aspect ratio for square display
        self.heatmap_plot.setAspectLocked(True, ratio=1.0)
        self.heatmap_plot.invertY(True)
        self.heatmap_plot.showAxis('left', False)
        self.heatmap_plot.showAxis('bottom', False)
        self.heatmap_plot.setMouseEnabled(x=False, y=False)
        
        # Create ImageItem for heatmap
        self.heatmap_image = pg.ImageItem()
        self.heatmap_plot.addItem(self.heatmap_image)
        
        # Set colormap (using built-in 'viridis'-like colormap)
        colormap = pg.colormap.get('viridis')
        self.heatmap_image.setColorMap(colormap)
        
        # Add colorbar
        self.heatmap_colorbar = pg.ColorBarItem(
            values=(0, 1),
            colorMap=colormap,
            width=15,
            interactive=False
        )
        self.heatmap_colorbar.setImageItem(self.heatmap_image)
        self.heatmap_plot_widget.addItem(self.heatmap_colorbar)
        
        # Initialize with empty data
        empty_heatmap = np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
        self.heatmap_image.setImage(empty_heatmap, autoLevels=False, levels=(0, 1))

        # Add static background overlay (circle + sensor markers)
        self._add_heatmap_background_overlay()
        
        # Status label for channel warnings
        self.heatmap_status_label = QLabel("")
        self.heatmap_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.heatmap_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(self.heatmap_plot_widget)
        layout.addWidget(self.heatmap_status_label)
        group.setLayout(layout)
        
        return group

    def _add_heatmap_background_overlay(self):
        width = float(HEATMAP_WIDTH)
        height = float(HEATMAP_HEIGHT)
        center_x = (width - 1.0) / 2.0
        center_y = (height - 1.0) / 2.0
        radius = min(width, height) * 0.48

        theta = np.linspace(0, 2 * np.pi, 200)
        circle_x = center_x + radius * np.cos(theta)
        circle_y = center_y + radius * np.sin(theta)
        circle_pen = pg.mkPen((200, 200, 200, 160), width=2)
        self.heatmap_circle = pg.PlotDataItem(circle_x, circle_y, pen=circle_pen)
        self.heatmap_circle.setZValue(5)
        self.heatmap_plot.addItem(self.heatmap_circle)

        label_to_number = {
            sensor_label: str(index + 1)
            for index, sensor_label in enumerate(HEATMAP_CHANNEL_SENSOR_MAP)
        }

        marker_positions = [
            (center_x + radius, center_y, label_to_number.get("R", "")),  # Right
            (center_x, center_y + radius, label_to_number.get("B", "")),  # Bottom
            (center_x, center_y, label_to_number.get("C", "")),          # Center
            (center_x - radius, center_y, label_to_number.get("L", "")),  # Left
            (center_x, center_y - radius, label_to_number.get("T", "")),  # Top
        ]

        marker_brush = pg.mkBrush(230, 230, 230, 200)
        marker_pen = pg.mkPen(120, 120, 120, 200)
        self.heatmap_marker_items = []
        self.heatmap_marker_labels = []

        for x_pos, y_pos, label in marker_positions:
            marker = pg.ScatterPlotItem(
                [x_pos],
                [y_pos],
                symbol='s',
                size=14,
                brush=marker_brush,
                pen=marker_pen,
            )
            marker.setZValue(6)
            self.heatmap_plot.addItem(marker)
            self.heatmap_marker_items.append(marker)

            text = pg.TextItem(label, color=(60, 60, 60))
            text.setAnchor((0.5, 0.5))
            text.setPos(x_pos, y_pos)
            text.setZValue(7)
            self.heatmap_plot.addItem(text)
            self.heatmap_marker_labels.append(text)
    
    def create_heatmap_readouts(self):
        """Create numeric readout displays for CoP and sensor values.
        
        Returns:
            QGroupBox: Group box containing readout labels
        """
        group = QGroupBox("Sensor Readouts")
        layout = QVBoxLayout()
        
        # Center of Pressure readouts
        cop_layout = QHBoxLayout()
        cop_layout.addWidget(QLabel("Center of Pressure:"))
        
        self.cop_x_label = QLabel("X: 0.000")
        self.cop_x_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        cop_layout.addWidget(self.cop_x_label)
        
        self.cop_y_label = QLabel("Y: 0.000")
        self.cop_y_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        cop_layout.addWidget(self.cop_y_label)
        
        cop_layout.addStretch()
        layout.addLayout(cop_layout)
        
        # Intensity readout
        intensity_layout = QHBoxLayout()
        intensity_layout.addWidget(QLabel("Intensity:"))
        
        self.intensity_label = QLabel("0.0")
        self.intensity_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        intensity_layout.addWidget(self.intensity_label)

        intensity_layout.addWidget(QLabel("Confidence:"))
        self.confidence_label = QLabel("0.00")
        self.confidence_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        intensity_layout.addWidget(self.confidence_label)
        
        intensity_layout.addStretch()
        layout.addLayout(intensity_layout)
        
        # Sensor values readouts
        sensors_layout = QHBoxLayout()
        sensors_layout.addWidget(QLabel("Sensors [T, B, R, L, C]:"))
        
        self.sensor_labels = []
        sensor_names = ['T', 'B', 'R', 'L', 'C']
        for name in sensor_names:
            label = QLabel(f"{name}: 0")
            label.setStyleSheet("font-family: monospace;")
            self.sensor_labels.append(label)
            sensors_layout.addWidget(label)
        
        sensors_layout.addStretch()
        layout.addLayout(sensors_layout)
        
        group.setLayout(layout)
        return group

    def create_heatmap_settings(self):
        """Create heatmap processing and calibration settings."""
        group = QGroupBox("Heatmap Settings")
        main_layout = QVBoxLayout()

        actions_layout = QHBoxLayout()
        self.save_heatmap_settings_btn = QPushButton("Save Settings...")
        self.save_heatmap_settings_btn.clicked.connect(self.on_save_heatmap_settings_clicked)
        actions_layout.addWidget(self.save_heatmap_settings_btn)

        self.load_heatmap_settings_btn = QPushButton("Load Settings...")
        self.load_heatmap_settings_btn.clicked.connect(self.on_load_heatmap_settings_clicked)
        actions_layout.addWidget(self.load_heatmap_settings_btn)
        actions_layout.addStretch()
        main_layout.addLayout(actions_layout)

        # Signal processing controls
        signal_group = QGroupBox("Signal Processing")
        signal_layout = QGridLayout()
        signal_layout.setColumnMinimumWidth(2, 80)

        signal_layout.addWidget(QLabel("RMS Window (ms):"), 0, 0)
        self.rms_window_spin = QSpinBox()
        self.rms_window_spin.setRange(2, 5000)
        self.rms_window_spin.setValue(RMS_WINDOW_MS)
        signal_layout.addWidget(self.rms_window_spin, 0, 1)

        signal_layout.addWidget(QLabel("DC Removal:"), 0, 3)
        self.dc_removal_combo = QComboBox()
        self.dc_removal_combo.addItems(["Bias (2s)", "High-pass"])
        self.dc_removal_combo.setCurrentIndex(0 if HEATMAP_DC_REMOVAL_MODE == "bias" else 1)
        signal_layout.addWidget(self.dc_removal_combo, 0, 4)

        signal_layout.addWidget(QLabel("HPF Cutoff (Hz):"), 1, 0)
        self.hpf_cutoff_spin = QDoubleSpinBox()
        self.hpf_cutoff_spin.setRange(0.01, 50.0)
        self.hpf_cutoff_spin.setDecimals(3)
        self.hpf_cutoff_spin.setValue(HPF_CUTOFF_HZ)
        signal_layout.addWidget(self.hpf_cutoff_spin, 1, 1)

        signal_layout.addWidget(QLabel("Threshold:"), 1, 3)
        self.magnitude_threshold_spin = QDoubleSpinBox()
        self.magnitude_threshold_spin.setRange(0.0, 1e6)
        self.magnitude_threshold_spin.setDecimals(4)
        self.magnitude_threshold_spin.setValue(HEATMAP_THRESHOLD)
        signal_layout.addWidget(self.magnitude_threshold_spin, 1, 4)

        self.dc_removal_combo.currentIndexChanged.connect(self._on_dc_mode_changed)
        self._on_dc_mode_changed(self.dc_removal_combo.currentIndex())

        signal_group.setLayout(signal_layout)
        main_layout.addWidget(signal_group)

        # Calibration controls
        calib_group = QGroupBox("Per-Sensor Calibration")
        calib_layout = QVBoxLayout()

        sensor_labels = ['T', 'B', 'R', 'L', 'C']

        gain_layout = QHBoxLayout()
        gain_layout.addWidget(QLabel("Gain [T,B,R,L,C]:"))
        self.sensor_gain_spins = []
        for idx, label in enumerate(sensor_labels):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(4)
            spin.setValue(SENSOR_CALIBRATION[idx])
            spin.setPrefix(f"{label}: ")
            self.sensor_gain_spins.append(spin)
            gain_layout.addWidget(spin)
        gain_layout.addStretch()
        calib_layout.addLayout(gain_layout)

        noise_layout = QHBoxLayout()
        noise_layout.addWidget(QLabel("Noise Floor [T,B,R,L,C]:"))
        self.sensor_noise_spins = []
        for idx, label in enumerate(sensor_labels):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1e6)
            spin.setDecimals(4)
            spin.setValue(SENSOR_NOISE_FLOOR[idx])
            spin.setPrefix(f"{label}: ")
            self.sensor_noise_spins.append(spin)
            noise_layout.addWidget(spin)
        noise_layout.addStretch()
        calib_layout.addLayout(noise_layout)

        calib_group.setLayout(calib_layout)
        main_layout.addWidget(calib_group)

        # Heatmap parameters
        heatmap_group = QGroupBox("Heatmap Parameters")
        heatmap_layout = QGridLayout()
        heatmap_layout.setColumnMinimumWidth(2, 80)

        heatmap_layout.addWidget(QLabel("Sensor Size:"), 0, 0)
        self.sensor_size_spin = QDoubleSpinBox()
        self.sensor_size_spin.setRange(0.01, 10000.0)
        self.sensor_size_spin.setDecimals(2)
        self.sensor_size_spin.setValue(SENSOR_SIZE)
        heatmap_layout.addWidget(self.sensor_size_spin, 0, 1)

        heatmap_layout.addWidget(QLabel("Intensity Scale:"), 0, 3)
        self.intensity_scale_spin = QDoubleSpinBox()
        self.intensity_scale_spin.setRange(0.0, 1.0)
        self.intensity_scale_spin.setDecimals(6)
        self.intensity_scale_spin.setSingleStep(0.0001)
        self.intensity_scale_spin.setValue(INTENSITY_SCALE)
        heatmap_layout.addWidget(self.intensity_scale_spin, 0, 4)

        heatmap_layout.addWidget(QLabel("Blob Sigma X:"), 1, 0)
        self.blob_sigma_x_spin = QDoubleSpinBox()
        self.blob_sigma_x_spin.setRange(0.01, 5.0)
        self.blob_sigma_x_spin.setDecimals(4)
        self.blob_sigma_x_spin.setValue(BLOB_SIGMA_X)
        heatmap_layout.addWidget(self.blob_sigma_x_spin, 1, 1)

        heatmap_layout.addWidget(QLabel("Blob Sigma Y:"), 1, 3)
        self.blob_sigma_y_spin = QDoubleSpinBox()
        self.blob_sigma_y_spin.setRange(0.01, 5.0)
        self.blob_sigma_y_spin.setDecimals(4)
        self.blob_sigma_y_spin.setValue(BLOB_SIGMA_Y)
        heatmap_layout.addWidget(self.blob_sigma_y_spin, 1, 4)

        heatmap_layout.addWidget(QLabel("Smooth Alpha:"), 2, 0)
        self.smooth_alpha_spin = QDoubleSpinBox()
        self.smooth_alpha_spin.setRange(0.0, 1.0)
        self.smooth_alpha_spin.setDecimals(3)
        self.smooth_alpha_spin.setSingleStep(0.01)
        self.smooth_alpha_spin.setValue(SMOOTH_ALPHA)
        heatmap_layout.addWidget(self.smooth_alpha_spin, 2, 1)

        heatmap_group.setLayout(heatmap_layout)
        main_layout.addWidget(heatmap_group)

        self._connect_heatmap_settings_autosave()

        group.setLayout(main_layout)
        return group

    def _on_dc_mode_changed(self, index):
        use_hpf = (index == 1)
        self.hpf_cutoff_spin.setEnabled(use_hpf)

    def get_heatmap_settings(self):
        dc_mode = "bias" if self.dc_removal_combo.currentIndex() == 0 else "highpass"
        return {
            'sensor_calibration': [spin.value() for spin in self.sensor_gain_spins],
            'sensor_noise_floor': [spin.value() for spin in self.sensor_noise_spins],
            'sensor_size': self.sensor_size_spin.value(),
            'intensity_scale': self.intensity_scale_spin.value(),
            'blob_sigma_x': self.blob_sigma_x_spin.value(),
            'blob_sigma_y': self.blob_sigma_y_spin.value(),
            'smooth_alpha': self.smooth_alpha_spin.value(),
            'rms_window_ms': self.rms_window_spin.value(),
            'dc_removal_mode': dc_mode,
            'hpf_cutoff_hz': self.hpf_cutoff_spin.value(),
            'magnitude_threshold': self.magnitude_threshold_spin.value(),
            'channel_sensor_map': HEATMAP_CHANNEL_SENSOR_MAP,
            'confidence_intensity_ref': CONFIDENCE_INTENSITY_REF,
            'sigma_spread_factor': SIGMA_SPREAD_FACTOR,
        }
    
    def update_heatmap_display(self, heatmap, cop_x, cop_y, intensity, confidence, sensor_values):
        """Update heatmap visualization with new data.
        
        Args:
            heatmap: 2D numpy array (HEATMAP_HEIGHT x HEATMAP_WIDTH)
            cop_x: Center of pressure X coordinate
            cop_y: Center of pressure Y coordinate
            intensity: Overall pressure intensity
            sensor_values: List of 5 sensor values
        """
        # Update heatmap image
        self.heatmap_image.setImage(heatmap.T, autoLevels=False, levels=(0, 1))
        
        # Update readouts
        self.cop_x_label.setText(f"X: {cop_x:+.3f}")
        self.cop_y_label.setText(f"Y: {cop_y:+.3f}")
        self.intensity_label.setText(f"{intensity:.1f}")
        self.confidence_label.setText(f"{confidence:.2f}")
        
        # Update sensor values
        sensor_names = ['T', 'B', 'R', 'L', 'C']
        for i, (name, value) in enumerate(zip(sensor_names, sensor_values)):
            self.sensor_labels[i].setText(f"{name}: {value:.1f}")
    
    def show_heatmap_channel_warning(self, current_channels):
        """Display warning message when channel count is incorrect.
        
        Args:
            current_channels: Current number of selected channels
        """
        message = f"⚠ Heatmap requires exactly 5 channels (currently {current_channels} selected)"
        self.heatmap_status_label.setText(message)
    
    def clear_heatmap_channel_warning(self):
        """Clear channel warning message."""
        self.heatmap_status_label.setText("")
