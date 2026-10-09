"""Bounded raw-byte transport outside the GUI process's Python GIL.

Windows duplicates the existing COM handle: no second port open, reset or wire
command is introduced. The private pipe framing is not the ADC wire protocol.
"""
import ctypes
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time

from data_processing.acquisition_queue import AcquisitionQueue, AcquisitionOverrun
from constants.serial import (SERIAL_READER_READ_MAX_BYTES, SERIAL_ISOLATED_QUEUE_BYTES,
                              SERIAL_READER_IDLE_MS, SERIAL_ISOLATED_CHUNK_INTERVAL_SEC)

_HEADER = struct.Struct('<cI')
_RAW = struct.Struct('<dIIdQ')
_BUDGET = SERIAL_ISOLATED_QUEUE_BYTES


def supports_isolation(port):
    return (os.name == 'nt' and type(port).__module__ == 'serial.serialwin32'
            and bool(getattr(port, '_port_handle', None)))


def _read_exact(stream, count):
    parts = bytearray()
    while len(parts) < count:
        data = stream.read(count - len(parts))
        if not data:
            raise EOFError('isolated reader pipe closed')
        parts.extend(data)
    return bytes(parts)


class _WindowsWorkerProcess:
    """Pin the actual interpreter, which may differ from Popen's venv launcher."""
    def __init__(self, pid):
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                               ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                               wintypes.BOOL, wintypes.DWORD]
        self.kernel.DuplicateHandle.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateProcess.restype = wintypes.BOOL
        self.pid = pid
        # PROCESS_DUP_HANDLE | PROCESS_TERMINATE | SYNCHRONIZE. Keep this handle
        # until shutdown so PID reuse cannot redirect duplication/termination.
        self.handle = self.kernel.OpenProcess(0x40 | 0x1 | 0x100000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def duplicate_handle(self, source_handle):
        from ctypes import wintypes
        duplicate = wintypes.HANDLE()
        if not self.kernel.DuplicateHandle(self.kernel.GetCurrentProcess(), source_handle,
                                           self.handle, ctypes.byref(duplicate), 0, False, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        return duplicate.value

    def wait(self, timeout_ms):
        result = self.kernel.WaitForSingleObject(self.handle, timeout_ms)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0  # WAIT_OBJECT_0, not WAIT_TIMEOUT.

    def terminate(self):
        if not self.wait(0) and not self.kernel.TerminateProcess(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class _RawChunkCoalescer:
    """Coalesce tiny USB reads without delaying/replacing measurements.

    The accumulator is bounded independently of the FIFO. Its timestamp is
    the first actual read, so queue/decode age includes coalescing delay.
    """
    def __init__(self, queue, *, max_bytes=SERIAL_READER_READ_MAX_BYTES,
                 interval=SERIAL_ISOLATED_CHUNK_INTERVAL_SEC):
        self.queue, self.max_bytes, self.interval = queue, max_bytes, interval
        self.buffer = bytearray()
        self.first_arrival = self.last_arrival = None
        self.read_gap_max_s = 0.0
        self.read_count = self.chunk_count = self.peak_bytes = 0

    def append(self, data, arrival):
        if len(data) > self.max_bytes:
            raise ValueError('raw read exceeds chunk budget')
        if self.buffer and len(self.buffer) + len(data) > self.max_bytes:
            self.flush()
        if not self.buffer:
            self.first_arrival = arrival
        if self.last_arrival is not None:
            self.read_gap_max_s = max(self.read_gap_max_s, arrival - self.last_arrival)
        self.last_arrival = arrival
        self.read_count += 1
        self.buffer.extend(data)
        self.flush_due(arrival)

    def flush_due(self, now):
        if self.buffer and (len(self.buffer) >= self.max_bytes or now - self.first_arrival >= self.interval):
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        pending = self.queue.snapshot()['bytes'] + len(self.buffer)
        self.peak_bytes = max(self.peak_bytes, pending)
        payload = _RAW.pack(self.first_arrival, pending, self.peak_bytes,
                            self.read_gap_max_s, self.read_count) + bytes(self.buffer)
        try:
            self.queue.put(payload, size=len(self.buffer), arrival=self.first_arrival)
        except AcquisitionOverrun as exc:
            raise AcquisitionOverrun(f'child raw FIFO: {exc}') from exc
        self.chunk_count += 1
        self.buffer.clear()
        self.read_gap_max_s = 0.0


class IsolatedRawReader:
    def __init__(self, port=None, *, replay=None, max_pending_bytes=_BUDGET):
        self.queue = AcquisitionQueue(max_bytes=max_pending_bytes)
        self.child_budget_bytes = max_pending_bytes
        self._ready = threading.Event()
        self._booted = threading.Event()
        self.worker_pid = None
        self._worker_process = None
        self._stopping = False
        self._fault = None
        self._write_lock = threading.Lock()
        self.received_bytes = 0
        self.delivery_age_max_s = 0.0
        self.child_pending_bytes = self.child_peak_bytes = 0
        self.native_read_count = self.received_chunks = 0
        self.last_native_read_interval_max_s = 0.0
        root = str(Path(__file__).resolve().parents[1])
        options = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                       cwd=root, bufsize=0)
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen([sys.executable, '-m', 'serial_communication.isolated_reader'], **options)
        self._bridge = threading.Thread(target=self._receive, name='RawReaderPipe', daemon=True)
        self._bridge.start()
        try:
            deadline = time.perf_counter() + 5
            if not self._booted.wait(5):
                raise RuntimeError('isolated raw reader bootstrap timed out')
            self._check_fault()
            if self.worker_pid is None:
                raise RuntimeError('isolated raw reader did not identify its interpreter')
            if os.name == 'nt':
                self._worker_process = _WindowsWorkerProcess(self.worker_pid)
            settings = dict(max_pending_bytes=max_pending_bytes, replay=replay)
            if replay is None:
                # The duplicated handle has the same access and COM state, but
                # the child creates its own OVERLAPPED event for reading.
                handle = self._worker_process.duplicate_handle(port._port_handle)
                settings.update(handle=handle, baudrate=port.baudrate, timeout=port.timeout)
            self._send(settings)
            if not self._ready.wait(max(0, deadline - time.perf_counter())):
                raise RuntimeError('isolated raw reader startup timed out')
            self._check_fault()
        except Exception:
            self.stop()
            raise

    def _send(self, message):
        data = (json.dumps(message) + '\n').encode()
        with self._write_lock:
            # Unbuffered FileIO may perform a short pipe write.
            view = memoryview(data)
            while view:
                written = self.process.stdin.write(view)
                if not written:
                    raise BrokenPipeError('isolated reader control pipe closed')
                view = view[written:]

    def replay_write(self, data):
        """Test/replay control only; production commands use the original port."""
        self._send({'write': data.hex()})

    def _receive(self):
        try:
            while True:
                kind, count = _HEADER.unpack(_read_exact(self.process.stdout, _HEADER.size))
                if count > SERIAL_READER_READ_MAX_BYTES + _RAW.size + 4096:
                    raise RuntimeError('invalid isolated-reader pipe record length')
                data = _read_exact(self.process.stdout, count)
                if kind == b'B':
                    self.worker_pid = int(json.loads(data)['pid'])
                    self._booted.set()
                elif kind == b'H':
                    self._ready.set()
                elif kind == b'R':
                    arrival, pending, peak, read_gap, read_count = _RAW.unpack_from(data)
                    raw = data[_RAW.size:]
                    self.child_pending_bytes, self.child_peak_bytes = pending, peak
                    self.received_bytes += len(raw)
                    self.native_read_count = read_count
                    self.received_chunks += 1
                    self.delivery_age_max_s = max(self.delivery_age_max_s, time.perf_counter() - arrival)
                    try:
                        self.queue.put((raw, arrival, read_gap), size=len(raw), arrival=arrival)
                    except AcquisitionOverrun as exc:
                        raise AcquisitionOverrun(f'parent pipe FIFO: {exc}') from exc
                elif kind == b'E':
                    failure = json.loads(data)
                    self._fault = (failure['kind'], failure['message'])
                    self._ready.set()
        except EOFError as exc:
            if not self._stopping and self._fault is None:
                self._fault = ('io', str(exc))
        except Exception as exc:
            self._fault = ('overrun' if isinstance(exc, AcquisitionOverrun) else 'io', str(exc))
        finally:
            self._booted.set()
            self._ready.set()

    def _check_fault(self):
        if self._fault:
            kind, message = self._fault
            error = AcquisitionOverrun if kind == 'overrun' else OSError
            raise error(f'isolated raw reader: {message}')

    def read_chunk(self, timeout=.02):
        item = self.queue.get(timeout)
        # Retain already owned measurements on an overrun/removal. Deliver the
        # bounded prefix, then report the failure instead of dropping the FIFO.
        if item is not None:
            raw, arrival, self.last_native_read_interval_max_s = item
            return raw, arrival
        self._check_fault()
        return None

    def snapshot(self):
        return dict(kind='isolated_process', pending=self.queue.snapshot(), budget_bytes=self.queue.max_bytes,
                    launcher_pid=self.process.pid, reader_pid=self.worker_pid,
                    child_budget_bytes=self.child_budget_bytes, child_pending_bytes_last=self.child_pending_bytes,
                    child_peak_bytes=self.child_peak_bytes, connection_received_bytes=self.received_bytes,
                    connection_native_reads=self.native_read_count, connection_pipe_chunks=self.received_chunks,
                    chunk_interval_s=SERIAL_ISOLATED_CHUNK_INTERVAL_SEC,
                    delivery_age_max_s=self.delivery_age_max_s, error=self._fault[1] if self._fault else None)

    def stop(self):
        self._stopping = True
        try:
            worker = self._worker_process
            active = not worker.wait(0) if worker and worker.handle else self.process.poll() is None
            if active:
                self._send({'stop': True})
                if worker is not None:
                    if not worker.wait(1000):
                        worker.terminate()
                        if not worker.wait(2000):
                            raise TimeoutError('isolated reader interpreter did not exit')
                else:
                    self.process.wait(timeout=1)
        except Exception:
            if self._worker_process is not None and self._worker_process.handle:
                self._worker_process.terminate()
                self._worker_process.wait(2000)
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=2)
        finally:
            if self._worker_process is not None:
                self._worker_process.close()
            # Reap the launcher too; terminating it alone would orphan a venv
            # interpreter with the duplicated COM handle still open.
            if self.process.poll() is None:
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    self.process.wait(timeout=2)
            self._bridge.join(1)
            for stream in (self.process.stdin, self.process.stdout):
                try:
                    stream.close()
                except Exception:
                    pass


def _worker():
    """Child: only serial reads, owned raw FIFO, and a pipe writer."""
    boot = json.dumps({'pid': os.getpid()}).encode()
    sys.stdout.buffer.write(_HEADER.pack(b'B', len(boot)) + boot)
    sys.stdout.buffer.flush()
    settings = json.loads(sys.stdin.buffer.readline())
    queue = AcquisitionQueue(max_bytes=settings['max_pending_bytes'])
    chunks = _RawChunkCoalescer(queue)
    done, stop = threading.Event(), threading.Event()
    commands = AcquisitionQueue(max_bytes=65536, max_items=128)
    failure = []
    device = None
    native_handle = native_event = None
    def send(kind, data):
        view = memoryview(_HEADER.pack(kind, len(data)) + data)
        while view:
            count = sys.stdout.buffer.write(view)
            if not count:
                raise BrokenPipeError('raw output pipe closed')
            view = view[count:]
        sys.stdout.buffer.flush()
    def control():
        try:
            for line in sys.stdin.buffer:
                message = json.loads(line)
                if message.get('stop'):
                    break
                commands.put(message, size=len(line))
        finally:
            stop.set()
    def output():
        try:
            while not done.is_set() or queue.snapshot()['items']:
                item = queue.get(timeout=.02)
                if item is not None:
                    send(b'R', item)
            if failure:
                send(b'E', json.dumps(failure[0]).encode())
        except Exception:
            stop.set()
    writer = None
    try:
        if settings.get('replay') is not None:
            from scripts.benchmark_testboard_gui import ReplayPort
            device = ReplayPort(**settings['replay'])
        else:
            from serial import serialwin32, win32
            device = serialwin32.Serial(port=None, baudrate=settings['baudrate'], timeout=settings['timeout'])
            native_handle = settings['handle']
            device._port_handle = native_handle
            device._overlapped_read = win32.OVERLAPPED()
            native_event = win32.CreateEvent(None, 1, 0, None)
            if not native_event:
                raise ctypes.WinError()
            device._overlapped_read.hEvent = native_event
            device.is_open = True
            # Validate the duplicated COM handle before reporting ready. The
            # GUI must never issue run* on a merely-created, unusable reader.
            device.in_waiting
        send(b'H', b'')
        writer = threading.Thread(target=output, name='RawPipeWriter', daemon=True)
        writer.start()
        threading.Thread(target=control, name='RawControl', daemon=True).start()
        while not stop.is_set():
            command = commands.get(timeout=0)
            if command is not None and settings.get('replay') is not None:
                device.write(bytes.fromhex(command['write']))
            data = device.read(min(device.in_waiting or 1, SERIAL_READER_READ_MAX_BYTES))
            if data:
                arrival = time.perf_counter()
                chunks.append(data, arrival)
            else:
                chunks.flush_due(time.perf_counter())
                if settings.get('replay') is not None or device.timeout == 0:
                    time.sleep(.0005 if settings.get('replay') is not None else SERIAL_READER_IDLE_MS / 1000)
    except Exception as exc:
        failure.append(dict(kind='overrun' if isinstance(exc, AcquisitionOverrun) else 'io',
                            message=f'{type(exc).__name__}: {exc}'))
        if writer is None:
            send(b'E', json.dumps(failure[0]).encode())
    finally:
        try:
            # A removal can occur while the final short chunk is accumulated.
            # Retain that owned prefix whenever the bounded FIFO still fits it.
            chunks.flush()
        except Exception as exc:
            if not failure:
                failure.append(dict(kind='overrun' if isinstance(exc, AcquisitionOverrun) else 'io',
                                    message=f'{type(exc).__name__}: {exc}'))
        done.set()
        if writer is not None:
            writer.join(1)
        if native_handle is not None:
            # Do not call Serial.close(): it purges the shared COM queues.
            from serial import win32
            device.is_open = False
            device._port_handle = None
            if native_event:
                win32.CloseHandle(native_event)
            win32.CloseHandle(native_handle)


if __name__ == '__main__':
    _worker()
