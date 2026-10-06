# Benchmark output glossary

Runner 2.3 adds three whole-capture integrity counters (including warm-up):
`timestamp_regressions` counts backward start timestamps using wrap-safe
differences, `duplicate_frames` counts exact frame replays within a timer epoch,
and `invalid_timing_frames` counts zero/backward acquisition durations or
overlapping/backward inter-frame timing. One frame may contribute more than once
to the last counter if both checks fail. Genuine uint32 rollover is accepted.
Any nonzero counter fails a measured repetition, as do parser resynchronizations
and discarded bytes. `usb_write_errors` records the firmware counter delta for
short binary writes. These counts are numeric columns in the Excel Results sheet.
Use a new results directory for this schema; retain earlier sessions unchanged.

The benchmark keeps CSV files for exact, resumable machine-readable data and
also creates `benchmark_report.xlsx` for review and charts. Excel cannot contain
the complete decoded sample stream for large sessions because one worksheet is
limited to 1,048,576 rows.

## Files

- `benchmark_results.csv`: one row for each measured repetition plus one
  aggregate row per test configuration.
- `benchmark_channel_stats.csv`: one row per physical ADC/channel and measured
  repetition.
- `benchmark_warmup_samples.csv`: bounded startup trace from the first valid
  test containing each physical channel.
- `benchmark_samples.csv`: one row for every decoded ADC value.
- `benchmark_report.xlsx`: summary charts plus Results, Channel Stats, Session,
  and Glossary worksheets.
- `session_metadata.json`: runner, host, serial, threshold, route-manifest, and
  requested SPI-clock information.
- `session_commands.log`: commands, acknowledgments, capture counts, retries,
  and failures.
- `raw/*.bin`: original USB bytes for each measured attempt.

In the Excel report, filter the `ADC` and `Channel` columns on `Warmup Samples`
to select one physical channel. The `Warmup Channel` graph plots visible rows
only, so it updates to show that channel's startup response and stable median.

## Ghosting output

`--ghosting` writes `ghosting_summary.csv`, `ghosting_pairs.csv`,
`ghosting_attempts.csv`, `ghosting_samples.csv`, and `ghosting_report.xlsx`.
The strongest valid source attempt supplies both the summary metrics and its
Signal Graphs overlay. Detection compares all other channels on the source ADC;
graphs overlay all acquired channels. Optional raw files contain complete
warm-up/baseline/window frames, excluding indefinite trigger-wait traffic.

| Field | File | Meaning |
| --- | --- | --- |
| source | Ghosting files | Pressed route as `ADC:channel`. |
| target | Ghosting Pairs | Compared route on the same ADC as the source. |
| attempt | Ghosting files | One-based attempt for this source, including redos. |
| selected_attempt | Ghosting Summary | Strongest valid source attempt; earlier attempt wins a tie. Blank if none. |
| status | Ghosting Summary/Attempts | `VALID`, `CLIPPED`, `SKIPPED`, `FAILED`, `INCOMPLETE`, or `UNTESTED`. A skipped redo preserves a prior valid selection. |
| status | Ghosting Pairs | `GHOST`, `NO_GHOST`, or `INCONCLUSIVE`; clipping or undefined correlation is inconclusive. |
| source_peak | Ghosting tables | Maximum absolute source departure from its calibrated median, in counts. |
| target_peak | Ghosting Pairs | Maximum absolute target departure from its calibrated median, in counts. |
| source_stdev | Ghosting tables | Source sample standard deviation (`ddof=1`) over the full-resolution two-second signal window, in ADC counts. Separate from quiet baseline noise. |
| target_stdev | Ghosting Pairs | Target sample standard deviation (`ddof=1`) over the same signal-window sweeps, in ADC counts. |
| attenuation_pct | Ghosting Pairs | `100 * target_stdev / source_stdev`. 20% means target variation is 20% of source variation. Blank if source variance is zero; zero for a constant target with a varying source. Noise contributes to this measured estimate; no noise-variance subtraction is applied. Replaces the former peak-ratio field in ghosting schema version 2. |
| correlation | Ghosting Pairs | Signed zero-lag Pearson correlation over matching sweeps in the two-second window. Blank if either signal has zero variance. |
| trigger_threshold | Ghosting Summary/Attempts | Effective source threshold: max of count floor (default 100 counts) and source sigma multiplier times its noise estimate. Trigger requires strictly exceeding it for the configured number of consecutive same-polarity samples. |
| trigger_samples | Ghosting Session metadata | Consecutive same-polarity source samples required above the threshold (default 3). In-band samples or polarity changes reset confirmation. Window time zero is the first sample in the confirmed run. |
| target_threshold | Ghosting Pairs | Effective target threshold: max of count floor and target sigma multiplier times its noise estimate. Target peak must strictly exceed it. |
| ghosting_detected | Ghosting tables | Target passed amplitude and positive-correlation rules, or source has at least one such target. No attenuation cutoff is applied. |
| ghost_targets | Ghosting Summary/Attempts | Comma-separated same-ADC routes classified as ghosts. |
| inconclusive_pairs | Ghosting Summary/Attempts | Number of targets whose clipping or undefined correlation prevented classification. |
| source_clipped | Ghosting Summary/Attempts | Source reached ADC rail 0 or 4095; attempt is excluded from strongest-valid selection. |
| target_clipped | Ghosting Pairs | Target reached ADC rail 0 or 4095; pair classification is inconclusive. |
| phase | Ghosting Samples | `baseline` or `window`; warm-up is excluded from measurement and optionally retained as raw frames. |
| baseline | Ghosting Samples | Channel median during the quiet calibration window for this attempt. |
| baseline_stdev | Ghosting Samples | Channel sample standard deviation during quiet calibration. |
| noise_sigma | Ghosting Samples | Greater of one ADC count and baseline standard deviation; used for source/target thresholds. |
| baseline_relative | Ghosting Samples/Graphs | Raw sample minus that channel's own baseline; graph values use these counts. |
| elapsed_us | Ghosting Samples | Wraparound-safe device time from baseline start or source-trigger sweep, depending on phase. |
| sample_count | Ghosting Summary/Attempts | Number of captured signal-window sweeps, excluding baseline and warm-up. |
| notes | Ghosting Summary/Attempts | Failure, clipping, or interruption explanation. |

## Results fields

| Field | File | Meaning |
| --- | --- | --- |
| session_id | Results | Stable identifier shared by every artifact from one benchmark session. |
| test_id | Results | Deterministic configuration identifier, including route set, order, sequence, engine, repeat, Vmid request, and SPI clock. |
| result_scope | Results | `repetition` is one measured run. `aggregate` summarizes all valid repetitions having the same `test_id`. |
| repetition | Results | One-based measured repetition number; blank on aggregate rows. |
| attempt | Results | First or retry attempt for a repetition; blank on aggregate rows. |
| drift_phase | Results | `begin`, `middle`, or `end` for fixed drift controls; otherwise blank. |
| route_set | Results | Named set of physical ADC/channel routes from the route manifest. |
| array | Results | Requested physical bus selection: `1`, `2`, or `both`. |
| route_list | Results | Exact ordered set of requested `ADC:channel` routes. |
| scanorder | Results | Canonical binary payload order: `interleaved`, `array`, or `adc`. |
| adcseq | Results | ADS7953 acquisition sequence: `manual` or sparse `auto1`. |
| spiengine | Results | Transfer implementation: `blocking`, `dma`, or direct `lpspi`. |
| spi_clock_hz | Results | Requested SPI serial clock in hertz, verified against firmware status. Hardware divider quantization should be checked with a logic analyzer when exact SCLK matters. |
| channelrepeat_requested | Results | Manual-mode settling conversions requested per route. |
| channelrepeat_effective | Results | Effective repeat reported by firmware; Auto-1 always reports one. |
| vmid_requested | Results | Whether optional between-channel Vmid sampling was requested. |
| vmid_effective | Results | Whether optional between-channel Vmid sampling is effective; Auto-1 reports false. Mandatory parking is always separate. |
| ref | Results | ADS7953 full-scale range selection used by the benchmark, in volts. |
| warm_up_ms | Results | Continuous acquisition time discarded before the measured window. The ADC is not stopped or reconfigured between warm-up and measurement. |
| window_ms | Results | Requested measured capture window in milliseconds. |
| captured_frames_total | Results | Frames decoded across the combined continuous warm-up and measurement capture. |
| warmup_frames_discarded | Results | Initial frames excluded from timing and measured-signal summaries using Teensy device timestamps. |
| valid_frames | Results | Number of correctly framed blocks with the expected payload width. Aggregate rows sum valid frames. |
| invalid_frames | Results | Frames rejected for malformed structure or unexpected payload width. |
| resync_events | Results | Times the parser discarded bytes to find the next `0xAA 0x55` header. |
| discarded_bytes | Results | Total bytes discarded during parser resynchronization. |
| trailing_bytes | Results | Incomplete bytes remaining when capture ended. |
| capture_timed_out | Results | True when capture reached its window plus grace deadline without becoming idle. |
| suspected_missing_frames | Results | Estimated omitted frames inferred from unusually long device block periods. |
| total_samples | Results | Sum of decoded payload values across valid frames. |
| startup_min_raw | Results | Minimum ADC code in the complete continuous capture, including the discarded warm-up region. This exposes startup transients without contaminating measured statistics. |
| sample_min_raw | Results | Minimum raw ADC code across every route value in the measured run. Aggregate rows take the minimum across repetitions. |
| sample_p1_raw | Results | First percentile of post-warm-up ADC codes. Aggregate rows report the median repetition percentile. |
| sample_p5_raw | Results | Fifth percentile of post-warm-up ADC codes. Aggregate rows report the median repetition percentile. |
| sample_mean_raw | Results | Mean raw ADC code across all measured values. Aggregate rows report the median of repetition means. |
| sample_median_raw | Results | Median raw ADC code across all measured values. Aggregate rows report the median of repetition medians. |
| sample_p95_raw | Results | Ninety-fifth percentile of post-warm-up ADC codes. Aggregate rows report the median repetition percentile. |
| sample_p99_raw | Results | Ninety-ninth percentile of post-warm-up ADC codes. Aggregate rows report the median repetition percentile. |
| sample_max_raw | Results | Maximum raw ADC code across every route value. Aggregate rows take the maximum across repetitions. |
| sample_stdev_raw | Results | Sample standard deviation of all raw ADC values. Aggregate rows report the median repetition standard deviation. Use Channel Stats to avoid mixing different physical signals. |
| duration_min_us | Results | Minimum sweep acquisition duration. For a repetition it summarizes device frames; for an aggregate it summarizes repetition medians. |
| duration_mean_us | Results | Mean sweep acquisition duration, with the same repetition/aggregate interpretation. |
| duration_median_us | Results | Median time from `block_start_us` to `block_end_us` for one complete ADC sweep. This excludes USB writing after the sweep. It is the primary engine comparison metric. |
| duration_p5_us | Results | Fifth percentile of sweep acquisition duration. |
| duration_p95_us | Results | Ninety-fifth percentile of sweep acquisition duration. |
| duration_max_us | Results | Maximum sweep acquisition duration. |
| duration_stdev_us | Results | Sample standard deviation of sweep acquisition duration. |
| payload_throughput_sps | Results | Median `sample_count * 1,000,000 / acquisition_duration_us`. It is the ADC payload rate during acquisition and excludes the between-block USB/loop gap. |
| sweep_rate_hz | Results | `1,000,000 / median block start-to-start period`. Because every block contains one value for every route, this is also the per-route sample rate. |
| block_period_median_us | Results | Median device time from one `block_start_us` to the next. It includes acquisition plus USB transmission, loop overhead, and other between-sweep time. |
| inter_block_gap_median_us | Results | Median next block start minus previous block end; approximately the non-acquisition portion of the block period. |
| host_arrival_period_median_us | Results | Median difference between host timestamps assigned when complete frames are decoded. USB reads can contain many frames, producing zero intervals; use this to observe host batching, not ADC cadence. |
| speedup_vs_blocking | Results | Matched blocking median duration divided by this engine's median duration. `2.0` means twice as fast. It is reported only for `array both` with identical clock, routes, order, sequence, repeat, Vmid, and reference. |
| throughput_gain_pct | Results | Percent payload-throughput change relative to the same matched blocking configuration. |
| dma_start_errors | Results | Increase in the cumulative firmware DMA-start counter during this measurement. |
| lpspi_start_errors | Results | Increase in the cumulative direct-LPSPI start-error counter. |
| transfer_timeouts | Results | Increase in the cumulative paired-transfer timeout counter. |
| returned_channel_errors | Results | Increase in ADS7953 returned-channel/tag validation failures. |
| vmid_warning_count | Results | Routes whose median lies more than `vmid_warning_tolerance` from nominal Vmid. |
| vmid_severe_count | Results | Routes whose median lies more than `vmid_severe_tolerance` from nominal Vmid. |
| unstable_channel_count | Results | Routes whose MAD exceeded the configured noise floor and baseline-relative multiplier. |
| cross_mode_shift_count | Results | Routes whose median changed beyond the configured absolute/MAD threshold relative to the clock-matched blocking/manual baseline. |
| drift_warning_count | Results | Signal or timing drift warnings in the fixed beginning/middle/end controls. |
| settling_warning_count | Results | Routes that did not satisfy the settling rule before the measured window began. |
| settling_max_frames | Results | Largest zero-based settling frame index among the configured routes. |
| settling_max_us | Results | Longest device-timestamp settling time among configured routes. |
| settling_tolerance_counts | Results | Minimum allowed distance from the post-warm-up route median when detecting settling; default 64 counts. The effective per-route tolerance is the greater of this value and six times measured MAD. |
| settling_stable_frames | Results | Consecutive in-tolerance frames required to declare a route settled; default five. |
| timing_drift_pct | Results | Percent duration change from the beginning drift control. |
| drift_timing_tolerance_pct | Results | Absolute timing-drift percentage allowed before `DRIFT_WARNING`; default 10%. |
| data_integrity_status | Results | `PASS`, `WARN`, or `FAIL` from framing, firmware counters, sample validity, Vmid, stability, shift, and drift checks. |
| overall_status | Results | Final repetition or aggregate result status. Analog warnings do not become hard framing failures. |
| vmid_nominal_code | Results | Expected half-scale ADC code; default 2048. |
| vmid_warning_tolerance | Results | Warning distance from nominal Vmid in ADC counts; default 512. |
| vmid_severe_tolerance | Results | Severe-warning distance from nominal Vmid in ADC counts; default 1024. |
| cross_mode_floor_counts | Results | Minimum median-shift threshold in ADC counts; default 128. This prevents tiny baseline MAD values from making the shift check hypersensitive. |
| cross_mode_mad_multiplier | Results | Multiplier applied to `max(reference MAD, test MAD, 1)`; default 6. The effective shift limit is the greater of this result and `cross_mode_floor_counts`. |
| baseline_test_ids | Results | Blocking/manual reference tests used for same-channel comparisons. |
| notes | Results | Aggregate description, warning explanation, retry, or failure detail. |

## Channel statistics fields

| Field | File | Meaning |
| --- | --- | --- |
| session_id | Channel Stats | Session identifier. |
| test_id | Channel Stats | Configuration identifier. |
| repetition | Channel Stats | Measured repetition number. |
| attempt | Channel Stats | Attempt number. |
| drift_phase | Channel Stats | Drift-control phase or blank. |
| route_set | Channel Stats | Route-set name. |
| array | Channel Stats | Physical array selection. |
| scanorder | Channel Stats | Payload ordering contract. |
| adcseq | Channel Stats | Manual or Auto-1 sequence. |
| spiengine | Channel Stats | Blocking, DMA, or direct LPSPI. |
| spi_clock_hz | Channel Stats | Requested SPI serial clock in hertz. |
| channelrepeat_requested | Channel Stats | Requested manual repeat. |
| channelrepeat_effective | Channel Stats | Effective repeat reported by firmware. |
| vmid_requested | Channel Stats | Requested optional Vmid sampling. |
| vmid_effective | Channel Stats | Effective optional Vmid sampling. |
| adc | Channel Stats | Physical ADS7953 number, 1 through 4. |
| channel | Channel Stats | ADS7953 input, 0 through 14. Channel 15 is reserved for Vmid parking. |
| sample_count | Channel Stats | Valid samples summarized for this physical route. |
| sample_min_raw | Channel Stats | Minimum raw ADC code for this route. |
| sample_mean_raw | Channel Stats | Arithmetic mean raw ADC code for this route. |
| sample_median_raw | Channel Stats | Median raw ADC code for this route. |
| sample_max_raw | Channel Stats | Maximum raw ADC code for this route. |
| sample_stdev_raw | Channel Stats | Sample standard deviation for this route. |
| sample_mad_raw | Channel Stats | Median absolute deviation for this route, used by stability/shift checks. |
| sample_p1_raw | Channel Stats | First percentile of post-warm-up samples for this route. |
| sample_p5_raw | Channel Stats | Fifth percentile of post-warm-up samples for this route. |
| sample_p95_raw | Channel Stats | Ninety-fifth percentile of post-warm-up samples for this route. |
| sample_p99_raw | Channel Stats | Ninety-ninth percentile of post-warm-up samples for this route. |
| startup_min_raw | Channel Stats | Minimum route value across warm-up and measurement, retained for startup-transient diagnosis. |
| settling_frame_index | Channel Stats | First zero-based frame of the required consecutive in-tolerance settling window. |
| settling_time_us | Channel Stats | Device time from the first captured frame to `settling_frame_index`. |
| settling_tolerance_counts | Channel Stats | Effective route tolerance: `max(configured tolerance, 6 * measured MAD)`. |
| settling_stable_frames | Channel Stats | Consecutive in-tolerance frames required by the settling rule. |
| settled_before_measurement | Channel Stats | True when settling occurred within `warm_up_ms`. |
| median_offset_from_vmid | Channel Stats | Route median minus nominal Vmid code. |
| route_warning | Channel Stats | Semicolon-separated Vmid, instability, cross-mode, or drift warnings. |

## Decoded sample fields

| Field | File | Meaning |
| --- | --- | --- |
| session_id | Samples | Session identifier. |
| test_id | Samples | Configuration identifier. |
| repetition | Samples | Repetition number. |
| attempt | Samples | Attempt number. |
| drift_phase | Samples | Drift-control phase or blank. |
| frame_index | Samples | Zero-based valid frame number within the measured capture. |
| host_received_ns | Samples | Host monotonic timestamp assigned to the USB read that completed the frame. |
| block_start_us | Samples | Teensy `micros()` timestamp immediately before the sweep. |
| block_end_us | Samples | Teensy `micros()` timestamp immediately after the sweep. |
| acquisition_duration_us | Samples | Wraparound-safe block end minus block start. |
| avg_dt_us | Samples | Firmware-rounded acquisition duration divided by payload route count. |
| sample_count | Samples | Number of route values in this binary frame. |
| payload_index | Samples | Zero-based sample position in the selected payload order. |
| array | Samples | Physical array selection. |
| adc | Samples | Physical ADS7953 number. |
| channel | Samples | Physical ADS7953 input. |
| sample_raw | Samples | Decoded unsigned 12-bit ADC code. |
| offset_from_vmid | Samples | Raw code minus nominal Vmid code. |
| route_warning | Samples | Warning assigned from the route's statistics for this repetition. |

## Warm-up sample fields

| Field | File | Meaning |
| --- | --- | --- |
| session_id | Warmup Samples | Session identifier. |
| test_id | Warmup Samples | First valid test from which this physical channel was exported. |
| repetition | Warmup Samples | Repetition supplying the trace. |
| attempt | Warmup Samples | Attempt supplying the trace. |
| route_set | Warmup Samples | Route set active during the trace. |
| array | Warmup Samples | Physical array selection. |
| scanorder | Warmup Samples | Payload ordering contract. |
| adcseq | Warmup Samples | Manual or Auto-1 sequence. |
| spiengine | Warmup Samples | Blocking, DMA, or direct LPSPI. |
| spi_clock_hz | Warmup Samples | Requested SPI clock in hertz. |
| channelrepeat_requested | Warmup Samples | Requested manual repeat. |
| vmid_requested | Warmup Samples | Requested between-channel Vmid sampling. |
| adc | Warmup Samples | Physical ADC number. |
| channel | Warmup Samples | Physical ADC input. |
| bias_resistor_ohms | Warmup Samples | Optional resistor value loaded from `testboard_7953_bias_resistors.json`; blank when not configured. |
| warmup_frame_index | Warmup Samples | Zero-based frame within the continuous capture. |
| elapsed_us | Warmup Samples | Wraparound-safe Teensy time since the first captured frame. This is the independent variable for later RC fitting. |
| block_start_us | Warmup Samples | Original Teensy block-start timestamp. |
| acquisition_duration_us | Warmup Samples | Acquisition duration of this frame. |
| sample_raw | Warmup Samples | Raw ADC code during warm-up. |
| post_warmup_median_raw | Warmup Samples | Stable reference level calculated from the measured window. |
| delta_from_post_warmup_median | Warmup Samples | Warm-up code minus the stable reference level. |
| settling_frame_index | Warmup Samples | First frame of the detected stable window for this route. |
| settling_time_us | Warmup Samples | Detected device-time settling interval. |

## Important interpretations

- `duration_median_us` answers “how long did the ADC sweep itself take?”
- `block_period_median_us` answers “how often did complete sweeps actually
  start?”
- `payload_throughput_sps` is acquisition-only throughput. `sweep_rate_hz` is
  the effective delivered rate for every configured physical route.
- Overall sample statistics mix all selected routes. Use Channel Stats when
  comparing analog levels or noise because each route is a different signal.
