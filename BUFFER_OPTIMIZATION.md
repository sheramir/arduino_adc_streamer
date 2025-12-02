# Buffer Optimization Implementation Summary

## Overview
Implemented an advanced buffer optimization system that calculates optimal `sweeps_per_block` values based on multiple factors including channel configuration, baud rate, target latency, and USB packet efficiency.

## New Constants Added to `config_constants.py`

```python
# Target latency for buffered blocks (seconds)
TARGET_LATENCY_SEC = 0.25  # ~250ms target (updated from 0.15s)

# Maximum samples buffer capacity on Arduino
MAX_SAMPLES_BUFFER = 32000

# USB CDC packet size (bytes) - used for optimizing block transfers
USB_PACKET_SIZE = 64
```

## New Helper Functions in `config_constants.py`

### 1. `calculate_optimal_sweeps_per_block()`
**Purpose**: Computes optimal sweeps_per_block candidates based on configuration and constraints.

**Parameters**:
- `channel_count`: Number of channels in the sweep sequence
- `repeat_count`: Number of repeats per channel
- `baud_rate`: Serial baud rate (default: 460800)
- `target_latency`: Target maximum latency in seconds (default: 0.25s)
- `max_candidates`: Maximum number of candidates to return (default: 5)

**Returns**: List of `(sweeps_per_block, metrics_dict)` tuples, sorted from largest to smallest.

**Metrics Calculated**:
- `total_samples`: Total samples in the block
- `block_bytes`: Total block size in bytes (header + samples + footer)
- `transmit_time_ms`: Estimated transmission time in milliseconds
- `usb_efficiency`: How well block aligns with USB packets (0-1, higher is better)
- `latency_ratio`: Ratio of transmit time to target latency
- `packets_needed`: Number of USB packets required
- `wasted_bytes`: Unused bytes in last USB packet

**Algorithm**:
1. Tests range of sweep counts from 1 to maximum allowed
2. Filters candidates that:
   - Exceed `MAX_SAMPLES_BUFFER` (32000 samples)
   - Exceed target latency (250ms)
3. Scores each candidate based on:
   - **USB efficiency** (40% weight): Minimizes wasted bytes in USB packets
   - **Latency utilization** (30% weight): Prefers 70-90% of target latency
   - **Block size** (30% weight): Larger blocks preferred (more efficient)
4. Returns top candidates sorted by score, then by size

### 2. `validate_and_limit_sweeps_per_block()`
**Purpose**: Validates sweeps_per_block and limits it to maximum allowed by buffer capacity.

**Parameters**:
- `sweeps_per_block`: Requested sweeps per block
- `channel_count`: Number of channels in sweep sequence
- `repeat_count`: Number of repeats per channel

**Returns**: Valid `sweeps_per_block` value (limited if necessary)

**Behavior**: If requested value would exceed `MAX_SAMPLES_BUFFER`, returns maximum allowed value.

## GUI Integration in `adc_gui.py`

### Updated Imports
```python
from config_constants import (
    ...,
    MAX_SAMPLES_BUFFER, USB_PACKET_SIZE,
    calculate_optimal_sweeps_per_block, validate_and_limit_sweeps_per_block
)
```

### Modified Methods

#### 1. `suggest_sweeps_per_block()`
- **Changed return type**: Now returns `(best_sweeps, candidates_list)` tuple
- **Uses advanced optimization**: Calls `calculate_optimal_sweeps_per_block()`
- **Provides detailed metrics**: Returns top 3 candidates with full metrics

#### 2. `update_buffer_suggestion()`
- **Enhanced display**: Shows suggested sweeps, transmit time, and block size
  - Example: `(suggested: 101 sweeps, 219.3ms, 10106 bytes)`
- **Auto-update**: Automatically sets buffer size to suggested value if at default (10)
- **Handles edge cases**: Gracefully handles invalid configurations

#### 3. `on_buffer_size_changed()` - NEW
- **Real-time validation**: Validates whenever user changes buffer size
- **Automatic limiting**: Limits to maximum allowed if exceeds `MAX_SAMPLES_BUFFER`
- **User feedback**: Logs warning when buffer size is limited
- **Example log**: `Buffer size limited to 640 sweeps (32000 samples) - Arduino buffer capacity is 32000 samples`

#### 4. `configure_arduino()`
- **Enhanced validation**: Uses `validate_and_limit_sweeps_per_block()` before sending to Arduino
- **Automatic correction**: Corrects invalid buffer sizes before configuration
- **Better error handling**: Clear feedback when buffer size is limited

### UI Changes

#### Buffer Spin Box
- **Increased range**: 1-10000 (was 1-1000)
- **Connected to validator**: Calls `on_buffer_size_changed()` on value change
- **Real-time feedback**: Validates against buffer capacity as user types

#### Suggestion Label
- **More detailed**: Shows sweeps, time, and bytes
- **Color coded**: Gray color for visual distinction
- **Dynamic updates**: Updates when channels or repeat count change

## Example Results

### Configuration: 5 channels × 10 repeats = 50 samples/sweep

**Top Candidate**:
- Sweeps per block: **101**
- Total samples: 5050
- Block size: 10106 bytes (158 USB packets)
- Transmit time: **219.3ms** (87.7% of 250ms target)
- USB efficiency: **90.6%** (only 6 bytes wasted)

### Configuration: 10 channels × 10 repeats = 100 samples/sweep

**Top Candidate**:
- Sweeps per block: **47**
- Total samples: 4700
- Block size: 9406 bytes (147 USB packets)
- Transmit time: **204.1ms** (81.6% of target)
- USB efficiency: **96.9%** (only 2 bytes wasted)

## Benefits

1. **Optimal USB utilization**: Minimizes wasted bytes in USB packets (typically >85% efficiency)
2. **Consistent latency**: Targets 250ms blocks for responsive real-time display
3. **Respects hardware limits**: Never exceeds 32000 sample buffer capacity
4. **Automatic optimization**: Suggests best values based on actual configuration
5. **User-friendly**: Clear feedback when limits are exceeded
6. **Efficient transmission**: Balances block size with transmission time

## Testing

Run `test_buffer_optimization.py` to see detailed analysis of different configurations:
```bash
python test_buffer_optimization.py
```

This demonstrates:
- Optimal sweeps_per_block for various channel/repeat combinations
- USB efficiency calculations
- Buffer capacity validation
- Latency utilization metrics
