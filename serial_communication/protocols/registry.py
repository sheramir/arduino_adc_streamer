"""Protocol algorithms are Python; board parameters and adapter selection are JSON."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class ProtocolAdapter:
    id: str
    implementation: str

    def configure(self, service, request):
        return getattr(service, self.implementation)(request)

    def stopped_status(self, session):
        # This ASCII status contract is specific to this protocol, not the GUI.
        return session.read_testboard_status() if self.id == 'ads7953' else None

    def capture_engine(self, status):
        return getattr(status, 'testboard_engine', None) if self.id == 'ads7953' else None


PROTOCOL_ADAPTERS = {
    name: ProtocolAdapter(name, '_send_legacy_config')
    for name in ('legacy_adc', 'legacy_555', 'array_dual')
}
PROTOCOL_ADAPTERS['ads7953'] = ProtocolAdapter('ads7953', '_send_testboard_config')


def protocol_adapter(context):
    return PROTOCOL_ADAPTERS[context.mode.definition['adapters']['protocol']]


# These are established codec families, not board identity tests. The stream
# reader owns shared framing; downstream processors own mode-specific payloads.
@dataclass(frozen=True)
class TimedU16Codec:
    id: str
    sample_bytes: int = 2

    def decode(self, payload):
        return np.frombuffer(payload, dtype='<u2')


FRAME_ADAPTERS = {name: TimedU16Codec(name) for name in
                  ('adc_u16_timed', 'ads7953_u16_timed', 'timer_555', 'pzt_rs_u16')}
