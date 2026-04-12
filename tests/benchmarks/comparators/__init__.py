"""External classifier comparators for side-by-side benchmarks.

Each comparator module exposes:
  - A mapping from the external tool's entity vocabulary to ours
    (both ``STRICT`` and ``AGGRESSIVE`` variants)
  - A ``run_<tool>_on_column`` / ``run_<tool>_on_corpus`` function that
    invokes the external engine and returns results in our vocabulary
  - A ``compute_column_comparison`` helper for per-column agreement stats

The live-engine imports are deferred so unit tests of the mapping logic
can run without the optional ``[bench-compare]`` / ``[bench-compare-cloud]``
extras being installed.
"""
