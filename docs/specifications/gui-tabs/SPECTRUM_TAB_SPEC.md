# Spectrum Tab Specification

Owner: Host application GUI/spectrum-processing stack  
Status: Implemented  
Date: 2026-07-08

## Purpose

The Spectrum tab provides real-time frequency-domain inspection of live ADC data, including FFT and Welch PSD modes, channel visibility, filter settings reuse, marker interaction, and export of spectrum artifacts.

## UI Behavior

- Spectrum Controls group includes:
  - Window preset and explicit window length.
  - NFFT selection.
  - Window function.
  - Mode selector: Welch PSD or Single FFT.
  - Welch segment length and overlap.
  - Averaging mode and corresponding parameters.
  - Frequency-range controls.
  - Band readout controls.
  - X/Y scale controls.
  - Update-rate control.
  - Remove-DC and snap-to-peak toggles.
- The tab reuses the shared filter configuration widgets/settings for display-only spectral processing.
- The plot supports marker-style interaction and export flows defined by the tab.

## Runtime Behavior

- Periodic spectrum updates start when the Spectrum tab becomes active and stop when the user switches away.
- The spectrum view operates on live buffered data and current filter settings without mutating stored raw capture.
- Save/load of settings can temporarily disable live filter enablement during restore so startup state remains controlled.

## Persistence

- Last-used Spectrum settings autosave under the user `.adc_streamer` settings path.
- Save/load actions support explicit Spectrum settings files.
- Persisted state includes spectrum controls and reusable filter settings payloads.

## Acceptance Criteria

- Users can switch between FFT and Welch PSD views.
- Frequency range, scaling, averaging, and update-rate changes apply through the GUI.
- Spectrum updates pause when the tab is not active.
- Saved settings restore the prior spectrum configuration.

## Out Of Scope

- Offline CSV+JSON analysis.
- Pressure-map or heatmap rendering.
