"""
Display Panels Mixin
====================
GUI components for plot display, visualization controls, and timing information.
Now includes tabbed interface for time-series and heatmap views.
"""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QComboBox, QCheckBox, QSpinBox, QWidget, QScrollArea, QTabWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import pyqtgraph as pg

from config_constants import (
    WINDOW_SIZE_MIN, WINDOW_SIZE_MAX, DEFAULT_WINDOW_SIZE, CHANNEL_SCROLL_HEIGHT
)


class DisplayPanelsMixin:
    """Mixin class for display and visualization GUI components."""
    
    def create_plot_section(self) -> QWidget:
        """Create tabbed visualization section with time-series plot and heatmap.
        
        Returns:
            QWidget: Widget containing tabbed display (Time Series + Heatmap)
        """
        # Create tab widget
        self.visualization_tabs = QTabWidget()
        
        # Create time-series tab
        timeseries_tab = self.create_timeseries_tab()
        self.visualization_tabs.addTab(timeseries_tab, "Time Series")
        self.timeseries_tab_index = 0
        
        # Create heatmap tab (from HeatmapPanelMixin)
        heatmap_tab = self.create_heatmap_tab()
        self.visualization_tabs.addTab(heatmap_tab, "2D Heatmap")
        self.heatmap_tab_index = 1

        # Create spectrum tab (from SpectrumPanelMixin)
        spectrum_tab = self.create_spectrum_tab()
        self.visualization_tabs.addTab(spectrum_tab, "Spectrum")
        self.spectrum_tab_index = 2
        
        return self.visualization_tabs
    
    def create_timeseries_tab(self) -> QWidget:
        """Create the traditional time-series plotting tab with controls.
        
        Returns:
            QWidget: Widget containing plot, controls, and timing
        """
        tab_widget = QWidget()
        layout = QVBoxLayout()

        # Plot section
        plot_group = QGroupBox("Real-time Data Visualization")
        plot_layout = QVBoxLayout()

        # Create main plot widget with dual Y-axes (ADC on left, Force on right)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'ADC Value', units='counts')
        self.plot_widget.setLabel('bottom', 'Sample Index')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Create a second ViewBox for force data (right Y-axis)
        self.force_viewbox = pg.ViewBox()
        self.plot_widget.scene().addItem(self.force_viewbox)
        self.plot_widget.getAxis('right').linkToView(self.force_viewbox)
        self.force_viewbox.setXLink(self.plot_widget)  # Link X-axis
        self.plot_widget.setLabel('right', 'Force (Raw)', units='')
        self.plot_widget.showAxis('right')
        
        # Add legends
        self.adc_legend = self.plot_widget.addLegend(offset=(10, 10))
        self.force_legend = pg.LegendItem(offset=(10, 100))
        self.force_legend.setParentItem(self.plot_widget.graphicsItem())
        
        # Connect view resize to update force viewbox geometry
        self.plot_widget.getViewBox().sigResized.connect(self.update_force_viewbox)

        plot_layout.addWidget(self.plot_widget)

        # Combined info label
        self.plot_info_label = QLabel("ADC - Sweeps: 0 | Samples: 0  |  Force: 0 samples")
        plot_layout.addWidget(self.plot_info_label)

        self.charge_time_label = QLabel("")
        self.charge_time_label.setStyleSheet("font-family: monospace;")
        self.charge_time_label.setVisible(False)
        plot_layout.addWidget(self.charge_time_label)

        self.discharge_time_label = QLabel("")
        self.discharge_time_label.setStyleSheet("font-family: monospace;")
        self.discharge_time_label.setVisible(False)
        plot_layout.addWidget(self.discharge_time_label)

        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)
        
        # Add timing section
        layout.addWidget(self.create_timing_section())
        
        # Add visualization controls
        layout.addWidget(self.create_visualization_controls())

        tab_widget.setLayout(layout)
        return tab_widget
    
    def update_force_viewbox(self):
        """Update force viewbox geometry to match main plot viewbox."""
        if hasattr(self, 'force_viewbox'):
            self.force_viewbox.setGeometry(self.plot_widget.getViewBox().sceneBoundingRect())

    def create_visualization_controls(self) -> QGroupBox:
        """Create visualization control section."""
        group = QGroupBox("Visualization Controls")
        main_layout = QVBoxLayout()

        # Channel selector with compact checkboxes
        channel_group = QGroupBox("Display Channels")
        channel_main_layout = QVBoxLayout()

        # Container for checkboxes (will be populated dynamically)
        self.channel_checkboxes_container = QWidget()
        self.channel_checkboxes_layout = QGridLayout()
        self.channel_checkboxes_layout.setSpacing(5)
        self.channel_checkboxes_container.setLayout(self.channel_checkboxes_layout)

        # Scroll area for many channels
        scroll = QScrollArea()
        scroll.setWidget(self.channel_checkboxes_container)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(CHANNEL_SCROLL_HEIGHT)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        channel_main_layout.addWidget(scroll)

        # Control buttons (compact, horizontal)
        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("All")
        self.select_all_btn.clicked.connect(self.select_all_channels)
        self.select_all_btn.setMaximumWidth(60)
        btn_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("None")
        self.deselect_all_btn.clicked.connect(self.deselect_all_channels)
        self.deselect_all_btn.setMaximumWidth(60)
        btn_layout.addWidget(self.deselect_all_btn)

        btn_layout.addStretch()
        channel_main_layout.addLayout(btn_layout)

        channel_group.setLayout(channel_main_layout)
        main_layout.addWidget(channel_group)

        # Consolidated Display Settings
        display_settings_group = QGroupBox("Display Settings")
        display_settings_layout = QGridLayout()

        # Row 0: Y-Axis Range and Units
        display_settings_layout.addWidget(QLabel("Y Range:"), 0, 0)
        self.yaxis_range_combo = QComboBox()
        self.yaxis_range_combo.addItems(["Adaptive", "Full-Scale"])
        self.yaxis_range_combo.setCurrentIndex(1)  # Default to Full-Scale
        self.yaxis_range_combo.setToolTip("Adaptive: Auto-scale to visible data | Full-Scale: 0 to max ADC value")
        self.yaxis_range_combo.currentIndexChanged.connect(self.on_yaxis_range_changed)
        display_settings_layout.addWidget(self.yaxis_range_combo, 0, 1)

        display_settings_layout.addWidget(QLabel("Y Units:"), 0, 2)
        self.yaxis_units_combo = QComboBox()
        self.yaxis_units_combo.addItems(["Values", "Voltage"])
        self.yaxis_units_combo.setToolTip("Values: Raw ADC samples | Voltage: Convert using Vref")
        self.yaxis_units_combo.currentIndexChanged.connect(self.on_yaxis_units_changed)
        display_settings_layout.addWidget(self.yaxis_units_combo, 0, 3)

        # Row 1: Window controls
        display_settings_layout.addWidget(QLabel("Window Size:"), 1, 0)
        self.window_size_spin = QSpinBox()
        self.window_size_spin.setRange(WINDOW_SIZE_MIN, WINDOW_SIZE_MAX)
        self.window_size_spin.setValue(DEFAULT_WINDOW_SIZE)
        self.window_size_spin.setToolTip("Number of sweeps to display during capture (scrolling mode)")
        display_settings_layout.addWidget(self.window_size_spin, 1, 1)

        self.reset_graph_btn = QPushButton("Reset View")
        self.reset_graph_btn.clicked.connect(self.reset_graph_view)
        self.reset_graph_btn.setToolTip("Reset X-axis to show window size")
        self.reset_graph_btn.setMaximumWidth(100)
        display_settings_layout.addWidget(self.reset_graph_btn, 1, 2)

        self.full_view_btn = QPushButton("Full View")
        self.full_view_btn.clicked.connect(self.full_graph_view)
        self.full_view_btn.setToolTip("Show all data from 0 to last sample (only available after capture finishes)")
        self.full_view_btn.setMaximumWidth(100)
        self.full_view_btn.setEnabled(False)  # Disabled by default (enabled after capture)
        display_settings_layout.addWidget(self.full_view_btn, 1, 3)

        display_settings_group.setLayout(display_settings_layout)
        main_layout.addWidget(display_settings_group)

        # Repeats visualization mode (horizontal layout for compactness)
        repeats_group = QGroupBox("Display Mode")
        repeats_layout = QHBoxLayout()

        self.show_all_repeats_radio = QCheckBox("All Repeats")
        self.show_all_repeats_radio.setChecked(True)
        self.show_all_repeats_radio.toggled.connect(self.trigger_plot_update)
        repeats_layout.addWidget(self.show_all_repeats_radio)

        self.show_average_radio = QCheckBox("Average")
        self.show_average_radio.setChecked(False)
        self.show_average_radio.toggled.connect(self.trigger_plot_update)
        repeats_layout.addWidget(self.show_average_radio)

        repeats_layout.addStretch()
        repeats_group.setLayout(repeats_layout)
        main_layout.addWidget(repeats_group)

        group.setLayout(main_layout)
        return group

    def create_timing_section(self) -> QGroupBox:
        """Create timing measurement display section."""
        group = QGroupBox("Sampling Rate")
        layout = QHBoxLayout()

        # Keep rate labels for internal timing updates but hide them from the GUI
        self.per_channel_rate_label = QLabel("- Hz")
        self.per_channel_rate_label.setStyleSheet("QLabel { font-weight: bold; color: #2196F3; }")
        self.per_channel_rate_label.setVisible(False)

        self.total_rate_label = QLabel("- Hz")
        self.total_rate_label.setStyleSheet("QLabel { font-weight: bold; color: #FF9800; }")
        self.total_rate_label.setVisible(False)

        # Between samples timing
        layout.addWidget(QLabel("Sample Interval:"))
        self.between_samples_label = QLabel("- µs")
        self.between_samples_label.setStyleSheet("QLabel { font-weight: bold; }")
        layout.addWidget(self.between_samples_label)

        layout.addWidget(QLabel("  |  "))

        # Block gap timing
        layout.addWidget(QLabel("Block Gap:"))
        self.block_gap_label = QLabel("- ms")
        self.block_gap_label.setStyleSheet("QLabel { font-weight: bold; color: #9C27B0; }")
        layout.addWidget(self.block_gap_label)

        layout.addStretch()
        group.setLayout(layout)
        return group
