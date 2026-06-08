---
name: protocol-change-guard
description: Protect coupled firmware/host protocol work in the arduino_adc_streamer repo. Use when changing serial commands, acknowledgments, MCU detection strings, binary frame layout, payload ordering, array/combined modes such as PZT_RS, parser assumptions, or any task that touches both Arduino sketches and Python serial/config/processing code.
---

# Protocol Change Guard

Keep protocol work narrow, explicit, and cross-checked across firmware, host parsing, docs, and tests.

## Start Here

Read these first:

- `Arduino_Sketches/README.md`
- `README.md`
- [references/protocol-surfaces.md](references/protocol-surfaces.md)

If the change involves arrays or sensor routing, also read:

- `docs/user/ARRAY_CONFIGURATION_GUIDE.md`

## Workflow

1. Identify the protocol surface that changed.
   Protocol changes include:
   - command names or arguments such as `channels`, `repeat`, `buffer`, `mode`, `rschannels`
   - `#OK` / `#NOT_OK` behavior
   - `mcu*` response strings
   - binary frame headers, sample counts, trailer timing fields, or payload ordering
   - mode-specific payload semantics such as `PZT_RS`

2. Search for the exact literals before editing.
   Search for the changed command names, ACK tokens, MCU strings, and mode names across both `Arduino_Sketches/` and the Python app. Do not patch only the first match.

3. Map every affected layer.
   At minimum check:
   - firmware sketches and shared C++ helpers
   - `serial_communication/`
   - `config/`
   - `data_processing/`
   - user docs and architecture notes
   - tests under `tests/`

4. Implement the smallest compatible slice.
   Prefer additive compatibility when practical. If a breaking change is unavoidable, update firmware docs, host parsing, UI assumptions, and tests in the same round.

5. Verify the active protocol, not historical behavior.
   The repo contains legacy sketches and history docs. Use the current sketch map in `Arduino_Sketches/README.md` as the source of truth for active host integration unless the task explicitly targets legacy firmware.

6. Leave a hardware validation note when behavior on-device matters.
   If the change can only be fully proven with real boards, document the exact manual validation steps and any unverified assumptions.

## Guardrails

- Do not change host parsing without checking the sketch map and frame description.
- Do not update a Teensy+MG24 pair on only one side unless the task explicitly requires temporary incompatibility.
- Do not mix unrelated serial refactors into a protocol change.
- Do not rely on `adc_gui.py` alone for protocol behavior; follow the path through workflow, session, parser, and downstream processors.
- Do not forget export or reload paths when payload shape changes.

## Verification

Pick the smallest relevant tests, then widen only if the touched surface is broad.

Common protocol-side tests:

- `tests/test_adc_connection_workflow.py`
- `tests/test_adc_connection_state.py`
- `tests/test_adc_configuration_service.py`
- `tests/test_adc_serial_routing.py`
- `tests/test_serial_threads.py`
- `tests/test_binary_status.py`
- `tests/test_array_dual_mode_pzt.py`
- `tests/test_force_connection_workflow.py`
- `tests/test_force_reader_thread_parser.py`

If export shape or timing alignment changed, also run:

- `tests/test_data_exporter.py`
- `tests/test_archive_io.py`
- `tests/test_force_export_alignment.py`

For tighter selection, use `$targeted-test-selector` if available.
