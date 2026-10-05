# TestBoard ADC124 benchmarks

`testboard_adc124_benchmark.py` owns the USB serial port, checks firmware
identity and status, configures a matrix, captures continuously through warm-up
and measurement, and compares DMA/LPSPI measurements with matching blocking
runs. Close the GUI and serial monitors first. Flash the ADC124 firmware,
keep sensors untouched for quiet benchmarks, and review the wiring and supply
validation in [`../README.md`](../README.md).

From the repository root:

```powershell
uv run python Arduino_Sketches/TestBoard_ADC124/benchmarks/testboard_adc124_benchmark.py --list-ports
uv run python Arduino_Sketches/TestBoard_ADC124/benchmarks/testboard_adc124_benchmark.py --dry-run
uv run python Arduino_Sketches/TestBoard_ADC124/benchmarks/testboard_adc124_benchmark.py --port COM7 --smoke-only
uv run python Arduino_Sketches/TestBoard_ADC124/benchmarks/testboard_adc124_benchmark.py --port COM7
```

Replace COM7 with the board's port. Dry-run opens no port and creates no output.
Default: 36 configurations x 3 repetitions, each with 1 second warm-up and
5 seconds measurement. It compares arrays 1/2/both, `mux`/`channel` scan order,
blocking/DMA/LPSPI engines, and 2/5 us settling, with repeat 1, Vmid off and
requested 16 MHz SPI. Allow about 11 minutes plus command/capture overhead.
Smoke mode tests nine combinations (three array selections x three engines)
with MUX order, repeat 1, Vmid off, 5 us settling, one repetition and at most
1 second measurement. Other requested array/engine/clock filters remain active.

Expand the analog/settling matrix explicitly:

```powershell
uv run python Arduino_Sketches/TestBoard_ADC124/benchmarks/testboard_adc124_benchmark.py `
  --port COM7 --arrays both --scan-order mux channel interleaved `
  --spi-clock-hz 8000000 12000000 16000000 --channel-repeat 1 2 3 `
  --mux-settle-us 0 2 5 10 --vmid off on --window-ms 2000 --repetitions 1
```

This example has 648 configurations; inspect its `--dry-run` first. The
settle value 0 retains the fixed switching allowances, but adds no analog
settling delay. SCLK requests are constrained to the ADC's 8–16 MHz AC range.

## Sparse routing

The manifest [`testboard_adc124_routes.json`](testboard_adc124_routes.json)
defines `full_array1`, `full_array2`, `both_full` and `pzt7_both`. The runner
checks reference and bias-resistor metadata against this board's fixed wiring.
Each route is `array:mux:input`; array number is also ADC number. Input numbers
are zero-based external MUX addresses; MUX numbers are 1–4 (ADC IN1–IN4).

```powershell
uv run python Arduino_Sketches/TestBoard_ADC124/benchmarks/testboard_adc124_benchmark.py `
  --port COM7 --route-set pzt7_both --arrays both --scan-order mux
uv run python Arduino_Sketches/TestBoard_ADC124/benchmarks/testboard_adc124_benchmark.py `
  --port COM7 --sensors 1 7 --arrays 1
uv run python Arduino_Sketches/TestBoard_ADC124/benchmarks/testboard_adc124_benchmark.py `
  --port COM7 --routes 1:1:0,1:4:6,2:2:0 --arrays both
```

`--sensors` filters by PZT numbers 1/3/5/6/7 on each array. PZT7 channels 1–4
are MUX1–MUX4 input 5; its fifth channel is MUX4 input 6. Duplicate/reserved
routes are rejected. Scan order determines actual acquisition and wire order;
the runner requires firmware `payload_routes` to match before starting.

## Artifacts and interpretation

Sessions default to a UTC timestamped folder below `benchmarks/results/`,
ignored by Git. `--output PATH` must name a new directory, preserving previous
sessions. Samples and raw USB bytes are written incrementally; only per-run
statistics stay in memory. Allow substantial disk space: every route sample
is retained. Choose shorter windows/filters for initial checks.

- `session.json`: arguments, board/route/resistor metadata, configuration
  matrix, session state and failure details.
- `commands.log`: timestamped commands and replies.
- `results.csv`: per-run PASS/WARN/FAIL, measured device rate, acquisition
  timing, parser diagnostics and firmware/received sweep counters.
- `channel_stats.csv`: per-route mean, sample standard deviation, extrema,
  Vmid offset, clipping and bias-resistor metadata, excluding warm-up.
- `comparisons.csv`: engine mean shifts, noise and throughput ratios against
  a successful blocking run with identical settings and repetition.
- `benchmark_report.xlsx`: Results, Channels, Engine comparisons and Notes.
- Each `TEST_ID__repN/` contains `capture.bin`, `samples.csv` (including
  warm-up and measurement phases), and before/after `status.json`.

`--no-raw` omits raw binary bytes; `--no-excel` omits the workbook. CSVs are
saved after every completed run. Ctrl+C requests stop, retains existing results
and the current partial raw/sample files, and records an interrupted session.
No resume/overwrite mode is implemented; use a new directory.

**FAIL** means incorrect status/identity, new or existing firmware errors,
malformed frames, impossible ADC codes, insufficient measured duration,
failure to become idle, or a mismatch between transmitted/received sweep
counts. The runner stops at the first failure and preserves its artifacts.
Reset the Teensy after a transfer fault before retrying.

**WARN** flags quiet mean offset over 100 counts from nominal Vmid code 2048,
noise standard deviation over 10 counts, or clipping at 0/4095. Engine
comparison rows warn on a mean shift over 5 counts. Set thresholds using
`--vmid-warn-counts`, `--noise-warn-counts`, `--shift-warn-counts`.
Comparisons are separate from the stream-validation result and are absent
when no matching successful blocking baseline exists. Analog drift between
runs can also produce engine mean shifts; repeat under stable conditions.

Rates use differences between **device sweep-start timestamps**, not the
host CSV-writing clock. USB backpressure and host logging can still affect
achieved rate. Samples share a sweep timing interval; exported start/end
timestamps are not individual ADC conversion times. ADC124S101 has no channel
identity tag, so a PASS cannot prove PCB channel wiring or detect every form
of corruption. Verify known-voltage routing and actual SCLK on hardware.
