"""Narrow, fail-closed patch for the pinned Teensy 1.162.0 USB core.

Generate a build-local source copy; never edit the installed framework.
The upstream file retains its MIT license and copyright in the generated copy.
"""

import hashlib

CORE_SHA256 = "a675e0479e27cbad3a8e0fa6b918020af5b0f8894be43ebc495832995f5d842c"

# This uses the audited core's TX ownership, rather than availableForWrite(),
# which totals other free descriptors without checking the next ring slot.
# Reserve an entire frame before copying any bytes. USB completions can only
# free descriptors while autoflush is excluded; no foreground wait or yield.
LIVE_WRITE_SOURCE = r'''
int usb_serial_try_write_frame(const void *buffer, uint32_t size)
{
    if (!buffer || !size || size > TX_SIZE) return -1;
    if (!usb_configuration) return 0;
    tx_noautoflush = 1;
    asm volatile("" ::: "memory");
    const uint32_t available = tx_available ? tx_available : TX_SIZE;
    const uint8_t next = (tx_head + 1) % TX_NUM;
    if ((!tx_available && (usb_transfer_status(tx_transfer + tx_head) & 0x80)) ||
        (size > available && (usb_transfer_status(tx_transfer + next) & 0x80))) {
        // Submit already accepted bytes now. Re-arming a 75 us timer on every
        // rejected sweep could indefinitely defer a partial buffer's flush.
        if (tx_available) {
            uint8_t *txbuf = txbuffer + tx_head * TX_SIZE;
            const uint32_t count = TX_SIZE - tx_available;
            usb_prepare_transfer(tx_transfer + tx_head, txbuf, count, 0);
            arm_dcache_flush_delete(txbuf, count);
            usb_transmit(CDC_TX_ENDPOINT, tx_transfer + tx_head);
            tx_head = next;
            tx_available = 0;
            timer_stop();
        }
        asm("dsb" ::: "memory");
        tx_noautoflush = 0;
        return 0;
    }
    const uint32_t requested = size;
    const uint8_t *data = (const uint8_t *)buffer;
    while (size) {
        if (!tx_available) tx_available = TX_SIZE;
        const uint32_t count = size < tx_available ? size : tx_available;
        uint8_t *txbuf = txbuffer + tx_head * TX_SIZE;
        memcpy(txbuf + TX_SIZE - tx_available, data, count);
        tx_available -= count;
        data += count;
        size -= count;
        if (!tx_available) {
            usb_prepare_transfer(tx_transfer + tx_head, txbuf, TX_SIZE, 0);
            arm_dcache_flush_delete(txbuf, TX_SIZE);
            usb_transmit(CDC_TX_ENDPOINT, tx_transfer + tx_head);
            tx_head = (tx_head + 1) % TX_NUM;
            timer_stop();
        } else {
            timer_start_oneshot();
        }
    }
    transmit_previous_timeout = 0;
    asm("dsb" ::: "memory");
    tx_noautoflush = 0;
    return requested;
}
'''


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
    source = source.replace(before, after)
    marker = "#endif // CDC_STATUS_INTERFACE && CDC_DATA_INTERFACE"
    if source.count(marker) != 1:
        raise RuntimeError("Unexpected Teensy USB implementation boundary")
    return source.replace(marker, LIVE_WRITE_SOURCE + "\n" + marker)
