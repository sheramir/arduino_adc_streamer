## Plan: TestBoard_7953 Interactive Ghosting Benchmark

Status: IMPLEMENTED IN HOST TOOLS - automated validation complete; hardware and manual Excel validation pending.
Date: 2026-10-01
Workspace: `C:/Code/arduino_adc_streamer/`

**Target benchmark folder:** `C:\Code\arduino_adc_streamer\Arduino_Sketches\TestBoard_7953\benchmarks`

**Existing script to extend:** `C:\Code\arduino_adc_streamer\Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py`

Implement the ghosting workflow and Excel reporting in this benchmark folder. Add focused tests under `C:\Code\arduino_adc_streamer\tests`; keep this plan under `C:\Code\arduino_adc_streamer\Plans`.

Add an interactive ghosting mode to the existing benchmark runner. Test each selected channel as a source, compare its response with every other channel on the same ADC, and export results plus synchronized signal graphs to Excel.

Each session uses one ADC or one array and one acquisition configuration. A full array has 25 populated channels; ADC1/ADC3 have 10 channels, and ADC2/ADC4 have 15.

**Steps**

1. **Add ghosting configuration and dispatch.**

   Add `--ghosting` without changing normal benchmark behavior. Require either `--ghost-adc 1|2|3|4` or one existing `--route-set`; selectors are mutually exclusive.

   Support single-ADC route sets and `full_array1`/`full_array2`. Map `all_four_full` to `full_array1`, notifying the user and recording requested/effective selections. Reject other two-array selections. Use the route manifest and populated board wiring; channel 15 remains reserved for Vmid.

   Ghosting configuration:

   | Option | Default / behavior |
   | --- | --- |
   | Existing `--scan-order` | `adc`; accept one order |
   | Existing `--spi-clock-hz` | 20 MHz; accept one speed within existing limits |
   | New `--spi-engine` | `lpspi`; choices `blocking`, `dma`, `lpspi` |
   | New `--vmid` | `off`; choices `on`, `off` |
   | Existing `--warm-up-ms` | 1,000 ms |
   | New `--ghost-baseline-ms` | 1,000 ms; positive |
   | New `--ghost-trigger-counts` | 100 counts; positive minimum threshold |
   | New `--ghost-trigger-samples` | 3 consecutive same-polarity samples; range 1–64 |
   | New `--ghost-target-counts` | 1 count; positive minimum threshold |
   | New `--ghost-trigger-sigma` | 5; minimum 3 |
   | New `--ghost-target-sigma` | 3; positive |
   | New `--ghost-correlation-min` | 0.8; range 0–1 |

   Use manual ADC sequencing. Force channel repeat and session repetitions to 1, and the triggered window to 2,000 ms; disclose overrides of supplied repeat/window values.

   Support existing port, output, logging, raw-capture, Excel, and dry-run options. Reject matrix filters, smoke mode, multiple configurations, and resume in ghosting mode.

2. **Implement the interactive acquisition lifecycle.**

   Test sources in ADC/channel order. Before every attempt, ask the user to release all sensors and press Enter when ready.

   Configure the selected routes and start one continuous firmware stream. Discard warm-up frames, collect the quiet baseline, and then prompt: `Press ADCn_CHm; Space skips`.

   For each channel, calculate its baseline median and baseline sample standard deviation. Use `σ = max(1 count, measured standard deviation)`.

   Trigger when the source satisfies the following for the configured number of consecutive samples on the same side of baseline. In-band samples or polarity changes reset confirmation:

   ```text
   abs(sample − baseline) >
       max(ghost_trigger_counts, ghost_trigger_sigma × source_noise_sigma)
   ```

   Time zero is the first sweep in the confirmed crossing. Include every confirmation sweep and subsequent sweeps whose device timestamps fall within the two-second window. Use wraparound-safe device timing rather than host arrival timing. All channels use the same captured sweeps.

   Poll keyboard input while consuming serial data. Space skips immediately without Enter during trigger waiting and advances to the next source, preserving any prior valid result. Discard waiting samples rather than accumulating them indefinitely.

   Add a stream-stop helper that consumes complete binary frames before reading the stop acknowledgment. Recognize acknowledgment text only at frame boundaries. Clean up streaming and the serial port on completion, skip, failure, Quit, and interruption.

3. **Calculate ghosting metrics and retain attempt history.**

   Subtract each channel’s own baseline. Calculate:

   ```text
   source_peak = max(abs(source_signal))
   target_peak = max(abs(target_signal))
   source_stdev = std(source_signal, ddof=1)
   target_stdev = std(target_signal, ddof=1)
   attenuation_pct = 100 × target_stdev / source_stdev
   correlation = signed, zero-lag Pearson correlation
   ```

   Evaluate every other selected channel on the source ADC. Flag ghosting when the target peak exceeds its threshold and correlation meets the configured minimum:

   ```text
   target_peak > max(ghost_target_counts,
                     ghost_target_sigma × target_noise_sigma)
   correlation >= ghost_correlation_min
   ```

   Apply no attenuation cutoff. Calculate standard deviations and correlation over the full-resolution two-second window. Export both standard deviations in counts. If source variance is zero, attenuation is undefined (blank); if the target alone is constant, attenuation is zero and correlation remains undefined. Noise still contributes to the measured ratio; do not subtract baseline noise variance.

   Show source amplitude and target amplitude, both standard deviations, attenuation, correlation, and outcome. Offer **Continue**, **Redo**, and **Quit**.

   Preserve every attempt. Select the integrity-valid, unclipped attempt with the greatest source amplitude for the final summary; ties retain the earlier attempt. A skipped redo preserves an existing valid result. Otherwise mark the source skipped.

   Exclude source-clipped attempts from strongest-valid selection. Target clipping or undefined correlation makes that pair inconclusive. Keep failed, incomplete, skipped, and untested states distinct. Preserve available measurements and failure reasons.

4. **Export durable results and the Excel workbook.**

   Write ghosting-specific artifacts in the selected session directory:

   - `ghosting_summary.csv`
   - `ghosting_pairs.csv`
   - `ghosting_attempts.csv`
   - `ghosting_samples.csv`
   - `session_metadata.json`
   - `session_commands.log`
   - `ghosting_report.xlsx`
   - Optional phase/attempt binary captures under `raw/`

   Sample records identify source, attempt, phase, measured route, device time, raw reading, baseline, and baseline-relative reading. Retain baseline and triggered-window data for every measured channel.

   Save results after each attempt. Generate the workbook on completion and a partial workbook on Quit or interruption.

   Workbook sheets:

   - **Summary:** one row per source, selected attempt, amplitude, status, ghosting flag, and detected targets.
   - **Pairs:** selected-attempt metrics for all evaluated source/target pairs.
   - **Attempts:** complete attempt history.
   - **Signal Graphs:** per-source overlays described below.
   - **Session / Glossary:** separate sheets for settings, calibration measurements, formulas, and definitions.
   - **Chart Data:** hidden numeric data supporting native Excel charts.

5. **Add synchronized, zoomed signal graphs.**

   Create one graph for each source with a selected valid attempt: 25 graphs for a completed full-array session, or 10/15 for a completed single-ADC session. Reserve a labeled slot explaining the status when a source lacks a valid attempt.

   Each graph must:

   - Use the exact attempt selected by the Summary sheet.
   - Overlay the source and **all other measured channels**, including the other ADC during an array session.
   - Plot baseline-relative ADC counts against elapsed device time since the trigger.
   - Show the common two-second window with an X-axis of 0–2 seconds.
   - Use a native Excel XY scatter chart with straight lines and no markers.
   - Highlight the source with a thicker line; use stable channel colors and route labels.
   - Identify the source and selected attempt in the title.
   - Use one shared Y-axis so amplitudes remain directly comparable.

   Set the Y-axis from the minimum and maximum across all overlaid full-resolution signals. Pad both ends by `max(1 count, 5% of the signal range)`, including a usable range for flat signals. Do not use the fixed 0–4095 scale.

   Arrange graphs vertically in source order, approximately 1,100 × 600 pixels each, with a source index linking to graph locations.

   Limit chart data to 5,000 common time points per source. For larger captures, divide time into buckets and retain the union of every channel’s minimum/maximum sample indices plus the first/last points. Choose the bucket count to stay within the limit. Preserve all full-resolution data in CSV and use it for analysis and axis limits. Label charts when their display data is reduced.

   Enable plotting from hidden chart-data cells. Cross-ADC traces are for visual inspection; automated ghosting classification remains restricted to the source ADC.

6. **Document the workflow and register the plan.**

   Add commands for single-ADC and single-array sessions, the array1 fallback, threshold settings, key controls, strongest-attempt selection, and chart interpretation.

   Explain that attenuation is the target/source sample-standard-deviation ratio, correlations use sweep-level alignment, and physical isolation of unpressed sensors is necessary to investigate electrical coupling. An attenuation value of 20% means target variation is 20% of source variation. Ghosting schema version 2 replaces the earlier peak-ratio output in new sessions; preserve historical artifacts.

   Register this plan in `Plans/README.md`.

**Relevant files**

All paths are relative to `C:/Code/arduino_adc_streamer/`.

The `Arduino_Sketches/TestBoard_7953/benchmarks/` entries below refer to the target benchmark folder `C:\Code\arduino_adc_streamer\Arduino_Sketches\TestBoard_7953\benchmarks`.

| File or folder | Role |
| --- | --- |
| `Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_benchmark.py` | CLI, ghosting dispatch, acquisition state machine, keyboard handling, cleanup, and session persistence |
| `Arduino_Sketches/TestBoard_7953/benchmarks/ghosting_analysis.py` — new | Pure analysis helpers, result models, validity checks, and strongest-attempt selection |
| `Arduino_Sketches/TestBoard_7953/benchmarks/ghosting_capture.py` — new | Continuous acquisition, warm-up/baseline/trigger/window state machine, terminal key polling, and frame-aware stream stopping |
| `Arduino_Sketches/TestBoard_7953/benchmarks/benchmark_common.py` | Reuse frame parsing and wraparound-safe timing |
| `Arduino_Sketches/TestBoard_7953/benchmarks/excel_report.py` | Add `write_ghosting_workbook` and graph helpers while preserving benchmark reporting |
| `Arduino_Sketches/TestBoard_7953/benchmarks/testboard_7953_routes.json` | Existing route-set selection and array1 fallback |
| `config/testboard_7953_board.py` | Reference for populated ADC/channel wiring |
| `Arduino_Sketches/TestBoard_7953/src/PztController.cpp` and `Arduino_Sketches/TestBoard_7953/src/Firmware.cpp` | Read-only references for continuous streaming, stop handling, and payload timing |
| `Arduino_Sketches/TestBoard_7953/benchmarks/README.md` and `Arduino_Sketches/TestBoard_7953/benchmarks/OUTPUT_GLOSSARY.md` | Usage and output documentation |
| `Arduino_Sketches/TestBoard_7953/benchmarks/results/` | Default generated session location |
| `tests/test_testboard_7953_ghosting.py` — new | Focused acquisition, analysis, interaction, and workbook tests |
| `tests/test_testboard_7953_benchmark.py` | Existing benchmark regressions |
| `Plans/plan-testboard7953-ghosting-test.prompt.md` and `Plans/README.md` | Plan artifact and index |

**Verification**

1. Test selection, all four ADCs, array1 fallback, defaults, forced settings, invalid combinations, and unchanged benchmark behavior.
2. Test warm-up exclusion, fresh calibration, threshold boundaries, positive/negative source triggers, rollover, and the exact two-second window.
3. Verify synthetic 20% correlated ghosting, independent noise, inverted signals, constant signals, and clipping. Verify standard-deviation attenuation with an isolated target spike, baseline-offset invariance, zero source/target variance, and numeric CSV/Excel export under the attenuation name.
4. Test immediate Space handling, strongest-attempt selection, skipped redos, disconnects, binary/ACK separation, cleanup, and partial reports.
5. Inspect workbook XML for graph counts, correct attempt/series references, all-array overlays, numeric time axes, hidden-data visibility, and padded Y-axis bounds.
6. Test chart reduction for common timestamps, retained extrema, the point limit, and unchanged analysis metrics.
7. Run:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_testboard_7953_benchmark.py tests/test_testboard_7953_ghosting.py -q
   ```

8. Open a representative workbook in Excel and verify readable legends, source emphasis, synchronized overlays, zoomed axes, and missing-result placeholders. Validate isolated presses, controlled electrical coupling where available, redo, skip, and interruption on hardware.

Implementation validation: the existing benchmark suite and new ghosting suite pass all 76 tests. Attenuation uses the sample-standard-deviation ratio; console, CSV, Excel, and metadata checks cover the new fields and schema version 2. CLI dry runs cover a single ADC with explicit settings and the full-four-ADC fallback to array 1. The 2026-10-02 unpressed ADC1 session exposed false triggers at the original 5-count threshold; its source excursions reached 58 counts. Raising the default source count floor to 100 and adding three-sample same-polarity confirmation rejected all 10 recorded unpressed captures in offline replay. COM3 is the user's serial port. Live pressed-sensor validation of the revised trigger and manual Excel layout validation remain pending.

**Decisions**

- One acquisition configuration per session; fresh warm-up and baseline before every attempt.
- Source triggering defaults to max(100 counts, 5σ), confirmed by three consecutive same-polarity samples; target detection defaults to 3σ plus positive correlation ≥0.8.
- Summary and graphs use the strongest valid source attempt.
- Detection compares all other channels on the same ADC; graphs show all acquired channels.
- Graphs use baseline-relative counts and per-graph min/max zoom.
- No firmware, GUI, or wire-format changes are planned.
