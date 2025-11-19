# ADC Streamer GUI Application

A comprehensive Python GUI application for controlling and visualizing data from the Arduino Interactive ADC CSV Sweeper sketch.

![ADC Streamer GUI](docs/screenshot_placeholder.png)

## Features

### 🔌 Serial Communication
- Automatic serial port detection and selection
- Connect/Disconnect with status indicators
- 115200 baud rate communication
- Real-time command and response monitoring

### ⚙️ ADC Configuration
- **Resolution Control**: 8, 10, 12, or 16 bits
- **Voltage Reference Selection**:
  - 1.2V Internal Reference
  - 3.3V VDD
  - 0.8×VDD
  - External 1.25V Reference

### 📊 Acquisition Settings
- **Channel Sequence**: Configure multiple ADC channels (supports duplicates)
- **Ground Pin**: Set reference ground pin for offset correction
- **Ground Sampling**: Enable/disable ground reading before each capture
- **Repeat Count**: Number of samples per channel (1-1000)
- **Inter-sample Delay**: Configurable delay in microseconds (0-100000 µs)

### 🎮 Run Control
- **Continuous Mode**: Stream data until manually stopped
- **Timed Mode**: Capture for a specified duration (10 ms - 1 hour)
- **Real-time Start/Stop**: Responsive control during acquisition
- **Clear Data**: Reset captured data buffer

### 💾 Data Export
- **CSV Export**: Raw ADC values with automatic timestamping
- **Metadata File**: Complete acquisition parameters and configuration
- **Plot Image Export**: High-resolution PNG of current visualization
- **Custom File Naming**: Configurable output directory and filename

### 📈 Real-time Visualization
- **Interactive Plotting**: Powered by pyqtgraph for fast rendering
- **Channel Selection**: Choose which channels to display
- **Repeats Visualization**:
  - Show all individual repeat samples
  - Show averaged values across repeats
  - Combine both modes for comparison
- **Automatic Legend**: Color-coded channel identification
- **Grid and Labels**: Clear axis labels and grid lines

### 🔒 State Management
- **Parameter Lock-out**: Configuration disabled during capture
- **Status Indicators**: Clear visual feedback of system state
- **Error Handling**: Comprehensive error messages and recovery

## Installation

### Prerequisites
- Python 3.8 or higher
- Arduino with the "Interactive ADC CSV Sweeper" sketch uploaded
- USB connection to Arduino

### Setup

1. **Clone the repository**:
   ```bash
   git clone <repository_url>
   cd arduino_adc_streamer
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Upload Arduino sketch**:
   - Open `ADC_Streamer XIAO MG24/ADC_Streamer XIAO MG24.ino` in Arduino IDE
   - Upload to your Arduino board

## Usage

### Starting the Application

```bash
python adc_gui.py
```

Or make it executable and run directly:
```bash
chmod +x adc_gui.py
./adc_gui.py
```

### Quick Start Guide

1. **Connect to Arduino**:
   - Select your serial port from the dropdown
   - Click "Connect"
   - Wait for "Connected" status

2. **Configure ADC**:
   - Set resolution (e.g., 12 bits)
   - Choose voltage reference (e.g., 3.3V VDD)

3. **Set Acquisition Parameters**:
   - Enter channel sequence (e.g., `0,1,2,3` or `0,0,1,1,2,2`)
   - Set repeat count for averaging (e.g., 20)
   - Configure delay if needed (e.g., 50 µs)
   - Optionally set ground pin and enable ground sampling

4. **Start Capture**:
   - For continuous: Click "Start"
   - For timed: Check "Timed Run", set duration, click "Start"

5. **Monitor Data**:
   - Watch real-time plot update
   - Select/deselect channels to display
   - Toggle repeat visualization modes

6. **Save Data**:
   - Click "Save Data (CSV)" for raw data + metadata
   - Click "Save Plot Image" for visualization snapshot

### Example Workflow: Sensor Characterization

```
1. Connect Arduino on COM3 (or /dev/ttyUSB0)
2. Set channels to: 0,1,2
3. Set repeat count: 50 (for averaging)
4. Set delay: 100 µs
5. Enable ground sampling with ground pin 3
6. Start timed run for 5000 ms
7. After capture, select "Show Average" for cleaner visualization
8. Save data with filename "sensor_test_v1"
```

### Example Workflow: High-Speed Sampling

```
1. Connect Arduino
2. Set channels to: 0,0,0,0 (same channel, 4 times per sweep)
3. Set repeat count: 1 (no averaging within sweep)
4. Set delay: 0 µs (fastest possible)
5. Set resolution: 12 bits
6. Start continuous run
7. Let capture run for desired duration
8. Click "Stop" when complete
9. Use "Show All Repeats" to see individual samples
```

## Arduino Commands

The GUI sends the following commands to the Arduino:

| Command | Purpose | Example |
|---------|---------|---------|
| `channels 0,1,2,3` | Set ADC channel sequence | `channels 0,1,1,2,3` |
| `repeat 20` | Set samples per channel | `repeat 50` |
| `delay 50` | Set inter-sample delay (µs) | `delay 100` |
| `ground 2` | Set ground reference pin | `ground 3` |
| `ground true` | Enable ground sampling | `ground false` |
| `ref 3.3` | Set voltage reference | `ref 1.2` |
| `res 12` | Set ADC resolution (bits) | `res 16` |
| `run` | Start continuous capture | `run` |
| `run 1000` | Start timed capture (ms) | `run 5000` |
| `stop` | Stop capture | `stop` |
| `status` | Request configuration | `status` |

## Data Format

### CSV Output
- One row per sweep
- Comma-separated raw ADC values
- Structure: `[ch0_r1, ch0_r2, ..., ch0_rN, ch1_r1, ..., chLast_rN]`
- No headers, pure numerical data

Example with channels `0,1`, repeat `2`:
```
1234,1235,5678,5679
1233,1236,5677,5680
```

### Metadata File
Contains complete acquisition parameters:
```
ADC Streamer - Acquisition Metadata
==================================================

Timestamp: 2025-11-19 14:30:45
Total Sweeps: 1000
Total Samples: 8000

Configuration:
--------------------------------------------------
Channels: 0,1,2,3
Repeat Count: 20
Delay (µs): 50
Ground Pin: 2
Use Ground Sample: True
ADC Resolution: 12 bits
Voltage Reference: 3.3
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
- **Solution**: Check USB connection, install Arduino drivers

**Problem**: "Failed to connect - Permission denied" (Linux)
- **Solution**: Add user to dialout group:
  ```bash
  sudo usermod -a -G dialout $USER
  # Log out and log back in
  ```

**Problem**: Connection works but no data received
- **Solution**:
  - Verify Arduino sketch is uploaded correctly
  - Check baud rate matches (115200)
  - Try clicking "Refresh" and reconnecting

### Data Acquisition Issues

**Problem**: No data appears when clicking "Start"
- **Solution**:
  - Configure channels first (e.g., `0,1,2`)
  - Check Arduino is in command mode (not stuck in previous run)
  - Disconnect and reconnect to reset Arduino

**Problem**: Plot shows no lines
- **Solution**:
  - Ensure channels are selected in "Display Channels" list
  - Check that data was actually captured (see sweep count)
  - Try clicking "Select All" button

**Problem**: Plot updates very slowly
- **Solution**:
  - Reduce repeat count
  - Increase delay between samples
  - Close other resource-intensive applications

### Export Issues

**Problem**: "Failed to save data" error
- **Solution**:
  - Check output directory exists and is writable
  - Ensure filename doesn't contain invalid characters
  - Close any files with the same name that might be open

## Advanced Features

### Custom Analysis Scripts

After exporting CSV data, you can process it with custom Python scripts:

```python
import numpy as np
import pandas as pd

# Load data
data = pd.read_csv('adc_data_20251119_143045.csv', header=None)

# Extract channel data (assuming 4 channels, 20 repeats each)
channels = 4
repeats = 20

# Reshape each row
for idx, row in data.iterrows():
    values = row.values
    reshaped = values.reshape(channels, repeats)

    # Compute statistics per channel
    means = np.mean(reshaped, axis=1)
    stds = np.std(reshaped, axis=1)

    print(f"Sweep {idx}: means={means}, stds={stds}")
```

### Automated Testing

The GUI can be controlled programmatically for automated testing:

```python
# Example: Automated sweep across multiple configurations
configs = [
    {'channels': '0,1', 'repeat': 10, 'delay': 0},
    {'channels': '0,1', 'repeat': 50, 'delay': 100},
    {'channels': '0,1,2,3', 'repeat': 20, 'delay': 50},
]

for config in configs:
    # Set parameters
    # Run capture
    # Save data
    # Analyze results
    pass
```

## System Requirements

### Minimum
- **OS**: Windows 10, macOS 10.14, Linux (Ubuntu 18.04+)
- **Python**: 3.8+
- **RAM**: 2 GB
- **Disk Space**: 100 MB

### Recommended
- **OS**: Windows 11, macOS 12+, Linux (Ubuntu 22.04+)
- **Python**: 3.11+
- **RAM**: 4 GB
- **Disk Space**: 500 MB (for data storage)

## Dependencies

- **PyQt6** (>=6.4.0): GUI framework
- **pyserial** (>=3.5): Serial communication
- **pyqtgraph** (>=0.13.0): Real-time plotting
- **numpy** (>=1.21.0): Numerical operations

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

[Add your license here]

## Authors

- [Your Name] - Initial work

## Acknowledgments

- Arduino community for the excellent hardware platform
- PyQt and pyqtgraph developers for powerful Python tools

## Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Contact: [your email]

## Version History

### v1.0.0 (2025-11-19)
- Initial release
- Full feature implementation per specification
- Serial communication with Arduino
- Real-time plotting
- Data export with metadata
- Comprehensive GUI controls

## Future Enhancements

Potential features for future versions:
- [ ] FFT analysis and frequency domain visualization
- [ ] Trigger-based capture modes
- [ ] Multiple Arduino support (multi-channel systems)
- [ ] Data streaming to cloud storage
- [ ] Machine learning integration for signal classification
- [ ] Custom plugin system for user extensions

---

**Happy Data Acquisition! 📊⚡**
