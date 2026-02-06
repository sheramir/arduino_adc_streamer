# Using the Modular Architecture

## Overview

Three versions are now available:

1. **`adc_gui.py`** - ✅ **Original (Recommended for production)**
   - Full-featured, tested, working application
   - Use this for actual data acquisition
   - 3,500 lines in single file

2. **`adc_gui_modular.py`** - 🔄 **Hybrid (Compatibility wrapper)**
   - Inherits from original for stability
   - Demonstrates how to gradually migrate
   - Same functionality as original

3. **`adc_gui_refactored_demo.py`** - 🎯 **Demo (Architecture proof-of-concept)**
   - Shows the fully modular architecture
   - Uses extracted modules (serial, MCU detection)
   - Minimal GUI for demonstration only

## Quick Start

### Production Use (Recommended)
```bash
python adc_gui.py
# or
uv run adc_gui.py
```

### Test Modular Architecture
```bash
python adc_gui_refactored_demo.py
# or
uv run adc_gui_refactored_demo.py
```

## What's Been Refactored

### ✅ Completed Modules

#### 1. serial_communication/ (~500 lines)
Extracted from original 3,500 line file.

**Files:**
- `serial_threads.py` - Background threads for non-blocking I/O
  - `SerialReaderThread` - ADC binary packet parsing
  - `ForceReaderThread` - Force sensor CSV parsing
  
- `adc_serial.py` - ADC serial communication (~220 lines)
  - `ADCSerialMixin` class with methods:
    - `update_port_list()` - Enumerate available ports
    - `connect_serial()` / `disconnect_serial()` - Connection management
    - `send_command()` - Fire-and-forget commands
    - `send_command_and_wait_ack()` - Verified command sending
    - `drain_serial_input()` - Buffer cleanup
  
- `force_serial.py` - Force sensor communication (~90 lines)
  - `ForceSerialMixin` class with methods:
    - `connect_force_serial()` / `disconnect_force_serial()`
    - `toggle_force_connection()`

**Benefits:**
- Serial logic isolated and testable
- Can mock serial port for unit tests
- Reusable in other projects

#### 2. config/ (~100 lines)
MCU detection and adaptation.

**Files:**
- `mcu_detector.py` - MCU detection mixin
  - `MCUDetectorMixin` class with methods:
    - `detect_mcu()` - Auto-detect MCU type (Teensy vs MG24)
    - `update_gui_for_mcu()` - Adapt GUI controls for MCU capabilities

**Benefits:**
- Easy to add new MCU types
- GUI adaptation logic centralized

### 📋 Placeholders Created

These directories have `__init__.py` files and are ready for extraction:

- **gui/** - GUI component creation (to be extracted)
- **data_processing/** - Data processing and analysis (to be extracted)
- **file_operations/** - Data export functionality (to be extracted)

## How the Modular Architecture Works

### Mixin Pattern

The refactored code uses **mixin classes** to add functionality:

```python
# Each module provides a mixin class
from serial_communication import ADCSerialMixin, ForceSerialMixin
from config import MCUDetectorMixin

# Main class inherits from all mixins
class ADCStreamerGUI(
    QMainWindow,
    ADCSerialMixin,      # Adds serial communication methods
    ForceSerialMixin,    # Adds force sensor methods
    MCUDetectorMixin,    # Adds MCU detection methods
):
    def __init__(self):
        super().__init__()
        # Methods from all mixins are now available
        self.connect_serial()  # From ADCSerialMixin
        self.detect_mcu()      # From MCUDetectorMixin
```

### Benefits

1. **Modularity** - Each file has 200-500 lines vs 3,500
2. **Testability** - Test mixins independently
3. **Maintainability** - Find bugs faster in smaller files
4. **Reusability** - Use modules in other projects
5. **Collaboration** - Multiple developers can work on different modules
6. **Backward Compatible** - Original file unchanged

## Testing the Modules

### Test Serial Communication Module

```python
# test_serial_comm.py
from serial_communication import SerialReaderThread
import pytest

def test_binary_packet_parsing():
    # Create mock serial port
    mock_port = MockSerial()
    thread = SerialReaderThread(mock_port)
    
    # Test binary packet
    buffer = bytearray([0xAA, 0x55, 0x02, 0x00, 0x34, 0x12, 0x78, 0x56])
    result = thread.process_binary_data(buffer)
    
    assert len(result) == 0  # Buffer should be empty after processing
```

### Test MCU Detection

```python
# test_mcu_detection.py
from config import MCUDetectorMixin

class TestGUI(MCUDetectorMixin):
    def __init__(self):
        self.current_mcu = None
        self.serial_port = MockSerial()

def test_teensy_detection():
    gui = TestGUI()
    gui.serial_port.inject_response("# Teensy4.1\n")
    gui.detect_mcu()
    assert gui.current_mcu == "Teensy4.1"
```

## Completing the Refactoring

To fully refactor the remaining code, extract to these modules:

### Phase 2: GUI Components (~1,000 lines)

Create `gui/control_panels.py`:
```python
class ControlPanelsMixin:
    def create_serial_section(self): ...
    def create_adc_config_section(self): ...
    def create_acquisition_section(self): ...
    # ... etc
```

### Phase 3: Data Processing (~800 lines)

Create `data_processing/adc_processor.py`:
```python
class ADCProcessorMixin:
    def process_serial_data(self, line): ...
    def process_binary_sweep(self, samples, ...): ...
    def parse_status_line(self, line): ...
```

### Phase 4: File Operations (~300 lines)

Create `file_operations/data_export.py`:
```python
class DataExportMixin:
    def save_data(self): ...
    def browse_directory(self): ...
```

## Migration Strategy

### Option 1: Gradual Migration (Safest)

1. Keep `adc_gui.py` as production version
2. Extract one module at a time
3. Test each module thoroughly
4. Update `adc_gui_modular.py` to use new modules
5. When all modules complete, switch to modular version

### Option 2: Fresh Start (Fastest)

1. Copy working methods from `adc_gui.py` to new modules
2. Create new main file using all mixins
3. Test comprehensive functionality
4. Rename when complete

## Directory Structure

```
arduino_adc_streamer/
├── adc_gui.py                      # ✅ Original (use this)
├── adc_gui_modular.py              # 🔄 Hybrid wrapper  
├── adc_gui_refactored_demo.py      # 🎯 Architecture demo
├── config_constants.py             # Configuration
├── buffer_utils.py                 # Utilities
│
├── serial_communication/           # ✅ COMPLETE
│   ├── __init__.py
│   ├── serial_threads.py          # Thread classes
│   ├── adc_serial.py              # ADC serial mixin
│   └── force_serial.py            # Force serial mixin
│
├── config/                         # ✅ MCU detection complete
│   ├── __init__.py
│   └── mcu_detector.py            # MCU detection mixin
│
├── gui/                            # ⏳ Placeholder
│   └── __init__.py
│
├── data_processing/                # ⏳ Placeholder
│   └── __init__.py
│
└── file_operations/                # ⏳ Placeholder
    └── __init__.py
```

## Documentation

- **README.md** - Main project documentation (updated)
- **README_REFACTORING.md** - Detailed architecture guide
- **GUIDE_MODULAR.md** - This file (usage guide)
- **GUI_README.md** - GUI user guide
- **BUFFER_OPTIMIZATION.md** - Performance tuning

## Troubleshooting

### Import Errors

If you get import errors:
```bash
# Make sure you're in the correct directory
cd c:\Code\arduino_adc_streamer

# Install dependencies
pip install -r requirements.txt
```

### Module Not Found

The modules use relative imports. Make sure you're running from the project root:
```bash
# Correct:
python adc_gui_refactored_demo.py

# Wrong (from inside a subdirectory):
cd serial_communication
python ../adc_gui_refactored_demo.py  # Will fail
```

## Next Steps

1. **Test the demo**: Run `adc_gui_refactored_demo.py` to see the architecture
2. **Review modules**: Examine `serial_communication/` and `config/` modules
3. **Continue refactoring**: Extract remaining functionality as needed
4. **Update this guide**: Document new modules as they're created

## Questions?

- See `README_REFACTORING.md` for complete architecture details
- Check `serial_communication/` for working examples
- Original `adc_gui.py` is always available as reference
