"""Offline reproduction of the Teensy USB transmit exclusion race.

Run with uv --no-project --with unicorn --with pyelftools python <this file>.
This executes the existing ARM ELF in an emulator; no serial port is opened,
firmware uploaded, or ELF/package file changed. The ordered-guard control
rearranges instructions only in emulator memory. It is not a firmware fix.
Use --expect-fixed to check the actual repaired ELF without rearranging code.
The opcode checks intentionally reject unsupported compiler/code layouts.
"""

import argparse
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UcError
from unicorn.arm_const import (
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_PC,
    UC_ARM_REG_SP,
    UC_ARM_REG_LR,
)

if not __debug__:
    raise SystemExit("Run without -O: this verification requires enabled assertions")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--elf",
    type=Path,
    default=Path(__file__).resolve().parents[1] / ".pio/build/teensy41/firmware.elf",
)
parser.add_argument(
    "--expect-fixed",
    action="store_true",
    help="Validate the actual repaired build without changing instructions",
)
args = parser.parse_args()
ELF = args.elf
with ELF.open("rb") as file:
    elf = ELFFile(file)
    symbols = {
        s.name: s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()
    }
    sections = [
        (s["sh_addr"], s.data())
        for s in elf.iter_sections()
        if s["sh_flags"] & 2 and s["sh_size"] and s["sh_type"] != "SHT_NOBITS"
    ]


def frame(start):
    return (
        b"\xaa\x55\x19\x00"
        + struct.pack("<25H", *range(2000, 2025))
        + struct.pack("<HII", 3, start, start + 72)
    )


def run(
    inject,
    stale,
    ordered_guard=False,
    interrupt_offset=0x2E,
    operation="write",
    pending=True,
):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for addr, size in [
        (0, 0x20000),
        (0x20000000, 0x80000),
        (0x20200000, 0x80000),
        (0x60000000, 0x200000),
        (0x402E0000, 0x1000),
        (0xE000E000, 0x2000),
    ]:
        uc.mem_map(addr, size)
    for addr, data in sections:
        uc.mem_write(addr, data)

    def put(name, data):
        uc.mem_write(symbols[name], data)

    put("usb_configuration", b"\x01")
    put("tx_head", b"\x00")
    put("tx_available", struct.pack("<H", 2048 - 64 if pending else 0))
    put("tx_noautoflush", b"\x00")
    uc.mem_write(symbols["tx_transfer"], b"\x00" * 128)
    txbuffer = symbols["txbuffer"]
    first, fresh = frame(1000), frame(2000)
    uc.mem_write(txbuffer, first)
    uc.mem_write(txbuffer + 2048, stale)
    source = 0x20060000
    uc.mem_write(source, fresh)
    stop, irq_return = 0x10000, 0x10010
    write = symbols["usb_serial_write.part.0"] & ~1
    callback = symbols["usb_serial_flush_callback"] & ~1
    transmit = symbols["usb_transmit"] & ~1
    entry = write if operation == "write" else symbols["usb_serial_flush_output"] & ~1
    # Verify the compiled load-before-guard instruction sequence before injection.
    if args.expect_fixed:
        assert bytes(uc.mem_read(write + 0x22, 16)) == bytes.fromhex(
            "84f800905d4b5d4a1d783b8802eb4512"
        )
        # Guard must precede the state read on reacquisition after yield too.
        assert bytes(uc.mem_read(write + 0x7C, 6)) == bytes.fromhex("84f800903b88")
    else:
        assert bytes(uc.mem_read(write + 0x26, 12)) == bytes.fromhex(
            "1d783b8802eb451284f80090"
        )
    if ordered_guard:
        # Reorder the existing instructions in emulator memory only. No ELF is edited.
        # Guard store first, then tx_head/tx_available loads and descriptor calculation.
        uc.mem_write(write + 0x26, bytes.fromhex("84f800901d783b8802eb4512"))
    state = {"injected": False, "saved": None, "packets": []}

    def hook(uc, address, size, unused):
        if address == stop:
            uc.emu_stop()
        elif address == irq_return:
            saved = state["saved"]
            state["saved"] = None
            uc.context_restore(saved)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_PC) | 1)
        elif address == entry + interrupt_offset and inject and not state["injected"]:
            state["injected"] = True
            state["saved"] = uc.context_save()
            uc.reg_write(UC_ARM_REG_LR, irq_return | 1)
            uc.reg_write(UC_ARM_REG_PC, callback | 1)
        elif address == transmit:
            transfer = uc.reg_read(UC_ARM_REG_R1)
            _, status, pointer = struct.unpack("<III", uc.mem_read(transfer, 12))
            length = status >> 16
            state["packets"].append(bytes(uc.mem_read(pointer, length)))
            # Simulate immediate host completion; packet bytes are frozen at submit time.
            uc.mem_write(transfer + 4, b"\x00" * 4)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    uc.hook_add(UC_HOOK_CODE, hook)
    uc.reg_write(UC_ARM_REG_SP, 0x20070000)
    uc.reg_write(UC_ARM_REG_LR, stop | 1)
    uc.reg_write(UC_ARM_REG_R0, source)
    uc.reg_write(UC_ARM_REG_R1, 64)
    try:
        uc.emu_start(entry | 1, 0, count=100000)
    except UcError:
        print(
            "Emulator error PC",
            hex(uc.reg_read(UC_ARM_REG_PC)),
            "LR",
            hex(uc.reg_read(UC_ARM_REG_LR)),
            "SP",
            hex(uc.reg_read(UC_ARM_REG_SP)),
        )
        raise
    assert uc.reg_read(UC_ARM_REG_PC) == stop
    if operation == "write":
        assert uc.reg_read(UC_ARM_REG_R0) == 64
        # Expire the restarted timer to send the writer's pending data.
        uc.reg_write(UC_ARM_REG_LR, stop | 1)
        uc.emu_start(callback | 1, 0, count=100000)
    result = b"".join(state["packets"])
    expected = first + fresh if operation == "write" else (first if pending else b"")
    vulnerable = (
        inject
        and not ordered_guard
        and not args.expect_fixed
        and interrupt_offset in (0x2A, 0x2E)
    )
    if vulnerable:
        assert result == first + stale
        assert fresh not in result
    else:
        assert result == expected
    assert state["saved"] is None
    assert state["injected"] == inject
    assert bytes(uc.mem_read(symbols["tx_noautoflush"], 1)) == b"\x00"
    print(
        "fixed build"
        if args.expect_fixed
        else (
            "ordered guard" if ordered_guard else ("interrupt" if inject else "control")
        ),
        f"offset=0x{interrupt_offset:x}",
        operation,
        "pending" if pending else "empty",
        "packet_lengths",
        [len(p) for p in state["packets"]],
        "received_bytes",
        len(result),
        "stale_inserted",
        stale in result,
    )
    return result


old_frame = frame(100) + frame(200)
old_status = (b"# vmid_between_channels_requested=false\r\n# route_count=25\r\n").ljust(
    128, b" "
)
assert len(old_status) == 128
for stale in [old_frame, old_status]:
    run(False, stale)
    offsets = (
        (0x22, 0x26, 0x28, 0x2A, 0x2C, 0x2E)
        if args.expect_fixed
        else (0x22, 0x24, 0x26, 0x28, 0x2A, 0x2E)
    )
    for offset in offsets:
        run(True, stale, interrupt_offset=offset)
    # Guard-first instruction order has different instruction boundaries.
    if not args.expect_fixed:
        for offset in (0x22, 0x24, 0x26, 0x2A, 0x2C, 0x2E):
            run(True, stale, ordered_guard=True, interrupt_offset=offset)
    else:
        # Exercise explicit flush before/after guard acquisition and the empty
        # return branch, using the actual repaired machine code.
        for pending in (False, True):
            for offset in (0xC, 0x10, 0x12, 0x14, 0x16, 0x22 if pending else 0x18):
                run(
                    True,
                    stale,
                    interrupt_offset=offset,
                    operation="flush",
                    pending=pending,
                )
print(
    "PASS: actual repaired build preserves fresh data under every tested interrupt timing."
    if args.expect_fixed
    else "PASS: compiled USB write/flush code replays stale data and omits the fresh frame; ordered guard prevents this interleaving."
)
