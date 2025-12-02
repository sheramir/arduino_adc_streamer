"""
Buffer optimization utilities for ADC Streamer.

This module provides helper functions for calculating optimal buffer sizes
and validating buffer configurations based on hardware constraints.
"""

from config_constants import MAX_SAMPLES_BUFFER, TARGET_LATENCY_SEC, USB_PACKET_SIZE, BAUD_RATE


def calculate_optimal_sweeps_per_block(channel_count, repeat_count, baud_rate=BAUD_RATE, 
                                       target_latency=TARGET_LATENCY_SEC, max_candidates=5):
    """
    Compute optimal sweeps_per_block candidates based on configuration and constraints.
    
    Args:
        channel_count: Number of channels in the sweep sequence
        repeat_count: Number of repeats per channel
        baud_rate: Serial baud rate (default from BAUD_RATE constant)
        target_latency: Target maximum latency in seconds (default from TARGET_LATENCY_SEC)
        max_candidates: Maximum number of candidates to return
    
    Returns:
        List of tuples: [(sweeps_per_block, metrics_dict), ...]
        Sorted from largest to smallest sweeps_per_block.
        
        metrics_dict contains:
            - 'total_samples': Total samples in the block
            - 'block_bytes': Total block size in bytes
            - 'transmit_time_ms': Estimated transmission time (ms)
            - 'usb_efficiency': How well block aligns with USB packets (0-1, higher is better)
            - 'latency_ratio': Ratio of transmit time to target latency
    """
    if channel_count <= 0 or repeat_count <= 0:
        return [(1, {'total_samples': 0, 'block_bytes': 0, 'transmit_time_ms': 0, 
                     'usb_efficiency': 0, 'latency_ratio': 0})]
    
    samples_per_sweep = channel_count * repeat_count
    
    # Binary protocol: [0xAA][0x55][countL][countH] + samples(uint16 LE) + [avgTimeL][avgTimeH]
    # Header: 4 bytes, Sample: 2 bytes each, Footer: 2 bytes
    HEADER_BYTES = 4
    BYTES_PER_SAMPLE = 2
    FOOTER_BYTES = 2
    
    # Serial framing overhead: 1 start bit + 8 data bits + 1 stop bit = 10 bits per byte
    BITS_PER_BYTE = 10
    
    candidates = []
    
    # Generate candidate sweep counts (1 to a reasonable upper limit)
    # Upper limit based on either max buffer size or max reasonable latency
    max_sweeps_by_buffer = MAX_SAMPLES_BUFFER // samples_per_sweep if samples_per_sweep > 0 else 1000
    max_sweeps_by_latency = 10000  # Conservative upper limit for search
    
    max_sweeps_to_test = min(max_sweeps_by_buffer, max_sweeps_by_latency)
    
    # Test a range of sweep counts
    for sweeps in range(1, max_sweeps_to_test + 1):
        total_samples = sweeps * samples_per_sweep
        
        # Check buffer capacity constraint
        if total_samples > MAX_SAMPLES_BUFFER:
            break  # No point testing larger values
        
        # Calculate block size in bytes
        block_bytes = HEADER_BYTES + (total_samples * BYTES_PER_SAMPLE) + FOOTER_BYTES
        
        # Calculate transmission time
        # Time = (bytes * bits_per_byte) / baud_rate
        transmit_time_sec = (block_bytes * BITS_PER_BYTE) / baud_rate
        transmit_time_ms = transmit_time_sec * 1000.0
        
        # Check latency constraint
        if transmit_time_sec > target_latency:
            continue  # Skip candidates that exceed target latency
        
        # Calculate USB packet efficiency
        # How close is block_bytes to a multiple of USB_PACKET_SIZE?
        packets_needed = (block_bytes + USB_PACKET_SIZE - 1) // USB_PACKET_SIZE
        ideal_size = packets_needed * USB_PACKET_SIZE
        wasted_bytes = ideal_size - block_bytes
        usb_efficiency = 1.0 - (wasted_bytes / USB_PACKET_SIZE)
        
        # Calculate latency ratio (how much of target latency is used)
        latency_ratio = transmit_time_sec / target_latency if target_latency > 0 else 0
        
        # Store candidate with metrics
        metrics = {
            'total_samples': total_samples,
            'block_bytes': block_bytes,
            'transmit_time_ms': transmit_time_ms,
            'usb_efficiency': usb_efficiency,
            'latency_ratio': latency_ratio,
            'packets_needed': packets_needed,
            'wasted_bytes': wasted_bytes
        }
        
        candidates.append((sweeps, metrics))
    
    if not candidates:
        # Fallback: return minimum viable option
        total_samples = samples_per_sweep
        block_bytes = HEADER_BYTES + (total_samples * BYTES_PER_SAMPLE) + FOOTER_BYTES
        transmit_time_ms = (block_bytes * BITS_PER_BYTE) / baud_rate * 1000.0
        metrics = {
            'total_samples': total_samples,
            'block_bytes': block_bytes,
            'transmit_time_ms': transmit_time_ms,
            'usb_efficiency': 1.0 - ((USB_PACKET_SIZE - (block_bytes % USB_PACKET_SIZE)) / USB_PACKET_SIZE),
            'latency_ratio': transmit_time_ms / (target_latency * 1000.0) if target_latency > 0 else 0
        }
        return [(1, metrics)]
    
    # Score and sort candidates
    # Prefer: high USB efficiency, high latency utilization (but < 1.0), larger blocks
    scored_candidates = []
    for sweeps, metrics in candidates:
        # Scoring formula weights:
        # - USB efficiency (0-1): 40% weight
        # - Latency utilization (prefer 0.7-0.9 range): 30% weight
        # - Block size (normalized): 30% weight
        
        usb_score = metrics['usb_efficiency']
        
        # Latency score: prefer values between 0.7 and 0.9 of target
        latency_util = metrics['latency_ratio']
        if latency_util <= 0.7:
            latency_score = latency_util / 0.7  # 0 to 1
        elif latency_util <= 0.9:
            latency_score = 1.0  # Optimal range
        else:
            latency_score = 1.0 - ((latency_util - 0.9) / 0.1)  # Degrade as approaching 1.0
        latency_score = max(0, min(1.0, latency_score))
        
        # Size score: normalize by maximum candidate size
        max_samples = max(c[1]['total_samples'] for c in candidates)
        size_score = metrics['total_samples'] / max_samples if max_samples > 0 else 0
        
        # Combined score
        score = (0.4 * usb_score) + (0.3 * latency_score) + (0.3 * size_score)
        
        scored_candidates.append((score, sweeps, metrics))
    
    # Sort by score (descending), then by sweeps (descending)
    scored_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    
    # Return top candidates, sorted by sweeps_per_block (largest first)
    top_candidates = [(sweeps, metrics) for score, sweeps, metrics in scored_candidates[:max_candidates]]
    top_candidates.sort(key=lambda x: x[0], reverse=True)
    
    return top_candidates


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
