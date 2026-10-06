# TestBoard 7953 USB repair: completed hardware comparison

Analyzed 2026-10-06. The uploaded repaired firmware completed all 252 captures
with runner 2.3. Every capture passed on its first attempt. Independent checks of
all raw captures found no replayed frames, backward timestamps, invalid timing,
malformed headers/counts, or discarded bytes. The USB repair preserves the
sampling optimization's throughput.

## Inputs and method

- Original firmware: `optimization_baseline_adc_10_20` (runner 2.2).
- Sampling optimization before USB repair: `optimization_after_adc_10_20_v2`
  (runner 2.2).
- Repaired firmware: `optimization_after_usb_fix_adc_10_20` (runner 2.3).
- These directories are under
  `Arduino_Sketches/TestBoard_7953/benchmarks/results/`.
- Matched all 84 configuration IDs, route lists, reference ranges, sequence
  modes, engines, clocks, repeat counts, and optional Vmid settings. The matrix
  uses seven route sets, manual/Auto-1, blocking/DMA/LPSPI, 10/20 MHz, and three
  repetitions. ADC payload order, repeat 1, optional Vmid off, seed 7953, 1 s
  warm-up, 5 s measurement, and no drift controls match the earlier sessions.
- Read metadata, repetition results, logs, and every repaired raw capture.
  Reconciled raw frame totals, warm-up slicing, measurement counts, and timing
  medians with the CSV. Independently checked whole captures, including warm-up,
  for exact repeated frames, backwards timestamp progression, invalid durations,
  and overlapping sweeps, accounting for uint32 timestamp rollover.
- Earlier raw results were reused from the independently checked comparison;
  original result files were preserved. Large per-sample CSVs were not scanned.
- Table values are medians across three repetitions. Sustained rate is the
  retained frame count divided by first-start to last-end device elapsed time,
  rather than the reciprocal of the median period. Tail maxima include all
  three retained measurement windows; p99 is the median of their p99 values.

## Stream integrity

All 252 rows report zero timestamp regressions, duplicate frames, invalid timing,
invalid frames, resynchronizations, discarded/trailing bytes, DMA/LPSPI start
errors, transfer timeouts, returned-channel errors, and USB write errors. The log
contains no failed attempts. Independent raw checks agree.

The two configurations affected in earlier sessions are now clean in all three
repetitions: full array 1, Auto-1 blocking at 10 MHz; and full array 1, manual
LPSPI at 10 MHz. Manual LPSPI now has a 72 us median period, 74 us p99, and
74 us maximum in that configuration. Corrupt earlier captures remain excluded
from rate comparisons involving their affected stage.

The retained measurement windows contain **27,807,255 sweeps**. The separate focused check also passed all 12 captures.

## Both full arrays at 20 MHz

Each sweep contains 50 channel values. The final LPSPI modes have the same
71 us acquisition and 72 us median start-to-start period.

| Mode | Original sweeps/s | Optimized sweeps/s | Repaired sweeps/s | Gain over original | Change after USB repair |
| --- | ---: | ---: | ---: | ---: | ---: |
| auto1 blocking | 10,101 | 11,302 | 11,105 | +9.9% | -1.75% |
| auto1 dma | 6,328 | 6,553 | 6,540 | +3.4% | -0.20% |
| auto1 lpspi | 11,241 | 13,836 | 13,860 | +23.3% | +0.17% |
| manual blocking | 9,441 | 11,105 | 11,190 | +18.5% | +0.76% |
| manual dma | 5,909 | 6,320 | 6,320 | +7.0% | +0.01% |
| manual lpspi | 10,524 | 13,837 | 13,841 | +31.5% | +0.03% |

Manual LPSPI retains its **31.5% gain**, with only +0.03% rate change after the
USB repair. Auto-1 LPSPI retains a 23.3% gain. Across the 83 configurations with
clean pre-repair captures, the repair's median sustained-rate change is
-0.03%, with observed changes ranging from
-1.75% to +3.49%. Three repetitions do not separate
small code effects from run-to-run variation; there is no broad throughput
regression in this matrix. The full-array Auto-1 blocking rate decreased 1.75%
from the previous optimized run, but remains 9.9% above the original.

At 10 MHz, both-array manual LPSPI delivers 10,903 sweeps/s; Auto-1 LPSPI delivers
11,173. At 20 MHz, manual LPSPI delivers about 692,000 channel values/s and
1.578 MB/s of framed USB data (114 bytes per sweep).

## Remaining timing gaps and measurement limits

Manual LPSPI, both full arrays, 20 MHz: p99 period 76 us, maximum 77 us, and no
periods exceeding 1 ms across three measurement windows. Auto-1 at the same
settings has the same median and p99, but two periods above 1 ms, maximum
3,801 us. Those positive gaps are a separate timing observation from the
previous replay/corruption fault.

Across the whole matrix, there are 247 periods above 1 ms in
98 of 252 captures, spread across
39 of 84 configurations. The longest period is 30,120 us in one-ADC bus 2,
manual blocking, 20 MHz. The longest inter-sweep gap is 30,101 us. No acquisition
exceeds 1 ms; the largest is 173 us. This locates the long gaps outside the
measured acquisition interval, but does not identify USB, foreground-loop work,
or other scheduling as their individual cause. Similar positive stalls appeared
before the repair; this comparison does not establish their cause.

For full-array manual LPSPI at 20 MHz, acquisition occupies 71 of the typical
72 us period. Entire-window gap share is about 2.15%, including periodic gaps.
Eliminating the typical 1 us gap would give only about 1.4% typical-rate
headroom. Further firmware speed work should profile acquisition phases before
choosing another optimization.

The wire format has no sequence number or checksum. Clean checks demonstrate
the absence of the detected replay/framing/timestamp anomalies in this run;
they cannot prove zero missing frames or arbitrary undetectable payload damage.
Analog accuracy, settling under different inputs, and long-duration operation
were not separately qualified by this timing comparison.

## Next step

Keep this firmware as the validated candidate for the tested matrix. No further
upload or repeat of the same full matrix is needed for this repair. The next
firmware task is acquisition and foreground-phase profiling, followed by a
measured choice of optimization. The user has deferred GUI testing until the
separate GUI repair supports the fast TestBoard. When that work is ready,
compare receive/processed/recorded rates, backlog and stop/save time against
approximately 13.8k sweeps/s. The standalone benchmark does not exercise GUI
ingestion or archive writing.

See the [USB race diagnosis](TESTBOARD_7953_USB_STREAM_DIAGNOSIS.md), the
[earlier firmware comparison](TESTBOARD_7953_BENCHMARK_COMPARISON.md), and the
[next firmware optimization plan](TESTBOARD_7953_NEXT_OPTIMIZATION_PLAN.md).
GUI repair is a separate task; the user has deferred GUI testing until it is ready.

No firmware, benchmark code, or GUI source was changed during this analysis;
only analysis documentation was updated. No serial-port access was performed.

## All 84 matching configurations

Acquisition and period columns show original -> repaired medians in us.
Rate gain is excluded when the original raw captures were corrupt; repair-rate
change is excluded when the optimized raw captures were corrupt.

| Route set | MHz | Sequence | Engine | Acquisition us | Period us | Repaired sweeps/s | Gain over original | Change after repair |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| all_four_full | 10 | auto1 | blocking | 140 -> 134 | 144 -> 135 | 7,417 | +6.6% | -1.44% |
| all_four_full | 20 | auto1 | blocking | 95 -> 89 | 99 -> 90 | 11,105 | +9.9% | -1.75% |
| all_four_full | 10 | auto1 | dma | 171 -> 164 | 174 -> 165 | 6,049 | +5.6% | -0.69% |
| all_four_full | 20 | auto1 | dma | 154 -> 151 | 158 -> 153 | 6,540 | +3.4% | -0.20% |
| all_four_full | 10 | auto1 | lpspi | 109 -> 88 | 113 -> 89 | 11,173 | +26.5% | +0.14% |
| all_four_full | 20 | auto1 | lpspi | 85 -> 71 | 89 -> 72 | 13,860 | +23.3% | +0.17% |
| all_four_full | 10 | manual | blocking | 150 -> 135 | 153 -> 137 | 7,273 | +11.6% | -0.13% |
| all_four_full | 20 | manual | blocking | 102 -> 88 | 106 -> 89 | 11,190 | +18.5% | +0.76% |
| all_four_full | 10 | manual | dma | 183 -> 170 | 187 -> 171 | 5,834 | +9.1% | -0.49% |
| all_four_full | 20 | manual | dma | 165 -> 156 | 169 -> 158 | 6,320 | +7.0% | +0.01% |
| all_four_full | 10 | manual | lpspi | 118 -> 90 | 122 -> 92 | 10,903 | +33.2% | -0.02% |
| all_four_full | 20 | manual | lpspi | 91 -> 71 | 95 -> 72 | 13,841 | +31.5% | +0.03% |
| all_four_sparse_unbalanced | 10 | auto1 | blocking | 54 -> 48 | 56 -> 49 | 20,261 | +14.0% | -0.68% |
| all_four_sparse_unbalanced | 20 | auto1 | blocking | 38 -> 32 | 40 -> 33 | 29,774 | +20.4% | -1.19% |
| all_four_sparse_unbalanced | 10 | auto1 | dma | 66 -> 60 | 68 -> 61 | 16,379 | +11.2% | -0.63% |
| all_four_sparse_unbalanced | 20 | auto1 | dma | 59 -> 55 | 62 -> 56 | 17,857 | +10.0% | +0.08% |
| all_four_sparse_unbalanced | 10 | auto1 | lpspi | 44 -> 34 | 46 -> 35 | 28,644 | +32.8% | +0.14% |
| all_four_sparse_unbalanced | 20 | auto1 | lpspi | 35 -> 27 | 37 -> 28 | 35,242 | +31.0% | -0.20% |
| all_four_sparse_unbalanced | 10 | manual | blocking | 63 -> 54 | 65 -> 55 | 17,994 | +18.0% | +0.05% |
| all_four_sparse_unbalanced | 20 | manual | blocking | 44 -> 35 | 46 -> 36 | 27,431 | +27.2% | -0.05% |
| all_four_sparse_unbalanced | 10 | manual | dma | 78 -> 69 | 80 -> 70 | 14,286 | +15.0% | -0.60% |
| all_four_sparse_unbalanced | 20 | manual | dma | 70 -> 63 | 72 -> 64 | 15,622 | +12.4% | +0.14% |
| all_four_sparse_unbalanced | 10 | manual | lpspi | 51 -> 37 | 53 -> 38 | 26,158 | +39.7% | +0.27% |
| all_four_sparse_unbalanced | 20 | manual | lpspi | 40 -> 29 | 42 -> 30 | 32,780 | +38.7% | -0.31% |
| full_array1 | 10 | auto1 | blocking | 70 -> 67 | 73 -> 68 | 14,722 | exclude | -0.02% |
| full_array1 | 20 | auto1 | blocking | 48 -> 44 | 51 -> 45 | 22,013 | +11.7% | -0.03% |
| full_array1 | 10 | auto1 | dma | 119 -> 116 | 121.5 -> 117 | 8,526 | +3.6% | -0.83% |
| full_array1 | 20 | auto1 | dma | 98 -> 91 | 100 -> 92 | 10,813 | +8.2% | +3.48% |
| full_array1 | 10 | auto1 | lpspi | 78 -> 68 | 81 -> 69 | 14,408 | +16.7% | +2.34% |
| full_array1 | 20 | auto1 | lpspi | 55 -> 47 | 57 -> 48 | 20,919 | +20.1% | +0.80% |
| full_array1 | 10 | manual | blocking | 76 -> 68 | 78 -> 69 | 14,472 | +12.9% | +0.02% |
| full_array1 | 20 | manual | blocking | 50 -> 44 | 53 -> 45 | 22,254 | +17.5% | +0.03% |
| full_array1 | 10 | manual | dma | 127 -> 120 | 130 -> 121 | 8,268 | +7.1% | -0.16% |
| full_array1 | 20 | manual | dma | 104 -> 97 | 107 -> 98 | 10,166 | +8.8% | +0.25% |
| full_array1 | 10 | manual | lpspi | 83 -> 71 | 86 -> 72 | 13,938 | +20.5% | exclude |
| full_array1 | 20 | manual | lpspi | 59 -> 47 | 61 -> 49 | 20,601 | +26.6% | +1.26% |
| full_array2 | 10 | auto1 | blocking | 70 -> 66 | 73 -> 67 | 14,818 | +8.5% | +0.36% |
| full_array2 | 20 | auto1 | blocking | 48 -> 44 | 51 -> 45 | 22,216 | +12.5% | +0.58% |
| full_array2 | 10 | auto1 | dma | 119 -> 117 | 122 -> 118 | 8,473 | +3.5% | -1.05% |
| full_array2 | 20 | auto1 | dma | 98 -> 95 | 101 -> 96 | 10,408 | +5.0% | -0.54% |
| full_array2 | 10 | auto1 | lpspi | 81 -> 70 | 84 -> 72 | 13,941 | +17.1% | -0.05% |
| full_array2 | 20 | auto1 | lpspi | 58 -> 49 | 60 -> 50 | 19,939 | +20.2% | -0.11% |
| full_array2 | 10 | manual | blocking | 76 -> 68 | 78 -> 69 | 14,477 | +13.0% | -0.03% |
| full_array2 | 20 | manual | blocking | 50 -> 44 | 53 -> 45 | 22,271 | +17.7% | -0.03% |
| full_array2 | 10 | manual | dma | 127 -> 122 | 130 -> 123 | 8,130 | +5.8% | -0.77% |
| full_array2 | 20 | manual | dma | 105 -> 99 | 107 -> 100 | 9,999 | +7.4% | +0.00% |
| full_array2 | 10 | manual | lpspi | 87 -> 72 | 90 -> 73 | 13,699 | +22.7% | +3.49% |
| full_array2 | 20 | manual | lpspi | 62 -> 49 | 64 -> 50 | 20,085 | +29.0% | +2.58% |
| one_adc_bus1 | 10 | auto1 | blocking | 29 -> 28 | 31 -> 29 | 34,698 | +8.5% | -0.33% |
| one_adc_bus1 | 20 | auto1 | blocking | 20 -> 18 | 22 -> 20 | 50,733 | +12.6% | -0.09% |
| one_adc_bus1 | 10 | auto1 | dma | 49 -> 47 | 50 -> 48 | 20,657 | +4.4% | -0.94% |
| one_adc_bus1 | 20 | auto1 | dma | 40 -> 37 | 42 -> 38 | 26,066 | +9.6% | +2.82% |
| one_adc_bus1 | 10 | auto1 | lpspi | 32 -> 28 | 34 -> 29 | 33,858 | +15.1% | +2.22% |
| one_adc_bus1 | 20 | auto1 | lpspi | 23 -> 20 | 25 -> 21 | 47,963 | +19.1% | +0.57% |
| one_adc_bus1 | 10 | manual | blocking | 31 -> 28 | 33 -> 30 | 33,757 | +12.1% | -0.07% |
| one_adc_bus1 | 20 | manual | blocking | 21 -> 18 | 23 -> 20 | 50,352 | +17.1% | -0.28% |
| one_adc_bus1 | 10 | manual | dma | 53 -> 49 | 55 -> 51 | 19,772 | +7.9% | -0.09% |
| one_adc_bus1 | 20 | manual | dma | 43 -> 40 | 45 -> 41 | 24,299 | +10.2% | +0.10% |
| one_adc_bus1 | 10 | manual | lpspi | 35 -> 30 | 37 -> 31 | 32,387 | +18.9% | +2.68% |
| one_adc_bus1 | 20 | manual | lpspi | 25 -> 20 | 27 -> 21 | 46,560 | +24.5% | +0.78% |
| one_adc_bus2 | 10 | auto1 | blocking | 29 -> 27 | 31 -> 28 | 34,963 | +9.3% | +0.12% |
| one_adc_bus2 | 20 | auto1 | blocking | 20 -> 18 | 22 -> 19 | 51,026 | +13.3% | +0.34% |
| one_adc_bus2 | 10 | auto1 | dma | 49 -> 47 | 51 -> 49 | 20,528 | +4.8% | -1.07% |
| one_adc_bus2 | 20 | auto1 | dma | 40 -> 39 | 42 -> 40 | 25,147 | +6.2% | -0.58% |
| one_adc_bus2 | 10 | auto1 | lpspi | 33 -> 29 | 35 -> 30 | 32,778 | +16.0% | -0.17% |
| one_adc_bus2 | 20 | auto1 | lpspi | 24 -> 20 | 26 -> 22 | 45,688 | +18.9% | +0.22% |
| one_adc_bus2 | 10 | manual | blocking | 31 -> 28 | 33 -> 30 | 33,790 | +12.3% | -0.08% |
| one_adc_bus2 | 20 | manual | blocking | 21 -> 18 | 23 -> 20 | 50,590 | +18.1% | -0.24% |
| one_adc_bus2 | 10 | manual | dma | 53 -> 51 | 55 -> 52 | 19,312 | +6.5% | -0.79% |
| one_adc_bus2 | 20 | manual | dma | 44 -> 41 | 45 -> 42 | 23,798 | +8.4% | -0.21% |
| one_adc_bus2 | 10 | manual | lpspi | 36 -> 30 | 38 -> 31 | 31,821 | +21.4% | +1.45% |
| one_adc_bus2 | 20 | manual | lpspi | 26 -> 21 | 28 -> 22 | 45,478 | +27.1% | +1.89% |
| one_adc_each_bus | 10 | auto1 | blocking | 57 -> 54 | 60 -> 56 | 17,958 | +7.5% | -1.10% |
| one_adc_each_bus | 20 | auto1 | blocking | 39 -> 36 | 41 -> 37 | 26,769 | +11.2% | -1.63% |
| one_adc_each_bus | 10 | auto1 | dma | 70 -> 67 | 72 -> 68 | 14,703 | +6.3% | -0.67% |
| one_adc_each_bus | 20 | auto1 | dma | 63 -> 62 | 65 -> 63 | 15,885 | +4.2% | -0.15% |
| one_adc_each_bus | 10 | auto1 | lpspi | 45 -> 37 | 48 -> 38 | 26,359 | +25.8% | +0.03% |
| one_adc_each_bus | 20 | auto1 | lpspi | 35 -> 30 | 37 -> 31 | 32,301 | +21.3% | +0.01% |
| one_adc_each_bus | 10 | manual | blocking | 62 -> 56 | 65 -> 58 | 17,349 | +12.4% | +0.05% |
| one_adc_each_bus | 20 | manual | blocking | 42 -> 36 | 45 -> 38 | 26,546 | +19.0% | +0.03% |
| one_adc_each_bus | 10 | manual | dma | 77 -> 70 | 79 -> 72 | 13,938 | +10.1% | -0.59% |
| one_adc_each_bus | 20 | manual | dma | 68 -> 65 | 71 -> 66 | 15,101 | +7.2% | -0.04% |
| one_adc_each_bus | 10 | manual | lpspi | 49 -> 38 | 51 -> 39 | 25,693 | +32.3% | -0.14% |
| one_adc_each_bus | 20 | manual | lpspi | 38 -> 30 | 40 -> 31 | 31,921 | +28.7% | -0.22% |
