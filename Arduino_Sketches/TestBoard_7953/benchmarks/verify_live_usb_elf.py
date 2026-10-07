"""Execute the built ARM nonblocking USB writer without opening a serial port.

uv run --no-project --with unicorn --with pyelftools python <this file> --elf <firmware.elf>
Checks complete-frame reservation, ring wrap, busy descriptors, disconnects,
invalid requests and autoflush interrupts at compiled instruction boundaries
outside Thumb IT blocks (Unicorn cannot resume hook-injected handlers inside IT).
"""

import argparse
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_CPSR


def verify(path: Path) -> int:
    with path.open("rb") as file:
        elf = ELFFile(file)
        table = {s.name: (s["st_value"], s["st_size"]) for s in elf.get_section_by_name(".symtab").iter_symbols()}
        sections = [(s["sh_addr"], s.data()) for s in elf.iter_sections()
                    if s["sh_flags"] & 2 and s["sh_size"] and s["sh_type"] != "SHT_NOBITS"]
    symbols = {name: value[0] for name, value in table.items()}
    entry = symbols["usb_serial_try_write_frame"] & ~1
    end = entry + table["usb_serial_try_write_frame"][1]
    callback = symbols["usb_serial_flush_callback"] & ~1
    transmit = symbols["usb_transmit"] & ~1
    stop, irq_return, source = 0x10000, 0x10010, 0x20060000
    fresh = b"\xaa\x55\x19\x00" + struct.pack("<25H", *range(2000, 2025)) + struct.pack("<HII", 3, 1000, 1072)

    def run(head=0, remaining=0, busy=0, length=64, inject=None, connected=True):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for addr, size in [(0, 0x20000), (0x20000000, 0x80000), (0x20200000, 0x80000),
                           (0x60000000, 0x200000), (0x402E0000, 0x1000), (0xE000E000, 0x2000)]:
            uc.mem_map(addr, size)
        for addr, data in sections:
            uc.mem_write(addr, data)
        put = lambda name, data: uc.mem_write(symbols[name], data)
        put("usb_configuration", bytes([connected]))
        put("tx_head", bytes([head]))
        put("tx_available", struct.pack("<H", remaining))
        put("tx_noautoflush", b"\0")
        put("tx_packet_size", struct.pack("<H", 512))
        put("tx_transfer", b"\0" * 128)
        for i in range(4):
            uc.mem_write(symbols["tx_transfer"] + i * 32 + 4, struct.pack("<I", 0x80 if busy & (1 << i) else 0))
        uc.mem_write(source, fresh + b"\x7c" * 2048)
        old = b"\x39" * (2048 - remaining) if remaining else b""
        uc.mem_write(symbols["txbuffer"] + head * 2048, old)
        before = bytes(uc.mem_read(symbols["txbuffer"], 8192))
        state = dict(saved=None, injected=False, packets=[], trace=set(), instructions=0)

        def hook(uc, address, size, unused):
            state["instructions"] += 1
            if address == stop:
                uc.emu_stop()
            elif address == irq_return:
                uc.context_restore(state["saved"])
                state["saved"] = None
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_PC) | 1)
            elif address == inject and not state["injected"]:
                state["injected"] = True
                state["saved"] = uc.context_save()
                # Cortex-M exception entry clears IT state for the handler.
                uc.reg_write(UC_ARM_REG_CPSR, uc.reg_read(UC_ARM_REG_CPSR) & ~((3 << 25) | (0x3F << 10)))
                uc.reg_write(UC_ARM_REG_LR, irq_return | 1)
                uc.reg_write(UC_ARM_REG_PC, callback | 1)
            elif address == transmit:
                transfer = uc.reg_read(UC_ARM_REG_R1)
                _, status, pointer = struct.unpack("<III", uc.mem_read(transfer, 12))
                state["packets"].append(bytes(uc.mem_read(pointer, status >> 16)))
                uc.mem_write(transfer + 4, b"\0" * 4)  # Host completes newly submitted bytes.
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            elif address == (symbols.get("yield", 0) & ~1):
                raise AssertionError("Live writer called yield/wait")
            if entry <= address < end:
                state["trace"].add(address)

        handle = uc.hook_add(UC_HOOK_CODE, hook)
        uc.reg_write(UC_ARM_REG_SP, 0x20070000)
        uc.reg_write(UC_ARM_REG_LR, stop | 1)
        uc.reg_write(UC_ARM_REG_R0, source)
        uc.reg_write(UC_ARM_REG_R1, length)
        uc.emu_start(entry | 1, 0, count=10000)
        assert uc.reg_read(UC_ARM_REG_PC) == stop, "Writer did not return within bounded instruction budget"
        result = uc.reg_read(UC_ARM_REG_R0)
        assert bytes(uc.mem_read(symbols["tx_noautoflush"], 1)) == b"\0"
        assert state["saved"] is None, (head, remaining, busy, length, hex(inject or 0), hex(uc.reg_read(UC_ARM_REG_PC)), hex(uc.reg_read(UC_ARM_REG_LR)))
        assert state["injected"] == (inject is not None)
        if length == 0 or length > 2048:
            assert result == 0xFFFFFFFF and bytes(uc.mem_read(symbols["txbuffer"], 8192)) == before
        else:
            assert result in (0, length)
            if inject is None:
                available = remaining or 2048
                blocked = (not remaining and busy & (1 << head)) or (length > available and busy & (1 << ((head + 1) % 4)))
                assert result == (0 if blocked or not connected else length)
            if result == 0 and inject is None:
                assert bytes(uc.mem_read(symbols["txbuffer"], 8192)) == before, "Rejected frame copied a partial prefix"
            # Finish pending bytes through the real core's autoflush routine.
            uc.reg_write(UC_ARM_REG_LR, stop | 1)
            uc.emu_start(callback | 1, 0, count=10000)
            expected = (old + (fresh + b"\x7c" * 2048)[:length] if result else old) if connected else b""
            assert b"".join(state["packets"]) == expected, "Partial, duplicate or stale bytes emitted"
        # ctypes callbacks retain the engine. Break the reference cycle on each
        # scenario rather than leaving hundreds of ARM engines to Windows GC.
        uc.hook_del(handle)
        return state["trace"]

    count = 0
    for head in range(4):
        for remaining in (0, 32, 64, 1984):
            for busy in range(16):
                if remaining and busy & (1 << head):
                    continue  # Partially filled current descriptor is owned by foreground.
                for length in (18, 64, 114):
                    run(head, remaining, busy, length)
                    count += 1
    for remaining, busy in ((1984, 0), (32, 2), (0, 15)):
        conditional_count = 0
        for address in sorted(run(remaining=remaining, busy=busy)):
            if conditional_count:
                conditional_count -= 1
                continue
            # Find IT instructions in the actual executed trace. Their mask
            # gives the number of following conditional instructions.
            opcode = None
            for base, data in sections:
                if base <= address < base + len(data):
                    opcode = struct.unpack_from("<H", data, address - base)[0]
                    break
            if opcode is not None and opcode & 0xFF00 == 0xBF00 and opcode & 15:
                mask = opcode & 15
                conditional_count = 4 - ((mask & -mask).bit_length() - 1)
            run(remaining=remaining, busy=busy, inject=address)
            count += 1
    for connected, length in ((False, 64), (True, 0), (True, 2049)):
        run(connected=connected, length=length)
        count += 1
    print(f"PASS: {count} live USB ARM scenarios; whole frames or zero bytes, no foreground waits")
    return count


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without -O: verification requires assertions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, default=Path(__file__).resolve().parents[1] / ".pio/build/teensy41/firmware.elf")
    verify(parser.parse_args().elf)
