"""Capture strategy selected once from the active mode's JSON contract."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamingPolicy:
    pipeline: str = 'legacy_blocks'
    render_interval_ms: int = 200

    @property
    def batched(self):
        return self.pipeline == 'batched_timed_sweeps'


def streaming_policy(mode):
    return StreamingPolicy(**mode.definition.get('streaming', {}))


def validate_streaming(mode):
    definition = mode.get('streaming', {})
    if set(definition) - {'pipeline', 'render_interval_ms'}:
        raise ValueError('Unknown streaming policy field')
    policy = StreamingPolicy(**definition)
    if policy.pipeline not in ('legacy_blocks', 'batched_timed_sweeps'):
        raise ValueError('Unknown streaming pipeline')
    if type(policy.render_interval_ms) is not int or not 1 <= policy.render_interval_ms <= 1000:
        raise ValueError('Invalid streaming render interval')
    if policy.batched:
        if mode['adapters']['acquisition'] != 'multi_array' or mode['adapters']['frame'] not in ('ads7953_u16_timed', 'adc_u16_timed'):
            raise ValueError('Batched timed sweeps require lane-aware timed-u16 acquisition')
        for name in ('samples_per_channel', 'sweeps_per_block'):
            param = mode['parameters'].get(name, {})
            if param.get('policy') != 'fixed' or param.get('default') != 1:
                raise ValueError('Batched timed sweeps require one emitted result per route and one sweep per frame')
