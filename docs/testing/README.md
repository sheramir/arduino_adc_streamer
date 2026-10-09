# testing

Evidence from tests and benchmarks. Test procedures and instrumentation designs live in [`../architecture/firmware/`](../architecture/firmware/) and [`../plans/testing/`](../plans/testing/).

- `results/testboard-7953/` — noise, channel-quality, Vmid, battery/charger, and GUI repair results, plus `gui-noise-analysis/` (the full analysis package: summary, per-run folders with JSON, CSV, PNG, PDF, and HTML).
- `benchmarks/testboard-7953/` — firmware throughput and USB/LPSPI/profiling benchmark comparisons and results.
- `datasets/testboard-7953/` — machine-readable GUI replay results (JSON).

The `gui-noise-analysis/` package is kept intact so its relative links and generated artifacts stay valid. Some generated `comparison.json` files record absolute paths from the time of the run; they are historical provenance and were not rewritten.
