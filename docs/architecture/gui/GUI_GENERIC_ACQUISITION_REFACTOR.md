# Shared, profile-driven GUI acquisition

Date: 9 October 2026. Firmware source and wire protocol are unchanged.

## Architecture

The detected MCU resolves through `config/boards/registry.json` into its immutable
board/mode profile. Board JSON owns supported modes, parameters, bounds, scaling,
physical capacity, transport and adapter selection. Sensor JSON owns connector
routes, physical array IDs and spatial placement. Python implements shared
algorithms and the distinct firmware protocol families.

The former board-named implementations are now shared modules:

| Responsibility | Implementation |
| --- | --- |
| Frozen identities, capture/display selection | `config/acquisition_runtime.py` |
| Descriptor creation and offline validation | `config/array_acquisition.py` |
| Array membership and scan ordering | `config/array_scan.py` |
| GUI controls for lane-aware arrays | `gui/array_panel.py` |
| Ordered, widget-free ingestion/filtering | `data_processing/acquisition_worker.py` |
| Capture lifecycle and newest-state rendering | `data_processing/live_acquisition.py` |
| Pipeline choice and startup validation | `config/boards/streaming.py` |

ADC grouping, array selection and routing no longer assume four lanes, two
arrays, channel numbers 0–15, or array IDs 1/2. Pressure Map reads placement
order from the active sensor configuration. Direct transitions between two
array profiles select their matching sensor layouts. Scalar handlers write
through semantic parameter IDs, including profiles without legacy state keys.
Captures retain their frozen identity when the connected board changes.

`modes.<mode>.streaming` explicitly selects `legacy_blocks` or
`batched_timed_sweeps`, and optionally specifies `render_interval_ms` (default
200). Omitted policies preserve the established block path. The ADS7953 profile
explicitly selects its existing batched path, at the same 200 ms cadence. The
validator rejects unknown policies, unsupported frame families, or a batched
contract with multiple results per route or multiple sweeps per frame.

New compatible boards select existing adapters in JSON. A different wire format
or command contract needs a protocol adapter; JSON cannot invent firmware
support. ADC124 remains a standalone benchmark project. The registry records
that explicitly and the connection workflow closes its session with a clear
unsupported-GUI error instead of applying generic ADC commands.

Board-named modules remain import-only compatibility facades. Old widget/state
names delegate to the canonical state through `config/legacy_array_api.py`;
they do not create a second worker or buffer. Old request/status fields and the
`testboard_acquisition` metadata key remain compatibility contracts. Installed
profiles do not reinterpret saved capture descriptors. State startup no longer
requires the optional ADS7953 profile to be installed.

## Performance preservation

The isolated USB reader, vectorized timed-u16 decoder, batch limits, bounded
queues, single processing consumer, ring buffers, archive batching, timestamp
extension, gap handling and display decimation are retained. Configuration and
lane groups resolve before ingestion; no registry lookup was added per sample
or frame. The named SPI/status routines remain confined to their protocol
adapter.

Each replay below ran for five seconds with live filters, the isolated reader,
fragmented reads, timestamp rollover and real archive output. Each before/after
matrix retained **920,000 sweeps**, showed visible traces and had zero parser
rejections. All queues drained.

| Routes | Sweeps/s | Recorded after / expected | Heartbeat p95 before (ms) | Heartbeat p95 after (ms) |
| --- | ---: | ---: | ---: | ---: |
| 50 | 12,000 | 60,000 / 60,000 | 20.6 | 19.7 |
| 50 | 17,000 | 85,000 / 85,000 | 17.0 | 21.0 |
| 10 | 60,000 | 300,000 / 300,000 | 13.2 | 14.9 |
| 50 | 20,000 | 100,000 / 100,000 | 18.9 | 20.6 |
| 10 | 75,000 | 375,000 / 375,000 | 13.8 | 14.6 |

The measured heartbeat variation is small relative to the 100 ms acceptance
target; these finite runs show retained throughput capacity, not an exact
latency guarantee for every machine or an indefinite hardware capture.

The 75,000 sweeps/s replay with a deliberate 500 ms source pause and a separate
GUI/GIL stall retained all 375,000 sweeps. Pipeline catch-up took
216.0 ms; a fresh plot followed
176.2 ms later. The maximum heartbeat
includes the deliberately injected stall. This additional stress case ran
concurrently with regression tests; it is not the before/after timing comparison.

Raw metrics: [GUI_GENERIC_ACQUISITION_REPLAY_RESULTS.json](../../testing/datasets/testboard-7953/GUI_GENERIC_ACQUISITION_REPLAY_RESULTS.json).

Supplementary three-second replays retained all 60,000 Pressure Map sweeps at
20,000/s, all 225,000 Spectrum sweeps at 75,000/s and all 60,000 Heatmap sweeps at
20,000/s. These also used filters, the isolated reader and fragmented reads,
with zero parser rejections. Their heartbeat p95 values were 16.8, 15.2 and
12.8 ms respectively. These are additional current-path checks, not paired
before/after timing comparisons or a visual inspection of every tab.

To reproduce the capacity comparison on the repository interpreter:

```powershell
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 5 --filters --isolated-reader --fragmented-reads
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 5 --filters --isolated-reader --fragmented-reads --stall --width 10 --rate 75000
.venv/Scripts/python.exe -m config.boards.audit
.venv/Scripts/python.exe -m pytest -q
```

## Verification and hardware check

The full regression suite passed: **1,050 tests**, five skips and 36 subtests.
All 116 previously present firmware source files retain their original hashes.

Regression coverage includes a JSON-only six-lane, three-array board with
nonconsecutive array IDs, 32 inputs per ADC, 16-bit samples, an external
4.096 V reference and different SPI defaults. Tests cover configuration commands,
all scan orders, each/all arrays, shared worker grouping, raw archive integrity,
timestamp rollover/gaps, offline descriptor validation and board transitions.
The board registry audit validates 13 GUI profiles, seven active GUI identities
and the explicitly standalone ADC124 identity.

No physical serial port was opened during this refactor. After restarting the
GUI, repeat the existing production-board capture, switch Display Array and
tabs, stop/restart and reload/export. Compare received/archive counts and check
queue ages. Firmware flashing is unnecessary.
