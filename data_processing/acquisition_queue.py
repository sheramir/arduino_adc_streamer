"""Owned, bounded FIFO data with measurable backlog (never evict measurements)."""
from collections import deque
import threading
import time


class AcquisitionOverrun(RuntimeError):
    pass


class AcquisitionQueue:
    def __init__(self, max_bytes=16 * 1024 * 1024, max_items=2048):
        self.max_bytes, self.max_items = max_bytes, max_items
        self._items = deque()
        self._bytes = self._sweeps = 0
        self._condition = threading.Condition()

    def put(self, value, *, size=0, sweeps=0, arrival=None):
        with self._condition:
            if self._bytes + size > self.max_bytes or len(self._items) >= self.max_items:
                raise AcquisitionOverrun(
                    f"capture queue budget exceeded: items={len(self._items)}/{self.max_items}, "
                    f"bytes={self._bytes}+{size}/{self.max_bytes}")
            self._items.append((value, size, sweeps, time.perf_counter() if arrival is None else arrival))
            self._bytes += size
            self._sweeps += sweeps
            self._condition.notify()

    def get(self, timeout=0.02):
        with self._condition:
            if not self._items:
                self._condition.wait_for(lambda: bool(self._items), timeout)
            if not self._items:
                return None
            value, size, sweeps, arrival = self._items.popleft()
            self._bytes -= size
            self._sweeps -= sweeps
            return value

    def snapshot(self):
        with self._condition:
            return dict(items=len(self._items), bytes=self._bytes, sweeps=self._sweeps,
                        oldest_age_s=max(0.0, time.perf_counter() - self._items[0][3]) if self._items else 0.0)
