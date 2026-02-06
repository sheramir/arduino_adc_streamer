#!/usr/bin/env python3
"""
Test script for buffer optimization helper functions.
Demonstrates the calculation of optimal sweeps_per_block values.
"""

from config_constants import MAX_SAMPLES_BUFFER, TARGET_LATENCY_SEC, BAUD_RATE
from config.buffer_utils import calculate_optimal_sweeps_per_block, validate_and_limit_sweeps_per_block

def print_candidates(channel_count, repeat_count, baud_rate=BAUD_RATE):
    """Print detailed information about candidate sweeps_per_block values."""
    print(f"\n{'='*80}")
    print(f"Configuration: {channel_count} channels × {repeat_count} repeats = {channel_count * repeat_count} samples/sweep")
    print(f"Baud rate: {baud_rate} bps, Target latency: {TARGET_LATENCY_SEC*1000:.0f}ms")
    print(f"Max buffer capacity: {MAX_SAMPLES_BUFFER} samples")
    print(f"{'='*80}")
    
    candidates = calculate_optimal_sweeps_per_block(
        channel_count, repeat_count, baud_rate, TARGET_LATENCY_SEC, max_candidates=5
    )
    
    if not candidates:
        print("No valid candidates found!")
        return
    
    print(f"\nFound {len(candidates)} optimal candidates:\n")
    
    for i, (sweeps, metrics) in enumerate(candidates, 1):
        print(f"Candidate #{i}:")
        print(f"  Sweeps per block: {sweeps}")
        print(f"  Total samples:    {metrics['total_samples']}")
        print(f"  Block size:       {metrics['block_bytes']} bytes ({metrics['packets_needed']} USB packets, {metrics['wasted_bytes']} bytes wasted)")
        print(f"  Transmit time:    {metrics['transmit_time_ms']:.2f}ms ({metrics['latency_ratio']*100:.1f}% of target)")
        print(f"  USB efficiency:   {metrics['usb_efficiency']*100:.1f}%")
        print()

def test_validation():
    """Test the validation function."""
    print(f"\n{'='*80}")
    print("Testing validation and limiting:")
    print(f"{'='*80}\n")
    
    test_cases = [
        (5, 10, 1000),   # channels, repeats, requested_sweeps
        (8, 5, 1000),
        (10, 10, 1000),
        (4, 8, 2000),
    ]
    
    for channels, repeats, requested in test_cases:
        samples_per_sweep = channels * repeats
        validated = validate_and_limit_sweeps_per_block(requested, channels, repeats)
        max_samples = validated * samples_per_sweep
        
        print(f"Config: {channels} ch × {repeats} rpt = {samples_per_sweep} samples/sweep")
        print(f"  Requested: {requested} sweeps → {requested * samples_per_sweep} samples")
        print(f"  Validated: {validated} sweeps → {max_samples} samples")
        
        if validated != requested:
            print(f"  ⚠️  LIMITED (exceeds {MAX_SAMPLES_BUFFER} sample buffer)")
        else:
            print(f"  ✓ OK")
        print()

if __name__ == "__main__":
    print("\n" + "="*80)
    print("Buffer Optimization Test Suite")
    print("="*80)
    
    # Test common configurations
    print_candidates(channel_count=5, repeat_count=10)   # 50 samples/sweep
    print_candidates(channel_count=8, repeat_count=5)    # 40 samples/sweep
    print_candidates(channel_count=4, repeat_count=8)    # 32 samples/sweep
    print_candidates(channel_count=10, repeat_count=10)  # 100 samples/sweep
    
    # Test validation
    test_validation()
    
    print(f"{'='*80}")
    print("Test complete!")
    print(f"{'='*80}\n")
