# TestBoard 7953: live USB hardware validation

Analyzed 2026-10-07. All 18 diagnostic-firmware captures pass on their first
attempts. SPI acquisition continues during real USB backpressure while complete
unsent sweeps are discarded. The intentional 500 ms host-reader pause produces
approximately 8,000 discarded sweeps per capture without a sensor sampling
pause. The previously observed large post-pause signal dips are absent from
received measurement data. The subsequent 18-capture production comparison
also passes; see [production results](TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md)
for mixed-engine coverage, remaining blocking dips and the next stress check.

## Sessions and independent checks

Results are under `Arduino_Sketches/TestBoard_7953/benchmarks/results/`:

- `live_usb_20261007T160816Z_normal20`: nine captures, manual LPSPI at 20 MHz,
  full array 1, both full arrays and single ADC3, three repetitions each.
- `live_usb_20261007T160816Z_adc3_10`: three single-ADC3 manual LPSPI 10 MHz captures.
- `live_usb_20261007T160816Z_deferred20`: three both-array 20 MHz captures with
  raw reads during acquisition and parsing afterward.
- `live_usb_20261007T160816Z_pause500ms20`: three deferred-parser both-array
  captures with an intentional 500 ms read pause at elapsed 2 s.

Runner 2.5, profiling available and enabled, profile version 2, ADC payload order,
repeat 1, optional between-channel Vmid off, 1 s warm-up, 5 s measurement and
no drift controls. All sessions have completed metadata. All channel rows meet
the coarse startup-settling test, with maximum 5.259 ms, well inside warm-up.

Independently decoded every raw capture as complete fixed-layout frames:
headers, route counts, 12-bit sample ranges, positive acquisition durations,
monotonic nonoverlapping start/end times and unique whole frames are valid.
Reconciled full and measurement frame counts and warm-up cuts against CSV.
Recomputed every measurement channel's standard deviation, median and extrema
from raw samples and reconciled them with the channel-statistic CSV.

Across the sessions, firmware acquired 2,721,609 sweeps, submitted 2,685,807
complete frames and discarded 35,802 sweeps. Raw frame counts exactly match
submitted counts in every capture. Acquired = sent + discarded, with no aborted
profile attempts, clock changes or counter-wrap ambiguity. All reported firmware
errors, frame/timestamp faults, resynchronizations and discarded-byte counters
are zero. Checked 55,521,235 received measurement channel values; the large
per-sample CSVs did not need to be read. Result sources and firmware were not
changed during analysis; no serial port or board upload was used.

## Sampling stays continuous while transmission stalls

| Selection / reader | Typical received-frame period, us | Largest actual sensor period, us | Discarded sweeps per capture | Discard fraction of whole run |
| --- | ---: | ---: | ---: | ---: |
| Both arrays, normal, 20 MHz | 62 | 66 | 80-124 | 0.083-0.128% |
| Both arrays, deferred parsing, 20 MHz | 62 | 66 | 0 | 0% |
| Both arrays, deferred parsing + 500 ms pause | 62 | 66 | 7,967-7,980 | 8.214-8.229% |
| Array 1, normal, 20 MHz | 44 | 46 | 118-153 | 0.087-0.113% |
| ADC3, normal, 20 MHz | 21 | 26 | 3,124-3,596 | 1.096-1.262% |
| ADC3, normal, 10 MHz | 31 | 35 | 337-404 | 0.172-0.206% |

Typical periods shown are retained-frame medians. Actual acquisition profiles
and firmware maximum/over-1-ms counters reconcile exactly.
There are no actual sensor periods above 1 ms anywhere, including warm-up and
discarded sweeps. Since the largest period is 66 us, no period exceeds 100 us
either. The largest measured USB write is 4.657 us.

The forced-pause captures have received-frame gaps of 489.614-490.311 ms. These
are omitted transmissions, while the sensor kept being sampled at intervals
no longer than 66 us. The normal ADC3 20 MHz captures likewise have received
gaps of 26.930-29.858 ms but actual sensor intervals no longer than 26 us.
Received gaps must not be treated as renewed sensor sampling stalls.

For a matched diagnostic comparison, the prior `lpspi_word_path_on_adc20`
both-array captures had actual periods up to 11.670 ms and USB writes up to
11.609 ms. Typical acquisition/period medians are unchanged at 58/62 us;
array 1 likewise remains 41/44 us. The new mechanism addresses host-dependent
timing tails rather than changing the SPI transfer loop.

Enabled-profile both-array acquisition runs at approximately 16,155 sweeps/s;
the forced-pause runs are approximately 16,165 sweeps/s. Their delivered
post-warm-up rate falls to about 14,572 sweeps/s because the required omissions
are real. Production rates should be measured with probes off.

## Reader-side contribution

Normal both-array reading discards 80, 124 and 89 sweeps; parsing after capture
discards zero in all three runs. This supports parsing/scheduling in the host
read loop as a contributor to backpressure. These are sequential runs, not a
measurement of CPU utilization or isolation of the Windows driver, USB host
controller or Python scheduler. It does not establish that every stall has
the same trigger.

The deliberately paused reader produces thousands of firmware discards, so
this stress test did exercise board-side USB backpressure; Windows did not
absorb the entire pause. The board stores no acquisition history for replay.
Previously accepted USB/Windows bytes can still arrive late, and these data do
not measure end-to-end delivery age or guarantee latest-frame display in a GUI.
Continuously draining raw bytes and processing them separately is the supported
next host-side direction. GUI integration remains a separate task.

## Channel behavior and resistor differences

All received measurement samples in these 18 captures stay within four counts
of their own channel's measurement-window median. There are no departures
greater than eight counts, including after the approximately 490 ms received
gaps. Earlier ADC3 manual 10 MHz production captures contained departures up
to 57 counts after real sampling pauses. This is consistent with the user's
sensor explanation: continuous selection prevents the extended discharge that
occurred while blocking USB writes stopped ADC sweeps.

Values below are the median of three repetitions for each channel, then the
median across selected channels. Standard deviation measures observed signal
variation, not isolated electronic noise.

| Manual LPSPI selection | Previous production standard deviation, counts | New diagnostic, normal reader |
| --- | ---: | ---: |
| Both arrays, 20 MHz | 0.524 | 0.500 |
| Array 1, 20 MHz | 0.511 | 0.460 |
| Single ADC3, 20 MHz | 0.632 | 0.499 |
| Single ADC3, 10 MHz | 0.830 | 0.480 |

Both-array measurements by ADC:

| ADC / mapped bias resistor | Normal reader standard deviation, counts | Forced reader pause standard deviation, counts |
| --- | ---: | ---: |
| ADC1 / 1 MOhm | 0.526 | 0.504 |
| ADC2 / 470 kOhm | 0.497 | 0.453 |
| ADC3 / 470 kOhm | 0.508 | 0.494 |
| ADC4 / 249 kOhm | 0.432 | 0.430 |

The forced-pause channels show no increase in variation or resumption dip in
received samples. Discarded values are not transmitted and their analog levels
cannot be inspected from these recordings. The firmware profiles establish
acquisition continuity, not every discarded sample's voltage.

Production versus diagnostic comparisons include different probe overhead,
sampling cadence and run times. Sensor inputs were not controlled enough to
attribute every standard-deviation change to USB alone. Coarse startup settling
for both arrays is about 2.937 ms in the new diagnostic runs versus 2.633 ms
in the earlier production run; all channels settle within warm-up. This still
does not measure accuracy after each channel switch. ADC-specific leakage,
capacitance, recharge time and resistor values remain relevant.

Baseline-relative unstable-channel/cross-mode warnings are still inactive
because these ADC-order sessions contain no eligible interleaved-order
reference. Conclusions above use direct raw/channel comparisons, not absence
of those warnings. The protocol also lacks sequence numbers/checksums;
clean frame checks do not detect every possible payload corruption.

## Next validation

The production `teensy41` both-array comparison is complete: all 18 manual/Auto-1
blocking/DMA/LPSPI captures pass. Both LPSPI modes discard zero sweeps with the
deferred reader, and manual retains approximately 16,887 sweeps/s. See
[production validation](TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md) for
sampling continuity, DMA's approximately 3% rate decrease and localized
blocking-mode dips. The six subsequent production LPSPI forced-pause captures
also pass: maximum actual sensor interval 66 us, 49,187 total discarded sweeps,
and all received values in the first 10 ms after each gap within two counts of
their channel median. The full 252-capture production matrix is now also complete:
all final captures pass, actual sampling intervals stay within 171 us across
engines and 86 us in LPSPI, and both-array manual LPSPI retains 16,887 sweeps/s.
See [full-matrix results](TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md), including
the export artifacts from disk-full/resume. Keep each output directory separate.
