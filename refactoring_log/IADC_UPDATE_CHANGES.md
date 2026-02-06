# Arduino High-Speed IADC Update - GUI Changes

## Summary of Changes

Updated GUI to support Arduino's new high-speed IADC scan with oversampling and analog gain configuration.

## Arduino Changes (Context)

- **ADC**: Now using high-speed IADC scan with oversampling and analog gain
- **Ground reads**: Extra ground reads done internally on Arduino, NOT sent to PC
- **Binary protocol**: UNCHANGED - same header, count, data samples, and avg_dt_us footer

## GUI Changes Made

### 1. Removed Resolution Configuration

**Removed**:
- Resolution dropdown (8/10/12/16 bits)
- `res ...***` command
- `resolution` from config dictionaries
- All resolution-related UI and handlers

**Why**: IADC has fixed resolution, no longer configurable

### 2. Restricted Voltage Reference Options

**Before**: 1.2V, 3.3V, 0.8*VDD, External 1.25V

**Now**: Only two options
- `1.2V (Internal)` → sends `ref 1.2***`
- `3.3V (VDD)` → sends `ref vdd***`

**Removed**: 
- `ref 0.8vdd***`
- `ref ext***`

### 3. Added OSR (Oversampling Ratio) Configuration

**New UI Control**: Dropdown in ADC Configuration section
- Label: "OSR (Oversampling):"
- Options: `2`, `4`, `8`
- Default: `2`
- Tooltip: "Oversampling ratio: higher = better SNR, lower sample rate"

**Command**: `osr <value>***`
- Example: `osr 4***`

**Meaning**: Trades speed for noise reduction
- Higher OSR = Better signal-to-noise ratio
- Higher OSR = Lower effective sample rate

### 4. Added Gain (Analog Amplification) Configuration

**New UI Control**: Dropdown in ADC Configuration section
- Label: "Gain (Analog):"
- Options: `1×`, `2×`, `3×`, `4×`
- Default: `1×`
- Tooltip: "Analog amplification factor (1× to 4×)"

**Command**: `gain <value>***`
- Example: `gain 2***`

**Meaning**: Analog front-end amplification
- 1× = No amplification
- 4× = 4× signal amplification

## Updated Configuration Flow

### Old Flow:
1. Send `res 12***`
2. Send `ref vdd***`
3. Send channels, repeat, ground, buffer

### New Flow:
1. Send `ref vdd***` (or `ref 1.2***`)
2. Send `osr 2***` (or 4, 8)
3. Send `gain 1***` (or 2, 3, 4)
4. Send channels, repeat, ground, buffer

## UI Layout Changes

**ADC Configuration Section** now shows:
```
┌─ ADC Configuration ─────────────────┐
│ Voltage Reference:  [3.3V (VDD) ▼] │
│ OSR (Oversampling): [2 ▼]          │
│ Gain (Analog):      [1× ▼]         │
└─────────────────────────────────────┘
```

## Code Changes Summary

### Modified Files:
- `adc_gui.py`

### Key Changes:
1. **Config dictionaries** (`self.config`, `self.last_sent_config`, `self.arduino_status`):
   - Removed: `'resolution'`
   - Added: `'osr'`, `'gain'`

2. **UI Creation** (`create_adc_config_section()`):
   - Removed resolution dropdown
   - Restricted vref to 2 options
   - Added OSR dropdown
   - Added gain dropdown

3. **Event Handlers**:
   - Removed: `on_resolution_changed()`
   - Modified: `on_vref_changed()` (restricted mapping)
   - Added: `on_osr_changed()`
   - Added: `on_gain_changed()`

4. **Configuration Commands** (`send_config_with_verification()`):
   - Removed: `res ...***` command
   - Modified: `ref ...***` (only 1.2 and vdd)
   - Added: `osr ...***` command
   - Added: `gain ...***` command

5. **Status Parsing** (`parse_status_line()`):
   - Removed: `adcResolutionBits` parsing
   - Added: `osr` parsing
   - Added: `gain` parsing
   - Updated reference mapping

6. **Control Enable/Disable** (`set_controls_enabled()`):
   - Removed: `self.resolution_combo.setEnabled()`
   - Added: `self.osr_combo.setEnabled()`
   - Added: `self.gain_combo.setEnabled()`

## Binary Protocol - NO CHANGES

The binary block format remains **exactly the same**:
```
[0xAA][0x55][countL][countH]  // 4-byte header
[sample0_L][sample0_H]         // count × 2 bytes of uint16 samples
[sample1_L][sample1_H]
...
[sampleN_L][sampleN_H]
[avg_dt_us_L][avg_dt_us_H]    // 2-byte footer (timing)
```

No changes needed to binary parsing or data processing code.

## Testing Checklist

- [ ] Connect to Arduino with new firmware
- [ ] Verify reference options (only 1.2V and 3.3V visible)
- [ ] Test OSR configuration (2, 4, 8)
- [ ] Test gain configuration (1×, 2×, 3×, 4×)
- [ ] Verify configuration commands sent correctly
- [ ] Verify binary data still parsed correctly
- [ ] Test various OSR/gain combinations
- [ ] Verify timing display updates correctly
- [ ] Check ground pin functionality (internal reads not visible)
