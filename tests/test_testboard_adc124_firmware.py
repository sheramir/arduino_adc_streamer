"""Host simulation of the production driver; optional compiler dependency.

Run explicitly with: uv run --with ziglang pytest tests/test_testboard_adc124_firmware.py
The regular Python suite skips this test if no native compiler is installed.
"""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_production_adc_driver_pipeline_gpio_and_error_recovery(tmp_path):
    project = Path(__file__).resolve().parents[1] / "Arduino_Sketches" / "TestBoard_ADC124"
    if importlib.util.find_spec("ziglang"):
        compiler = [sys.executable, "-m", "ziglang", "c++"]
        if sys.platform == "win32":
            compiler += ["-target", "x86_64-windows-gnu"]
    elif shutil.which("g++"):
        compiler = [shutil.which("g++")]
    elif shutil.which("clang++"):
        compiler = [shutil.which("clang++")]
    else:
        pytest.skip("Install a native C++ compiler or use uv run --with ziglang pytest")
    executable = tmp_path / ("driver_test.exe" if sys.platform == "win32" else "driver_test")
    command = compiler + ["-std=c++14", "-I", str(project / "test" / "host"),
        "-I", str(project / "include"), str(project / "test" / "host" / "driver_test.cpp"),
        str(project / "src" / "Adc124s101.cpp"), "-o", str(executable)]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=180)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    tested = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert tested.returncode == 0, tested.stdout + tested.stderr
    assert "failures passed" in tested.stdout
