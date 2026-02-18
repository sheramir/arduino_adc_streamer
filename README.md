# Arduino ADC Streamer

High-speed ADC data acquisition system for Arduino-based boards with real-time visualization and analysis. This repository includes a comprehensive Python GUI application and Arduino firmware for streaming analog sensor data at high sample rates with advanced features like ground subtraction, repeat averaging, and force sensor integration.

## 🚀 Quick Start

1. **Upload Arduino Sketch**:
   - Navigate to `Arduino_Sketches/MG24/ADC_Streamer_binary_scan/`
   - Open `ADC_Streamer_binary_scan.ino` in Arduino IDE
   - Upload to your XIAO MG24 board (or compatible)

2. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the GUI**:
   ```bash
   python adc_gui.py
   # Or with uv:
   uv run adc_gui.py
   
   # To test the modular architecture (demo):
   python adc_gui_refactored_demo.py
   ```

## 📁 Repository Contents

### Main Application Files
- **`adc_gui.py`**: Main GUI entry point
- **`config_constants.py`**: Centralized configuration constants
- **`buffer_utils.py`**: Buffer optimization and validation utilities
- **`requirements.txt`**: Python package dependencies

### Modular Code Structure
- **`serial_communication/`**: Serial port handling and data acquisition threads
- **`gui/`**: GUI component creation (planned)
- **`data_processing/`**: Data processing and analysis (planned)
- **`config/`**: Configuration management (planned)
- **`file_operations/`**: Data export functionality (planned)

See **[README_REFACTORING.md](README_REFACTORING.md)** for detailed architecture documentation.

### Arduino Sketches
- **`Arduino_Sketches/MG24/ADC_Streamer_binary_scan/`**: **Current sketch** - Binary streaming with buffered blocks (recommended)
- **`Arduino_Sketches/MG24/ADC_Streamer_binary/`**: Binary streaming (legacy)
- **`Arduino_Sketches/MG24/ADC_Streamer_binary_buffer/`**: Binary with buffer (legacy)
- **`Arduino_Sketches/MG24/ADC_Streamer XIAO MG24/`**: ASCII streaming (legacy)

### Documentation
- **`GUI_README.md`**: Comprehensive GUI user guide
- **`README_REFACTORING.md`**: Code architecture and modularization guide
- **`BUFFER_OPTIMIZATION.md`**: Buffer size optimization guide
- **`IADC_UPDATE_CHANGES.md`**: IADC firmware update notes

## ✨ Features

### Hardware Support
- 🔌 **XIAO MG24**: 12-bit IADC with oversampling (OSR 2×, 4×, 8×)
- 🧪 **Teensy 4.0 + Teensy555_streamer**: 555 timing analyzer streaming resistance-like channel values
- 📊 **Multi-channel scanning**: Up to 18 analog input pins
- ⚡ **High-speed acquisition**: Up to 76 kHz per channel (OSR 2×)
- 🔄 **Ground subtraction**: Automatic background subtraction with dedicated ground pin
- 🎯 **Analog gain**: 1×, 2×, 3×, 4× amplification

### Data Acquisition
- 🔁 **Repeat averaging**: 1-16 measurements per channel per sweep (hardware limit)
- 📦 **Buffered streaming**: Configurable block size (up to 32,000 samples)
- ⏱️ **Timing measurement**: Per-sample and block-gap timing from Arduino
- 🕐 **Timed runs**: Fixed-duration captures with automatic stop

### Visualization & Analysis
- 📈 **Real-time plotting**: Fast pyqtgraph-based visualization with scrolling window
- 🎨 **Channel selection**: Individual channel display control
- 📊 **Display modes**: View all repeats or averaged data
- 🔍 **Zoom/pan**: Interactive plot navigation
- 📏 **Dual Y-axes**: ADC values or voltage conversion
- 💪 **Force sensor support**: Dual-axis force measurement overlay (115200 baud CSV)
- 🎛️ **Real-time filtering**: User-configurable Notch/LP/HP/BP filtering with shared processing for time-series + spectrum

### Filtering (Time Series + Spectrum)
- Filter controls are in the **Spectrum** tab under **Filtering**.
- One master toggle controls filtering ON/OFF.
- Supports up to 3 notch filters (default: 60 Hz + 120 Hz enabled), each with enable/frequency/Q.
- Supports one main filter at a time: **Low-pass**, **High-pass**, or **Band-pass**.
- Notch filters can be combined with one main filter.
- The pipeline is shared:
   - `raw samples -> optional filter engine -> processed samples`
   - time-series uses processed samples when filtering is ON
   - spectrum/FFT uses the same processed samples when filtering is ON
- Uses stable IIR SOS filtering (SciPy) with per-channel state continuity across blocks.

### Data Management
- 💾 **CSV export**: Timestamped data with full metadata
- 🖼️ **Plot export**: Save visualization as PNG images
- 📝 **Notes**: Add experimental notes to saved files
- 🎯 **Range selection**: Export specific sweep ranges

## 🔧 Requirements

### Software
- **Python**: 3.8+ (tested with 3.11)
- **Packages**: PyQt6, pyserial, pyqtgraph, numpy
- **Arduino IDE**: 1.8+ or Arduino CLI

### Hardware
- **Primary**: Seeed XIAO MG24 (12-bit IADC, 76 kHz max)
- **Force Sensor** (optional): Serial CSV output (X, Z axes)

## 📖 Configuration

### ADC Settings
- **Voltage Reference**: 1.2V (internal) or 3.3V (VDD)
- **Oversampling (OSR)**: 2, 4, or 8 (higher = better SNR, lower sample rate)
- **Analog Gain**: 1×, 2×, 3×, 4× (applied before ADC)

### MCU-Aware Device Modes
- The GUI detects MCU type automatically on connect.
- If MCU name contains **`555`** (e.g. `Teensy555`), the app switches to **555 analyzer mode**.
- Otherwise, it stays in **ADC streamer mode**.

#### 555 Analyzer Mode
- ADC-specific controls are hidden/disabled (ground pin, averaging/OSR, conversion speed, sampling speed).
- 555 parameter controls are shown:
   - **Cf** (with pF/nF/uF unit selector, converted to farads before send)
   - **Rk** (ohms)
   - **Rb** (ohms)
   - **Rx max** (ohms)
- Time-series plotting is interpreted as **resistance-like values** and labeled in ohms.
- Time-series tab shows computed timing readouts:
   - $T_{charge}=\ln(2)\,C_f\,(R_x + R_k + R_b)$
   - $T_{discharge}=\ln(2)\,C_f\,R_b$

### Acquisition Settings
- **Channel Sequence**: Comma-separated list (e.g., `0,1,2,3` or `0,1,1,2,3` for oversampling channel 1)
- **Repeat Count**: 1-16 measurements per channel per sweep
- **Ground Pin**: 0-18 (optional, for background subtraction)
- **Buffer Size**: Sweeps per block sent to PC (validated against 32K sample limit)

### Buffer Optimization
The GUI automatically validates buffer size against hardware limits:
- **Formula**: `buffer_size × channels × repeat_count ≤ 32,000 samples`
- See `BUFFER_OPTIMIZATION.md` for tuning guidelines

## 📊 Arduino Protocol

### Configuration Commands
```
ref <value>        - Set voltage reference: "1.2" or "vdd"
osr <value>        - Set oversampling: 2, 4, or 8
gain <value>       - Set analog gain: 1, 2, 3, or 4
channels <list>    - Set channel sequence: "0,1,2,3"
repeat <count>     - Set repeat count: 1-16
ground <pin|false> - Set ground pin (0-18) or disable ("false")
buffer <size>      - Set sweeps per block
```

### 555 Analyzer Commands
When in 555 mode, configuration sends only this subset:
```
channels <list>
repeat <count>
buffer <size>
rb <value>
rk <value>
cf <farads>
rxmax <value>
```
ADC-only commands such as `ref`, `osr`, `gain`, and `ground` are not sent in 555 mode.

### Run Commands
```
run           - Start continuous capture
run <ms>      - Timed capture (milliseconds)
stop          - Stop capture
status        - Print current configuration
```

### Data Format
- **Binary blocks**: Header `[0xAA][0x55][countL][countH]` + samples (uint16 LE) + timing (uint16 LE)
- **ASCII messages**: Lines starting with `#` for status/errors

## 🎯 Typical Workflow

1. **Connect** Arduino via serial port
2. **Configure** ADC settings (reference, OSR, gain)
3. **Set channels** and acquisition parameters
4. **Press Configure** to send settings to Arduino
5. **Press Start** to begin capture and real-time plotting
6. **Press Stop** when complete
7. **Save data** as CSV with notes and metadata

## 📚 Documentation

- **[README_REFACTORING.md](README_REFACTORING.md)**: Code architecture and modularization guide
- **[GUI_README.md](GUI_README.md)**: Complete user guide with screenshots
- **[BUFFER_OPTIMIZATION.md](BUFFER_OPTIMIZATION.md)**: Performance tuning guide
- **[IADC_UPDATE_CHANGES.md](IADC_UPDATE_CHANGES.md)**: Firmware change notes

## 🐛 Troubleshooting

### Common Issues
- **No data received**: Check "Use Ground Sample" is unchecked unless using ground pin
- **Buffer size error**: Reduce buffer size or repeat count
- **Configuration fails**: Reset Arduino and reconnect
- **Intermittent crashes**: Fixed in latest version (Qt thread safety)

### Qt Geometry Warning
The warning about window geometry can be safely ignored - it's a cosmetic issue with Qt adjusting window size to fit your display.

## 🤝 Contributing

Contributions welcome! Areas for improvement:
- Additional Arduino board support
- Advanced signal processing features
- Export format options
- Calibration tools

## 📄 License

[Add your license here]

---

**Note**: This project has evolved significantly from ASCII to optimized binary streaming with buffering. The current recommended firmware is `ADC_Streamer_binary_scan` which provides the best performance and reliability.
