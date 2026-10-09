"""Temporary Windows sleep inhibition, scoped to an active capture."""
import sys


def set_capture_awake(active):
    if sys.platform == 'win32':
        import ctypes
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED. Allow the screen to turn off.
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if active else 0x80000000)
