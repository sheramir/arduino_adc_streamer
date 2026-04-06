"""
Archive Writer Thread
=====================
Background thread for writing sweep data to JSONL archive files
without blocking the ingestion or GUI threads.

Usage::

    writer = ArchiveWriterThread(archive_path, metadata_dict)
    writer.start()

    # From ingestion thread (non-blocking):
    writer.enqueue(sweep_timestamps_sec_1d, block_uint16_2d)

    # When capture stops (blocks until queue is drained):
    writer.stop()
"""

import json
import queue
import threading
import time


class ArchiveWriterThread(threading.Thread):
    """Background daemon thread that drains a queue and writes JSONL sweep records.

    Each enqueued item is a ``(sweep_timestamps_sec, block_array)`` tuple where:
    - ``sweep_timestamps_sec`` is a 1-D numpy array of per-sweep timestamps (float).
    - ``block_array`` is a 2-D numpy array of shape ``(sweeps, samples)`` whose
      ``dtype`` should be ``uint16`` so that ``row.tolist()`` yields integer values
      matching the original binary protocol format.

    GIL note: ``json.dumps()`` is pure-Python and holds the GIL.  After processing
    each queue item the thread sleeps briefly (``_GIL_YIELD_SEC``) so the main/GUI
    thread gets consistent GIL time even when the queue is never empty.
    """

    _GIL_YIELD_SEC = 0.002  # 2 ms sleep between queue items → yields GIL to GUI thread

    def __init__(self, archive_path: str, metadata: dict):
        super().__init__(name="ArchiveWriter", daemon=True)
        self._archive_path = archive_path
        self._metadata = metadata
        self.queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self):
        try:
            with open(self._archive_path, 'w', encoding='utf-8') as f:
                # Write metadata header
                f.write(json.dumps(self._metadata) + '\n')

                write_count = 0
                while True:
                    try:
                        item = self.queue.get(timeout=0.1)
                    except queue.Empty:
                        # If stop has been requested and queue is empty, exit.
                        if self._stop_event.is_set():
                            break
                        continue

                    if item is None:
                        # Sentinel — drain is complete.
                        self.queue.task_done()
                        break

                    sweep_timestamps, block_array = item

                    # Build all lines for this block then do one write (fewer
                    # system calls; GIL is released during the actual I/O).
                    lines = []
                    for ts, row in zip(sweep_timestamps, block_array):
                        lines.append(
                            json.dumps({'timestamp_s': float(ts), 'samples': row.tolist()})
                            + '\n'
                        )
                    f.write(''.join(lines))
                    write_count += len(lines)

                    # Periodic flush every ~1000 sweeps.
                    if write_count % 1000 < len(lines):
                        try:
                            f.flush()
                        except Exception:
                            pass

                    self.queue.task_done()

                    # Yield GIL so the GUI/main thread gets consistent CPU time.
                    # Without this the tight json.dumps loop can starve Qt's event
                    # loop (timers, paint events) even though it runs in a thread.
                    time.sleep(self._GIL_YIELD_SEC)

                # Final flush before closing.
                try:
                    f.flush()
                except Exception:
                    pass

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, sweep_timestamps, block_array):
        """Enqueue a block of sweeps for writing. Non-blocking; drops on overflow."""
        try:
            self.queue.put_nowait((sweep_timestamps, block_array))
        except Exception:
            pass

    def stop_nowait(self):
        """Signal the writer to finish but do NOT block the caller.

        The thread is daemon=True, so it will complete and close the file in
        the background.  Use this from the GUI thread to avoid freezing the UI
        while a large queue drains.  Only use the blocking ``stop()`` when you
        need the file to be fully closed before proceeding (e.g. before deleting
        it from disk).
        """
        self._stop_event.set()
        try:
            self.queue.put_nowait(None)
        except Exception:
            pass
        # Do NOT join — let the daemon thread finish without blocking the caller.

    def stop(self):
        """Signal the writer to finish and block until the queue is fully drained."""
        self._stop_event.set()
        try:
            self.queue.put_nowait(None)
        except Exception:
            pass
        self.join(timeout=15.0)
