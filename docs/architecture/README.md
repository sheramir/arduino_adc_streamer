# architecture

How the current system is built. Test evidence lives in [`../testing/`](../testing/README.md), reviews in [`../reports/`](../reports/README.md), and open plans in [`../plans/`](../plans/README.md).

## gui/

- `gui/GUI_GENERIC_ACQUISITION_REFACTOR.md` — shared, profile-driven GUI acquisition: board JSON profiles, routing, workers, rendering, and replay validation.
- `gui/HEATMAP_IMPLEMENTATION.md` — heatmap file map, current behavior (live data, PZT/PZR modes, shared package grouping with shear, persisted settings). `Legacy/data_processing/` and `Legacy/gui/` hold separate archived copies of the same modules.

## firmware/

TestBoard_7953 firmware designs and implementation notes:

- `firmware/TESTBOARD_7953_FIRMWARE_OPTIMIZATION.md` — firmware optimization candidate.
- `firmware/TESTBOARD_7953_PHASE_PROFILING.md` — phase profiling instrumentation and procedure.
- `firmware/TESTBOARD_7953_LPSPI_WORD_PATH.md` — LPSPI word-path candidate.
- `firmware/TESTBOARD_7953_LIVE_USB_STREAM.md` — keep sampling and discard sweeps when USB is busy.
