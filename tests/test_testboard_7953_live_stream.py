import importlib.util
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from Arduino_Sketches.TestBoard_7953.benchmarks import testboard_7953_benchmark as runner


def live_status(**updates):
    return dict(usb_stream_policy="discard_if_busy", sampling_sweeps="105",
                usb_frames_sent="5", usb_frames_discarded="100",
                sampling_period_max_us="60", sampling_period_over_1ms="0", **updates)


def test_discarded_samples_reconcile_without_becoming_usb_errors():
    runner.validate_live_transport(live_status(), 5)
    runner.validate_live_transport({}, 5)  # Historical firmware remains supported.


@pytest.mark.parametrize("field,value", [
    ("sampling_sweeps", "106"), ("usb_frames_sent", "6"),
    ("usb_frames_discarded", "-100"), ("sampling_period_max_us", "bad"),
])
def test_live_counter_mismatch_or_malformed_status_fails(field, value):
    status = live_status()
    status[field] = value
    with pytest.raises(runner.BenchmarkError):
        runner.validate_live_transport(status, 5)


def test_live_status_requires_all_fields_and_all_accepted_frames():
    status = live_status()
    del status["sampling_period_max_us"]
    with pytest.raises(runner.BenchmarkError):
        runner.validate_live_transport(status, 5)
    with pytest.raises(runner.BenchmarkError, match="sent/received"):
        runner.validate_live_transport(live_status(), 4)


@pytest.mark.parametrize("deferred", [False, True])
def test_reader_pause_and_deferred_parser_preserve_bytes_and_arrival_times(monkeypatch, deferred):
    wire = b"".join(b"\xaa\x55\x01\x00" + struct.pack("<HHII", 2048, 10, i * 20, i * 20 + 10)
                    for i in range(1, 4))

    class Clock:
        now = 0
        sleeps = []

        def stamp(self):
            self.now += 100_000
            return self.now

        def sleep(self, duration):
            self.sleeps.append(duration)
            self.now += int(duration * 1e9)

    class Port:
        chunks = [wire[i:i + 5] for i in range(0, len(wire), 5)]
        commands = []

        @property
        def in_waiting(self):
            return len(self.chunks[0]) if self.chunks else 0

        def read(self, size):
            return self.chunks.pop(0) if self.chunks else b""

        def write(self, data):
            self.commands.append(data)

        def flush(self):
            pass

    class Log:
        def write(self, text):
            pass

    clock, port = Clock(), Port()
    original = runner.BinaryFrameParser
    pending_at_parse = []

    class ObservedParser(original):
        def feed(self, data, received_ns=None):
            pending_at_parse.append(len(port.chunks))
            return super().feed(data, received_ns)

    monkeypatch.setattr(runner.time, "monotonic_ns", clock.stamp)
    monkeypatch.setattr(runner.time, "sleep", clock.sleep)
    monkeypatch.setattr(runner, "BinaryFrameParser", ObservedParser)
    capture = runner.SerialProtocol(port, Log()).capture_timed(
        10, 1, 3, 1, reader_pause_ms=2, reader_pause_at_ms=1, defer_parsing=deferred)
    assert capture.raw == wire and len(capture.frames) == 3
    assert not capture.timed_out and capture.trailing_bytes == 0
    assert not any(capture.stream_integrity.values())
    assert clock.sleeps == [.002]
    assert port.commands == [b"run 10*"]
    assert all(frame.host_received_ns > 0 for frame in capture.frames)
    assert (max(pending_at_parse) == 0) == deferred


def test_stress_cli_rejects_pause_beyond_run_or_ghosting():
    args = runner.parse_args(["--dry-run", "--reader-pause-ms", "500", "--defer-parsing"])
    assert args.reader_pause_ms == 500 and args.defer_parsing
    for options in (["--reader-pause-ms", "-1"],
                    ["--reader-pause-ms", "5000"],
                    ["--ghosting", "--ghost-adc", "1", "--defer-parsing"]):
        with pytest.raises(SystemExit):
            runner.parse_args(["--dry-run", *options])


@pytest.mark.parametrize("environment", ["teensy41", "teensy41_profile"])
def test_actual_arm_live_writer_never_waits_or_emits_partial_frame(environment):
    if not importlib.util.find_spec("unicorn") or not importlib.util.find_spec("elftools"):
        pytest.skip("ARM emulator dependencies required")
    elf = Path(__file__).resolve().parents[1] / "Arduino_Sketches/TestBoard_7953/.pio/build" / environment / "firmware.elf"
    if not elf.exists():
        pytest.skip("Build firmware before testing ARM USB code")
    # Isolate Unicorn's Windows exception handling from pytest's faulthandler.
    # A real native crash is a nonzero subprocess exit and fails this test.
    script = elf.parents[3] / "benchmarks/verify_live_usb_elf.py"
    result = subprocess.run([sys.executable, str(script), "--elf", str(elf)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "live USB ARM scenarios" in result.stdout
