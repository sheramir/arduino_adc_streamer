# Phase 4: Data Processing - Completion Report

## Overview

Phase 4 successfully extracted **~1,200 lines** of data processing code from the monolithic `adc_gui.py` into a dedicated `DataProcessorMixin` class.

## What Was Extracted

### Files Created

- **`data_processing/data_processor.py`** (1200 lines)
  - `DataProcessorMixin` class containing all data processing, plotting, and capture control logic

### Components Extracted

#### 1. Serial Data Processing (~90 lines)
**`process_serial_data(line)`** - ASCII data handling
- Logs status messages (lines starting with '#')
- Parses Arduino status messages
- Filters out binary garbage

**`parse_status_line(line)`** - Status parser
- Extracts channels from "#   1,2,3,4,5" format
- Parses key:value pairs (repeat, ground_pin, osr, gain, reference)
- Maps Arduino reference names to internal format

#### 2. Binary Data Processing (~250 lines)
**`process_binary_sweep(samples, avg_time, start_us, end_us)`** - Core data processing
- Thread-safe numpy circular buffer management
- Handles wrap-safe 32-bit MCU timestamps (Arduino micros() overflows ~71min)
- Tracks timing data (buffer receipt times, MCU block timestamps, gaps)
- Initializes/reinitializes buffers on config changes
- Validates sweep count against samples_per_sweep
- Streams to archive file (.jsonl) for full data persistence
- Streams block timing to sidecar CSV file
- Updates plot periodically (every PLOT_UPDATE_FREQUENCY sweeps)
- Calculates sweep timestamps with microsecond precision

#### 3. Force Data Processing (~70 lines)
**`calibrate_force_sensors()`** - Force calibration
- Collects 10 baseline samples
- Calculates average offsets for X and Z axes

**`process_force_data(x_force, z_force)`** - Force data handling
- Applies calibration offsets
- Timestamps relative to ADC capture start
- Rolling window (keeps only MAX_FORCE_SAMPLES)
- Debounced plot updates

#### 4. Plotting and Visualization (~430 lines)
**`update_plot()`** - Main plotting engine (~300 lines)
- Thread-safe access to circular buffer
- Handles three view modes:
  - **Full view**: Loads all data from archive (legacy list format)
  - **During capture**: Shows last window_size sweeps in scrolling mode
  - **After capture**: Shows windowed data from buffer
- Circular buffer indexing with wrap-around logic
- Extracts selected channels from checkboxes
- Numpy-optimized data extraction (no loops!)
- Handles multiple channel positions in sequence
- Supports 3 visualization modes:
  - **All repeats**: Separate lines for each repeat measurement
  - **Average**: Averages across repeats
  - **Single**: Shows all data together
- Voltage conversion (ADC counts → voltage)
- Downsampling to MAX_SAMPLES_TO_DISPLAY (10K points)
- Dynamic curve management (creates/hides curves as needed)
- Y-axis units (ADC counts or Voltage)

**`update_force_plot()`** (~80 lines)
- Time-based alignment with ADC data
- Extracts time window from buffer timestamps
- Numpy binary search for efficient filtering
- Downsampling to MAX_FORCE_POINTS (2000)
- Separate X and Z force curves (red and blue)

**`apply_y_axis_range()`** (~10 lines)
- Auto or manual Y-axis range
- Parses range strings ("0-4096", "0-3.3V")

#### 5. Timing Display (~80 lines)
**`update_timing_display()`** - Timing calculations
- Per-channel sample rate (Hz)
- Total sample rate (Hz)
- Average sample time (µs)
- Block gap time (ms) - prefers MCU timing over host timing
- Stores all timing data in dict for export
- Updates UI labels with formatted values

#### 6. Capture Control (~270 lines)
**`start_capture()`** (~160 lines)
- Validates configuration
- Locks configuration controls
- Thread-safe data clearing
- Creates archive files (.jsonl for data, .csv for timing)
- Writes metadata header to archive
- Sets binary capture mode on serial thread
- Sends "run" or "run <duration_ms>" command
- Updates UI state (buttons, plot interactions)

**`stop_capture()`** (~30 lines)
- Sends stop command with ACK verification
- Exits binary mode
- Flushes serial buffers
- Calls on_capture_finished()

**`on_capture_finished()`** (~80 lines)
- Records end time
- Stops force data collection
- Logs final timing summary
- Re-enables controls and buttons
- Closes archive files
- Final plot update
- Enable Full View button

**`set_controls_enabled(enabled)`** (~30 lines)
- Enables/disables all configuration widgets
- Prevents changes during capture

**`clear_data()`** (~70 lines)
- Confirmation dialog
- Thread-safe data clearing
- Resets all timing references
- Deletes all plot curves
- Recreates legends
- Resets plot ranges and zoom
- Flushes serial buffers

#### 7. Helper Methods (~10 lines)
**`get_vref_voltage()`** - Voltage reference lookup
- Maps reference strings to numeric voltages
- Supports 1.2V, 3.3V, 0.8×VDD, external

**`log_status(message)`** - Status logging
- Timestamps every message
- Auto-scrolls to bottom
- Limits to MAX_LOG_LINES to prevent memory overflow

## Key Features

### Circular Buffer Management
Uses numpy circular buffers (50K sweeps) for memory-efficient storage. Handles wrap-around indexing correctly for three view modes.

### Wrap-Safe Timestamps
Arduino micros() overflows every ~71 minutes (32-bit unsigned). All timestamp arithmetic uses `& 0xFFFFFFFF` to handle wrap-around correctly.

### Thread-Safe Operations
All buffer accesses use `with self.buffer_lock` to prevent race conditions between GUI and serial reader threads.

### Archive Streaming
Every sweep is immediately written to a `.jsonl` archive file (one JSON array per line). This ensures data persistence even if the app crashes.

### Optimized Plotting
- Numpy-based extraction (no Python loops)
- Downsampling to 10K points for responsiveness
- Dynamic curve creation/deletion
- Debounced updates to reduce CPU load

### MCU-Accurate Timing
Uses Arduino's MCU micros() timestamps for precise sample timing, not host PC clock. Accounts for serial transmission delays.

## Integration

### Updated Files

1. **`data_processing/__init__.py`**
   - Exports `DataProcessorMixin`

2. **`adc_gui_modular.py`**
   - Added `DataProcessorMixin` to class inheritance
   - Updated documentation (now 79% extracted)

3. **`adc_gui_refactored_demo.py`**
   - Added `DataProcessorMixin` to class inheritance
   - Removed data processing stub methods
   - Updated documentation to reflect Phase 4 completion

4. **`README_REFACTORING.md`**
   - Updated progress: 79% of codebase extracted (2,770 lines)
   - Marked Phase 4 complete

## Dependencies

The `DataProcessorMixin` depends on these attributes/methods from the parent class:
- **Serial/Thread**: `self.serial_thread`, `self.is_capturing`
- **Config**: `self.config`, `self.arduino_status`
- **Buffer**: `self.buffer_lock`, `self.raw_data_buffer`, `self.sweep_timestamps_buffer`, etc.
- **UI Widgets**: `self.plot_widget`, `self.force_viewbox`, `self.status_text`, timing labels, etc.
- **Methods**: `self.send_command()`, `self.send_command_and_wait_ack()`, `self.drain_serial_input()`
- **Constants**: `MAX_TIMING_SAMPLES`, `PLOT_UPDATE_FREQUENCY`, `MAX_FORCE_SAMPLES`, etc.

## Testing Recommendations

1. **Test circular buffer**:
   - Capture > 50K sweeps to trigger wrap-around
   - Verify timestamps remain monotonic
   - Check window_size correctly extracts recent data
   
2. **Test plotting modes**:
   - All repeats mode with repeat > 1
   - Average mode
   - Single mode
   - Toggle between ADC counts and Voltage units
   
3. **Test force integration**:
   - Verify X and Z force align with ADC timeline
   - Check calibration (tare before data collection)
   
4. **Test timing**:
   - Verify per-channel rate = total_rate / num_channels
   - Check block gap timing matches MCU values
   
5. **Test archive**:
   - Verify .jsonl contains all sweeps
   - Check metadata header
   - Verify block timing CSV has correct columns

## Benefits

1. **Separation of Concerns**: Data processing isolated from UI and config
2. **Maintainability**: 1,200 lines in focused module vs. scattered in 3,500-line file
3. **Performance**: Numpy-optimized operations, no Python loops
4. **Memory Efficiency**: Circular buffers prevent unbounded growth
5. **Data Persistence**: Archive streaming ensures no data loss
6. **Thread Safety**: Proper locking for concurrent GUI/serial access
7. **Testability**: Can mock buffer and test processing independently

## Statistics

- **Lines Extracted**: ~1,200
- **Methods Extracted**: 19
- **Total Extraction Progress**: 2,770 lines / 3,499 lines (79%)

## Next Steps

### Phase 5: File Operations (~300 lines)
Extract file I/O operations (final phase):
- `save_data()` - CSV export with metadata and range selection
- `save_plot_image()` - PNG/SVG plot export
- `full_graph_view()` - Load archive for full data view
- `browse_directory()` - Directory picker helper

## Conclusion

Phase 4 successfully extracted the largest and most complex module (~1,200 lines). The data processing pipeline is now:
- ✅ Isolated in dedicated module
- ✅ Thread-safe with proper locking
- ✅ Memory-efficient with circular buffers
- ✅ Optimized with numpy operations
- ✅ Persistent with archive streaming
- ✅ Accurate with MCU-based timing
- ✅ Easy to test and maintain

Both production versions (`adc_gui_modular.py`) and the demo (`adc_gui_refactored_demo.py`) now use `DataProcessorMixin` with no stub methods needed for data processing. The refactoring is 79% complete with only file operations remaining.
