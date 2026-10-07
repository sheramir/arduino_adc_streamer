import json

import pytest

from Arduino_Sketches.TestBoard_7953.benchmarks.firmware_profile import PHASES, decode_profile, save_profile
from Arduino_Sketches.TestBoard_7953.benchmarks.testboard_7953_benchmark import (
    BenchmarkError, configure_profile, parse_args,
)


def status_fixture():
    result = dict(profile_available="true", profile_enabled="true", profile_version="1", running="false")
    for key in ("aborted", "invalid_foreground", "frequency_changes", "capacity_below_frame"):
        result[f"profile_{key}"] = "0"
    for key in ("attempts", "written", "write_calls"):
        result[f"profile_{key}"] = "2"
    for key in ("capacity_min", "capacity_max"):
        result[f"profile_{key}"] = "2048"
    result.update(profile_clock_hz="600000000", profile_probe_cycles_min="1", profile_probe_cycles_max="3",
                  profile_bounds_us="1,2,4,8,16,32,64,100,128,256,512,1000,2000,4000,16000,64000")
    for name in PHASES:
        # Two 0.5 us observations in the first bin; period/gap use microseconds.
        total, maximum = (2, 1) if name in ("period", "gap") else (600, 300)
        result[f"profile_{name}"] = ",".join(map(str, [2, total, maximum, 0, 0, 2, *([0] * 16)]))
    return result


def test_cycles_units_histogram_bounds_and_tail_attribution():
    status = status_fixture()
    status["profile_tail0"] = "3100,3000,42000,600,300,1800000,1200,600"
    result = decode_profile(status)
    assert result["phases"]["usb_write"]["mean_us"] == .5
    assert result["phases"]["usb_write"]["p99_upper_us"] == 1
    assert result["phases"]["period"]["mean_us"] == 1
    assert result["longest_periods"][0]["previous_usb_write_us"] == 3000
    assert result["longest_periods"][0]["previous_acquisition_us"] == 70


def test_overflow_histogram_quantile_is_unbounded_not_a_false_64ms_limit():
    status = status_fixture()
    status["profile_usb_write"] = ",".join(map(str, [2, 120000000, 60000000, 2, 2, *([0] * 16), 2]))
    phase = decode_profile(status)["phases"]["usb_write"]
    assert phase["p99_upper_us"] is None
    assert phase["max_us"] == 100000


@pytest.mark.parametrize("key,value", [
    ("profile_transfer", "1,2,3"), ("profile_frequency_changes", "1"),
    ("profile_invalid_foreground", "1"), ("profile_clock_hz", "0"),
    ("profile_clock_hz", "600000000,1"), ("profile_attempts", "4"),
    ("profile_encode", "-1"), ("profile_tail0", "110,30"),
    ("running", "true"), ("profile_version", "3"),
])
def test_reject_invalid_or_unusable_profile(key, value):
    status = status_fixture()
    status[key] = value
    with pytest.raises(ValueError):
        decode_profile(status)


def test_legacy_and_disabled_profiles_remain_compatible():
    assert decode_profile({}) == dict(available=False, enabled=False)
    assert decode_profile(dict(profile_available="true", profile_enabled="false")) == dict(available=True, enabled=False)


def test_live_discarded_sweeps_are_separate_from_aborted_acquisitions(tmp_path):
    status = status_fixture()
    status.update(profile_version="2", profile_attempts="7", profile_discarded="5")
    status["profile_bookkeeping"] = ",".join(map(str, [7, 2100, 300, 0, 0, 7, *([0] * 16)]))
    summary = save_profile(tmp_path / "profile.jsonl", status, received_frames=2, requested="on")
    assert summary["attempts"] == 7 and summary["discarded"] == 5 and summary["aborted"] == 0
    status["profile_discarded"] = "4"
    with pytest.raises(ValueError, match="sweep counts"):
        decode_profile(status)


def test_persist_profile_evidence_even_when_received_count_does_not_match(tmp_path):
    path = tmp_path / "profile.jsonl"
    status = status_fixture()
    with pytest.raises(ValueError, match="count mismatch"):
        save_profile(path, status, received_frames=1, requested="on", test_id="example", attempt=1)
    record = json.loads(path.read_text())
    assert record["raw_status"]["profile_written"] == "2"
    assert record["received_frames"] == 1
    assert "error" in record


def test_save_success_and_disabled_captures_without_nan(tmp_path):
    path = tmp_path / "profile.jsonl"
    save_profile(path, status_fixture(), received_frames=2, requested="on", attempt=1)
    save_profile(path, {}, received_frames=2, requested="off", attempt=2)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["summary"]["phases"]["acquisition"]["mean_us"] == .5
    assert records[1]["summary"]["enabled"] is False


def test_aborted_sweep_fails_even_when_all_complete_writes_arrived(tmp_path):
    status = status_fixture()
    status.update(profile_attempts="3", profile_aborted="1")
    # Three observed attempts, two successful writes. Histogram bookkeeping
    # remains internally consistent, so the abort is the reason for rejection.
    status["profile_bookkeeping"] = ",".join(map(str, [3, 900, 300, 0, 0, 3, *([0] * 16)]))
    with pytest.raises(ValueError, match="aborted sweeps"):
        save_profile(tmp_path / "profile.jsonl", status, received_frames=2, requested="on")


class Protocol:
    def __init__(self):
        self.commands = []

    def send_command(self, command):
        self.commands.append(command)
        return ["# profile_available=true", f"# profile_enabled={'true' if self.commands[0] == 'profile on' else 'false'}", "#OK"]


def test_normalize_mode_and_reject_profile_request_on_legacy_firmware():
    protocol = Protocol()
    configure_profile(protocol, {"profile_available": "true"}, "off")
    assert protocol.commands == ["profile off", "status"]
    legacy = Protocol()
    assert configure_profile(legacy, {}, "off") == {}
    assert legacy.commands == []
    with pytest.raises(BenchmarkError, match="teensy41_profile"):
        configure_profile(legacy, {}, "on")
    enabled = Protocol()
    assert configure_profile(enabled, {"profile_available": "true"}, "on")["profile_enabled"] == "true"


def test_profiling_is_optional_and_ghosting_cannot_enable_it():
    assert parse_args(["--dry-run"]).profile == "off"
    assert parse_args(["--dry-run", "--profile", "on"]).profile == "on"
    with pytest.raises(SystemExit):
        parse_args(["--ghosting", "--profile", "on", "--ghost-adc", "1", "--dry-run"])


def test_resume_cannot_mix_instrumented_and_uninstrumented_results(tmp_path, monkeypatch):
    from Arduino_Sketches.TestBoard_7953.benchmarks import testboard_7953_benchmark as runner

    metadata = tmp_path / "session_metadata.json"
    original = json.dumps(dict(session_id="retained", firmware_profile_mode="off"))
    metadata.write_text(original)
    monkeypatch.setattr(runner, "open_serial_port", lambda *_: pytest.fail("Must reject before opening COM3"))
    with pytest.raises(SystemExit, match="Cannot resume"):
        runner.main(["--resume", "--port", "COM3", "--output", str(tmp_path), "--profile", "on"])
    assert metadata.read_text() == original
    assert not (tmp_path / "session_commands.log").exists()
