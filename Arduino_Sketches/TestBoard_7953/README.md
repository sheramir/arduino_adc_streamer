# TestBoard 7953 PlatformIO project

Active Teensy 4.1 firmware for four ADS7953 ADCs on two independent SPI
buses. Build with:

```text
pio run -d Arduino_Sketches/TestBoard_7953
```

The build is pinned to PlatformIO Teensy platform `6.0.0`, which currently
resolves Teensyduino framework `1.162.0`. Upload requires the physical Teensy:

```text
pio run -d Arduino_Sketches/TestBoard_7953 -t upload
```

The PlatformIO build applies a project-controlled USB transmit repair to a
build-local copy of the audited core. The installed framework is unchanged.
The repair enforces compiler ordering around the transmit/automatic-flush
guard and checks explicit-flush pending bytes under that guard. A changed
framework source causes a build error until the patch is reviewed. Use this
PlatformIO project to build the repaired firmware; an Arduino IDE build without
the middleware does not include the repair. USB transfers remain asynchronous.

PZT now uses an atomic nonblocking USB write: if USB cannot accept the complete
sweep immediately, discard that sweep and keep sampling. No acquisition backlog
is stored. Per-run status reports `sampling_sweeps`, `usb_frames_sent`,
`usb_frames_discarded`, `sampling_period_max_us` and `sampling_period_over_1ms`.
Unexpected write errors still stop acquisition and increment `usb_write_errors`;
PZR retains its original write path. Binary framing and commands keep their
existing layout. Previously accepted bytes in USB/Windows buffers can still
arrive late. See [live USB behavior and the reduced COM3 test](../../docs/architecture/TESTBOARD_7953_LIVE_USB_STREAM.md).
See [USB repair validation](../../docs/architecture/TESTBOARD_7953_USB_STREAM_DIAGNOSIS.md#implemented-repair)
for offline checks and the focused on-board benchmark.

## Optional phase profiling

The default `teensy41` build excludes profiling probes and storage. To build
the diagnostic firmware, select `-e teensy41_profile`; upload that environment
explicitly. It starts with profiling off. While stopped, `profile on*` enables
measurement and `profile off*` disables it without another upload. Changing the
setting while running is rejected. `status*` reports profile availability and
mode; detailed summaries are emitted only when stopped, never automatically
in the binary stream. Each accepted run resets its profiling statistics.

The benchmark's `--profile on` collects phase histograms, cycle counts, capacity
observations, and long-period snapshots in `firmware_profile.jsonl`. Default
`--profile off` normalizes the setting on diagnostic firmware, and stays
compatible with earlier firmware. Frames and payload timing fields are unchanged.
See [profiling instructions](../../docs/architecture/TESTBOARD_7953_PHASE_PROFILING.md)
for upload, a reduced COM3 comparison, measurement limits, and offline checks.

The current LPSPI candidate caches CS register access, specializes the word loop
by engine, and uses cycle-counter polling with bounded foreground servicing.
Both environments include it. The production 252-capture comparison passes
with clean raw streams. Manual LPSPI with both full arrays at 20 MHz reaches
16,889 sweeps/s, 60.5% above the original firmware. Long-gap latency and
electrical/analog acceptance remain separate work; see
[the production validation](../../docs/architecture/TESTBOARD_7953_LPSPI_PRODUCTION_RESULTS.md).

## Hardware map

| Array / physical bus | Teensy object | ADCs | MOSI | MISO | SCK | CS pins |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Array 1 / bus 1 | `SPI` (LPSPI4) | ADC1, ADC2 | 11 | 12 | 13 | 9, 24 |
| Array 2 / bus 2 | `SPI1` (LPSPI3) | ADC3, ADC4 | 26 | 39 | 27 | 32, 33 |

The buses default to 20 MHz, MSB first, SPI mode 0, and a minimum 40 ns CS-high
interval. `spiclock` can request 100 kHz through 30 MHz. The ADS7953 specifies
a 20 MHz maximum; 20–30 MHz remains experimental and outside the ADC
specification. Combined four-ADC testing passed at 30 MHz, while higher
achievable clocks produced returned-channel errors. Direct LPSPI mode uses these
same pins and software-controlled CS GPIOs. It requires no PCS, handshake, or
other additional board connection.

ADS7953 channel 15 is physically connected to Vmid and is reserved. It cannot
be included in `adcchannels`.

## Serial protocol

Commands are ASCII terminated by `*`. Successful configuration commands return
`#OK` and failures return `#NOT_OK`. Successful `run*` transitions directly to
binary streaming without a text ACK.

### Routing and payload order

```text
array 1*                       # enable ADC1/ADC2 on SPI
array 2*                       # enable ADC3/ADC4 on SPI1
array both*                    # permit both buses
adcchannels 1:0,1:1,2:10*     # sparse ADC/channel routes
scanorder interleaved|array|adc*
```

`array` is the authoritative physical-bus gate. `array 1` and `array 2` run
only their selected bus. `array both` permits parallel execution, but a second
bus is started only when it has configured routes.

`scanorder` controls binary payload order, not the physical execution engine.
Results acquired concurrently are placed back into the selected canonical
order. Every route still contributes exactly one `uint16_t` payload word.

### ADC sequencing and transfer engines

```text
adcseq manual*                 # explicit ADS7953 manual channel commands
adcseq auto1*                  # sparse ADS7953 Auto-1 channel mask
spiengine blocking*            # sequential SPIClass reference
spiengine dma*                 # EventResponder/DMA on both buses
spiengine lpspi*               # direct paired LPSPI start/poll
spiclock 20000000*             # both buses, 100 kHz..30 MHz; >20 MHz experimental
channelrepeat 1|2|3*           # manual settling conversions; retain final one
```

Manual mode pipelines the ADS7953 two-frame response delay. `channelrepeat`
performs one to three consecutive conversions per route but emits only the
last result, so it does not change frame width.

Auto-1 programs a persistent sparse mask for each active ADC. The mask also
enables the board-fixed Vmid channel 15 as the final sequence position. The
firmware captures each selected sensor channel once in ascending hardware
channel order, maps tagged responses back to the requested payload positions,
and stops clocking that ADC when the last sensor result has advanced its MUX to
Vmid. On the next sweep it discards the Vmid result and continues from the
first sensor without rewriting the mask. Its effective repeat is always one.

DMA uses Teensy SPI's byte-oriented asynchronous transfer API with persistent
per-bus buffers. Direct LPSPI uses the normal SPI pin mux established by
`SPI.begin()`/`SPI1.begin()`, then starts one 16-bit frame on each active
peripheral and polls internal receive flags with a bounded timeout.

The acquisition plan is prepared once at `run*`: payload destinations and
manual conversion/parking commands are cached for each ADC. Sweeps rewind
pipeline state rather than rebuilding those commands. Auto-1 retains its
persistent masks and rebuilds only the small startup/resume stream using cached
routes. In LPSPI mode each active bus uses one 16-bit SPI transaction per sweep,
with separate GPIO CS frames for every conversion. Session setup writes an
explicit 16-bit command while disabled rather than reading asynchronous TCR
state. Receive availability and a fresh transfer-complete flag are both checked
before CS release. Ordinary SPI state is
restored before USB enqueue and on acquisition failure.

This optimization candidate has been built and checked with offline digital
ADC models. On-board speed and analog behavior still need the matching
before/after benchmark and hardware checks below. See
[`firmware optimization notes`](../../docs/architecture/TESTBOARD_7953_FIRMWARE_OPTIMIZATION.md)
for comparison instructions and validation coverage.

`spiclock` is accepted only while stopped. `status*` reports the requested
value as `spi_clock_hz`; the Teensy SPI hardware may select the nearest
supported divider, so the requested value is not proof of the wire frequency.
Check actual SCLK with a logic analyzer. Treat returned-channel errors, transfer
timeouts, malformed/missing frames, or repeatable cross-clock sample shifts as
failure indicators when testing above 20 MHz.

### Vmid behavior

```text
vmid true*                     # sample Vmid between manual sensor routes
vmid false*                    # omit optional between-route Vmid conversions
vmid 15*                       # GUI-compatible equivalent of vmid true
ground ...*                    # legacy alias
```

No Vmid-channel command is needed: channel 15 is fixed by the board. Numeric
values other than 15 are rejected.

Optional Vmid sampling and mandatory parking are separate. `vmid false` does
not disable parking. Active ADCs are parked on channel 15:

- before a run starts;
- before another ADC takes ownership of the same SPI bus;
- at normal stop, timed stop, or acquisition failure.

When only one ADC is active on a bus, it is not parked between sweeps unless
optional manual Vmid sampling is enabled. When both buses change ADC ownership,
their parking frames are started together by DMA or direct LPSPI mode.

Auto-1 ignores optional between-channel Vmid sampling but still applies all
mandatory parking rules. During a run it normally parks without leaving
Auto-1: Vmid is the highest enabled mask bit, so the MUX reaches channel 15
immediately after the last sensor result. Manual Vmid commands remain the
startup, stop, failure-recovery, and explicit-mode-change fallback.

### Other commands

| Command | Purpose |
| --- | --- |
| `mode PZT|PZR*` | Select acquisition path; PZR is unavailable unless optional 555 hardware is configured |
| `mcu*` | Print `# TestBoard_7953` |
| `help*` | Print command summary |
| `status*` | Print requested/effective sequencing, engine, SPI clock, Vmid, topology, error counters, and cumulative Auto1 program/resume counts |
| `ref 2.5|5*` | Select ADS7953 1xVREF or 2xVREF input span |
| `run*` / `run <ms>*` | Start continuous or timed streaming |
| `stop*` | Park active ADCs and stop |
| `osr*`, `gain*`, `conv*`, `samp*`, `rate*` | Accepted no-ops for host compatibility |

## Binary frame

The shared frame layout is unchanged:

```text
[0xAA][0x55][countL][countH][uint16 samples...]
[avg_dt_us uint16][block_start_us uint32][block_end_us uint32]
```

All integer fields and samples are little-endian on USB. `sample_count` equals
the number of active routes and is identical across blocking, DMA, and LPSPI
engines for the same configuration.

## Required hardware validation

The code builds without a board, but electrical and analog behavior must be
validated on the connected TestBoard before benchmarking:

1. Confirm 16 SCLK edges per CS frame and the required CS-high interval.
2. Confirm `array 1` and `array 2` toggle only their selected bus.
3. Confirm DMA and LPSPI overlap bus-1 and bus-2 clocks with `array both`.
4. Confirm two CS lines on one physical bus are never asserted together.
5. Confirm the outgoing ADC is on Vmid before the other ADC's CS is asserted.
6. Compare channel identity, signal level, noise, and crosstalk across engines,
   manual/Auto-1 modes, repeats, and Vmid settings.
7. Run long captures and verify all error counters remain zero.

The board-specific host runner, route manifest, preparation steps, and output
format are documented in [`benchmarks/README.md`](benchmarks/README.md).
