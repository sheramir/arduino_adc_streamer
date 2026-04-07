# Real-Time Performance Optimization Summary

**Date:** April 2026  
**Scope:** `arduino_adc_streamer` — PyQt6 desktop GUI, 40-channel ADC, 10–20k samples/sec over USB serial

---

## Overview

The codebase was optimized for real-time throughput, GUI responsiveness, and memory stability. Changes span the serial ingestion path, in-memory buffer management, IIR filtering, archive I/O, and plot rendering. Six correctness bugs introduced during refactoring were subsequently identified and fixed.

---

## Changes by File

### `data_processing/archive_writer.py` *(new file)*

**Problem:** The ingestion path was writing each sweep synchronously to a JSONL archive file, blocking the serial reader thread on every disk write.

**Fix:** Introduced `ArchiveWriterThread` — a daemon `threading.Thread` with a `queue.Queue`. The ingestion path calls `enqueue()` (non-blocking `put_nowait`), and the writer thread drains the queue in the background. The thread sleeps 2ms between items to yield the GIL and avoid starving the Qt event loop.

Two stop modes are provided:
- `stop_nowait()` — sets the stop flag and returns immediately (used from the GUI thread after capture ends)
- `stop()` — blocks until the queue is empty and the file is closed (used only before file deletion)

---

### `serial_communication/serial_threads.py`

**Problem:** Samples were parsed in a Python `for` loop, one `uint16` at a time. PyQt signal parameters were declared as `int`, silently truncating Arduino `uint32` microsecond timestamps above 2³¹−1 to negative values. Buffer management used per-packet bytearray slicing, allocating a new object on every packet.

**Fixes:**
- Sample parsing replaced with `np.frombuffer(..., dtype='<u2').copy()` — one vectorized call per block instead of N Python iterations. `.copy()` is required to release the memoryview export immediately, allowing the bytearray to be resized.
- Timestamp parsing uses `int.from_bytes(buffer[offset:offset+4], 'little')` — avoids holding a live memoryview export on the bytearray.
- All four signal parameters changed to `pyqtSignal(object, object, object, object)` — prevents PyQt int32 truncation of uint32 hardware values.
- Buffer management changed to an integer `buf_start` offset with a single `del buffer[:buf_start]` at the end of each loop iteration, eliminating per-packet allocations.

---

### `data_processing/binary_processor.py`

**Problem:** Incoming samples were written to the circular numpy buffer one sweep at a time in a Python loop. Plot updates used a count-based modulo check (`sweep_count % N == 0`) that broke when counts jumped by an arbitrary block size per call. Archive writes happened synchronously on the ingestion thread.

**Fixes:**
- Vectorized buffer write: `positions = (buffer_write_index + np.arange(sweeps_in_block)) % MAX_SWEEPS_BUFFER` followed by a single `buffer[positions] = values` assignment, covering the entire block in one numpy operation.
- Plot rate-limiting replaced with a wall-clock gate: `time.time() - _last_plot_update_time >= PLOT_UPDATE_INTERVAL_SEC`. Fires at a stable, guaranteed rate regardless of block size.
- Archive write replaced with `self._archive_writer.enqueue(...)` — non-blocking, decoupled from ingestion.
- `uint32` overflow guard added: `int(block_start_us) & 0xFFFFFFFF` before any arithmetic with `np.uint64` arrays.

---

### `data_processing/filter_processor.py`

**Problem:** scipy's `sosfilt` defaults to float64 output even when given float32 input. The filter state (`zi`) was also float64, causing silent upcasting on every call and doubling memory bandwidth for filter arrays.

**Fix:** Input cast changed to `astype(np.float32, copy=False)`. Filter state initialized as `sosfilt_zi(sos).astype(np.float32)`. Output stays float32 throughout — no extra conversion needed.

---

### `data_processing/data_processor.py`

**Problem:** Several issues accumulated here:
- `update_plot` full-view branch used `if not self.raw_data` — raises `ValueError: truth value of array is ambiguous` when `raw_data` is a numpy ndarray (set by `full_graph_view`).
- `start_capture` and `clear_data` called `self.raw_data.clear()` — crashes with `AttributeError` when `raw_data` is a numpy array.
- `on_capture_finished` blocked the GUI thread with `time.sleep(0.1)` + `drain_serial_input(0.3)` (400ms extra) after a 500ms drain had already run in `stop_capture`.
- `MAX_TOTAL_POINTS_TO_DISPLAY = 12000` was hardcoded inline inside `update_plot`.

**Fixes:**
- Full-view empty check replaced with `len()`-based guards safe for both lists and ndarrays.
- `np.array(self.raw_data)` replaced with `np.asarray(...)` — zero-copy when data is already the correct dtype/shape.
- `self.raw_data.clear()` / `self.sweep_timestamps.clear()` replaced with `self.raw_data = []` / `self.sweep_timestamps = []` in all reset paths (`start_capture`, `clear_data`).
- `time.sleep(0.1)` removed from `on_capture_finished`; final drain reduced from 0.3s to 0.05s.
- `MAX_TOTAL_POINTS_TO_DISPLAY` extracted to `config_constants.py`.

---

### `file_operations/archive_loader.py`

**Problem:** `full_graph_view` called `load_archive_data()`, which reads from the archive file on disk. With a background `ArchiveWriterThread`, the file is still being written when the user clicks Full View — resulting in incomplete or empty data. It also called `QApplication.processEvents()` on the GUI thread.

**Fix:** `full_graph_view` now reads directly from the in-memory circular numpy buffer:
1. Acquires `buffer_lock` and snapshots `sweep_count` and `buffer_write_index`.
2. Re-orders the circular buffer (handles both the not-yet-wrapped and wrapped cases via `np.concatenate`).
3. Assigns the ordered numpy arrays to `self.raw_data` and `self.sweep_timestamps`.
4. Calls `update_plot()` — the full-view branch then uses `np.asarray(self.raw_data)` (zero-copy).

Data is always complete and consistent regardless of the archive writer's state.

---

### `config/config_handlers.py`

**Problem:** `reset_graph_view` called `self.raw_data.clear()` — same numpy array crash as above.

**Fix:** Changed to `self.raw_data = []` / `self.sweep_timestamps = []`.

---

### `adc_gui.py`

- `_init_archive_state` adds `self._archive_writer = None` for clean lifecycle tracking.
- `_init_force_state` changes `force_data` from `List[tuple]` to `collections.deque(maxlen=MAX_FORCE_SAMPLES)` — O(1) bounded append, no manual slicing.

---

### `data_processing/force_processor.py`

Removed `force_data = force_data[-MAX_FORCE_SAMPLES:]` slice — no longer needed since `force_data` is now a bounded deque.

---

### `config_constants.py`

Two previously hardcoded values extracted:

| Constant | Value | Description |
|---|---|---|
| `PLOT_UPDATE_INTERVAL_SEC` | `0.2` | Wall-clock interval between live plot redraws (5 FPS cap) |
| `MAX_TOTAL_POINTS_TO_DISPLAY` | `12000` | Maximum data points rendered across all channels per update |

---

## Bug Taxonomy

All bugs were introduced by the initial vectorization pass and fixed in subsequent rounds:

| # | Symptom | Root Cause | Fix |
|---|---|---|---|
| 1 | Display froze, never updated | Debounce timer reset on every block → never fired | Replaced with wall-clock gate |
| 2 | All tabs froze | GIL held by archive thread tight loop; broken modulo rate check | Added 2ms sleep in archive thread; wall-clock rate limiting |
| 3 | No signal; uint64 overflow crash | `np.frombuffer` held live export on bytearray → resize crashed serial thread; PyQt `int` truncated uint32 to int32 | `.copy()` after frombuffer; `object` signal types; `int.from_bytes` for timestamps |
| 4 | Stop button slow | `writer.stop()` (blocking join) called on GUI thread | Added `stop_nowait()` for GUI use |
| 5 | Stop still slow | `time.sleep(0.1)` + 300ms `drain_serial_input` in `on_capture_finished` | Removed sleep; reduced drain to 50ms |
| 6 | Full View empty after Stop | `full_graph_view` read from partially-written archive file | Changed to read from in-memory circular buffer |
| 7 | Clear / Start after Stop crash | `.clear()` called on numpy array (set by `full_graph_view`) | All reset paths use `= []` re-assignment |

---

## Performance Impact Summary

| Area | Before | After |
|---|---|---|
| Sample parsing | Python loop, 1 `uint16` at a time | `np.frombuffer` — single vectorized call |
| Buffer write | Python loop, 1 sweep at a time | Vectorized index write, entire block at once |
| Filter dtype | float64 (silent upcast) | float32 throughout |
| Archive I/O | Synchronous, on ingestion thread | Background daemon thread, non-blocking enqueue |
| Force data bound | `list[-N:]` slice on every append | `deque(maxlen=N)` — O(1), zero allocation |
| Plot rate limiting | Count-based modulo (broken under variable block sizes) | Wall-clock gate, stable FPS |
| Full View load | File read (incomplete during background write) | Direct in-memory circular buffer read |
| GUI thread blocking on Stop | ~400ms extra sleep + drain | ~50ms drain only |
