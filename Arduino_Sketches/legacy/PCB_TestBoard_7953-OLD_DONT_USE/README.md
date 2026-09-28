# PCB TestBoard 7953 firmware

Self-contained Teensy 4.1 firmware for four ADS7953 ADCs on two SPI buses. The
top-level `PCB_TestBoard_7953.ino` only delegates to the firmware module; all
implementation sources are under `src/`, which Arduino IDE/CLI compiles
recursively.

## Current status

The architecture and host integration are implemented and covered by source
and Python routing tests. The sketch compiles for Teensy 4.1 with Teensy core
1.62.0. Hardware behavior is not yet validated because the PCB is not
available. Start board bring-up at the conservative 10 MHz SPI setting in
`ConfigurableParameters.h`.

## Pin map

| User bus name | Teensyduino object | ADCs | MISO | MOSI | SCK | chip selects |
| --- | --- | --- | ---: | ---: | ---: | --- |
| SPI1 | `SPI` | ADC1, ADC2 | 12 | 11 | 13 | 9, 24 |
| SPI2 | `SPI1` | ADC3, ADC4 | 39 | 26 | 27 | 32, 33 |

The apparent bus-name mismatch is intentional: Teensyduino calls the primary
pins 11/12/13 `SPI` and the secondary pins 26/27/39 `SPI1`.

## Modules

- `ConfigurableParameters.h`: all pins, speeds, ADC limits, ADS7953 range,
  validation, and optional 555 pins.
- `src/ApiProtocol.*`: the unchanged host frame and command helpers.
- `src/UsbSerialController.*`: `*`-terminated USB command collection, ACKs, and
  binary writes.
- `src/SpiController.*`: Teensy SPI bus and chip-select transactions.
- `src/AdcDevice.h`: replaceable ADC interface.
- `src/Ads7953Adc.*`: ADS7953 manual-mode channel selection, two-frame pipeline
  handling, returned-channel validation, and 12-bit extraction.
- `src/PztController.*`: sparse lane/channel routing, selectable acquisition
  order, Vmid parking, and one-sweep binary streaming.
- `src/PzrController.*`: optional 555/external-MUX resistance acquisition. It is
  compiled but disabled by default because this test board has no 555 circuit.
- `src/Firmware.*`: mode selection and command dispatch.

To use a different SPI ADC, implement `AdcDevice::begin()`, `channelCount()`,
`readChannel()`, and `errorCount()`, then replace the four `Ads7953Adc`
instances in `Firmware.cpp`. An ADC that uses GPIO for an external MUX should
perform that GPIO selection inside its `readChannel()` implementation. Neither
the PZT controller nor the USB protocol needs to change.

## Host protocol

The transport remains compatible with the Python app:

- Device response to `mcu*`: `# PCB_TestBoard_7953`
- Commands are ASCII and terminated by `*`.
- Success/failure uses `#OK [args]` / `#NOT_OK [args]`.
- Binary blocks remain
  `[AA 55][uint16 count][uint16 samples...][uint16 avg_dt_us]`
  `[uint32 block_start_us][uint32 block_end_us]`, all little-endian.

PZT commands are `mode PZT`, `array`, `scanorder`, `adcchannels`, `vmid`,
`run`, `stop`, `status`, `mcu`, and `help`. `ref`, `osr`,
`gain`, `conv`, `samp`, and `rate` are accepted as compatibility no-ops because
ADS7953 resolution and reference behavior are not equivalent to MG24/Teensy
internal-ADC controls. `ground` remains a compatibility alias for `vmid`.
`channels`, `repeat`, and `buffer` are intentionally not part of TestBoard PZT
acquisition.

PZR uses the existing `mode PZR`, `channels`, `rb`, `rk`, `cf`, `rxmax`, and
`ascii` vocabulary, with one measurement per selected channel per frame. With
the default `kEnablePzrHardware=false`, `mode PZR*` fails safely. Configure the
six PZR pins and enable the flag only on a PCB revision that includes a 555
circuit.

## Host board wiring profile

The GUI does not derive TestBoard routes from the editable Sensor-tab MUX
mapping. Fixed electrical wiring is defined in
`config/testboard_7953_board.py`; the sensor library remains responsible for
spatial placement and visualization. This separation prevents a sensor-layout
edit from changing physical ADC routing.

| Physical array | First ADC | Second ADC |
| --- | --- | --- |
| Array 1 | ADC1 | ADC2 |
| Array 2 | ADC3 | ADC4 |

The two arrays use the same relative wiring:

| PZT sensor | ADC position in pair | ADS7953 inputs | Input labels |
| --- | ---: | --- | --- |
| PZT6 | 1 | 0..4 | B, L, C, R, T |
| PZT7 | 1 | 5..9 | B, L, C, R, T |
| PZT1 | 2 | 0..4 | B, L, C, R, T |
| PZT3 | 2 | 5..9 | B, L, C, R, T |
| PZT5 | 2 | 10..14 | B, L, C, R, T |

When this MCU is detected, the GUI shows Physical Arrays and PZT Sensors but
hides the inapplicable generic ADC controls, Channels Sequence, PZR Sensors,
Repeat Count, and Sweeps per block.

## Lane-aware routes and two arrays

The app sends only requested `(ADC lane, ADS7953 input)` pairs:

```text
array both*
scanorder interleaved*
adcchannels 1:0,1:1,2:10,3:0,3:1,4:10*
```

`array 1` enables ADC1/ADC2, `array 2` enables ADC3/ADC4, and `array both`
enables both pairs. The host board profile resolves each selected PZT to the
first or second ADC in the pair and mirrors that route to the selected physical
array or arrays.

For example, `Array 1` plus PZT sensors `3,6` resolves to ADC2 inputs 5..9 and
ADC1 inputs 0..4. With interleaved order the sweep begins `ADC1:0, ADC2:5,
ADC1:1, ADC2:6, ...`; only those ten requested inputs are transmitted.

The three scan orders change both acquisition and payload order while keeping
the same set of route samples:

- `interleaved`: round-robin ADC1, ADC2, ADC3, ADC4, taking the next requested
  input from each ADC. This is the full-board channel-hopping experiment.
- `array`: complete array 1 by hopping between ADC1/ADC2, then complete array 2
  by hopping between ADC3/ADC4. The binary header and array-1 samples are queued
  to USB before array 2 is acquired; the host still receives one conventional
  complete frame.
- `adc`: complete every requested input on ADC1, then ADC2, ADC3, and ADC4.

Binary writes no longer call `Serial.flush()`. After a frame or frame segment
is queued, acquisition continues while the Teensy USB peripheral transmits,
subject to normal USB-buffer backpressure.

Each route produces exactly one sample, and every binary frame contains exactly
one complete sweep. The frame sample count therefore equals `number_of_routes`.
Python constructs the same ordered route list to calculate display, parser,
pressure-processing, ghost-removal, and export indices.

## Vmid parking

`vmid <channel>*` enables parking and selects a dedicated ADS7953 input.
`vmid false*` disables it. After reading a requested route, firmware
commands that same ADC to the Vmid input and discards the Vmid conversion. It
also parks every routed ADC before starting and immediately before stopping.
This prevents a PZT input from remaining connected through its bias resistor
while another ADC is sampled. Configuration fails if the Vmid input is also an
active data route. `ground` is retained only as a backward-compatible alias;
Vmid conversions are never included in the binary payload.

No binary framing change is required. The app uses the detected MCU name to
send the sparse route table and derive each sweep's exact width and labels.

Time-series traces retain separate `A1_...` and `A2_...` labels when both
physical arrays are selected. The current pressure-map data model still has one
3x3 grid per saved configuration, so with `Both arrays` it uses the first
selected physical array for that grid. Select `Array 1` or `Array 2` for an
unambiguous pressure map. Displaying two independent pressure-map grids at once
is a separate UI/data-model feature.

## Bring-up checklist

1. Install Teensyduino/Arduino CLI and compile for Teensy 4.1. Confirm every
   source under `src/` is compiled.
2. With ADCs disconnected or held inactive, verify all four CS lines idle high
   and both clocks are idle low.
3. Connect one ADC at a time. Send `array 1*`, `scanorder adc*`,
   `adcchannels 1:0*`, then `run 100*`; inspect
   `status*` for returned-channel errors.
4. Apply known DC inputs to channels 0 and 15 on every ADC. Confirm payload
   order ADC1, ADC2, ADC3, ADC4 and codes stay within `0..4095`.
5. Repeat on both SPI buses and then with all four ADCs populated. Check MISO
   tri-state behavior while each sibling CS is high.
6. Exercise all three scan orders and all three array selections. Verify count
   equals `route_count` and verify host labels follow the
   `status*` route/order report.
7. Attach Vmid to a dedicated input, enable `vmid`, and scope the ADC MUX output
   to confirm it parks after every requested route and remains parked after
   `stop*`. Increase SPI clock only after signal-integrity validation.

## ADS7953 implementation note

The initial driver favors correctness over maximum throughput: it repeats each
manual channel command through the documented two-frame latency and validates
the returned channel nibble. Once hardware capture confirms timing and signal
integrity, this can be optimized into a pipelined or Auto-1 scanner behind the
same `AdcDevice` interface.

References: [TI ADS7953 product page](https://www.ti.com/product/ADS7953),
[TI ADS79xx datasheet](https://www.ti.com/lit/ds/symlink/ads7953.pdf), and
[PJRC Teensy 4.1 hardware page](https://www.pjrc.com/store/teensy41.html).
