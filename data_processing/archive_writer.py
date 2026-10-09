"""
Archive Writer Thread
=====================
Background thread for writing sweep data to JSONL archive files
without blocking the ingestion or GUI threads.

Usage::

    writer = ArchiveWriterThread(archive_path, metadata_dict)
    writer.start()

    # From ingestion thread (non-blocking):
    writer.enqueue(sweep_timestamps_sec_1d, block_samples_2d)

    # When capture stops (blocks until queue is drained):
    writer.stop()
"""

import json
import queue
import threading
import time
import csv
from collections import deque


class ArchiveWriterThread(threading.Thread):
    """Background daemon thread that drains a queue and writes JSONL sweep records.

    Each enqueued item is a ``(sweep_timestamps_sec, block_array)`` tuple where:
    - ``sweep_timestamps_sec`` is a 1-D numpy array of per-sweep timestamps (float).
    - ``block_array`` is a 2-D numpy array of shape ``(sweeps, samples)`` whose
      ``dtype`` may be ``uint16`` for unprocessed captures or ``float32`` when a
      host-side processing stage makes cleaned samples canonical.

    JSON serialization uses bounded host batches. There is no fixed per-item
    sleep; the live replay benchmark includes serialization/GIL contention.
    """

    STATE_OPENING = "opening"
    STATE_OPEN = "open"
    STATE_DRAINING = "draining"
    STATE_CLOSED = "closed"
    STATE_FAILED = "failed"

    _GIL_YIELD_SEC = 0.0
    _QUEUE_GET_TIMEOUT_SEC = 0.1
    _DRAIN_IDLE_GRACE_SEC = 0.25

    def __init__(self, archive_path: str, metadata: dict, *, max_pending_bytes=64 * 1024 * 1024):
        super().__init__(name="ArchiveWriter", daemon=True)
        self._archive_path = archive_path
        self._metadata = metadata
        self.queue: queue.Queue = queue.Queue(maxsize=2048)
        self.max_pending_bytes = max_pending_bytes
        self._pending_bytes = self._pending_sweeps = 0
        self._pending_arrivals = deque()
        self.timing_handle = None
        self.final_summary = None
        self._accepting = True
        self._stop_event = threading.Event()
        self._closed_event = threading.Event()
        self._state_lock = threading.Lock()
        self._state = self.STATE_OPENING
        self._last_error = None
        self._enqueued_blocks = 0
        self._written_blocks = 0
        self._written_sweeps = 0
        self._dropped_blocks = 0
        self._last_enqueue_time = time.perf_counter()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _transition_state(self, new_state: str, *, error: str | None = None) -> None:
        with self._state_lock:
            if self._state in {self.STATE_FAILED, self.STATE_CLOSED} and new_state != self._state:
                if error:
                    self._last_error = error
                return
            self._state = new_state
            if error:
                self._last_error = error
            if new_state in {self.STATE_CLOSED, self.STATE_FAILED}:
                self._closed_event.set()

    def _record_failure(self, phase: str, exc: Exception) -> None:
        self._stop_event.set()
        self._transition_state(self.STATE_FAILED, error=f"{phase}: {exc}")

    def get_status_snapshot(self) -> dict:
        with self._state_lock:
            return {
                "state": self._state,
                "last_error": self._last_error,
                "enqueued_blocks": self._enqueued_blocks,
                "written_blocks": self._written_blocks,
                "written_sweeps": self._written_sweeps,
                "dropped_blocks": self._dropped_blocks,
                "is_alive": self.is_alive(),
                "pending_bytes": self._pending_bytes,
                "pending_sweeps": self._pending_sweeps,
                "pending_items": len(self._pending_arrivals),
                "oldest_age_s": max(0.0, time.perf_counter() - self._pending_arrivals[0]) if self._pending_arrivals else 0.0,
            }

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self):
        try:
            with open(self._archive_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(self._metadata) + "\n")
                self._transition_state(self.STATE_OPEN)

                while True:
                    if self._stop_event.is_set():
                        self._transition_state(self.STATE_DRAINING)
                        if self.queue.empty():
                            idle_time = time.perf_counter() - self._last_enqueue_time
                            if idle_time >= self._DRAIN_IDLE_GRACE_SEC:
                                break

                    try:
                        item = self.queue.get(timeout=self._QUEUE_GET_TIMEOUT_SEC)
                    except queue.Empty:
                        continue

                    if item is None:
                        self.queue.task_done()
                        continue

                    sweep_timestamps, block_array, timing_rows, item_bytes = item

                    lines = []
                    for ts, row in zip(sweep_timestamps, block_array):
                        lines.append(
                            json.dumps({"timestamp_s": float(ts), "samples": row.tolist()}, separators=(',', ':'))
                            + "\n"
                        )
                    handle.write("".join(lines))
                    if timing_rows is not None and self.timing_handle is not None:
                        csv.writer(self.timing_handle).writerows(timing_rows)
                    with self._state_lock:
                        self._written_blocks += 1
                        self._written_sweeps += len(lines)
                        written_sweeps = self._written_sweeps
                        self._pending_bytes -= item_bytes
                        self._pending_sweeps -= len(sweep_timestamps)
                        self._pending_arrivals.popleft()

                    if written_sweeps % 1000 < len(lines):
                        handle.flush()

                    self.queue.task_done()

                if self.final_summary is not None:
                    summary = dict(self.final_summary)
                    summary.update(archive_written_sweeps=self._written_sweeps,
                                   archive_overruns=self._dropped_blocks)
                    handle.write(json.dumps({'capture_summary': summary}) + '\n')

                handle.flush()

        except Exception as exc:
            self._record_failure("archive writer", exc)
            return
        finally:
            if self.timing_handle is not None:
                try:
                    self.timing_handle.close()
                except Exception as exc:
                    self._record_failure('timing sidecar close', exc)
            snapshot = self.get_status_snapshot()
            if snapshot["state"] != self.STATE_FAILED:
                self._transition_state(self.STATE_CLOSED)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, sweep_timestamps, block_array, *, timing_rows=None):
        """Enqueue a block of sweeps for writing without blocking the caller."""
        with self._state_lock:
            item_bytes = sweep_timestamps.nbytes + block_array.nbytes
            if timing_rows is not None:
                item_bytes += len(timing_rows) * 384  # conservative Python row/list overhead
            if not self._accepting or self._state in {self.STATE_CLOSED, self.STATE_FAILED} or self._pending_bytes + item_bytes > self.max_pending_bytes:
                self._dropped_blocks += 1
                self._last_error = 'archive rejected data; capture incomplete (closed, failed or queue budget exceeded)'
                return False
            try:
                self.queue.put_nowait((sweep_timestamps.copy(), block_array.copy(), timing_rows, item_bytes))
            except queue.Full:
                self._dropped_blocks += 1
                self._last_error = 'archive queue budget exceeded; capture incomplete'
                return False
            self._enqueued_blocks += 1
            self._last_enqueue_time = time.perf_counter()
            self._pending_arrivals.append(self._last_enqueue_time)
            self._pending_bytes += item_bytes
            self._pending_sweeps += len(sweep_timestamps)
            return True

    def stop_nowait(self):
        """Signal the writer to finish but do not block the caller."""
        with self._state_lock:
            self._accepting = False
        self._stop_event.set()
        self._transition_state(self.STATE_DRAINING)
        return self.get_status_snapshot()

    def stop(self, timeout: float | None = 15.0):
        """Signal the writer to finish and wait for it to close."""
        self.stop_nowait()
        self.join(timeout=timeout)
        if not self.is_alive():
            self._closed_event.wait(timeout=0.0)
        return self.get_status_snapshot()
