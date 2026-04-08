import json
import shutil
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import numpy as np

from data_processing.archive_writer import ArchiveWriterThread
from file_operations.archive_loader import ArchiveLoaderMixin


@contextmanager
def workspace_tempdir(prefix: str):
    root = Path(".codex_test_tmp")
    root.mkdir(exist_ok=True)
    path = root / f"{prefix}_{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class DummyArchiveLoader(ArchiveLoaderMixin):
    def __init__(self, archive_path: Path, block_timing_path: Path | None = None):
        self._archive_path = str(archive_path)
        self._block_timing_path = str(block_timing_path) if block_timing_path else None
        self.sweep_timestamps = []
        self.buffer_lock = threading.Lock()
        self.log_messages = []
        self._archive_writer = None

    def log_status(self, message: str):
        self.log_messages.append(message)


class ArchiveIoTests(unittest.TestCase):
    def test_archive_writer_persists_metadata_and_sweeps(self):
        with workspace_tempdir("archive_writer") as tmpdir:
            archive_path = tmpdir / "capture.jsonl"
            writer = ArchiveWriterThread(
                str(archive_path),
                {"metadata": {"channels": [1, 2], "repeat": 1}},
            )

            writer.start()
            writer.enqueue(
                np.asarray([0.0, 0.25], dtype=np.float64),
                np.asarray([[10, 20], [30, 40]], dtype=np.uint16),
            )
            writer.stop()

            with archive_path.open("r", encoding="utf-8") as handle:
                lines = [json.loads(line) for line in handle if line.strip()]

            self.assertEqual(lines[0]["metadata"]["channels"], [1, 2])
            self.assertEqual(lines[1], {"timestamp_s": 0.0, "samples": [10, 20]})
            self.assertEqual(lines[2], {"timestamp_s": 0.25, "samples": [30, 40]})
            self.assertEqual(writer.get_status_snapshot()["state"], ArchiveWriterThread.STATE_CLOSED)

    def test_archive_writer_reports_open_failure(self):
        with workspace_tempdir("archive_writer_failure") as tmpdir:
            archive_path = tmpdir / "missing" / "capture.jsonl"
            writer = ArchiveWriterThread(
                str(archive_path),
                {"metadata": {"channels": [1, 2], "repeat": 1}},
            )

            writer.start()
            snapshot = writer.stop(timeout=1.0)

            self.assertEqual(snapshot["state"], ArchiveWriterThread.STATE_FAILED)
            self.assertIn("archive writer", snapshot["last_error"])

    def test_archive_loader_prefers_embedded_timestamps(self):
        with workspace_tempdir("archive_embedded") as tmpdir:
            archive_path = tmpdir / "capture.jsonl"
            archive_path.write_text(
                "\n".join(
                    [
                        json.dumps({"metadata": {"channels": [1, 2]}}),
                        json.dumps({"timestamp_s": 0.0, "samples": [1, 2]}),
                        json.dumps({"timestamp_s": 0.5, "samples": [3, 4]}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            loader = DummyArchiveLoader(archive_path)
            sweeps, timestamps = loader.load_archive_data()

            self.assertEqual(sweeps, [[1, 2], [3, 4]])
            self.assertEqual(timestamps, [0.0, 0.5])

    def test_archive_loader_reconstructs_timestamps_from_sidecar(self):
        with workspace_tempdir("archive_sidecar") as tmpdir:
            archive_path = tmpdir / "capture.jsonl"
            archive_path.write_text(
                "\n".join(
                    [
                        json.dumps({"metadata": {"channels": [1, 2]}}),
                        json.dumps([11, 12]),
                        json.dumps([21, 22]),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            timing_path = tmpdir / "capture_block_timing.csv"
            timing_path.write_text(
                "sample_count,samples_per_sweep,sweeps_in_block,avg_dt_us,block_start_us,block_end_us,mcu_gap_us\n"
                "4,2,2,100,1000,1300,0\n",
                encoding="utf-8",
            )

            loader = DummyArchiveLoader(archive_path, timing_path)
            sweeps, timestamps = loader.load_archive_data()

            self.assertEqual(sweeps, [[11, 12], [21, 22]])
            self.assertEqual(timestamps, [0.0, 0.0002])
            self.assertFalse(hasattr(loader, "first_sweep_timestamp_us"))

    def test_archive_loader_falls_back_to_indices_without_timing_data(self):
        with workspace_tempdir("archive_fallback") as tmpdir:
            archive_path = tmpdir / "capture.jsonl"
            archive_path.write_text(
                "\n".join(
                    [
                        json.dumps({"metadata": {"channels": [1, 2]}}),
                        json.dumps([11, 12]),
                        json.dumps([21, 22]),
                        json.dumps([31, 32]),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            loader = DummyArchiveLoader(archive_path)
            sweeps, timestamps = loader.load_archive_data()

            self.assertEqual(sweeps, [[11, 12], [21, 22], [31, 32]])
            self.assertEqual(timestamps, [0, 1, 2])

    def test_finalize_archive_logs_writer_failure(self):
        with workspace_tempdir("archive_finalize_failure") as tmpdir:
            loader = DummyArchiveLoader(tmpdir / "capture.jsonl")
            writer = ArchiveWriterThread(
                str(tmpdir / "missing" / "capture.jsonl"),
                {"metadata": {"channels": [1], "repeat": 1}},
            )
            loader._archive_writer = writer

            writer.start()
            writer.stop(timeout=1.0)
            loader._finalize_archive_if_active()

            self.assertIsNone(loader._archive_writer)
            self.assertTrue(any("Archive writer failed" in msg for msg in loader.log_messages))


if __name__ == "__main__":
    unittest.main()
