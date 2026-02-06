"""
Serial Reader Threads
====================
Background threads for reading serial data without blocking the GUI.
"""

from PyQt6.QtCore import QThread, pyqtSignal


class SerialReaderThread(QThread):
    """Background thread for reading serial data without blocking the GUI."""
    data_received = pyqtSignal(str)
    binary_sweep_received = pyqtSignal(list, int, int, int)  # samples, avg_sample_time_us, block_start_us, block_end_us
    error_occurred = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True
        self.is_capturing = False

    def run(self):
        """Continuously read from serial port and emit signals."""
        binary_buffer = bytearray()
        
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self.serial_port.in_waiting > 0:
                        data = self.serial_port.read(self.serial_port.in_waiting)
                        
                        # Always process as binary buffer to handle mixed binary/ASCII data
                        # This prevents "Unexpected ASCII" errors when MCU sends binary packets
                        binary_buffer.extend(data)
                        binary_buffer = self.process_binary_data(binary_buffer)
                else:
                    break

                self.msleep(10)  # Small delay to prevent CPU spinning

            except Exception as e:
                self.error_occurred.emit(f"Serial read error: {e}")
                break

    def process_binary_data(self, buffer):
        """Process buffer for binary block packets and ASCII messages.
        
        Binary blocks contain multiple sweeps:
        - Header: [0xAA][0x55][countL][countH] (4 bytes)
        - Payload: count samples as uint16_t little-endian
        - Each block may contain multiple sweeps
        
        If not capturing, binary packets are discarded (but not logged as errors).
        """
        while len(buffer) >= 2:
            # Look for binary block packet first (0xAA 0x55 header) - most reliable
            if len(buffer) >= 2 and buffer[0] == 0xAA and buffer[1] == 0x55:
                if len(buffer) < 4:
                    break  # Need more data for header
                
                sample_count = buffer[2] | (buffer[3] << 8)
                # New format: header(4) + samples(count*2) + avg_time(2) + block_start_us(4) + block_end_us(4)
                packet_size = 4 + (sample_count * 2) + 2 + 8
                
                if len(buffer) < packet_size:
                    break  # Need more data for complete block
                
                # Only process and emit if capturing
                if self.is_capturing:
                    # Extract all samples in block (little-endian uint16)
                    samples = []
                    for i in range(sample_count):
                        idx = 4 + (i * 2)
                        sample = buffer[idx] | (buffer[idx + 1] << 8)
                        samples.append(sample)
                    
                    # Extract average sampling time (us) from last 2 bytes (little-endian uint16)
                    avg_time_idx = 4 + (sample_count * 2)
                    avg_sample_time_us = buffer[avg_time_idx] | (buffer[avg_time_idx + 1] << 8)

                    # Extract block start/end micros (little-endian uint32)
                    ts_idx = avg_time_idx + 2
                    block_start_us = (
                        buffer[ts_idx]
                        | (buffer[ts_idx + 1] << 8)
                        | (buffer[ts_idx + 2] << 16)
                        | (buffer[ts_idx + 3] << 24)
                    )
                    block_end_us = (
                        buffer[ts_idx + 4]
                        | (buffer[ts_idx + 5] << 8)
                        | (buffer[ts_idx + 6] << 16)
                        | (buffer[ts_idx + 7] << 24)
                    )

                    # Emit block with average sampling time and MCU timestamps
                    self.binary_sweep_received.emit(samples, avg_sample_time_us, block_start_us, block_end_us)
                
                # Remove processed packet from buffer (whether capturing or not)
                buffer = buffer[packet_size:]
                continue
            
            # Look for ASCII messages (lines starting with #)
            if buffer[0] == ord('#'):
                # Find newline
                try:
                    newline_idx = buffer.index(ord('\n'))
                    line = buffer[:newline_idx].decode('utf-8', errors='strict').strip()
                    # Only emit if it's valid printable ASCII (not corrupted binary)
                    if line and line.isprintable():
                        self.data_received.emit(line)
                    buffer = buffer[newline_idx + 1:]
                    continue
                except (ValueError, UnicodeDecodeError):
                    # Not valid UTF-8 or no newline - this might be binary data disguised as #
                    buffer = buffer[1:]  # Skip this byte
                    continue
                except Exception:
                    # Other error - skip byte
                    buffer = buffer[1:]
                    continue
            
            # Unknown byte - skip it to resync
            buffer = buffer[1:]
        
        return buffer

    def set_capturing(self, capturing):
        """Set whether we're currently capturing data."""
        self.is_capturing = capturing

    def stop(self):
        """Stop the thread."""
        self.running = False


class ForceReaderThread(QThread):
    """Background thread for reading force sensor CSV data."""
    force_data_received = pyqtSignal(float, float)  # x_force, z_force
    error_occurred = pyqtSignal(str)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True

    def run(self):
        """Continuously read CSV data from force sensor serial port."""
        while self.running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    if self.serial_port.in_waiting > 0:
                        line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                        
                        if line:
                            # Parse CSV format: x,z
                            try:
                                parts = line.split(',')
                                if len(parts) >= 2:
                                    x_force = float(parts[0].strip())
                                    z_force = float(parts[1].strip())
                                    self.force_data_received.emit(x_force, z_force)
                            except ValueError:
                                pass  # Skip invalid lines
                else:
                    break

                self.msleep(10)  # Small delay to prevent CPU spinning

            except Exception as e:
                self.error_occurred.emit(f"Force sensor read error: {e}")
                break

    def stop(self):
        """Stop the thread."""
        self.running = False
