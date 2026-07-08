# Time Series Tab Specification

Owner: Host application GUI/live plotting stack  
Status: Implemented  
Date: 2026-07-08

## Purpose

The Time Series tab is the default live view for streamed ADC data and aligned force-sensor traces. It provides fast inspection of recent or full capture data, per-channel visibility controls, baseline handling, and simple display-mode changes without mutating the stored raw capture.

## UI Behavior

- Plot group titled `Real-time Data Visualization`.
- Dual-axis plot:
  - Left axis for ADC values or converted voltage.
  - Right axis for force in Newtons.
- Live info labels show sweep/sample/force counts and timing-related readouts.
- Sampling Rate section shows per-channel rate and sample interval timing.
- Visualization Controls section includes:
  - Dynamic channel checklist with All/None buttons.
  - Y-range mode: Adaptive or Full-Scale.
  - Y-units mode: Values or Voltage.
  - Window-size control for scrolling live view.
  - Reset View and Full View actions.
  - Display mode toggles for All Repeats or Average.
  - Subtract Baseline and Zero Signals controls.

## Runtime Behavior

- Live redraws are driven from buffered capture data and debounced timers.
- Force traces are overlaid on the shared X domain of the ADC traces.
- Wheel zoom is blocked during active capture to avoid heavy redraw stalls.
- Full View is disabled until capture data exists and can include archive-backed reload when the capture exceeds in-memory view limits.
- Baseline subtraction uses a user-captured baseline rather than altering the raw stored data.

## Persistence

- This tab uses current app/runtime state rather than a dedicated standalone settings file.
- Shared acquisition and configuration settings outside the tab remain controlled by the main app.

## Acceptance Criteria

- Visible channels redraw immediately when toggled.
- Users can switch between raw ADC counts and voltage display using the active Vref.
- Force traces stay aligned with the ADC X axis.
- Reset View restores the windowed live view and Full View exposes the whole capture after recording.
- Baseline tools affect only display behavior, not the underlying captured samples.

## Out Of Scope

- Frequency-domain analysis.
- Offline CSV+JSON inspection.
