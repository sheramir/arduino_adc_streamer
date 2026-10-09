# TestBoard 7953 manual ghosting results

Recorded from the board designer's observations supplied on 9 October 2026. Sensor strips attached. **Vmid off:** 5, 10 and 20 MHz. **Vmid on:** 20 MHz. Channel repeat, scan order and SPI engine were not supplied. No raw traces or calibrated response-ratio measurements accompanied these notes. Percentages below are approximate visual estimates.

## Method and physical routes

Press a TOP sensor and observe the next sensor's BOTTOM and LEFT inputs in ADC/MUX order. Global ADC numbering is used: Array 2's first and second ADCs are ADC3 and ADC4.

| Array | Global ADC | Shared MXO bias | Press | Observe next BOTTOM | Observe next LEFT |
|---|---|---|---|---|---|
| 1 | ADC1 | 1 MΩ | PZT6_T, ch4 | PZT7_B, ch5 | PZT7_L, ch6 |
| 1 | ADC2 | 470 kΩ | PZT1_T, ch4 | PZT3_B, ch5 | PZT3_L, ch6 |
| 1 | ADC2 | 470 kΩ | PZT3_T, ch9 | PZT5_B, ch10 | PZT5_L, ch11 |
| 2 | ADC3 | 470 kΩ | PZT6_T, ch4 | PZT7_B, ch5 | PZT7_L, ch6 |
| 2 | ADC4 | 249 kΩ | PZT1_T, ch4 | PZT3_B, ch5 | PZT3_L, ch6 |
| 2 | ADC4 | 249 kΩ | PZT3_T, ch9 | PZT5_B, ch10 | PZT5_L, ch11 |

The Array-2 PZT6_T 5 MHz note originally named the second affected channel as “5_L”; this report interprets it as PZT7_L/ch6, consistent with the method and route table. No numeric value is assigned to qualitative observations.

## Observations

| Press and ADC | 5 MHz | 10 MHz | 20 MHz |
|---|---|---|---|
| Array 1, ADC1, PZT6_T | About 30% at PZT7_B; follows into PZT7_L | Almost 50% at PZT7_B; follows into PZT7_L | More than 50% at PZT7_B; follows into PZT7_L |
| Array 1, ADC2, PZT1_T | Less than 20% at PZT3_B; no observed carryover into PZT3_L | About 40% at PZT3_B; follows into PZT3_L | About 40% at PZT3_B; follows into PZT3_L |
| Array 1, ADC2, PZT3_T | About 20% at PZT5_B; small carryover into PZT5_L | About 30% at PZT5_B; follows into PZT5_L | More than 50% at PZT5_B; follows into PZT5_L |
| Array 2, ADC3, PZT6_T | Some ghosting at PZT7_B; small carryover into PZT7_L | About 40% at PZT7_B; follows into PZT7_L | More than 50% at PZT7_B; follows into PZT7_L |
| Array 2, ADC4, PZT1_T | Very small at PZT3_B; no observed carryover into PZT3_L | Small at PZT3_B, larger than 5 MHz; hardly follows into PZT3_L | Larger than 10 MHz but smaller than 470 kΩ/1 MΩ paths; very small carryover into PZT3_L |
| Array 2, ADC4, PZT3_T | Very small at PZT5_B; no observed carryover into PZT5_L | Small at PZT5_B, larger than 5 MHz; hardly follows into PZT5_L | Larger than 10 MHz but smaller than the preceding higher-resistance paths; very small carryover into PZT5_L |

No ghosting was noticed on earlier ADC/MUX channels, or between different ADC/MUXs. Ghosting within one sensor is harder to distinguish from physical coupling during manual pressing.

## Vmid on at 20 MHz

The same six pressing routes were tested with Vmid insertion on. The tester considered the results satisfactory and did not repeat 5/10 MHz with Vmid on.

| Route / shared bias | 20 MHz Vmid off | 20 MHz Vmid on |
|---|---|---|
| Array 1, ADC1, 1 MΩ, PZT6_T → PZT7_B | More than 50%; also follows to PZT7_L | Very small, less than 20% at PZT7_B; no ghosting follows to PZT7_L |
| Array 1, ADC2, 470 kΩ, PZT1_T → PZT3_B | About 40%; also follows to PZT3_L | No ghosting observed at PZT3_B |
| Array 1, ADC2, 470 kΩ, PZT3_T → PZT5_B | More than 50%; also follows to PZT5_L | No ghosting observed at PZT5_B |
| Array 2, ADC3, 470 kΩ, PZT6_T → PZT7_B | More than 50%; also follows to PZT7_L | Almost no ghosting, about 5% at PZT7_B |
| Array 2, ADC4, 249 kΩ, PZT1_T → PZT3_B | More than at 10 MHz, less than higher-resistance paths; very small at PZT3_L | No ghosting observed at PZT3_B |
| Array 2, ADC4, 249 kΩ, PZT3_T → PZT5_B | More than at 10 MHz, less than higher-resistance paths; very small at PZT5_L | No ghosting observed at PZT5_B |

“No ghosting observed” does not establish a measured zero or detection threshold. LEFT-channel outcomes were not specified in the Vmid-on notes except for ADC1. Global ADC3/4 correspond to the first/second ADCs of Array 2.

## Interpretation and remaining measurements

Forward carryover increases with SPI speed. The 249 kΩ path shows less observed ghosting than the 470 kΩ and 1 MΩ paths. This is consistent with analog settling or shared-node charge history; it does not establish the mechanism, because ADC, routing and resistance differ together. The channel-11 controls separately demonstrate selection-history-dependent baselines, not a measured ghosting transfer function.

At 20 MHz, Vmid insertion greatly reduces the observed forward ghosting on all six routes. Four routes show no observed ghosting; the 1 MΩ ADC1 path remains below 20%, and ADC3 remains around 5%. This supports Vmid insertion as a practical mitigation under the tested conditions, but does not demonstrate a channel-11 baseline correction or establish a calibrated improvement factor.

The manual Vmid-on comparison is complete at 20 MHz; lower-clock repeats are not planned. Retain raw traces to quantify residual response ratios, delay, recovery and observation thresholds; document engine, scan order and repeat, and use a repeatable input to separate electrical carryover from physical coupling. Account for Vmid insertion's sampling-rate cost when choosing operating settings.
