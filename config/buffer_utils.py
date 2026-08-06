"""
Buffer utilities for ADC Streamer.

Validates buffer configurations against hardware capacity constraints.
"""

from constants.serial import MAX_SAMPLES_BUFFER


def validate_and_limit_sweeps_per_block(sweeps_per_block, channel_count, repeat_count):
    """
    Validate sweeps_per_block and limit to maximum allowed by buffer capacity.
    
    Args:
        sweeps_per_block: Requested sweeps per block
        channel_count: Number of channels in sweep sequence
        repeat_count: Number of repeats per channel
    
    Returns:
        Valid sweeps_per_block value (limited if necessary)
    """
    if channel_count <= 0 or repeat_count <= 0:
        return max(1, sweeps_per_block)
    
    samples_per_sweep = channel_count * repeat_count
    max_allowed_sweeps = MAX_SAMPLES_BUFFER // samples_per_sweep
    
    if sweeps_per_block > max_allowed_sweeps:
        return max(1, max_allowed_sweeps)
    
    return max(1, sweeps_per_block)
