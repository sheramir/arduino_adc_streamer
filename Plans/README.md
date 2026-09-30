# Plans

Prompt-style implementation plans and planning notes. These files capture proposed steps, affected files, verification ideas, decisions, and open questions. Formal behavior specs live in `../Specs/`.

## Files

- `plan-analysisTabOfflineSignalWorkbench.prompt.md` — implementation plan for the offline Analysis workbench, including source adapters, read-only lifecycle, Spectrum filter reuse, integration/shear/normal overlays, synchronized plots, marker behavior, settings persistence, and compatibility decisions.
- `plan-forceCalibration.prompt.md` — implementation plan for the Force Calibration tab: sensor family/number selection, measured calibration windows, calibration table persistence, and deferred follow-up scope.
- `plan-inAnalysisTab-Calculated_PZT_Force.md` — plan/spec notes for calculated PZT force in Analysis: settings, reusable calculation ownership, quiet-window Vmid/noise estimation, noise thresholding, leakage model, automatic zeroing, plot behavior, and export expectations.
- `plan-pressureMap-adjacentPackageInterpolation.md` — implementation plan for adjacent-package interpolation in the Pressure Map workflow.
- `plan-testboard7953-parallel-spi-scan.md` — implementation plan for a DMA-parallel `scanorder parallel` mode on the TestBoard_7953 (ADS7953) firmware, overlapping SPI1/SPI2 reads via async transfer for timing comparison against the existing scan modes.
