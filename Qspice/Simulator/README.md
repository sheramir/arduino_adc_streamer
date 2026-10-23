# Qspice Simulator

A GUI front end for QSPICE circuit models. Pick a model in the toolbar ([TestBoard_ADC124](../TestBoard_ADC124/README.md) and [TestBoard_7953](../TestBoard_7953/README.md) are included), change
component, system and simulation parameters, choose which nodes to display, run QSPICE, look at the node waveforms, save the image and
run again with different parameters. Any folder that follows the [model contract](#adding-a-model) shows up in the model list.

![Result with a held reference run](docs/result_with_reference.png)

*Two-pulse scenario of TestBoard_ADC124 with the mux leakage raised from 1 nA to 10 nA. The dashed traces are the held reference run
(1 nA), the solid traces the new run; the plot title lists the parameters that were changed.*

## Start

```bash
pip install PyQt6 pyqtgraph numpy          # already dependencies of this repository
python Qspice/Simulator/run_simulator.py                     # or: python -m qspice_sim  (from Qspice/Simulator)
python Qspice/Simulator/run_simulator.py --model TestBoard_ADC124 --qspice "C:\Program Files\QSPICE\QSPICE64.exe"
python Qspice/Simulator/run_simulator.py --models D:\my_models     # extra folder of models
```

QSPICE is found via `--qspice`, the Model tab, the `QSPICE_EXE` environment variable or `C:\Program Files\QSPICE\QSPICE64.exe`.
Models are looked up in `Qspice/*/` plus the folders in `--models` and `QSPICE_MODEL_PATH`.

## Screens

| Tab | What you do there |
| --- | --- |
| **Model** | Pick the model (also in the toolbar), read its description, set the QSPICE path, add another model folder, reset every parameter to the model defaults, reload the model files after editing them. |
| **Components** | Edit component parameters (sensor material and size, bias network, mux leakage / capacitances / charge injection, op-amp, parasitics). A typed value is applied on Enter, when you leave the field, and also when you press Run (F5), Hold as reference, Save settings or Update estimate. Values accept engineering notation (`1e10`, `470k`, `1.5n`, `2meg`). Changed values are highlighted, the ↺ button resets one value, the filter box finds a parameter by name. |
| **System** | System-level parameters of the scan: scan order, settle / acquisition / conversion / VMID times and the per-sensor sampling rate (when set, the park time is derived from it). The *Derived values* box shows the resulting cycle time, sampling rate, sensor capacitance and sensitivity. |
| **Simulation** | Input profile (table of force pulses: sensor, start, rise, hold, fall, amplitude; second table of sine waves, **Add sin**: sensor, start, frequency, number of cycles, amplitude), preset scenarios, measurement time (run duration or number of scan cycles), solver step. *Update estimate* predicts number of time points, run time and result size. |
| **Visualization** | Tick the nodes to display (grouped by plot panel; *Other nodes* lists every node found in the netlist), layout (stacked per group / one plot per node / single overlay), time window, line width, sample markers, reference overlay, title annotation. |

Toolbar: **Run** (F5), **Stop** (Esc), **Save image…** (PNG or SVG), **Export data…** (CSV of the visible time range),
**Hold as reference** / **Clear reference**, **Load / Save settings…** (all parameters and display options as JSON).

## Typical workflow

1. Choose a preset on the Simulation tab (for example `two_pulses`) or edit the input profile.
2. Change parameters, for example *Components → Off-state S→D leakage per channel*.
3. Pick the nodes on the Visualization tab and press **Run**. Only the selected nodes are saved by QSPICE, which keeps long runs small.
4. Zoom with the mouse wheel / drag; the plot re-decimates (min/max envelope), so spikes survive even with tens of millions of points.
5. **Save image…**, or **Hold as reference**, change a parameter and **Run** again to compare against the dashed reference. The reference stays until you clear it or confirm a replacement (pressing *Hold as reference* again asks first), so any number of runs with different settings can be compared against the same original reference; the plot title shows the changed parameters of the current run and of the reference.
6. Changing the node selection after a run re-plots instantly when the nodes were saved; otherwise press Run again.

Long simulations: QSPICE does about 60 000 time points per second. A 60 ms run at the model's 5 ns step is ~12 M points (~4 minutes,
~100–200 MB per saved node). The Run button warns when the estimate exceeds 90 s or 500 MB; the run can be stopped at any time.
A coarse maximum step is much faster but unreliable for models with ns-wide events (see the TestBoard_ADC124 reports).

Run files are written to `Qspice/Simulator/runs/<model>/` (git-ignored) and overwritten by the next run.

## Adding a model

A model is a folder directly below `Qspice/` (or below a folder passed with `--models`) containing:

| File | Purpose |
| --- | --- |
| `simulator_model.json` | Manifest: name, description, parameter forms, input tables, plot groups, node list. |
| `config.json` (name set in the manifest) | Default configuration: any nested JSON. Dotted paths (`mux.ileak_s_off_nA`) address values. An optional `"scenarios": {name: {"description", "overrides": {path: value}}}` entry defines the presets. |
| `simulator_adapter.py` (name set in the manifest) | Python module that turns a configuration into a SPICE netlist. |

Adapter contract (any extra files, models, libraries stay in the model folder; the adapter loads them itself):

```python
def build(cfg: dict) -> dict:
    return {"netlist": "<SPICE text with a .tran statement>",
            "t_stop": 5.7e-4,                                  # seconds
            "samples": [{"t": 1.2e-6, "label": "addr 0"}],     # optional: times shown as markers
            "warnings": ["optional message shown above the plot"]}
    # raise ValueError("readable message") for invalid parameters

def summary(cfg: dict) -> list[tuple[str, str]]:               # optional, shown as "Derived values" on the System tab
    return [("Scan cycle", "133 us")]
```

Manifest keys:

```jsonc
{
  "name": "...", "description": "...", "config": "config.json", "adapter": "simulator_adapter.py",
  "components": [ {"group": "MUX", "items": [ {"path": "mux.ron_ohm", "label": "On resistance", "unit": "ohm",
                                               "type": "float", "tip": "tooltip", "nullable": false} ]} ],
  "system": [ ... ], "simulation": [ ... ],            // same structure; types: float, int, bool, choice (+ "choices"), intlist
  "tables": [ {"path": "forces", "title": "...", "columns": [{"key": "amp_N", "label": "Amplitude [N]", "type": "float"}],
               "new_row": {"amp_N": 0.1}, "add_label": "Add pulse"} ],   // editable list-of-dicts (the input profile); add_label = text of the add button
  "plot_groups": [ {"id": "adc", "title": "ADC input [V]"} ],     // one stacked plot panel per group
  "nodes": [ {"name": "ain", "label": "AIN_B4", "group": "adc", "default": true} ],
  "sample_marker": {"node": "ain", "label": "ADC hold samples"}   // optional: marks the adapter's sample times on this node
}
```

- Every `path` must exist in the default configuration; the Model tab lists manifest problems.
- The simulator replaces all `.save` lines of the netlist by `V(node)` for the ticked nodes, so adapters do not need to save anything.
  Nodes found in the netlist but not listed in the manifest appear under *Other nodes*.
- Only node voltages and transient analysis are supported. (QSPICE turns `.save I(R1)` into an alias instead of a saved column.)
- Models are loaded with a unique module name, so several models may each have their own helper files (use the `_load_sibling` pattern of
  [TestBoard_ADC124/simulator_adapter.py](../TestBoard_ADC124/simulator_adapter.py)).

## Code layout

```
Simulator/
  run_simulator.py          entry point
  qspice_sim/
    model_loader.py         model discovery, manifest validation, adapter loading
    runner.py               QSPICE discovery, prepare/estimate, run with progress and cancel
    netlist_tools.py        .save handling, node discovery, .tran parsing
    qraw.py                 binary .qraw reader (memory-mapped)
    decimate.py             min/max envelope for fast zoomable plots
    config_utils.py         dotted-path access, engineering-notation parser
    gui/                    main_window.py, param_form.py (schema forms + table editor), plot_panel.py, worker.py
  tests/                    pytest: core, real QSPICE runs, headless GUI (Qt offscreen)
  tools/make_screenshots.py regenerates docs/*.png
```

## Tests

```bash
python -m pytest Qspice/Simulator/tests          # 41 tests; the QSPICE and GUI-run tests are skipped when QSPICE is missing
```

They cover parameter parsing, netlist handling, decimation, model discovery, a real QSPICE run, the effect of a changed leakage on the
simulated baseline, cancellation, periodic-control runs and the headless GUI (editing, presets, run, reference overlay, image export).

## Limitations

- One transient simulation at a time; results of earlier runs are replaced (use *Hold as reference* to keep one for comparison).
- The result plot shows saved node voltages only; measurement post-processing specific to a model (for example the ADC-hold sample
  tables of the TestBoard_ADC124 reports) stays in that model's scripts. The sample markers show where those samples are taken.
- The time estimate is a rough rule (simulated time / maximum step ÷ 60 000 points per second) measured on the TestBoard_ADC124 model.
