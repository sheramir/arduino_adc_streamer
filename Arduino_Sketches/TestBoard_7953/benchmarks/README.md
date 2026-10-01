# TestBoard 7953 benchmarks

This directory contains host-side benchmark tools for the TestBoard 7953
PlatformIO project. Other test-board projects can keep their own `benchmarks/`
directory alongside their firmware. Generated sessions are written below
`results/` by default and are ignored by Git.

## TestBoard 7953

`testboard_7953_benchmark.py` configures the Teensy over its command protocol,
captures the framed binary ADC stream, decodes it, compares acquisition modes,
and writes resumable benchmark artifacts.

Before running it:

1. Connect and power the TestBoard 7953 normally, with USB data connected.
2. Confirm the board has stable power and approximately Vmid-biased inputs.
3. Flash the current `Arduino_Sketches/TestBoard_7953` firmware.
4. Close the GUI, serial monitors, and every other process using the port.
5. Review `testboard_7953_routes.json`; channel 15 is reserved for mandatory
   parking and must not appear as a sampled route.
6. Review `testboard_7953_bias_resistors.json`. Each key is an `ADC:channel`
   route and each value is its bias resistance in ohms, such as
   `{"1:3": 1000000}`. The supplied board map expands ADC1=1 MOhm,
   ADC2=470 kOhm, ADC3=470 kOhm, and ADC4=249 kOhm across their populated
   sensor channels. Channel 15 is Vmid and is intentionally omitted. Values
   are copied into the warm-up export for later RC/capacitance fitting.
7. Keep the wiring, power, sensors, and physical environment unchanged for the
   complete session.
8. Choose an output drive with several gigabytes free. The runner deliberately
   retains every decoded route sample, so the default 210 measured runs
   can produce a large `benchmark_samples.csv`.

From the repository root, first inspect the available ports and planned matrix:

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py --list-ports
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py --dry-run
```

Run a short end-to-end smoke session before the full benchmark:

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py `
  --port COM7 --smoke-only --window-ms 1000 --repetitions 1
```

Run the default benchmark (1 s warm-up, 5 s measurement, three repetitions):

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py --port COM7
```

## Benchmark command-line flags

Run with `--help` to display the parser's short reference. The complete set of
runner flags is listed below. Unless stated otherwise, time values are
milliseconds and count/tolerance values are raw 12-bit ADC counts.

| Flag | Default | Explanation |
| --- | --- | --- |
| `-h`, `--help` | — | Print command usage and exit. |
| `--port <port>` | None | Teensy serial port, such as `COM7`. Required for acquisition, but not for listing ports/tests or a dry run. |
| `--baud <rate>` | `460800` | Serial baud rate used to open the Teensy port. USB serial transport may not use this as a physical line rate, but the host API still requires it. |
| `--spi-clock-hz <hz>` | `20000000` | Requested ADC SPI clock. Accepted range: 100,000–30,000,000 Hz. Values above the ADS7953's specified 20 MHz maximum are experimental. Repeat the flag to benchmark multiple clocks in one session; duplicate values are removed. |
| `--routes <path>` | `testboard_7953_routes.json` | Route-manifest JSON defining named route sets, arrays, sampled ADC channels, and channels exempted from Vmid checks. |
| `--bias-map <path>` | `testboard_7953_bias_resistors.json` | Optional JSON mapping physical routes such as `1:3` to bias resistance in ohms. Missing files are treated as an empty map. |
| `--output <directory>` | Timestamped directory under `benchmarks/results/` | Session output directory. A non-empty directory is rejected unless `--resume` is also supplied. |
| `--window-ms <ms>` | `5000` | Measured acquisition window after the warm-up portion of the same continuous run. Must be positive. |
| `--warm-up-ms <ms>` | `1000` | Initial portion of each continuous capture excluded from measured timing and signal summaries. Must be positive. |
| `--repetitions <count>` | `3` | Number of independent measured runs for every selected configuration. This is not `channelrepeat`: the default matrix separately tests manual `r1`, `r2`, and `r3`, and each configuration receives this many runs. Auto1 always uses `r1`. |
| `--grace-ms <ms>` | `3000` | Extra host capture time allowed after the requested firmware run window before declaring a timeout. |
| `--idle-ms <ms>` | `250` | Maximum interval without incoming serial data while a capture is expected before treating the stream as idle. |
| `--tests <substring>` | All configurations | Select test IDs containing the case-insensitive substring. Repeat the flag to match additional substrings; a configuration is selected when any supplied substring matches. |
| `--route-set <name>` | Built-in default matrix | Build a complete matrix for the named route set instead of using the built-in mixed-topology matrix. Repeat to include multiple route sets. Use with `--scan-order` for a focused complete benchmark. |
| `--scan-order <order>` | `interleaved` when a focused matrix is requested | Build a complete matrix for `interleaved`, `array`, or `adc` payload order. Repeat to include multiple orders. If neither focused-matrix flag is supplied, the normal built-in matrix is used. |
| `--smoke-only` | Off | Run only the baseline `one_adc_bus1` and `all_four_full` configurations. Drift controls are automatically disabled. Use this before a full session. |
| `--list-tests` | Off | Print route sets and the scheduled test list, then exit without opening the serial port. |
| `--list-ports` | Off | Print detected serial ports and exit. |
| `--dry-run` | Off | Print route sets and the complete scheduled test list, state that no port was opened, then exit. |
| `--resume` | Off | Continue an existing session, skipping completed PASS/WARN repetitions. Requires `--output` pointing to an existing compatible session directory. Use the same matrix and timing options as the original run. |
| `--allow-existing-errors` | Off | Permit nonzero cumulative firmware error counters at session startup. Any counter increment during an individual test still fails that test. |
| `--no-raw` | Off | Do not retain the original binary capture files under `raw/`. Decoded CSV results are still written. |
| `--no-excel` | Off | Skip generation of `benchmark_report.xlsx`. CSV, metadata, logs, and enabled raw captures are still produced. |
| `--no-drift-controls` | Off | Omit the beginning, middle, and ending baseline control captures used to detect timing drift across a long session. |
| `--seed <integer>` | `7953` | Seed used to randomize non-baseline configuration order. Reuse the same seed when reproducing or resuming a session. |
| `--vmid-code <count>` | `2048` | Nominal Vmid ADC code used by data-integrity checks. |
| `--vmid-warning-tolerance <count>` | `512` | Median distance from nominal Vmid that raises a channel warning. |
| `--vmid-severe-tolerance <count>` | `1024` | Median distance from nominal Vmid that raises a severe Vmid integrity result. |
| `--cross-mode-floor <count>` | `128` | Minimum absolute median shift considered by cross-mode comparison, preventing very small differences from being flagged. |
| `--cross-mode-mad-multiplier <value>` | `6.0` | Robust-noise multiplier used with channel MAD to set the cross-mode shift threshold. The effective threshold is at least `--cross-mode-floor`. |
| `--noise-floor <count>` | `32` | Minimum absolute spread threshold used when determining whether a channel is unusually noisy or unstable. |
| `--noise-mad-multiplier <value>` | `3.0` | MAD multiplier used with `--noise-floor` for channel-noise/instability checks. |
| `--settling-tolerance-counts <count>` | `64` | Minimum band around the post-warm-up median used by settling analysis. The effective band is the larger of this value and six measured MADs. Must be positive. |
| `--settling-stable-frames <count>` | `5` | Consecutive in-band frames required to declare a channel settled. Must be positive. |
| `--warmup-export-frames <count>` | `250` | Maximum number of pre-measurement frames exported for the first valid warm-up trace of each physical channel. Must be positive. |
| `--drift-timing-tolerance-pct <percent>` | `10.0` | Maximum allowed percentage change in control-test median duration relative to the beginning control before a drift warning is recorded. |

The runner does not expose `channelrepeat` as a command-line flag. It is part
of the built-in comparison matrix: manual mode tests `r1`, `r2`, and `r3`,
while Auto1 always samples each channel once. `--repetitions` controls how many
times every one of those configurations is measured.

For a complete benchmark restricted to `all_four_full` and ADC payload order,
run:

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py `
  --port COM7 --route-set all_four_full --scan-order adc
```

At one SPI clock this schedules 21 configurations: three engines multiplied by
six manual combinations (`r1`/`r2`/`r3`, Vmid off/on), plus one Auto1
configuration per engine. With the default three repetitions and three drift
controls, the session contains 66 measured runs.

Warm-up and measurement use one continuous firmware `run`. Initial frames are
classified by Teensy device timestamps and excluded from measured timing and
signal statistics without stopping, parking, or reconfiguring the ADCs between
the two windows. Per-channel settling uses five consecutive values within
`max(64 counts, 6 * measured MAD)` of the post-warm-up median. Override those
defaults with `--settling-tolerance-counts` and `--settling-stable-frames`.

Select one SPI clock, or repeat the option to include several clocks in the
same matrix without reflashing:

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py `
  --port COM7 --spi-clock-hz 5000000 --spi-clock-hz 10000000
```

The firmware accepts 100,000 through 30,000,000 Hz while stopped. Frequencies
above the ADS7953's specified 20 MHz maximum remain experimental. The 30 MHz
ceiling is the fastest clock that passed combined four-ADC benchmarking;
higher achievable clocks produced returned-channel errors. The runner
sends `spiclock`, verifies `spi_clock_hz` in `status`, includes the clock in each
test ID and comparison key, and records the requested clock in CSV, Excel, and
session metadata. Reflash the updated firmware once before using this option.

Use `--output <directory>` to choose the session directory. If a run is
interrupted, use the exact same options plus `--resume --output <directory>`.
Completed PASS/WARN repetitions are skipped, channel references are restored
from the existing sample CSV, and incomplete or failed repetitions are rerun.
Use one or more `--tests <substring>` arguments for a focused subset.
Resume only a session created by the same runner output schema. Version 2.2
adds continuous warm-up, settling columns, and the first-channel warm-up trace,
so start a new output directory instead of resuming an earlier benchmark.

The runner verifies firmware identity, requested/effective status, payload
route count, and error-counter deltas. A test that fails twice stops the session
and leaves all completed rows recoverable. Firmware error counters are
cumulative; after investigating a historical nonzero count, resume with
`--allow-existing-errors`. New increments still fail the affected test.

Each session contains:

- `benchmark_samples.csv`: decoded ADC values with route and timing fields;
- `benchmark_results.csv`: per-repetition and aggregate timing/comparison rows;
- `benchmark_channel_stats.csv`: per-test, per-ADC/channel sample statistics;
- `benchmark_warmup_samples.csv`: the first 250 continuous warm-up frames for
  the first valid test containing each physical channel, including elapsed
  device time, post-warm-up median, settling result, and optional bias resistor;
- `benchmark_report.xlsx`: formatted results, channel statistics, session
  metadata, glossary, and native comparison charts. The Summary table exposes
  route set, array, Vmid, channel repeat, engine, sequence, and SPI clock as
  filterable columns. Test ID and scan order are shown explicitly so tests that
  differ only in payload ordering are not displayed as identical configurations.
  Summary comparison graphs are stacked below the table starting in column A,
  so they remain accessible without horizontal scrolling.
  Auto1 is scheduled only with Vmid sampling off because its effective behavior
  is identical for either requested Vmid value. The Results worksheet repeats
  the Summary short ID (`T001`, etc.) on every associated repetition and
  aggregate row. New sessions also include a filterable Warmup Samples
  worksheet, a Warmup Channel graph driven by its visible filtered rows, and
  four Warmup Curves comparison charts (one per ADC). Filter ADC and Channel on
  Warmup Samples to update the single-channel graph. Curve legends include the
  configured bias resistance when it is available;
- `session_metadata.json`: settings, firmware status, and completion state;
- `session_commands.log`: timestamped commands, acknowledgments, and events;
- `raw/`: original binary captures unless `--no-raw` is selected.

The CSV files remain alongside Excel because they support crash-safe resume and
the complete decoded sample stream can exceed Excel's 1,048,576-row worksheet
limit. Use `--no-excel` only when a workbook is not wanted. Every output field
is defined in [`OUTPUT_GLOSSARY.md`](OUTPUT_GLOSSARY.md).

To create a workbook for a session produced by an older runner, pass its
directory to the report module. It derives the new sample statistics from the
retained sample CSV without changing the original CSV files:

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/excel_report.py `
  Arduino_Sketches/TestBoard_7953/benchmarks/results/20260930T140300Z
```

ADC values are checked against nominal Vmid code 2048. The warning thresholds
are deliberately configurable because the board compares different op-amp bias
resistors and sensor noise. Vmid offsets and cross-mode shifts produce WARN
results; malformed frames, impossible ADC values, or new firmware engine errors
produce FAIL results.
