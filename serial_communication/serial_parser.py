"""
Serial Data Parser Mixin
=========================
Handles parsing of ASCII serial messages from Arduino.
"""


class SerialParserMixin:
    """Mixin for parsing ASCII serial data."""
    
    def process_serial_data(self, line: str):
        """Process incoming ASCII serial data (status messages, errors, etc.)."""
        if line.startswith('#'):
            # Log all status messages
            self.log_status(line)
            # Parse status lines when not in configuration mode
            if 'STATUS' in line or ':' in line or (line.startswith('#   ') and ',' in line):
                self.parse_status_line(line)
        else:
            # Only log if it's printable ASCII (not binary data that got through)
            if line.strip() and line.isprintable():
                self.log_status(f"Unexpected ASCII: {line}")
    
    def parse_status_line(self, line: str):
        """Parse a single line from Arduino status output."""
        try:
            # Parse channels: "#   1,2,3,4,5"
            if line.startswith('#   ') and ',' in line and not ':' in line:
                channels_str = line[4:].strip()
                channels = [int(c.strip()) for c in channels_str.split(',')]
                self.arduino_status['channels'] = channels
                return
            
            # Parse other fields
            if ':' in line:
                parts = line.split(':', 1)
                key = parts[0].strip('# ').strip()
                value = parts[1].strip()
                
                if 'repeatCount' in key:
                    self.arduino_status['repeat'] = int(value)
                elif 'groundPin' in key:
                    self.arduino_status['ground_pin'] = int(value)
                elif 'useGroundBeforeEach' in key:
                    self.arduino_status['use_ground'] = (value.lower() == 'true')
                elif 'osr' in key.lower():
                    self.arduino_status['osr'] = int(value)
                elif 'gain' in key.lower():
                    self.arduino_status['gain'] = int(value)
                elif 'adcReference' in key or 'reference' in key.lower():
                    # Map Arduino reference names back to our format
                    ref_map = {
                        'INTERNAL1V2': '1.2',
                        'VDD': 'vdd',
                        '1V2': '1.2',
                        '3V3': 'vdd'
                    }
                    self.arduino_status['reference'] = ref_map.get(value, value.lower())
        except Exception as e:
            # Silently ignore parse errors
            pass
