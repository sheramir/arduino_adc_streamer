from pathlib import Path

import pytest

from Arduino_Sketches.TestBoard_7953.scripts.usb_core_patch import patch_usb_serial


def test_usb_patch_rejects_unknown_framework_source():
    with pytest.raises(RuntimeError, match="differs from audited"):
        patch_usb_serial("unexpected framework version")


def test_usb_patch_orders_all_guards_and_moves_flush_check_under_exclusion():
    core = (
        Path.home()
        / ".platformio/packages/framework-arduinoteensy/cores/teensy4/usb_serial.c"
    )
    if not core.exists():
        pytest.skip("Pinned Teensy package is not installed")
    original = core.read_bytes()
    patched = patch_usb_serial(original.decode())
    assert patched.count('tx_noautoflush = 1;\n\tasm volatile("" ::: "memory");') == 4
    flush = patched.split("void usb_serial_flush_output(void)", 1)[1]
    assert flush.index("tx_noautoflush = 1") < flush.index("if (tx_available == 0)")
    empty = flush.split("if (tx_available == 0)", 1)[1].split("transfer_t", 1)[0]
    assert "tx_noautoflush = 0" in empty
    assert core.read_bytes() == original
