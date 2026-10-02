# Plans

Prompt-style implementation plans and planning notes. These files capture proposed steps, affected files, verification ideas, decisions, and open questions. Formal behavior specs live in `../Specs/`.

## Files

- `plan-analysisTabOfflineSignalWorkbench.prompt.md` — implementation plan for the offline Analysis workbench, including source adapters, read-only lifecycle, Spectrum filter reuse, integration/shear/normal overlays, synchronized plots, marker behavior, settings persistence, and compatibility decisions.
- `plan-forceCalibration.prompt.md` — implementation plan for the Force Calibration tab: sensor family/number selection, measured calibration windows, calibration table persistence, and deferred follow-up scope.
- `plan-inAnalysisTab-Calculated_PZT_Force.md` — plan/spec notes for calculated PZT force in Analysis: settings, reusable calculation ownership, quiet-window Vmid/noise estimation, noise thresholding, leakage model, automatic zeroing, plot behavior, and export expectations.
- `plan-pressureMap-adjacentPackageInterpolation.md` — implementation plan for adjacent-package interpolation in the Pressure Map workflow.
- `plan-testboard7953-parallel-spi-scan.md` — implementation plan for a DMA-parallel `scanorder parallel` mode on the TestBoard_7953 (ADS7953) firmware, overlapping SPI1/SPI2 reads via async transfer for timing comparison against the existing scan modes.
- `plan-testboard7953-ghosting-test.prompt.md` — implementation plan for interactive TestBoard_7953 ghosting measurements, per-attempt baseline calibration, noise/correlation detection, strongest-valid attempt selection, and Excel signal overlays with min/max zoom.
- `plan-testboard7953-gui-capabilities.prompt.md` — planned GUI update for TestBoard_7953 detection, PZT-only ADC/acquisition controls, two-array sensor configuration, runtime display-array switching, and array-aware capture/export/reload.
- `plan-boardRegistry-jsonProfiles-refactor.prompt.md` — implemented board-registry refactor with populated JSON profiles for all supported MCU identities and TestBoard_7953, centralized parameters, sensor-JSON routing, reusable adapters and frozen capture interpretation; hardware acceptance pending.
