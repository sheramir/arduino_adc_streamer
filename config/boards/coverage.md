# MCU/profile coverage

Software audit: 2026-10-02. Active identities come from
`Arduino_Sketches/README.md`; historical entries preserve host/test contracts.
No firmware files changed. Hardware checks remain manual.

Implementation verification: 900 tests and 34 subtests passed. The registry audit
validated all 13 profiles and seven active sketch-map identities. An offscreen GUI
smoke check passed startup and all 18 profile/mode transitions.

| Profile | Exact identities / declared family | Modes | Source or compatibility decision |
| --- | --- | --- | --- |
| `mg24` | MG24 | ADC | MG24/ADC_Streamer_binary_scan |
| `mg24_mux` | MG24_MUX | ADC | Active ADG1206 sketch: MUX channels/ground 0..15; fixes the old generic host 0..9 restriction |
| `teensy40_adc` | TEENSY40 | ADC | Active binary_scan2; OSR 2/4/8; fixed 3.3 V; gain compatibility command does not imply analog gain |
| `teensy_adc_compat` | Teensy4.1; remaining Teensy family | ADC | Historical averaging 0/1/4/8/16/32, separate from TEENSY40 |
| `teensy555` | Teensy555 | 555 | Active Teensy555_streamer; 115200 baud after USB discovery |
| `array_pzt1` | Array_PZT1 | PZT | Archived Teensy_MG24_SPI host contract |
| `array_pzt_pzr1` | Array_PZT_PZR1 | PZT, PZR, PZT_RS | PCB1.0/PCB1.5 share identity; declared variants, preserve historical RS option and firmware rejection behavior |
| `array_pzt_pzr17` | Array_PZT_PZR1.7 | PZT, PZR, PZT_RS | Both active monolithic/modular PCB1.7 pairs |
| `array_dual_compat` | Array_PZT_PZR_v1; unmatched dual prefix | PZT, PZR | Historical compatibility; RS is not inferred |
| `testboard_7953` | TestBoard_7953, PCB_TestBoard_7953 | PZT | PlatformIO ADS7953 project; no PZR hardware |
| `generic_555` | 555 Analyzer; unmatched 555 substring | 555 | Historical analyzer fallback; checked before Teensy substring |
| `generic_array` | Unmatched Array prefix | PZT | Historical array fallback; one effective ADC lane |
| `generic_adc` | Unknown / no identity | ADC | Historical generic ADC fallback and legacy reference interpretation |

Exact aliases win over family rules. Rules explicitly prioritize the dual-array
prefix over Array, and 555 over Teensy. The timing-spec spelling Array_PPZT_PZR1
and its suffixes map to the existing dual-array timing interpretation. Per-mode
features preserve presentation compatibility; editable controls and parameter
limits derive from parameter definitions.

The MG24 timing calculation uses a registered model and the shared JSON data in
`timing_profiles/mg24_dual_mux.json`, retaining calibration provenance and software
overhead estimates. TestBoard never selects that timing model. Shared buffer/frame
safeguards remain protocol constants; board/mode pair-buffer limits are JSON data.

Validate all loaded profiles and active sketch identities with:

```powershell
.\.venv\Scripts\python.exe -m config.boards.audit
.\.venv\Scripts\python.exe -m pytest -q
```
