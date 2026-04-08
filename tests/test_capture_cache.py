import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from data_processing.capture_cache import CaptureCacheMixin


class FakeWriter:
    def __init__(self, *, alive=False, stop_state='closed', stop_nowait_state='draining'):
        self._alive = alive
        self.stop_state = stop_state
        self.stop_nowait_state = stop_nowait_state
        self.stop_called = 0
        self.stop_nowait_called = 0

    def stop(self):
        self.stop_called += 1
        self._alive = False
        return {'state': self.stop_state, 'last_error': None}

    def stop_nowait(self):
        self.stop_nowait_called += 1
        return {'state': self.stop_nowait_state, 'last_error': None}

    def is_alive(self):
        return self._alive


class CaptureCacheHarness(CaptureCacheMixin):
    def __init__(self):
        self.logged = []
        self.deferred = None
        self._archive_writer = None
        self._block_timing_file = None
        self._archive_path = None
        self._block_timing_path = None
        self._cache_dir_path = None
        self._archive_write_count = 0
        self._block_timing_write_count = 0

    def log_status(self, message):
        self.logged.append(message)

    def _defer_capture_cache_cleanup(self, writer, archive_path, block_timing_path, cache_dir_path, attempts_left=100):
        self.deferred = {
            'writer': writer,
            'archive_path': archive_path,
            'block_timing_path': block_timing_path,
            'cache_dir_path': cache_dir_path,
            'attempts_left': attempts_left,
        }


class CaptureCacheTests(unittest.TestCase):
    def _make_cache_dir(self):
        base = Path('tests') / f'__cache_test_{uuid4().hex}'
        cache_dir = base / 'cache'
        cache_dir.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(base, ignore_errors=True))
        return cache_dir

    def test_cleanup_capture_cache_blocking_deletes_files_and_resets_state(self):
        harness = CaptureCacheHarness()
        cache_dir = self._make_cache_dir()
        archive_path = cache_dir / 'capture.jsonl'
        timing_path = cache_dir / 'timing.csv'
        archive_path.write_text('data', encoding='utf-8')
        timing_path.write_text('timing', encoding='utf-8')

        harness._archive_writer = FakeWriter(alive=False)
        harness._block_timing_file = open(timing_path, 'a', encoding='utf-8')
        self.addCleanup(lambda: harness._block_timing_file and getattr(harness._block_timing_file, 'close', lambda: None)())
        harness._archive_path = str(archive_path)
        harness._block_timing_path = str(timing_path)
        harness._cache_dir_path = str(cache_dir)
        harness._archive_write_count = 3
        harness._block_timing_write_count = 4

        harness.cleanup_capture_cache(block=True)

        self.assertIsNone(harness._archive_writer)
        self.assertIsNone(harness._block_timing_file)
        self.assertIsNone(harness._archive_path)
        self.assertIsNone(harness._block_timing_path)
        self.assertIsNone(harness._cache_dir_path)
        self.assertEqual(harness._archive_write_count, 0)
        self.assertEqual(harness._block_timing_write_count, 0)
        self.assertFalse(archive_path.exists())
        self.assertFalse(timing_path.exists())
        self.assertFalse(cache_dir.exists())

    def test_cleanup_capture_cache_nonblocking_defers_when_writer_alive(self):
        harness = CaptureCacheHarness()
        writer = FakeWriter(alive=True)
        cache_dir = self._make_cache_dir()
        archive_path = cache_dir / 'capture.jsonl'
        timing_path = cache_dir / 'timing.csv'
        archive_path.write_text('data', encoding='utf-8')
        timing_path.write_text('timing', encoding='utf-8')

        harness._archive_writer = writer
        harness._block_timing_file = open(timing_path, 'a', encoding='utf-8')
        self.addCleanup(lambda: harness._block_timing_file and getattr(harness._block_timing_file, 'close', lambda: None)())
        harness._archive_path = str(archive_path)
        harness._block_timing_path = str(timing_path)
        harness._cache_dir_path = str(cache_dir)

        harness.cleanup_capture_cache(block=False)

        self.assertEqual(writer.stop_nowait_called, 1)
        self.assertIsNotNone(harness.deferred)
        self.assertEqual(harness.deferred['archive_path'], str(archive_path))
        self.assertTrue(archive_path.exists())
        self.assertTrue(timing_path.exists())


if __name__ == '__main__':
    unittest.main()
