## Plan: Board Registry, JSON MCU Profiles, and Shared Parameter Handling

Status: IMPLEMENTED - all MCU profiles, shared bindings/adapters and capture migration implemented; automated checks passed; hardware acceptance pending.
Date: 2026-10-02
Workspace: `C:/Code/arduino_adc_streamer/`

Implementation record: [board maintenance](../../../config/boards/README.md),
[profile coverage](../../../config/boards/coverage.md), and `tests/test_board_registry.py`.
Active firmware was not changed. Hardware validation remains manual as documented.
Verification: 900 tests and 34 subtests passed; registry audit validated 13 profiles
and seven active identities; offscreen GUI startup and 18 profile/mode transitions
passed.

Refactor the Python application so supported boards are described by versioned
JSON profiles selected through their reported MCU names. Centralize each board's
parameter definitions, defaults, limits, supported modes, labels, units, and
adapter selection. GUI construction, configuration validation, command generation,
voltage conversion, and processing must consume the same resolved definitions.

The implementer must build and populate the new JSON profiles for **every existing
supported board/MCU, historical compatibility identities, generic fallback paths,
and TestBoard_7953**. A registry framework with only a TestBoard example does not
complete this plan. Migrate existing consumers and remove their competing active
definitions while preserving working acquisition, visualization, and file behavior.

Keep sensor positions and sensor-to-ADC/input associations in
`sensor_configurations.json`. Remove TestBoard's duplicate Python PZT wiring map.
Keep executable protocol and processing algorithms in reusable Python adapters.
Future boards using existing adapters should be added through JSON and sensor
configuration changes without editing GUI, configuration, or processing branches.

This task creates the implementation plan and its index entry only. Existing
TestBoard GUI implementation changes in the workspace are the migration baseline;
do not overwrite or revert them while planning or implementing this refactor.

**Current behavior and gaps**

- `config/mcu_profile.py` describes capabilities through hardcoded constructors,
  MCU-name equality/prefix/substring tests, and board-specific properties.
- `config/mcu_detector.py` contains separate ground-pin/default rules and combined
  PZT/RS tuning defaults. Other files repeat MCU identity tests and capability
  decisions instead of consuming one resolved profile.
- TestBoard reference choices appear in `mcu_profile.py`, `gui/testboard_panel.py`,
  `config/config_snapshot.py`, and acquisition validation. Voltage conversion adds
  another string-based interpretation in `config_handlers.py`.
- SPI defaults, repeat limits, frame settings, and Vmid values are repeated in
  configuration state, requests, snapshots, widgets, and board helpers. Moving
  one copy into JSON without updating all consumers would leave the duplication.
- `PZT_SENSOR_ROUTES`, `PZT_CHANNEL_LABELS`, and `ARRAY_ADC_LANES` in
  `testboard_7953_board.py` duplicate mapping data in the sensor library. The JSON
  is currently checked against these Python mappings, preventing JSON-only edits.
- `ADCConfigurationState` and requests acquire board-prefixed fields as new boards
  are added. Generic `repeat` also obscures the distinction between retained
  samples per channel and ADS7953 settling conversions.
- Serial configuration and status handling differ across MG24 ADC, Teensy ADC,
  555, paired array boards, combined PZT_RS, and ADS7953. Data files cannot replace
  the algorithms needed to encode commands and decode these formats.
- Existing firmware documents and host behavior are not entirely equivalent.
  Examples needing audit include Teensy OSR/averaging choices, the Teensy555 baud
  exception, and PZT_RS support among revisions reporting `Array_PZT_PZR1`.
  Record and resolve these explicitly; do not infer support from a family name.

**Target ownership and runtime flow**

| Information | Single owner |
| --- | --- |
| Board IDs, MCU names/aliases, supported modes, parameter definitions/defaults/limits, labels/units, hardware capacities, feature policies | Board profile JSON |
| Sensor spatial layout, placement labels/order, polarity, sensor-to-ADC/input mappings, physical-array associations | Sensor configuration JSON |
| Command sequencing, encoding/normalization, ACK/status semantics, frame decoding | Registered protocol adapters |
| Route ordering, frame/sample interpretation, hardware timing and specialized processing algorithms | Registered acquisition/processing adapters |
| Requested acquisition values and per-board user preferences | Validated runtime settings and existing JSON persistence helpers |
| Reported/effective device values | Normalized firmware status |
| Display array, visibility and other presentation choices | Separate view state |
| Configuration used to interpret recorded samples | Immutable capture descriptor with resolved profile and sensor mapping |

Runtime flow:

```text
reported MCU name -> BoardRegistry -> resolved BoardProfile + selected ModeProfile
                                      |             |
                             parameter controls     validation/normalization
                                      |             |
                                      +-- requested settings
                                                |
sensor configuration -> acquisition adapter -> protocol adapter -> firmware
                                                |
                                     verified/effective settings
                                                |
                            frozen capture descriptor + acquired data
                                                |
                                  processing -> display projection
                                                |
                                           export/reload
```

The registry resolves identity centrally. Downstream components receive a typed,
immutable profile/context rather than repeatedly resolving a name. Keep the raw
reported MCU name alongside the stable profile ID for diagnostics and captures.

**Required JSON profile inventory**

Use `Arduino_Sketches/README.md`, active sketches, existing host paths, and tests
to build a checked inventory before migrating behavior. Proposed files below are
deliverables, not empty placeholders. Equivalent identities may share one file
through aliases; differing behavior needs a separate profile/variant.

| Proposed JSON file under `config/boards/profiles/` | MCU identity / required coverage | Source and audit notes |
| --- | --- | --- |
| `mg24.json` | `MG24` | Active `MG24/ADC_Streamer_binary_scan/`; ADC reference, OSR, gain, channels, ground, repeat/buffer and current command/status/frame behavior |
| `mg24_mux.json` | `MG24_MUX` | Active ADG1206 MUX variant; retain its channel selection and charge/reset differences where exposed |
| `teensy40_adc.json` | `TEENSY40` | Active `Teensy/ADC_Streamer_binary_scan2/`; fixed 3.3 V scaling, actual OSR/averaging and compatibility-only gain semantics, speed/rate controls |
| `teensy_adc_compat.json` | Historical `Teensy4.1` and other currently accepted Teensy ADC identities | Host tests exercise this identity; audit available firmware before treating it as an alias of TEENSY40. Preserve compatibility without inventing identical hardware behavior |
| `teensy555.json` | `Teensy555` | Active `Teensy/Teensy555_streamer/`; 555 tuning, value units, repeat/block limits, transport and ACK/status behavior |
| `array_pzt1.json` | `Array_PZT1` | Supported historical PZT array path; firmware under `legacy/Teensy_MG24_SPI/` and current host tests; preserve paired ADC payload behavior |
| `array_pzt_pzr1.json` | `Array_PZT_PZR1` | PCB1.0/1.5 paths share this identity; preserve applicable mode/tuning/ground policies and audit PZT_RS capability/revision ambiguity |
| `array_pzt_pzr17.json` | `Array_PZT_PZR1.7` | Both active monolithic and modular PCB1.7 paths; PZT, PZR, PZT_RS, combined routing, held RS values, timing-model selection and default policies |
| `array_dual_compat.json` | `Array_PZT_PZR_v1` and existing unmatched dual-array family behavior | Compatibility path exercised by current tests; do not grant PZT_RS merely because the name has the family prefix |
| `testboard_7953.json` | `TestBoard_7953`, alias `PCB_TestBoard_7953` | Current implemented two-array PZT-only GUI and active ADS7953 firmware; full requirements below |
| `generic_555.json` | Existing generic 555 identity/fallback, including `555 Analyzer` | Preserve the current generic analyzer presentation and defaults; distinguish confirmed firmware identity from compatibility fallback |
| `generic_adc.json` and, if required by the audited behavior, `generic_array.json` | Unknown/no-MCU generic path and existing unmatched Array family behavior | Explicit fallback profiles, preserving currently supported fallback behavior without inheriting TestBoard or combined-mode capabilities |

Also audit the timing-only historical spelling `Array_PPZT_PZR1` and every other
MCU literal in host code/tests. Register a compatibility mapping only when its
meaning is verified; otherwise document the limited existing behavior separately.
List each final profile's firmware sources, host compatibility evidence, modes,
and unresolved hardware assumptions in a checked-in coverage document.

An MCU name may identify a family without distinguishing firmware revisions. For
shared names, use a validated explicit variant selection or already available
reported capability/version information when needed. Do not add new firmware
commands or advertise capabilities unconditionally. If an existing host/firmware
discrepancy cannot be settled from the repository, document it and preserve the
existing compatibility path rather than silently changing unrelated behavior.

**Profile schema and proposed package layout**

```text
config/boards/
    schema.json
    registry.json
    profiles/                       # populated files from the inventory above
    models.py                       # immutable profile and parameter models
    registry.py                     # loading, validation, identity resolution
    validation.py                   # settings validation and dependency rules
    README.md                       # maintenance and add-a-board instructions

serial_communication/protocols/
    registry.py                     # adapter IDs -> explicit implementations
    ...                             # wrappers/refactoring of existing protocols

gui/board_controls.py               # shared controls and parameter bindings
```

Keep existing processing modules and mixins; introduce focused helpers where the
current ownership requires them. Do not create a new monolithic board manager.

Profiles require `schema_version`, `profile_version`, a stable `id`, exact MCU
names/aliases, source/provenance, mode definitions, hardware capacities, and named
protocol/acquisition/processing adapter references. Use registered adapter IDs.

Each parameter definition must support:

- Stable semantic ID, type, canonical units, default, enum choices or range/step.
- GUI section/order, label, tooltip, display units/scale/precision, and editability.
- Fixed values, configuration-file-only settings, and firmware-owned reported
  values as distinct policies. Hidden does not imply unsupported.
- Protocol binding/semantic role and status binding through the selected adapter.
- Whether it changes acquisition and consequently invalidates configuration.
- Mode applicability and dependency rules. Distinguish requested and effective
  values when firmware changes their meaning, such as Auto-1 repeat.

For voltage-reference choices, one definition supplies the stable option ID,
wire value, GUI label and numerical full-scale span (including fixed or measured
span policies where needed). Do not treat every wire token as a numerical voltage:
`vdd`, `ext`, `0.8vdd`, and historical aliases need explicit supported semantics.
ADC bit depth and count-to-voltage conversion also come from the resolved capture
context; remove the assumption that all future boards use a global 12-bit ADC.

Use semantic names such as `spi_clock_hz`, `settling_conversions`,
`samples_per_channel`, `sweeps_per_block`, and `vmid_sampling`. Two controls with
similar labels but different payload effects must not share an ambiguous `repeat`
setting. A typed settings container can hold a validated parameter mapping with
stable common accessors; adding a board parameter must not require new fields in
every state, request, status, and snapshot dataclass.

Prefer self-contained resolved board profiles in the first implementation. Repeated
values across independent boards are legitimate board definitions. Any optional
shared templates must have deterministic documented merge/override rules and
produce one resolved definition; avoid deep inheritance and parallel defaults in
Python. Schema defaults are not a second source for board values.

Illustrative parameter fragment; the implementer must define the complete schema
and populate every profile, not stop at this example:

```json
{
  "reference": {
    "type": "enum",
    "section": "adc",
    "label": "Voltage Reference",
    "default": "span_2_5",
    "choices": [
      {"id": "span_2_5", "wire_value": "2.5", "label": "2.5 V", "full_scale_volts": 2.5},
      {"id": "span_5", "wire_value": "5", "label": "5 V", "full_scale_volts": 5.0}
    ]
  },
  "spi_clock_hz": {
    "type": "integer",
    "section": "adc",
    "label": "SPI CLK",
    "default": 20000000,
    "minimum": 100000,
    "maximum": 30000000,
    "display": {"unit": "MHz", "scale": 0.000001, "decimals": 3}
  },
  "settling_conversions": {
    "type": "integer",
    "section": "acquisition",
    "label": "Repeat Count",
    "default": 1,
    "minimum": 1,
    "maximum": 3
  }
}
```

**Steps**

1. **Audit and characterize the existing supported board matrix.**

   Inventory identities, aliases/family fallbacks, modes, UI controls, defaults,
   firmware-accepted values, fixed/locked settings, voltage scaling, wire commands,
   ACK/status behavior, payload shapes and timing models. Populate the coverage
   document with source paths and distinguish intended GUI defaults from firmware
   power-on defaults. Preserve the implemented TestBoard behavior as the baseline.
   Capture meaningful regression fixtures before changing shared paths. Resolve
   the inventory discrepancies above explicitly. *Foundation for all steps.*

2. **Build the schema, typed models, and BoardRegistry.**

   Validate all bundled profiles on load: versions, unique IDs/aliases, valid
   mode/default selection, parameter types, supported default values, sane bounds,
   display conversions, reserved-resource roles, rule references, adapter IDs,
   and compatible sensor-configuration references. Report invalid files with the
   file/field path; do not quietly substitute unrelated board capabilities.

   `registry.json` records discovery/fallback precedence centrally: exact names
   and aliases first, explicitly declared compatibility family matches second,
   generic fallback last. Match deterministically after trimming/case normalization
   and reject ambiguity. Preserve unknown-board behavior through the explicit
   fallback profile. Never let broad Teensy/Array matches override TestBoard or a
   known specific board.

   Load once per registry lifecycle and resolve on connection/mode/variant change.
   During capture, freeze the resolved context. Initially preserve
   `resolve_mcu_profile()` as a compatibility facade over the registry; it must
   not remain a competing hardcoded implementation. *Depends on step 1.*

3. **Create complete JSON definitions for the inventory.**

   Build all listed board profiles and the registry file in this implementation.
   Include mode-specific parameters and feature availability for channel/manual
   selection, sensor selection, multiple arrays, reference, gain, OSR/averaging,
   speed/rate, ground/Vmid, retained repeat, settling repeat, block sizes, 555
   tuning, PZT_RS and specialized visualizations as applicable.

   Include transport/bootstrap requirements and actual ACK/run/status policies.
   Account for connection before identity is known: preserve working discovery
   and use a central bootstrap/port policy for any confirmed baud differences.
   Profile selection after detection alone cannot fix an initial baud mismatch.
   Keep USB baud behavior and the documented Teensy555 115200 exception explicit;
   validate before changing current discovery or transmitted terminators.

   Express fixed versus user-editable settings accurately. Where firmware accepts
   a compatibility-only command, do not advertise a hardware effect it does not
   have. *Depends on steps 1-2.*

4. **Migrate sensor routing to its JSON owner.**

   Keep `channel_sensor_map`, `array_layout`, `mux_mapping`, per-array associations,
   and polarity in the sensor library. Preserve existing user overrides and old
   sensor entries; normalize old `board_profile` references through stable board
   IDs/aliases, and introduce a versioned compatibility-reference field if needed.

   Remove the authoritative Python copies of TestBoard PZT names, electrical
   mapping, placement order, and array/ADC associations. Derive selectable sensor
   IDs and route groups from the selected compatible JSON entry. Validate against
   profile capacities, reserved inputs and adapter requirements, without comparing
   the JSON to a second PZT wiring table in Python.

   Allow valid sensor-to-input mapping changes through JSON alone and reflect them
   in command routes, payload indices, labels and metadata. Update Sensor editor
   validation/editability accordingly; any restriction must be profile-declared
   or an actual firmware constraint, not a hardcoded TestBoard-name rule. Preserve
   the current bundled TestBoard wiring and Array_PCB1.7 grid as defaults. Firmware
   still verifies whether requested physical routes/array selection are accepted.

   Preserve `array_count` for old files but validate/derive it from the owned array
   entries; do not invent a second array-to-ADC mapping in the board profile.
   Existing five-placement PZT algorithms may declare their input requirements;
   do not require every future board or raw-signal display to use five channels,
   two arrays, or four ADC lanes. *Depends on steps 2-3.*

5. **Unify settings, normalization, and parameter dependencies.**

   Use the same definitions for defaults, saved-value validation, GUI edits,
   Configure requests and effective-setting interpretation. Do not seed hardcoded
   TestBoard/MG24/Teensy values in dataclasses and later overwrite them in widgets.

   Define a small declarative rule vocabulary for common predicates, forced/fixed
   values, effective values, enabled/visible state, and retained requested values.
   Apply it to GUI state and request validation through one evaluator. Avoid JSON
   expressions evaluated as Python; unusual algorithms use named adapters.

   Maintain separate board/mode settings, reported firmware status, view state,
   and captured state. Namespace persisted acquisition preferences by stable board
   ID and mode; preserve intentional reconnect defaults unless the existing UX or
   documented policy restores saved values. Migrate old `testboard_*`, reference
   tokens, `repeat`, and snapshot fields explicitly. Saved view state cannot
   override profile-owned/configuration-file-only device settings. *Depends on 2-4.*

6. **Make GUI controls consume the profile and shared parameter bindings.**

   `gui/board_controls.py` creates/binds enum, integer, number and boolean controls
   using their definitions. Existing specialized sensor/channel selectors and
   visualization panels remain reusable components selected by capabilities.
   Generic widgets hold stable option IDs in item data; never recover protocol
   values by parsing label text or replacing unit characters.

   Derive section visibility from supported parameters, and mode selection from
   available modes. Apply labels, choices, ranges, units, tooltips, fixed values,
   dependencies and capture lock policies centrally. Profile-defined behavior
   must update immediately when the board/mode changes and restore the next
   board's settings without leftover labels or ranges. Keep the scrollable left
   control panel and thin `adc_gui.py` composition.

   View-only Display Array remains available during acquisition and derives choices
   from the source descriptor. It sends no commands and does not invalidate device
   configuration. Analysis keeps its independent source-aware selector. Remove
   duplicated value/visibility rules from `testboard_panel.py` and MCU detector
   branches after the replacement path is verified. *Depends on steps 2-5.*

7. **Adapt protocol and processing through registered behavior IDs.**

   Extract/wrap existing configuration and parsing behavior behind small protocol
   adapters. Adapters build ordered command plans, encode values, normalize actual
   status, verify required fields, and decode the selected format. Preserve
   failures, Start gating, framing, units, held RS channels, time alignment and
   mode-specific run ACK differences. Reuse `ADCSessionController` transport and
   reader infrastructure instead of adding a parallel serial stack.

   Board values come from resolved definitions; algorithm details stay in code.
   Shared codec constants belong to their protocol family. Do not require JSON to
   describe arbitrary executable frame parsers or mathematical algorithms.

   Acquisition adapters build complete routes/specs from settings plus sensor
   JSON, including absolute payload indices and array-qualified identities.
   Stateful filtering, baselines, integration, heatmap, force, ghost removal,
   Spectrum and calibration retain all acquired arrays independently. Display
   projection does not alter processing membership. Timing-model selection and
   board-specific coefficients/provenance come from the resolved profile; shared
   mathematical formulas remain in processing modules. Mark unavailable physical
   timing as unavailable and never infer MG24 timing for ADS7953.

   Replace downstream MCU-name tests with profile/context capabilities and adapter
   calls. Central compatibility wrappers may remain temporarily, but cannot contain
   duplicated board parameter definitions. *Depends on steps 2-6.*

8. **Freeze interpretation metadata and preserve file compatibility.**

   New captures record stable profile ID, schema/profile versions, reported MCU,
   resolved mode/variant, profile fingerprint, the interpretation-relevant resolved
   profile data, requested/verified/effective settings, ADC scaling and units,
   adapter/format IDs, and sensor/routes/layout snapshot. A fingerprint identifies
   a definition but is not a substitute for a self-contained capture snapshot.

   Preserve current archive/CSV fields and TestBoard descriptor readers through
   explicit versioned migrations. Old captures without registry metadata use
   existing compatibility readers. Saved mapping is validated against its captured
   contract, not the currently installed board profile or edited sensor library.
   Offline loading must not require the original board to be connected.

   Both-array export remains complete regardless of Display Array. No automatic
   rewriting of existing captures or user libraries is part of this refactor.
   *Depends on steps 4-7.*

9. **Remove duplication, document maintenance, and prove extensibility.**

   Remove active board-specific default/choice/range tables and wiring literals
   from GUI handlers, snapshots, configuration state, conversion helpers and
   constants where the profiles now own them. Preserve general application limits,
   transport safeguards and algorithm constants under their existing owners.

   Update config, GUI, serial and sensor-library documentation. Explain the schema,
   sources of truth, aliases/fallbacks, profile-only settings, compatibility
   migrations and steps to add a board. Include an inventory report proving every
   supported MCU/mode resolves to a populated profile. Add a synthetic future
   board through test JSON only and show it can select an existing adapter, expose
   a different reference/range/parameter, configure, scale and export without
   editing production board-name branches. *Depends on steps 1-8.*

**TestBoard_7953 behavior that the refactor must preserve**

| Area | Required resolved behavior |
| --- | --- |
| Identity | Canonical `TestBoard_7953`; historical `PCB_TestBoard_7953` alias; preserve reported name |
| Mode | PZT only; no PZR hardware capability despite firmware command compatibility |
| Reference | 2.5/5 V input spans; default 2.5 V; ADS7953 12-bit scaling |
| SPI clock | Canonical integer Hz; display MHz; 0.1-30 MHz; default 20 MHz; requested clock metadata; >20 MHz experimental tooltip |
| ADC controls | No supported OSR/gain parameters |
| Selection | Arrays 1, 2 or both, default both; same selected PZT list on both; selections/mappings derived from sensor JSON |
| Vmid | Boolean optional discarded sampling, default false; channel 15 owned once by the profile's reserved-resource role; mandatory firmware parking remains active |
| Sequence | Manual/auto1, default manual; Vmid true forces manual; turning Vmid off leaves manual selected |
| Settling repeat | Requested 1-3, default 1; auto1 effective 1; preserve requested manual value |
| Payload repeat/block | One retained sample per route and one sweep per frame; settling repeat and Vmid do not add emitted samples |
| Scan order | `adc` default; `adc`, `array`, `interleaved` supported; configuration-file-only, now owned by board JSON, not a GUI control or competing Python constant |
| Routing | Current default layout/maps unchanged; five populated PZTs give 25 samples for one array or 50 for both; valid JSON edits change routing consistently |
| Verification | Bare ACKs followed by actual complete matching key=value status; Configure aborts on failure/mismatch |
| Display | Shared array selector; new both-array captures default to 1; single-array lock; runtime changes preserve data/history and send no commands |
| Capture/reload | All acquired arrays exported; captured descriptor controls stopped/full/offline interpretation; independent Analysis selector |
| Physical timing | ADS7953 physical connection timing remains unavailable; decay voltage preview available, physical characterization gated; no MG24 timing substitution |

This plan intentionally replaces the earlier TestBoard plan's Python-owned wiring
and scan-order constant with the JSON ownership requested in this conversation.
Provide a short migration note for users who edited
`TESTBOARD_DEFAULT_SCAN_ORDER` in `testboard_7953_board.py`.

**Relevant files**

| File or folder | Refactoring role |
| --- | --- |
| `config/boards/` (new) | Schema, registry, all populated profiles, typed models, validation/rules and maintenance docs |
| `config/mcu_profile.py`, `mcu_view_state.py`, `mcu_detector.py`, `mcu_state.py` | Registry facade/context, deterministic identity, capability-driven view state and defaults |
| `config/adc_config_state.py`, `config_snapshot.py`, `config_handlers.py` | Shared parameter settings, migration, option IDs, conversion and request consumers |
| `config/adc_configuration_service.py`, `adc_configuration_runner.py`, `buffer_utils.py` | Adapter dispatch, profile-owned constraints, preserved configure/failure behavior |
| `config/testboard_7953_board.py`, `testboard_scan.py`, `testboard_acquisition.py`, `testboard_runtime.py` | Remove duplicate wiring/defaults; generic routing/captured context and compatibility wrappers |
| `config/sensor_config.py`, `sensors_library/sensor_configurations.json`, `constants/sensor_config.py` | Sole sensor mapping owner, compatible board references, structural validation and legacy schema migration |
| `gui/board_controls.py` (new), `gui/control_panels.py`, `gui/testboard_panel.py`, `gui/sensor_panel.py` | Parameter-driven controls, centralized dependencies and mapping editability |
| `serial_communication/protocols/` (new), `adc_session.py`, `serial_threads.py`, `serial_parser.py`, `testboard_status.py`, `adc_connection_state.py` | Adapter IDs, bootstrap/transport policies, actual status/ACK/frame handling and reported state |
| `data_processing/adc_mux_timing.py`, `adc_plotting.py`, `analysis_workbench.py`, filtering/spectrum/heatmap/force/ghost/integration modules | Captured scaling, capability requirements, adapter-based sample/timing interpretation and array state |
| `data_processing/capture_lifecycle.py`, `capture_cache.py`, `file_operations/archive_loader.py`, `data_exporter.py`, `settings_persistence.py` | Frozen descriptors, profile/settings persistence, compatible full-view/export/reload |
| `constants/serial.py`, `defaults_555.py`, `plotting.py` | Distinguish board-owned values from transport/general/algorithm constants; remove competing definitions |
| `adc_gui.py` | Context initialization and mixin orchestration only |
| `Arduino_Sketches/README.md` and referenced firmware | Read-only evidence of accepted parameters, modes, command behavior and revision ambiguity |
| `tests/`, root/config/GUI/serial READMEs, `docs/guides/configuration/ARRAY_CONFIGURATION_GUIDE.md` | Inventory, regressions, maintenance instructions and migration documentation |

**Verification**

1. **Inventory completeness:** Every active sketch-map MCU name, currently tested
   historical identity, supported mode and existing generic fallback resolves to
   a populated profile. Equivalent modular/monolithic firmware shares a profile
   only where behavior is verified equivalent. No unresolved alias collisions.
2. **Schema/registry tests:** Invalid versions/defaults/ranges/types/rules/adapter
   IDs and ambiguous aliases fail clearly. Exact matching wins over explicit
   family compatibility fallbacks. Whitespace/case and unknown/no-MCU behavior
   remain deliberate. Verify bundled files can be found outside the repo cwd.
3. **Single-definition tests:** Change a test profile's reference options, default
   SPI clock or limit. GUI choices/defaults, request validation, wire encoding,
   numerical conversion and export must all follow it. Demonstrate there is no
   hidden second list/default in Python. Test display-unit conversion round trips.
4. **Settings/rules tests:** Vmid/sequence and requested/effective repeat rules,
   fixed parameters, per-mode/default restoration, per-board persistence, legacy
   field migration and acquisition versus view-only invalidation. Unsupported
   parameters cannot produce commands accidentally.
5. **Board compatibility tests:** Characterize each inventory row across its
   supported modes. Verify controls, defaults, allowed values, channel ranges,
   fixed ground behavior (currently 10 for Array_PZT_PZR1 and 15 for 1.7), 555/RS
   tuning and actual command/status transcripts. Distinguish firmware-reported
   values from host-synthesized legacy compatibility where unavoidable.
6. **Mapping tests:** Valid sensor JSON mapping edits change command routes,
   specs/labels and exported metadata without Python changes. Reject out-of-range
   or reserved inputs and incompatible processing groups. Include sparse,
   nonascending, repeated input numbers across arrays and all supported scan
   orders, using distinct sentinel values for every physical route.
7. **Processing/capture tests:** Retained repeat versus settling repeat frame
   widths, profile bit depths/spans, combined PZT_RS units/held values, state
   isolation, stale asynchronous result guards and runtime array switching.
   Snapshot interpretation remains stable after board/mode/profile/library changes.
8. **File compatibility tests:** Current and older archive/CSV metadata, generic
   and TestBoard captures, >RAM full view, all-array exports, disconnected/offline
   Analysis, profile fingerprint/version changes and missing historical mapping.
   Interpret old data using saved or explicit legacy contracts, not live widgets.
9. **Future-board test:** A temporary profile with a new MCU name, different
   reference span/ADC bit depth, parameter choices/ranges and a compatible sensor
   layout uses existing adapters. Prove no new GUI/service/processing MCU-name
   branch is required. New executable behavior is tested through a new adapter.
10. **Regression execution:** Start with affected existing suites and new
    registry/profile/parameter tests, selected through the targeted-test selector.
    Include MCU profile/detector/view, configuration snapshots/service, sensor
    configuration/panel, serial routing/reader/parser, TestBoard capabilities,
    mixed array modes, plotting/filtering/sample rates, Spectrum/Heatmap/Pressure
    Map/force/calibration/decay, settings persistence, archive/export and Analysis.
    Once targeted checks pass, run the full suite because this refactor touches
    shared board behavior. Use the repo interpreter:

    ```powershell
    .\.venv\Scripts\python.exe -m pytest tests -q
    ```

11. **Manual/hardware acceptance:** For available boards verify MCU/variant
    resolution, complete configuration/status, mode switches, actual frames and
    stop/reconfigure behavior. Exercise TestBoard both spans, settling repeat,
    Vmid/manual/auto1, individual/both arrays, every visualization switch and
    export/reload. Check the documented transport exceptions on actual hardware.
    Record exactly which boards/revisions were exercised; do not claim hardware
    validation from synthetic tests. Firmware modifications are outside this plan.

**Decisions**

- One versioned JSON profile per distinct supported board behavior; aliases share
  a profile only when equivalent. All existing supported paths must be populated
  and migrated, including TestBoard_7953 and historical/generic compatibility.
- Profiles own MCU parameters; sensor JSON owns sensor/electrical/spatial mapping.
  Command/frame and processing algorithms remain in registered Python adapters.
- Modes are part of the board definition. Fixed/hidden/configuration-file-only
  parameters are distinct from unsupported parameters.
- Identity matching and compatibility family fallbacks are centralized, explicit,
  deterministic and subordinate to exact matches.
- All consumers use resolved typed definitions. Board values are not independently
  restated in GUI widgets, validation code, snapshots or conversion tables.
- Semantic parameter IDs and validated mappings replace growth of board-prefixed
  dataclass fields. Requested, effective, view and captured values remain separate.
- Vref options bind GUI labels, wire values and numerical scaling once. Bit depth,
  measurement units and timing-model availability travel with captured data.
- TestBoard sensor wiring and scan order move out of authoritative Python literals.
  Preserve its accepted defaults and runtime two-array behavior.
- Keep the current mixin architecture and transport; migrate incrementally through
  compatibility facades, then remove competing active definitions.
- No firmware/protocol changes, new board-manager GUI, arbitrary executable JSON,
  or rewriting historical captures are included.

**Further Considerations**

1. A later firmware capability/version handshake can resolve MCU names shared by
   revisions. This refactor must document today's ambiguity and provide an explicit
   compatible variant path where necessary without requiring firmware changes.
2. Start with bundled board definitions. Reuse existing per-board preference
   persistence; do not add overlapping local profile override layers unless a
   concrete requirement appears. A future profile editor can reuse the schema.
3. Future ADC topologies, non-five-channel sensors and new sample formats should
   reuse parameter/routing abstractions where compatible. They may still require
   new adapters or visualization algorithms; JSON cannot supply absent algorithms.
