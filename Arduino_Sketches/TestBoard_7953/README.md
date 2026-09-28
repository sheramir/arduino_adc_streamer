# TestBoard 7953 PlatformIO project

PlatformIO project for the Teensy 4.1 TestBoard firmware. The original Arduino
IDE source this project was migrated from is archived at
`../legacy/PCB_TestBoard_7953-OLD_DONT_USE` for reference only; this project
is the active firmware and is arranged with implementation files in `src/`
and headers in `include/`.

Build from this directory with `pio run`. Upload with `pio run -t upload` when
the Teensy is connected. The project uses the latest Teensy platform resolved
by PlatformIO and does not pin a framework version.

The firmware uses Teensy's native USB `Serial`. The configured serial baud is
retained for host compatibility; it does not set the native USB link speed.
Hardware behavior still requires board bring-up validation.

## Board Description

The TestBoard hosts four Texas Instruments ADS7953 ADCs (12-bit, 16-channel,
SPI, internal MUX) driven by a single Teensy 4.1. The four ADCs are split
across two independent SPI buses and grouped into two logical sensor arrays:

- **Array 1**: ADC1 + ADC2, on SPI bus 1 (Teensyduino `SPI`)
- **Array 2**: ADC3 + ADC4, on SPI bus 2 (Teensyduino `SPI1`)

Each ADC has 16 analog input channels (`Ch0`-`Ch15`). Host software addresses
a specific input as an `adc:channel` route (1-based ADC number, 0-based
channel), and only explicitly routed inputs are ever sampled. This supports
sparse wiring where different sensors are attached to different channels
across the four ADCs, and lets the host select array 1, array 2, or both.

A `PZT` (piezo) acquisition path is the primary use case (`PztController`),
driving all four ADS7953 devices. A `PZR` (555 resistance/displacement) path
also exists (`PzrController`) for a possible future PCB revision, but its
hardware is disabled by default on this board (see
[Optional 555/PZR Hardware](#optional-555pzr-hardware)).

## Pin Map

All pins are defined in `include/ConfigurableParameters.h`; update them there,
not in controller code.

### SPI 1 - Array 1 (ADC1 + ADC2), Teensyduino `SPI`

| Signal | Teensy pin |
| --- | --- |
| MISO | 12 |
| MOSI | 11 |
| SCK | 13 |
| ADC1 `CS` | 9 |
| ADC2 `CS` | 24 |

### SPI 2 - Array 2 (ADC3 + ADC4), Teensyduino `SPI1`

| Signal | Teensy pin |
| --- | --- |
| MISO | 39 |
| MOSI | 26 |
| SCK | 27 |
| ADC3 `CS` | 32 |
| ADC4 `CS` | 33 |

### SPI Bus Settings

| Setting | Value |
| --- | --- |
| SCLK | 10 MHz (ADS7953 supports up to 20 MHz; raise only after checking signal integrity on both buses) |
| Bit order | MSB first |
| SPI mode | Mode 0 |
| Minimum `CS` high time | 40 ns |

### Optional 555/PZR Hardware (Disabled)

`PzrController` is compiled in but inert: all pins default to `-1` and
`kEnablePzrHardware = false`, so `mode PZR*` returns `#NOT_OK` until a future
PCB revision assigns non-conflicting pins, sets
`kEnablePzrHardware = true`, and is validated on hardware.

## Serial Protocol

### Transport And Framing

| Setting | Value |
| --- | --- |
| Baud rate | `460800` (native USB `Serial`; does not set the physical link speed) |
| Command terminator | `*` |
| Text encoding | ASCII |
| Binary transport | raw bytes on the same serial port |

Text commands are terminated by `*` and acknowledged with `#OK`/`#OK <args>`
or `#NOT_OK`/`#NOT_OK <args>`, matching the shared protocol described in
`../README.md`. `run*` is the one exception: on success it transitions
directly into binary streaming without a text ACK, matching PCB1.7 behavior.

### Binary Block Format

Identical layout to the other sketches (see `../README.md#binary-block-format`):

```text
[0xAA][0x55][countL][countH][samples...][avg_dt_us][block_start_us][block_end_us]
```

Each `uint16` sample belongs to one explicitly routed `adc:channel` pair
(never a fixed/implicit channel order). `avg_dt_us` is the average time per
sample in the block, and `block_start_us`/`block_end_us` are `micros()`
timestamps bracketing the whole block, letting the host compute the actual
sampling rate.

### Commands

| Command | Purpose |
| --- | --- |
| `mode PZT\|PZR*` | Select acquisition path; `PZR` fails unless the 555 hardware is enabled |
| `mcu*` | Print `# TestBoard_7953` |
| `help*` | Print the command summary |
| `status*` | Print current mode and controller state |
| `stop*` | Stop acquisition in both controllers |
| `array 1\|2\|both*` | Restrict routing to array 1 (ADC1/2), array 2 (ADC3/4), or both |
| `scanorder interleaved\|array\|adc*` | Select payload/acquisition order (see [Scan Modes](#scan-modes)) |
| `adcchannels adc:channel,...*` | Set the explicit sparse route list, e.g. `adcchannels 1:0,1:1,2:10*` |
| `vmid channel*` / `vmid true\|false*` | Set/enable/disable the Vmid park channel read after each route |
| `ground ...*` | Legacy alias for `vmid ...*` |
| `ref 2.5\|5*` | Select the ADS7953 input range: `2.5` = 1xVREF (2.5V full-scale), `5` = 2xVREF (5V full-scale); board VREF is fixed at 2.5V |
| `run*` / `run <ms>*` | Start continuous or timed streaming |
| `osr*`, `gain*`, `conv*`, `samp*`, `rate*` | Accepted no-ops kept for host protocol compatibility; ADS7953 has fixed 12-bit conversion |
| `rb*`, `rk*`, `cf*`, `rxmax*`, `ascii*` | `PZR`-mode only; require enabled 555 hardware |

The desktop app builds `adcchannels` from its fixed TestBoard wiring profile
and the user's Physical Arrays + PZT Sensors selection. There is no
`channels`, `repeat`, or `buffer` command in `PZT` mode: every configured
route is sampled exactly once per frame.

## Scan Modes

`scanorder` controls both the order routes are read over SPI and the order
samples appear in the binary payload. All three modes only ever touch routes
configured via `adcchannels`.

- **`adc`** - group strictly by physical ADC: every route on ADC1, then every
  route on ADC2, then ADC3, then ADC4 (regardless of the order routes were
  configured in). Captured with a single buffered block write.
- **`interleaved`** (default) - round-robin one route at a time across all
  four ADCs: first route of ADC1, first of ADC2, first of ADC3, first of
  ADC4, then second route of each ADC that still has one, and so on. This
  minimizes time skew between all four ADCs. Also uses the buffered block
  write.
- **`array`** - like `interleaved`, but scoped separately per array: array 1
  (ADC1/ADC2) is fully interleaved and streamed out as one chunk, then array 2
  (ADC3/ADC4) is fully interleaved and streamed out as a second chunk, both
  inside the same binary frame (one header, one trailer). This path streams
  each array's samples over USB as soon as they're captured instead of
  building the whole block in RAM first.

After each route's sample is read, if Vmid parking is enabled
(`vmid <channel>*` or `vmid true*`), that ADC lane is immediately switched to
the parked/dummy channel so a just-sampled sensor input does not remain
connected to the ADC between sweeps.

### Worked Example

Wiring (per the pin map, ADC1/ADC2 are on SPI1, ADC3/ADC4 are on SPI2):

- ADC1: `Ch0`-`Ch9` wired (10 routes), Vmid park channel `Ch15`
- ADC2: `Ch0`-`Ch14` wired (15 routes), Vmid park channel `Ch15`
- ADC3: `Ch0`-`Ch9` wired (10 routes), Vmid park channel `Ch15`
- ADC4: `Ch0`-`Ch14` wired (15 routes), Vmid park channel `Ch15`

Configured with `adcchannels 1:0,1:1,...,1:9,2:0,...,2:14,3:0,...,3:9,4:0,...,4:14*`
and `vmid 15*` (so `vmid_park_enabled_ = true`, park channel `15`). Total
routes = 10 + 15 + 10 + 15 = **50**, so every frame contains 50 samples
regardless of `scanorder`. In every mode, reads stay strictly sequential (one
SPI transaction group at a time) even though ADC1/ADC2 and ADC3/ADC4 sit on
independent buses - `scanorder` only changes the visiting order, not
concurrency. After **every** sample read, the same ADC is immediately
re-read on its Vmid channel (`Ch15`) and that reading is discarded; this
"read sample, then park" pair repeats for each of the 50 routes in all three
modes.

**`scanorder adc*`** - read order (P = park read on `Ch15`, discarded):

```text
ADC1:Ch0,P ADC1:Ch1,P ... ADC1:Ch9,P
ADC2:Ch0,P ADC2:Ch1,P ... ADC2:Ch14,P
ADC3:Ch0,P ADC3:Ch1,P ... ADC3:Ch9,P
ADC4:Ch0,P ADC4:Ch1,P ... ADC4:Ch14,P
```

One USB block is sent, built in RAM and written after all 50 reads complete:

```text
[0xAA][0x55][50,0][ADC1:Ch0..Ch9 (10)][ADC2:Ch0..Ch14 (15)][ADC3:Ch0..Ch9 (10)][ADC4:Ch0..Ch14 (15)][avg_dt_us][block_start_us][block_end_us]
```

**`scanorder interleaved*`** - round-robin one channel index ("depth") at a
time across all four ADCs, skipping any ADC that has run out of routes at
that depth:

```text
depth 0-9  (all 4 ADCs have a route): ADC1:ChD,P ADC2:ChD,P ADC3:ChD,P ADC4:ChD,P   (repeated for D = 0..9)
depth 10-14 (only ADC2/ADC4 still have routes): ADC2:ChD,P ADC4:ChD,P              (repeated for D = 10..14)
```
i.e. `ADC1:Ch0,P ADC2:Ch0,P ADC3:Ch0,P ADC4:Ch0,P, ADC1:Ch1,P ADC2:Ch1,P ADC3:Ch1,P ADC4:Ch1,P, ... ADC1:Ch9,P ADC2:Ch9,P ADC3:Ch9,P ADC4:Ch9,P, ADC2:Ch10,P ADC4:Ch10,P, ... ADC2:Ch14,P ADC4:Ch14,P`

Also one buffered USB block, sent after all 50 reads complete:

```text
[0xAA][0x55][50,0][ADC1:Ch0,ADC2:Ch0,ADC3:Ch0,ADC4:Ch0, ADC1:Ch1,ADC2:Ch1,ADC3:Ch1,ADC4:Ch1, ..., ADC1:Ch9,ADC2:Ch9,ADC3:Ch9,ADC4:Ch9, ADC2:Ch10,ADC4:Ch10, ..., ADC2:Ch14,ADC4:Ch14][avg_dt_us][block_start_us][block_end_us]
```

**`scanorder array*`** - the same depth round-robin as `interleaved`, but run
independently per array, and the two arrays are streamed to USB as two
separate chunks inside one frame instead of one RAM-built block:

```text
array 1 (ADC1+ADC2), depth 0-9: ADC1:ChD,P ADC2:ChD,P    (repeated D=0..9)
array 1, depth 10-14 (ADC1 exhausted): ADC2:ChD,P        (repeated D=10..14)
-> array 1 chunk = 25 samples: Ch0..Ch9 pairs (ADC1,ADC2), then ADC2:Ch10..Ch14

array 2 (ADC3+ADC4), depth 0-9: ADC3:ChD,P ADC4:ChD,P    (repeated D=0..9)
array 2, depth 10-14 (ADC3 exhausted): ADC4:ChD,P        (repeated D=10..14)
-> array 2 chunk = 25 samples: Ch0..Ch9 pairs (ADC3,ADC4), then ADC4:Ch10..Ch14
```

USB write order for `array` mode (header goes out before any sample is even
read, then each array's 25 samples are written as soon as that array finishes
its reads, and the trailer goes out last):

```text
1. usb write: [0xAA][0x55][50,0]                                     (header, sent immediately)
2. read+park all 25 array-1 routes (ADC1:Ch0,ADC2:Ch0,...,ADC2:Ch14)
3. usb write: [array 1's 25 samples]                                 (sent before array 2 is sampled)
4. read+park all 25 array-2 routes (ADC3:Ch0,ADC4:Ch0,...,ADC4:Ch14)
5. usb write: [array 2's 25 samples]
6. usb write: [avg_dt_us][block_start_us][block_end_us]               (trailer, sent last)
```

So `array` mode's on-the-wire bytes are identical in total content to
`interleaved`/`adc` (same 50 samples, same 16-byte header+trailer overhead),
but they arrive over USB as three separate writes instead of one, and array
1's data is available to the host before array 2 has even been sampled.

