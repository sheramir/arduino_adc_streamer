# TestBoard_7953 PZT front-end – QSPICE model (one ADS7953)

Transient model of **one ADS7953** (16-channel input mux + 12-bit SAR ADC) on TestBoard_7953 with its shared OPA365 buffer:
15 PZT sensors on Ch0..Ch14 → ADS7953 mux → **MXO** → OPA365 unity buffer (bias resistor from MXO to VMID) → **AINP** → sample-and-hold.
Channel 15 is the VMID channel. The other ADC pair of the board is not modelled: while it is clocked, this ADC's mux is parked on VMID.
VREF = 2.5 V, VMID = 1.25 V, SPI = 20 MHz.

Open it in the GUI (`python Qspice/Simulator/run_simulator.py`, then pick *TestBoard_7953 PZT front end* in the model list) to change
parameters, run, plot nodes, save images and compare runs; the netlist can also be generated alone with `python build_model.py`.

![GUI result](docs/gui_result.png)

*Default two-pulse scenario: ADC chain, sensor pins, force, mux enables (Ch15 = VMID park) and the sample/hold control. The circles are the
ADC hold instants on the sample capacitor.*

## What is modelled

| Block | Model |
| --- | --- |
| PZT sensors (15) | Force in N → charge source `d33·dF/dt` ‖ `Cp` ‖ 10 GΩ insulation; trace R/C and adjacent-pin coupling (same model as TestBoard_ADC124). |
| ADS7953 mux | 16 behavioral channels (Ron, off resistance, pin and feedthrough capacitance, pin leakage to ground, optional charge injection) driven by the SPI frame schedule. Break-before-make enforced. |
| MXO node | Capacitance to ground (holds the previous channel's charge) and a bias resistor to VMID (470 kΩ: ADC2/ADC3 value). |
| Buffer | OPA365 behavioral model (GBW, slew, rails, offset, bias current, input capacitance, output resistance) from datasheet SBOS365G. |
| AINP and S/H | R/C at AINP (datasheet typical application), a 15 pF sample capacitor behind a track switch. The switch opens (hold) when CS falls and tracks again at the 14th SCLK rising edge, every frame of this ADC's stream. The sample capacitor voltage at the hold instant is the value the ADC converts. |
| Timing | Frame = 16 SCLK clocks + frame gap. The mux changes 100 ns after CS falls (2nd SCLK falling edge), tracking opens 675 ns after CS falls (14th rising edge), the sample is held at the next CS fall. A sensor is connected `repeat` frames (**Repeats** on the System tab, default 1; only the last conversion is kept) and sampled `repeat × frame − 100 ns` after it is connected (1.9 µs with repeat 1). |

Sweep = the frames of the other ADCs with this mux on VMID (`n_adc` ADCs in total, default 2; each other ADC streams `other_adc_channels` × `repeat` + 2 frames, default 10 routes + 2 drain = 12 frames per other ADC; `n_adc` = 1 gives a sweep of this ADC alone), then this ADC's stream of
`n × repeat + 2` frames (`n × (repeat + 2)` with a VMID visit after every channel; 17 frames for 15 channels, repeat 1). The default sweep is 29 frames = 58 µs
(17,241 sweeps/s; the board measures 16,889 sweeps/s including software overhead, `sweep_gap_us` adds that).

## Where the numbers come from

| Parameter | Value | Source |
| --- | --- | --- |
| Sample (input) capacitance | 15 pF | ADS7953 datasheet SLAS605C, electrical characteristics |
| Input leakage | 3.5 / 5.1 / 7.0 nA at 25 °C for a pin at 0 / 1.25 / 2.5 V (20 / 36 / 44 nA at 110 °C) | Datasheet **Figure 43** (AINP leakage vs temperature, VA = VBD = 5 V), curves read by eye (about ±1 nA), interpolated log-linearly in temperature and linearly in pin voltage; the 2.5 V curve extrapolates to 59 nA at 125 °C, close to the 61 nA in the electrical characteristics. Applied as a current to ground at every channel pin and at AINP, same sign everywhere (worst case). Whether the figure also applies to the off channel pins is an assumption. |
| Minimum acquisition, aperture delay | 325 ns, 5 ns | Datasheet. The adapter warns when the track window is below 325 ns. |
| Mux change / track opens / MXO settling | 2nd SCLK falling edge / 14th rising edge / ~600 ns before sampling | Datasheet and `docs/architecture/firmware/TESTBOARD_7953_CAPTURE_TIMING_REPORT.md` |
| SPI clock, 16-clock frame, bias 470 kΩ, channel 15 = VMID | 20 MHz, 16, 470 kΩ, VMID | Capture-timing report; VREF/VMID from the user |
| Frame gap | 1200 ns (frame ≈ 2 µs) | **Derived**: 16,889 sweeps/s (TestBoard_7953 README) over 29 frame slots ≈ 2.04 µs; replace with a CS/SCLK scope measurement |
| First SCLK edge after CS falls | 25 ns | Assumption from the timing report's illustration |
| Mux Ron (200 Ω), pin / feedthrough capacitance, track switch (200 Ω), MXO capacitance (10 pF), R/C at AINP (100 Ω / 150 pF), VMID channel network, supply (3.3 V), mux delays, charge injection (0) | – | **Placeholders**: not in any supplied document. The datasheet gives no mux Ron; AINP R/C is its typical-application value, not this board's schematic. |
| PZT SM311 (d33 600 pC/N, εr 3500), 0.7 × 0.7 × 0.25 mm | – | Steminc table; size from TestBoard_ADC124 (confirm for this board) |

## Presets (Simulation tab)

- `two_pulses`: pulses on channels 2 (0.06 N) and 4 (0.10 N), 6 sweeps. About 0.12 N already brings a 0.7 mm sensor to VREF; the adapter warns above that.
- `baseline`: no force, 5 ms (about 20 s at 5 ns): the baseline of every channel. With the Figure 43 leakage (about 5 nA per pin at 25 °C) the baseline settles within ~4 ms to a channel-dependent offset: −17 mV on Ch0 (first after the VMID park) growing to −67 mV on Ch14, mean −54 mV (about 90 LSB of the 12-bit ADC). Cause: each sensor floats ~56 µs per 58 µs sweep and is refreshed through the 470 kΩ bias for 2 µs; without a VMID visit between channels the MXO node also passes each channel's deficit on to the next. A longer run (12 ms) confirms it is stable.
- `repeat_3_vmid_between`: manual repeat 3 with a VMID visit after every channel.

## Limitations

- Only one ADC; the other pair appears only as parked time. The two buses and the Teensy are not modelled.
- No ADC quantisation or code output; the converted value is the voltage on the sample capacitor at the hold instant (12-bit LSB at 2.5 V is 0.61 mV).
- No hold droop, comparator or reference noise; leakage uses the same sign on every channel (worst case).
- Long runs create long piecewise-linear control sources: a 5 ms run takes about 20 s and a 60 ms run a few minutes at the 5 ns step.

## Files

`config.json` defaults and scenarios · `build_model.py` netlist generator and SPI frame schedule · `simulator_model.json` GUI manifest ·
`simulator_adapter.py` GUI plugin · `models/` behavioral cells · `TestBoard_7953_PZT.cir` netlist of the defaults ·
tests in `../Simulator/tests/test_model_7953.py`.
