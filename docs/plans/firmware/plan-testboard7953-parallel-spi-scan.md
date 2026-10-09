## Plan: TestBoard_7953 Manual/Auto Scan Engines and Dual-SPI Parallelism

Status: IMPLEMENTED IN FIRMWARE - build and automated checks complete; physical
board validation and systematic benchmarking remain.

Rework the `Arduino_Sketches/TestBoard_7953` acquisition path so the same
firmware can run the configurations needed for a later hardware benchmark:

- manual ADS7953 sequencing with configurable `channelrepeat` from 1 to 3;
- ADS7953 Auto-1 sparse-channel sequencing, with each selected channel sampled
  exactly once;
- blocking SPI as the reference execution engine;
- DMA-backed parallel operation of the two physical SPI buses;
- direct Teensy 4.1 LPSPI start-and-poll parallel operation for comparison;
- optional Vmid conversions between manual-mode sensor channels;
- mandatory Vmid parking at startup, shutdown, and before changing from one ADC
  to the other ADC on the same physical SPI bus; and
- topology selection through the existing `array 1|2|both` command.

This plan implements and validates the selectable firmware modes. The systematic
on-device performance and signal-quality benchmark is a separate next step.

### Hardware terminology

Use unambiguous physical-bus names in code and documentation:

| Array / physical bus | Teensyduino object | ADCs sharing that bus |
| --- | --- | --- |
| Array 1 / SPI bus 1 | `SPI` | ADC1 and ADC2 |
| Array 2 / SPI bus 2 | `SPI1` | ADC3 and ADC4 |

Only one ADC on a physical bus can transfer at a time. `array 1` enables only
bus 1, `array 2` enables only bus 2, and `array both` enables both. When both
physical buses have work, the natural concurrent pairs are:

```text
pair 0: ADC1 on bus 1 || ADC3 on bus 2
pair 1: ADC2 on bus 1 || ADC4 on bus 2
```

At most two ADCs can therefore transfer simultaneously. ADC1 cannot overlap
ADC2, and ADC3 cannot overlap ADC4.

## Decisions

### 1. Keep payload order separate from the execution engine

Do not add `scanorder parallel`. Retain the existing
`scanorder interleaved|array|adc` values as the binary payload-order contract.

The acquisition scheduler may execute routes in a different order to use both
SPI buses efficiently, but every result is written into the destination slot
assigned by the selected `scanorder`. DMA and LPSPI modes must therefore produce
the same sample count and payload interpretation as blocking mode.

For example, firmware may acquire ADC1 and ADC3 together and then ADC2 and ADC4
together while storing the values into an existing payload order such as:

```text
ADC1, ADC2, ADC3, ADC4
```

This lets execution engines be compared without changing downstream sample
meaning. The binary header and trailer remain unchanged.

### 2. Reuse the existing Vmid command and fix Vmid to channel 15

`Vmid sampling` and `Vmid parking` are different operations:

- **Vmid sampling** means inserting a discarded Vmid conversion between manual
  sensor-channel conversions. It is selected by the existing `vmid` command.
- **Vmid parking** means leaving an inactive ADS7953 MUX connected to the
  board's Vmid input, channel 15. It is a mandatory safety/state invariant and
  cannot be disabled by the Vmid-sampling setting.

Parking rules:

1. Park every active ADC before a run starts.
2. Park the outgoing ADC before selecting the other ADC on the same physical
   SPI bus.
3. Park every active ADC when a run stops, times out, or fails.
4. If only one ADC has routes on a physical SPI bus, no between-route parking is
   required on that bus; park only at startup and stop unless manual Vmid
   sampling is enabled.
5. If one ADC is active on each physical bus, they may run in parallel without
   between-route parking because neither physical bus changes ADC ownership.
6. If two ADCs are active on one physical bus, the outgoing ADC must be fully
   parked before the scheduler begins transfers to the other ADC on that bus.
7. When two buses park concurrently, pair ADC1 with ADC3 or ADC2 with ADC4 so
   both outgoing ADCs finish parking before either bus advances to its next ADC.

`vmid false` therefore disables optional between-channel Vmid conversions; it
does not disable startup, stop, error-recovery, or device-switch parking.
`vmid true` enables those conversions. Keep accepting `vmid 15` for compatibility
with the current GUI, with the same effect as `vmid true`. Do not add separate
Vmid channel or Vmid-sampling commands. Because channel 15 is fixed by the
board routing, reject numeric Vmid values other than 15 for this firmware.

Channel 15 is reserved for Vmid and must not also appear as a sensor route.
Validate this regardless of whether `vmid` or `adcchannels` is configured first.

### 3. Respect the ADS7953 two-frame manual pipeline

An ADS7953 manual command written in frame N produces its selected-channel
result in frame N+2. The scheduler must track the command and expected response
for every ADC independently instead of assuming that the following frame
returns the newly requested channel.

For a self-contained one-sample operation that must leave the ADC parked before
switching devices, the minimum safe command pattern is conceptually:

```text
channel, Vmid, Vmid
```

The final frame returns the requested channel result and leaves no sensor
selection active or pending. This replaces the current six-frame behavior:

```text
channel, channel, channel, Vmid, Vmid, Vmid
```

When the same ADC continues running, the response pipeline may remain full and
commands may be interleaved more efficiently. A small per-ADC metadata FIFO must
associate every returned word with:

- the command/expected returned channel;
- its destination payload index, if any;
- the repeat index;
- whether the response is retained or discarded;
- whether the command is a sensor, Vmid, drain, or mode-control frame.

Returned channel nibbles remain validated. Pipeline priming, draining, mode
changes, and block boundaries must not leak stale results into the payload.

### 4. Define `channelrepeat` precisely

Add a TestBoard-specific `channelrepeat 1|2|3` setting.

In manual mode:

- it controls how many consecutive valid sensor conversions are performed for
  each configured route;
- only the final conversion is retained in the binary payload;
- earlier conversions are settling/discard conversions;
- every configured route still contributes exactly one payload word;
- the two-frame response pipeline is used instead of completing an independent
  three-frame `readChannel()` call for every conversion.

In Auto-1 mode:

- the effective repeat is always 1;
- `channelrepeat` remains stored as the requested manual-mode value but is
  ignored until manual mode is selected again;
- status reports both requested and effective values.

Do not reuse the generic `repeat` command in this phase. In the rest of the
repository, `repeat` normally changes the number of emitted samples and the
host's expected sweep width. `channelrepeat` does not change payload width.

### 5. Define manual and automatic ADC sequencing

#### Manual mode

Manual mode supports `channelrepeat 1..3` and optional Vmid sampling.

- With Vmid sampling disabled, pipeline consecutive routes on the same ADC.
- With Vmid sampling enabled, ensure at least one actual Vmid conversion occurs
  between sensor conversions; discard all Vmid results.
- Regardless of that flag, finish the required Vmid park sequence before
  switching to the other ADC on the same physical bus.
- Retain only the final valid sensor conversion for each route.

#### Auto-1 mode

Use ADS7953 Auto-1 rather than Auto-2 because Auto-1 supports a sparse selected
channel mask.

- Program each active ADC's Auto-1 mask from its configured `adcchannels`
  routes plus the fixed Vmid channel 15. Cache that mask until the route set
  changes instead of programming it on every sweep.
- Sample every selected channel exactly once per sweep.
- Hardware scans selected channels in ascending input-number order.
- Map returned `(adc, channel)` identities back to their payload destination
  indices; hardware scan order must not change wire interpretation.
- Ignore `channelrepeat`; effective repeat is 1.
- Ignore optional between-channel Vmid sampling, even when requested.
- Stop clocking an ADC immediately after its last sensor result. Because Vmid
  is the highest enabled channel, that frame has already advanced the MUX to
  channel 15; the ADC can remain selected in Auto-1 while the other device uses
  the shared bus.
- On the next sweep, discard the tagged Vmid result, then collect one result
  from every selected sensor channel. This resumes the persistent sequence
  without rewriting the mask or entering manual mode.
- Use manual Vmid commands only at startup, stop, failure recovery, or when a
  configuration/mode transition requires them.
- Re-entering Auto-1 from another mode resets to the first enabled sensor;
  persistent sweeps instead resume from the parked Vmid position.

Auto-1 configuration frames and pipeline priming/draining are overhead, not
payload samples.

### 6. Core configurations to benchmark later

The implementation must expose these six core runtime configurations:

| ADC sequencing | SPI engine | Expected bus behavior |
| --- | --- | --- |
| Manual | Blocking | Reference path; physical buses execute sequentially |
| Manual | DMA | Parallel paired frames when both buses have work |
| Manual | Direct LPSPI | Parallel paired frames when both buses have work |
| Auto-1 | Blocking | Auto-1 scans execute sequentially across physical buses |
| Auto-1 | DMA | Auto-1 frame clocks overlap when both buses have work |
| Auto-1 | Direct LPSPI | Auto-1 frame clocks overlap when both buses have work |

Manual-mode modifiers are `channelrepeat 1|2|3` and Vmid sampling on/off.
Auto-1 always uses effective repeat 1 and effective Vmid sampling off. Every
core configuration must support all route topologies, including cases where
only one physical bus is active and no parallel speedup is possible.

### 7. Let `array` determine the enabled physical buses

Use the existing `array 1|2|both` command as the authoritative bus-selection
input:

| `array` value | Enabled ADCs/buses | Parallel behavior |
| --- | --- | --- |
| `1` | ADC1+ADC2 on physical SPI bus 1 (`SPI`) | Single-bus execution; no cross-bus parallelism |
| `2` | ADC3+ADC4 on physical SPI bus 2 (`SPI1`) | Single-bus execution; no cross-bus parallelism |
| `both` | Both physical buses | Pair transfers only when both buses have active routes |

`array` gates which ADC lanes `adcchannels` may configure. The scheduler then
uses the active routes within those enabled buses to determine whether one or
two engines actually have work. Thus `array both` permits parallelism but does
not force it: if the configured routes use only one bus, execution remains
single-bus. `array 1` and `array 2` must never start the unselected LPSPI
peripheral or assert a chip select belonging to the other array.

## Runtime configuration protocol

Add only the TestBoard commands still needed to select benchmark combinations
without reflashing:

```text
adcseq manual*                    # manual ADS7953 channel commands
adcseq auto1*                     # sparse ADS7953 Auto-1 scan

spiengine blocking*               # reference SPIClass blocking engine
spiengine dma*                    # two-bus async DMA engine
spiengine lpspi*                  # two-bus direct LPSPI start/poll engine

channelrepeat 1*                  # manual only; retain final conversion
channelrepeat 2*
channelrepeat 3*
```

Reuse and clarify the existing commands:

- `vmid true*` enables optional manual between-channel Vmid sampling.
- `vmid false*` disables only optional between-channel sampling. It does not
  disable mandatory parking.
- `vmid 15*` remains accepted for the current GUI and behaves as `vmid true`.
  Other numeric values are invalid because TestBoard Vmid is physically fixed
  to ADC channel 15.
- The existing `ground ...*` alias remains compatible with `vmid ...*`.
- Existing `array 1|2|both*`, `adcchannels`, `scanorder`, `ref`, `run`, and
  `stop` commands remain valid. `array` controls which physical buses may run.
- Configuration-changing commands return `#NOT_OK` while acquisition is active.
- Unsupported engines or invalid values return `#NOT_OK`; never silently fall
  back to another engine during a benchmark.

Recommended initial defaults preserve the closest practical current behavior:

```text
adcseq manual
spiengine blocking
channelrepeat 3
array both
vmid false
```

The firmware always uses channel 15 for Vmid. Mandatory startup/stop/
device-switch parking still applies with these defaults.

Extend `status*` with at least:

```text
# adcseq=manual|auto1
# spiengine=blocking|dma|lpspi
# channelrepeat_requested=1|2|3
# channelrepeat_effective=1|2|3
# array=1|2|both
# vmid_channel=15
# vmid_between_channels_requested=true|false
# vmid_between_channels_effective=true|false
# active_adcs=...
# active_spi_buses=1|2|1,2
# dma_start_errors=...
# lpspi_start_errors=...
# transfer_timeouts=...
# returned_channel_errors=...
```

In Auto-1 mode, `channelrepeat_effective=1` and
`vmid_between_channels_effective=false`.

The GUI does not need new controls in this implementation phase. Existing GUI
configuration must continue to work through the compatibility aliases. A later
GUI change may expose these settings after benchmarking identifies useful
production modes.

## Execution engines

### Blocking reference engine

Use the normal blocking `SPIClass::transfer16(uint16_t)` primitive and the new
pipeline-aware scheduler. SPI bus 1 and SPI bus 2 execute sequentially. This is
the reference for determining the benefit of actual bus overlap without
retaining the current redundant six-frame sample-and-park implementation.

### DMA parallel engine

The installed Teensy SPI API does not provide an async `transfer16` overload.
Implement each async 16-bit frame with:

```cpp
SPIClass::transfer(tx_bytes, rx_bytes, 2, EventResponderRef)
```

Requirements:

- pack and unpack bytes explicitly in ADS7953 MSB-first order;
- use persistent, suitably aligned DMA-safe TX/RX buffers for each physical bus;
- call `beginTransaction()` before asserting CS;
- keep CS asserted until that bus's completion event fires;
- start one transfer on each bus, then wait for both;
- deassert both CS pins, end both transactions, and enforce CS-high time;
- reject a second outstanding transfer on the same bus;
- impose a bounded timeout;
- if one DMA start succeeds and the other fails, finish or abort the started side
  and restore both buses and CS pins before reporting failure;
- count start failures/timeouts and stop the run rather than emitting a silently
  corrupted block.

DMA is still performed per 16-bit CS frame, so its setup/event overhead must be
measured later rather than assumed to be faster.

### Direct LPSPI parallel engine

Add a Teensy 4.1-specific paired-frame primitive that uses the two underlying
LPSPI peripherals directly:

- reuse the already-connected standard SPI pins: MOSI, MISO, and SCK for `SPI`
  and `SPI1`;
- retain the existing ADC chip-select pins as ordinary software-controlled GPIO;
- do not require hardware PCS pins, extra handshake pins, or any board wiring
  change;
- treat LPSPI transmit/receive/completion "flags" as internal register bits,
  not external GPIO signals;
- let `SPI.begin()` and `SPI1.begin()` establish the normal Teensy pin mux, then
  keep direct register access isolated to the selected execution engine; and
- never mix a direct-register frame with an in-progress `SPIClass` transfer on
  the same peripheral.

The existing board connections remain:

| Physical bus | MOSI | MISO | SCK | Software CS |
| --- | ---: | ---: | ---: | --- |
| Bus 1 / `SPI` | 11 | 12 | 13 | ADC1 pin 9, ADC2 pin 24 |
| Bus 2 / `SPI1` | 26 | 39 | 27 | ADC3 pin 32, ADC4 pin 33 |

For the installed Teensy 4.1 framework, `SPI` is backed by LPSPI4 and `SPI1` by
LPSPI3. This is an implementation mapping, not an additional electrical
interface.

1. Configure both active peripherals for the established clock, mode, bit order,
   and 16-bit frame size.
2. Begin both transactions and assert both selected CS pins.
3. Write both transmit words to their respective transmit data registers.
4. Let both LPSPI peripherals clock concurrently.
5. Poll both completion/receive-ready flags with a bounded timeout.
6. Read both responses.
7. Deassert both CS pins, end both transactions, and enforce CS-high time.

The single-bus form uses the same implementation with only one active side.
Keep register-specific code isolated behind `SpiController` or a dedicated
`DualSpiFrameExecutor`; do not spread i.MX RT register access through
`PztController` or `Ads7953Adc`.

Document every register assumption and pin the PlatformIO Teensy platform
version used for development so future framework updates do not silently change
the tested low-level environment.

## Route-topology behavior

Build an execution topology from the existing `array` selection and configured
routes before every run:

| `array` | Active routes | Parallel opportunity | Between-route/device parking |
| --- | --- | --- | --- |
| `1` | One of ADC1/ADC2 | None | Startup and stop only, unless manual Vmid sampling is enabled |
| `1` | ADC1+ADC2 | None; both share bus 1 | Park outgoing ADC before every ADC1/ADC2 ownership change |
| `2` | One of ADC3/ADC4 | None | Startup and stop only, unless manual Vmid sampling is enabled |
| `2` | ADC3+ADC4 | None; both share bus 2 | Park outgoing ADC before every ADC3/ADC4 ownership change |
| `both` | One ADC total | None | Startup and stop only, unless manual Vmid sampling is enabled |
| `both` | One ADC on each bus | Yes, pair those ADCs | Startup and stop only on each bus, unless manual Vmid sampling is enabled |
| `both` | Three ADCs | Parallel while both buses have work | Apply switching parks only on the bus that has two active ADCs |
| `both` | All four ADCs | ADC1+ADC3, then ADC2+ADC4 | Park both members of an outgoing pair concurrently before advancing |

If paired sides have unequal route counts, continue until both sides of the
current pair are complete. The shorter side becomes idle/parked while the longer
side finishes. Do not switch an individual physical bus to its next ADC until
its outgoing ADC satisfies the parking invariant.

DMA and LPSPI engines must also work correctly when only one physical bus is
active. They may be slower than blocking mode in that topology; this is a valid
future benchmark result, not a reason to change engines silently.

## Implementation steps

1. **Pin and document the build environment.** Pin the tested PlatformIO Teensy
   platform version in `platformio.ini`, record the resolved Teensy framework
   version, and retain the current successful baseline build. This is especially
   important for direct LPSPI register access and the async SPI API. No behavior
   change yet.

2. **Add acquisition configuration and commands.** Introduce enums/state for
   ADC sequencing (`manual|auto1`), SPI engine (`blocking|dma|lpspi`), requested
   channel repeat (`1..3`), and requested Vmid sampling. Keep the existing
   `array` and `vmid` commands, make Vmid channel 15 a board constant, implement
   command validation, compatibility behavior, help text, and expanded status.
   Keep all configuration immutable while running.

3. **Replace whole-channel assumptions with frame/pipeline primitives.** Refactor
   `Ads7953Adc` so it can construct manual, Auto-1, Vmid, and mode-control words;
   validate returned channel identities; and track the two-frame pipeline. Keep
   `begin()` for startup initialization only. Do not add Teensy-specific async
   types to generic `AdcDevice` unless required; prefer a TestBoard-specific
   framed ADS7953 interface or coordinator.

4. **Implement the blocking pipeline engine.** Establish correct manual
   `channelrepeat`, optional Vmid sampling, mandatory switching parks, startup/
   stop parks, pipeline draining, and canonical payload placement before adding
   concurrency. Add Auto-1 mask programming and one-sample-per-route collection
   using the same result-placement logic.

5. **Implement the DMA paired-frame engine.** Add the byte-oriented async
   transfer primitive, persistent DMA buffers, paired begin/finish logic,
   timeouts, cleanup, and counters. Reuse the scheduler and payload placement
   from step 4; only frame execution changes.

6. **Implement the direct LPSPI paired-frame engine.** Add isolated Teensy 4.1
   register-level paired start/poll support with the same external result and
   failure contract as the DMA engine. Reuse the same scheduler.

7. **Add topology-aware scheduling.** Detect active ADCs per physical bus, form
   ADC1+ADC3 and ADC2+ADC4 stages only when `array both` and the routes require
   both buses. For `array 1` or `array 2`, instantiate only that bus's work.
   Handle uneven/partial route sets and enforce per-bus ownership/parking rules.
   Populate samples by destination index so all engines and ADC modes preserve
   the selected payload order.

8. **Harden run/stop/error transitions.** On normal stop, timed stop, invalid
   returned channel, DMA failure, or LPSPI timeout, restore CS high, end open
   transactions, park all active ADCs when communication remains possible, and
   leave the firmware responsive to text commands. Do not emit partial binary
   frames after a fatal acquisition error.

9. **Update firmware and protocol documentation.** Update `printHelp()`, status
   descriptions, `Arduino_Sketches/TestBoard_7953/README.md`, and the shared
   `Arduino_Sketches/README.md`. Document requested versus effective settings,
   Vmid sampling versus mandatory parking, Auto-1 ordering, and the fact that
   execution order can differ from payload order.

10. **Add automated non-hardware verification.** Add source-contract and pure
    scheduler tests for command validation, topology construction, pipeline
    response association, payload placement, parking decisions, Auto-1 masks,
    requested/effective settings, and failure cleanup. Build the PlatformIO
    firmware after each engine is added.

## Relevant files

Firmware:

- `Arduino_Sketches/TestBoard_7953/platformio.ini`
- `Arduino_Sketches/TestBoard_7953/include/ConfigurableParameters.h`
- `Arduino_Sketches/TestBoard_7953/include/SpiController.h`
- `Arduino_Sketches/TestBoard_7953/src/SpiController.cpp`
- `Arduino_Sketches/TestBoard_7953/include/AdcDevice.h`
- `Arduino_Sketches/TestBoard_7953/include/Ads7953Adc.h`
- `Arduino_Sketches/TestBoard_7953/src/Ads7953Adc.cpp`
- `Arduino_Sketches/TestBoard_7953/include/PztController.h`
- `Arduino_Sketches/TestBoard_7953/src/PztController.cpp`
- `Arduino_Sketches/TestBoard_7953/src/Firmware.cpp`
- `Arduino_Sketches/TestBoard_7953/README.md`
- `Arduino_Sketches/README.md`

Tests and protocol checks:

- `tests/test_firmware_source_contracts.py`
- new TestBoard scheduler/pipeline tests under `tests/`
- `tests/test_adc_configuration_service.py` for compatibility with the existing
  GUI command sequence
- `tests/test_testboard_scan.py` to prove payload order remains unchanged

Future GUI exposure is deliberately out of scope for this implementation. If
added later, likely host surfaces include `config/adc_config_state.py`,
`config/adc_configuration_service.py`, `config/config_handlers.py`,
`config/testboard_scan.py`, `gui/control_panels.py`, and their tests.

## Verification before the benchmark phase

### Automated checks

1. `pio run -d Arduino_Sketches/TestBoard_7953` succeeds with the pinned
   toolchain.
2. All existing Python tests continue to pass.
3. Command tests cover valid and invalid values, running-state rejection, aliases,
   fixed Vmid channel 15, `array` bus gating, and requested/effective status.
4. Scheduler tests cover all route topologies in the table above, including
   `array 1`, `array 2`, `array both`, unequal sides, and one empty physical bus.
5. Pipeline tests use synthetic returned channel tags to prove that stale,
   Vmid, settling, and Auto-1 setup results are discarded and every configured
   route fills exactly one correct payload slot.
6. Binary framing, sample count, and payload order are identical across
   `blocking`, `dma`, and `lpspi` for the same routes and `scanorder`.
7. Failure tests prove that a partial paired start cannot leave CS low or a
   transaction open.

### Hardware smoke checks required before systematic benchmarking

These checks validate correctness only; performance comparison belongs to the
next phase.

1. Logic-analyzer traces show exactly 16 SCLK pulses per CS frame and compliant
   CS-high/quiet time.
2. With `array both`, DMA and LPSPI paired modes visibly overlap bus-1 and bus-2
   clocks. With `array 1` or `array 2`, only the selected bus toggles.
3. No two ADC chip-selects on the same physical bus are asserted together.
4. An outgoing ADC reaches Vmid before its physical bus selects the other ADC.
5. A single-ADC route set performs no unnecessary between-route parks when
   Vmid sampling is disabled.
6. Manual `channelrepeat 1`, `2`, and `3` return the expected final route value
   and do not change payload width.
7. Auto-1 samples every sparse selected channel once, ignores requested repeat
   and Vmid sampling, and maps results to the same payload order as manual mode.
8. Long smoke runs show zero returned-channel errors, DMA start failures,
   transfer timeouts, missing samples, or malformed binary frames.

## Next phase: systematic hardware benchmark

The host-side runner is now implemented under
`Arduino_Sketches/TestBoard_7953/benchmarks/`.
It takes exclusive ownership of the Teensy's USB serial port, configures each
test without reflashing, reads the binary stream continuously, decodes every
frame, and writes reproducible CSV results. Offline parser, route-order,
configuration-matrix, aggregation, and resume tests are included. The remaining
work in this phase is the on-device smoke run and systematic measurements.

### Actions required from the user before the agent starts

1. Connect the TestBoard to stable power and connect the Teensy 4.1 to the
   computer with a known-good USB data cable.
2. Connect the intended sensors and analog front ends. Leave the sensors
   mechanically undisturbed during the benchmark unless a test explicitly asks
   for stimulation.
3. Confirm that Vmid is present and approximately half scale. For the benchmark
   `ref 2.5` configuration, the expected ADC code is approximately 2048 out of
   4095. A multimeter check of the board's Vmid node is recommended before a
   long run.
4. Flash the implemented `TestBoard_7953` firmware if it is not already on the
   Teensy. The agent can run the upload command, but the user must press the
   Teensy program button if the uploader requests it. After upload, allow the
   board several seconds to reset and re-enumerate.
5. Close the ADC Streamer GUI, Arduino Serial Monitor, PlatformIO monitor, and
   every other program that could hold the Teensy's serial port. Only the
   benchmark runner may read the binary stream.
6. Tell the agent which serial port belongs to `TestBoard_7953`, or allow the
   agent to enumerate ports and confirm the device with `mcu*`. Also choose an
   output directory for the benchmark artifacts.
7. Review and approve the route sets below. Remove any route that is not
   physically connected or biased on this board revision, and identify any
   channels whose expected DC level is intentionally not Vmid.
8. Keep USB wiring, board power, sensor connections, and the physical test
   environment unchanged until all repetitions finish. Do not open the GUI or
   touch the sensors during a run.
9. For the first DMA/LPSPI validation, optionally connect a logic analyzer to
   both SCLK signals and the four CS signals. The agent can interpret an exported
   trace, but the user must attach the probes and start/save the capture.
10. Choose an output drive with several gigabytes free. The interpreted sample
    CSV retains every valid route value and may be large for the full default
    matrix.

The benchmark must not begin until device identity, route selection, exclusive
serial access, and the approximate Vmid condition have been confirmed.

### Implemented benchmark runner

The command-line tool at
`Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py`, inside
the PlatformIO board project. Future test-board projects should use their own
peer `benchmarks/` directory, with arguments for:

- serial port;
- output directory;
- measurement window and warm-up duration;
- repetition count;
- one or more runtime SPI clocks from 100 kHz through 30 MHz, with values above
  the ADS7953's specified 20 MHz maximum treated as experimental;
- optional route-manifest override;
- optional subset of test IDs for resuming or debugging a session; and
- optional suppression of the generated Excel report.

Recommended initial defaults are:

```text
warm_up_ms = 1000
measurement_window_ms = 5000
repetitions = 3
serial_baud = 460800
reference = 2.5
scanorder = interleaved, except for the payload-order comparison group
```

The baud value is retained for API compatibility; Teensy's native USB serial
link does not operate at a UART baud rate.

### Preflight and command sequence

Before the first test, the runner must:

1. Open the port and discard only stale bytes that existed before the session.
2. Send `stop*`, wait for `#OK`, and confirm that the firmware accepts text
   commands.
3. Send `mcu*` and require the `# TestBoard_7953` identity.
4. Send `status*`, save the complete initial status, and require zero or
   explicitly acknowledged pre-existing error counters.
5. Run a short blocking/manual/single-ADC smoke capture and verify framing,
   expected sample count, route mapping, and plausible ADC values before
   starting the full matrix.

For each measured configuration, send and verify `#OK` for the following
commands in this order:

```text
stop*
array <1|2|both>*
scanorder <interleaved|array|adc>*
adcchannels <adc:channel,...>*
ref 2.5*
adcseq <manual|auto1>*
spiengine <blocking|dma|lpspi>*
spiclock <100000..30000000>*
channelrepeat <1|2|3>*
vmid <true|false>*
status*
```

The runner must parse the status response and verify the requested/effective
engine, SPI clock, ADC sequence, repeat, Vmid setting, active ADCs, and active
SPI buses.
It must not proceed if the firmware reports a different effective
configuration or silently falls back to another engine.

Run one continuous acquisition covering both warm-up and measurement:

```text
run <warm_up_ms + measurement_window_ms>*
```

A successful `run*` does not return a text ACK; binary data begins immediately.
The reader must therefore already be active before sending `run`. Classify
frames using wraparound-safe Teensy `block_start_us` deltas from the first
frame. Retain the initial frames for settling analysis but exclude all frames
before `warm_up_ms` from measured timing and signal statistics. Do not stop,
park, or reapply configuration at the warm-up boundary. After the combined
window plus its grace period, send `stop*` to force a known text-command state,
then request `status*` and save the final counters.

### Binary capture and interpretation

Decode the existing little-endian frame without changing firmware framing:

```text
[0xAA][0x55][sample_count uint16]
[sample_count x uint16 samples]
[avg_dt_us uint16][block_start_us uint32][block_end_us uint32]
```

The parser must:

- search for the `0xAA 0x55` header and resynchronize after any malformed data;
- validate `sample_count` against the configured route count for every frame;
- reject truncated frames and record malformed, resynchronized, or missing
  frame counts;
- map every payload index back to its `(ADC, channel)` route using the selected
  `scanorder` contract;
- record a monotonic host timestamp when each complete frame is received;
- compute all `uint32` Teensy timestamp differences with wraparound-safe
  arithmetic;
- keep reading continuously so host-side processing and CSV writing cannot
  create USB backpressure during acquisition; and
- perform decoding/CSV serialization after the measured window or on a separate
  consumer queue, never in the serial read loop.

Save the raw byte stream for each run when practical. Raw capture is not one of
the two required CSV deliverables, but it allows parser bugs or disputed results
to be investigated without rerunning the hardware.

### Route sets and topology coverage

The initial route manifest should contain these named cases. Ranges exclude
channel 15 because it is reserved for Vmid.

| Route-set ID | `array` | Default routes | Purpose |
| --- | --- | --- | --- |
| `one_adc_bus1` | `1` | ADC1 channels 0..9 | Single ADC, no device switching or parallel opportunity |
| `one_adc_bus2` | `2` | ADC3 channels 0..9 | Symmetric single-ADC check on the second bus |
| `full_array1` | `1` | ADC1 0..9 and ADC2 0..14 | Two ADCs sharing bus 1; exercises mandatory device-switch parking |
| `full_array2` | `2` | ADC3 0..9 and ADC4 0..14 | Two ADCs sharing bus 2; symmetric parking case |
| `one_adc_each_bus` | `both` | ADC1 0..9 and ADC3 0..9 | Balanced dual-bus case without same-bus device switching |
| `all_four_full` | `both` | ADC1/ADC3 0..9 and ADC2/ADC4 0..14 | Main 50-route throughput comparison |
| `all_four_sparse_unbalanced` | `both` | A documented sparse subset with unequal routes per ADC | Tests paired scheduling when one side finishes earlier |

The exact sparse list and any board-revision differences must be written into
the route manifest and copied into the result CSV. The runner must never infer
that an unlisted or floating input should be close to Vmid.

### Test matrix

Run the benchmark in stages so a wiring or parser problem is found before the
long matrix:

1. **Smoke tests:** blocking/manual, `channelrepeat 1`, `vmid false`, first on
   `one_adc_bus1`, then on `all_four_full`.
2. **Main engine comparison on `all_four_full`:**
   - manual x `blocking|dma|lpspi` x `channelrepeat 1|2|3` x
     `vmid false|true`;
   - Auto-1 x `blocking|dma|lpspi`, effective repeat 1 and effective
     between-channel Vmid sampling off;
   - one additional Auto-1 group requested with `vmid true` to verify that the
     effective status and performance remain equivalent to Auto-1 Vmid off.
3. **Topology comparison:** for every approved route set, run each SPI engine
   with manual/repeat-1/Vmid-off and with Auto-1. This measures single-bus
   overhead, same-bus device-switch cost, balanced parallel gain, and
   unbalanced-pair behavior.
4. **Parking comparison:** on `full_array1`, `full_array2`, and
   `all_four_full`, compare manual Vmid off/on for every engine.
5. **Payload-order equivalence:** on `all_four_full`, run
   `scanorder interleaved|array|adc` with blocking and both parallel engines.
   Timing may differ, but route identity and per-route values must remain
   correctly mapped.
6. **Drift controls:** repeat the same blocking/manual/repeat-1/Vmid-off
   reference configuration at the beginning, middle, and end of the session.

De-duplicate configurations that appear in more than one stage. Run three
measured repetitions per unique configuration by default. Randomize engine
order inside comparable groups, while keeping the beginning/middle/end drift
controls fixed. Repeat the selected matrix for every requested SPI clock and
compare only configurations having the same clock.

### Timing and performance calculations

For every valid frame calculate:

- acquisition duration:
  `(block_end_us - block_start_us) mod 2^32`;
- firmware-reported average time per payload sample, `avg_dt_us`;
- payload throughput:
  `sample_count * 1e6 / acquisition_duration_us`;
- per-route sweep rate, because every block contains one sample per route;
- device block period from consecutive `block_start_us` values;
- device inter-block idle/USB gap from the next `block_start_us` minus the
  previous `block_end_us`;
- host frame-arrival period from monotonic receive timestamps; and
- malformed, missing, timed-out, or resynchronized frame counts.

Aggregate each repeated test with count, minimum, maximum, mean, median,
standard deviation, p5, and p95. Use median acquisition duration as the primary
comparison. For identical parameters and routes, report:

```text
speedup_vs_blocking = blocking_median_duration / tested_median_duration
throughput_gain_pct = 100 * (tested_throughput / blocking_throughput - 1)
```

Compare DMA and direct LPSPI only with the blocking run having identical route
set, ADC sequence, repeat, Vmid request/effective state, reference, and scan
order. Do not claim a parallel speedup for `array 1` or `array 2`; those cases
measure engine overhead on a single bus.

### Signal and data-integrity checks

Timing is the primary goal, but every decoded sample must be retained and
checked. Use 2048 counts as the nominal Vmid code for the fixed `ref 2.5`
benchmark. Different op-amp bias resistors, sensor noise, and channel loading
mean channels are not expected to be identical.

Compare repeated measurements of the same physical `(ADC, channel)` route. Do
not treat, for example, ADC1 channel 0 and ADC2 channel 0 as equivalent analog
signals merely because their channel numbers match.

For every `(ADC, channel, test)` calculate sample count, minimum, maximum, mean,
median, p1, p5, p95, p99, standard deviation, median absolute deviation, and
median offset from 2048. Also retain the startup minimum and calculate settling
time as the first five-frame window within
`max(64 counts, 6 * measured MAD)` of the post-warm-up median. Apply warnings
rather than automatic timing-test failures:

- `VMID_OFFSET_WARNING`: median outside 1536..2560 (2048 +/- 512 counts);
- `VMID_OFFSET_SEVERE`: median outside 1024..3072, unless that route was marked
  as intentionally non-Vmid;
- `UNSTABLE_CHANNEL`: unusually large noise relative to the same channel's
  blocking reference;
- `CROSS_MODE_SHIFT`: for the same physical `(ADC, channel)`, the median differs
  from its blocking/manual reference by more than
  `max(128 counts, 6 * max(reference_MAD, test_MAD, 1))`;
- `DRIFT_WARNING`: the repeated reference median or timing changes materially
  between the beginning and end controls; and
- `SETTLING_EXCEEDS_WARMUP`: the route does not satisfy the settling rule before
  the measured window begins; and
- `DATA_INTEGRITY_FAILURE`: invalid frame size, impossible value outside
  0..4095, missing route, changed payload width, firmware channel error, or
  inconsistent payload mapping.

All thresholds must be columns/configuration values in the output rather than
hidden constants. Offset/noise warnings remain annotations unless accompanied
by framing, routing, or firmware errors. The report must explicitly note that
cross-mode differences can reveal settling, Vmid insertion, repeat-count, or
analog-front-end behavior and are not automatically firmware defects.

### Required output artifacts

Create a timestamped session directory containing the resumable CSV files plus
a review-oriented Excel report:

#### `benchmark_samples.csv`

One row per decoded route sample, with at least:

```text
session_id,test_id,repetition,frame_index,host_received_ns,
block_start_us,block_end_us,acquisition_duration_us,avg_dt_us,
sample_count,payload_index,array,adc,channel,sample_raw,
offset_from_vmid,route_warning
```

This is the interpreted form of the Teensy's binary stream. It must contain all
valid samples, including warm-up samples only if they are clearly marked and
excluded from measured summaries.

#### `benchmark_results.csv`

One row per unique test/repetition plus aggregate rows. It is both the test
manifest and comparison report, with at least:

```text
session_id,test_id,result_scope,repetition,route_set,array,route_list,
scanorder,adcseq,spiengine,spi_clock_hz,channelrepeat_requested,
channelrepeat_effective,vmid_requested,vmid_effective,ref,
window_ms,valid_frames,invalid_frames,total_samples,
sample_min_raw,sample_mean_raw,sample_median_raw,sample_max_raw,
sample_stdev_raw,
duration_min_us,duration_mean_us,duration_median_us,duration_p95_us,
payload_throughput_sps,sweep_rate_hz,block_period_median_us,
inter_block_gap_median_us,host_arrival_period_median_us,
speedup_vs_blocking,throughput_gain_pct,dma_start_errors,
lpspi_start_errors,transfer_timeouts,returned_channel_errors,
vmid_warning_count,cross_mode_shift_count,data_integrity_status,
overall_status,notes
```

#### `benchmark_channel_stats.csv`

One row per measured repetition and physical `(ADC, channel)`, containing the
sample count, minimum, mean, median, maximum, standard deviation, MAD, Vmid
offset, and route warnings. This makes analog comparisons possible without
mixing unrelated routes.

#### `benchmark_report.xlsx`

A formatted workbook containing an aggregate Summary with native timing, sweep
rate, and ADC-value charts, the complete Results and Channel Stats tables,
session metadata, and the output glossary. Keep the CSV files as the resumable
source of truth because the decoded sample stream can exceed Excel's worksheet
row limit.

Also save, when practical:

- `session_commands.log`: every command, ACK, status block, retry, and failure;
- `session_metadata.json`: firmware identity, git revision, operating-system and
  serial-port information, benchmark-runner version, thresholds, and start/end
  times;
- `raw/<test_id>_<repetition>.bin`: original binary bytes for reprocessing.
- `OUTPUT_GLOSSARY.md`: definitions and interpretation notes for every output
  field (maintained beside the runner and embedded as a workbook sheet).

Write CSVs atomically through temporary files or flush them after each completed
test so an interrupted long session preserves earlier results.

### Failure handling and resumption

- Abort a configuration if any command returns `#NOT_OK`, status does not match,
  or the binary sample count differs from the route count.
- If a run exceeds its window plus grace period, send `stop*`, save all bytes,
  mark the run timed out, and request status before deciding whether to retry.
- If an engine error counter increases, mark that repetition invalid, save its
  raw data, and retry it once after returning to blocking mode and performing a
  short smoke capture.
- Never replace a requested engine with another engine silently.
- Give every test a deterministic ID derived from its complete parameter set.
  On resume, skip only tests whose required repetitions and output rows are
  already complete and valid.
- Stop the session if device identity changes, the USB port disconnects
  repeatedly, framing cannot be recovered, or severe integrity failures appear
  across many channels. Ask the user to check power, USB, and analog wiring
  before continuing.

### Benchmark completion criteria

The benchmark phase is complete when:

1. every approved unique configuration has the required valid repetitions;
2. the CSV files can be reloaded and reproduce all aggregates and the Excel
   report;
3. every result row identifies the exact command parameters and route list;
4. blocking/DMA/LPSPI comparisons use matched configurations;
5. timing, USB-gap, jitter, and error-counter comparisons are present;
6. channels far from Vmid and same-channel cross-mode shifts are clearly noted;
7. malformed/missing frames and all retries are reported rather than discarded;
8. the beginning/middle/end reference controls show whether drift affected the
   session; and
9. the report clearly separates measured results from hardware behavior still
   requiring logic-analyzer or analog investigation.
