"""Execute the actual firmware controllers against tagged digital ADC/register stubs.

Run with a C++ compiler on PATH, or:
uv run --no-project --with pytest --with ziglang --with numpy --with pyserial python -m pytest tests/test_testboard_7953_firmware_runtime.py
No board or serial port is accessed. This does not validate analog/electrical timing.
"""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("profiling", [False, True])
def test_actual_controllers_preserve_frames_and_release_sessions(tmp_path, profiling):
    root = Path(__file__).resolve().parents[1]
    project = root / "Arduino_Sketches" / "TestBoard_7953"
    stubs = root / "tests" / "firmware_stubs"
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler:
        command = [compiler]
    elif importlib.util.find_spec("ziglang"):
        command = [sys.executable, "-m", "ziglang", "c++"]
    else:
        pytest.skip("Native C++ compiler required; run the uv command in this module's docstring")
    executable = tmp_path / ("testboard.exe" if sys.platform == "win32" else "testboard")
    sources = [project / "src" / f"{name}.cpp" for name in (
        "PztController", "SpiController", "Ads7953Adc", "ApiProtocol", "UsbSerialController")]
    # Zig's optimized C++ modes define NDEBUG. These checks (and the command
    # driver) use assert, so explicitly keep assertions enabled for every compiler.
    command += ["-std=c++17", "-O1", "-UNDEBUG", "-D__IMXRT1062__", f"-DTESTBOARD_PROFILE={int(profiling)}", "-I", str(stubs), "-I", str(project / "include"),
                *map(str, sources), str(stubs / "testboard_7953_runtime.cpp"), "-o", str(executable)]
    build = subprocess.run(command, capture_output=True, text=True, timeout=180)
    assert build.returncode == 0, build.stdout + build.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1188 digital acquisition cases passed" in result.stdout
    if profiling:
        from Arduino_Sketches.TestBoard_7953.benchmarks.testboard_7953_benchmark import parse_status
        from Arduino_Sketches.TestBoard_7953.benchmarks.firmware_profile import decode_profile

        status_text = result.stdout.split("PROFILE_STATUS_BEGIN\n", 1)[1].split("PROFILE_STATUS_END", 1)[0]
        summary = decode_profile(parse_status(status_text.splitlines()))
        assert summary["attempts"] == 5
        assert summary["written"] == 4
        assert summary["discarded"] == 1
        assert summary["aborted"] == 0
        assert summary["phases"]["run_prepare"]["count"] == 1
        assert summary["phases"]["period"]["count"] == 4
        assert summary["capacity_below_frame"] == 1
        assert summary["phases"]["usb_write"]["over_1ms"] == 0
