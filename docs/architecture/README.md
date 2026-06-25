# architecture

Implementation notes for active (non-legacy) subsystems: how a feature is currently organized across the codebase, which files own which responsibilities, and brief historical context where relevant.

## Files

- `HEATMAP_IMPLEMENTATION.md` — describes how the heatmap feature is organized: the file map (GUI panel, processor mixins, signal processing, config helpers), current behavior (live data, PZT/PZR modes, shared package grouping with shear, persisted last-used settings), and a short note on the removed simulated-data path from early development. The referenced files (`data_processing/heatmap_*processor.py`, `gui/heatmap_panel.py`) are accurate as the active, promoted implementation; `Legacy/data_processing/` and `Legacy/gui/` hold separate archived copies of the same modules kept for reference/rollback.
