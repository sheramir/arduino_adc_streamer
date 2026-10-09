"""Causal median-of-3 blip filtering for PZT ADC voltage columns during binary ingest.

Rejects isolated single-sample spikes the same way the 555/PZR firmware's own
``pzr_median3`` rejects isolated one-pair spikes on its resistance readings:
for three consecutive raw samples the middle-ranked value is kept, so a lone
outlier is always out-voted by its two neighbours. Runs after PZT ghost
removal, on the same PZT voltage columns identified by
``PztGhostRemovalMixin._get_pzt_ghost_groups`` (RS/555 resistance columns are
never sampled waveforms and must not be median-filtered).

Each column's filtered value only ever depends on its own two immediately
preceding raw samples, so the state carried across blocks is two rows per
filtered column, not a growing history.
"""

from __future__ import annotations

import numpy as np


class PztBlipFilterMixin:
    """Owns per-column causal median-of-3 state for PZT ADC voltage columns."""

    def _init_pzt_blip_filter_state(self) -> None:
        self._pzt_blip_filter_history: np.ndarray | None = None  # shape (2, len(columns))
        self._pzt_blip_filter_history_len = 0
        self._pzt_blip_column_indices = None

    def begin_pzt_blip_filter_capture(self) -> None:
        """Drop carried-over history so a new capture never blends across the boundary."""
        self._pzt_blip_filter_history = None
        self._pzt_blip_filter_history_len = 0

    def prepare_pzt_blip_filter_blocks(
        self, block_data: np.ndarray, archive_data: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Filter PZT voltage columns once and mirror the result into both outputs.

        ``block_data`` and ``archive_data`` carry identical values in the PZT
        voltage columns (only RS/other slots may differ between the display
        and archive representations), so the stateful filter must run exactly
        once per block on those columns; running it twice would consume the
        two-row carry-over history twice for what is the same signal.
        """
        block = np.asarray(block_data, dtype=np.float32).copy()
        archive = np.asarray(archive_data, dtype=np.float32).copy()
        if block.ndim != 2 or block.shape[0] == 0:
            return block, archive

        width = block.shape[1]
        column_indices = self._pzt_blip_column_indices
        if column_indices is None:
            columns = sorted({column for group in self._get_pzt_ghost_groups(width) for column in group})
            if not columns:
                return block, archive
            column_indices = np.asarray(columns, dtype=np.int32)
        filtered = self._pzt_blip_filtered_columns(block[:, column_indices])
        block[:, column_indices] = filtered
        if archive.ndim == 2 and archive.shape[1] == width:
            archive[:, column_indices] = filtered
        return block, archive

    def _pzt_blip_filtered_columns(self, raw_columns: np.ndarray) -> np.ndarray:
        """Median-of-3 filter every column of ``raw_columns`` (rows = samples)."""
        column_count = raw_columns.shape[1]
        history = self._pzt_blip_filter_history
        history_len = self._pzt_blip_filter_history_len
        if history is None or history.shape[1] != column_count:
            history = np.zeros((2, column_count), dtype=np.float32)
            history_len = 0

        prefix = history[2 - history_len:] if history_len else history[:0]
        extended = np.concatenate([prefix, raw_columns], axis=0)

        if extended.shape[0] >= 3:
            a, b, c = extended[:-2], extended[1:-1], extended[2:]
            # Sum-minus-max-minus-min selects the middle-ranked value without
            # a sort, matching np.median's exact-middle-element output for 3
            # samples.
            median = (
                a + b + c
                - np.maximum(np.maximum(a, b), c)
                - np.minimum(np.minimum(a, b), c)
            )
            filtered = raw_columns.copy()
            offset = 2 - history_len
            filtered[offset:] = median
        else:
            # Not enough samples (across this block + carried history) for a
            # single full window yet; pass raw values through unfiltered.
            filtered = raw_columns.copy()

        tail = extended[-2:]
        if tail.shape[0] < 2:
            padded = np.zeros((2, column_count), dtype=np.float32)
            padded[2 - tail.shape[0]:] = tail
            self._pzt_blip_filter_history = padded
        else:
            self._pzt_blip_filter_history = tail.copy()
        self._pzt_blip_filter_history_len = min(2, extended.shape[0])

        return filtered
