# TestBoard 7953: channel noise and settling comparison

Analyzed 2026-10-07. Typical LPSPI channel noise remains near half an ADC count,
but several configurations show higher variation. Startup settling is slightly
faster. Raw captures also contain brief level dips immediately after long gaps
between sweeps. These findings require an analog follow-up before declaring
the faster firmware equivalent in signal quality. The sensor behavior described
by the user explains why long sampling pauses can produce discharge/recharge
transients; the different bias resistors must be included in their interpretation.

## Inputs and method

Compared the following sessions under
`Arduino_Sketches/TestBoard_7953/benchmarks/results/`:

- Original firmware: `optimization_baseline_adc_10_20`.
- First optimization with USB repair: `optimization_after_usb_fix_adc_10_20`.
- Latest production: `lpspi_word_path_production_adc_10_20`.

Each session has 5,580 channel-statistic rows, representing 1,860 matched
configuration/channel pairs with three repetitions. LPSPI accounts for 620
matched pairs. Settings match: ADC payload order, repeat 1, Vmid off, 10/20 MHz,
one-second warm-up and five-second measurement windows.

For each configuration/channel pair, take the median statistic across the three
repetitions. Table values then take the median across the selected channels.
Noise means sample standard deviation in raw ADC counts. It includes input
variation and occasional excursions; it does not isolate electronic noise.
Startup statistics use the runner's existing threshold definition below.

## Sensor behavior and bias resistors

The user describes the connected sensors as charging toward Vmid while selected
by the MUX/ADC and leaking toward ground while unselected. A long acquisition
pause therefore gives them more time to discharge, and their subsequent samples
include recovery toward Vmid. Treat these events as sensor discharge/recharge
transients when interpreting the measurements, rather than counting their entire
contribution as random electronic noise. The observation of a post-pause dip
fits this mechanism; the recordings do not measure sensor capacitance or isolate
every possible contributor to the waveform.

The existing `testboard_7953_bias_resistors.json` maps the tested sensor routes:

| ADC | Sensor channels | Bias resistor |
| --- | --- | ---: |
| ADC1 | 0-9 | 1 MOhm |
| ADC2 | 0-14 | 470 kOhm |
| ADC3 | 0-9 | 470 kOhm |
| ADC4 | 0-14 | 249 kOhm |

Compare each channel against itself with the same hardware and configuration.
Group summaries by ADC and resistor value, retaining channel identity: matching
resistors do not establish matching sensor capacitance or leakage. Also retain
selection time, time between successive visits to the channel, scan topology,
and pause duration. Faster sweeps affect both the time available to recharge
while selected and the time available to leak between visits. Resistance alone
cannot determine the magnitude or recovery time of a dip.

The `vmid off` setting in these sessions refers to optional between-channel
Vmid conversions; it does not mean the board's Vmid bias is absent.

Selected raw captures were also examined for single ADC3, manual LPSPI at
10 MHz, and both full arrays, manual/Auto-1 LPSPI at 20 MHz. This covers 27
captures across three firmware stages. Gap-exclusion analysis covers the 18
repaired/latest captures. The original full-array-1 Auto-1 blocking 10 MHz
configuration has known corrupt timestamps and cannot support a settling
comparison; the LPSPI comparisons are unaffected.

## Noise

| LPSPI selection | Original standard deviation, counts | First optimized + USB repair | Latest production |
| --- | ---: | ---: | ---: |
| All 620 configuration/channel pairs | 0.482 | 0.518 | 0.524 |
| Both full arrays, manual, 20 MHz | 0.464 | 0.479 | 0.524 |
| Both full arrays, Auto-1, 20 MHz | 0.495 | 0.478 | 0.592 |
| Single ADC3 on bus 2, manual, 10 MHz | 0.503 | 0.496 | 0.830 |

Typical LPSPI variation is about 9% above the original and 1% above the repaired
first optimization, using ratios of the overall medians. Blocking and DMA show
similar shifts from the original: 0.474 -> 0.515 -> 0.523 and
0.476 -> 0.525 -> 0.535 counts respectively. This is not evidence that the
LPSPI optimization alone caused the overall shift. The median LPSPI p99-p1
span remains two counts across the three stages.

The following breakdown uses the same matched-pair aggregation, separately for
each ADC. It includes all its LPSPI modes, clocks and route sets, so it summarizes
sample variation rather than providing a controlled comparison of resistors.

| ADC / bias | Matched pairs | Original standard deviation, counts | First optimized + USB repair | Latest production |
| --- | ---: | ---: | ---: | ---: |
| ADC1 / 1 MOhm | 172 | 0.495 | 0.551 | 0.570 |
| ADC2 / 470 kOhm | 140 | 0.435 | 0.492 | 0.491 |
| ADC3 / 470 kOhm | 168 | 0.509 | 0.547 | 0.552 |
| ADC4 / 249 kOhm | 140 | 0.435 | 0.461 | 0.470 |

Against the repaired first optimization, the selected both-array manual and
Auto-1 tests increase by approximately 9% and 24%; single-ADC3 manual increases
by 67%. The latter's median p99-p1 span widens from two to four counts.
The largest paired LPSPI increase is ADC3 channel 8 in that manual 10 MHz
configuration: 0.495 -> 0.836 counts, while its median stays at 2,036.
Of the 620 LPSPI pairs, 147 increase by more than 0.1 count and 38 by more than
0.2 count; none increase by more than 0.5 count.

The changes are not monotonic with SPI clock or sequencing mode. For example,
both-array Auto-1 at 10 MHz decreases from 0.726 to 0.501 counts. Independent
captures also vary noticeably between repetitions. Input stability, run timing
and temperature were not controlled tightly enough to assign the noise changes
to firmware alone.

## Startup settling and pauses

Across LPSPI configuration/channel pairs, median reported startup settling is
2.710 -> 2.259 -> 2.146 ms. Maximum per-capture LPSPI settling is
11.849 -> 6.692 -> 6.180 ms. All latest channel rows, across all engines,
meet the one-second warm-up criterion. The longest latest reported startup
settling across the complete matrix is 9.742 ms.

This is a coarse startup test: it finds the first five successive readings
within `max(64 counts, 6 * max(MAD, 1))` of the measurement-window median.
It does not require readings to remain inside the band afterward and does not
measure settling following each channel switch. These results cannot establish
one-count accuracy at the higher sweep rate or rule out channel crosstalk.

Raw measurement windows reveal short level dips following inter-sweep pauses:

- Single-ADC3 manual 10 MHz, latest: pauses reach 14.935 ms; the largest
  departure from the channel median is 57 counts. Across three repetitions,
  546 samples depart by more than eight counts. All occur within one millisecond
  of a gap longer than 100 us.
- The same repaired-firmware test already has this behavior: 188 samples depart
  by more than eight counts, all within the same post-gap interval; its largest
  departure is 35 counts.
- Both-array latest Auto-1 20 MHz has 262 such samples, and manual 20 MHz has
  140. Again, all lie within one millisecond after a gap over 100 us.

The user-provided sensor discharge/recharge behavior supplies a physical
explanation for this association. Earlier phase profiling attributes long gaps
to USB writes, although the latest production captures have no per-event phase
attribution. Removing five milliseconds after each gap
does not remove the single-ADC3 noise increase: the median of per-repetition
channel-median standard deviations remains approximately 0.484 -> 0.801 counts.
Thus the pause transients do not explain all the extra variation. Ordinary
switching-related discharge/recharge can also contribute during uninterrupted
sampling; this remaining variation is not established as random ADC noise.

## Why PASS is insufficient

The benchmark's baseline eligibility requires `scanorder == "interleaved"`,
manual blocking, repeat 1 and Vmid off. These sessions contain ADC-order tests
only. Every repetition's `baseline_test_ids` field is empty in all three
sessions, so baseline-relative unstable-channel and cross-mode-shift checks
were inactive. Zero warnings from those checks cannot establish analog quality.
Their normal MAD-based noise floor of 32 counts is also much larger than the
sub-count standard-deviation changes measured here.

The analysis above compares the saved channel statistics directly and examines
selected raw captures. The 252 PASS outcomes remain useful for acquisition and
stream checks, with the protocol-detection limits described in the production
report.

## Focused follow-up

Use stable known input voltages and a repeatable connection setup. Compare the
single-ADC3 manual configuration and both full arrays at 10/20 MHz. In manual
mode, compare `channelrepeat` 1, 2 and 3: these add same-channel settling
conversions and retain the final value. Check whether channel levels, standard
deviation and large excursions improve with the extra conversions. This must
be distinguished from averaging, which could reduce noise without establishing
settling.

Keep a separate sensor-connected check: a low-impedance voltage source alone
cannot reproduce the sensor's leakage and recharge behavior. Report per-channel
and per-ADC results with the mapped bias resistor. Separate steady-state
variation from post-pause dip depth, recovery time in microseconds, and recovery
sample count. Relate those metrics to the preceding gap and channel revisit
interval; compare pauses of similar duration rather than just the largest dip
in each firmware run. Do not assume the same settling tolerance or recovery
duration applies to every ADC.

For a direct switching test, alternate channels held at clearly different
known levels and check error against the expected level, including dependence
on the preceding channel. Separately inspect the first readings after long
pauses. A controlled comparison against the previous firmware is needed to
attribute any difference to faster sampling. No drift-control campaign is
needed for this small follow-up.

No firmware, runner, result files, serial connection or board upload was changed
as part of this analysis.
