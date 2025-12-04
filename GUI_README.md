# ADC Streamer GUI - User Guide

Comprehensive Python GUI for high-speed ADC data acquisition with the XIAO MG24 board.

## Features

### 🔌 Serial Communication
- Automatic serial port detection and selection
- Connect/Disconnect with status indicators
- 460800 baud rate (optimized for binary streaming)
- Real-time status monitoring
- Force sensor support (115200 baud, separate port)

### ⚙️ ADC Configuration (IADC Hardware)
- **Fixed Resolution**: 12-bit (0-4095 range)
- **Voltage Reference Selection**:
  - 1.2V Internal Reference
  - 3.3V VDD (default)
- **Oversampling Ratio (OSR)**: 2×, 4×, or 8×
  - Higher OSR = better SNR, lower sample rate
- **Analog Gain**: 1×, 2×, 3×, 4×

### 📊 Acquisition Settings
- **Channel Sequence**: Configure multiple ADC channels (0-18, supports duplicates)
  - Example: `0,1,2,3` or `0,1,1,2,3` for repeated channels
- **Ground Pin**: Set reference ground pin (0-18) for offset correction
- **Ground Sampling**: Enable/disable ground subtraction
- **Repeat Count**: 1-16 measurements per channel per sweep (hardware limit)
- **Buffer Size**: Sweeps per block (auto-validated against 32K sample limit)

### 🎮 Run Control
- **Continuous Mode**: Stream data until manually stopped
- **Timed Mode**: Capture for specified duration (10 ms - 3,600,000 ms)
- **Configure Button**: Send all settings to Arduino with verification
- **Real-time Start/Stop**: Responsive control during acquisition
- **Clear Data**: Reset captured data buffer

### 💾 Data Export
- **CSV Export**: Raw ADC values with automatic timestamping
- **Metadata File**: Complete acquisition parameters and timing statistics
- **Plot Image Export**: High-resolution PNG of current visualization
- **Range Selection**: Export specific sweep ranges
- **Custom Notes**: Add experimental notes to saved files

### 📈 Real-time Visualization
- **High-speed Plotting**: Powered by pyqtgraph with binary streaming
- **Dual Y-axes**: ADC left axis, Force sensor right axis
- **Channel Selection**: Individual channel display control
- **Display Modes**:
  - Show all individual repeat samples
  - Show averaged values across repeats
- **Y-axis Options**:
  - Adaptive (auto-scale to visible data)
  - Full-Scale (0 to max ADC value)
  - Units: Values or Voltage conversion
- **Window Control**: Scrolling window size (10-100,000 sweeps)
- **Force Sensor Overlay**: X and Z force measurements on same timeline

### 📊 Timing Measurement
- **Per-Channel Rate**: Sampling frequency per channel
- **Total Rate**: Overall sampling rate
- **Sample Interval**: Time between samples (from Arduino)
- **Block Gap**: Time between data blocks (transmission overhead)

## Installation

### Prerequisites
- Python 3.8 or higher (tested with 3.11)
- XIAO MG24 board with ADC_Streamer_binary_scan sketch
- USB connection to Arduino
- Optional: Force sensor with serial output (X,Z CSV format)

### Setup

1. **Clone the repository**:
   ```bash
   git clone <repository_url>
   cd arduino_adc_streamer
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   # Or with uv:
   uv sync
   ```

3. **Upload Arduino sketch**:
   - Open `Arduino_Sketches/MG24/ADC_Streamer_binary_scan/ADC_Streamer_binary_scan.ino`
   - Upload to your XIAO MG24 board

## Usage

### Starting the Application

```bash
python adc_gui.py
# Or with uv:
uv run adc_gui.py
```

### Quick Start Guide

1. **Connect to Arduino**:
   - Click "Refresh" to scan for ports
   - Select your serial port (e.g., COM9 on Windows)
   - Click "Connect"
   - Wait for "Connected - Please configure" status

2. **Configure ADC**:
   - Set voltage reference (default: 3.3V VDD)
   - Set OSR (default: 2 for fastest sampling)
   - Set gain (default: 1×)
   - Enter channel sequence (e.g., `0,1,2,3`)
   - Set repeat count (1-16)
   - Optionally enable ground pin and select pin number
   - Click "Configure Arduino"
   - Wait for "✓ Configuration verified - Ready to start"

3. **Start Capture**:
   - For continuous: Click "Start"
   - For timed: Check "Timed Run (ms)", set duration, click "Start"
   - Watch real-time plot and timing statistics

4. **Monitor Data**:
   - Observe sweep count and sample count in plot info
   - Check timing display for sample rates
   - Select/deselect channels in "Display Channels"
   - Choose display mode (All Repeats or Average)

5. **Stop and Save**:
   - Click "Stop" when done
   - Add notes in the text box
   - Optionally set save range
   - Click "Save Data (CSV)" to export
   - Click "Save Plot Image" to save visualization

### Example Workflow: Multi-Channel Acquisition

```
1. Connect Arduino on COM9
2. Configure: Ref=VDD, OSR=2, Gain=1
3. Set channels: 0,1,2,3,4,5
4. Set repeat: 4 (for averaging)
5. Buffer: 128 sweeps per block
6. Click "Configure Arduino"
7. Click "Start" for continuous capture
8. Monitor timing: ~76 kHz total rate with OSR=2
9. Click "Stop" after 10 seconds
10. Save data with notes: "Sensor array baseline test"
```

### Example Workflow: Ground Subtraction

```
1. Connect Arduino
2. Set channels: 0,1,2,3
3. Set repeat: 8
4. Enable "Use Ground Sample" checkbox
5. Set ground pin: 5 (connect to ground reference)
6. Click "Configure Arduino"
7. Start timed run: 5000 ms
8. System automatically subtracts ground reading from each channel
9. View averaged data for cleaner signal
10. Save with notes: "With ground subtraction"
```

### Example Workflow: High-Speed Single Channel

```
1. Connect Arduino
2. Set channels: 0
3. Set repeat: 1
4. OSR: 2 (fastest)
5. Click "Configure Arduino"
6. Start continuous run
7. Achieve ~76 kHz sampling on channel 0
8. Monitor "Sample Interval" display
9. Stop and save raw data
```

## Arduino Commands

The GUI automatically sends these commands (you don't need to type them):

| Command | Purpose | Example |
|---------|---------|---------|
| `ref <value>` | Set voltage reference | `ref vdd` or `ref 1.2` |
| `osr <value>` | Set oversampling ratio | `osr 2`, `osr 4`, `osr 8` |
| `gain <value>` | Set analog gain | `gain 1`, `gain 2`, `gain 4` |
| `channels <list>` | Set channel sequence | `channels 0,1,2,3` |
| `repeat <count>` | Set repeat count (1-16) | `repeat 8` |
| `ground <pin>` | Enable ground on pin | `ground 0`, `ground 5` |
| `ground false` | Disable ground | `ground false` |
| `buffer <size>` | Set sweeps per block | `buffer 128` |
| `run` | Start continuous capture | `run` |
| `run <ms>` | Start timed capture | `run 5000` |
| `stop` | Stop capture | `stop` |
| `status` | Request configuration | `status` |

**Note**: All commands use `***` terminator (sent automatically by GUI)

## Data Format

### CSV Output (Binary Streaming)
- **Binary blocks** during capture: `[0xAA][0x55][countL][countH] + samples (uint16 LE) + timing (uint16 LE)`
- **CSV export**: One row per sweep, comma-separated ADC values
- **Structure**: `[ch0_r1, ch0_r2, ..., ch0_rN, ch1_r1, ..., chN_rM]`
  - Where N = number of channels, M = repeat count
- **No headers**: Pure numerical data for easy import

Example with channels `0,1`, repeat `3`:
```csv
1234,1235,1236,5678,5679,5680
1233,1236,1237,5677,5680,5681
1232,1234,1235,5676,5678,5679
```

### Metadata File
Saved alongside CSV with `_metadata.txt` suffix:
```
ADC Streamer - Acquisition Metadata
==================================================

Timestamp: 2025-12-04 14:30:45
Total Sweeps: 5000
Total Samples: 60000

Configuration:
--------------------------------------------------
Channels: 0,1,2,3
Repeat Count: 12
Ground Pin: 0
Use Ground Sample: True
Voltage Reference: vdd
OSR: 2
Gain: 1
Buffer Size: 128
Resolution (bits): 12

Timing Statistics:
--------------------------------------------------
Per-Channel Rate: 19234.56 Hz
Total Sample Rate: 76938.25 Hz
Sample Interval: 13.00 µs
Block Gap: 45.23 ms

Notes:
--------------------------------------------------
Test with ground subtraction enabled
```

## Visualization Controls

### Channel Selection
- **Select All**: Display all configured channels
- **Deselect All**: Hide all channels
- **Individual Selection**: Click specific channels in the list

### Repeats Visualization
- **Show All Repeats**: Display every individual sample (raw data)
- **Show Average**: Display averaged values across repeats (smoother)
- Both can be enabled simultaneously for comparison

### Plot Interaction
- **Mouse Drag**: Pan the plot
- **Mouse Wheel**: Zoom in/out
- **Right Click**: Access pyqtgraph context menu for advanced options

## Troubleshooting

### Connection Issues

**Problem**: "No ports found" in dropdown
- **Solution**: Check USB connection, restart Arduino, click "Refresh"

**Problem**: "Failed to connect - Permission denied" (Linux)
- **Solution**: Add user to dialout group:
  ```bash
  sudo usermod -a -G dialout $USER
  # Log out and log back in
  ```

**Problem**: Connection works but Configure button grayed out
- **Solution**: Successfully connected, ready to configure

### Configuration Issues

**Problem**: "Configuration failed after retries"
- **Solution**:
  - Check channel format (comma-separated numbers, no spaces)
  - Verify repeat count is 1-16
  - Disconnect and reconnect Arduino
  - Hard reset Arduino if frozen

**Problem**: Buffer size keeps getting reduced
- **Solution**: This is normal - GUI validates against 32K sample limit
  - Formula: `buffer × channels × repeat ≤ 32000`
  - Reduce repeat count or buffer size

**Problem**: Cannot select ground pin 0
- **Solution**: Fixed in current version - pin 0 is valid

### Data Acquisition Issues

**Problem**: No data received (0 sweeps)
- **Solution**:
  - Press "Configure Arduino" before "Start"
  - Wait for "✓ Configuration verified" message
  - If using ground pin, ensure Arduino firmware is updated
  - Check status window for error messages

**Problem**: Arduino stops responding after configuration
- **Solution**:
  - Hard reset Arduino (press reset button)
  - Disconnect and reconnect in GUI
  - Check Arduino firmware version (use ADC_Streamer_binary_scan)

**Problem**: Plot shows no lines
- **Solution**:
  - Click "Select All" in Display Channels
  - Check sweep count > 0
  - Try "Reset View" or "Full View" buttons

**Problem**: Intermittent crashes
- **Solution**: Fixed in latest version (Qt thread safety improvements)

### Export Issues

**Problem**: "Failed to save data" error
- **Solution**:
  - Check output directory is writable
  - Close any files with same name
  - Avoid special characters in filename

**Problem**: Metadata file missing timing data
- **Solution**: Timing data only available after capture completes

### Performance Issues

**Problem**: Plot updates slowly or freezes
- **Solution**:
  - Reduce window size (default 10,000 sweeps)
  - Reduce buffer size
  - Use "Show Average" instead of "All Repeats"
  - Close other applications

**Problem**: Low sample rate achieved
- **Solution**:
  - Use OSR=2 for fastest sampling
  - Minimize channel count
  - Reduce repeat count
  - Check USB cable quality

## System Requirements

### Minimum
- **OS**: Windows 10, macOS 10.14, Linux (Ubuntu 18.04+)
- **Python**: 3.8+
- **RAM**: 4 GB
- **Disk Space**: 500 MB

### Recommended
- **OS**: Windows 11, macOS 12+, Linux (Ubuntu 22.04+)
- **Python**: 3.11+
- **RAM**: 8 GB
- **Disk Space**: 2 GB (for data storage)
- **USB**: USB 3.0 port for best performance

## Dependencies

See `requirements.txt` for exact versions:
- **PyQt6** (>=6.4.0): GUI framework
- **pyserial** (>=3.5): Serial communication
- **pyqtgraph** (>=0.13.0): Real-time plotting
- **numpy** (>=1.21.0): Numerical operations

## Configuration Constants

All configurable values are in `config_constants.py`:
- Serial baud rate (460800)
- Timeout values
- Buffer limits (32,000 samples)
- UI dimensions
- Timing parameters

## Force Sensor Integration

Optional force sensor support for correlated measurements:

1. **Connect force sensor** to separate serial port (115200 baud)
2. **Select port** from "Force Port" dropdown
3. **Click "Connect Force"**
4. **Calibration** happens automatically (10 samples)
5. **Start ADC capture** - force data syncs automatically
6. **View overlay** - X (red) and Z (blue) on right Y-axis
7. **Export** - force data saved in separate CSV

Force data format: `timestamp,x_force,z_force`

## Advanced Topics

### Buffer Size Optimization

See `BUFFER_OPTIMIZATION.md` for detailed guide on:
- Calculating optimal buffer size
- Trade-offs between latency and throughput
- USB packet alignment
- Memory constraints

Formula: `max_buffer = floor(32000 / (channels × repeat))`

### Custom Analysis

Example post-processing script:

```python
import numpy as np
import pandas as pd

# Load ADC data
data = np.loadtxt('adc_data_20251204_143045.csv', delimiter=',')

# Reshape: (sweeps, channels × repeats)
channels = 4
repeats = 12
n_sweeps = data.shape[0]

# Separate by channel
for ch in range(channels):
    ch_data = data[:, ch*repeats:(ch+1)*repeats]
    mean = np.mean(ch_data, axis=1)
    std = np.std(ch_data, axis=1)
    
    print(f"Channel {ch}: mean={mean.mean():.2f}, noise={std.mean():.2f}")
```

### Automated Testing

```python
# Example: Parameter sweep
import subprocess
import time

configs = [
    {'osr': 2, 'gain': 1, 'repeat': 4},
    {'osr': 4, 'gain': 2, 'repeat': 8},
    {'osr': 8, 'gain': 4, 'repeat': 16},
]

for config in configs:
    # Launch GUI with config
    # Capture data
    # Analyze SNR
    # Save results
    pass
```

## Known Issues

### Qt Geometry Warning
You may see a warning about window geometry on startup:
```
QWindowsWindow::setGeometry: Unable to set geometry...
```
**This is harmless** - Qt automatically adjusts the window to fit your display. No action needed.

### Thread Safety
All Qt thread safety issues have been fixed in the current version. Configuration and data reception run in background threads without blocking the UI.

## Version History

### Current Version
- Binary streaming with buffered blocks (32K limit)
- IADC support (12-bit, OSR, gain control)
- Ground pin subtraction (0-18)
- Force sensor integration
- Thread-safe operation
- Timing measurement from Arduino
- Range export
- Notes field
- Full configuration validation

### Legacy Versions
- ASCII streaming (deprecated)
- Simple binary streaming (deprecated)
- Resolution control (removed - now hardware fixed at 12-bit)

## Future Enhancements

Potential features for future versions:
- [ ] FFT analysis and frequency domain visualization
- [ ] Trigger-based capture modes
- [ ] Multiple Arduino support (synchronized capture)
- [ ] Data streaming to file during capture
- [ ] Calibration curve management
- [ ] Plugin system for custom signal processing

---

**Happy Data Acquisition! 📊⚡**
