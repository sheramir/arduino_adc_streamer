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

- `ConfigurableParameters.h`: all pins, speeds, ADC limits, buffering defaults,
  ADS7953 range, validation, and optional 555 pins.
- `src/ApiProtocol.*`: the unchanged host frame and command helpers.
- `src/UsbSerialController.*`: `*`-terminated USB command collection, ACKs, and
  binary writes.
- `src/SpiController.*`: Teensy SPI bus and chip-select transactions.
- `src/AdcDevice.h`: replaceable ADC interface.
- `src/Ads7953Adc.*`: ADS7953 manual-mode channel selection, two-frame pipeline
  handling, returned-channel validation, and 12-bit extraction.
- `src/PztController.*`: four-lane acquisition, channel/repeat/buffer/ground
  configuration, and binary block streaming.
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

PZT commands are `mode PZT`, `channels`, `repeat`, `buffer`, `ground`, `run`,
`stop`, `status`, `mcu`, and `help`. `ref`, `osr`, `gain`, `conv`, `samp`, and
`rate` are accepted as compatibility no-ops because ADS7953 resolution and
reference behavior are not equivalent to MG24/Teensy internal-ADC controls.

PZR uses the existing `mode PZR`, `rb`, `rk`, `cf`, `rxmax`, and `ascii`
vocabulary. With the default `kEnablePzrHardware=false`, `mode PZR*` fails
safely. Configure the six PZR pins and enable the flag only on a PCB revision
that includes a 555 circuit.

## PZT sample order and two arrays

Each requested channel produces four samples:

```text
channel 0 repeat 0: ADC1, ADC2, ADC3, ADC4
channel 1 repeat 0: ADC1, ADC2, ADC3, ADC4
...
```

ADC lanes 1/2 belong to physical sensor array 1 and lanes 3/4 belong to array
2. The Python app now derives this width from the `PCB_TestBoard_7953` MCU
profile instead of assuming two lanes. In an `array_layout` sensor mapping,
use `mux: 1..4` as the ADC lane and `channels: 0..15` as ADS7953 input numbers.

No binary-parser change is required. A parameter-only change was not enough:
the Sensor editor and display/pressure/ghost-removal index calculations needed
the four-lane profile added in this change.

The current sensor library still represents one 3x3 spatial grid per saved
configuration. Four-lane acquisition and plotting can combine sensors from
both physical arrays in that grid. If both complete 3x3 arrays must be shown as
two independent grids at the same time, that is a separate UI/data-model
feature; the PCB wiring and desired two-grid layout are needed before defining
it safely.

## Bring-up checklist

1. Install Teensyduino/Arduino CLI and compile for Teensy 4.1. Confirm every
   source under `src/` is compiled.
2. With ADCs disconnected or held inactive, verify all four CS lines idle high
   and both clocks are idle low.
3. Connect one ADC at a time. Send `channels 0*`, `repeat 1*`, `buffer 1*`, then
   `run 100*`; inspect `status*` for returned-channel errors.
4. Apply known DC inputs to channels 0 and 15 on every ADC. Confirm payload
   order ADC1, ADC2, ADC3, ADC4 and codes stay within `0..4095`.
5. Repeat on both SPI buses and then with all four ADCs populated. Check MISO
   tri-state behavior while each sibling CS is high.
6. Exercise multi-channel/repeat/buffer cases and verify count equals
   `unique_channels * repeat * buffer * 4`.
7. Test `stop*` and timed runs. Finally enable ground reads if a grounded ADC
   input exists and increase SPI clock only after scope validation.

## ADS7953 implementation note

The initial driver favors correctness over maximum throughput: it repeats each
manual channel command through the documented two-frame latency and validates
the returned channel nibble. Once hardware capture confirms timing and signal
integrity, this can be optimized into a pipelined or Auto-1 scanner behind the
same `AdcDevice` interface.

References: [TI ADS7953 product page](https://www.ti.com/product/ADS7953),
[TI ADS79xx datasheet](https://www.ti.com/lit/ds/symlink/ads7953.pdf), and
[PJRC Teensy 4.1 hardware page](https://www.pjrc.com/store/teensy41.html).
