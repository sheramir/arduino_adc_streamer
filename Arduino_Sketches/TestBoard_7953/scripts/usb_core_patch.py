"""Narrow, fail-closed patch for the pinned Teensy 1.162.0 USB core.

Generate a build-local source copy; never edit the installed framework.
The upstream file retains its MIT license and copyright in the generated copy.
"""

import hashlib

CORE_SHA256 = "a675e0479e27cbad3a8e0fa6b918020af5b0f8894be43ebc495832995f5d842c"


def patch_usb_serial(source: str) -> str:
    source = source.replace("\r\n", "\n")
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != CORE_SHA256:
        raise RuntimeError(
            "Teensy USB core differs from audited 1.162.0. "
            "Review the USB exclusion patch before changing framework versions."
        )
    # A volatile store alone does not prevent nonvolatile TX state reads from
    # being hoisted above exclusion (including reacquisition after yield).
    source = source.replace(
        "tx_noautoflush = 1;",
        'tx_noautoflush = 1;\n\tasm volatile("" ::: "memory");',
    )
    # Pending length must be checked under exclusion too. A timer callback can
    # otherwise flush/advance the ring between this check and guard acquisition.
    before = """\tif (tx_available == 0) return;
\ttx_noautoflush = 1;
\tasm volatile("" ::: "memory");"""
    after = """\ttx_noautoflush = 1;
\tasm volatile("" ::: "memory");
\tif (tx_available == 0) {
\t\tasm("dsb" ::: "memory");
\t\ttx_noautoflush = 0;
\t\treturn;
\t}"""
    if source.count(before) != 1 or source.count('asm volatile("" ::: "memory");') != 4:
        raise RuntimeError("Unexpected Teensy USB guard layout")
    return source.replace(before, after)
