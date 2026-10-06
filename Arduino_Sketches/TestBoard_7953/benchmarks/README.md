# TestBoard 7953 benchmarks

Runner 2.3 fails captures containing exact frame replays, backward/overlapping
timestamps, stale text (discarded bytes/resynchronization), or short-write error
counter increases. Checks include warm-up and accept genuine timer rollover.
Use a fresh output directory; earlier runner 2.2 sessions remain valid historical
artifacts with their original, less strict verdicts. Failed attempts and raw
captures remain evidence even if an automatic retry later passes.

After uploading the USB repair, run the
[focused 12-capture check](../../../docs/architecture/TESTBOARD_7953_USB_STREAM_DIAGNOSIS.md#implemented-repair)
before repeating the full performance comparison.

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

## Interactive ghosting test

Use `--ghosting` to investigate whether an isolated press produces a smaller,
similarly shaped response on other channels. Run it from an interactive
terminal so Space can skip a broken or inactive source without Enter. Close
the GUI and other serial clients first.

Test one ADC (ADC2 has 15 populated sensor channels):

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py `
  --ghosting --ghost-adc 2 --port COM3
```

Test all 25 channels in array 1 with explicit acquisition settings:

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py `
  --ghosting --route-set full_array1 --port COM3 `
  --vmid on --scan-order adc --spi-clock-hz 20000000 --spi-engine lpspi
```

Inspect the effective settings and sources without opening the port:

```powershell
uv run python Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py `
  --ghosting --route-set all_four_full --dry-run
```

Select either `--ghost-adc 1|2|3|4` or one `--route-set`. ADC1/ADC3 have 10
populated channels (0–9); ADC2/ADC4 have 15 (0–14). Arrays 1/2 contain ADC1/ADC2
and ADC3/ADC4 respectively. `all_four_full` is mapped to `full_array1`, with a
notice and requested/effective selections in metadata. Other two-array route
sets are rejected. Channel 15 is Vmid and is never a sensor source.

Each ghosting session uses one configuration, manual ADC sequencing,
`channelrepeat=1`, and `repetitions=1`. The window is always two seconds from
the source trigger. `--window-ms` and `--repetitions` are overridden and the
requested values are recorded. Matrix filters (`--tests`), smoke mode, multiple
settings, and `--resume` are unsupported; use a new output directory for each
session. Normal benchmark sessions keep their existing behavior.

| Ghosting option | Default | Meaning |
| --- | --- | --- |
| `--spi-engine blocking|dma|lpspi` | `lpspi` | One acquisition engine. |
| `--vmid on|off` | `off` | Optional between-channel Vmid conversions; mandatory parking remains enabled. |
| `--scan-order` | `adc` | One payload order; also accepts `array` and `interleaved`. |
| `--spi-clock-hz` | `20000000` | One SPI speed within the existing 100 kHz–30 MHz limits. |
| `--warm-up-ms` | `1000` | Device-time warm-up before each attempt; excluded from baseline and measurements. |
| `--ghost-baseline-ms` | `1000` | Quiet calibration duration after warm-up. |
| `--ghost-trigger-counts` | `100` | Minimum source-trigger threshold in ADC counts, above the unpressed excursions observed during board testing. |
| `--ghost-trigger-samples` | `3` | Consecutive samples beyond the threshold with the same polarity; accepts 1–64. |
| `--ghost-trigger-sigma` | `5` | Source noise multiplier; must be at least 3. |
| `--ghost-target-counts` | `1` | Minimum noticeable target amplitude in ADC counts. |
| `--ghost-target-sigma` | `3` | Target noise multiplier; must be positive. |
| `--ghost-correlation-min` | `0.8` | Minimum positive Pearson correlation to classify ghosting. |

Before each source or redo, release **all** sensors and press Enter when ready.
The runner warms up and calculates each channel's median baseline and sample
standard deviation. Noise sigma is the greater of one count and that measured
standard deviation. Keep every sensor untouched throughout calibration.

After `Press ADCn_CHm` appears, press only the requested source. The trigger
requires three consecutive samples more than
`max(trigger_counts, trigger_sigma * source_noise_sigma)` from baseline, all on
the same side of baseline. An in-band sample or polarity change resets the
confirmation. The two-second capture starts at the **first** sample in the
confirmed run and retains all confirming samples. Press **Space** while waiting to skip
and advance to the next source, or **Q** to finish with a partial report.
After a captured/failed attempt, choose Enter/C to continue, R to redo, or Q to
finish. Ctrl+C preserves completed results and any available partial capture.

The source count floor defaults to 100 because an unpressed ADC1 session
recorded source excursions up to 58 counts even though the quiet calibration
standard deviations were below one count. A 5-sigma rule alone produced a
5-count threshold and falsely triggered on these later excursions. The higher
floor and consecutive-sample confirmation reject that recorded behavior.
If a real press is weaker than the floor, choose a lower
`--ghost-trigger-counts` explicitly after checking unpressed excursions for
your configuration. Target thresholds remain independently configurable and
default to 3 sigma with a one-count floor.

For every other channel on the source ADC, the runner reports its absolute
baseline-relative peak, signal standard deviation, attenuation percentage, and signed, zero-lag
Pearson correlation over the same sweeps. Ghosting requires both a peak above
`max(target_counts, target_sigma * target_noise_sigma)` and correlation at least
the configured minimum. There is no attenuation cutoff; inverted responses
are reported but do not pass the positive-correlation rule. A clipped target
or undefined correlation is inconclusive. Source clipping at 0/4095 excludes
the attempt from strongest-valid selection.

Attenuation is `100 * std(target_signal) / std(source_signal)`, using sample
standard deviations (`ddof=1`) from the full-resolution shared two-second
window. An attenuation value of 20% means the target's standard deviation is
20% of the source's. Both `source_stdev` and `target_stdev` are exported in ADC
counts so the ratio can be checked. A constant source has undefined attenuation
(blank in CSV/Excel); a constant target has 0% attenuation and undefined
correlation. Additive noise still contributes to standard deviations, so this
is a measured attenuation estimate; baseline-noise variance is not subtracted.
Ghosting schema version 2 replaces the former peak-ratio field `gain_pct` with
`attenuation_pct` in new sessions. Existing session artifacts are preserved.

The Summary uses the valid attempt with the **largest source amplitude**;
ties retain the earlier attempt. A skipped redo preserves an existing valid
result. The Attempts sheet retains all attempts, and the sample CSV retains
baseline and signal-window data at full resolution. A source with no valid
result is marked skipped, failed, clipped, incomplete, or untested as applicable.

### Ghosting artifacts and graphs

Sessions default to a timestamped directory beneath `benchmarks/results/`.
`--output`, `--no-raw`, `--no-excel`, `--idle-ms`, `--grace-ms`, and
`--allow-existing-errors` are also supported. CSVs and metadata are saved after
each attempt. Completion, Quit, and interruption produce a workbook unless
`--no-excel` is set.

- `ghosting_summary.csv`: strongest-valid source results and source statuses.
- `ghosting_pairs.csv`: all same-ADC target metrics for selected attempts.
- `ghosting_attempts.csv`: complete attempt history.
- `ghosting_samples.csv`: baseline/window samples, baselines, noise estimates,
  route identities, and device timestamps for all measured channels.
- `ghosting_report.xlsx`: Summary, Pairs, Attempts, Signal Graphs, Session,
  Glossary, and hidden Chart Data sheets.
- `raw/*.bin`: optional warm-up/baseline/window frame captures per attempt;
  indefinite trigger-wait traffic is not retained.

**Signal Graphs** contains one native Excel chart per source with a valid
selected attempt: 25 for an array or 10/15 for one ADC. Each chart overlays the
source and **all measured channels**, including the other ADC in an array
session. Detection remains limited to the source ADC. Missing valid results
have labeled placeholders, and the source index links to each graph slot.

Graphs show baseline-relative counts against device time since the trigger,
from 0 to 2 seconds. A thicker source line identifies the pressed channel.
Each chart's Y-axis covers the minimum/maximum of all its full-resolution
traces with 5% padding (at least one count). Graphs use at most 5,000 common
time points, preserving per-channel bucket extrema and window endpoints;
reduced plots are labeled. Metrics and CSVs always use full-resolution data.

### Hardware validation

The software reports correlated responses; it cannot distinguish electrical
coupling from mechanically transmitted force. Physically isolate unpressed
sensors and avoid loading shared sensor packages or the board during a press.
Baseline noise is estimated from the quiet window and may include drift or
environmental interference; it is not a separately measured white-noise spectrum.
Timing and correlation use aligned sweeps because firmware does not provide
individual channel sample timestamps.

Validate one ADC and one array on the real board: perform an isolated press,
redo it with a larger unclipped response, skip an inactive source, and quit
partway through. Confirm summary selection and charts match the intended
attempt. Test clipping with a lighter redo, Ctrl+C while waiting/capturing,
and stream loss. Where available, use controlled electrical signal injection
to verify a known attenuation and correlation without mechanically loading targets.
Hardware behavior and visual Excel layout still require on-device/manual review.

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
