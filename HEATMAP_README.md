# Heatmap Display Feature

## Overview

The ADC Streamer GUI now includes a real-time 2D pressure heatmap visualization for 5-sensor piezo arrays. The heatmap calculates center-of-pressure (CoP) and displays a Gaussian blob representation of pressure distribution.

## Architecture

### Modular Structure

The heatmap feature follows the existing modular architecture:

```
arduino_adc_streamer/
├── config_constants.py           # Heatmap configuration constants
├── data_processing/
│   ├── heatmap_processor.py     # CoP calculation & heatmap generation
│   └── simulated_source.py      # Simulated sensor data for testing
└── gui/
    ├── heatmap_panel.py         # Heatmap GUI components
    └── display_panels.py        # Tabbed interface (modified)
```

### Key Components

1. **HeatmapProcessorMixin** (`data_processing/heatmap_processor.py`)
   - Calculates center of pressure from 5 sensor values
   - Generates 2D Gaussian blob heatmap
   - Applies exponential moving average (EMA) smoothing
   - Pre-allocates buffers for performance

2. **SimulatedSensorThread** (`data_processing/simulated_source.py`)
   - Background thread generating test data
   - Simulates moving pressure point with noise
   - Runs at target FPS without blocking UI
   - Easily replaceable with real ADC data source

3. **HeatmapPanelMixin** (`gui/heatmap_panel.py`)
   - Creates pyqtgraph ImageItem for heatmap display
   - Numeric readouts for CoP and sensor values
   - Channel count validation and warnings
   - Colorbar with viridis colormap

## User Interface

### Tabbed Display

The right-hand panel now contains two tabs:

1. **Time Series** - Traditional ADC waveform display (existing functionality)
2. **2D Heatmap** - Real-time pressure heatmap (new feature)

The left-hand control panel remains constant across all tabs.

### Heatmap Tab Components

**Heatmap Display:**
- 160×80 pixel resolution (configurable)
- Viridis colormap with colorbar
- Gaussian blob centered at CoP position
- Updates at 30 FPS (configurable)

**Readouts Panel:**
- Center of Pressure: X and Y coordinates (normalized -1 to 1)
- Intensity: Total pressure magnitude
- Sensor Values: Individual readings [Top, Bottom, Right, Left, Center]

**Channel Validation:**
- Requires exactly 5 channels selected
- Displays warning if incorrect channel count
- Heatmap only updates when 5 channels configured

## Configuration Constants

All heatmap parameters are defined in `config_constants.py`:

```python
# Update rate
HEATMAP_FPS = 30

# Resolution
HEATMAP_WIDTH = 160
HEATMAP_HEIGHT = 80

# Sensor positions (normalized coordinates [-1, 1])
SENSOR_POS_X = [0.0, 0.0, 1.0, -1.0, 0.0]  # Top, Bottom, Right, Left, Center
SENSOR_POS_Y = [-1.0, 1.0, 0.0, 0.0, 0.0]

# Calibration factors (per-sensor scaling)
SENSOR_CALIBRATION = [1.0, 1.5, 2.5, 1.0, 2.0]

# Gaussian blob parameters
BLOB_SIGMA_X = 0.3  # Horizontal spread
BLOB_SIGMA_Y = 0.2  # Vertical spread

# Intensity scaling
INTENSITY_SCALE = 0.001

# Smoothing (0 = no smoothing, 1 = no history)
SMOOTH_ALPHA = 0.2

# Required channels
HEATMAP_REQUIRED_CHANNELS = 5
```

## Algorithm Details

### Center of Pressure Calculation

Given 5 sensor values `v[i]` and positions `(x[i], y[i])`:

1. **Apply calibration**: `v_cal[i] = v[i] × SENSOR_CALIBRATION[i]`

2. **Calculate weights**: `w[i] = max(v_cal[i], 0)`

3. **Total intensity**: `intensity = Σ w[i]`

4. **Center of pressure**:
   ```
   CoP_x = Σ(x[i] × w[i]) / (Σ w[i] + ε)
   CoP_y = Σ(y[i] × w[i]) / (Σ w[i] + ε)
   ```
   where ε = `COP_EPS = 1e-6` prevents division by zero

5. **Apply EMA smoothing**:
   ```
   CoP_x_smooth = α × CoP_x + (1-α) × CoP_x_prev
   CoP_y_smooth = α × CoP_y + (1-α) × CoP_y_prev
   intensity_smooth = α × intensity + (1-α) × intensity_prev
   ```
   where α = `SMOOTH_ALPHA = 0.2`

### Heatmap Generation

1. **Create coordinate grids**: Pre-computed X and Y grids spanning [-1, 1]

2. **Calculate distances**:
   ```
   dx = X_grid - CoP_x
   dy = Y_grid - CoP_y
   ```

3. **Gaussian blob**:
   ```
   heatmap = exp(-(dx²/(2σ_x²) + dy²/(2σ_y²))) × intensity × INTENSITY_SCALE
   ```

4. **Clip to range**: `heatmap = clip(heatmap, 0, 1)`

### Performance Optimizations

- Pre-allocated numpy buffers (reused every frame)
- Pre-computed coordinate grids (once at initialization)
- Float32 arrays for efficiency
- Vectorized numpy operations (no Python loops)
- Single-shot timer pattern prevents accumulation

**Target Performance**: 30 FPS on typical laptop hardware

## Usage

### Testing with Simulated Data

1. Launch the application: `uv run adc_gui.py`
2. Click the **"2D Heatmap"** tab
3. Heatmap simulation starts automatically
4. Watch the blob move across the display
5. Monitor readouts for CoP and sensor values

The simulation generates a sinusoidal traveling pressure point with realistic noise.

### Using Real ADC Data

To connect real sensor data:

1. **Configure 5 channels** in the ADC Configuration section
2. Sensor mapping (assumed order):
   - Channel 0: Top sensor (X=0, Y=-1)
   - Channel 1: Bottom sensor (X=0, Y=1)
   - Channel 2: Right sensor (X=1, Y=0)
   - Channel 3: Left sensor (X=-1, Y=0)
   - Channel 4: Center sensor (X=0, Y=0)

3. **Modify data source** in `adc_gui.py`:
   ```python
   # In update_heatmap() method, replace simulation with:
   self.use_simulated_data = False
   
   # Extract latest 5 channel values from raw_data_buffer
   # Use last sweep from circular buffer
   if self.raw_data_buffer is not None and self.sweep_count > 0:
       idx = (self.buffer_write_index - 1) % self.MAX_SWEEPS_BUFFER
       sensor_values = self.raw_data_buffer[idx, :5]  # First 5 channels
   ```

4. **Adjust sensor positions** in `config_constants.py` to match physical layout

5. **Calibrate sensors** by measuring responses and updating `SENSOR_CALIBRATION`

### Customization

**Adjust update rate:**
```python
HEATMAP_FPS = 60  # Smoother, higher CPU usage
```

**Change resolution:**
```python
HEATMAP_WIDTH = 320
HEATMAP_HEIGHT = 160
```

**Modify blob size:**
```python
BLOB_SIGMA_X = 0.5  # Wider blob
BLOB_SIGMA_Y = 0.3
```

**Adjust smoothing:**
```python
SMOOTH_ALPHA = 0.1  # More smoothing (slower response)
SMOOTH_ALPHA = 0.5  # Less smoothing (faster response)
```

**Change colormap:**
```python
# In gui/heatmap_panel.py, create_heatmap_display():
colormap = pg.colormap.get('plasma')  # or 'inferno', 'magma', 'cividis'
```

## Technical Notes

### Thread Safety

- Simulated data thread emits Qt signals (thread-safe)
- Heatmap updates run in main GUI thread via QTimer
- No explicit locking needed for sensor value storage

### Memory Usage

- Heatmap buffer: 160×80×4 bytes = 51.2 KB (negligible)
- Pre-computed grids: ~102.4 KB total
- Total overhead: <200 KB

### Future Enhancements

**Integration with ADC Data:**
- Extract latest sweep from circular buffer
- Map ADC channels to sensor positions
- Support dynamic channel reordering

**Advanced Features:**
- Historical CoP trajectory overlay
- CoP path recording and export
- Multiple blob detection (multi-touch)
- Configurable sensor geometry
- Auto-calibration routine

**Visualization:**
- 3D surface plot option
- Contour lines
- Vector field display
- Split-screen comparison

## Troubleshooting

**Heatmap not updating:**
- Check that you're on the "2D Heatmap" tab
- Verify simulation thread started (check status log)
- Ensure 5 channels selected (or ignore warning for testing)

**Performance issues:**
- Reduce `HEATMAP_FPS` to 15 or 20
- Lower resolution: `HEATMAP_WIDTH = 80`, `HEATMAP_HEIGHT = 40`
- Check CPU usage in task manager

**Calibration problems:**
- Measure each sensor's raw response to known pressure
- Calculate scaling factors: `calibration[i] = target / measured[i]`
- Update `SENSOR_CALIBRATION` list

**Coordinate mapping:**
- Verify sensor physical positions match `SENSOR_POS_X/Y`
- Use right-hand coordinate system (X: left→right, Y: down→up)
- Normalized coordinates: center=(0,0), edges=±1

## API Reference

### HeatmapProcessorMixin Methods

```python
def calculate_cop_and_intensity(self, sensor_values: list) -> tuple:
    """Returns (cop_x, cop_y, intensity)"""

def generate_heatmap(self, cop_x: float, cop_y: float, intensity: float) -> np.ndarray:
    """Returns 2D heatmap array (H×W)"""

def process_sensor_data_for_heatmap(self, sensor_values: list) -> tuple:
    """Complete pipeline. Returns (heatmap, cop_x, cop_y, intensity, sensor_values)"""
```

### HeatmapPanelMixin Methods

```python
def create_heatmap_tab(self) -> QWidget:
    """Creates heatmap tab widget"""

def update_heatmap_display(self, heatmap, cop_x, cop_y, intensity, sensor_values):
    """Updates visualization with new data"""

def show_heatmap_channel_warning(self, current_channels: int):
    """Displays channel count warning"""

def clear_heatmap_channel_warning(self):
    """Clears warning message"""
```

### SimulatedSensorThread

```python
class SimulatedSensorThread(QThread):
    sensor_data_ready = pyqtSignal(list)  # Emits [v0, v1, v2, v3, v4]
    
    def __init__(self, fps: int = 30)
    def run(self)
    def stop(self)
    def generate_sensor_values(self) -> list
```

## Dependencies

No new dependencies required! Uses existing packages:
- PyQt6 (GUI, signals, timers)
- pyqtgraph (heatmap ImageItem, colormap)
- numpy (array operations, Gaussian calculation)

## Testing Checklist

- [x] Tab switching (Time Series ↔ Heatmap)
- [x] Simulation starts/stops automatically
- [x] Heatmap displays and updates
- [x] CoP readouts update in real-time
- [x] Sensor value readouts display correctly
- [x] Channel count warning appears when ≠ 5 channels
- [x] Colorbar displays properly
- [x] Smooth rendering at 30 FPS
- [x] Clean shutdown (simulation thread stops)
- [ ] Real ADC data integration (TODO)
- [ ] Sensor calibration workflow (TODO)

## License & Credits

This feature integrates seamlessly with the existing ADC Streamer codebase while maintaining the modular architecture and clean separation of concerns.
